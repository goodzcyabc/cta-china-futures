"""统一执行语义的回测引擎:T 收盘定手数、未成交次日重算、两腿换月且过闸门、保证金缩减、手数带、逐品种盈亏对账。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cta.backtest.engine import run_backtest
from cta.continuous.roll import PANEL_COLS, SymbolPanel
from cta.instruments.specs import load_instruments


def _panel(dates, opens, settles, roll_day=None, limit_up=None, contracts=None):  # type: ignore[no-untyped-def]
    f = pd.DataFrame(index=dates)
    f["contract"] = "CU2106"
    f["open"] = opens
    f["high"] = f["open"]
    f["low"] = f["open"]
    f["close"] = settles
    f["settle"] = settles
    f["prev_settle"] = f["settle"].shift(1).fillna(f["settle"].iloc[0])
    f["limit_up"] = f["prev_settle"] * 1.06 if limit_up is None else limit_up
    f["limit_down"] = f["prev_settle"] * 0.94
    f["volume"] = 1000.0
    f["open_interest"] = 10000.0
    f["multiplier"] = 5.0
    f["margin_rate"] = load_instruments()["CU"].margin_rate  # 与参数表一致:规划用面板值,盯市后占用用参数表值
    f["maturity"] = pd.Timestamp("2021-06-15")
    f["roll"] = False
    f["roll_from"] = None
    f["roll_from_open"] = np.nan
    f["adj_close"] = f["close"]
    f["next_contract"] = "CU2107"
    f["next_close"] = f["close"] * 1.01
    f["days_to_next"] = 30
    f["oi_total"] = f["open_interest"]
    f["volume_total"] = f["volume"]
    f["tick"] = 10.0
    f["settle_official"] = 1.0
    if roll_day is not None:
        f.loc[roll_day, "roll"] = True
        f.loc[roll_day, "roll_from"] = "CU2105"
        f.loc[roll_day, "roll_from_open"] = f.loc[roll_day, "open"]
        f.loc[roll_day:, "contract"] = "CU2106"
        f.loc[: roll_day - pd.Timedelta(days=1), "contract"] = "CU2105"
    f["sched_next"] = f["contract"].shift(-1).fillna(f["contract"])
    return SymbolPanel("CU", f[PANEL_COLS], contracts=contracts)


def test_pnl_costs_and_sizing() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=5)
    settles = [70000.0, 70000.0, 71000.0, 71000.0, 71000.0]
    p = _panel(dates, opens=settles, settles=settles)
    tgt = pd.DataFrame({"CU": [0.5, 0.5, 0.5, 0.5, 0.5]}, index=dates)  # 目标 50% 名义
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, slippage_ticks=1.0)
    # 第 1 日收盘定手数:round(0.5 × 1e6 / (70000×5)) = 1 手;第 2 日开盘成交 70010(1 跳滑点);当日结算 70000 → 亏 50
    t = r.trades.iloc[0]
    assert t["lots"] == 1 and t["price"] == 70010.0 and t["reason"] == "rebalance"
    fee = specs["CU"].fee(70010.0, 1)
    assert abs(r.equity.iloc[1] - (1_000_000 - 50 - fee)) < 1e-6
    assert abs(r.equity.iloc[2] - r.equity.iloc[1] - 5000) < 1e-6  # 第 3 日结算 71000:+1000×5
    assert abs(r.exposure.iloc[2]["CU"] - 71000 * 5 / r.equity.iloc[2]) < 1e-9
    assert abs(r.margin_usage.iloc[2] - 71000 * 5 * specs["CU"].margin_rate / r.equity.iloc[2]) < 1e-9


def test_roll_two_legs_and_lock_refreshes_instead_of_deferring() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=6)
    settles = [70000.0] * 6
    p = _panel(dates, opens=settles, settles=settles, roll_day=dates[3])
    tgt = pd.DataFrame({"CU": [0.5] * 6}, index=dates)
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, slippage_ticks=1.0)
    assert r.trades["reason"].tolist()[:3] == ["rebalance", "roll_close", "roll_open"]
    # 换月日:先平旧(69990)再开新到目标(70010),两腿手续费计入 costs;滑点体现在成交价 → 盯市多亏 2×10×5 = 100
    two_fees = specs["CU"].fee(69990.0, 1) + specs["CU"].fee(70010.0, 1)
    assert abs(r.costs.loc[dates[3]] - two_fees) < 1e-9
    assert abs((r.equity.loc[dates[2]] - r.equity.loc[dates[3]]) - (two_fees + 100.0)) < 1e-6
    # 涨停锁死:第 2 日开盘价等于涨停价 → 当日不成交(记 1 条),第 3 日按最新目标重算后成交
    lu = pd.Series(70000.0 * 1.06, index=dates)
    lu.iloc[1] = 70000.0
    p2 = _panel(dates, opens=settles, settles=settles, limit_up=lu)
    r2 = run_backtest({"CU": p2}, tgt, specs, initial_capital=1_000_000)
    assert r2.unfilled.loc[dates[1]] == 1 and r2.trades.iloc[0]["date"] == dates[2]


def test_blocked_roll_retries_next_day_with_contract_quotes() -> None:
    """换月日旧腿撞跌停 → 两腿都不动(旧引擎会无视闸门照换);次日按合约级行情重试成功。"""
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=6)
    settles = [70000.0] * 6
    rows = []
    for c in ("CU2105", "CU2106"):
        for d in dates:
            rows.append(
                {
                    "contract": c,
                    "date": d,
                    "open": 70000.0,
                    "close": 70000.0,
                    "settle": 70000.0,
                    "prev_settle": 70000.0,
                }
            )
    cdf = pd.DataFrame(rows).set_index(["contract", "date"])
    cdf.loc[("CU2105", dates[3]), "open"] = 70000.0 * (1 - specs["CU"].limit_pct)  # 旧腿(卖)跌停
    p = _panel(dates, opens=settles, settles=settles, roll_day=dates[3], contracts=cdf)
    tgt = pd.DataFrame({"CU": [0.5] * 6}, index=dates)
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000)
    assert r.unfilled.loc[dates[3]] == 2 and r.trades[r.trades["date"] == dates[3]].empty
    day4 = r.trades[r.trades["date"] == dates[4]]
    assert day4["reason"].tolist() == ["roll_close", "roll_open"] and day4["contract"].tolist() == [
        "CU2105",
        "CU2106",
    ]


def test_margin_cap_scales_next_target() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=4)
    settles = [70000.0] * 4
    p = _panel(dates, opens=settles, settles=settles)
    tgt = pd.DataFrame({"CU": [10.0] * 4}, index=dates)  # 1000% 名义 → 保证金远超 40% 上限
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, max_margin_usage=0.4)
    mr = specs["CU"].margin_rate
    raw = round(10.0 * 1_000_000 / (70000 * 5))  # 29 手
    expected = int(raw * (0.4 * 1_000_000) / (raw * 70000 * 5 * mr))  # 等比缩减后向零取整
    assert r.margin_usage.iloc[-1] < 0.4 + 1e-9 and r.positions["CU"].iloc[-1] == expected


def test_lot_band_suppresses_jitter_but_not_close() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=6)
    settles = [70000.0] * 6
    p = _panel(dates, opens=settles, settles=settles)
    # 目标暴露 3.5 → 10 手;之后微调到 3.85 → 11 手(差 1 手 < 20%×10)不交易;最后目标 0 必须平仓
    tgt = pd.DataFrame({"CU": [3.5, 3.5, 3.85, 3.85, 0.0, 0.0]}, index=dates)
    # 放开保证金上限,只看手数带(11 手 × 铜 11% 保证金会触发 40% 上限缩减,那是另一个测试)
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, lot_band=0.2, max_margin_usage=1.0)
    lots = r.positions["CU"].tolist()
    assert lots[1] == 10 and lots[3] == 10 and lots[5] == 0
    assert r.slippage.loc[dates[1]] == 10 * 10 * 5  # 10 手 × 1 跳 × 10 元 × 5 吨
    r0 = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, lot_band=0.0, max_margin_usage=1.0)
    assert r0.positions["CU"].tolist()[3] == 11  # 无手数带时会追到 11 手


def test_pnl_by_symbol_reconciles_with_equity_and_override_reproduces_path() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=8)
    settles = [70000.0, 70100.0, 69900.0, 70300.0, 70300.0, 70000.0, 70200.0, 70100.0]
    p = _panel(dates, opens=settles, settles=settles, roll_day=dates[4])
    tgt = pd.DataFrame({"CU": [0.5, 0.5, -0.5, -0.5, 0.5, 0.5, 0.0, 0.0]}, index=dates)
    r = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000)
    total_pnl = r.pnl_by_symbol.sum(axis=1)
    d_eq = r.equity.diff().fillna(r.equity.iloc[0] - 1_000_000)
    assert np.allclose((total_pnl - r.costs).to_numpy(), d_eq.to_numpy(), atol=1e-6)
    # 固定仓位(lots_override)重放同一条持仓路径 → 权益完全一致
    r2 = run_backtest({"CU": p}, tgt, specs, initial_capital=1_000_000, lots_override=r.positions)
    assert r2.positions["CU"].tolist() == r.positions["CU"].tolist()
    assert np.allclose(r2.equity.to_numpy(), r.equity.to_numpy())
