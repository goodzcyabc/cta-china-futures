"""大连商品交易所(DCE)日频公开数据:日行情、会员成交持仓排名、仓单日报。

数据源是大商所新版报表系统 dcereport 的后端接口(http://www.dce.com.cn/dcereport/publicweb/...)。
全站有瑞数类反爬(curl/requests 直接请求返回 412),接口的签名参数由页面 JS 生成,所以这里不手工构造 HTTP 请求,
而是通过本机 CDP Proxy(http://localhost:3456)在用户 Chrome 里新建一个后台 tab 打开 dcereport 页面,
在页面上下文里调用 fetch(),由页面自己的反爬脚本补签名。每次站点请求之间至少间隔 MIN_INTERVAL 秒。

口径(见 docs/data_exchanges_dce.md):
- 交易所公布口径:2020-01-01 起成交量/持仓量由双边改单边(大商所 2019-10-29 通知),首个单边交易日 2020-01-02。
- dcereport 接口(本模块的数据源)把 2020 年前的历史也按单边重述;"历史数据"打包下载(datadownload)则全程双边。
  本仓库存接口原值(全程单边),与米筐导出对账时 2020-01-02 之前米筐值 = 本仓库值 × 2。
- 成交额:接口单位万元,规范化时乘 1e4 转成元。鸡蛋 JD 报价 元/500kg、5 吨/手,乘数 10。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.data.exchanges.base import (
    POSITION_COLS,
    QUOTE_COLS,
    RECEIPT_COLS,
    Store,
    normalize_contract,
    symbol_of,
)

log = logging.getLogger(__name__)

EXCHANGE = "DCE"
KINDS: tuple[str, ...] = ("quotes", "positions", "receipts")
RAW_EXT: dict[str, str] = {"quotes": "json", "positions": "zip", "receipts": "json"}

PROXY_URL = "http://localhost:3456"
SITE = "http://www.dce.com.cn"
# 任意 dcereport 页面都行,只是为了拿到同源页面上下文(cookie + 反爬签名脚本)。
SPA_PAGE = SITE + "/frontend/dcereport/#/zh/dayFuturesQuotation?variety=all&tradeType=1"
API_QUOTES = "/dcereport/publicweb/dailystat/dayQuotes"
API_POSITIONS = "/dcereport/publicweb/dailystat/memberDealPosi/batchDownload"
API_RECEIPTS = "/dcereport/publicweb/dailystat/wbillWeeklyQuotes"
API_TRADEDATE = "/dcereport/publicweb/tradeDateNum"
MIN_INTERVAL = 1.0  # 站点请求最小间隔(秒)

# ---- 口径常量 ----
# 交易所公布数据首个单边交易日(2020-01-01 起改口径,大商所 2019-10-29 通知)
SINGLE_SIDED_SINCE = pd.Timestamp("2020-01-02")
# dcereport 接口把 2020 年前历史也按单边重述(2016-01-04 c1601:接口 1147 手,当年公布/米筐 2294 手)
API_RESTATED_SINGLE_SIDED = True
TURNOVER_UNIT = 1e4  # 接口成交额单位:万元 → 元
# 会员持仓排名:接口和批量下载在此之前只返回空表(2020-07-17 及更早均为空,2020-07-20 起有数据)
POSITIONS_HISTORY_START = pd.Timestamp("2020-07-20")
JD_MULTIPLIER = 10  # 鸡蛋:5 吨/手,报价 元/500kg → 每手 = 价格 × 10

_CODE_RE = re.compile(r"^([A-Za-z]{1,2})(\d{4})$")  # 大商所合约 4 位年月;月均价期货 l2610F 之类不匹配 → 剔除
_POS_FILE_RE = re.compile(r"^(\d{8})_([A-Za-z]{1,2}\d{4})_")
_POS_SECTION = {"成交量": "vol", "持买单量": "long", "持卖单量": "short"}
_TOTAL_LABEL = "合计"


class DceError(RuntimeError):
    pass


# 页面上下文里的 fetch 前半段;{path}/{body} 由 json.dumps 转成 JS 字面量
_FETCH_JS = (
    "(async () => {{ const r = await fetch({path}, {{method: 'POST', credentials: 'include', "
    "headers: {{'Content-Type': 'application/json;charset=UTF-8'}}, body: {body}}}); "
)


def _num(v: Any) -> float:
    """接口里的数字可能是 None、数值或带千分位的字符串。"""
    if v is None:
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _ymd(date: pd.Timestamp) -> str:
    return pd.Timestamp(date).strftime("%Y%m%d")


# --------------------------------------------------------------------------------------
# CDP 会话:在用户 Chrome 里开一个后台 tab,在页面上下文里发请求
# --------------------------------------------------------------------------------------
class CdpSession:
    """通过 web-access skill 的 CDP Proxy 操作一个自己新建的 tab;结束时 close()。"""

    def __init__(self, proxy: str = PROXY_URL, page: str = SPA_PAGE, min_interval: float = MIN_INTERVAL):
        self.proxy = proxy.rstrip("/")
        self.page = page
        self.min_interval = min_interval
        self.target: str | None = None
        self._last_request = 0.0
        self.requests_made = 0

    # -- proxy 基础调用 --
    def _call(self, path: str, data: str | None = None, timeout: float = 150.0) -> dict[str, Any]:
        body = data.encode("utf-8") if data is not None else None
        req = urllib.request.Request(
            self.proxy + path, data=body, method="POST" if body is not None else "GET"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 本机 proxy
            payload: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return payload

    def open(self) -> None:
        r = self._call("/new?url=" + urllib.parse.quote(self.page, safe=""))
        self.target = str(r["targetId"])
        for _ in range(40):
            info = self._call(f"/info?target={self.target}")
            if info.get("ready") == "complete" and "dce.com.cn" in str(info.get("url", "")):
                break
            time.sleep(0.5)
        time.sleep(1.0)  # 让页面自己的反爬脚本初始化

    def close(self) -> None:
        if self.target:
            try:
                self._call(f"/close?target={self.target}")
            except Exception as e:  # noqa: BLE001
                log.warning("close tab failed: %s", e)
            self.target = None

    def __enter__(self) -> CdpSession:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def eval(self, js: str, timeout: float = 150.0) -> Any:
        if not self.target:
            raise DceError("session not open")
        r = self._call(f"/eval?target={self.target}", js, timeout=timeout)
        if "value" not in r:
            raise DceError(f"eval failed: {r}")
        return r["value"]

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
        self.requests_made += 1

    # -- 站点请求(页面上下文 fetch) --
    def post_json(self, path: str, body: dict[str, Any]) -> bytes:
        """POST JSON,返回响应正文(bytes)。非 200 抛 DceError。"""
        self._throttle()
        js = (
            _FETCH_JS.format(path=json.dumps(path), body=json.dumps(json.dumps(body, ensure_ascii=False)))
            + "const t = await r.text(); return JSON.stringify({status: r.status, text: t}); })()"
        )
        out = json.loads(self.eval(js))
        if out["status"] != 200:
            raise DceError(f"{path} -> HTTP {out['status']}: {str(out['text'])[:200]}")
        return str(out["text"]).encode("utf-8")

    def post_bytes(self, path: str, body: dict[str, Any]) -> bytes:
        """POST JSON,响应按二进制取回(base64 分片)。"""
        self._throttle()
        js = (
            _FETCH_JS.format(path=json.dumps(path), body=json.dumps(json.dumps(body, ensure_ascii=False)))
            + "const buf = await r.arrayBuffer(); const u8 = new Uint8Array(buf); const parts = []; "
            "for (let i = 0; i < u8.length; i += 32768) parts.push(String.fromCharCode.apply(null, u8.subarray(i, i + 32768))); "
            "window.__dce_b64 = btoa(parts.join('')); "
            "return JSON.stringify({status: r.status, cd: r.headers.get('content-disposition'), len: window.__dce_b64.length}); })()"
        )
        meta = json.loads(self.eval(js))
        if meta["status"] != 200:
            raise DceError(f"{path} -> HTTP {meta['status']}")
        n = int(meta["len"])
        chunk = 400_000
        parts = [str(self.eval(f"window.__dce_b64.slice({i}, {i + chunk})")) for i in range(0, n, chunk)]
        return base64.b64decode("".join(parts))


# --------------------------------------------------------------------------------------
# 抓取:原样落盘
# --------------------------------------------------------------------------------------
def _store_raw(store: Store | None, kind: str, date: pd.Timestamp, raw: bytes) -> None:
    if store is not None:
        store.write_raw(EXCHANGE, kind, date, RAW_EXT[kind], raw)


def fetch_quotes(date: pd.Timestamp, session: CdpSession, store: Store | None = None) -> bytes:
    body = {
        "varietyId": "all",
        "tradeDate": _ymd(date),
        "tradeType": "1",  # 1=期货 2=期权
        "contractId": "",
        "lang": "zh",
        "optionSeries": "",
        "statisticsType": 0,
    }
    raw = session.post_json(API_QUOTES, body)
    _check_json(raw, API_QUOTES)
    return raw


def fetch_positions(date: pd.Timestamp, session: CdpSession, store: Store | None = None) -> bytes:
    """批量下载:一次返回当日全部品种、全部合约的 成交量/买持仓/卖持仓 排名(zip,每合约一个 txt)。
    请求体里的 varietyId/contractId 只是页面状态,服务端返回的是整日全部合约。"""
    body = {"tradeDate": _ymd(date), "varietyId": "c", "contractId": "all", "tradeType": "1", "lang": "zh"}
    raw = session.post_bytes(API_POSITIONS, body)
    if not raw.startswith(b"PK"):
        raise DceError(f"{API_POSITIONS} did not return a zip ({raw[:60]!r})")
    return raw


def fetch_receipts(date: pd.Timestamp, session: CdpSession, store: Store | None = None) -> bytes:
    raw = session.post_json(API_RECEIPTS, {"varietyId": "all", "tradeDate": _ymd(date)})
    _check_json(raw, API_RECEIPTS)
    return raw


def is_trading_day(date: pd.Timestamp, session: CdpSession) -> bool:
    """tradeDateNum 在非交易日返回 data=null。"""
    raw = session.post_json(API_TRADEDATE, {"date": _ymd(date)})
    payload = _check_json(raw, API_TRADEDATE)
    return payload.get("data") is not None


def _check_json(raw: bytes, path: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise DceError(f"{path}: not JSON ({raw[:80]!r})") from e
    if not payload.get("success", False) or payload.get("code") != 200:
        raise DceError(f"{path}: {payload.get('msg')} (code {payload.get('code')})")
    return payload


_FETCHERS = {"quotes": fetch_quotes, "positions": fetch_positions, "receipts": fetch_receipts}


# --------------------------------------------------------------------------------------
# 解析:原始文件 → 规范化 DataFrame
# --------------------------------------------------------------------------------------
def parse_quotes(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """日行情 JSON → QUOTE_COLS。剔除 小计/总计 行(contractId 为空)和月均价期货(代码带 F);成交额 万元→元。
    交易所用 0 表示无成交价(含只有期转现/交割配对成交、成交量>0 但无撮合价的合约,如 eb2609 2026-09-15),规范化为 NaN。"""
    date = pd.Timestamp(date)
    rows = _check_json(raw, API_QUOTES).get("data") or []
    recs: list[dict[str, Any]] = []
    for r in rows:
        cid = r.get("contractId")
        if not cid or not _CODE_RE.match(str(cid)):
            continue
        contract = normalize_contract(str(cid), EXCHANGE)
        recs.append(
            {
                "date": date,
                "exchange": EXCHANGE,
                "symbol": symbol_of(contract),
                "contract": contract,
                "open": _num(r.get("open")),
                "high": _num(r.get("high")),
                "low": _num(r.get("low")),
                "close": _num(r.get("close")),
                "settle": _num(r.get("clearPrice")),
                "prev_settle": _num(r.get("lastClear")),
                "volume": _num(r.get("volumn")),
                "open_interest": _num(r.get("openInterest")),
                "turnover": _num(r.get("turnover")) * TURNOVER_UNIT,
            }
        )
    df = pd.DataFrame(recs, columns=QUOTE_COLS)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].where(df[c] > 0, np.nan)
    return df


def _parse_position_txt(text: str) -> tuple[dict[int, dict[str, Any]], dict[str, tuple[float, float]]]:
    """一个合约的排名 txt:三段(成交量/持买单量/持卖单量),每段 名次/会员简称/数量/增减 + 合计行。"""
    ranks: dict[int, dict[str, Any]] = {}
    totals: dict[str, tuple[float, float]] = {}
    section: str | None = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if not parts:
            continue
        if parts[0] == "名次":
            section = next((v for k, v in _POS_SECTION.items() if k in line), None)
            continue
        if section is None:
            continue
        if parts[0] == _TOTAL_LABEL:
            totals[section] = (
                _num(parts[1]) if len(parts) > 1 else float("nan"),
                _num(parts[2]) if len(parts) > 2 else float("nan"),
            )
            continue
        if len(parts) >= 3 and parts[0].isdigit():
            rank = int(parts[0])
            row = ranks.setdefault(rank, {})
            row[f"member_{section}"] = parts[1]
            row[{"vol": "vol", "long": "long_oi", "short": "short_oi"}[section]] = _num(parts[2])
            row[f"{section}_chg"] = _num(parts[3]) if len(parts) > 3 else float("nan")
    return ranks, totals


def parse_positions(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """批量下载 zip → POSITION_COLS。每合约:rank 1..N 三榜并排,rank=0/is_total=True 为合计行。
    没有任何排名行的合约(交易所返回空表)整体略去。"""
    date = pd.Timestamp(date)
    recs: list[dict[str, Any]] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for name in sorted(z.namelist()):
            m = _POS_FILE_RE.match(Path(name).name)
            if not m:
                log.debug("skip positions file %s", name)
                continue
            contract = normalize_contract(m.group(2), EXCHANGE)
            ranks, totals = _parse_position_txt(z.read(name).decode("utf-8", errors="replace"))
            if not ranks:
                continue
            base = {"date": date, "exchange": EXCHANGE, "symbol": symbol_of(contract), "contract": contract}
            for rank in sorted(ranks):
                recs.append({**base, "is_total": False, "rank": rank, **ranks[rank]})
            tot = {
                "member_vol": _TOTAL_LABEL,
                "vol": totals.get("vol", (np.nan, np.nan))[0],
                "vol_chg": totals.get("vol", (np.nan, np.nan))[1],
                "member_long": _TOTAL_LABEL,
                "long_oi": totals.get("long", (np.nan, np.nan))[0],
                "long_chg": totals.get("long", (np.nan, np.nan))[1],
                "member_short": _TOTAL_LABEL,
                "short_oi": totals.get("short", (np.nan, np.nan))[0],
                "short_chg": totals.get("short", (np.nan, np.nan))[1],
            }
            recs.append({**base, "is_total": True, "rank": 0, **tot})
    df = pd.DataFrame(recs, columns=POSITION_COLS)
    for c in ("member_vol", "member_long", "member_short"):
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def parse_receipts(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    """仓单日报 JSON → RECEIPT_COLS。
    entityList 里 variety 非空的是主行(仓库,或有分库的仓库组,组行数量已含分库);variety 为空的是分库/子行或品种小计,略去;
    varietyOrder 为空的是交易所总计行,略去。每品种追加一行 warehouse='合计' is_total=True(主行求和)。"""
    date = pd.Timestamp(date)
    rows = _check_json(raw, API_RECEIPTS).get("data", {}).get("entityList") or []
    recs: list[dict[str, Any]] = []
    for r in rows:
        if not r.get("variety") or not r.get("varietyOrder") or not r.get("whAbbr"):
            continue
        recs.append(
            {
                "date": date,
                "exchange": EXCHANGE,
                "symbol": str(r["varietyOrder"]).upper(),
                "warehouse": str(r["whAbbr"]).strip(),
                "is_total": False,
                "receipts": _num(r.get("wbillQty")),
                "change": _num(r.get("diff")),
            }
        )
    df = pd.DataFrame(recs, columns=RECEIPT_COLS)
    if df.empty:
        return df
    tot = df.groupby("symbol", as_index=False)[["receipts", "change"]].sum()
    tot["date"], tot["exchange"], tot["warehouse"], tot["is_total"] = date, EXCHANGE, _TOTAL_LABEL, True
    out = pd.concat([df, tot[RECEIPT_COLS]], ignore_index=True)
    return out.sort_values(["symbol", "is_total", "warehouse"]).reset_index(drop=True)


_PARSERS = {"quotes": parse_quotes, "positions": parse_positions, "receipts": parse_receipts}


# --------------------------------------------------------------------------------------
# 入库、回填
# --------------------------------------------------------------------------------------
def missing_log_path(store: Store) -> Path:
    return store.root / EXCHANGE / "missing.log"


def load_missing(store: Store) -> dict[tuple[pd.Timestamp, str], str]:
    """missing.log:date\\tkind\\treason。kind='*' 表示整日(节假日)。reason 以 error: 开头的下次重试。"""
    p = missing_log_path(store)
    out: dict[tuple[pd.Timestamp, str], str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        out[(pd.Timestamp(parts[0]), parts[1])] = parts[2]
    return out


def record_missing(store: Store, date: pd.Timestamp, kind: str, reason: str) -> None:
    p = missing_log_path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with p.open("a", encoding="utf-8") as f:
        if new:
            f.write(
                "# date\tkind\treason  (kind='*' = 整日非交易日; reason 以 error: 开头的条目下次回填会重试)\n"
            )
        f.write(f"{pd.Timestamp(date).strftime('%Y-%m-%d')}\t{kind}\t{reason}\n")


def _is_final_missing(known: dict[tuple[pd.Timestamp, str], str], date: pd.Timestamp, kind: str) -> bool:
    for k in (kind, "*"):
        reason = known.get((date, k))
        if reason is not None and not reason.startswith("error:"):
            return True
    return False


def ingest_day(
    date: pd.Timestamp,
    kind: str,
    session: CdpSession,
    store: Store | None = None,
    overwrite: bool = False,
) -> str:
    """抓取(若 raw 不存在)+ 解析 + 落盘。返回 'written' | 'exists' | 'holiday' | 'empty'。"""
    store = store or Store()
    date = pd.Timestamp(date)
    if store.has_day(EXCHANGE, kind, date) and not overwrite:
        return "exists"
    raw = store.read_raw(EXCHANGE, kind, date, RAW_EXT[kind])
    if raw is None:
        raw = _FETCHERS[kind](date, session, store)
    df = _PARSERS[kind](raw, date)
    if df.empty:
        # 行情为空 = 非交易日;排名/仓单为空 = 交易所无数据(如 2020-07-20 前的排名)
        if kind == "quotes":
            return "holiday"
        _store_raw(store, kind, date, raw)
        return "empty"
    _store_raw(store, kind, date, raw)
    store.write_day(EXCHANGE, kind, date, df, overwrite=overwrite)
    return "written"


def reparse_day(date: pd.Timestamp, kind: str, store: Store | None = None) -> str:
    """只用已落盘的 raw 重建当日 parquet(解析逻辑改了之后用)。"""
    store = store or Store()
    date = pd.Timestamp(date)
    raw = store.read_raw(EXCHANGE, kind, date, RAW_EXT[kind])
    if raw is None:
        return "no-raw"
    df = _PARSERS[kind](raw, date)
    if df.empty:
        return "empty"
    store.write_day(EXCHANGE, kind, date, df, overwrite=True)
    return "written"


def backfill(
    start: pd.Timestamp,
    end: pd.Timestamp,
    kinds: Sequence[str] = KINDS,
    store: Store | None = None,
    session: CdpSession | None = None,
    max_retries: int = 4,
    positions_from: pd.Timestamp | None = POSITIONS_HISTORY_START,
) -> dict[str, dict[str, int]]:
    """按 kind 逐日回填 [start, end] 的工作日。可断点续跑:已有当日文件、或 missing.log 里已判定为非交易日/无数据的跳过;
    失败按 2^n 秒退避重试 max_retries 次,仍失败记 error: 到 missing.log(下次继续重试)并继续。
    positions_from:排名在此之前交易所只返回空表,默认不请求直接记 empty(传 None 则逐日请求验证)。"""
    store = store or Store()
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    days = pd.bdate_range(start, end)
    known = load_missing(store)
    own = session is None
    sess = session or CdpSession()
    if own:
        sess.open()
    stats: dict[str, dict[str, int]] = {k: {} for k in kinds}

    def bump(kind: str, status: str) -> None:
        stats[kind][status] = stats[kind].get(status, 0) + 1

    try:
        for kind in kinds:
            if kind not in KINDS:
                raise ValueError(f"unknown kind {kind!r}; choose from {KINDS}")
            log.info("DCE backfill %s %s..%s (%d business days)", kind, start.date(), end.date(), len(days))
            for d in days:
                if store.has_day(EXCHANGE, kind, d) or _is_final_missing(known, d, kind):
                    bump(kind, "skipped")
                    continue
                if kind == "positions" and positions_from is not None and d < positions_from:
                    reason = f"empty:before-history-start-{positions_from.date()}"
                    record_missing(store, d, kind, reason)
                    known[(d, kind)] = reason
                    bump(kind, "empty")
                    continue
                if kind != "quotes" and not _trading_day(d, store, known, sess, max_retries):
                    bump(kind, "holiday")
                    continue
                status = _ingest_with_retry(d, kind, sess, store, max_retries)
                if status == "holiday":
                    record_missing(store, d, "*", "holiday")
                    known[(d, "*")] = "holiday"
                elif status == "empty":
                    record_missing(store, d, kind, "empty:exchange-returned-no-rows")
                    known[(d, kind)] = "empty"
                elif status.startswith("error:"):
                    record_missing(store, d, kind, status)
                    known[(d, kind)] = status
                    status = "error"
                bump(kind, status)
            log.info(
                "DCE backfill %s done: %s (site requests so far: %d)", kind, stats[kind], sess.requests_made
            )
    finally:
        if own:
            sess.close()
    return stats


def _trading_day(
    d: pd.Timestamp,
    store: Store,
    known: dict[tuple[pd.Timestamp, str], str],
    sess: CdpSession,
    max_retries: int,
) -> bool:
    if store.has_day(EXCHANGE, "quotes", d):
        return True
    if known.get((d, "*")) == "holiday":
        return False
    for attempt in range(max_retries + 1):
        try:
            ok = is_trading_day(d, sess)
            break
        except Exception as e:  # noqa: BLE001
            log.warning("tradeDateNum %s failed (%s), attempt %d", d.date(), e, attempt)
            _backoff(attempt, sess)
    else:
        return True  # 判定不了就照常抓,由抓取结果决定
    if not ok:
        record_missing(store, d, "*", "holiday")
        known[(d, "*")] = "holiday"
    return ok


def _backoff(attempt: int, sess: CdpSession) -> None:
    time.sleep(min(2.0 * 2**attempt, 60.0))
    if attempt >= 2:  # 连续失败多半是 tab 挂了,重开
        try:
            sess.close()
            sess.open()
        except Exception as e:  # noqa: BLE001
            log.warning("reopen tab failed: %s", e)


def _ingest_with_retry(d: pd.Timestamp, kind: str, sess: CdpSession, store: Store, max_retries: int) -> str:
    last = "error:unknown"
    for attempt in range(max_retries + 1):
        try:
            status = ingest_day(d, kind, sess, store)
            log.info("%s %s %s", d.date(), kind, status)
            return status
        except FileExistsError:
            return "exists"
        except Exception as e:  # noqa: BLE001
            last = f"error:{type(e).__name__}:{str(e)[:160]}".replace("\t", " ").replace("\n", " ")
            log.warning("%s %s failed (%s), attempt %d/%d", d.date(), kind, e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                _backoff(attempt, sess)
    return last


# --------------------------------------------------------------------------------------
# 与米筐导出对账
# --------------------------------------------------------------------------------------
def volume_factor_vs_ricecta(dates: pd.Series[Any]) -> pd.Series[float]:
    """米筐导出沿用交易所当时公布口径(2020-01-02 前双边),本仓库存接口重述后的单边:米筐 = 本仓库 × factor。"""
    return pd.Series(np.where(pd.to_datetime(dates) < SINGLE_SIDED_SINCE, 2.0, 1.0), index=dates.index)


def reconcile_with_ricecta(
    symbols: Iterable[str],
    store: Store | None = None,
    ricecta_dir: Path | None = None,
    n_samples: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐合约逐日与 data/ricecta/data/contracts_daily/{SYMBOL}.parquet 比较。
    返回 (summary, samples):summary 每品种一行(重叠行数、OHLC 一致比例、volume/OI 一致比例);samples 为不一致样例。"""
    store = store or Store()
    ricecta_dir = ricecta_dir or (store.root.parent / "ricecta" / "data" / "contracts_daily")
    rows: list[dict[str, Any]] = []
    samples: list[pd.DataFrame] = []
    for sym in symbols:
        ours = store.read_symbol([EXCHANGE], sym)
        rq_path = ricecta_dir / f"{sym}.parquet"
        if ours.empty or not rq_path.exists():
            rows.append({"symbol": sym, "n": 0})
            continue
        rq = pd.read_parquet(rq_path).reset_index().rename(columns={"order_book_id": "contract"})
        rq["date"] = pd.to_datetime(rq["date"])
        m = ours.merge(rq, on=["contract", "date"], suffixes=("", "_rq"))
        if m.empty:
            rows.append({"symbol": sym, "n": 0})
            continue
        traded = m["volume"].fillna(0) > 0
        priced = traded & m[["open", "high", "low", "close"]].notna().all(axis=1)  # 有成交且交易所给了撮合价
        ohlc_ok = pd.Series(True, index=m.index)
        for c in ("open", "high", "low", "close"):
            ohlc_ok &= np.isclose(m[c], m[f"{c}_rq"], atol=1e-6) | ~priced
        f = volume_factor_vs_ricecta(m["date"])
        vol_ok = np.isclose(m["volume"] * f, m["volume_rq"], atol=0.5)
        oi_ok = np.isclose(m["open_interest"] * f, m["open_interest_rq"], atol=0.5)
        rows.append(
            {
                "symbol": sym,
                "n": int(len(m)),
                "date_min": m["date"].min().date(),
                "date_max": m["date"].max().date(),
                "ohlc_match": float(ohlc_ok[priced].mean()) if priced.any() else float("nan"),
                "n_traded_unpriced": int((traded & ~priced).sum()),
                "volume_match": float(vol_ok.mean()),
                "oi_match": float(oi_ok.mean()),
                "n_ohlc_mismatch": int((~ohlc_ok[priced]).sum()),
                "n_volume_mismatch": int((~vol_ok).sum()),
                "n_oi_mismatch": int((~oi_ok).sum()),
            }
        )
        bad = m[~(ohlc_ok & vol_ok & oi_ok)]
        if not bad.empty:
            cols = [
                "symbol",
                "contract",
                "date",
                "open",
                "open_rq",
                "close",
                "close_rq",
                "volume",
                "volume_rq",
                "open_interest",
                "open_interest_rq",
            ]
            samples.append(bad[cols].head(n_samples).assign(factor=f[bad.index].head(n_samples)))
    summary = pd.DataFrame(rows)
    sample_df = pd.concat(samples, ignore_index=True) if samples else pd.DataFrame()
    return summary, sample_df


