"""纸面交易日步:拉当日交易所数据 → 成交昨日订单并盯市 → 以今日为 as-of 生成新订单。可补跑漏掉的交易日(catchup)。"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import pandas as pd

from cta.config import StrategyConfig, load_config
from cta.data.exchanges.base import Kind, Store
from cta.data.exchanges.source import ExchangeSource, default_stitched
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable, load_instruments
from cta.live.orders import generate_orders
from cta.paper.book import DEFAULT_DIR, PaperBook

SETTLE_TIME_BEIJING = "16:30"  # 三所日行情/结算价在收盘结算后发布;此前网站上的"当日文件"是盘中快照


def beijing_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)


def settlement_published(date: pd.Timestamp, now: pd.Timestamp | None = None) -> bool:
    """date 的结算数据是否应已发布:date 早于今天(北京)为真;等于今天须过 SETTLE_TIME_BEIJING;晚于今天为假。"""
    now = now if now is not None else beijing_now()
    d = pd.Timestamp(date).normalize()
    if d < now.normalize():
        return True
    if d > now.normalize():
        return False
    hh, mm = (int(x) for x in SETTLE_TIME_BEIJING.split(":"))
    return bool(now >= d + pd.Timedelta(hours=hh, minutes=mm))


def ingest_all(
    date: pd.Timestamp, kinds: tuple[Kind, ...] = ("quotes", "positions", "receipts"), force: bool = False
) -> dict[str, str]:
    """拉四家交易所某日数据。北京 16:30 前不拉当天(盘中快照);盘中快照即使拉到也会被 NotFinalError 拒绝。
    单个交易所失败只记录不中断:该所品种当日无数据 → 出单时视为 stale、持仓保持不动。"""
    status: dict[str, str] = {}
    if not force and not settlement_published(date):
        return dict.fromkeys(("SHFE", "INE", "CZCE", "DCE"), "not_settled_yet")
    from cta.data.exchanges import czce, dce, ine, shfe
    from cta.data.exchanges.base import NotFinalError

    for exch, fn in (("SHFE", shfe.ingest_day), ("INE", ine.ingest_day), ("CZCE", czce.ingest_day)):
        try:
            status[exch] = ",".join(f"{k}:{v}" for k, v in fn(date, kinds).items())
        except NotFinalError as e:
            status[exch] = f"not_final: {e}"[:200]
        except Exception as e:  # noqa: BLE001
            status[exch] = f"error: {type(e).__name__}: {e}"[:200]
    try:
        with dce.CdpSession() as sess:  # 大商所需要浏览器会话(web-access CDP proxy)
            parts = [f"{k}:{dce.ingest_day(date, k, sess)}" for k in kinds]
        status["DCE"] = ",".join(parts)
    except Exception as e:  # noqa: BLE001
        status["DCE"] = f"error: {type(e).__name__}: {e}"[:200]
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
    if not settlement_published(date):
        log["skipped"] = f"{date.date()} settlement not published yet (Beijing {beijing_now():%H:%M})"
        return log
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
        summary = meta.get("summary", meta)
        log["orders"] = {
            k: summary[k]
            for k in ("n_symbols", "n_trades", "n_rolls", "est_margin_usage", "stale_symbols")
            if k in summary
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
    kw["cfg"] = cfg
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
