"""纸面账本:持仓、现金、逐日盯市;成交模拟规则与回测引擎一致(次日开盘 + 滑点 + 手续费,开盘触及涨跌停则顺延)。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.instruments.specs import InstrumentTable
from cta.live.orders import _num

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "paper"


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
        self.state_path.write_text(self.state.to_json(), encoding="utf-8")

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
    def fill_orders(
        self,
        orders: pd.DataFrame,
        day_quotes: pd.DataFrame,
        specs: InstrumentTable,
        date: pd.Timestamp,
        slippage_ticks: float,
    ) -> pd.DataFrame:
        """按 date 日开盘价成交上一交易日生成的订单。day_quotes:该日各合约行情(index=contract,含 open、prev_settle、limit_up/limit_down 可缺)。
        规则:换月先平旧合约再开新合约;开盘价触及涨跌停(按 prev_settle × limit_pct 自算)则该腿顺延(记 unfilled)。"""
        fills: list[dict[str, Any]] = []
        for _, o in orders.iterrows():
            s = str(o["symbol"])
            sp = specs[s]
            tgt_c, want = str(o["target_contract"]), float(o["target_lots"])
            pos = self.state.positions.get(s)
            legs: list[tuple[str, float]] = []  # (contract, delta_lots)
            if pos is not None and pos.lots != 0 and pos.contract != tgt_c:
                legs.append((pos.contract, -pos.lots))
                legs.append((tgt_c, want))
            else:
                held = pos.lots if pos is not None else 0.0
                if want != held:
                    legs.append((tgt_c, want - held))
            for c, delta in legs:
                if delta == 0 or c not in day_quotes.index:
                    if delta != 0:
                        fills.append(
                            {"date": date, "symbol": s, "contract": c, "lots": delta, "status": "no_quote"}
                        )
                    continue
                q = day_quotes.loc[c]
                px = _num(q["open"])
                prev = _num(q["prev_settle"]) if not np.isnan(_num(q["prev_settle"])) else np.nan
                if not np.isnan(prev):
                    up, dn = prev * (1 + sp.limit_pct), prev * (1 - sp.limit_pct)
                    if (delta > 0 and px >= up * 0.999) or (delta < 0 and px <= dn * 1.001):
                        fills.append(
                            {
                                "date": date,
                                "symbol": s,
                                "contract": c,
                                "lots": delta,
                                "status": "limit_locked",
                            }
                        )
                        continue
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
        """按结算价盯市:equity += lots × (settle − ref) × mult;ref 更新为结算价。"""
        pnl_by_symbol: dict[str, float] = {}
        for s, pos in list(self.state.positions.items()):
            if pos.lots == 0:
                del self.state.positions[s]
                continue
            if pos.contract not in day_quotes.index:
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
        p = self.root / "equity.csv"
        row = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(date).date(),
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
        row.to_csv(p, mode="a", header=not p.exists(), index=False)