# --------------------------------------------------------------------------------------
# 与交易所年度打包(双边口径)交叉核对
# --------------------------------------------------------------------------------------
YEARLY_PACKAGE_DIR = "raw/quotes_yearly"  # data/exchanges/DCE/raw/quotes_yearly/<year>_allVarietyFtr.zip
_PKG_COLS = {
    "合约名称": "contract",
    "交易日期": "date",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "结算价": "settle",
    "成交量": "volume",
    "持仓量": "open_interest",
    "成交额": "turnover",
}


def read_yearly_package(path: Path) -> pd.DataFrame:
    """新站 datadownload 的 allVarietyFtr.zip(每品种一个 xlsx,数值带千分位)→ 与 QUOTE_COLS 同名的列(双边口径,成交额 元)。"""
    frames = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if not name.endswith(".xlsx") or "-F" in name:  # 月均价期货
                continue
            raw = pd.read_excel(io.BytesIO(z.read(name)), dtype=str)
            raw = raw.rename(columns=_PKG_COLS)
            keep = [c for c in _PKG_COLS.values() if c in raw.columns]
            frames.append(raw[keep])
    if not frames:
        return pd.DataFrame(columns=list(_PKG_COLS.values()))
    df = pd.concat(frames, ignore_index=True)
    df = df[df["contract"].map(lambda c: _CODE_RE.match(str(c)) is not None)].copy()
    df["contract"] = df["contract"].map(lambda c: normalize_contract(str(c), EXCHANGE))
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    for c in ("open", "high", "low", "close", "settle", "volume", "open_interest", "turnover"):
        df[c] = df[c].map(_num)
    return df.reset_index(drop=True)


