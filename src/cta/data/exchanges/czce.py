"""郑州商品交易所(CZCE)公开日频数据:期货行情、会员持仓排名、仓单日报。

数据源(均为交易所官网静态文件,2016-01-04 起可用,见 docs/data_exchanges_czce.md):
  每日文件  https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureData{Daily|Holding|Whsheet}.txt
  年度打包  https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/ALLFUTURES{YYYY}.zip(2020 起)
            https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/FutureDataHistory.zip(2015–2019),仅行情
反爬:.htm/.zip 受瑞数 JS 挑战保护(直连返回 412),.txt 直连可取;412 时回退到本机 Chrome 的 CDP 代理在页面内 fetch。
口径:自 2020-01-01 起成交量/持仓量/成交额按单边计算,之前为双边;规范化数据保留交易所原值,不折算。
"""

from __future__ import annotations

import argparse
import atexit
import base64
import contextlib
import io
import json
import logging
import re
import sys
import time
import urllib.error
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

log = logging.getLogger("cta.czce")

EXCHANGE = "CZCE"
BASE_URL = "https://www.czce.com.cn/cn/DFSStaticFiles/Future"
DAILY_FILE: dict[str, str] = {
    "quotes": "FutureDataDaily",
    "positions": "FutureDataHolding",
    "receipts": "FutureDataWhsheet",
}
KINDS: tuple[str, ...] = ("quotes", "positions", "receipts")
RAW_EXT = "txt"
FIRST_DATE = pd.Timestamp("2016-01-04")

# 成交量/持仓量/成交额口径:郑商所自 2020-01-01 起改为单边计算(此前双边,即买卖各计一次)。
# 官网"历史行情下载"页脚注:"自2020年1月1日起,成交量、持仓量、成交额、行权量均为单边计算"。
# 米筐导出在两段都保留交易所原值(2019-12-31→2020-01-02 持仓量约减半),对账时不做折算;
# 需要跨口径可比时,把 2020 年前的 volume/open_interest/turnover 除以 2。
SINGLE_SIDED_FROM = pd.Timestamp("2020-01-01")
TURNOVER_UNIT = 10_000.0  # 文件中成交额单位为万元,规范化为元(与米筐/本仓库 turnover 口径一致)

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
DEFAULT_CDP_PROXY = "http://localhost:3456"
CDP_HOME = (
    "https://www.czce.com.cn/cn/jysj/lshqxz/H077003019index_1.htm"  # 同源页面,页面内 fetch 可带反爬 cookie
)

_CONTRACT_RE = re.compile(r"^[A-Za-z]{1,2}\d{3,4}$")
_TOTAL_WORDS = ("小计", "合计", "总计")
_SYMBOL_ALIAS = {"PTA": "TA"}  # 表头写 "品种:PTA",合约代码为 TA
# 仓单日报里算作"仓单"的数量列:普通仓单、PTA 完税/保税仓单、强麦 2020-06 起的交割确认书
_RECEIPT_QTY_HEADERS = ("仓单数量", "确认书数量")


def counting_basis(date: pd.Timestamp) -> str:
    """该日成交量/持仓量的交易所口径:'double'(双边)或 'single'(单边)。"""
    return "single" if pd.Timestamp(date) >= SINGLE_SIDED_FROM else "double"


def daily_url(kind: str, date: pd.Timestamp) -> str:
    d = pd.Timestamp(date)
    return f"{BASE_URL}/{d.year}/{d.strftime('%Y%m%d')}/{DAILY_FILE[kind]}.{RAW_EXT}"


def annual_zip_url(year: int) -> str:
    if year >= 2020:
        return f"{BASE_URL}/{year}/ALLFUTURES{year}.zip"
    if year >= 2015:
        return f"{BASE_URL}/{year}/FutureDataHistory.zip"
    return f"https://www.czce.com.cn/cn/exchange/datahistory{year}.zip"


def annual_zip_path(store: Store, year: int) -> Path:
    return store.root / EXCHANGE / "raw" / "quotes_annual" / f"ALLFUTURES{year}.zip"


# ----------------------------------------------------------------------------- 抓取


class FetchError(RuntimeError):
    pass


# 页面内 fetch(同源,自动带反爬 cookie),把响应体转成 base64 交回
_CDP_FETCH_JS = (
    "(async()=>{try{const r=await fetch(__URL__,{credentials:'include'});"
    "const b=new Uint8Array(await r.arrayBuffer());let s='';"
    "for(let i=0;i<b.length;i+=32768){s+=String.fromCharCode.apply(null,b.subarray(i,i+32768));}"
    "return JSON.stringify({status:r.status,b64:btoa(s)});}"
    "catch(e){return JSON.stringify({status:-1,error:String(e)})}})()"
)


