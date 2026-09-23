"""组合诊断(只读):逐品种净归因、收益广度与集中度、IS→OOS 符号迁移、板块汇总、滚动广度,以及严格对账。

口径:
- `BacktestResult.pnl_by_symbol` = 逐品种盯市 + 已实现盈亏(元),滑点已在成交价里体现,**不含手续费**;
- 逐品种净贡献 = pnl_by_symbol − 该品种逐笔手续费(按成交所属品种归属;引擎逐笔记录在 `trades.fee`,没有该列时按参数表用成交价重算——同一公式);
- 不再扣滑点(否则重复扣除);
- 对账:任一区间 Σ_品种 净贡献 = 区间权益变化(区间首日前一交易日权益 → 区间末日权益;首段以初始资金为基),只允许浮点误差。
这是诊断,不是选池规则:任何"负贡献品种"清单都不自动作用于品种池。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from cta.backtest.engine import BacktestResult
from cta.instruments.specs import InstrumentTable


@dataclass(frozen=True)
class Period:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


@dataclass(frozen=True)
class Reconciliation:
    period: str
    sum_net: float
    equity_change: float
    diff: float
    tol: float

    @property
    def ok(self) -> bool:
        return abs(self.diff) <= self.tol


class ReconciliationError(RuntimeError):
    """逐品种净贡献之和与区间权益变化不一致:报告生成必须中止。"""


def _mask(index: pd.Index[Any], period: Period) -> np.ndarray[Any, Any]:
    idx = pd.DatetimeIndex(index)
    out: np.ndarray[Any, Any] = np.asarray((idx >= period.start) & (idx <= period.end))
    return out


def fees_by_symbol_day(trades: pd.DataFrame, specs: InstrumentTable) -> pd.DataFrame:
    """逐笔手续费按(成交日, 成交所属品种)归属,返回 date × symbol(元)。"""
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    if "fee" not in t.columns:
        t["fee"] = [
            specs[str(s)].fee(float(p), float(lots)) for s, p, lots in zip(t["symbol"], t["price"], t["lots"])
        ]
    t["date"] = pd.to_datetime(t["date"])
    out: pd.DataFrame = t.pivot_table(index="date", columns="symbol", values="fee", aggfunc="sum").fillna(0.0)
    return out


def net_by_symbol_day(res: BacktestResult, specs: InstrumentTable) -> pd.DataFrame:
    """date × symbol 净贡献 = pnl_by_symbol − 该品种当日手续费。"""
    pnl = res.pnl_by_symbol.copy()
    pnl.index = pd.DatetimeIndex(pnl.index)
    raw = fees_by_symbol_day(res.trades, specs)
    fees = (
        raw.reindex(index=pnl.index, columns=pnl.columns).fillna(0.0)
        if not raw.empty
        else pd.DataFrame(0.0, index=pnl.index, columns=pnl.columns)
    )
    out: pd.DataFrame = pnl.fillna(0.0) - fees
    return out


def equity_change(equity: pd.Series[Any], period: Period, initial_capital: float) -> float:
    """区间权益变化:区间末日权益 − 区间首日前一交易日权益(没有前一日时用初始资金)。"""
    eq = equity.dropna()
    eq.index = pd.DatetimeIndex(eq.index)
    seg = eq[_mask(eq.index, period)]
    if seg.empty:
        return 0.0
    before = eq[pd.DatetimeIndex(eq.index) < period.start]
    base = float(before.iloc[-1]) if len(before) else float(initial_capital)
    return float(seg.iloc[-1]) - base


def reconcile(
    res: BacktestResult,
    specs: InstrumentTable,
    period: Period,
    initial_capital: float,
    abs_tol: float = 1e-2,
) -> Reconciliation:
    """Σ_品种 净贡献 vs 区间权益变化;abs_tol 以元计,只覆盖浮点累加误差(默认 1 分)。"""
    net = net_by_symbol_day(res, specs)
    s = float(net[_mask(net.index, period)].to_numpy(dtype=float).sum())
    e = equity_change(res.equity, period, initial_capital)
    return Reconciliation(period.name, s, e, s - e, abs_tol)


def assert_reconciled(
    res: BacktestResult, specs: InstrumentTable, periods: list[Period], initial_capital: float
) -> list[Reconciliation]:
    out = [reconcile(res, specs, p, initial_capital) for p in periods]
    bad = [r for r in out if not r.ok]
    if bad:
        raise ReconciliationError(
            "; ".join(
                f"{r.period}: Σ净贡献 {r.sum_net:,.4f} vs 权益变化 {r.equity_change:,.4f} 差 {r.diff:,.6f}"
                for r in bad
            )
        )
    return out


def _sign(v: float) -> str:
    return "+" if v > 0 else ("-" if v < 0 else "0")


def per_symbol_table(
    res: BacktestResult, specs: InstrumentTable, periods: list[Period], initial_capital: float
) -> pd.DataFrame:
    """每个品种各区间的净贡献(元)、占初始资金比例、符号、是否活跃(区间内有过持仓)。"""
    net = net_by_symbol_day(res, specs)
    pos = res.positions.copy()
    pos.index = pd.DatetimeIndex(pos.index)
    rows: list[dict[str, Any]] = []
    for s in net.columns:
        sym = str(s)
        row: dict[str, Any] = {"symbol": sym, "asset_class": specs[sym].asset_class}
        for p in periods:
            v = float(net.loc[_mask(net.index, p), s].sum())
            active = bool((pos.loc[_mask(pos.index, p), s].abs() > 0).any()) if s in pos.columns else False
            row[f"net_{p.name}"] = v
            row[f"pct_{p.name}"] = v / initial_capital
            row[f"sign_{p.name}"] = _sign(v) if active else "n/a"
            row[f"active_{p.name}"] = active
        rows.append(row)
    return pd.DataFrame(rows).set_index("symbol")


def breadth_table(table: pd.DataFrame, periods: list[Period]) -> pd.DataFrame:
    """各区间:参评(活跃)品种数、正/负/零收益品种数、广度 = 正收益品种数 / 参评品种数。"""
    rows = []
    for p in periods:
        act = table[table[f"active_{p.name}"]]
        sg = act[f"sign_{p.name}"]
        n_pos, n_neg, n_zero = int((sg == "+").sum()), int((sg == "-").sum()), int((sg == "0").sum())
        rows.append(
            {
                "period": p.name,
                "n_active": int(len(act)),
                "n_pos": n_pos,
                "n_neg": n_neg,
                "n_zero": n_zero,
                "breadth": n_pos / len(act) if len(act) else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("period")


def sign_transitions(table: pd.DataFrame, a: str = "IS", b: str = "OOS") -> pd.DataFrame:
    """a 区间符号 → b 区间符号 的迁移矩阵(只算两段都活跃的品种),每格给数量与品种列表。"""
    both = table[table[f"active_{a}"] & table[f"active_{b}"]]
    rows = []
    for fa in ("+", "-", "0"):
        for fb in ("+", "-", "0"):
            syms = sorted(both[(both[f"sign_{a}"] == fa) & (both[f"sign_{b}"] == fb)].index.tolist())
            if fa == "0" and fb == "0" and not syms:
                continue
            rows.append({"from": f"{a}{fa}", "to": f"{b}{fb}", "n": len(syms), "symbols": ",".join(syms)})
    return pd.DataFrame(rows)


def sector_contribution(table: pd.DataFrame, periods: list[Period]) -> pd.DataFrame:
    """按 asset_class 汇总各区间净贡献(元)与正/负品种数。"""
    rows = []
    for ac, g in table.groupby("asset_class"):
        row: dict[str, Any] = {"asset_class": ac, "n_symbols": int(len(g))}
        for p in periods:
            act = g[g[f"active_{p.name}"]]
            row[f"net_{p.name}"] = float(g[f"net_{p.name}"].sum())
            row[f"n_pos_{p.name}"] = int((act[f"sign_{p.name}"] == "+").sum())
            row[f"n_neg_{p.name}"] = int((act[f"sign_{p.name}"] == "-").sum())
        rows.append(row)
    return pd.DataFrame(rows).set_index("asset_class")


def concentration(
    table: pd.DataFrame, periods: list[Period], ks: tuple[int, ...] = (1, 3, 5)
) -> pd.DataFrame:
    """前 k 大正贡献品种的集中度。两种占比,定义不同:
    - share_of_positive = 前 k 正贡献之和 / 全部正贡献之和(分母只含正贡献,恒 ≤ 100%);
    - share_of_total = 前 k 正贡献之和 / 组合总净贡献(分母含负贡献品种,可能 > 100%;总净贡献 ≤ 0 时为 NaN)。"""
    rows = []
    for p in periods:
        net = table[f"net_{p.name}"]
        positives = net[net > 0].sort_values(ascending=False)
        pos_total = float(positives.sum())
        total = float(net.sum())
        for k in ks:
            top = positives.head(k)
            s = float(top.sum())
            rows.append(
                {
                    "period": p.name,
                    "k": k,
                    "symbols": ",".join(top.index.tolist()),
                    "sum_topk": s,
                    "positive_total": pos_total,
                    "share_of_positive": s / pos_total if pos_total > 0 else np.nan,
                    "total_net": total,
                    "share_of_total": s / total if total > 0 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def rolling_breadth(
    res: BacktestResult, specs: InstrumentTable, windows_years: tuple[int, ...] = (1, 2)
) -> pd.DataFrame:
    """按日历年与滚动两年窗口:窗口内活跃品种中净贡献为正的比例。"""
    net = net_by_symbol_day(res, specs)
    pos = res.positions.copy()
    pos.index = pd.DatetimeIndex(pos.index)
    years = sorted(set(pd.DatetimeIndex(net.index).year))
    rows = []
    for w in windows_years:
        for i in range(w - 1, len(years)):
            y0, y1 = years[i - w + 1], years[i]
            p = Period(
                f"{y0}" if w == 1 else f"{y0}-{y1}", pd.Timestamp(f"{y0}-01-01"), pd.Timestamp(f"{y1}-12-31")
            )
            m = _mask(net.index, p)
            pm = _mask(pos.index, p)
            active = [s for s in net.columns if s in pos.columns and bool((pos.loc[pm, s].abs() > 0).any())]
            sums = net.loc[m, active].sum() if active else pd.Series(dtype=float)
            n_pos, n_neg = int((sums > 0).sum()), int((sums < 0).sum())
            rows.append(
                {
                    "window_type": f"{w}y",
                    "window": p.name,
                    "n_active": len(active),
                    "n_pos": n_pos,
                    "n_neg": n_neg,
                    "breadth": n_pos / len(active) if active else np.nan,
                }
            )
    return pd.DataFrame(rows)


def negative_lists(table: pd.DataFrame) -> dict[str, list[str]]:
    """长期负贡献清单(只列出,不作用于品种池):三段皆负;FULL 与 OOS 皆负;仅 OOS 为负(IS 为正)。"""
    neg = {p: table[f"sign_{p}"] == "-" for p in ("IS", "OOS", "FULL") if f"sign_{p}" in table.columns}
    out: dict[str, list[str]] = {}
    if {"IS", "OOS", "FULL"} <= set(neg):
        out["三段皆负(IS、OOS、FULL)"] = sorted(table[neg["IS"] & neg["OOS"] & neg["FULL"]].index.tolist())
        out["FULL 与 OOS 皆负"] = sorted(table[neg["FULL"] & neg["OOS"]].index.tolist())
        out["IS 为正、OOS 为负"] = sorted(table[(table["sign_IS"] == "+") & neg["OOS"]].index.tolist())
    return out
