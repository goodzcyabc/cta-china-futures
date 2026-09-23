"""组合诊断:逐品种手续费归属、滑点不重复扣、严格对账、符号迁移、含负贡献的集中度、板块聚合、滚动广度、leave-one-out 真重跑。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from cta.analysis import attribution as attr
from cta.analysis.loo import leave_one_out
from cta.backtest.engine import BacktestResult, run_backtest
from cta.continuous.roll import PANEL_COLS, SymbolPanel
from cta.instruments.specs import load_instruments

D = pd.bdate_range("2021-03-01", periods=4)
CAP = 1_000_000.0


def _result() -> BacktestResult:
    """手工构造的 4 日 × 2 品种结果:pnl_by_symbol(盯市+已实现,含滑点效应,不含手续费)、逐笔手续费、权益按引擎恒等式推出。"""
    pnl = pd.DataFrame({"CU": [0.0, -50.0, 5000.0, -1000.0], "AL": [0.0, 200.0, -300.0, 800.0]}, index=D)
    trades = pd.DataFrame(
        [
            (D[1], "CU", "CU2106", 1.0, 70010.0, "rebalance", 3.5, 50.0),
            (D[1], "AL", "AL2106", 2.0, 20005.0, "rebalance", 6.0, 100.0),
            (D[3], "CU", "CU2106", -1.0, 71000.0, "rebalance", 3.55, 50.0),
        ],
        columns=["date", "symbol", "contract", "lots", "price", "reason", "fee", "slippage"],
    )
    fees = trades.groupby("date")["fee"].sum().reindex(D).fillna(0.0)
    equity = CAP + (pnl.sum(axis=1) - fees).cumsum()
    positions = pd.DataFrame({"CU": [0, 1, 1, 0], "AL": [0, 2, 2, 2]}, index=D, dtype=float)
    return BacktestResult(
        equity=equity,
        positions=positions,
        exposure=positions * 0.0,
        margin_usage=pd.Series(0.1, index=D),
        costs=fees,
        trades=trades,
        unfilled=pd.Series(0, index=D),
        slippage=trades.groupby("date")["slippage"].sum().reindex(D).fillna(0.0),
        pnl_by_symbol=pnl,
    )


def test_fee_attributed_to_trade_symbol_and_recomputable() -> None:
    specs = load_instruments()
    res = _result()
    f = attr.fees_by_symbol_day(res.trades, specs)
    assert f.loc[D[1], "CU"] == 3.5 and f.loc[D[1], "AL"] == 6.0 and f.loc[D[3], "CU"] == 3.55
    assert D[3] not in f.index or f.loc[D[3], "AL"] == 0.0
    # 没有 fee 列时按参数表以成交价重算(与引擎同一公式)
    t = res.trades.drop(columns=["fee"])
    f2 = attr.fees_by_symbol_day(t, specs)
    assert f2.loc[D[1], "CU"] == specs["CU"].fee(70010.0, 1.0) and f2.loc[D[1], "AL"] == specs["AL"].fee(
        20005.0, 2.0
    )


def test_slippage_is_not_deducted_again() -> None:
    specs = load_instruments()
    res = _result()
    net = attr.net_by_symbol_day(res, specs)
    assert net.loc[D[1], "CU"] == -50.0 - 3.5  # 只扣手续费;滑点 50 已在成交价 70010 里体现
    assert net.loc[D[2], "CU"] == 5000.0 and net.loc[D[3], "AL"] == 800.0


def test_reconciliation_is_strict() -> None:
    specs = load_instruments()
    res = _result()
    full = attr.Period("FULL", D[0], D[-1])
    a = attr.Period("A", D[0], D[1])
    b = attr.Period("B", D[2], D[-1])
    recs = attr.assert_reconciled(res, specs, [a, b, full], CAP)
    assert all(r.ok for r in recs) and abs(recs[0].sum_net + recs[1].sum_net - recs[2].sum_net) < 1e-9
    assert recs[2].equity_change == float(res.equity.iloc[-1] - CAP)
    res.pnl_by_symbol.loc[D[2], "AL"] += 1.0  # 注入 1 元错误
    with pytest.raises(attr.ReconciliationError):
        attr.assert_reconciled(res, specs, [full], CAP)


def _table() -> pd.DataFrame:
    rows = {
        "A": dict(asset_class="有色", net_IS=100.0, net_OOS=60.0, net_FULL=160.0),
        "B": dict(asset_class="有色", net_IS=50.0, net_OOS=-20.0, net_FULL=30.0),
        "C": dict(asset_class="农产品", net_IS=-30.0, net_OOS=40.0, net_FULL=10.0),
        "D": dict(asset_class="农产品", net_IS=-80.0, net_OOS=-150.0, net_FULL=-230.0),
    }
    t = pd.DataFrame(rows).T
    for p in ("IS", "OOS", "FULL"):
        t[f"net_{p}"] = t[f"net_{p}"].astype(float)
        t[f"pct_{p}"] = t[f"net_{p}"] / CAP
        t[f"sign_{p}"] = t[f"net_{p}"].map(lambda v: "+" if v > 0 else "-")
        t[f"active_{p}"] = True
    return t


def test_sign_transitions_and_breadth() -> None:
    t = _table()
    tr = attr.sign_transitions(t, "IS", "OOS").set_index(["from", "to"])
    assert tr.loc[("IS+", "OOS+"), "n"] == 1 and tr.loc[("IS+", "OOS+"), "symbols"] == "A"
    assert tr.loc[("IS+", "OOS-"), "symbols"] == "B" and tr.loc[("IS-", "OOS+"), "symbols"] == "C"
    assert tr.loc[("IS-", "OOS-"), "symbols"] == "D"
    periods = [attr.Period(p, D[0], D[-1]) for p in ("IS", "OOS", "FULL")]
    br = attr.breadth_table(t, periods)
    assert br.loc["OOS", "n_pos"] == 2 and br.loc["OOS", "n_neg"] == 2 and br.loc["OOS", "breadth"] == 0.5


def test_concentration_definitions_with_negative_contributors() -> None:
    t = _table()
    c = attr.concentration(t, [attr.Period("OOS", D[0], D[-1])], ks=(1, 3)).set_index("k")
    # OOS 正贡献:A 60、C 40 → 正贡献总和 100;总净贡献 = 60 − 20 + 40 − 150 = −70(≤ 0 → share_of_total 不定义)
    assert (
        c.loc[1, "symbols"] == "A"
        and c.loc[1, "share_of_positive"] == 0.6
        and np.isnan(c.loc[1, "share_of_total"])
    )
    assert c.loc[3, "symbols"] == "A,C" and c.loc[3, "share_of_positive"] == 1.0
    c2 = attr.concentration(t, [attr.Period("IS", D[0], D[-1])], ks=(1,)).set_index("k")
    # IS:正贡献 A 100、B 50 → 150;总净贡献 = 100 + 50 − 30 − 80 = 40 → 前 1 占总净贡献 250%(> 100%,分母含负贡献)
    assert c2.loc[1, "share_of_positive"] == pytest.approx(100 / 150) and c2.loc[
        1, "share_of_total"
    ] == pytest.approx(2.5)


def test_sector_aggregation_and_negative_lists() -> None:
    t = _table()
    periods = [attr.Period(p, D[0], D[-1]) for p in ("IS", "OOS", "FULL")]
    s = attr.sector_contribution(t, periods)
    assert s.loc["有色", "net_OOS"] == 40.0 and s.loc["农产品", "net_FULL"] == -220.0
    assert s.loc["有色", "n_pos_OOS"] == 1 and s.loc["有色", "n_neg_OOS"] == 1
    neg = attr.negative_lists(t)
    assert (
        neg["三段皆负(IS、OOS、FULL)"] == ["D"]
        and neg["FULL 与 OOS 皆负"] == ["D"]
        and neg["IS 为正、OOS 为负"] == ["B"]
    )


def test_rolling_breadth_by_year() -> None:
    specs = load_instruments()
    res = _result()
    rb = attr.rolling_breadth(res, specs, windows_years=(1,))
    assert (
        len(rb) == 1 and rb.iloc[0]["n_active"] == 2 and rb.iloc[0]["n_pos"] == 2
    )  # CU 净 +3946.45、AL 净 +694


def _panel(
    symbol: str, dates: pd.DatetimeIndex, px: float, mult: float, mr: float, tick: float
) -> SymbolPanel:
    f = pd.DataFrame(index=dates)
    f["contract"] = f"{symbol}2106"
    for c in ("open", "high", "low", "close", "settle"):
        f[c] = px
    f["prev_settle"] = px
    f["limit_up"], f["limit_down"] = px * 1.06, px * 0.94
    f["volume"], f["open_interest"] = 1000.0, 10000.0
    f["multiplier"], f["margin_rate"] = mult, mr
    f["maturity"] = pd.Timestamp("2021-06-15")
    f["roll"], f["roll_from"], f["roll_from_open"] = False, None, np.nan
    f["adj_close"], f["next_contract"], f["next_close"], f["days_to_next"] = px, f"{symbol}2107", px, 30
    f["oi_total"], f["volume_total"], f["tick"] = 10000.0, 1000.0, tick
    f["sched_next"], f["settle_official"] = f["contract"], 1.0
    return SymbolPanel(symbol, f[PANEL_COLS])


def test_leave_one_out_reruns_engine_instead_of_subtracting() -> None:
    specs = load_instruments()
    dates = pd.bdate_range("2021-03-01", periods=6)
    panels = {
        "CU": _panel("CU", dates, 70000.0, specs["CU"].multiplier, specs["CU"].margin_rate, specs["CU"].tick),
        "AL": _panel("AL", dates, 20000.0, specs["AL"].multiplier, specs["AL"].margin_rate, specs["AL"].tick),
    }
    # 两个品种目标暴露都很大 → 保证金上限缩减把两者都压下去;剔除一个后另一个不再被缩减,路径完全不同
    target = pd.DataFrame({"CU": [4.0] * 6, "AL": [4.0] * 6}, index=dates)
    kw: dict[str, Any] = dict(max_margin_usage=0.4, slippage_ticks=1.0, lot_band=0.0)
    calls: list[pd.DataFrame] = []

    def spy(panels_: Any, t: pd.DataFrame, *a: Any, **k: Any) -> BacktestResult:
        calls.append(t.copy())
        return run_backtest(panels_, t, *a, **k)

    base = run_backtest(panels, target, specs, CAP, **kw)
    full = attr.Period("FULL", dates[0], dates[-1])
    oos = attr.Period("OOS", dates[3], dates[-1])
    loo = leave_one_out(panels, target, specs, CAP, ["CU", "AL"], full, oos, kw, run_fn=spy, baseline=base)
    assert len(calls) == 2  # 每个品种各重跑一次
    assert (calls[0]["CU"] == 0).all() and calls[0]["AL"].equals(target["AL"])
    assert (calls[1]["AL"] == 0).all() and calls[1]["CU"].equals(target["CU"])
    # 真重跑 ≠ 简单相减:剔 CU 后 AL 的手数从被缩减的值放大到不受缩减的值
    loo_cu = run_backtest(panels, target.assign(CU=0.0), specs, CAP, **kw)
    assert loo_cu.positions["AL"].iloc[-1] > base.positions["AL"].iloc[-1]
    subtract = float(base.equity.iloc[-1]) - float(attr.net_by_symbol_day(base, specs)["CU"].sum())
    assert abs(float(loo["final_equity"].loc["CU"]) - subtract) > 1.0
    assert set(loo.columns) >= {"d_full_sharpe_m", "d_oos_cagr", "dependent"}
