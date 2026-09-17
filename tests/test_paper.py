"""纸面账本:成交、换月、涨跌停顺延、盯市与权益对账(合成数据,不联网)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cta.instruments.specs import load_instruments
from cta.paper.book import PaperBook


def _dq(rows: dict[str, tuple[float, float, float]]) -> pd.DataFrame:
    """contract -> (open, settle, prev_settle)。"""
    return pd.DataFrame({c: {"open": v[0], "settle": v[1], "prev_settle": v[2]} for c, v in rows.items()}).T


def test_fill_mark_and_roll_reconcile(tmp_path: Path) -> None:
    specs = load_instruments()
    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    cu = specs["CU"]
    d1 = pd.Timestamp("2026-09-10")
    orders = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2610",
                "target_lots": 2.0,
                "held_contract": None,
                "held_lots": 0.0,
                "roll_required": False,
                "delta_lots": 2.0,
            }
        ]
    )
    q1 = _dq({"CU2610": (70000.0, 70500.0, 69800.0)})
    fills = book.fill_orders(orders, q1, specs, d1, slippage_ticks=1.0)
    assert fills.iloc[0]["status"] == "filled" and fills.iloc[0]["price"] == 70000.0 + cu.tick
    pnl = book.mark_to_market(q1, specs, d1)
    fee = cu.fee(70000.0, 2)
    expected = 1_000_000.0 - fee + 2 * (70500.0 - (70000.0 + cu.tick)) * cu.multiplier
    assert np.isclose(book.state.equity, expected) and np.isclose(pnl["CU"], 2 * (70500.0 - 70010.0) * 5)
    # 次日换月:平 CU2610、开 CU2611 各 2 手;开盘价与结算价不同
    d2 = pd.Timestamp("2026-09-11")
    orders2 = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2611",
                "target_lots": 2.0,
                "held_contract": "CU2610",
                "held_lots": 2.0,
                "roll_required": True,
                "delta_lots": 2.0,
            }
        ]
    )
    q2 = _dq({"CU2610": (70600.0, 70400.0, 70500.0), "CU2611": (70900.0, 70800.0, 70700.0)})
    f2 = book.fill_orders(orders2, q2, specs, d2, slippage_ticks=1.0)
    assert len(f2) == 2 and set(f2["contract"]) == {"CU2610", "CU2611"}
    eq_before_mark = book.state.equity
    book.mark_to_market(q2, specs, d2)
    close_pnl = 2 * ((70600.0 - cu.tick) - 70500.0) * 5  # 平旧合约:开盘价−1跳 相对上日结算
    open_pnl = 2 * (70800.0 - (70900.0 + cu.tick)) * 5  # 新合约:结算 相对 成交价
    fees = cu.fee(70600.0, 2) + cu.fee(70900.0, 2)
    assert np.isclose(book.state.equity, expected + close_pnl + open_pnl - fees)
    assert book.state.positions["CU"].contract == "CU2611" and book.state.positions["CU"].lots == 2.0
    assert eq_before_mark == expected + close_pnl - fees  # 盯市前:平仓盈亏已实现,新仓未盯市
    # 涨停开盘:买单顺延,不成交
    d3 = pd.Timestamp("2026-09-14")
    orders3 = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2611",
                "target_lots": 3.0,
                "held_contract": "CU2611",
                "held_lots": 2.0,
                "roll_required": False,
                "delta_lots": 1.0,
            }
        ]
    )
    q3 = _dq({"CU2611": (70800.0 * (1 + cu.limit_pct), 71000.0, 70800.0)})
    f3 = book.fill_orders(orders3, q3, specs, d3, slippage_ticks=1.0)
    assert f3.iloc[0]["status"] == "limit_locked" and book.state.positions["CU"].lots == 2.0
    book.mark_to_market(q3, specs, d3)
    book.append_equity(d3, {}, book.margin_used(q3, specs))
    eq = pd.read_csv(tmp_path / "equity.csv")
    assert len(eq) == 1 and eq.iloc[0]["n_positions"] == 1
    # 状态持久化往返
    book.save()
    book2 = PaperBook(tmp_path)
    assert book2.state.equity == book.state.equity and book2.state.positions["CU"].ref_price == 71000.0


def test_settlement_gate() -> None:
    from cta.paper.runner import settlement_published

    d = pd.Timestamp("2026-09-17")
    assert not settlement_published(d, now=pd.Timestamp("2026-09-17 11:21"))
    assert settlement_published(d, now=pd.Timestamp("2026-09-17 16:30"))
    assert settlement_published(d, now=pd.Timestamp("2026-09-18 09:00"))
    assert not settlement_published(pd.Timestamp("2026-09-18"), now=pd.Timestamp("2026-09-17 23:00"))


def test_intraday_snapshot_is_rejected() -> None:
    import gzip
    import json
    from pathlib import Path

    import pytest

    from cta.data.exchanges import shfe
    from cta.data.exchanges.base import NotFinalError

    fx = Path("tests/fixtures/exchanges/shfe")
    raw_files = sorted(fx.glob("*kx*")) or sorted(fx.glob("*quotes*"))
    assert raw_files, "需要 shfe quotes fixture"
    f = raw_files[0]
    if f.suffix == ".gz":
        with gzip.open(f, "rb") as fh:
            raw = fh.read()
    else:
        raw = f.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    for r in data.get("o_curinstrument", []):
        r["SETTLEMENTPRICE"] = ""  # 模拟盘中快照:结算价全空
    with pytest.raises(NotFinalError):
        shfe.parse_quotes(json.dumps(data).encode("utf-8"), pd.Timestamp("2026-09-11"))
