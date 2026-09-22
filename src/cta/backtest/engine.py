"""日频合约级回测引擎(2026-09-22 起与实盘出单、纸面账本共用 cta.execution;design_log 17.6 第 4 项)。

时间线:T 日收盘 → plan_lots(目标暴露、T 收盘后权益、T+1 将持有合约在 T 的收盘价)→ 绝对目标手数;
T+1 开盘按合约级行情成交(每腿预检:缺行情 / 开盘价为空 / 触及涨跌停;换月两腿同进退,被挡则次日重试);
每日按持仓合约自身的结算价盯市(历史数据缺结算价的持仓当日不盯市、记入 unmarked,不中断)。
与冻结的旧引擎(engine_legacy.py)相比:定手数用 T 收盘价而非 T+1 开盘价;未成交不顺延、次日按最新信号重算;
换月先平旧、再直接开到目标手数(两腿,而非等手数移仓 + 再平衡三腿);换月腿也过涨跌停/缺行情闸门;
目标暴露缺失(NaN)视为 0(与出单一致);保证金上限、手数带、成交、盯市的代码与 generate_orders / PaperBook 完全相同。
成本与保证金参数全部来自 InstrumentTable 与合约面板,不在此处写死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cta.continuous.roll import SymbolPanel
from cta.execution import ledger
from cta.execution.ledger import Ledger, Quote
from cta.execution.plan import SymbolInputs, plan_lots
from cta.instruments.specs import InstrumentTable


@dataclass
class BacktestResult:
    equity: pd.Series[Any]
    positions: pd.DataFrame  # date x symbol, 手数(正多负空)
    exposure: pd.DataFrame  # date x symbol, 名义/权益
    margin_usage: pd.Series[Any]
    costs: pd.Series[Any]  # 每日手续费(元)
    trades: pd.DataFrame  # date, symbol, contract, lots, price, reason
    unfilled: pd.Series[Any] = field(default_factory=lambda: pd.Series(dtype=int))  # 每日被挡的腿数
    slippage: pd.Series[Any] = field(
        default_factory=lambda: pd.Series(dtype=float)
    )  # 每日滑点(元),已体现在成交价中
    pnl_by_symbol: pd.DataFrame = field(default_factory=pd.DataFrame)  # date x symbol 盈亏(元,不含手续费)
    unmarked: pd.Series[Any] = field(
        default_factory=lambda: pd.Series(dtype=int)
    )  # 每日缺结算价未盯市的持仓数


def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


class _QuoteTable:
    """(合约, 日期) → (open, settle, prev_settle, close)。优先用面板附带的合约级行情;
    没有时(合成测试面板)从面板列还原:当日持有合约 + roll 日的旧合约(open = roll_from_open)。"""

    def __init__(self, panel: SymbolPanel, limit_pct: float):
        self.q: dict[tuple[str, pd.Timestamp], tuple[float, float, float, float]] = {}
        c = panel.contracts
        if c is not None and len(c):
            cols = [x for x in ("open", "settle", "prev_settle", "close") if x in c.columns]
            contracts_lv = c.index.get_level_values(0)
            dates_lv = c.index.get_level_values(1)
            for contract, date, vals in zip(contracts_lv, dates_lv, c[cols].to_dict("records")):
                self.q[(str(contract), pd.Timestamp(date))] = (
                    _f(vals.get("open")),
                    _f(vals.get("settle")),
                    _f(vals.get("prev_settle")),
                    _f(vals.get("close")),
                )
            return
        for d, row in panel.frame.iterrows():
            ts = pd.Timestamp(str(d))
            lu = _f(row["limit_up"])
            own_prev = lu / (1 + limit_pct) if np.isfinite(lu) else _f(row["prev_settle"])
            self.q[(str(row["contract"]), ts)] = (
                _f(row["open"]),
                _f(row["settle"]),
                own_prev,
                _f(row["close"]),
            )
            rf = row["roll_from"]
            if isinstance(rf, str) and np.isfinite(_f(row["roll_from_open"])):
                self.q.setdefault(
                    (rf, ts), (_f(row["roll_from_open"]), float("nan"), _f(row["prev_settle"]), float("nan"))
                )

    def quote(self, contract: str, date: pd.Timestamp) -> Quote | None:
        v = self.q.get((contract, date))
        return None if v is None else Quote(v[0], v[1], v[2])

    def close(self, contract: str, date: pd.Timestamp) -> float:
        v = self.q.get((contract, date))
        return float("nan") if v is None else v[3]


def run_backtest(
    panels: dict[str, SymbolPanel],
    target_exposure: pd.DataFrame,
    specs: InstrumentTable,
    initial_capital: float,
    max_margin_usage: float = 0.4,
    slippage_ticks: float = 1.0,
    lot_band: float = 0.3,
    lots_override: pd.DataFrame | None = None,
) -> BacktestResult:
    """target_exposure: index=信号日(收盘), columns=symbol, 值=目标名义暴露/权益;在下一交易日开盘成交。
    lots_override(date × symbol 手数)给定时跳过规划,直接把该日持仓作为当日执行目标(固定仓位只换记账口径的对照)。"""
    symbols = [s for s in target_exposure.columns if s in panels]
    frames = {s: panels[s].frame for s in symbols}
    tables = {s: _QuoteTable(panels[s], specs[s].limit_pct) for s in symbols}
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()])) if frames else []
    lo, hi = target_exposure.index.min(), target_exposure.index.max()
    dates = pd.DatetimeIndex([d for d in all_dates if lo <= d <= hi])

    state = Ledger(equity=initial_capital)
    plan: dict[str, tuple[str, float]] = {}
    eq_hist: dict[pd.Timestamp, float] = {}
    pos_hist: dict[pd.Timestamp, dict[str, float]] = {}
    exp_hist: dict[pd.Timestamp, dict[str, float]] = {}
    mu_hist: dict[pd.Timestamp, float] = {}
    cost_hist: dict[pd.Timestamp, float] = {}
    unf_hist: dict[pd.Timestamp, int] = {}
    slip_hist: dict[pd.Timestamp, float] = {}
    unm_hist: dict[pd.Timestamp, int] = {}
    pnl_hist: dict[pd.Timestamp, dict[str, float]] = {}
    trades: list[tuple[pd.Timestamp, str, str, float, float, str]] = []

    for i, d in enumerate(dates):
        rows = {s: frames[s].loc[d] for s in symbols if d in frames[s].index}
        # ① 今日行情:持仓合约 + 计划合约(合约级)
        quotes: dict[str, Quote] = {}
        for s in symbols:
            pos = state.positions.get(s)
            for c in ([pos.contract] if pos is not None else []) + ([plan[s][0]] if s in plan else []):
                q = tables[s].quote(c, d)
                if q is not None:
                    quotes[c] = q
        # ② 执行昨日计划 → ③ 盯市(非 strict:历史缺口记入 unmarked)
        fills = ledger.execute_day(state, plan, quotes, specs, slippage_ticks, d)
        marked, missing = ledger.mark(state, quotes, specs, strict=False)
        pnl_sym = dict.fromkeys(symbols, 0.0)
        day_cost, day_slip, unfilled = 0.0, 0.0, 0
        for f in fills:
            if f["status"] == "filled":
                pnl_sym[f["symbol"]] += float(f["realized_pnl"])
                day_cost += float(f["fee"])
                day_slip += float(f["slippage"])
                trades.append(
                    (d, f["symbol"], f["contract"], float(f["lots"]), float(f["price"]), str(f["leg"]))
                )
            else:
                unfilled += 1
        for s, v in marked.items():
            pnl_sym[s] += v
        # ④ 记录
        margin = ledger.margin_used(state, quotes, specs)
        pos_row = {s: (state.positions[s].lots if s in state.positions else 0.0) for s in symbols}
        exp_row = {
            s: (
                state.positions[s].lots * state.positions[s].ref_price * specs[s].multiplier / state.equity
                if s in state.positions and state.equity > 0
                else 0.0
            )
            for s in symbols
        }
        eq_hist[d] = state.equity
        pos_hist[d] = pos_row
        exp_hist[d] = exp_row
        mu_hist[d] = margin / state.equity if state.equity > 0 else np.nan
        cost_hist[d] = day_cost
        unf_hist[d] = unfilled
        slip_hist[d] = day_slip
        unm_hist[d] = len(missing)
        pnl_hist[d] = pnl_sym
        # ⑤ T 收盘规划明日:T+1 将持有的合约、它在 T 的收盘价、T 收盘后的权益(与 generate_orders 同一函数)
        inputs: dict[str, SymbolInputs] = {}
        sched_of: dict[str, str] = {}
        for s, row in rows.items():
            sn = row["sched_next"] if "sched_next" in row.index else None
            sched = str(sn) if isinstance(sn, str) and sn else str(row["contract"])
            ref = tables[s].close(sched, d)
            if not (np.isfinite(ref) and ref > 0):
                ref = _f(row["close"])
            exposure = (
                _f(target_exposure.at[d, s])
                if s in target_exposure.columns and d in target_exposure.index
                else 0.0
            )
            if not np.isfinite(exposure):
                exposure = 0.0
            held = state.positions[s].lots if s in state.positions else 0.0
            inputs[s] = SymbolInputs(exposure, ref, _f(row["multiplier"]), _f(row["margin_rate"]), held)
            sched_of[s] = sched
        if lots_override is not None:
            nxt = dates[i + 1] if i + 1 < len(dates) else None
            plan = (
                {
                    s: (sched_of[s], float(lots_override.at[nxt, s]))
                    for s in inputs
                    if s in lots_override.columns and np.isfinite(_f(lots_override.at[nxt, s]))
                }
                if nxt is not None and nxt in lots_override.index
                else {}
            )
        else:
            planned = plan_lots(inputs, state.equity, lot_band, max_margin_usage)
            plan = {s: (sched_of[s], planned.lots[s]) for s in inputs}

    return BacktestResult(
        equity=pd.Series(eq_hist, name="equity"),
        positions=pd.DataFrame(pos_hist).T,
        exposure=pd.DataFrame(exp_hist).T,
        margin_usage=pd.Series(mu_hist, name="margin_usage"),
        costs=pd.Series(cost_hist, name="costs"),
        trades=pd.DataFrame(trades, columns=["date", "symbol", "contract", "lots", "price", "reason"]),
        unfilled=pd.Series(unf_hist, name="unfilled", dtype=int),
        slippage=pd.Series(slip_hist, name="slippage"),
        pnl_by_symbol=pd.DataFrame(pnl_hist).T,
        unmarked=pd.Series(unm_hist, name="unmarked", dtype=int),
    )
