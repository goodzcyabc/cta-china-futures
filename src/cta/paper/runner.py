"""纸面交易日步:拉当日交易所数据 → 成交昨日订单并盯市 → 以今日为 as-of 生成新订单。可补跑漏掉的交易日(catchup)。

日步是"全有或全无"的:成交、盯市、出单全部成功才写 fills/equity/state;任一步失败则抛 PaperStepError、
写 <book>/FAILED.json(阶段 + 原因)、state.json 不变。修复后重跑同一日幂等(fills 覆盖、equity 按日去重)。
交易日判定只看"周一至周五 ∧ 不在 configs/holidays.csv":真实休市但未登记的日子会失败而不是静默跳过,提醒补日历。"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.config import StrategyConfig, load_config
from cta.data.exchanges.base import Kind, Store
from cta.data.exchanges.calendar import load_holidays
from cta.data.exchanges.source import ExchangeSource, default_stitched
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable, load_instruments
from cta.live.orders import generate_orders
from cta.paper.book import DEFAULT_DIR, BookIntegrityError, PaperBook

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
    date: pd.Timestamp,
    kinds: tuple[Kind, ...] = ("quotes", "positions", "receipts", "params"),
    force: bool = False,
) -> dict[str, str]:
    """拉四家交易所某日数据。北京 16:30 前不拉当天(盘中快照);盘中快照即使拉到也会被 NotFinalError 拒绝。
    单个交易所失败只记录不中断:该所品种当日无数据 → 出单时视为 stale、持仓保持不动。
    "params"(每日风控参数,监管事件覆盖层的事件源)由 params 模块三所直连;大商所需浏览器,跳过并记录。"""
    status: dict[str, str] = {}
    if not force and not settlement_published(date):
        return dict.fromkeys(("SHFE", "INE", "CZCE", "DCE"), "not_settled_yet")
    from cta.data.exchanges import czce, dce, ine, shfe
    from cta.data.exchanges import params as exparams
    from cta.data.exchanges.base import NotFinalError

    base_kinds = tuple(k for k in kinds if k != "params")
    for exch, fn in (("SHFE", shfe.ingest_day), ("INE", ine.ingest_day), ("CZCE", czce.ingest_day)):
        try:
            status[exch] = ",".join(f"{k}:{v}" for k, v in fn(date, base_kinds).items())
        except NotFinalError as e:
            status[exch] = f"not_final: {e}"[:200]
        except Exception as e:  # noqa: BLE001
            status[exch] = f"error: {type(e).__name__}: {e}"[:200]
    if base_kinds:
        try:
            with dce.CdpSession() as sess:  # 大商所需要浏览器会话(web-access CDP proxy)
                parts = [f"{k}:{dce.ingest_day(date, k, sess)}" for k in base_kinds]
            status["DCE"] = ",".join(parts)
        except Exception as e:  # noqa: BLE001
            status["DCE"] = f"error: {type(e).__name__}: {e}"[:200]
    if "params" in kinds:
        try:
            res = exparams.ingest_day(date, exparams.EXCHANGES)
        except Exception as e:  # noqa: BLE001
            res = dict.fromkeys(exparams.EXCHANGES, f"error: {type(e).__name__}: {e}"[:200])
        res["DCE"] = "skipped_needs_browser"
        for exch, v in res.items():
            status[exch] = ",".join(x for x in (status.get(exch, ""), f"params:{v}") if x)
    return status


class PaperStepError(RuntimeError):
    """日步失败:当日状态未落盘(state.json 不变),修复后重跑同一日即可;<book>/FAILED.json 记录阶段与原因。"""


FAILED_MARKER = "FAILED.json"


def is_trading_day(date: pd.Timestamp, holidays: pd.DatetimeIndex | None = None) -> bool:
    """周一至周五且不在公告休市日(configs/holidays.csv)里。"""
    d = pd.Timestamp(date).normalize()
    hol = holidays if holidays is not None else load_holidays()
    return d.weekday() < 5 and d not in hol


def _day_quotes(ex: ExchangeSource, date: pd.Timestamp) -> pd.DataFrame:
    q = ex.quotes()
    d = q[q["date"] == pd.Timestamp(date)]
    return d.set_index("contract")


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def step(
    date: pd.Timestamp,
    cfg: StrategyConfig | None = None,
    specs: InstrumentTable | None = None,
    src: DataSource | None = None,
    ex: ExchangeSource | None = None,
    paper_dir: Path | None = None,
    rq_root: Path = Path("data/ricecta/data"),
    do_ingest: bool = True,
    holidays: pd.DatetimeIndex | None = None,
) -> dict[str, Any]:
    cfg = cfg or load_config()
    specs = specs or load_instruments()
    date = pd.Timestamp(date).normalize()
    log: dict[str, Any] = {"date": str(date.date())}
    if not settlement_published(date):
        log["skipped"] = f"{date.date()} settlement not published yet (Beijing {beijing_now():%H:%M})"
        return log
    if not is_trading_day(date, holidays):
        log["skipped"] = "not a trading day (weekend or configs/holidays.csv)"
        return log
    if do_ingest:
        log["ingest"] = ingest_all(date)
    ex = ex or ExchangeSource(Store(), specs=specs)
    book = PaperBook(paper_dir or DEFAULT_DIR, initial_capital=cfg.backtest.initial_capital_cny)
    if book.state.last_settled is not None and pd.Timestamp(book.state.last_settled) >= date:
        log["skipped"] = f"already settled {book.state.last_settled}"
        return log
    stage = "quotes"
    try:
        dq = _day_quotes(ex, date)
        if dq.empty:
            raise PaperStepError(
                "trading day but no exchange quotes on disk "
                "(data late, ingest failed, or holiday missing from configs/holidays.csv)"
            )
        # 1) 成交待处理订单(上一交易日 as-of 生成)—— 只改内存,不落盘
        stage = "fill"
        fills: pd.DataFrame | None = None
        if book.state.pending_orders_date:
            op = book.root / "orders" / book.state.pending_orders_date / "orders.csv"
            if not op.exists():
                raise PaperStepError(f"pending orders file missing: {op}")
            orders = pd.read_csv(op, dtype={"symbol": str, "target_contract": str, "held_contract": str})
            fills = book.fill_orders(orders, dq, specs, date, cfg.execution.slippage_ticks)
            n_filled = int((fills["status"] == "filled").sum()) if "status" in fills.columns else 0
            log["fills"] = {"n": int(len(fills)), "filled": n_filled, "blocked": int(len(fills)) - n_filled}
            book.state.pending_orders_date = None
        # 2) 盯市:每个持仓合约必须有有限结算价;状态必须全为有限值
        stage = "settle"
        pnl = book.mark_to_market(dq, specs, date)
        margin = book.margin_used(dq, specs)
        if not np.isfinite(margin):
            raise BookIntegrityError(f"{date.date()}: non-finite margin {margin}")
        book.state.assert_finite()
        # 3) 生成今日订单(as-of = date);失败即整日失败,不再吞掉
        stage = "orders"
        src = src or default_stitched(rq_root)
        meta = generate_orders(
            cfg, src, specs, str(date.date()), book.state.equity, book.positions_csv(), book.root / "orders"
        )
        summary = meta.get("summary", meta)
        log["orders"] = {
            k: summary[k]
            for k in ("n_symbols", "n_trades", "n_rolls", "est_margin_usage", "stale_symbols", "warning")
            if k in summary and summary[k] is not None
        }
        # 4) 全部成功后才落盘:fills(覆盖)→ equity(按日去重)→ state(原子)
        stage = "save"
        if fills is not None:
            fdir = book.root / "fills"
            fdir.mkdir(exist_ok=True)
            fills.to_csv(fdir / f"{date.date()}.csv", index=False)
        book.append_equity(date, pnl, margin)
        book.state.pending_orders_date = str(date.date())
        book.save()
        marker = book.root / FAILED_MARKER
        if marker.exists():
            marker.unlink()
    except Exception as e:
        failure = {
            "date": str(date.date()),
            "stage": stage,
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-2000:],
        }
        _write_json(book.root / FAILED_MARKER, failure)
        log["failed"] = {"stage": stage, "error": failure["error"]}
        _write_json(book.root / "log" / f"{date.date()}.json", log)
        raise PaperStepError(
            f"{book.root.name} {date.date()} failed at stage '{stage}': {failure['error']}"
        ) from e
    log["equity"] = book.state.equity
    log["positions"] = {s: [p.contract, p.lots] for s, p in book.state.positions.items()}
    _write_json(book.root / "log" / f"{date.date()}.json", log)
    return log


def catchup(end: pd.Timestamp, **kw: Any) -> list[dict[str, Any]]:
    """从账本最后盯市日之后的第一个交易日补跑到 end(含);逐日调用 step,任一日失败即中止(异常上抛),不跳过。"""
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
