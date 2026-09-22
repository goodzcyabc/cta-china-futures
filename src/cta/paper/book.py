"""纸面账本:持仓、现金、逐日盯市的落盘外壳;成交与盯市规则全部来自 cta.execution.ledger(与回测引擎同一函数)。

防线(2026-09-22 起,见 docs/design_log.md 十七):
- 非有限开盘价一律不成交(no_quote);换月两腿预检、同进退(roll_blocked);盯市要求每个持仓合约有有限结算价,否则
  BookIntegrityError → 整日失败、状态不落盘;落盘前 assert_finite;equity.csv 按日期去重;state.json 原子写入。
未成交的意图不需要"顺延":订单是绝对目标手数,次日按最新信号与真实持仓重新出单。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from cta.execution import ledger
from cta.execution.ledger import LedgerIntegrityError, Position
from cta.instruments.specs import InstrumentTable

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "paper"
BookIntegrityError = LedgerIntegrityError

__all__ = ["DEFAULT_DIR", "BookIntegrityError", "BookState", "PaperBook", "Position"]


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
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, s: str) -> BookState:
        d = json.loads(s)
        d["positions"] = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        return cls(**d)

    def assert_finite(self) -> None:
        if not ledger._finite(self.cash_start):
            raise BookIntegrityError("non-finite cash_start")
        ledger.assert_finite(self)


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

    def write_state(self, path: Path) -> None:
        """校验有限值后写到 path(原子:临时文件 + rename)。"""
        self.state.assert_finite()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.state.to_json(), encoding="utf-8")
        os.replace(tmp, path)

    def save(self) -> None:
        self.write_state(self.state_path)

    def positions_frame(self) -> pd.DataFrame:
        """当前持仓(index=symbol,列 contract/lots),给 generate_orders 直接用。"""
        rows = [
            {"symbol": s, "contract": pos.contract, "lots": pos.lots}
            for s, pos in self.state.positions.items()
        ]
        return pd.DataFrame(rows, columns=["symbol", "contract", "lots"]).set_index("symbol")

    def positions_csv(self, path: Path | None = None) -> Path:
        p = path or (self.root / "positions.csv")
        self.positions_frame().reset_index().to_csv(p, index=False)
        return p

    # ---- 成交与盯市(规则见 cta.execution.ledger) ----
    def fill_orders(
        self,
        orders: pd.DataFrame,
        day_quotes: pd.DataFrame,
        specs: InstrumentTable,
        date: pd.Timestamp,
        slippage_ticks: float,
    ) -> pd.DataFrame:
        """按 date 日开盘价执行上一交易日的绝对目标(orders: symbol/target_contract/target_lots)。"""
        plan = {
            str(o["symbol"]): (str(o["target_contract"]), float(o["target_lots"]))
            for _, o in orders.iterrows()
        }
        quotes = ledger.quotes_from_frame(day_quotes)
        return pd.DataFrame(ledger.execute_day(self.state, plan, quotes, specs, slippage_ticks, date))

    def mark_to_market(
        self, day_quotes: pd.DataFrame, specs: InstrumentTable, date: pd.Timestamp
    ) -> dict[str, float]:
        """按结算价盯市(strict:持仓合约缺有限结算价即整日失败)。"""
        pnl, _ = ledger.mark(self.state, ledger.quotes_from_frame(day_quotes), specs, strict=True)
        self.state.last_settled = str(pd.Timestamp(date).date())
        return pnl

    def margin_used(self, day_quotes: pd.DataFrame, specs: InstrumentTable) -> float:
        return ledger.margin_used(self.state, ledger.quotes_from_frame(day_quotes), specs)

    def equity_frame(
        self, date: pd.Timestamp, pnl_by_symbol: dict[str, float], margin: float
    ) -> pd.DataFrame:
        """正式 equity.csv 加上当日行之后的完整内容;同一日期重跑时替换旧行(幂等)。"""
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
        return row

    def append_equity(self, date: pd.Timestamp, pnl_by_symbol: dict[str, float], margin: float) -> None:
        p = self.root / "equity.csv"
        tmp = p.with_suffix(".csv.tmp")
        self.equity_frame(date, pnl_by_symbol, margin).to_csv(tmp, index=False)
        os.replace(tmp, p)
