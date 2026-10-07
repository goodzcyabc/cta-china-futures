"""上期所库存周报(库存周报)—— 非仓单可交割库存(预注册 docs/research/altdata_prereg.md 第 6 节,试验 55)。

来源(官方、免登录):
- JSON 时代(报告日 2014-05-23 → 2025-11-14):
  https://www.shfe.com.cn/data/tradedata/future/weeklydata/{YYYYMMDD}weeklystock.dat
  行在 o_cursor 下;VARNAME(中文部分)识别品种,WHABBRNAME 以 总计 / 保税商品总计 / 完税商品总计 标记汇总行;
  字段 SPOTWGHTS(小计 = 全部符合交割品质的库存)、WRTWGHTS(期货 = 仓单)、WHSTOCKS(可用库容),
  PRE* 为上周同字段;update_date 为交易所嵌入的生成时间(北京)。
- HTML 时代(报告日 2025-10-31 起):
  https://www.shfe.com.cn/data/tradedata/future/stockdata/weeklystock_{YYYYMMDD}/ZH/all.html
  每个品种一张 el-table_table,表头行 special_row_type 给品种名,isTotal 行给 总计 等汇总;
  列:上周小计、上周期货、本周小计、本周期货、增减小计、增减期货、上周库容、本周库容、库容增减。无 Last-Modified。
报告日 = 每周最后一个交易日:从 2014-05-23 起逐周五尝试,404 时向前退到周四…周一(整周休市则无报告)。

品种(写死):CU 铜、AL 铝、NI 镍、SN 锡、RU 天然橡胶。每品种每报告日取 总计 行的 小计(total)、期货(warrant)、
库容(capacity),value = off_warrant = 小计 − 期货(吨)。若只有 保税/完税 两行而无 总计 行则相加;两行另存 meta。

可得规则(预注册,写死):available_day = 报告日 R 之后的第一个交易日,交易日 = 周一至周五 且不在 configs/holidays.csv
(该文件只登记 2026 年起的公告休市日;更早年份的法定假日未登记,则 available_day 可能落在非交易日,
下游按"A 当日或之后的第一个交易日"记暴露,不会早于真实的下一交易日)。
不用 Last-Modified 推可得日(2014–2023 的文件在 2024-03-20 被整体重写,头部无信息);但每个原始文件的
Last-Modified(UTC)与嵌入 update_date 都随文件落盘并写进观测表的 meta 列。

原始文件全部保留在 dest/raw/{json,html}/,旁边有同名 .meta.json(url、抓取时间、Last-Modified、大小、update_date);
404(以及 2014–2015 服务器对无报告日返回的 200 + 空 o_cursor)记录在 dest/raw/not_found.csv
(报告日 7 天后仍无报告的日期不再重探)。
已知口径:2014–2015 年若周五为交易所休市日,服务器仍有以该周五命名的文件,内容与该周最后一个交易日的文件
逐字相同(2015-01-02、2015-02-20、2015-05-01);本模块按周五记 obs_date,可得日因此比必要的晚、绝不会早。

命令行:PYTHONPATH=src python3 -m cta.data.alt.shfe_weekly --dest data/external/alt/shfe_weekly
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html as html_lib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------------------------

BASE_URL = "https://www.shfe.com.cn/data/tradedata/future"
JSON_URL = BASE_URL + "/weeklydata/{d}weeklystock.dat"
HTML_URL = BASE_URL + "/stockdata/weeklystock_{d}/ZH/all.html"

DEFAULT_START = "2014-05-23"  # 第一份可下载的 JSON 周报
JSON_LAST = date(2025, 11, 14)  # 最后一份 JSON(之后 404)
HTML_FIRST = date(2025, 10, 31)  # 第一份 HTML
NOT_FOUND_STABLE_DAYS = 7  # 报告日 7 天后仍 404 → 视为该日无报告,不再重探

PRODUCTS: dict[str, str] = {"铜": "CU", "铝": "AL", "镍": "NI", "锡": "SN", "天然橡胶": "RU"}
KEY_PREFIX = "S-"
TOTAL_LABELS: dict[str, str] = {"总计": "total", "保税商品总计": "bonded", "完税商品总计": "dutypaid"}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
MIN_INTERVAL = 0.8  # 秒;同一主机两次请求最小间隔
RETRIES = 4
TIMEOUT = 60
BEIJING = timezone(timedelta(hours=8))

OBS_COLUMNS: list[str] = [
    "obs_date",
    "available_day",
    "key",
    "value",
    "total",
    "warrant",
    "capacity",
    "bonded_total",
    "bonded_warrant",
    "dutypaid_total",
    "dutypaid_warrant",
    "prev_total",
    "prev_warrant",
    "prev_capacity",
    "source_format",
    "last_modified_utc",
    "update_date",
    "raw_file",
]


class FetchError(RuntimeError):
    pass


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------------------------


@dataclass
class Record:
    """一个品种在一个报告日的汇总行(全部仓库 总计)。数值单位吨;None = 该字段在报告里为空。"""

    symbol: str
    report_date: date
    total: float | None = None
    warrant: float | None = None
    capacity: float | None = None
    prev_total: float | None = None
    prev_warrant: float | None = None
    prev_capacity: float | None = None
    bonded_total: float | None = None
    bonded_warrant: float | None = None
    dutypaid_total: float | None = None
    dutypaid_warrant: float | None = None
    source_format: str = ""
    last_modified_utc: str = ""
    update_date: str = ""
    raw_file: str = ""

    @property
    def off_warrant(self) -> float | None:
        if self.total is None or self.warrant is None:
            return None
        return self.total - self.warrant


@dataclass
class _TotalRow:
    total: float | None = None
    warrant: float | None = None
    capacity: float | None = None
    prev_total: float | None = None
    prev_warrant: float | None = None
    prev_capacity: float | None = None


@dataclass
class _ProductTotals:
    rows: dict[str, _TotalRow] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------------------------


def _num(v: Any) -> float | None:
    """报告里的数字:int/float 原样;字符串去逗号;空串、'-'、'--' 为空。"""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ParseError(f"unexpected boolean cell {v!r}")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "—", "None", "null"):
        return None
    try:
        return float(s)
    except ValueError as e:
        raise ParseError(f"non-numeric cell {v!r}") from e


def _cn(s: Any) -> str:
    """'铜$$COPPER' → '铜'(中英双语字段的中文部分,去空白)。"""
    return str(s if s is not None else "").split("$$")[0].strip()


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_iso(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _today_beijing() -> date:
    return datetime.now(BEIJING).date()


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_modified_iso(header: str | None) -> str:
    """HTTP Last-Modified → 'YYYY-MM-DDTHH:MM:SSZ'(UTC);无头部为空串。"""
    if not header:
        return ""
    dt = parsedate_to_datetime(header)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _combine(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return a + b


# ---------------------------------------------------------------------------------------------
# 交易日历与可得日(预注册规则)
# ---------------------------------------------------------------------------------------------


def repo_holidays_path() -> Path:
    return Path(__file__).resolve().parents[4] / "configs" / "holidays.csv"


def load_holidays(path: Path | None = None) -> set[date]:
    """configs/holidays.csv(列 date,name;# 注释)→ 日期集合;文件不存在 → 空集合。"""
    p = path if path is not None else repo_holidays_path()
    if not p.exists():
        return set()
    out: set[date] = set()
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(line for line in fh if not line.lstrip().startswith("#")):
            s = (row.get("date") or "").strip()
            if s:
                out.add(_parse_iso(s))
    return out


def is_trading_day(d: date, holidays: Collection[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def available_day(report_date: date, holidays: Collection[date]) -> date:
    """可得日 = 报告日之后(严格)的第一个交易日。报告在 R 当天 15:00 收盘后公布,R+1 起任何日子 15:00 前都已公开。"""
    d = report_date + timedelta(days=1)
    while not is_trading_day(d, holidays):
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------------------------
# 解析:JSON
# ---------------------------------------------------------------------------------------------


def _finish(symbol: str, report_date: date, totals: _ProductTotals) -> Record | None:
    rows = totals.rows
    rec = Record(symbol=symbol, report_date=report_date)
    bonded, dutypaid = rows.get("bonded"), rows.get("dutypaid")
    if bonded is not None:
        rec.bonded_total, rec.bonded_warrant = bonded.total, bonded.warrant
    if dutypaid is not None:
        rec.dutypaid_total, rec.dutypaid_warrant = dutypaid.total, dutypaid.warrant
    main = rows.get("total")
    if main is None:
        if bonded is None or dutypaid is None:
            return None
        main = _TotalRow(
            total=_combine(bonded.total, dutypaid.total),
            warrant=_combine(bonded.warrant, dutypaid.warrant),
            capacity=_combine(bonded.capacity, dutypaid.capacity),
            prev_total=_combine(bonded.prev_total, dutypaid.prev_total),
            prev_warrant=_combine(bonded.prev_warrant, dutypaid.prev_warrant),
            prev_capacity=_combine(bonded.prev_capacity, dutypaid.prev_capacity),
        )
    rec.total, rec.warrant, rec.capacity = main.total, main.warrant, main.capacity
    rec.prev_total, rec.prev_warrant, rec.prev_capacity = (
        main.prev_total,
        main.prev_warrant,
        main.prev_capacity,
    )
    return rec


def parse_json(raw: bytes, report_date: date) -> list[Record]:
    """weeklystock.dat → 五个品种的汇总 Record(品种缺席则没有)。"""
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ParseError(f"{_ymd(report_date)}: not JSON ({e})") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("o_cursor"), list):
        raise ParseError(f"{_ymd(report_date)}: no o_cursor")
    embedded = str(doc.get("report_date") or doc.get("o_tradingday") or "")
    if embedded and embedded != _ymd(report_date):
        raise ParseError(f"{_ymd(report_date)}: embedded report_date {embedded} differs from file name")
    update_date = str(doc.get("update_date") or "")
    per: dict[str, _ProductTotals] = {}
    for row in doc["o_cursor"]:
        if not isinstance(row, dict):
            continue
        symbol = PRODUCTS.get(_cn(row.get("VARNAME")))
        if symbol is None:
            continue
        varid = str(row.get("VARID") or "").strip().upper()
        if varid and varid != symbol:
            raise ParseError(f"{_ymd(report_date)}: VARNAME {row.get('VARNAME')!r} but VARID {varid!r}")
        kind = TOTAL_LABELS.get(_cn(row.get("WHABBRNAME")))
        if kind is None:
            continue
        totals = per.setdefault(symbol, _ProductTotals())
        if kind in totals.rows:
            raise ParseError(f"{_ymd(report_date)}: duplicate {kind} row for {symbol}")
        totals.rows[kind] = _TotalRow(
            total=_num(row.get("SPOTWGHTS")),
            warrant=_num(row.get("WRTWGHTS")),
            capacity=_num(row.get("WHSTOCKS")),
            prev_total=_num(row.get("PRESPOTWGHTS")),
            prev_warrant=_num(row.get("PREWRTWGHTS")),
            prev_capacity=_num(row.get("PREWHSTOCKS")),
        )
    out: list[Record] = []
    for symbol in PRODUCTS.values():
        if symbol in per:
            rec = _finish(symbol, report_date, per[symbol])
            if rec is not None:
                rec.source_format, rec.update_date = "json", update_date
                out.append(rec)
    return out


# ---------------------------------------------------------------------------------------------
# 解析:HTML
# ---------------------------------------------------------------------------------------------

_TABLE_RE = re.compile(r"<table[^>]*class=\"el-table_table\"[^>]*>(.*?)</table>", re.S)
_HEADER_RE = re.compile(r"special_row_type[^>]*>(.*?)</tr>", re.S)
_CELL_DIV_RE = re.compile(r"<div[^>]*class=\"cell\"[^>]*>(.*?)</div>", re.S)
_TOTAL_ROW_RE = re.compile(r"<tr[^>]*class=\"[^\"]*\bisTotal\b[^\"]*\"[^>]*>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_INTRO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\d{4}年")


def _text(fragment: str) -> str:
    return html_lib.unescape(_TAG_RE.sub("", fragment)).replace("\xa0", " ").strip()


def parse_html(raw: bytes, report_date: date) -> list[Record]:
    """weeklystock_{d}/ZH/all.html → 五个品种的汇总 Record。"""
    text = raw.decode("utf-8", errors="replace")
    if "el-table_table" not in text:
        raise ParseError(f"{_ymd(report_date)}: no el-table_table in HTML")
    m = _INTRO_DATE_RE.search(text)
    if m is not None and m.group(1) != report_date.isoformat():
        raise ParseError(f"{_ymd(report_date)}: embedded date {m.group(1)} differs from file name")
    per: dict[str, _ProductTotals] = {}
    for table in _TABLE_RE.findall(text):
        hm = _HEADER_RE.search(table)
        if hm is None:
            continue
        cells = [_text(c) for c in _CELL_DIV_RE.findall(hm.group(1))]
        if not cells:
            continue
        symbol = PRODUCTS.get(cells[0])
        if symbol is None:
            continue
        totals = per.setdefault(symbol, _ProductTotals())
        for rm in _TOTAL_ROW_RE.finditer(table):
            tds = [_text(td) for td in _TD_RE.findall(rm.group(1))]
            if len(tds) < 10:
                continue
            kind = TOTAL_LABELS.get(tds[0])
            if kind is None:
                continue
            if kind in totals.rows:
                raise ParseError(f"{_ymd(report_date)}: duplicate {kind} row for {symbol}")
            nums = [_num(x) for x in tds[-9:]]
            # 上周小计, 上周期货, 本周小计, 本周期货, 增减小计, 增减期货, 上周库容, 本周库容, 库容增减
            totals.rows[kind] = _TotalRow(
                total=nums[2],
                warrant=nums[3],
                capacity=nums[7],
                prev_total=nums[0],
                prev_warrant=nums[1],
                prev_capacity=nums[6],
            )
    out: list[Record] = []
    for symbol in PRODUCTS.values():
        if symbol in per:
            rec = _finish(symbol, report_date, per[symbol])
            if rec is not None:
                rec.source_format = "html"
                out.append(rec)
    return out


# ---------------------------------------------------------------------------------------------
# 下载(存 raw,幂等可续传)
# ---------------------------------------------------------------------------------------------

_last_request_at: list[float] = [0.0]


def _throttle() -> None:
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    _last_request_at[0] = time.monotonic()


def _validate_json(body: bytes) -> bool:
    try:
        doc = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(doc, dict) and isinstance(doc.get("o_cursor"), list)


def _validate_html(body: bytes) -> bool:
    return b"el-table_table" in body


def _get_once(url: str) -> tuple[int, bytes, str | None]:
    """单次 GET:返回 (status, 解压后的 body, Last-Modified 头);HTTP 错误状态作为状态码返回而不抛。"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = int(resp.status)
            body = bytes(resp.read())
            lm = resp.headers.get("Last-Modified")
            enc = str(resp.headers.get("Content-Encoding") or "").lower()
    except urllib.error.HTTPError as e:
        return int(e.code), b"", None
    if enc == "gzip" and body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return status, body, (str(lm) if lm else None)


def http_get(url: str, valid: Callable[[bytes], bool]) -> tuple[int, bytes, str | None]:
    """GET url。404 → (404, b'', None);2xx 且内容通过 valid → (status, body, Last-Modified);
    其他状态、网络错误、2xx 但内容不对(WAF 挑战页)→ 指数退避重试,用尽后抛 FetchError。"""
    delay = 2.0
    last = ""
    for attempt in range(RETRIES + 1):
        _throttle()
        try:
            status, body, lm = _get_once(url)
            if status == 404:
                return 404, b"", None
            if 200 <= status < 300:
                if valid(body):
                    return status, body, lm
                last = f"HTTP {status} but body failed validation ({len(body)} bytes)"
            else:
                last = f"HTTP {status}"
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError, EOFError) as e:  # 网络层
            last = str(e)
        if attempt < RETRIES:
            log.warning("GET %s failed (%s); retry in %.0fs", url, last, delay)
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"{url}: {last}")


def raw_paths(raw: Path, d: date, fmt: str) -> tuple[Path, Path]:
    """(数据文件, 旁车 meta)。"""
    if fmt == "json":
        f = raw / "json" / f"{_ymd(d)}weeklystock.dat"
    elif fmt == "html":
        f = raw / "html" / f"weeklystock_{_ymd(d)}.html"
    else:
        raise ValueError(fmt)
    return f, f.with_name(f.name + ".meta.json")


def url_for(d: date, fmt: str) -> str:
    return (JSON_URL if fmt == "json" else HTML_URL).format(d=_ymd(d))


def formats_for(d: date) -> list[str]:
    out: list[str] = []
    if d <= JSON_LAST:
        out.append("json")
    if d >= HTML_FIRST:
        out.append("html")
    return out


def _not_found_path(raw: Path) -> Path:
    return raw / "not_found.csv"


def _load_not_found(raw: Path) -> dict[tuple[str, str], str]:
    """(YYYY-MM-DD, fmt) → probed_at_utc。"""
    p = _not_found_path(raw)
    out: dict[tuple[str, str], str] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["report_date"], row["format"])] = row["probed_at_utc"]
    return out


def _record_not_found(raw: Path, d: date, fmt: str, not_found: dict[tuple[str, str], str]) -> None:
    p = _not_found_path(raw)
    new = not p.exists()
    probed = _utc_now_iso()
    with p.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["report_date", "format", "probed_at_utc"])
        w.writerow([d.isoformat(), fmt, probed])
    not_found[(d.isoformat(), fmt)] = probed


def _not_found_is_final(d: date, probed_at_utc: str) -> bool:
    probed = datetime.strptime(probed_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (probed.astimezone(BEIJING).date() - d).days >= NOT_FOUND_STABLE_DAYS


def file_present(raw: Path, d: date, fmt: str) -> bool:
    """数据文件与 meta 都在且大小与 meta 记录一致。"""
    f, m = raw_paths(raw, d, fmt)
    if not (f.exists() and m.exists()):
        return False
    try:
        meta = json.loads(m.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(isinstance(meta, dict) and meta.get("size") == f.stat().st_size)


def ensure_file(raw: Path, d: date, fmt: str, not_found: dict[tuple[str, str], str]) -> bool:
    """确保 (d, fmt) 的原始文件在本地;返回该报告是否存在。已在本地(大小匹配)或已知最终 404 则不发请求。"""
    if file_present(raw, d, fmt):
        return True
    probed = not_found.get((d.isoformat(), fmt))
    if probed is not None and _not_found_is_final(d, probed):
        return False
    url = url_for(d, fmt)
    status, body, last_modified = http_get(url, _validate_json if fmt == "json" else _validate_html)
    if status == 404:
        _record_not_found(raw, d, fmt, not_found)
        log.info("%s %s: 404", d, fmt)
        return False
    update_date = ""
    if fmt == "json":
        doc = json.loads(body.decode("utf-8-sig"))
        if not doc["o_cursor"]:
            # 2014–2015 的服务器对无报告的日子返回 200 + 空 o_cursor(而非 404);视为无报告,继续向前退。
            _record_not_found(raw, d, fmt, not_found)
            log.info("%s %s: HTTP %d but empty o_cursor → no report", d, fmt, status)
            return False
        update_date = str(doc.get("update_date") or "")
    f, m = raw_paths(raw, d, fmt)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(body)
    meta: dict[str, Any] = {
        "url": url,
        "report_date": d.isoformat(),
        "format": fmt,
        "http_status": status,
        "size": len(body),
        "fetched_at_utc": _utc_now_iso(),
        "last_modified_http": last_modified,
        "last_modified_utc": _last_modified_iso(last_modified),
        "update_date": update_date,
    }
    m.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info(
        "%s %s: saved %d bytes (Last-Modified %s, update_date %s)",
        d,
        fmt,
        len(body),
        last_modified,
        update_date,
    )
    return True


def _fridays(start: date, end: date) -> Iterator[date]:
    """start 所在周(含)到 end 所在周(含)的每个周五。"""
    first = start + timedelta(days=(4 - start.weekday()) % 7)
    d = first
    while d - timedelta(days=4) <= end:
        yield d
        d += timedelta(days=7)


def fetch(dest: Path, start: str = DEFAULT_START, end: str = "") -> None:
    """抓取 [start, end](end 为空 = 北京今天)内每周的库存周报到 dest/raw,幂等、可续传。
    每周:周五 → 404 则周四 … 周一;某日在 JSON/HTML 时代各试其格式(重叠期两种都存)。"""
    start_d = _parse_iso(start)
    end_d = _parse_iso(end) if end else _today_beijing()
    raw = dest / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    not_found = _load_not_found(raw)
    n_weeks = n_found = 0
    for friday in _fridays(start_d, end_d):
        n_weeks += 1
        for back in range(5):
            d = friday - timedelta(days=back)
            if d < start_d or d > end_d:
                continue
            found = False
            for fmt in formats_for(d):
                if ensure_file(raw, d, fmt, not_found):
                    found = True
            if found:
                n_found += 1
                break
    log.info("fetch done: %d weeks scanned, %d reports present", n_weeks, n_found)


# ---------------------------------------------------------------------------------------------
# 读取 → 观测表
# ---------------------------------------------------------------------------------------------


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def iter_raw(raw: Path) -> Iterator[tuple[date, str, Path]]:
    """按报告日、格式(json 先于 html)枚举本地原始文件。"""
    items: list[tuple[date, str, Path]] = []
    for f in (raw / "json").glob("*weeklystock.dat"):
        items.append((datetime.strptime(f.name[:8], "%Y%m%d").date(), "json", f))
    for f in (raw / "html").glob("weeklystock_*.html"):
        items.append((datetime.strptime(f.stem.split("_")[1], "%Y%m%d").date(), "html", f))
    items.sort(key=lambda t: (t[0], 0 if t[1] == "json" else 1))
    yield from items


def parse_file(path: Path, d: date, fmt: str) -> list[Record]:
    recs = parse_json(path.read_bytes(), d) if fmt == "json" else parse_html(path.read_bytes(), d)
    meta = _read_meta(path.with_name(path.name + ".meta.json"))
    for r in recs:
        r.last_modified_utc = str(meta.get("last_modified_utc") or "")
        if fmt == "json" and not r.update_date:
            r.update_date = str(meta.get("update_date") or "")
        r.raw_file = f"raw/{fmt}/{path.name}"
    return recs


def load_records(dest: Path) -> tuple[dict[tuple[str, date], Record], list[tuple[Record, Record]]]:
    """所有原始文件 → {(symbol, report_date): Record};重叠期 JSON 优先,HTML 副本与之比较,返回差异对。"""
    raw = dest / "raw"
    records: dict[tuple[str, date], Record] = {}
    overlap_mismatch: list[tuple[Record, Record]] = []
    for d, fmt, path in iter_raw(raw):
        for rec in parse_file(path, d, fmt):
            k = (rec.symbol, d)
            if k in records:
                prev = records[k]
                if (prev.total, prev.warrant, prev.capacity) != (rec.total, rec.warrant, rec.capacity):
                    overlap_mismatch.append((prev, rec))
                continue
            records[k] = rec
    return records, overlap_mismatch


def records_to_frame(records: Collection[Record], holidays: Collection[date]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for r in records:
        v = r.off_warrant
        if v is None:
            continue
        rows.append(
            {
                "obs_date": r.report_date.isoformat(),
                "available_day": available_day(r.report_date, holidays).isoformat(),
                "key": KEY_PREFIX + r.symbol,
                "value": float(v),
                "total": r.total,
                "warrant": r.warrant,
                "capacity": r.capacity,
                "bonded_total": r.bonded_total,
                "bonded_warrant": r.bonded_warrant,
                "dutypaid_total": r.dutypaid_total,
                "dutypaid_warrant": r.dutypaid_warrant,
                "prev_total": r.prev_total,
                "prev_warrant": r.prev_warrant,
                "prev_capacity": r.prev_capacity,
                "source_format": r.source_format,
                "last_modified_utc": r.last_modified_utc,
                "update_date": r.update_date,
                "raw_file": r.raw_file,
            }
        )
    df = pd.DataFrame(rows, columns=OBS_COLUMNS)
    df = df.sort_values(["key", "obs_date"], kind="mergesort").reset_index(drop=True)
    dup = df.duplicated(["key", "obs_date"])
    if bool(dup.any()):
        raise ParseError(f"duplicate (key, obs_date): {df.loc[dup, ['key', 'obs_date']].values.tolist()[:5]}")
    return df


def load(dest: Path, holidays_path: Path | None = None) -> pd.DataFrame:
    """原始文件 → 观测表(obs_date, available_day, key, value, meta…),available_day 按预注册规则重算。"""
    records, _ = load_records(dest)
    return records_to_frame(list(records.values()), load_holidays(holidays_path))


def write_observations(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, float_format="%.12g", lineterminator="\n")


# ---------------------------------------------------------------------------------------------
# 一致性检查:报告 t+1 的"上周"字段 == 报告 t 的"本周"字段
# ---------------------------------------------------------------------------------------------


def consistency_check(df: pd.DataFrame) -> pd.DataFrame:
    """逐品种按 obs_date 排序,相邻两份报告比较 prev_* 与前一份的 total/warrant/capacity;返回不一致明细。
    两边都空视为一致;一边空一边有值或数值不等视为不一致。"""
    out: list[pd.DataFrame] = []
    pairs = (("prev_total", "total"), ("prev_warrant", "warrant"), ("prev_capacity", "capacity"))
    cols = ["key", "obs_date", "prev_obs_date", "field", "reported_prev", "actual_prev"]
    for _key, g0 in df.sort_values(["key", "obs_date"]).groupby("key", sort=True):
        g = g0.reset_index(drop=True)
        if len(g) < 2:
            continue
        prev_date = g["obs_date"].shift(1)
        has_prev = prev_date.notna()
        for pf, cf in pairs:
            reported = pd.to_numeric(g[pf], errors="coerce")
            actual = pd.to_numeric(g[cf], errors="coerce").shift(1)
            both_nan = reported.isna() & actual.isna()
            bad = has_prev & ~both_nan & (reported != actual)
            if bool(bad.any()):
                part = pd.DataFrame(
                    {
                        "key": g.loc[bad, "key"],
                        "obs_date": g.loc[bad, "obs_date"],
                        "prev_obs_date": prev_date[bad],
                        "field": cf,
                        "reported_prev": reported[bad],
                        "actual_prev": actual[bad],
                    }
                )
                out.append(part)
    if not out:
        return pd.DataFrame(columns=cols)
    res = pd.concat(out, ignore_index=True)[cols]
    return res.sort_values(["key", "obs_date", "field"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------------------------


def _summary(df: pd.DataFrame, overlap_mismatch: list[tuple[Record, Record]]) -> str:
    lines = [f"observations: {len(df)} rows, {df['key'].nunique()} keys"]
    if len(df):
        lines.append(f"obs_date range: {df['obs_date'].min()} → {df['obs_date'].max()}")
        for key, g in df.groupby("key"):
            lines.append(
                f"  {key}: {len(g)} weeks {g['obs_date'].min()} → {g['obs_date'].max()}, "
                f"json={int((g['source_format'] == 'json').sum())} html={int((g['source_format'] == 'html').sum())}"
            )
        mism = consistency_check(df)
        lines.append(f"week-to-week consistency mismatches (prev-week fields vs prior report): {len(mism)}")
        if len(mism):
            lines.append(mism.head(20).to_string(index=False))
    lines.append(f"json/html overlap value mismatches: {len(overlap_mismatch)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="SHFE weekly inventory report → observations.csv")
    ap.add_argument("--dest", type=Path, required=True, help="data/external/alt/shfe_weekly")
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default="", help="YYYY-MM-DD; empty = today (Beijing)")
    ap.add_argument("--no-fetch", action="store_true", help="only rebuild observations.csv from raw/")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dest: Path = args.dest
    if not args.no_fetch:
        fetch(dest, args.start, args.end)
    records, overlap_mismatch = load_records(dest)
    df = records_to_frame(list(records.values()), load_holidays())
    out = dest / "observations.csv"
    write_observations(df, out)
    print(f"wrote {out}")
    print(_summary(df, overlap_mismatch))


if __name__ == "__main__":
    main()
