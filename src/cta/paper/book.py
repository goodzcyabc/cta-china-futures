"""纸面账本:持仓、现金、逐日盯市;成交模拟规则与回测引擎一致(次日开盘 + 滑点 + 手续费,开盘触及涨跌停则该单当日不成交)。

防线(2026-09-22 起,见 docs/design_log.md 十七):
- 非有限开盘价(当日零成交/停牌,交易所文件 open 为空)一律不成交,记 no_quote。此前会按 NaN 价"成交"并把权益永久污染成 NaN。
- 换月两腿先预检再统一执行:任一腿不可成交则两腿都不动(roll_blocked),既不会"旧腿已平、新腿未开"留下空仓,也不会抛异常。
- 盯市要求每个持仓合约都有有限结算价,否则抛 BookIntegrityError → 整日失败、状态不落盘。
- 落盘前 assert_finite;equity.csv 按日期去重(重跑同一日不产生重复行);state.json 原子写入。
未成交的意图不需要"顺延":订单是绝对目标手数,次日按最新信号与真实持仓重新出单。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.instruments.specs import InstrumentSpec, InstrumentTable
from cta.live.orders import _num

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "paper"


class BookIntegrityError(RuntimeError):
    """账本无法安全推进(持仓合约缺有限结算价、状态含非有限值等);抛出即整日失败。"""


def _finite(x: Any) -> bool:
    try:
        return bool(np.isfinite(float(x)))
    except (TypeError, ValueError):
        return False


@dataclass
class Position:
    contract: str
    lots: float  # 正多负空
    ref_price: float  # 上次盯市价(结算价)或成交价


@dataclass
class BookState:
    equity: float
    cash_start: float
    last_settled: str | None = None  # 最近完成盯市的交易日
    pending_orders_date: str | None = None  # 待成交订单的生成日(在下一交易日开盘成交)
    positions: dict[str, Position] = field(default_factory=dict)  # symbol -> Position
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    slippage_paid: float = 0.0

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> BookState:
        d = json.loads(s)
        d["positions"] = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        return cls(**d)

    def assert_finite(self) -> None:
        bad = [
            k
            for k in ("equity", "cash_start", "realized_pnl", "fees_paid", "slippage_paid")
            if not _finite(getattr(self, k))
        ]
        bad += [
            f"positions[{s}]"
            for s, p in self.positions.items()
            if not (_finite(p.lots) and _finite(p.ref_price))
        ]
        if bad:
            raise BookIntegrityError(f"non-finite book state: {bad}")


class PaperBook:
    def __init__(self, root: Path | None = None, initial_capital: float = 3_000_000.0):
        self.root = root or DEFAULT_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        if self.state_path.exists():
            self.state = BookState.from_json(self.state_path.read_text(encoding="utf-8"))
        else:
            self.state = BookState(equity=initial_capital, cash_start=initial_capital)
            self.save()

    def save(self) -> None:
        """原子写入:先校验有限值,再写临时文件并 rename;进程中途退出不会留下半个或被污染的 state.json。"""
        self.state.assert_finite()
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(self.state.to_json(), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def positions_csv(self) -> Path:
        """给 generate_orders 用的当前持仓文件。"""
        p = self.root / "positions.csv"
        rows = [
            {"symbol": s, "contract": pos.contract, "lots": pos.lots}
            for s, pos in self.state.positions.items()
        ]
        pd.DataFrame(rows, columns=["symbol", "contract", "lots"]).to_csv(p, index=False)
        return p

    # ---- 成交与盯市 ----
    @staticmethod
    def _leg_block(contract: str, delta: float, day_quotes: pd.DataFrame, sp: InstrumentSpec) -> str | None:
        """这条腿今天不能成交的原因;None 表示可以成交。"""
        if contract not in day_quotes.index:
            return "no_quote"
        q = day_quotes.loc[contract]
        px = _num(q["open"])
        if not np.isfinite(px):
            return "no_quote"  # 当日零成交/停牌:交易所文件 open 为空(如 2022-03-10 NI2204)
        prev = _num(q["prev_settle"])
        if np.isfinite(prev):
            up, dn = prev * (1 + sp.limit_pct), prev * (1 - sp.limit_pct)
            if (delta > 0 and px >= up * 0.999) or (delta < 0 and px <= dn * 1.001):
                return "limit_locked"
        return None

    def fill_orders(
        self,
        orders: pd.DataFrame,
        day_quotes: pd.DataFrame,
        specs: InstrumentTable,
        date: pd.Timestamp,
        slippage_ticks: float,
    ) -> pd.DataFrame:
        """按 date 日开盘价成交上一交易日生成的订单。day_quotes:该日各合约行情(index=contract,含 open、prev_settle)。
        规则:换月两腿先预检、任一腿不可成交则整个换月不动(roll_blocked);单腿不可成交记 no_quote / limit_locked。
        不成交的目标不保留:次日订单按最新信号与真实持仓重新生成。"""
        fills: list[dict[str, Any]] = []
        for _, o in orders.iterrows():
            s = str(o["symbol"])
            sp = specs[s]
            tgt_c, want = str(o["target_contract"]), float(o["target_lots"])
            pos = self.state.positions.get(s)
            roll = pos is not None and pos.lots != 0 and pos.contract != tgt_c
            if pos is not None and roll:
                legs = [(pos.contract, -pos.lots), (tgt_c, want)]
            else:
                held = pos.lots if pos is not None else 0.0
                legs = [(tgt_c, want - held)]
            legs = [(c, d) for c, d in legs if d != 0]
            blocks = {c: self._leg_block(c, d, day_quotes, sp) for c, d in legs}
            blocked = [c for c, b in blocks.items() if b]
            if blocked:
                # 换月两腿同进退:任一腿不可成交,两腿都不动(明日按最新目标重出)
                status = "roll_blocked" if len(legs) == 2 else str(blocks[blocked[0]])
                for c, d in legs:
                    fills.append(
                        {
                            "date": date,
                            "symbol": s,
                            "contract": c,
                            "lots": d,
                            "status": status,
                            "reason": blocks[c] or f"other_leg:{blocks[blocked[0]]}",
                        }
                    )
                continue
            for c, delta in legs:
                px = _num(day_quotes.loc[c, "open"])
                slip = sp.slippage(delta, slippage_ticks)
                fee = sp.fee(px, delta)
                fill_px = px + np.sign(delta) * slippage_ticks * sp.tick
                self._apply_fill(s, c, delta, fill_px, sp.multiplier)
                self.state.fees_paid += fee
                self.state.slippage_paid += slip
                self.state.equity -= fee
                fills.append(
                    {
                        "date": date,
                        "symbol": s,
                        "contract": c,
                        "lots": delta,
                        "status": "filled",
                        "reason": "",
                        "price": fill_px,
                        "fee": fee,
                        "slippage": slip,
                    }
                )
        return pd.DataFrame(fills)

    def _apply_fill(self, symbol: str, contract: str, delta: float, price: float, mult: float) -> None:
        pos = self.state.positions.get(symbol)
        if pos is None or pos.lots == 0 or pos.contract != contract:
            if pos is not None and pos.lots != 0 and pos.contract != contract:
                raise RuntimeError(f"{symbol}: cannot open {contract} while holding {pos.contract}")
            self.state.positions[symbol] = Position(contract, delta, price)
            return
        # 同合约加减仓:先结清被平掉部分相对 ref_price 的盈亏(盯市口径),ref 更新为加权价
        new_lots = pos.lots + delta
        if np.sign(new_lots) == np.sign(pos.lots) and abs(new_lots) > abs(pos.lots):  # 加仓
            pos.ref_price = (pos.ref_price * pos.lots + price * delta) / new_lots
            pos.lots = new_lots
        else:  # 减仓/反手:平掉的部分按 ref_price 结算
            closed = -delta if abs(delta) <= abs(pos.lots) else pos.lots
            pnl = closed * (price - pos.ref_price) * mult
            self.state.equity += pnl
            self.state.realized_pnl += pnl
            remain = pos.lots - closed
            if remain == 0 and new_lots != 0:  # 反手:剩余以成交价新开
                pos.lots, pos.ref_price = new_lots, price
            elif remain == 0:
                del self.state.positions[symbol]
            else:
                pos.lots = remain

    def mark_to_market(
        self, day_quotes: pd.DataFrame, specs: InstrumentTable, date: pd.Timestamp
    ) -> dict[str, float]:
        """按结算价盯市:equity += lots × (settle − ref) × mult;ref 更新为结算价。
        任何持仓合约缺行情或结算价非有限 → BookIntegrityError(整日失败,不允许"当天零盈亏"糊过去)。"""
        missing = [
            f"{s}:{pos.contract}"
            for s, pos in self.state.positions.items()
            if pos.lots != 0
            and (pos.contract not in day_quotes.index or not _finite(day_quotes.loc[pos.contract, "settle"]))
        ]
        if missing:
            raise BookIntegrityError(
                f"{pd.Timestamp(date).date()}: held contracts without a finite settlement price: {missing}"
            )
        pnl_by_symbol: dict[str, float] = {}
        for s, pos in list(self.state.positions.items()):
            if pos.lots == 0:
                del self.state.positions[s]
                continue
            settle = _num(day_quotes.loc[pos.contract, "settle"])
            pnl = pos.lots * (settle - pos.ref_price) * specs[s].multiplier
            pos.ref_price = settle
            self.state.equity += pnl
            pnl_by_symbol[s] = pnl
        self.state.last_settled = str(pd.Timestamp(date).date())
        return pnl_by_symbol

    def margin_used(self, day_quotes: pd.DataFrame, specs: InstrumentTable) -> float:
        tot = 0.0
        for s, pos in self.state.positions.items():
            if pos.contract in day_quotes.index:
                tot += specs[s].margin(_num(day_quotes.loc[pos.contract, "settle"]), abs(pos.lots))
        return tot

    def append_equity(self, date: pd.Timestamp, pnl_by_symbol: dict[str, float], margin: float) -> None:
        """追加当日权益行;同一日期重跑时替换旧行(幂等),不会出现重复行。"""
        p = self.root / "equity.csv"
        day = str(pd.Timestamp(date).date())
        row = pd.DataFrame(
            [
                {
                    "date": day,
                    "equity": self.state.equity,
                    "realized_pnl": self.state.realized_pnl,
                    "fees_paid": self.state.fees_paid,
                    "slippage_paid": self.state.slippage_paid,
                    "margin_used": margin,
                    "n_positions": len(self.state.positions),
                    "pnl_by_symbol": json.dumps(
                        {k: round(v, 2) for k, v in pnl_by_symbol.items()}, ensure_ascii=False
                    ),
                }
            ]
        )
        if p.exists():
            old = pd.read_csv(p, dtype=str)
            old = old[old["date"] != day]
            if not old.empty:
                row = pd.concat([old, row.astype(str)], ignore_index=True)
        row.to_csv(p, index=False)