def crosscheck_yearly_packages(
    store: Store | None = None, years: Iterable[int] | None = None
) -> pd.DataFrame:
    """仓库行情(接口,单边)vs 年度打包(双边):逐合约逐日比较,返回每年一行的一致比例。
    预期:价格完全一致,打包成交量/持仓量/成交额 = 本仓库 × 2(成交额允许接口万元两位小数的舍入误差)。"""
    store = store or Store()
    pdir = store.root / EXCHANGE / YEARLY_PACKAGE_DIR
    ours = store.read_days(EXCHANGE, "quotes")
    rows: list[dict[str, Any]] = []
    for path in sorted(pdir.glob("*_allVarietyFtr.zip")):
        year = int(path.name.split("_")[0])
        if years is not None and year not in set(years):
            continue
        pk = read_yearly_package(path)
        mine = ours[ours["date"].dt.year == year]
        m = mine.merge(pk, on=["contract", "date"], how="outer", suffixes=("", "_pk"), indicator=True)
        both = m[m["_merge"] == "both"]
        priced = (both["volume"].fillna(0) > 0) & both[["open", "high", "low", "close"]].notna().all(axis=1)
        ohlc = pd.Series(True, index=both.index)
        for c in ("open", "high", "low", "close"):
            ohlc &= np.isclose(both[c], both[f"{c}_pk"], atol=1e-6) | ~priced
        rows.append(
            {
                "year": year,
                "n_store": int(len(mine)),
                "n_package": int(len(pk)),
                "n_both": int(len(both)),
                "ohlc_match": float(ohlc[priced].mean()) if priced.any() else float("nan"),
                "settle_match": float(np.isclose(both["settle"], both["settle_pk"], atol=1e-6).mean()),
                "volume_x2_match": float(np.isclose(both["volume"] * 2, both["volume_pk"], atol=0.5).mean()),
                "oi_x2_match": float(
                    np.isclose(both["open_interest"] * 2, both["open_interest_pk"], atol=0.5).mean()
                ),
                "turnover_x2_match": float(
                    np.isclose(both["turnover"] * 2, both["turnover_pk"], rtol=0, atol=150).mean()
                ),
            }
        )
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# 覆盖率统计(文档用)
# --------------------------------------------------------------------------------------
def coverage(store: Store | None = None) -> pd.DataFrame:
    """每类每年的交易日文件数。"""
    store = store or Store()
    counts: dict[tuple[str, int], int] = {}
    for kind in KINDS:
        for d in store.days(EXCHANGE, kind):
            counts[(kind, d.year)] = counts.get((kind, d.year), 0) + 1
    recs = [{"kind": k, "year": y, "days": n} for (k, y), n in sorted(counts.items())]
    return pd.DataFrame(recs, columns=["kind", "year", "days"])


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def _parse_kinds(s: str) -> list[str]:
    kinds = [k.strip() for k in s.split(",") if k.strip()]
    bad = [k for k in kinds if k not in KINDS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown kinds {bad}; choose from {','.join(KINDS)}")
    return kinds


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python3 -m cta.data.exchanges.dce", description=__doc__.split("\n")[0])
    p.add_argument("--root", type=Path, default=None, help="data/exchanges 根目录(默认仓库内)")
    p.add_argument("--proxy", default=PROXY_URL, help="CDP proxy 地址")
    p.add_argument("--interval", type=float, default=MIN_INTERVAL, help="站点请求最小间隔(秒)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="按日回填")
    b.add_argument("--start", required=True)
    b.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    b.add_argument("--kinds", type=_parse_kinds, default=list(KINDS))
    b.add_argument("--max-retries", type=int, default=4)
    b.add_argument(
        "--probe-positions-history",
        action="store_true",
        help="排名也请求 2020-07-20 之前的日期(默认直接记 empty)",
    )
    i = sub.add_parser("ingest", help="抓取并入库单日")
    i.add_argument("--date", required=True)
    i.add_argument("--kinds", type=_parse_kinds, default=list(KINDS))
    i.add_argument("--overwrite", action="store_true")
    r = sub.add_parser("reparse", help="用已存 raw 重建 parquet(不联网)")
    r.add_argument("--start", required=True)
    r.add_argument("--end", required=True)
    r.add_argument("--kinds", type=_parse_kinds, default=list(KINDS))
    c = sub.add_parser("reconcile", help="与米筐导出对账(不联网)")
    c.add_argument("--symbols", default="C,M,Y,P,JD,V,J,I")
    sub.add_parser("coverage", help="每类每年天数(不联网)")
    sub.add_parser("crosscheck", help="与交易所年度打包(双边)交叉核对(不联网)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    store = Store(args.root) if args.root else Store()
    if args.cmd == "backfill":
        with CdpSession(proxy=args.proxy, min_interval=args.interval) as sess:
            stats = backfill(
                pd.Timestamp(args.start),
                pd.Timestamp(args.end),
                args.kinds,
                store=store,
                session=sess,
                max_retries=args.max_retries,
                positions_from=None if args.probe_positions_history else POSITIONS_HISTORY_START,
            )
        print(json.dumps(stats, ensure_ascii=False, indent=1))
    elif args.cmd == "ingest":
        with CdpSession(proxy=args.proxy, min_interval=args.interval) as sess:
            for kind in args.kinds:
                print(
                    args.date,
                    kind,
                    ingest_day(pd.Timestamp(args.date), kind, sess, store, overwrite=args.overwrite),
                )
    elif args.cmd == "reparse":
        for kind in args.kinds:
            for d in pd.bdate_range(args.start, args.end):
                st = reparse_day(d, kind, store)
                if st != "no-raw":
                    print(d.date(), kind, st)
    elif args.cmd == "reconcile":
        summary, samples = reconcile_with_ricecta([s.strip().upper() for s in args.symbols.split(",")], store)
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(summary.to_string(index=False))
            if not samples.empty:
                print("\nmismatch samples:")
                print(samples.to_string(index=False))
    elif args.cmd == "crosscheck":
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(crosscheck_yearly_packages(store).to_string(index=False))
    elif args.cmd == "coverage":
        print(
            coverage(store)
            .pivot(index="year", columns="kind", values="days")
            .fillna(0)
            .astype(int)
            .to_string()
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