class Fetcher:
    """带限速、退避重试与 CDP 回退的下载器。get() 返回 (status, body);404 不重试。"""

    def __init__(
        self,
        sleep: float = 1.0,
        cdp_proxy: str | None = DEFAULT_CDP_PROXY,
        retries: int = 5,
        timeout: float = 30.0,
    ):
        self.sleep = sleep
        self.cdp_proxy = cdp_proxy
        self.retries = retries
        self.timeout = timeout
        self._last = 0.0
        self._cdp_target: str | None = None
        self._cdp_dead = False
        self.stats: dict[str, int] = {"direct": 0, "cdp": 0, "retry": 0}

    # -- 限速
    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.sleep:
            time.sleep(self.sleep - gap)
        self._last = time.monotonic()

    # -- 直连
    def _direct(self, url: str) -> tuple[int, bytes]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://www.czce.com.cn/",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as e:
            body = e.read() if e.fp is not None else b""
            return int(e.code), body

    # -- CDP 回退:在用户 Chrome 的同源标签页里 fetch,返回 base64
    def _cdp_tab(self) -> str | None:
        if self._cdp_dead or not self.cdp_proxy:
            return None
        if self._cdp_target:
            return self._cdp_target
        try:
            q = urllib.parse.quote(CDP_HOME, safe="")
            with urllib.request.urlopen(f"{self.cdp_proxy}/new?url={q}", timeout=60) as r:
                tid = str(json.loads(r.read().decode())["targetId"])
        except Exception as e:  # noqa: BLE001 - 代理不可用即视为无回退
            log.warning("CDP proxy unavailable (%s); direct only", e)
            self._cdp_dead = True
            return None
        time.sleep(3.0)  # 等反爬脚本完成挑战并写 cookie
        self._cdp_target = tid
        atexit.register(self.close)
        return tid

    def close(self) -> None:
        if self._cdp_target and self.cdp_proxy:
            with contextlib.suppress(Exception):
                urllib.request.urlopen(f"{self.cdp_proxy}/close?target={self._cdp_target}", timeout=10).read()
            self._cdp_target = None

    def _cdp(self, url: str) -> tuple[int, bytes] | None:
        tid = self._cdp_tab()
        if tid is None:
            return None
        js = _CDP_FETCH_JS.replace("__URL__", json.dumps(url))
        req = urllib.request.Request(f"{self.cdp_proxy}/eval?target={tid}", data=js.encode(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                outer = json.loads(r.read().decode())
            inner = json.loads(outer["value"])
        except Exception as e:  # noqa: BLE001
            log.warning("CDP eval failed (%s)", e)
            self._cdp_target = None
            return None
        status = int(inner["status"])
        if status < 0:
            log.warning("CDP fetch error: %s", inner.get("error"))
            return None
        self.stats["cdp"] += 1
        return status, base64.b64decode(inner["b64"])

    def get(self, url: str, allow_cdp: bool = True) -> tuple[int, bytes]:
        delay = 5.0
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                status, body = self._direct(url)
                self.stats["direct"] += 1
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                log.warning("network error on %s: %s (attempt %d)", url, e, attempt)
                status, body = -1, b""
            if status in (200, 404):
                return status, body
            if status == 412 and allow_cdp:  # JS 反爬:换浏览器同源 fetch
                self._throttle()
                got = self._cdp(url)
                if got is not None and got[0] in (200, 404):
                    return got
            self.stats["retry"] += 1
            log.info("status %s for %s; backing off %.0fs", status, url, delay)
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
        raise FetchError(f"giving up on {url} after {self.retries} retries (last status {status})")


# ----------------------------------------------------------------------------- 解析


def decode_text(raw: bytes | str) -> str:
    """2016–2017 的文件为 GBK,2018 起为 UTF-8;先按 UTF-8 严格解码,失败退回 GB18030。"""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030", errors="replace")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.rstrip("\r\n").split("|")]


def _num(s: str) -> float:
    s = s.strip().replace(",", "")
    if s in ("", "-", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _member(cell: str) -> str:
    """榜单某列名额不足时交易所填 "-",统一为空字符串。"""
    return "" if cell.strip() in ("-", "--") else cell.strip()


def _is_total(cell: str) -> bool:
    return any(w in cell for w in _TOTAL_WORDS)


def _symbol_from_label(label: str) -> str | None:
    """'棉花CF' / 'PTA' / '一号棉CF' / '动力煤TC' → 品种代码。"""
    m = re.search(r"([A-Za-z]{1,3})\s*$", label.strip())
    if not m:
        return None
    code = m.group(1).upper()
    return _SYMBOL_ALIAS.get(code, code)


_QUOTE_HEADER_MAP = {
    "昨结算": "prev_settle",
    "今开盘": "open",
    "最高价": "high",
    "最低价": "low",
    "今收盘": "close",
    "今结算": "settle",
    "成交量(手)": "volume",
    "成交量": "volume",
    "持仓量": "open_interest",
    "空盘量": "open_interest",  # 2020 及以前的表头叫"空盘量"
    "成交额(万元)": "turnover",
    "成交额": "turnover",
}


def _quote_header_index(cells: list[str]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, c in enumerate(cells):
        key = c.replace("（", "(").replace("）", ")").strip()
        name = _QUOTE_HEADER_MAP.get(key)
        if name and name not in idx:
            idx[name] = i
    return idx


def _quote_rows(lines: Iterable[str]) -> list[dict[str, Any]]:
    """把行情表(每日文件或年度打包的单品种文件)解析为记录;剔除小计/合计/总计与非期货代码行。
    年度打包多一列"交易日期"在最前;每日文件无日期列(记录里 date 为 None)。"""
    idx: dict[str, int] = {}
    code_col = -1
    date_col = -1
    out: list[dict[str, Any]] = []
    for line in lines:
        if "|" not in line:
            continue
        cells = _cells(line)
        if not idx:
            if "今结算" in cells or any("结算" in c for c in cells):
                idx = _quote_header_index(cells)
                for i, c in enumerate(cells):
                    if c in ("合约代码", "品种月份"):
                        code_col = i
                    elif c == "交易日期":
                        date_col = i
                if code_col < 0:
                    code_col = 1 if date_col == 0 else 0
            continue
        code = cells[code_col] if code_col < len(cells) else ""
        if not code or _is_total(code) or not _CONTRACT_RE.match(code):
            continue  # 小计/合计/总计;期权(如 CF601C12000)与空行也不匹配代码正则
        rec: dict[str, Any] = {"code": code, "date": cells[date_col] if date_col >= 0 else None}
        for name, i in idx.items():
            rec[name] = _num(cells[i]) if i < len(cells) else float("nan")
        out.append(rec)
    return out


def _quotes_frame(records: list[dict[str, Any]], date: pd.Timestamp | None) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=QUOTE_COLS)
    df = pd.DataFrame.from_records(records)
    if date is not None:
        df["date"] = pd.Timestamp(date)
    else:
        df["date"] = pd.to_datetime(df["date"])
    df["contract"] = [normalize_contract(c, EXCHANGE, d) for c, d in zip(df["code"], df["date"])]
    df["symbol"] = df["contract"].map(symbol_of)
    df["exchange"] = EXCHANGE
    for c in ("open", "high", "low", "close", "settle", "prev_settle", "volume", "open_interest", "turnover"):
        if c not in df.columns:
            df[c] = float("nan")
    df["turnover"] = df["turnover"] * TURNOVER_UNIT
    # 交易所用 0 表示"无成交价";交割月合约偶见 成交量>0 但 OHLC 全 0(交割/期转现类成交),统一把 0 价置 NaN、成交量照存
    ohlc = ["open", "high", "low", "close"]
    df[ohlc] = df[ohlc].where(df[ohlc] > 0)
    odd = (df["volume"] > 0) & df[ohlc].isna().any(axis=1)
    if odd.any():
        log.debug(
            "%d traded rows without price (kept, OHLC=NaN): %s", int(odd.sum()), list(df.loc[odd, "code"][:5])
        )
    # 无成交合约 OHLC 为 0,validate 会置 NaN;结算价缺失/为 0 的行无法入库,单独剔除并记日志
    bad = df["settle"].isna() | (df["settle"] <= 0)
    if bad.any():
        log.warning(
            "dropping %d quote rows with non-positive settle: %s",
            int(bad.sum()),
            list(df.loc[bad, "code"][:5]),
        )
        df = df[~bad]
    dup = df.duplicated(["date", "contract"], keep="first")
    if dup.any():
        log.warning("dropping %d duplicated quote rows: %s", int(dup.sum()), list(df.loc[dup, "code"][:5]))
        df = df[~dup]
    return df[QUOTE_COLS].reset_index(drop=True)


def parse_quotes(raw: bytes | str, date: pd.Timestamp) -> pd.DataFrame:
    """每日行情文件 FutureDataDaily.txt → QUOTE_COLS。"""
    return _quotes_frame(_quote_rows(decode_text(raw).splitlines()), pd.Timestamp(date))


def parse_annual_zip(blob: bytes) -> pd.DataFrame:
    """年度打包(每品种一个 txt,首列交易日期)→ 全年 QUOTE_COLS。"""
    zf = zipfile.ZipFile(io.BytesIO(blob))
    records: list[dict[str, Any]] = []
    for name in zf.namelist():
        if not name.lower().endswith(".txt"):
            continue
        records.extend(_quote_rows(decode_text(zf.read(name)).splitlines()))
    return _quotes_frame(records, None)


_BLOCK_RE = re.compile(r"^(品种|合约)[：:]\s*(\S+?)\s+日期")


def parse_positions(raw: bytes | str, date: pd.Timestamp) -> pd.DataFrame:
    """持仓排名 FutureDataHolding.txt → POSITION_COLS。品种级榜单 contract=品种代码;合约级榜单 contract=规范化合约;
    合计行 is_total=True、rank=0;三列榜单(成交量/持买/持卖)并排。"""
    date = pd.Timestamp(date)
    rows: list[dict[str, Any]] = []
    symbol: str | None = None
    contract: str | None = None
    for line in decode_text(raw).splitlines():
        m = _BLOCK_RE.match(line.strip())
        if m:
            kind, label = m.group(1), m.group(2)
            if kind == "合约" and _CONTRACT_RE.match(label):
                contract = normalize_contract(label, EXCHANGE, date)
                symbol = symbol_of(contract)
            else:
                symbol = _symbol_from_label(label)
                contract = symbol
            continue
        if "|" not in line or symbol is None:
            continue
        cells = _cells(line)
        if len(cells) < 10 or cells[0] in ("名次", ""):
            continue
        head = cells[0]
        if _is_total(head):
            rank, total = 0, True
        elif head.isdigit():
            rank, total = int(head), False
        else:
            continue
        rows.append(
            {
                "date": date,
                "exchange": EXCHANGE,
                "symbol": symbol,
                "contract": contract,
                "is_total": total,
                "rank": rank,
                "member_vol": _member(cells[1]),
                "vol": _num(cells[2]),
                "vol_chg": _num(cells[3]),
                "member_long": _member(cells[4]),
                "long_oi": _num(cells[5]),
                "long_chg": _num(cells[6]),
                "member_short": _member(cells[7]),
                "short_oi": _num(cells[8]),
                "short_chg": _num(cells[9]),
            }
        )
    return pd.DataFrame(rows, columns=POSITION_COLS)


def parse_receipts(raw: bytes | str, date: pd.Timestamp) -> pd.DataFrame:
    """仓单日报 FutureDataWhsheet.txt → RECEIPT_COLS。一行 = 品种×仓库(仓库小计;无小计行的仓库取其明细之和),
    总计行 is_total=True(文件无总计行时按仓库求和补一行)。只取"仓单数量"表,跳过苹果/红枣/花生的"预报数量"表;
    PTA 的完税+保税两列相加;强麦 2020-06 起的"确认书数量"(交割确认书)按仓单处理;品种块内总计之后的附表(可交割品牌)忽略。"""
    date = pd.Timestamp(date)
    lines = decode_text(raw).splitlines()
    rows: list[dict[str, Any]] = []
    symbol: str | None = None
    qty_cols: list[int] = []
    chg_col = -1
    pending: list[Any] | None = None  # [warehouse, qty, chg]
    seen_total = False
    wh_sum = [0.0, 0.0]
    skip_block = False

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            rows.append(
                {
                    "date": date,
                    "exchange": EXCHANGE,
                    "symbol": symbol,
                    "warehouse": pending[0],
                    "is_total": False,
                    "receipts": pending[1],
                    "change": pending[2],
                }
            )
            wh_sum[0] += pending[1] if pending[1] == pending[1] else 0.0
            wh_sum[1] += pending[2] if pending[2] == pending[2] else 0.0
            pending = None

    def end_block() -> None:
        nonlocal seen_total, wh_sum
        flush_pending()
        if symbol is not None and not skip_block and not seen_total and rows and rows[-1]["symbol"] == symbol:
            rows.append(
                {
                    "date": date,
                    "exchange": EXCHANGE,
                    "symbol": symbol,
                    "warehouse": "合计",
                    "is_total": True,
                    "receipts": wh_sum[0],
                    "change": wh_sum[1],
                }
            )
        seen_total = False
        wh_sum = [0.0, 0.0]

    for line in lines:
        s = line.strip()
        if s.startswith("品种"):
            end_block()
            m = re.match(r"^品种[：:]\s*(\S+)", s)
            symbol = _symbol_from_label(m.group(1)) if m else None
            qty_cols, chg_col, skip_block = [], -1, False
            continue
        if "|" not in line or symbol is None:
            continue
        cells = _cells(line)
        if (not qty_cols and chg_col < 0) or cells[0].endswith(
            "编号"
        ):  # 表头行(同一品种块内可能有第二张子表)
            flush_pending()
            qty_cols = [i for i, c in enumerate(cells) if c.startswith(_RECEIPT_QTY_HEADERS)]
            chg_cols = [i for i, c in enumerate(cells) if c.startswith("当日增减")]
            chg_col = chg_cols[0] if chg_cols else -1
            skip_block = not qty_cols  # 预报数量表 / 可交割品牌表:不是仓单
            if skip_block:
                qty_cols = [-1]
            continue
        if skip_block:
            continue
        qty = (
            float(np.nansum([_num(cells[i]) for i in qty_cols if i < len(cells)]))
            if qty_cols
            else float("nan")
        )
        if all(np.isnan(_num(cells[i])) for i in qty_cols if i < len(cells)):
            qty = float("nan")
        chg = _num(cells[chg_col]) if 0 <= chg_col < len(cells) else float("nan")
        head = cells[0]
        if head == "小计":
            if pending is not None:
                pending[1], pending[2] = qty, chg
            flush_pending()
        elif _is_total(head):
            flush_pending()
            rows.append(
                {
                    "date": date,
                    "exchange": EXCHANGE,
                    "symbol": symbol,
                    "warehouse": "合计",
                    "is_total": True,
                    "receipts": qty,
                    "change": chg,
                }
            )
            seen_total = True
            skip_block = True  # 总计之后到下一个品种之前的内容(如可交割品牌附表)不再是仓单
        elif head:
            flush_pending()
            name = cells[1] if len(cells) > 1 and cells[1] else head
            pending = [name, qty, chg]
        elif pending is not None:  # 同一仓库的明细行(年度/等级/品牌)
            pending[1] = (0.0 if np.isnan(pending[1]) else pending[1]) + (0.0 if np.isnan(qty) else qty)
            pending[2] = (0.0 if np.isnan(pending[2]) else pending[2]) + (0.0 if np.isnan(chg) else chg)
    end_block()
    return pd.DataFrame(rows, columns=RECEIPT_COLS)


PARSERS = {"quotes": parse_quotes, "positions": parse_positions, "receipts": parse_receipts}


# ----------------------------------------------------------------------------- 落盘 / 回填


def missing_log_path(store: Store) -> Path:
    return store.root / EXCHANGE / "missing.log"


def load_missing(store: Store) -> dict[tuple[pd.Timestamp, str], str]:
    p = missing_log_path(store)
    out: dict[tuple[pd.Timestamp, str], str] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        parts = line.strip().split(",", 2)
        if len(parts) >= 2 and not line.startswith("#"):
            out[(pd.Timestamp(parts[0]), parts[1])] = parts[2] if len(parts) > 2 else ""
    return out


def log_missing(store: Store, date: pd.Timestamp, kind: str, reason: str) -> None:
    p = missing_log_path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(f"{pd.Timestamp(date).strftime('%Y-%m-%d')},{kind},{reason}\n")


def fetch_raw(kind: str, date: pd.Timestamp, store: Store, fetcher: Fetcher) -> bytes | None:
    """原始 .txt:已落盘则直接读,否则下载并 gzip 原样保存;404(节假日/未发布)返回 None。"""
    cached = store.read_raw(EXCHANGE, kind, date, RAW_EXT)
    if cached is not None:
        return cached
    status, body = fetcher.get(daily_url(kind, date))
    if status == 404:
        return None
    if not body.strip():
        return None
    store.write_raw(EXCHANGE, kind, date, RAW_EXT, body)
    return body


def fetch_quotes(
    date: pd.Timestamp, store: Store | None = None, fetcher: Fetcher | None = None
) -> bytes | None:
    return fetch_raw("quotes", pd.Timestamp(date), store or Store(), fetcher or Fetcher())


def fetch_positions(
    date: pd.Timestamp, store: Store | None = None, fetcher: Fetcher | None = None
) -> bytes | None:
    return fetch_raw("positions", pd.Timestamp(date), store or Store(), fetcher or Fetcher())


def fetch_receipts(
    date: pd.Timestamp, store: Store | None = None, fetcher: Fetcher | None = None
) -> bytes | None:
    return fetch_raw("receipts", pd.Timestamp(date), store or Store(), fetcher or Fetcher())


def ingest_day(
    date: pd.Timestamp,
    kinds: Sequence[str] = KINDS,
    store: Store | None = None,
    fetcher: Fetcher | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    """抓取并解析某日的若干类数据,返回每类状态:ok / exists / missing / empty / error:<msg>。"""
    st = store or Store()
    fx = fetcher or Fetcher()
    date = pd.Timestamp(date)
    out: dict[str, str] = {}
    for kind in kinds:
        if st.has_day(EXCHANGE, kind, date) and not overwrite:
            out[kind] = "exists"
            continue
        try:
            raw = fetch_raw(kind, date, st, fx)
            if raw is None:
                out[kind] = "missing"
                continue
            df = PARSERS[kind](raw, date)
            if df.empty:
                out[kind] = "empty"
                continue
            st.write_day(EXCHANGE, kind, date, df, overwrite=overwrite)
            out[kind] = "ok"
        except FetchError as e:
            out[kind] = f"error:{e}"
        except Exception as e:  # noqa: BLE001 - 解析异常记录后继续下一类
            log.exception("%s %s failed", kind, date.date())
            out[kind] = f"error:{type(e).__name__}:{e}"
    return out


def ingest_annual(
    year: int, store: Store | None = None, fetcher: Fetcher | None = None, overwrite: bool = False
) -> int:
    """年度打包 → 逐日 quotes parquet;返回新写入的天数。zip 原样保存在 raw/quotes_annual/。"""
    st = store or Store()
    fx = fetcher or Fetcher()
    p = annual_zip_path(st, year)
    if p.exists():
        blob = p.read_bytes()
    else:
        status, blob = fx.get(annual_zip_url(year))
        if status != 200 or not blob.startswith(b"PK"):
            log.warning("annual zip %s unavailable (status %s)", year, status)
            return 0
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    df = parse_annual_zip(blob)
    n = 0
    for _, g in df.groupby("date"):
        d = pd.Timestamp(g["date"].iloc[0])
        if st.has_day(EXCHANGE, "quotes", d) and not overwrite:
            continue
        st.write_day(EXCHANGE, "quotes", d, g.reset_index(drop=True), overwrite=overwrite)
        n += 1
    log.info("annual %d: %d days written (%d in zip)", year, n, df["date"].nunique())
    return n


def backfill(
    start: pd.Timestamp,
    end: pd.Timestamp,
    kinds: Sequence[str] = KINDS,
    store: Store | None = None,
    fetcher: Fetcher | None = None,
    use_annual: bool = True,
    retry_missing: bool = False,
) -> dict[str, int]:
    """逐工作日回填 [start, end]:已有 parquet 跳过,missing.log 里的 404 日期跳过(可断点续跑)。
    quotes 先用年度打包覆盖整年(当年除外),再逐日补缺。"""
    st = store or Store()
    fx = fetcher or Fetcher()
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    counts: dict[str, int] = {}
    if use_annual and "quotes" in kinds:
        today = pd.Timestamp.today().normalize()
        for year in range(start.year, end.year + 1):
            if year >= today.year:
                continue
            try:
                counts["annual_days"] = counts.get("annual_days", 0) + ingest_annual(year, st, fx)
            except FetchError as e:
                log.warning("annual %d skipped: %s", year, e)
    known = load_missing(st)
    for d in pd.bdate_range(start, end):
        todo = [k for k in kinds if not st.has_day(EXCHANGE, k, d) and (retry_missing or (d, k) not in known)]
        if not todo:
            continue
        res = ingest_day(d, todo, st, fx)
        for k, status in res.items():
            counts[status.split(":")[0]] = counts.get(status.split(":")[0], 0) + 1
            if status == "missing":
                log_missing(st, d, k, "404")
            elif status == "empty":
                log_missing(st, d, k, "empty")
        log.info("%s %s", d.date(), " ".join(f"{k}={v}" for k, v in res.items()))
    log.info("backfill done: %s fetch=%s", counts, fx.stats)
    return counts


def reparse(
    start: pd.Timestamp, end: pd.Timestamp, kinds: Sequence[str] = KINDS, store: Store | None = None
) -> int:
    """用当前解析器从已落盘 raw 重建 parquet(覆盖),解析器修订后使用。"""
    st = store or Store()
    n = 0
    for d in pd.bdate_range(pd.Timestamp(start), pd.Timestamp(end)):
        for kind in kinds:
            raw = st.read_raw(EXCHANGE, kind, d, RAW_EXT)
            if raw is None:
                continue
            df = PARSERS[kind](raw, d)
            if df.empty:
                continue
            st.write_day(EXCHANGE, kind, d, df, overwrite=True)
            n += 1
    return n


def coverage(store: Store | None = None, kinds: Sequence[str] = KINDS) -> pd.DataFrame:
    """每类每年的天数。"""
    st = store or Store()
    rows = {}
    for kind in kinds:
        days = st.days(EXCHANGE, kind)
        rows[kind] = (
            pd.Series([d.year for d in days]).value_counts().sort_index() if days else pd.Series(dtype=int)
        )
    out = pd.DataFrame(rows).fillna(0).astype(int)
    out.index.name = "year"
    return out


# ----------------------------------------------------------------------------- 与米筐导出对账

RQ_DIR = Store().root.parents[0] / "ricecta" / "data" / "contracts_daily"
RECONCILE_SYMBOLS = ("CF", "SR", "TA", "MA", "SA")


def reconcile(
    symbols: Sequence[str] = RECONCILE_SYMBOLS, store: Store | None = None, rq_dir: Path | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """逐合约逐日与米筐导出比较,返回 (summary, mismatches)。
    米筐对无成交合约把 OHLC 填成当日结算价,所以 OHLC 只在两边都有成交的行上比较(ohlc_match_traded),
    无成交行单独统计"米筐 OHLC == 交易所结算价"的比例(untraded_fill_settle)。
    volume/OI 按交易所原值比较(vol_match_raw / oi_match_raw);另给"2020 年前除以 2"的匹配率核对口径。
    交易所日报是结算后的官方数(含期转现/交割配对),米筐取自盘中行情快照,差异多呈 Δvolume = −ΔOI(efp_pattern)。"""
    st = store or Store()
    rq_root = rq_dir or RQ_DIR
    ex_all = st.read_days(EXCHANGE, "quotes")
    summaries: list[dict[str, Any]] = []
    mism: list[pd.DataFrame] = []
    for sym in symbols:
        p = rq_root / f"{sym}.parquet"
        if not p.exists():
            continue
        rq = pd.read_parquet(p).reset_index()
        rq = rq.rename(columns={"order_book_id": "contract"})
        rq["date"] = pd.to_datetime(rq["date"])
        ex = ex_all[ex_all["symbol"] == sym]
        m = ex.merge(rq, on=["contract", "date"], suffixes=("", "_rq"), how="inner")
        if m.empty:
            continue
        traded = (m["volume"] > 0) & (m["volume_rq"] > 0)
        ohlc_eq = pd.Series(True, index=m.index)
        for c in ("open", "high", "low", "close"):
            ohlc_eq &= np.abs(m[c] - m[f"{c}_rq"]) < 1e-6
        untraded = m["volume_rq"] == 0
        fill_ok = untraded & (np.abs(m["close_rq"] - m["settle"]) < 1e-6)
        ohlc_ok = (traded & ohlc_eq) | fill_ok
        pre = m["date"] < SINGLE_SIDED_FROM
        vol_raw = np.abs(m["volume"] - m["volume_rq"]) < 1e-6
        oi_raw = np.abs(m["open_interest"] - m["open_interest_rq"]) < 1e-6
        vol_half = np.abs(np.where(pre, m["volume"] / 2, m["volume"]) - m["volume_rq"]) < 1e-6
        oi_half = (
            np.abs(np.where(pre, m["open_interest"] / 2, m["open_interest"]) - m["open_interest_rq"]) < 1e-6
        )
        dv = m["volume"] - m["volume_rq"]
        doi = m["open_interest_rq"] - m["open_interest"]
        efp = (~vol_raw) & (np.abs(dv - doi) < 1e-6)
        summaries.append(
            {
                "symbol": sym,
                "pairs": len(m),
                "date_min": m["date"].min().date(),
                "date_max": m["date"].max().date(),
                "ohlc_match_traded": float(ohlc_eq[traded].mean()) if traded.any() else float("nan"),
                "untraded_fill_settle": float(fill_ok[untraded].mean()) if untraded.any() else float("nan"),
                "vol_match_raw": float(vol_raw.mean()),
                "oi_match_raw": float(oi_raw.mean()),
                "vol_match_half_pre2020": float(vol_half.mean()),
                "oi_match_half_pre2020": float(oi_half.mean()),
                "vol_mismatch_efp_pattern": float(efp.sum() / max(int((~vol_raw).sum()), 1)),
                "vol_mismatch_rq_lower": float((dv[~vol_raw] > 0).mean())
                if (~vol_raw).any()
                else float("nan"),
                "pre2020_pairs": int(pre.sum()),
                "ex_only_rows": int(len(ex) - len(m)),
            }
        )
        bad = m[~(ohlc_ok & vol_raw & oi_raw)].copy()
        if not bad.empty:
            bad["reason"] = np.where(
                ~ohlc_ok[bad.index],
                "ohlc",
                np.where(
                    efp[bad.index], "volume_efp", np.where(~vol_raw[bad.index], "volume", "open_interest")
                ),
            )
            mism.append(
                bad[
                    [
                        "date",
                        "contract",
                        "reason",
                        "open",
                        "open_rq",
                        "high",
                        "high_rq",
                        "low",
                        "low_rq",
                        "close",
                        "close_rq",
                        "settle",
                        "volume",
                        "volume_rq",
                        "open_interest",
                        "open_interest_rq",
                    ]
                ]
            )
    summary = pd.DataFrame(summaries)
    mismatches = pd.concat(mism, ignore_index=True) if mism else pd.DataFrame()
    return summary, mismatches


# ----------------------------------------------------------------------------- CLI


def _parse_kinds(s: str) -> list[str]:
    ks = [k.strip() for k in s.split(",") if k.strip()]
    bad = [k for k in ks if k not in KINDS]
    if bad:
        raise SystemExit(f"unknown kinds {bad}; choose from {KINDS}")
    return ks


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m cta.data.exchanges.czce", description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="data/exchanges 根目录(默认仓库内)")
    ap.add_argument("--sleep", type=float, default=1.0, help="请求间隔秒(≥1)")
    ap.add_argument("--cdp-proxy", default=DEFAULT_CDP_PROXY, help="CDP 代理地址;'none' 关闭回退")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="回填区间(可断点续跑)")
    b.add_argument("--start", default=FIRST_DATE.strftime("%Y-%m-%d"))
    b.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    b.add_argument("--kinds", default=",".join(KINDS))
    b.add_argument("--no-annual", action="store_true", help="不用年度打包,逐日抓行情")
    b.add_argument("--retry-missing", action="store_true", help="重试 missing.log 里的日期")
    i = sub.add_parser("ingest", help="抓取单日(每日增量)")
    i.add_argument("--date", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    i.add_argument("--kinds", default=",".join(KINDS))
    i.add_argument("--overwrite", action="store_true")
    r = sub.add_parser("reparse", help="从 raw 重新解析并覆盖 parquet")
    r.add_argument("--start", default=FIRST_DATE.strftime("%Y-%m-%d"))
    r.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    r.add_argument("--kinds", default=",".join(KINDS))
    sub.add_parser("coverage", help="每类每年天数")
    c = sub.add_parser("reconcile", help="与米筐导出对账")
    c.add_argument("--symbols", default=",".join(RECONCILE_SYMBOLS))
    c.add_argument("--out", type=Path, default=None, help="不一致样例写到 csv")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    store = Store(args.root) if args.root else Store()
    fetcher = Fetcher(
        sleep=max(args.sleep, 1.0), cdp_proxy=None if args.cdp_proxy == "none" else args.cdp_proxy
    )
    try:
        if args.cmd == "backfill":
            backfill(
                pd.Timestamp(args.start),
                pd.Timestamp(args.end),
                _parse_kinds(args.kinds),
                store,
                fetcher,
                use_annual=not args.no_annual,
                retry_missing=args.retry_missing,
            )
        elif args.cmd == "ingest":
            res = ingest_day(
                pd.Timestamp(args.date), _parse_kinds(args.kinds), store, fetcher, overwrite=args.overwrite
            )
            print(json.dumps(res, ensure_ascii=False))
        elif args.cmd == "reparse":
            print(reparse(pd.Timestamp(args.start), pd.Timestamp(args.end), _parse_kinds(args.kinds), store))
        elif args.cmd == "coverage":
            print(coverage(store).to_string())
        elif args.cmd == "reconcile":
            summary, mism = reconcile([s.strip() for s in args.symbols.split(",")], store)
            print(summary.to_string(index=False))
            print(f"mismatches: {len(mism)}")
            if args.out and not mism.empty:
                mism.to_csv(args.out, index=False)
    finally:
        fetcher.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
