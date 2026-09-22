"""合约级账本与成交状态机:纸面账本与回测引擎共用的唯一状态转换(design_log 十七 → 17.6 第 4 项)。

- 状态 = 权益 + {品种: (合约, 手数, 参考价)} + 累计已实现盈亏/手续费/滑点;引擎用 Ledger,纸面用 BookState(同一组字段)。
- execute_day:按"绝对目标(合约, 手数)"生成腿 —— 持有合约 ≠ 目标合约则换月(先平旧、再开新到目标手数),否则单腿调到目标;
  每条腿先预检(缺行情 / 开盘价为空 / 开盘触及涨跌停),换月两腿任一不可成交则两腿都不动(roll_blocked);
  成交价 = 开盘价 ± 滑点跳数 × 跳价;手续费按成交价计。未成交不保留意图:次日按最新目标重新规划。
- mark:按持仓合约自身的结算价盯市;strict 时任何持仓合约缺有限结算价 → LedgerIntegrityError(先检查后改状态)。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from cta.instruments.specs import InstrumentSpec, InstrumentTable


class LedgerIntegrityError(RuntimeError):
    """账本无法安全推进(持仓合约缺有限结算价、状态含非有限值等)。"""


@dataclass
class Position:
    contract: str
    lots: float  # 正多负空
    ref_price: float  # 上次盯市价(结算价)或成交价


@dataclass(frozen=True)
class Quote:
    open: float
    settle: float
    prev_settle: float


class LedgerState(Protocol):
    equity: float
    positions: dict[str, Position]
    realized_pnl: float
    fees_paid: float
    slippage_paid: float


@dataclass
class Ledger:
    equity: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0


def _finite(x: Any) -> bool:
    try:
        return bool(np.isfinite(float(x)))
    except (TypeError, ValueError):
        return False


def quotes_from_frame(day_quotes: pd.DataFrame) -> dict[str, Quote]:
    """index=contract、含 open/settle/prev_settle 列的当日行情表 → {contract: Quote}。"""
    out: dict[str, Quote] = {}
    for c, r in day_quotes.iterrows():
        out[str(c)] = Quote(
            float(r["open"]) if _finite(r["open"]) else float("nan"),
            float(r["settle"]) if _finite(r["settle"]) else float("nan"),
            float(r["prev_settle"]) if _finite(r["prev_settle"]) else float("nan"),
        )
    return out


def limit_prices(prev_settle: float, limit_pct: float) -> tuple[float, float]:
    """涨跌停板价(与 continuous.roll 面板同一公式:前结算 × (1 ± 幅度),不做跳价取整;比较时留半跳容差)。"""
    return prev_settle * (1 + limit_pct), prev_settle * (1 - limit_pct)


def leg_block(q: Quote | None, delta: float, sp: InstrumentSpec) -> str | None:
    """这条腿今天不能成交的原因;None 表示可以成交。"""
    if q is None or not _finite(q.open):
        return "no_quote"  # 缺行情,或当日零成交/停牌(交易所文件 open 为空,如 2022-03-10 NI2204)
    if _finite(q.prev_settle):
        up, dn = limit_prices(q.prev_settle, sp.limit_pct)
        tol = 0.5 * sp.tick if _finite(sp.tick) else 0.0
        if (delta > 0 and q.open >= up - tol - 1e-9) or (delta < 0 and q.open <= dn + tol + 1e-9):
            return "limit_locked"
    return None


def apply_fill(
    state: LedgerState, symbol: str, contract: str, delta: float, price: float, mult: float
) -> float:
    """把一笔成交记入持仓;返回本笔实现的盈亏(元,不含手续费;平仓部分相对 ref_price 结算)。"""
    pos = state.positions.get(symbol)
    if pos is None or pos.lots == 0 or pos.contract != contract:
        if pos is not None and pos.lots != 0 and pos.contract != contract:
            raise LedgerIntegrityError(f"{symbol}: cannot open {contract} while holding {pos.contract}")
        state.positions[symbol] = Position(contract, delta, price)
        return 0.0
    new_lots = pos.lots + delta
    if np.sign(new_lots) == np.sign(pos.lots) and abs(new_lots) > abs(pos.lots):  # 加仓:参考价加权
        pos.ref_price = (pos.ref_price * pos.lots + price * delta) / new_lots
        pos.lots = new_lots
        return 0.0
    closed = -delta if abs(delta) <= abs(pos.lots) else pos.lots  # 减仓/反手:平掉的部分按 ref_price 结算
    pnl = closed * (price - pos.ref_price) * mult
    state.equity += pnl
    state.realized_pnl += pnl
    remain = pos.lots - closed
    if remain == 0 and new_lots != 0:  # 反手:剩余以成交价新开
        pos.lots, pos.ref_price = new_lots, price
    elif remain == 0:
        del state.positions[symbol]
    else:
        pos.lots = remain
    return pnl


def execute_day(
    state: LedgerState,
    plan: Mapping[str, tuple[str, float]],
    quotes: Mapping[str, Quote],
    specs: InstrumentTable,
    slippage_ticks: float,
    date: pd.Timestamp,
) -> list[dict[str, Any]]:
    """按绝对目标 {symbol: (合约, 手数)} 在 date 开盘执行;返回成交/未成交记录(每腿一行)。"""
    fills: list[dict[str, Any]] = []
    for s, (tgt_c, want) in plan.items():
        sp = specs[s]
        pos = state.positions.get(s)
        roll = pos is not None and pos.lots != 0 and pos.contract != tgt_c
        if pos is not None and roll:
            legs = [(pos.contract, -pos.lots, "roll_close"), (tgt_c, want, "roll_open")]
        else:
            held = pos.lots if pos is not None else 0.0
            legs = [(tgt_c, want - held, "rebalance")]
        legs = [leg for leg in legs if leg[1] != 0]
        blocks = {c: leg_block(quotes.get(c), d, sp) for c, d, _ in legs}
        blocked = [c for c, b in blocks.items() if b]
        if blocked:
            status = "roll_blocked" if len(legs) == 2 else str(blocks[blocked[0]])
            for c, d, leg in legs:
                fills.append(
                    {
                        "date": date,
                        "symbol": s,
                        "contract": c,
                        "lots": d,
                        "status": status,
                        "reason": blocks[c] or f"other_leg:{blocks[blocked[0]]}",
                        "leg": leg,
                    }
                )
            continue
        for c, d, leg in legs:
            q = quotes[c]
            fill_px = q.open + float(np.sign(d)) * slippage_ticks * sp.tick
            fee = sp.fee(fill_px, d)
            slip = sp.slippage(d, slippage_ticks)
            pnl = apply_fill(state, s, c, d, fill_px, sp.multiplier)
            state.fees_paid += fee
            state.slippage_paid += slip
            state.equity -= fee
            fills.append(
                {
                    "date": date,
                    "symbol": s,
                    "contract": c,
                    "lots": d,
                    "status": "filled",
                    "reason": "",
                    "leg": leg,
                    "price": fill_px,
                    "fee": fee,
                    "slippage": slip,
                    "realized_pnl": pnl,
                }
            )
    return fills


def mark(
    state: LedgerState,
    quotes: Mapping[str, Quote],
    specs: InstrumentTable,
    strict: bool,
) -> tuple[dict[str, float], list[str]]:
    """按持仓合约自身的结算价盯市。返回 (逐品种盯市盈亏, 缺有限结算价的持仓);strict 时后者非空即抛错且不改状态。"""
    missing = [
        f"{s}:{pos.contract}"
        for s, pos in state.positions.items()
        if pos.lots != 0 and (pos.contract not in quotes or not _finite(quotes[pos.contract].settle))
    ]
    if strict and missing:
        raise LedgerIntegrityError(f"held contracts without a finite settlement price: {missing}")
    pnl: dict[str, float] = {}
    for s, pos in list(state.positions.items()):
        if pos.lots == 0:
            del state.positions[s]
            continue
        q = quotes.get(pos.contract)
        if q is None or not _finite(q.settle):
            continue
        p = pos.lots * (q.settle - pos.ref_price) * specs[s].multiplier
        pos.ref_price = q.settle
        state.equity += p
        pnl[s] = p
    return pnl, missing


def margin_used(state: LedgerState, quotes: Mapping[str, Quote], specs: InstrumentTable) -> float:
    tot = 0.0
    for s, pos in state.positions.items():
        q = quotes.get(pos.contract)
        if q is not None and _finite(q.settle):
            tot += specs[s].margin(q.settle, abs(pos.lots))
    return tot


def assert_finite(state: LedgerState) -> None:
    bad = [
        k for k in ("equity", "realized_pnl", "fees_paid", "slippage_paid") if not _finite(getattr(state, k))
    ]
    bad += [
        f"positions[{s}]"
        for s, p in state.positions.items()
        if not (_finite(p.lots) and _finite(p.ref_price))
    ]
    if bad:
        raise LedgerIntegrityError(f"non-finite ledger state: {bad}")
