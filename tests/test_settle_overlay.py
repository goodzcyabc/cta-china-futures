"""官方结算价覆盖(design_log 17.6 第 5 项):米筐段用交易所逐合约结算价覆盖、缺失不回退、面板标记覆盖率、official 模式缺失即报错。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from cta.config import DataCfg, load_config
from cta.data.exchanges.source import StitchedSource
from cta.instruments.specs import load_instruments
from cta.pipeline import build_panels

DATES = pd.bdate_range("2026-06-01", periods=6)
CUTOVER = pd.Timestamp("2026-06-30")


class _Prim:  # 米筐式:无结算价
    def symbols(self) -> list[str]:
        return ["CU"]

    def contracts(self, symbol: str) -> pd.DataFrame:
        idx = pd.MultiIndex.from_product([["CU2607"], DATES], names=["contract", "date"])
        return pd.DataFrame(
            {"open": 99.0, "high": 100.0, "low": 98.0, "close": 99.5, "volume": 10.0, "open_interest": 100.0},
            index=idx,
        )

    def dominant_map(self) -> pd.DataFrame:
        return pd.DataFrame({"date": DATES, "symbol": "CU", "contract": "CU2607"})

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

    def manifest(self) -> dict[str, str]:
        return {"prim": "x"}

    def receipts(self) -> pd.DataFrame:
        return pd.DataFrame()

    def reg_events(self) -> pd.DataFrame:
        return pd.DataFrame()


class _Sec:  # 交易所式:有官方结算价,但只覆盖部分日期
    def __init__(self, n_days: int):
        self.n = n_days

    def symbols(self) -> list[str]:
        return ["CU"]

    def quotes(self) -> pd.DataFrame:
        d = DATES[: self.n]
        return pd.DataFrame(
            {
                "contract": "CU2607",
                "date": d,
                "settle": 100.0 + np.arange(len(d)),
                "prev_settle": 99.0 + np.arange(len(d)),
            }
        )

    def contracts(self, symbol: str) -> pd.DataFrame:
        idx = pd.MultiIndex.from_product([["CU2607"], DATES[:0]], names=["contract", "date"])
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "open_interest"], index=idx)

    def dominant_map(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["date", "symbol", "contract"])

    def contract_meta(self) -> pd.DataFrame:
        return _Prim().contract_meta().iloc[:0]

    def manifest(self) -> dict[str, str]:
        return {"sec": "y"}

    def receipts(self) -> pd.DataFrame:
        return pd.DataFrame()

    def reg_events(self) -> pd.DataFrame:
        return pd.DataFrame()


def _cfg(settle: str) -> Any:
    cfg = load_config()
    return cfg.model_copy(
        update={
            "universe": cfg.universe.model_copy(update={"symbols": ["CU"]}),
            "data": DataCfg(settle=settle),  # type: ignore[arg-type]
        }
    )


def test_official_overlay_marks_missing_and_never_falls_back_to_close() -> None:
    src = StitchedSource(_Prim(), _Sec(4), CUTOVER, official_settle=True)  # type: ignore[arg-type]
    c = src.contracts("CU")
    assert c["settle_source"].tolist() == ["official"] * 4 + ["missing"] * 2
    assert c["settle"].iloc[0] == 100.0 and np.isnan(c["settle"].iloc[-1])  # 缺失保留 NaN,不是 close
    assert c["prev_settle"].iloc[1] == 100.0
    legacy = StitchedSource(_Prim(), _Sec(4), CUTOVER, official_settle=False)  # type: ignore[arg-type]
    cl = legacy.contracts("CU")
    assert (cl["settle"] == cl["close"]).all() and (cl["settle_source"] == "close_proxy").all()
    assert src.manifest()["settle"] == "official" and legacy.manifest()["settle"] == "close_proxy"


def test_build_panels_official_mode_refuses_gaps_and_reports_coverage() -> None:
    specs = load_instruments()
    with pytest.raises(ValueError, match="没有交易所官方结算价"):
        build_panels(StitchedSource(_Prim(), _Sec(4), CUTOVER), _cfg("official"), specs)  # type: ignore[arg-type]
    full = build_panels(StitchedSource(_Prim(), _Sec(6), CUTOVER), _cfg("official"), specs)  # type: ignore[arg-type]
    assert full["CU"].frame["settle_official"].mean() == 1.0
    assert full["CU"].frame["settle"].tolist() == [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    legacy = build_panels(
        StitchedSource(_Prim(), _Sec(4), CUTOVER, official_settle=False),  # type: ignore[arg-type]
        _cfg("vendor_close"),
        specs,
    )
    assert legacy["CU"].frame["settle_official"].mean() == 0.0
    assert (legacy["CU"].frame["settle"] == legacy["CU"].frame["close"]).all()
