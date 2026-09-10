"""日频合约级回测引擎。

时间线:T 日收盘后得到目标暴露(占权益的名义比例);T+1 开盘按 开盘价 ± 滑点 成交;每日按结算价盯市。
每日四步:
  ① 换月:roll 日按旧合约开盘平仓、新合约开盘开仓,两腿分别计手续费与滑点(不受保证金预检影响);
  ② 目标手数:目标暴露 × 昨日权益 / (今日开盘价 × 乘数),四舍五入;合并涨跌停顺延的挂单;
  ③ 保证金预检:全部目标的预计占用 > 上限 × 权益 时按比例缩减;
  ④ 成交与盯市:手数不交易带内不交易(平仓除外);开盘触及涨停不能买、跌停不能卖则顺延;按结算价盯市。
成本与保证金参数全部来自 InstrumentTable 与合约面板,不在此处写死。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from cta.continuous.roll import SymbolPanel
from cta.instruments.specs import InstrumentTable


@dataclass
class BacktestResult:
    equity: pd.Series[Any]
    positions: pd.DataFrame  # date x symbol, 手数(正多负空)
    exposure: pd.DataFrame  # date x symbol, 名义/权益
    margin_usage: pd.Series[Any]
    costs: pd.Series[Any]  # 每日手续费(元)
    trades: pd.DataFrame  # date, symbol, contract, lots, price, reason
    unfilled: pd.Series[Any] = field(default_factory=lambda: pd.Series(dtype=int))
    slippage: pd.Series[Any] = field(
        default_factory=lambda: pd.Series(dtype=float)
    )  # 每日滑点(元),已体现在成交价中
    pnl_by_symbol: pd.DataFrame = field(default_factory=pd.DataFrame)  # date x symbol 盯市盈亏(元,不含手续费)


def _fill_price(open_px: float, lots_delta: float, tick: float, slippage_ticks: float) -> float:
    return float(open_px + float(np.sign(lots_delta)) * slippage_ticks * tick)


def run_backtest(
    panels: dict[str, SymbolPanel],
    target_exposure: pd.DataFrame,
    specs: InstrumentTable,
    initial_capital: float,
    max_margin_usage: float = 0.4,
    slippage_ticks: float = 1.0,
    lot_band: float = 0.2,
) -> BacktestResult:
    """target_exposure: index=信号日(收盘), columns=symbol, 值=目标名义暴露/权益。在下一交易日开盘成交。
    lot_band:|目标手数 − 当前手数| < lot_band × max(1, |当前手数|) 时不交易(目标为 0 时不受限)。"""
    symbols = [s for s in target_exposure.columns if s in panels]
    frames = {s: panels[s].frame for s in symbols}
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    dates = pd.DatetimeIndex([d for d in all_dates if d >= target_exposure.index.min()])
    tgt = target_exposure.reindex(dates).shift(1)  # T 日信号 -> T+1 执行

    equity = initial_capital
    lots: dict[str, float] = {s: 0.0 for s in symbols}
    held_contract: dict[str, str | None] = {s: None for s in symbols}
    pending: dict[str, float] = {}
    eq_hist: dict[pd.Timestamp, float] = {}
    pos_hist: dict[pd.Timestamp, dict[str, float]] = {}
    exp_hist: dict[pd.Timestamp, dict[str, float]] = {}
    mu_hist: dict[pd.Timestamp, float] = {}
    cost_hist: dict[pd.Timestamp, float] = {}
    unf_hist: dict[pd.Timestamp, int] = {}
    slip_hist: dict[pd.Timestamp, float] = {}
    pnl_hist: dict[pd.Timestamp, dict[str, float]] = {}
    trades: list[tuple[pd.Timestamp, str, str, float, float, str]] = []
    pnl_sym: dict[str, float] = {s: 0.0 for s in symbols}

    def mark(sym: str, amount: float) -> None:
        pnl_sym[sym] += amount

    for d in dates:
        day_cost, unfilled, day_slip = 0.0, 0, 0.0
        for s in symbols:
            pnl_sym[s] = 0.0
        rows = {s: frames[s].loc[d] for s in symbols if d in frames[s].index}
        settled: set[str] = set()  # 今日已盯市到结算价的品种

        # ① 换月
        for s, row in rows.items():
            cur = lots[s]
            if not (
                bool(row["roll"])
                and cur != 0
                and isinstance(row["roll_from"], str)
                and held_contract[s] == row["roll_from"]
            ):
                continue
            old_open = float(row["roll_from_open"])
            if not np.isfinite(old_open):
                continue
            spec, mult = specs[s], float(row["multiplier"])
            px_old = _fill_price(old_open, -cur, spec.tick, slippage_ticks)
            mark(s, (px_old - float(row["prev_settle"])) * mult * cur)
            day_cost += spec.fee(px_old, cur)
            day_slip += spec.slippage(cur, slippage_ticks)
            trades.append((d, s, str(row["roll_from"]), -cur, px_old, "roll_close"))
            px_new = _fill_price(float(row["open"]), cur, spec.tick, slippage_ticks)
            mark(s, (float(row["settle"]) - px_new) * mult * cur)
            day_cost += spec.fee(px_new, cur)
            day_slip += spec.slippage(cur, slippage_ticks)
            trades.append((d, s, str(row["contract"]), cur, px_new, "roll_open"))
            held_contract[s] = str(row["contract"])
            settled.add(s)
        # ② 目标手数
        desired: dict[str, float] = {}
        for s, row in rows.items():
            if s in pending:
                desired[s] = pending.pop(s)
                continue
            t_exp = tgt.at[d, s] if s in tgt.columns else np.nan
            px_open = float(row["open"])
            if np.isfinite(t_exp) and px_open > 0:
                desired[s] = float(np.round(t_exp * equity / (px_open * float(row["multiplier"]))))
        # ③ 保证金预检
        proj = 0.0
        for s, row in rows.items():
            proj += (
                abs(desired.get(s, lots[s]))
                * float(row["open"])
                * float(row["multiplier"])
                * float(row["margin_rate"])
            )
        if equity > 0 and proj > max_margin_usage * equity:
            k = max_margin_usage * equity / proj
            for s in list(desired):
                desired[s] = float(np.trunc(desired[s] * k))
        # ④ 成交与盯市
        for s, row in rows.items():
            spec, mult = specs[s], float(row["multiplier"])
            want = desired.get(s, lots[s])
            delta = want - lots[s]
            px_open = float(row["open"])
            if want != 0 and abs(delta) < lot_band * max(1.0, abs(lots[s])):
                delta = 0.0
            if delta != 0:
                locked = (px_open >= float(row["limit_up"]) - 1e-9 and delta > 0) or (
                    px_open <= float(row["limit_down"]) + 1e-9 and delta < 0
                )
                if locked or not np.isfinite(px_open):
                    pending[s] = want
                    unfilled += 1
                else:
                    px = _fill_price(px_open, delta, spec.tick, slippage_ticks)
                    if lots[s] != 0 and s not in settled:
                        mark(s, (float(row["settle"]) - float(row["prev_settle"])) * mult * lots[s])
                    mark(s, (float(row["settle"]) - px) * mult * delta)
                    day_cost += spec.fee(px, delta)
                    day_slip += spec.slippage(delta, slippage_ticks)
                    trades.append((d, s, str(row["contract"]), delta, px, "rebalance"))
                    lots[s] = lots[s] + delta
                    held_contract[s] = str(row["contract"])
                    settled.add(s)
            if lots[s] != 0 and s not in settled:
                mark(s, (float(row["settle"]) - float(row["prev_settle"])) * mult * lots[s])
                settled.add(s)
        equity += sum(pnl_sym.values()) - day_cost
        margin = 0.0
        exp_row: dict[str, float] = {}
        pos_row: dict[str, float] = {}
        for s in symbols:
            pos_row[s] = lots[s]
            if s not in rows or lots[s] == 0:
                exp_row[s] = 0.0
                continue
            row = rows[s]
            notional = float(row["settle"]) * float(row["multiplier"]) * lots[s]
            margin += abs(notional) * float(row["margin_rate"])
            exp_row[s] = notional / equity if equity > 0 else np.nan
        eq_hist[d] = equity
        pos_hist[d] = pos_row
        exp_hist[d] = exp_row
        mu_hist[d] = margin / equity if equity > 0 else np.nan
        cost_hist[d] = day_cost
        unf_hist[d] = unfilled
        slip_hist[d] = day_slip
        pnl_hist[d] = dict(pnl_sym)

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
    )
