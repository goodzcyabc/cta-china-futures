"""纸面交易日步:拉当日交易所数据 → 成交昨日订单并盯市 → 以今日为 as-of 生成新订单。可补跑漏掉的交易日(catchup)。"""

from __future__ import annotations

import importlib
import json
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from cta.config import StrategyConfig, load_config
from cta.data.exchanges.base import Store
from cta.data.exchanges.source import ExchangeSource, default_stitched
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable, load_instruments
from cta.live.orders import generate_orders
from cta.paper.book import DEFAULT_DIR, PaperBook

EXCHANGE_MODULES = {
    "SHFE": "cta.data.exchanges.shfe",
    "INE": "cta.data.exchanges.ine",
    "CZCE": "cta.data.exchanges.czce",
    "DCE": "cta.data.exchanges.dce",
}


def ingest_all(
    date: pd.Timestamp, kinds: tuple[str, ...] = ("quotes", "positions", "receipts")
) -> dict[str, str]:
    """调用各交易所模块的 ingest_day;模块缺失或抓取失败只记录,不中断(当日缺某交易所数据时该所品种沿用旧数据并被标记 stale)。"""
    status: dict[str, str] = {}
    for exch, mod in EXCHANGE_MODULES.items():
        try:
            m = importlib.import_module(mod)
            m.ingest_day(date, kinds)
            status[exch] = "ok"
        except ModuleNotFoundError:
            status[exch] = "module_missing"
        except Exception as e:  # noqa: BLE001
            status[exch] = f"error: {type(e).__name__}: {e}"[:200]
    return status


def _day_quotes(ex: ExchangeSource, date: pd.Timestamp) -> pd.DataFrame:
    q = ex.quotes()
    d = q[q["date"] == pd.Timestamp(date)]
    return d.set_index("contract")


def step(
    date: pd.Timestamp,
    cfg: StrategyConfig | None = None,
    specs: InstrumentTable | None = None,
    src: DataSource | None = None,
    ex: ExchangeSource | None = None,
    paper_dir: Path | None = None,
    rq_root: Path = Path("data/ricecta/data"),
    do_ingest: bool = True,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    specs = specs or load_instruments()
    date = pd.Timestamp(date)
    log: dict[str, Any] = {"date": str(date.date())}
    if do_ingest:
        log["ingest"] = ingest_all(date)
    ex = ex or ExchangeSource(Store(), specs=specs)
    src = src or default_stitched(rq_root)
    book = PaperBook(paper_dir or DEFAULT_DIR, initial_capital=cfg.backtest.initial_capital_cny)
    dq = _day_quotes(ex, date)
    if dq.empty:
        log["skipped"] = "no exchange quotes for this date (holiday or data not yet published)"
        return log
    if book.state.last_settled is not None and pd.Timestamp(book.state.last_settled) >= date:
        log["skipped"] = f"already settled {book.state.last_settled}"
        return log
    # 1) 成交待处理订单(上一交易日 as-of 生成)
    if book.state.pending_orders_date:
        op = book.root / "orders" / book.state.pending_orders_date / "orders.csv"
        if op.exists():
            orders = pd.read_csv(op, dtype={"symbol": str, "target_contract": str, "held_contract": str})
            fills = book.fill_orders(orders, dq, specs, date, cfg.execution.slippage_ticks)
            fdir = book.root / "fills"
            fdir.mkdir(exist_ok=True)
            fills.to_csv(fdir / f"{date.date()}.csv", index=False)
            n_filled = int((fills["status"] == "filled").sum()) if "status" in fills.columns else 0
            log["fills"] = {"n": int(len(fills)), "filled": n_filled}
        book.state.pending_orders_date = None
    # 2) 盯市
    pnl = book.mark_to_market(dq, specs, date)
    margin = book.margin_used(dq, specs)
    book.append_equity(date, pnl, margin)
    # 3) 生成今日订单(as-of = date)
    out_dir = book.root / "orders"
    try:
        meta = generate_orders(
            cfg, src, specs, str(date.date()), book.state.equity, book.positions_csv(), out_dir
        )
        book.state.pending_orders_date = str(date.date())
        log["orders"] = {
            k: meta[k]
            for k in ("n_symbols", "n_trades", "n_rolls", "est_margin_usage", "stale_symbols")
            if k in meta
        }
    except Exception as e:  # noqa: BLE001
        log["orders_error"] = f"{type(e).__name__}: {e}"
        log["traceback"] = traceback.format_exc()[-1500:]
    book.save()
    log["equity"] = book.state.equity
    log["positions"] = {s: [p.contract, p.lots] for s, p in book.state.positions.items()}
    (book.root / "log").mkdir(exist_ok=True)
    (book.root / "log" / f"{date.date()}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return log


def catchup(end: pd.Timestamp, **kw: Any) -> list[dict[str, Any]]:
    """从账本最后盯市日之后的第一个交易日补跑到 end(含);逐日调用 step。"""
    cfg = kw.get("cfg") or load_config()
    specs = kw.get("specs") or load_instruments()
    book = PaperBook(kw.get("paper_dir") or DEFAULT_DIR, initial_capital=cfg.backtest.initial_capital_cny)
    start = (
        pd.Timestamp(book.state.last_settled) + pd.Timedelta(days=1)
        if book.state.last_settled
        else pd.Timestamp(end)
    )
    out = []
    for d in pd.bdate_range(start, pd.Timestamp(end)):
        out.append(
            step(d, cfg=cfg, specs=specs, **{k: v for k, v in kw.items() if k not in ("cfg", "specs")})
        )
    return out
