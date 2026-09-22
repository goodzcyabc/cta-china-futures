"""共用执行模块:目标手数规划(三步顺序、保证金缩减、手数带)与合约级成交状态机(预检、换月同进退、盯市)。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cta.execution import ledger
from cta.execution.plan import SymbolInputs, band_adjusted, plan_lots
from cta.instruments.specs import load_instruments


def _inp(
    exp: float, px: float = 70000.0, mult: float = 5.0, mr: float = 0.10, held: float = 0.0
) -> SymbolInputs:
    return SymbolInputs(exp, px, mult, mr, held)


def test_plan_rounds_then_scales_then_bands() -> None:
    eq = 1_000_000.0
    # ① 取整:0.5 × 1e6 / (70000×5) = 1.43 → 1 手
    r = plan_lots({"CU": _inp(0.5)}, eq, lot_band=0.3, max_margin_usage=0.4)
    assert r.lots == {"CU": 1.0} and not r.scaled
    # ② 保证金:10 倍名义 → 29 手 × 70000 × 5 × 10% = 101.5 万 > 40 万 → 等比缩到 11 手(trunc)
    r = plan_lots({"CU": _inp(10.0)}, eq, lot_band=0.3, max_margin_usage=0.4)
    assert r.scaled and r.lots["CU"] == 11.0 and r.margin_after <= 0.4 * eq < r.margin_before
    # ③ 手数带:持 10 手、目标 11 手,|1| < 0.3×10 → 不动;目标 0 不受限
    assert band_adjusted(11.0, 10.0, 0.3) == 10.0 and band_adjusted(0.0, 10.0, 0.3) == 0.0
    r = plan_lots({"CU": _inp(3.85, held=10.0)}, eq, lot_band=0.3, max_margin_usage=0.4)
    assert r.lots["CU"] == 10.0
    # 无参考价:保持持仓,且不计入保证金
    r = plan_lots({"CU": _inp(0.5, px=float("nan"), held=3.0)}, eq, lot_band=0.3, max_margin_usage=0.4)
    assert r.lots["CU"] == 3.0 and r.margin_after == 0.0


def test_leg_block_rules() -> None:
    specs = load_instruments()
    cu = specs["CU"]
    assert ledger.leg_block(None, 1.0, cu) == "no_quote"
    assert ledger.leg_block(ledger.Quote(float("nan"), 70000.0, 70000.0), 1.0, cu) == "no_quote"
    up = 70000.0 * (1 + cu.limit_pct)
    assert ledger.leg_block(ledger.Quote(up, up, 70000.0), 1.0, cu) == "limit_locked"  # 买单撞涨停
    assert ledger.leg_block(ledger.Quote(up, up, 70000.0), -1.0, cu) is None  # 卖单不受涨停影响
    assert ledger.leg_block(ledger.Quote(up - cu.tick, up, 70000.0), 1.0, cu) is None  # 差一跳不算锁死
    dn = 70000.0 * (1 - cu.limit_pct)
    assert ledger.leg_block(ledger.Quote(dn, dn, 70000.0), -1.0, cu) == "limit_locked"


def test_execute_day_single_leg_and_fee_on_fill_price() -> None:
    specs = load_instruments()
    cu = specs["CU"]
    st = ledger.Ledger(equity=1_000_000.0)
    q = {"CU2610": ledger.Quote(70000.0, 70500.0, 69800.0)}
    fills = ledger.execute_day(st, {"CU": ("CU2610", 2.0)}, q, specs, 1.0, pd.Timestamp("2026-09-10"))
    assert len(fills) == 1 and fills[0]["status"] == "filled" and fills[0]["price"] == 70000.0 + cu.tick
    assert fills[0]["fee"] == cu.fee(70000.0 + cu.tick, 2)  # 手续费按含滑点的成交价
    assert st.positions["CU"].lots == 2.0 and st.equity == 1_000_000.0 - fills[0]["fee"]
    pnl, missing = ledger.mark(st, q, specs, strict=True)
    assert missing == [] and pnl["CU"] == 2 * (70500.0 - 70010.0) * cu.multiplier


def test_roll_is_atomic_both_directions() -> None:
    specs = load_instruments()
    cu = specs["CU"]
    st = ledger.Ledger(equity=1_000_000.0, positions={"CU": ledger.Position("CU2610", 2.0, 70000.0)})
    plan = {"CU": ("CU2611", 2.0)}
    d = pd.Timestamp("2026-09-11")
    # 旧腿(卖)跌停 → 两腿都不动
    q = {
        "CU2610": ledger.Quote(70000.0 * (1 - cu.limit_pct), 69000.0, 70000.0),
        "CU2611": ledger.Quote(70900.0, 70800.0, 70700.0),
    }
    f = ledger.execute_day(st, plan, q, specs, 1.0, d)
    assert [x["status"] for x in f] == ["roll_blocked", "roll_blocked"] and st.positions[
        "CU"
    ].contract == "CU2610"
    # 新腿缺行情 → 两腿都不动(此前会平掉旧腿留下空仓)
    f = ledger.execute_day(st, plan, {"CU2610": ledger.Quote(70600.0, 70400.0, 70500.0)}, specs, 1.0, d)
    assert [x["status"] for x in f] == ["roll_blocked", "roll_blocked"] and st.positions["CU"].lots == 2.0
    # 正常换月:先平旧再开新,两腿各记费用;目标 3 手直接开 3 手(不是先移 2 手再加 1 手)
    q = {"CU2610": ledger.Quote(70600.0, 70400.0, 70500.0), "CU2611": ledger.Quote(70900.0, 70800.0, 70700.0)}
    f = ledger.execute_day(st, {"CU": ("CU2611", 3.0)}, q, specs, 1.0, d)
    assert [x["leg"] for x in f] == ["roll_close", "roll_open"] and [x["lots"] for x in f] == [-2.0, 3.0]
    assert st.positions["CU"].contract == "CU2611" and st.positions["CU"].lots == 3.0
    assert st.realized_pnl == 2 * ((70600.0 - cu.tick) - 70000.0) * cu.multiplier
    assert st.equity == 1_000_000.0 + st.realized_pnl - f[0]["fee"] - f[1]["fee"]


def test_mark_strict_checks_before_mutating() -> None:
    specs = load_instruments()
    st = ledger.Ledger(
        equity=1_000_000.0,
        positions={
            "CU": ledger.Position("CU2610", 2.0, 70000.0),
            "AL": ledger.Position("AL2610", 1.0, 20000.0),
        },
    )
    q = {"CU2610": ledger.Quote(70000.0, 70500.0, 70000.0)}  # AL 缺行情
    with pytest.raises(ledger.LedgerIntegrityError):
        ledger.mark(st, q, specs, strict=True)
    assert st.equity == 1_000_000.0 and st.positions["CU"].ref_price == 70000.0  # 未部分盯市
    pnl, missing = ledger.mark(st, q, specs, strict=False)  # 引擎口径:记录缺口、其余照常
    assert missing == ["AL:AL2610"] and "CU" in pnl and st.positions["AL"].ref_price == 20000.0


def test_assert_finite() -> None:
    st = ledger.Ledger(equity=float("nan"))
    with pytest.raises(ledger.LedgerIntegrityError):
        ledger.assert_finite(st)
    st2 = ledger.Ledger(equity=1.0, positions={"CU": ledger.Position("CU2610", 1.0, np.nan)})
    with pytest.raises(ledger.LedgerIntegrityError):
        ledger.assert_finite(st2)
