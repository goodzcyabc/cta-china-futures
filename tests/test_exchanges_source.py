"""ExchangeSource / StitchedSource:用合成的交易所落盘数据检查装配逻辑(主力候选取前一日最大持仓、元数据、拼接)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cta.data.exchanges.base import Store
from cta.data.exchanges.calendar import TradingCalendar
from cta.data.exchanges.source import ExchangeSource, StitchedSource
from cta.instruments.specs import load_instruments


def _day(date: str, rows: list[tuple[str, float, float, float]]) -> pd.DataFrame:
    """rows: (contract, close, volume, oi)。"""
    return pd.DataFrame(
        {
            "date": date,
            "exchange": "SHFE",
            "symbol": "CU",
            "contract": [r[0] for r in rows],
            "open": [r[1] for r in rows],
            "high": [r[1] * 1.01 for r in rows],
            "low": [r[1] * 0.99 for r in rows],
            "close": [r[1] for r in rows],
            "settle": [r[1] * 1.001 for r in rows],
            "prev_settle": [r[1] * 0.999 for r in rows],
            "volume": [r[2] for r in rows],
            "open_interest": [r[3] for r in rows],
            "turnover": [r[1] * r[2] * 5 for r in rows],
        }
    )


def _make_store(tmp: Path) -> Store:
    st = Store(tmp)
    days = pd.bdate_range("2026-06-08", periods=6)
    for i, d in enumerate(days):
        # 前 3 天 CU2607 持仓最大,之后 CU2608 最大;CU2609 无成交
        oi7, oi8 = (100 - 10 * i, 50 + 15 * i)
        st.write_day(
            "SHFE",
            "quotes",
            d,
            _day(
                str(d.date()),
                [("cu2607", 100 + i, 1000, oi7), ("cu2608", 101 + i, 900, oi8), ("cu2609", 102.0 + i, 0, 5)],
            ).assign(contract=["CU2607", "CU2608", "CU2609"]),
        )
    return st


def test_exchange_source_assembly(tmp_path: Path) -> None:
    st = _make_store(tmp_path)
    src = ExchangeSource(
        st,
        exchanges=("SHFE",),
        specs=load_instruments(),
        calendar=TradingCalendar(st, holidays=pd.DatetimeIndex([])),
    )
    assert src.symbols() == ["CU"]
    c = src.contracts("CU")
    assert list(c.index.names) == ["contract", "date"] and "settle" in c.columns
    # 无成交合约(volume=0)的 OHLC 落盘为 NaN,装配时用结算价填充
    assert np.isclose(c.loc[("CU2609", pd.Timestamp("2026-06-08")), "close"], 102.0 * 1.001)
    dm = src.dominant_map()
    dm = dm[dm.symbol == "CU"].set_index("date")["contract"]
    # 第 4 天(i=3)CU2608 持仓 95 > CU2607 70,但候选用前一日 → 第 4 天仍是 CU2607,第 5 天起 CU2608
    days = pd.bdate_range("2026-06-08", periods=6)
    assert dm[days[3]] == "CU2607" and dm[days[4]] == "CU2608"
    meta = src.contract_meta()
    assert meta.loc["CU2607", "maturity_date"] == pd.Timestamp("2026-07-15")
    assert meta.loc["CU2607", "multiplier"] == 5 and meta.loc["CU2607", "listed_date"] == days[0]
    assert src.manifest()["coverage"].startswith("SHFE:6:")


def test_stitched_source_concats_on_cutover(tmp_path: Path) -> None:
    st = _make_store(tmp_path)
    ex = ExchangeSource(
        st,
        exchanges=("SHFE",),
        specs=load_instruments(),
        calendar=TradingCalendar(st, holidays=pd.DatetimeIndex([])),
    )

    class Prim:
        def symbols(self) -> list[str]:
            return ["CU"]

        def contracts(self, symbol: str) -> pd.DataFrame:
            idx = pd.MultiIndex.from_product(
                [["CU2607"], pd.bdate_range("2026-06-01", periods=6)], names=["contract", "date"]
            )
            return pd.DataFrame(
                {
                    "open": 99.0,
                    "high": 100.0,
                    "low": 98.0,
                    "close": 99.5,
                    "volume": 10.0,
                    "open_interest": 100.0,
                },
                index=idx,
            )

        def dominant_map(self) -> pd.DataFrame:
            return pd.DataFrame(
                {"date": pd.bdate_range("2026-06-01", periods=6), "symbol": "CU", "contract": "CU2607"}
            )

        def contract_meta(self) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "symbol": ["CU"],
                    "exchange": ["SHFE"],
                    "listed_date": [pd.Timestamp("2025-07-15")],
                    "de_listed_date": [pd.Timestamp("2026-07-15")],
                    "maturity_date": [pd.Timestamp("2026-07-15")],
                    "margin_rate": [0.1],
                    "multiplier": [5.0],
                },
                index=pd.Index(["CU2607"], name="contract"),
            )

        def dominant_daily(self, symbol: str) -> pd.DataFrame:
            return pd.DataFrame()

        def shibor(self) -> pd.DataFrame:
            return pd.DataFrame()

        def manifest(self) -> dict[str, str]:
            return {"root": "prim"}

    src = StitchedSource(
        Prim(), ex, pd.Timestamp("2026-06-08"), official_settle=False
    )  # 6-08 及之前用 primary(6-08 在 primary 无数据);本测试只看拼接,结算价覆盖见 test_settle_overlay
    c = src.contracts("CU")
    dates = c.index.get_level_values("date")
    assert (
        dates.min() == pd.Timestamp("2026-06-01")
        and dates.max() == pd.bdate_range("2026-06-08", periods=6)[-1]
    )
    assert (dates <= pd.Timestamp("2026-06-08")).sum() == 6 and "settle" in c.columns  # 列取并集
    prim_part = c[dates <= pd.Timestamp("2026-06-08")]
    assert (
        prim_part["settle"] == prim_part["close"]
    ).all()  # legacy 口径(official_settle=False):米筐段用收盘价代结算
    sec_part = c[dates > pd.Timestamp("2026-06-08")]
    assert (sec_part["settle"] != sec_part["close"]).any()  # 交易所段:官方结算价保留
    meta = src.contract_meta()
    assert {"CU2607", "CU2608", "CU2609"} <= set(meta.index) and meta.loc[
        "CU2607", "listed_date"
    ] == pd.Timestamp("2025-07-15")
    assert src.manifest()["cutover"] == "2026-06-08"
    # primary 没有的品种:全程用 secondary(不截断到切换日之后)
    st2 = _make_store(tmp_path / "b")
    ex2 = ExchangeSource(
        st2,
        exchanges=("SHFE",),
        specs=load_instruments(),
        calendar=TradingCalendar(st2, holidays=pd.DatetimeIndex([])),
    )

    class PrimNone(Prim):
        def symbols(self) -> list[str]:
            return []

        def dominant_map(self) -> pd.DataFrame:
            return pd.DataFrame(columns=["date", "symbol", "contract"])

    src2 = StitchedSource(PrimNone(), ex2, pd.Timestamp("2026-06-10"))
    c2 = src2.contracts("CU")
    assert c2.index.get_level_values("date").min() == pd.Timestamp("2026-06-08")
    assert (src2.dominant_map()["date"].min()) == pd.Timestamp("2026-06-08")
