"""日频合约级回测引擎。

时间线:T 日收盘后得到目标暴露(占权益的名义比例);T+1 开盘按 开盘价 ± 滑点 成交;每日按结算价盯市。
规则:
- 手数取整;目标暴露 × 权益 / (开盘价 × 乘数) 四舍五入。
- 保证金:所有持仓的 |名义| × 合约保证金率 之和不得超过 max_margin_usage × 权益,否则按比例缩减当日新目标。
- 换月:roll 日按旧合约开盘价平仓、新合约开盘价开仓,两腿分别计手续费与滑点。
- 涨跌停:开盘价触及涨停时买单不能成交、触及跌停时卖单不能成交,订单顺延到下一日重试。
- 手续费与滑点来自 InstrumentTable;保证金率与乘数来自合约元数据(随合约变化)。
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
    costs: pd.Series[Any]  # 每日 手续费+滑点(元)
    trades: pd.DataFrame  # date, symbol, contract, lots, price, reason
    unfilled: pd.Series[Any] = field(default_factory=lambda: pd.Series(dtype=int))


def _fill_price(open_px: float, lots_delta: float, tick: float, slippage_ticks: float) -> float:
    return float(open_px + float(np.sign(lots_delta)) * slippage_ticks * tick)


def run_backtest(
    panels: dict[str, SymbolPanel],
    target_exposure: pd.DataFrame,
    specs: InstrumentTable,
    initial_capital: float,
    max_margin_usage: float = 0.4,
    slippage_ticks: float = 1.0,
) -> BacktestResult:
    """target_exposure: index=信号日(收盘), columns=symbol, 值=目标名义暴露/权益(正多负空)。在下一交易日开盘成交。

    每日四步:① 换月(旧平新开,不受保证金预检影响);② 由目标暴露与今日开盘价算目标手数,合并涨跌停顺延的挂单;
    ③ 保证金预检:预计占用 > 上限 × 权益 时按比例缩减全部目标手数;④ 成交(涨跌停锁死则顺延)并按结算价盯市。"""
    symbols = [s for s in target_exposure.columns if s in panels]
    frames = {s: panels[s].frame for s in symbols}
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    dates = pd.DatetimeIndex([d for d in all_dates if d >= target_exposure.index.min()])
    tgt = target_exposure.reindex(dates).shift(1)  # T 日信号 -> T+1 执行

    equity = initial_capital
    lots: dict[str, float] = {s: 0.0 for s in symbols}
    held_contract: dict[str, str | None] = {s: None for s in symbols}
    pending: dict[str, float] = {}  # 涨跌停未成交的目标手数
    eq_hist: dict[pd.Timestamp, float] = {}
    pos_hist: dict[pd.Timestamp, dict[str, float]] = {}
    exp_hist: dict[pd.Timestamp, dict[str, float]] = {}
    mu_hist: dict[pd.Timestamp, float] = {}
    cost_hist: dict[pd.Timestamp, float] = {}
    unf_hist: dict[pd.Timestamp, int] = {}
    trades: list[tuple[pd.Timestamp, str, str, float, float, str]] = []

    for d in dates:
        day_cost, pnl, unfilled = 0.0, 0.0, 0
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
            pnl += (px_old - float(row["prev_settle"])) * mult * cur
            day_cost += spec.fee(px_old, cur)
            trades.append((d, s, str(row["roll_from"]), -cur, px_old, "roll_close"))
            px_new = _fill_price(float(row["open"]), cur, spec.tick, slippage_ticks)
            pnl += (float(row["settle"]) - px_new) * mult * cur
            day_cost += spec.fee(px_new, cur)
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
        # ③ 保证金预检(按开盘价估算)
        proj = 0.0
        for s, row in rows.items():
            l = desired.get(s, lots[s])
            proj += abs(l) * float(row["open"]) * float(row["multiplier"]) * float(row["margin_rate"])
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
                        pnl += (float(row["settle"]) - float(row["prev_settle"])) * mult * lots[s]
                    pnl += (float(row["settle"]) - px) * mult * delta
                    day_cost += spec.fee(px, delta)
                    trades.append((d, s, str(row["contract"]), delta, px, "rebalance"))
                    lots[s] = want
                    held_contract[s] = str(row["contract"])
                    settled.add(s)
            if lots[s] != 0 and s not in settled:
                pnl += (float(row["settle"]) - float(row["prev_settle"])) * mult * lots[s]
                settled.add(s)
        equity += pnl - day_cost
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

    return BacktestResult(
        equity=pd.Series(eq_hist, name="equity"),
        positions=pd.DataFrame(pos_hist).T,
        exposure=pd.DataFrame(exp_hist).T,
        margin_usage=pd.Series(mu_hist, name="margin_usage"),
        costs=pd.Series(cost_hist, name="costs"),
        trades=pd.DataFrame(trades, columns=["date", "symbol", "contract", "lots", "price", "reason"]),
        unfilled=pd.Series(unf_hist, name="unfilled", dtype=int),
    )
