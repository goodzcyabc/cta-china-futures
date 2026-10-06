"""郑商所期权日行情 → 标准期权日表 options_daily.parquet(预注册 docs/research/options_prereg.md 第 2–3 节)。

来源(官方静态文件,免登录、无需浏览器;.htm/.zip 受 JS 反爬保护,本模块从不请求、也不绕过):
  每日文件 https://www.czce.com.cn/cn/DFSStaticFiles/Option/{YYYY}/{YYYYMMDD}/OptionDataDaily.txt
  2017-04-19(白糖期权首日)起每个交易日一份;休市日 404;期权上市前 200 + "无交易记录!"。
  年度文件 .../Option/{YYYY}/OptionDataAllHistory/{SYM}OPTIONS{YYYY}.txt 只用于抽样交叉核对(Range 取两段),不作数据源。
格式:竖线分隔定宽表,千分位逗号;2017 年文件为 GBK(响应头仍写 utf-8),之后 UTF-8(先严格 UTF-8,失败退回 GB18030)。
  表头 2017–2021-03 为 品种代码/空盘量,之后为 合约代码/持仓量;其余列 昨结算 今开盘 最高价 最低价 今收盘 今结算 涨跌1 涨跌2
  成交量(手) 增减量 成交额(万元) DELTA 隐含波动率 行权量。汇总行 小计 / XX合计 / 总计 剔除(XX合计 用来核对逐合约加总)。
  期权代码 SR707C6200(3 位年月,十年位按文件日期推断),序列期权带 MS(SR701MSC4900,标的仍为 SR2701 期货,到期更早),
  保留并标 is_serial=True。
口径:成交量/持仓量/成交额 2020-01-01 前为双边 → volume/oi/turnover 折半,原值存 *_raw;成交额万元 ×1e4 → 元;
  隐含波动率为百分数 → /100 存 iv_exchange(交易所结算 IV,逐合约,含偏度;0 或空 → NaN);DELTA 原样(看跌为负)。
  series_volume / series_oi = 同一标的、非序列期权的当日合计(单边);同一 (date, underlying) 的所有行(含序列期权行)取同一值,
  该标的当日没有常规期权时为 NaN。expire_date 文件不提供 → NaT。未成交合约 close 按原样(郑商所填 0)保留。
可得日:available_day = date 之后第一个交易日;交易日 = 项目期货行情 data/exchanges/*/quotes_all.parquet 的日期 ∪ 本来源期权文件日期;
  超出该日历末端时用 工作日 − configs/holidays.csv。

落盘(dest = data/external/alt/czce_options):
  raw/{YYYY}/{YYYYMMDD}_OptionDataDaily.txt.gz + 同名 .meta.json(url、HTTP 状态、Last-Modified(UTC)、抓取时间(UTC)、sha256、
  编码、文件内标题日期;郑商所文件无生成时间戳,update_date 为空);raw/not_found.csv 记 404 / 无交易记录 的日期;
  raw/annual_crosscheck/ 年度文件的 Range 片段;options_daily.parquet、files.csv、build_report.json、crosscheck_annual.csv。

命令行:PYTHONPATH=src python3 -m cta.data.alt.czce_options --dest data/external/alt/czce_options
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import http.client
import json
import logging
import os
import re
import time
import zlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.data.exchanges.base import normalize_contract
from cta.data.exchanges.czce import SINGLE_SIDED_FROM, TURNOVER_UNIT, USER_AGENT, decode_text

log = logging.getLogger("cta.alt.czce_options")

# ---------------------------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------------------------

EXCHANGE = "CZCE"
HOST = "www.czce.com.cn"
DAILY_PATH = "/cn/DFSStaticFiles/Option/{y}/{ymd}/OptionDataDaily.txt"
ANNUAL_PATH = "/cn/DFSStaticFiles/Option/{y}/OptionDataAllHistory/{sym}OPTIONS{y}.txt"
FIRST_DAY = "2017-04-19"  # 白糖期权上市首日 = 第一份有数据的 OptionDataDaily.txt
LAST_DAY = "2026-09-30"

MIN_INTERVAL = 1.05  # 秒;两次请求开始的最小间隔(≤ 1 次/秒)
RETRIES = 5
TIMEOUT = 60.0
NOT_FOUND_STABLE_DAYS = 7  # 日期过去 7 天后仍 404 → 视为休市,不再重探
BEIJING = timezone(timedelta(hours=8))

REPO_ROOT = Path(__file__).resolve().parents[4]
QUOTES_ROOT = REPO_ROOT / "data" / "exchanges"
HOLIDAYS_CSV = REPO_ROOT / "configs" / "holidays.csv"

# 预注册第 3 节的 14 个品种;本来源只覆盖其中郑商所的 5 个(期权上市日,见预注册第 2 节)
PREREG_PRODUCTS: tuple[str, ...] = (
    "CU",
    "RU",
    "AU",
    "AL",
    "SC",
    "AG",
    "RB",
    "NI",
    "SN",
    "SR",
    "CF",
    "MA",
    "TA",
    "SA",
)
LISTING: dict[str, str] = {
    "SR": "2017-04-19",
    "CF": "2019-01-28",
    "MA": "2019-12-16",
    "TA": "2019-12-16",
    "SA": "2023-10-20",
}

CORE_COLUMNS: list[str] = [
    "date",
    "exchange",
    "product",
    "underlying",
    "option_code",
    "cp",
    "strike",
    "settle",
    "close",
    "volume",
    "oi",
    "turnover",
    "delta",
    "iv_exchange",
    "series_volume",
    "series_oi",
    "expire_date",
    "available_day",
    "source_file",
    "last_modified_utc",
    "update_date",
]
EXTRA_COLUMNS: list[str] = ["volume_raw", "oi_raw", "turnover_raw", "is_serial"]
OUT_COLUMNS: list[str] = CORE_COLUMNS + EXTRA_COLUMNS

# 表头(规范化后:全角括号→半角、去空白、delta 大写)→ 内部字段
HEADER_MAP: dict[str, str] = {
    "交易日期": "trade_date",  # 只在年度文件中出现
    "品种代码": "option_code",  # 2017–2021-03
    "合约代码": "option_code",  # 2021-03 起
    "品种月份": "option_code",
    "合约": "option_code",
    "昨结算": "prev_settle",
    "今开盘": "open",
    "最高价": "high",
    "最低价": "low",
    "今收盘": "close",
    "今结算": "settle",
    "涨跌1": "chg1",
    "涨跌2": "chg2",
    "成交量(手)": "volume",
    "成交量": "volume",
    "持仓量": "oi",
    "空盘量": "oi",  # 2017–2020 的叫法
    "增减量": "oi_chg",
    "成交额(万元)": "turnover",
    "成交额": "turnover",
    "DELTA": "delta",
    "隐含波动率": "iv",
    "隐含波动率(%)": "iv",
    "行权量": "exercise",
}
REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"option_code", "settle", "close", "volume", "oi", "turnover", "delta", "iv"}
)
NUMERIC_FIELDS: tuple[str, ...] = (
    "prev_settle",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "chg1",
    "chg2",
    "volume",
    "oi",
    "oi_chg",
    "turnover",
    "delta",
    "iv",
    "exercise",
)
_TOTAL_WORDS = ("小计", "合计", "总计")
_SYMBOL_ALIAS = {"PTA": "TA"}
# 常规 SR707C6200;序列 SR701MSC4900;兼容 SR701-C-5000 写法
OPT_RE = re.compile(r"^([A-Z]{1,2})(\d{3,4})(MS)?-?([CP])-?(\d+(?:\.\d+)?)$")
_TITLE_RE = re.compile(r"期权每日行情表\s*[(（]\s*(\d{4}-\d{2}-\d{2})\s*[)）]")
_PRODUCT_TOTAL_RE = re.compile(r"^([A-Za-z]{1,3})合计$")
NO_DATA_MARK = "无交易记录"


class FetchError(RuntimeError):
    pass


class ParseError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_modified_iso(header: str | None) -> str:
    """HTTP Last-Modified → 'YYYY-MM-DDTHH:MM:SSZ'(UTC);无头部为空串。"""
    if not header:
        return ""
    dt = parsedate_to_datetime(header)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ymd(d: pd.Timestamp) -> str:
    return pd.Timestamp(d).strftime("%Y%m%d")


def _num(cell: str) -> float:
    """严格数值:去千分位逗号;空、'-'、'--' → NaN;其他非数字抛 ParseError(格式变化要暴露出来)。"""
    s = cell.strip().replace(",", "")
    if s in ("", "-", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError as e:
        raise ParseError(f"non-numeric cell {cell!r}") from e


def norm_header(cell: str) -> str:
    s = cell.replace("（", "(").replace("）", ")").replace("　", "")
    s = re.sub(r"\s+", "", s)
    return s.upper() if s.lower() == "delta" else s


def detect_encoding(raw: bytes) -> str:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "gb18030"
    return "utf-8"


def daily_url(d: pd.Timestamp) -> str:
    d = pd.Timestamp(d)
    return f"https://{HOST}" + DAILY_PATH.format(y=d.year, ymd=_ymd(d))


def annual_url(sym: str, year: int) -> str:
    return f"https://{HOST}" + ANNUAL_PATH.format(y=year, sym=sym)


def is_double_sided(d: pd.Timestamp) -> bool:
    """2020-01-01 前郑商所成交量/持仓量/成交额/行权量为双边计数(交易所脚注;期权同样适用)。"""
    return pd.Timestamp(d) < SINGLE_SIDED_FROM


# ---------------------------------------------------------------------------------------------
# HTTP(keep-alive、限速、退避;404 直接返回;412 = JS 反爬,只退避重试,从不绕过)
# ---------------------------------------------------------------------------------------------


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]


class Client:
    def __init__(self, min_interval: float = MIN_INTERVAL, retries: int = RETRIES, timeout: float = TIMEOUT):
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self._conn: http.client.HTTPSConnection | None = None
        self._last = 0.0
        self.n_requests = 0
        self.bytes_on_wire = 0

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last = time.monotonic()

    def close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.close()
            self._conn = None

    def _once(self, path: str, headers: dict[str, str]) -> Response:
        if self._conn is None:
            self._conn = http.client.HTTPSConnection(HOST, timeout=self.timeout)
        self._conn.request("GET", path, headers=headers)
        resp = self._conn.getresponse()
        body = resp.read()
        self.bytes_on_wire += len(body)
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        if resp.will_close:
            self.close()
        if hdrs.get("content-encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        return Response(int(resp.status), body, hdrs)

    def get(
        self, path: str, valid: Callable[[Response], bool], extra_headers: dict[str, str] | None = None
    ) -> Response:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.czce.com.cn/",
        }
        if extra_headers:
            headers.update(extra_headers)
        else:
            headers["Accept-Encoding"] = "gzip"
        delay = 3.0
        last = ""
        for attempt in range(self.retries + 1):
            self._throttle()
            self.n_requests += 1
            try:
                r = self._once(path, headers)
            except (http.client.HTTPException, OSError, EOFError, zlib.error) as e:
                self.close()
                last = f"network error {e!r}"
            else:
                if r.status == 404:
                    return r
                if r.status in (200, 206) and valid(r):
                    return r
                last = f"HTTP {r.status} ({len(r.body)} bytes)"
                if r.status == 412:
                    last += " [anti-bot challenge; not circumvented]"
            if attempt < self.retries:
                log.warning("GET %s failed (%s); retry %d in %.0fs", path, last, attempt + 1, delay)
                time.sleep(delay)
                delay = min(delay * 2, 120.0)
        raise FetchError(f"{path}: {last}")


# ---------------------------------------------------------------------------------------------
# 原始文件布局
# ---------------------------------------------------------------------------------------------


def raw_dir(dest: Path) -> Path:
    return dest / "raw"


def raw_file(dest: Path, d: pd.Timestamp) -> Path:
    d = pd.Timestamp(d)
    return raw_dir(dest) / f"{d.year}" / f"{_ymd(d)}_OptionDataDaily.txt.gz"


def meta_file(dest: Path, d: pd.Timestamp) -> Path:
    d = pd.Timestamp(d)
    return raw_dir(dest) / f"{d.year}" / f"{_ymd(d)}_OptionDataDaily.meta.json"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def file_present(dest: Path, d: pd.Timestamp) -> bool:
    """数据文件与旁车 meta 都在,且 gzip 文件大小与 meta 记录一致。"""
    f, m = raw_file(dest, d), meta_file(dest, d)
    if not (f.exists() and m.exists()):
        return False
    meta = _read_json(m)
    return bool(meta.get("stored_size") == f.stat().st_size)


def _not_found_path(dest: Path) -> Path:
    return raw_dir(dest) / "not_found.csv"


NOT_FOUND_FIELDS = ["date", "http_status", "note", "url", "last_modified_utc", "probed_at_utc"]


def load_not_found(dest: Path) -> dict[str, dict[str, str]]:
    """YYYY-MM-DD → 最近一次探测记录。"""
    p = _not_found_path(dest)
    out: dict[str, dict[str, str]] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["date"]] = dict(row)
    return out


def _record_not_found(
    dest: Path, d: pd.Timestamp, status: int, note: str, lm: str, nf: dict[str, dict[str, str]]
) -> None:
    p = _not_found_path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    row = {
        "date": pd.Timestamp(d).strftime("%Y-%m-%d"),
        "http_status": str(status),
        "note": note,
        "url": daily_url(d),
        "last_modified_utc": lm,
        "probed_at_utc": _utc_now_iso(),
    }
    with p.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=NOT_FOUND_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    nf[row["date"]] = row


def _not_found_is_final(d: pd.Timestamp, probed_at_utc: str) -> bool:
    probed = datetime.strptime(probed_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (probed.astimezone(BEIJING).date() - pd.Timestamp(d).date()).days >= NOT_FOUND_STABLE_DAYS


# ---------------------------------------------------------------------------------------------
# 交易日历与可得日
# ---------------------------------------------------------------------------------------------


def load_holidays(path: Path = HOLIDAYS_CSV) -> set[pd.Timestamp]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, comment="#")
    return {pd.Timestamp(x).normalize() for x in df["date"]}


def futures_calendar(quotes_root: Path = QUOTES_ROOT) -> pd.DatetimeIndex:
    """项目期货行情的交易日并集(data/exchanges/*/quotes_all.parquet 的 date)。"""
    days: set[pd.Timestamp] = set()
    for p in sorted(quotes_root.glob("*/quotes_all.parquet")):
        col = pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"]).dt.normalize()
        days.update(pd.Timestamp(x) for x in col.unique())
    return pd.DatetimeIndex(sorted(days))


def available_day_map(
    dates: Iterable[pd.Timestamp], calendar: pd.DatetimeIndex, holidays: set[pd.Timestamp]
) -> dict[pd.Timestamp, pd.Timestamp]:
    """每个 T → T 之后(严格)第一个交易日:日历内取下一个日历日期;超出日历末端用 工作日 − 已公告假期。"""
    cal = pd.DatetimeIndex(sorted(set(calendar)))
    out: dict[pd.Timestamp, pd.Timestamp] = {}
    for t0 in sorted({pd.Timestamp(x).normalize() for x in dates}):
        pos = int(cal.searchsorted(t0, side="right"))
        if pos < len(cal):
            out[t0] = pd.Timestamp(cal[pos])
            continue
        d = t0 + pd.Timedelta(days=1)
        while d.weekday() >= 5 or d in holidays:
            d += pd.Timedelta(days=1)
        out[t0] = d
    return out


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


@dataclass
class ParsedTable:
    """一张期权行情表(每日文件或年度文件)的逐合约原始字段(未折算),以及表头与汇总行信息。
    rows 列:trade_date(仅年度文件非空)、option_code、product、ym、is_serial、cp、strike + NUMERIC_FIELDS。"""

    rows: pd.DataFrame
    header_raw: list[str]
    header_map: dict[str, str]
    title_date: str = ""
    n_aggregate: int = 0
    product_totals: dict[str, tuple[float, float]] = field(default_factory=dict)  # 品种 → (成交量, 持仓量)


def parse_table(text: str) -> ParsedTable:
    """竖线分隔的期权行情表 → ParsedTable。未知表头、无法识别的代码、非数字单元格一律抛 ParseError。"""
    header_raw: list[str] | None = None
    idx: dict[str, int] = {}
    title = ""
    cols: dict[str, list[Any]] = {}
    n_agg = 0
    totals: dict[str, tuple[float, float]] = {}
    for line in text.splitlines():
        if header_raw is None and not title:
            m = _TITLE_RE.search(line)
            if m:
                title = m.group(1)
                continue
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if header_raw is None:
            normed = [norm_header(c) for c in cells]
            if not any(HEADER_MAP.get(c) == "option_code" for c in normed):
                continue
            header_raw = cells
            for i, c in enumerate(normed):
                if not c:
                    continue
                name = HEADER_MAP.get(c)
                if name is None:
                    raise ParseError(f"unknown header column {cells[i]!r}")
                if name in idx:
                    raise ParseError(f"duplicate header column {cells[i]!r}")
                idx[name] = i
            missing = REQUIRED_FIELDS - set(idx)
            if missing:
                raise ParseError(f"header lacks {sorted(missing)}: {cells}")
            for k in ["trade_date", "option_code", "product", "ym", "is_serial", "cp", "strike"]:
                cols[k] = []
            for k in NUMERIC_FIELDS:
                cols[k] = []
            continue
        code_cell = cells[idx["option_code"]] if idx["option_code"] < len(cells) else ""
        code = re.sub(r"\s+", "", code_cell)
        if not code:
            continue
        if any(w in code for w in _TOTAL_WORDS):
            n_agg += 1
            m = _PRODUCT_TOTAL_RE.match(code)
            if m:
                sym = m.group(1).upper()
                sym = _SYMBOL_ALIAS.get(sym, sym)
                totals[sym] = (_num(cells[idx["volume"]]), _num(cells[idx["oi"]]))
            continue
        m = OPT_RE.match(code)
        if not m:
            raise ParseError(f"unrecognised option code {code_cell!r}")
        need = max(idx.values()) + 1
        if len(cells) < need:
            raise ParseError(f"row {code!r} has {len(cells)} cells, header needs {need}")
        cols["trade_date"].append(cells[idx["trade_date"]] if "trade_date" in idx else "")
        cols["option_code"].append(code_cell.strip())
        cols["product"].append(m.group(1))
        cols["ym"].append(m.group(2))
        cols["is_serial"].append(m.group(3) is not None)
        cols["cp"].append(m.group(4))
        cols["strike"].append(float(m.group(5)))
        for k in NUMERIC_FIELDS:
            cols[k].append(_num(cells[idx[k]]) if k in idx else float("nan"))
    if header_raw is None:
        raise ParseError("no table header found")
    rows = pd.DataFrame(cols)
    for k in NUMERIC_FIELDS:
        rows[k] = rows[k].astype(float)
    rows["strike"] = rows["strike"].astype(float)
    rows["is_serial"] = rows["is_serial"].astype(bool)
    header_map = {c: HEADER_MAP[norm_header(c)] for c in header_raw if norm_header(c)}
    return ParsedTable(rows, header_raw, header_map, title, n_agg, totals)


def is_no_data(text: str) -> bool:
    """期权上市前的占位文件:200 + 标题 + 表头 + '无交易记录!',没有数据行(照样落盘,build 时为 0 行)。"""
    return NO_DATA_MARK in text


def _month_index(contract: str) -> int:
    digits = contract[-4:]
    return (2000 + int(digits[:2])) * 12 + int(digits[2:])


def standardize(
    rows: pd.DataFrame,
    dates: pd.Series[Any] | pd.Timestamp,
    source_file: str = "",
    last_modified_utc: str = "",
    update_date: str = "",
) -> pd.DataFrame:
    """ParsedTable.rows → 输出列(available_day 先置 NaT,由 build 统一按日历填)。
    dates:每日文件传该文件日期;年度文件传逐行日期序列。"""
    n = len(rows)
    date_s: pd.Series[Any]
    if isinstance(dates, pd.Timestamp):
        date_s = pd.Series(pd.DatetimeIndex([pd.Timestamp(dates).normalize()] * n), index=rows.index)
    else:
        date_s = pd.Series(pd.to_datetime(dates).dt.normalize().to_numpy(), index=rows.index)
    out = pd.DataFrame(index=rows.index)
    out["date"] = date_s.astype("datetime64[ns]")
    out["exchange"] = EXCHANGE
    out["product"] = rows["product"].astype(str)
    # 标的:3 位年月按文件日期补十年位(同 (代码, 日期) 只算一次)
    key = rows["product"].astype(str) + rows["ym"].astype(str)
    pairs = pd.DataFrame({"k": key, "d": out["date"]}).drop_duplicates()
    und_map = {
        (k, d): normalize_contract(k, EXCHANGE, pd.Timestamp(d)) for k, d in zip(pairs["k"], pairs["d"])
    }
    out["underlying"] = [und_map[(k, d)] for k, d in zip(key, out["date"])]
    if n:
        ahead = np.array([_month_index(u) for u in out["underlying"]]) - (
            out["date"].dt.year.to_numpy() * 12 + out["date"].dt.month.to_numpy()
        )
        if (ahead < 0).any() or (ahead > 48).any():
            bad = out.loc[(ahead < 0) | (ahead > 48), "underlying"].head().tolist()
            raise ParseError(f"underlying month outside [T, T+48m]: {bad}")
    out["option_code"] = rows["option_code"].astype(str)
    out["cp"] = rows["cp"].astype(str)
    out["strike"] = rows["strike"].astype(float)
    out["settle"] = rows["settle"].astype(float)
    out["close"] = rows["close"].astype(float)
    factor = np.where(out["date"] < SINGLE_SIDED_FROM, 0.5, 1.0)
    out["volume_raw"] = rows["volume"].astype(float)
    out["oi_raw"] = rows["oi"].astype(float)
    out["turnover_raw"] = rows["turnover"].astype(float) * TURNOVER_UNIT
    out["volume"] = out["volume_raw"] * factor
    out["oi"] = out["oi_raw"] * factor
    out["turnover"] = out["turnover_raw"] * factor
    out["delta"] = rows["delta"].astype(float)
    iv = rows["iv"].astype(float) / 100.0
    out["iv_exchange"] = iv.where(iv > 0)
    out["is_serial"] = rows["is_serial"].astype(bool)
    # 系列合计:同一 (date, underlying) 的常规(非序列)期权单边成交量/持仓量之和,广播到该标的全部行
    reg = out[~out["is_serial"]]
    sums = reg.groupby(["date", "underlying"], sort=False)[["volume", "oi"]].sum()
    mi = pd.MultiIndex.from_arrays([out["date"], out["underlying"]])
    out["series_volume"] = sums["volume"].reindex(mi).to_numpy(dtype=float)
    out["series_oi"] = sums["oi"].reindex(mi).to_numpy(dtype=float)
    out["expire_date"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    out["available_day"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    out["source_file"] = source_file
    out["last_modified_utc"] = last_modified_utc
    out["update_date"] = update_date
    return out[OUT_COLUMNS].reset_index(drop=True)


def check_product_totals(rows: pd.DataFrame, totals: dict[str, tuple[float, float]]) -> list[str]:
    """XX合计 行的成交量/持仓量 vs 逐合约加总(原始口径);返回不一致的品种。"""
    bad: list[str] = []
    if not totals:
        return bad
    g = rows.groupby("product")[["volume", "oi"]].sum()
    for sym, (vol, oi) in totals.items():
        if sym not in g.index:
            if (vol or 0) != 0 or (oi or 0) != 0:
                bad.append(sym)
            continue
        sv, so = float(g.at[sym, "volume"]), float(g.at[sym, "oi"])
        if not (np.isclose(sv, vol) and np.isclose(so, oi)):
            bad.append(sym)
    return bad


@dataclass
class DayFile:
    date: pd.Timestamp
    table: pd.DataFrame
    info: dict[str, Any]


def parse_daily_bytes(
    raw: bytes, d: pd.Timestamp, source_file: str = "", last_modified_utc: str = ""
) -> DayFile:
    """一份 OptionDataDaily.txt(原始字节)→ 标准行 + 文件级信息。标题日期与文件日期不一致抛 ParseError。"""
    d = pd.Timestamp(d).normalize()
    enc = detect_encoding(raw)
    text = decode_text(raw)
    info: dict[str, Any] = {"encoding": enc}
    if is_no_data(text) and not any(OPT_RE.match(ln.split("|")[0].strip()) for ln in text.splitlines()):
        m = _TITLE_RE.search(text)
        info.update(title_date=m.group(1) if m else "", n_option_rows=0, note="no data (无交易记录)")
        return DayFile(d, pd.DataFrame(columns=OUT_COLUMNS), info)
    pt = parse_table(text)
    if pt.title_date and pt.title_date != d.strftime("%Y-%m-%d"):
        raise ParseError(f"{_ymd(d)}: title date {pt.title_date} differs from file date")
    if pt.rows["option_code"].duplicated().any():
        dups = pt.rows.loc[pt.rows["option_code"].duplicated(), "option_code"].head().tolist()
        raise ParseError(f"{_ymd(d)}: duplicated option codes {dups}")
    table = standardize(pt.rows, d, source_file, last_modified_utc, "")
    bad_totals = check_product_totals(pt.rows, pt.product_totals)
    info.update(
        title_date=pt.title_date,
        header="|".join(pt.header_raw).strip("|"),
        header_fields="|".join(pt.header_map[c] for c in pt.header_raw if norm_header(c)),
        n_option_rows=len(table),
        n_serial_rows=int(table["is_serial"].sum()),
        n_aggregate_rows=pt.n_aggregate,
        products=" ".join(sorted(table["product"].unique())),
        total_check_mismatch=" ".join(bad_totals),
        n_close_zero_traded=int(((table["volume_raw"] > 0) & ~(table["close"] > 0)).sum()),
        n_iv_nonpositive=int(table["iv_exchange"].isna().sum()),
        n_odd_double_sided=(
            int(((table["volume_raw"] % 2 != 0) | (table["oi_raw"] % 2 != 0)).sum())
            if is_double_sided(d)
            else 0
        ),
    )
    return DayFile(d, table, info)


# ---------------------------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------------------------


def _valid_daily(r: Response) -> bool:
    if r.status != 200:
        return False
    text = decode_text(r.body)
    return "期权每日行情表" in text or NO_DATA_MARK in text


def candidate_dates(start: pd.Timestamp, end: pd.Timestamp, calendar: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """工作日 ∪ 项目期货日历中的日期(休市工作日也探测一次,404 记录在案)。"""
    days = set(pd.bdate_range(start, end))
    days.update(x for x in calendar if start <= x <= end)
    return sorted(pd.Timestamp(x) for x in days)


def fetch_day(client: Client, dest: Path, d: pd.Timestamp, nf: dict[str, dict[str, str]]) -> str:
    """下载一天;返回 'ok' / '404' / 'empty'。"""
    d = pd.Timestamp(d).normalize()
    path = DAILY_PATH.format(y=d.year, ymd=_ymd(d))
    r = client.get(path, _valid_daily)
    lm_http = r.headers.get("last-modified")
    lm = _last_modified_iso(lm_http)
    if r.status == 404:
        _record_not_found(dest, d, 404, "not found (holiday / no file)", lm, nf)
        return "404"
    text = decode_text(r.body)
    m = _TITLE_RE.search(text)
    title = m.group(1) if m else ""
    if title and title != d.strftime("%Y-%m-%d"):
        raise FetchError(f"{_ymd(d)}: title date {title} differs from requested date")
    gz = gzip.compress(r.body, compresslevel=9, mtime=0)
    f, mpath = raw_file(dest, d), meta_file(dest, d)
    _atomic_write(f, gz)
    meta: dict[str, Any] = {
        "url": daily_url(d),
        "date": d.strftime("%Y-%m-%d"),
        "http_status": r.status,
        "content_type": r.headers.get("content-type", ""),
        "content_encoding": r.headers.get("content-encoding", ""),
        "etag": r.headers.get("etag", ""),
        "size": len(r.body),
        "stored_size": len(gz),
        "sha256": hashlib.sha256(r.body).hexdigest(),
        "fetched_at_utc": _utc_now_iso(),
        "last_modified_http": lm_http or "",
        "last_modified_utc": lm,
        "encoding": detect_encoding(r.body),
        "title_date": title,
        "update_date": "",  # 郑商所文件无生成/打印时间戳
    }
    _atomic_write(mpath, json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    return "empty" if is_no_data(text) else "ok"


def fetch(dest: Path, start: str = FIRST_DAY, end: str = LAST_DAY) -> None:
    """抓取 [start, end] 每个工作日(∪ 项目日历)的 OptionDataDaily.txt 到 dest/raw;幂等、可续传。
    已在本地(大小与 meta 一致)或已确认 404/无数据的日期不再请求;单日失败记日志,全部跑完后统一抛错。"""
    s, e = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    raw_dir(dest).mkdir(parents=True, exist_ok=True)
    nf = load_not_found(dest)
    dates = candidate_dates(s, e, futures_calendar())
    todo = [
        d
        for d in dates
        if not file_present(dest, d)
        and not (
            (rec := nf.get(d.strftime("%Y-%m-%d"))) is not None
            and _not_found_is_final(d, rec["probed_at_utc"])
        )
    ]
    log.info("fetch %s → %s: %d candidate dates, %d to request", s.date(), e.date(), len(dates), len(todo))
    client = Client()
    failures: list[str] = []
    counts = {"ok": 0, "404": 0, "empty": 0}
    t0 = time.monotonic()
    try:
        for i, d in enumerate(todo, 1):
            try:
                counts[fetch_day(client, dest, d, nf)] += 1
            except FetchError as ex:
                failures.append(f"{d.date()}: {ex}")
                log.error("failed %s: %s", d.date(), ex)
            if i % 100 == 0 or i == len(todo):
                log.info(
                    "%d/%d done (%s) ok=%d 404=%d empty=%d fail=%d, %.1f MB on wire, %.0fs",
                    i,
                    len(todo),
                    d.date(),
                    counts["ok"],
                    counts["404"],
                    counts["empty"],
                    len(failures),
                    client.bytes_on_wire / 1e6,
                    time.monotonic() - t0,
                )
    finally:
        client.close()
    if failures:
        raise FetchError(f"{len(failures)} dates failed (re-run to resume): {failures[:5]}")


# ---------------------------------------------------------------------------------------------
# 构建标准表
# ---------------------------------------------------------------------------------------------


def iter_raw_dates(dest: Path) -> list[pd.Timestamp]:
    out = []
    for p in raw_dir(dest).glob("[0-9][0-9][0-9][0-9]/*_OptionDataDaily.txt.gz"):
        out.append(pd.Timestamp(datetime.strptime(p.name[:8], "%Y%m%d")))
    return sorted(out)


def load_day(dest: Path, d: pd.Timestamp) -> DayFile:
    f, m = raw_file(dest, d), meta_file(dest, d)
    meta = _read_json(m)
    with gzip.open(f, "rb") as fh:
        raw = fh.read()
    if meta.get("sha256") and hashlib.sha256(raw).hexdigest() != meta["sha256"]:
        raise ParseError(f"{f}: sha256 mismatch with meta")
    rel = f.relative_to(dest).as_posix()
    day = parse_daily_bytes(raw, d, rel, str(meta.get("last_modified_utc") or ""))
    day.info.update(
        url=str(meta.get("url") or daily_url(d)),
        http_status=meta.get("http_status", ""),
        raw_file=rel,
        size=meta.get("size", ""),
        sha256=meta.get("sha256", ""),
        fetched_at_utc=meta.get("fetched_at_utc", ""),
        last_modified_utc=meta.get("last_modified_utc", ""),
    )
    return day


FILES_FIELDS = [
    "date",
    "status",
    "http_status",
    "url",
    "raw_file",
    "size",
    "sha256",
    "fetched_at_utc",
    "last_modified_utc",
    "encoding",
    "title_date",
    "header",
    "header_fields",
    "n_option_rows",
    "n_serial_rows",
    "n_aggregate_rows",
    "products",
    "total_check_mismatch",
    "n_close_zero_traded",
    "n_iv_nonpositive",
    "n_odd_double_sided",
    "note",
]


def build(dest: Path, quotes_root: Path = QUOTES_ROOT, holidays_path: Path = HOLIDAYS_CSV) -> pd.DataFrame:
    """dest/raw → options_daily.parquet + files.csv + build_report.json;返回标准表。"""
    frames: list[pd.DataFrame] = []
    file_rows: list[dict[str, Any]] = []
    for d in iter_raw_dates(dest):
        day = load_day(dest, d)
        info = dict(day.info)
        info["date"] = d.strftime("%Y-%m-%d")
        info["status"] = "ok" if len(day.table) else "empty"
        file_rows.append(info)
        if len(day.table):
            frames.append(day.table)
    for ds, rec in load_not_found(dest).items():
        file_rows.append(
            {
                "date": ds,
                "status": "404" if rec["http_status"] == "404" else "empty",
                "http_status": rec["http_status"],
                "url": rec["url"],
                "last_modified_utc": rec.get("last_modified_utc", ""),
                "fetched_at_utc": rec["probed_at_utc"],
                "note": rec["note"],
            }
        )
    if not frames:
        raise ParseError(f"no option rows under {raw_dir(dest)}")
    df = pd.concat(frames, ignore_index=True)
    opt_dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    cal = pd.DatetimeIndex(futures_calendar(quotes_root).union(opt_dates))
    amap = available_day_map(opt_dates, cal, load_holidays(holidays_path))
    df["available_day"] = df["date"].map(amap).astype("datetime64[ns]")
    df = df.sort_values(["date", "option_code"], kind="mergesort").reset_index(drop=True)
    dup = df.duplicated(["date", "option_code"])
    if bool(dup.any()):
        raise ParseError(
            f"duplicate (date, option_code): {df.loc[dup, ['date', 'option_code']].head().values}"
        )
    if not bool((df["available_day"] > df["date"]).all()):
        raise ParseError("available_day must be strictly after date")
    dest.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest / "options_daily.parquet", index=False)
    files = pd.DataFrame(file_rows)
    for c in FILES_FIELDS:
        if c not in files.columns:
            files[c] = ""
    files = files[FILES_FIELDS].sort_values("date", kind="mergesort").reset_index(drop=True)
    files.to_csv(dest / "files.csv", index=False, lineterminator="\n")
    report = build_report(df, files, futures_calendar(quotes_root), amap)
    (dest / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return df


def coverage(df: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, dict[str, Any]]:
    """预注册郑商所品种:首日、行数、日期数、首日之后在郑商所期货日历中缺失的交易日。"""
    out: dict[str, dict[str, Any]] = {}
    last = pd.Timestamp(df["date"].max())
    for sym in PREREG_PRODUCTS:
        g = df[df["product"] == sym]
        if g.empty:
            out[sym] = {"rows": 0, "note": "not a CZCE option product" if sym not in LISTING else "missing"}
            continue
        days = pd.DatetimeIndex(sorted(g["date"].unique()))
        first = pd.Timestamp(days[0])
        expected = calendar[(calendar >= first) & (calendar <= last)]
        missing = expected.difference(days)
        out[sym] = {
            "listing_prereg": LISTING.get(sym, ""),
            "first_date": first.strftime("%Y-%m-%d"),
            "last_date": pd.Timestamp(days[-1]).strftime("%Y-%m-%d"),
            "n_dates": len(days),
            "rows": len(g),
            "serial_rows": int(g["is_serial"].sum()),
            "first_serial_date": (
                pd.Timestamp(g.loc[g["is_serial"], "date"].min()).strftime("%Y-%m-%d")
                if bool(g["is_serial"].any())
                else ""
            ),
            "missing_trading_days": [x.strftime("%Y-%m-%d") for x in missing],
        }
    return out


def build_report(
    df: pd.DataFrame,
    files: pd.DataFrame,
    fut_cal: pd.DatetimeIndex,
    amap: dict[pd.Timestamp, pd.Timestamp],
) -> dict[str, Any]:
    ok = files[files["status"] == "ok"]
    czce_cal = fut_cal
    with contextlib.suppress(Exception):
        czce_q = pd.read_parquet(QUOTES_ROOT / "CZCE" / "quotes_all.parquet", columns=["date"])
        czce_cal = pd.DatetimeIndex(sorted(pd.to_datetime(czce_q["date"]).dt.normalize().unique()))
    opt_days = pd.DatetimeIndex(sorted(df["date"].unique()))
    rng = czce_cal[(czce_cal >= opt_days[0]) & (czce_cal <= opt_days[-1])]
    header_variants: list[dict[str, Any]] = []
    for h, g in ok.groupby("header", sort=False):
        header_variants.append(
            {
                "header": h,
                "fields": str(g["header_fields"].iloc[0]),
                "first": str(g["date"].min()),
                "last": str(g["date"].max()),
                "n_files": len(g),
            }
        )
    beyond = {
        k.strftime("%Y-%m-%d"): v.strftime("%Y-%m-%d")
        for k, v in amap.items()
        if len(fut_cal) == 0 or k >= fut_cal.max()
    }
    per_product = (
        df.groupby("product")
        .agg(first=("date", "min"), last=("date", "max"), rows=("option_code", "size"))
        .reset_index()
    )
    return {
        "rows": len(df),
        "date_min": pd.Timestamp(df["date"].min()).strftime("%Y-%m-%d"),
        "date_max": pd.Timestamp(df["date"].max()).strftime("%Y-%m-%d"),
        "n_option_files": len(ok),
        "n_404": int((files["status"] == "404").sum()),
        "n_empty": int((files["status"] == "empty").sum()),
        "raw_bytes_uncompressed": int(pd.to_numeric(ok["size"], errors="coerce").sum()),
        "encodings": {str(k): int(v) for k, v in ok["encoding"].value_counts().items()},
        "header_variants": header_variants,
        "czce_futures_days_without_option_file": [x.strftime("%Y-%m-%d") for x in rng.difference(opt_days)],
        "option_days_not_in_futures_calendar": [x.strftime("%Y-%m-%d") for x in opt_days.difference(fut_cal)],
        "available_day_beyond_calendar": beyond,
        "coverage_prereg": coverage(df, czce_cal),
        "all_products": {
            str(r["product"]): {
                "first": pd.Timestamp(r["first"]).strftime("%Y-%m-%d"),
                "last": pd.Timestamp(r["last"]).strftime("%Y-%m-%d"),
                "rows": int(r["rows"]),
            }
            for _, r in per_product.iterrows()
        },
        "serial_rows": int(df["is_serial"].sum()),
        "serial_volume_total": float(df.loc[df["is_serial"], "volume"].sum()),
        "files_with_total_mismatch": ok.loc[ok["total_check_mismatch"].astype(str) != "", "date"].tolist(),
        "traded_rows_with_zero_close": int(pd.to_numeric(ok["n_close_zero_traded"]).sum()),
        "rows_iv_nonpositive_or_blank": int(df["iv_exchange"].isna().sum()),
        "rows_delta_blank": int(df["delta"].isna().sum()),
        "odd_raw_counts_pre2020": int(pd.to_numeric(ok["n_odd_double_sided"]).sum()),
        "untraded_rows": int((df["volume"] == 0).sum()),
        "untraded_close_values": {
            str(k): int(v) for k, v in df.loc[df["volume"] == 0, "close"].value_counts().head(3).items()
        },
    }


# ---------------------------------------------------------------------------------------------
# 年度文件抽样交叉核对(只核对,不作数据源)
# ---------------------------------------------------------------------------------------------

CROSSCHECK_SAMPLES: tuple[tuple[str, int], ...] = (
    ("SR", 2020),
    ("CF", 2021),
    ("MA", 2022),
    ("TA", 2024),
    ("SA", 2025),
)
CHUNK_BYTES = 1_000_000
COMPARE_FIELDS: dict[str, float] = {
    "settle": 1e-9,
    "close": 1e-9,
    "volume_raw": 1e-9,
    "oi_raw": 1e-9,
    "turnover_raw": 100.0 + 1e-6,  # 年度与每日文件成交额偶差 0.01 万元(舍入),见侦察核验
    "delta": 1e-9,
    "iv_exchange": 1e-9,
}


def _chunk_paths(dest: Path, sym: str, year: int, a: int, b: int) -> tuple[Path, Path]:
    base = raw_dir(dest) / "annual_crosscheck" / f"{sym}OPTIONS{year}.bytes{a}-{b}"
    return base.with_name(base.name + ".txt.gz"), base.with_name(base.name + ".meta.json")


def _get_chunk(client: Client, dest: Path, sym: str, year: int, a: int, b: int) -> tuple[bytes, int]:
    """年度文件 [a, b] 字节段(本地有则复用);返回 (字节, 文件总长)。"""
    f, m = _chunk_paths(dest, sym, year, a, b)
    if f.exists() and m.exists():
        meta = _read_json(m)
        with gzip.open(f, "rb") as fh:
            return fh.read(), int(meta["total_size"])
    path = ANNUAL_PATH.format(y=year, sym=sym)
    r = client.get(path, lambda r: r.status == 206, {"Range": f"bytes={a}-{b}"})
    if r.status != 206:
        raise FetchError(f"{path}: HTTP {r.status} for range request")
    cr = r.headers.get("content-range", "")
    total = int(cr.rsplit("/", 1)[-1]) if "/" in cr else -1
    _atomic_write(f, gzip.compress(r.body, mtime=0))
    meta = {
        "url": annual_url(sym, year),
        "range": f"bytes={a}-{b}",
        "http_status": r.status,
        "content_range": cr,
        "total_size": total,
        "size": len(r.body),
        "fetched_at_utc": _utc_now_iso(),
        "last_modified_http": r.headers.get("last-modified", ""),
        "last_modified_utc": _last_modified_iso(r.headers.get("last-modified")),
    }
    _atomic_write(m, json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    return r.body, total


def _chunk_rows(blob: bytes, header_line: str | None) -> tuple[pd.DataFrame, str]:
    """片段 → 标准行(只保留完整的日期:去掉片段首尾可能截断的日期)。返回 (行, 表头行)。"""
    start = 0
    if header_line is not None:  # 中段:丢掉第一行残片
        start = blob.index(b"\n") + 1
    end = blob.rindex(b"\n")
    text = decode_text(blob[start:end])
    if header_line is None:  # 开头:标题行"郑州商品交易所期权历史行情下载(2020SR)"之后才是表头
        header_line = next(
            ln
            for ln in text.splitlines()
            if "|" in ln and any(HEADER_MAP.get(norm_header(c)) == "option_code" for c in ln.split("|"))
        )
    else:
        text = header_line + "\n" + text
    pt = parse_table(text)
    rows = pt.rows
    dates = pd.to_datetime(rows["trade_date"])
    keep = dates < dates.max()
    if start > 0:
        keep &= dates > dates.min()
    rows = rows[keep.to_numpy()].reset_index(drop=True)
    std = standardize(rows, dates[keep.to_numpy()].reset_index(drop=True))
    return std, header_line


def crosscheck(dest: Path, table: pd.DataFrame | None = None) -> pd.DataFrame:
    """抽样:每个 (品种, 年) 取年度文件开头与中间各 ~1 MB,与每日文件建出的行逐字段比较。"""
    if table is None:
        table = pd.read_parquet(dest / "options_daily.parquet")
    client = Client()
    results: list[dict[str, Any]] = []
    try:
        for sym, year in CROSSCHECK_SAMPLES:
            head, total = _get_chunk(client, dest, sym, year, 0, CHUNK_BYTES - 1)
            a_rows, header = _chunk_rows(head, None)
            mid = max(total // 2, CHUNK_BYTES)
            body, _ = _get_chunk(client, dest, sym, year, mid, mid + CHUNK_BYTES - 1)
            b_rows, _ = _chunk_rows(body, header)
            ann = pd.concat([a_rows, b_rows], ignore_index=True)
            days = sorted(ann["date"].unique())
            daily = table[(table["product"] == sym) & table["date"].isin(days)]
            mg = ann.merge(
                daily, on=["date", "option_code"], how="outer", suffixes=("_a", "_d"), indicator=True
            )
            both = mg[mg["_merge"] == "both"]
            rec: dict[str, Any] = {
                "product": sym,
                "year": year,
                "dates": len(days),
                "first": pd.Timestamp(days[0]).strftime("%Y-%m-%d"),
                "last": pd.Timestamp(days[-1]).strftime("%Y-%m-%d"),
                "rows_compared": len(both),
                "only_annual": int((mg["_merge"] == "left_only").sum()),
                "only_daily": int((mg["_merge"] == "right_only").sum()),
            }
            for c, tol in COMPARE_FIELDS.items():
                x, y = both[c + "_a"].to_numpy(dtype=float), both[c + "_d"].to_numpy(dtype=float)
                same = (np.abs(x - y) <= tol) | (np.isnan(x) & np.isnan(y))
                rec[f"mismatch_{c}"] = int((~same).sum())
            exact_turn = np.abs(
                both["turnover_raw_a"].to_numpy(float) - both["turnover_raw_d"].to_numpy(float)
            )
            rec["turnover_rounding_diffs"] = int((exact_turn > 1e-6).sum())
            results.append(rec)
            log.info("crosscheck %s", rec)
    finally:
        client.close()
    res = pd.DataFrame(results)
    res.to_csv(dest / "crosscheck_annual.csv", index=False, lineterminator="\n")
    return res


# ---------------------------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------------------------


def summary(df: pd.DataFrame, dest: Path) -> str:
    rep = _read_json(dest / "build_report.json")
    lines = [
        f"options_daily: {len(df)} rows, {df['date'].nunique()} dates "
        f"{pd.Timestamp(df['date'].min()).date()} → {pd.Timestamp(df['date'].max()).date()}",
        f"files: {rep.get('n_option_files')} ok, {rep.get('n_404')} 404, {rep.get('n_empty')} empty",
    ]
    for sym, c in (rep.get("coverage_prereg") or {}).items():
        if c.get("rows"):
            lines.append(
                f"  {sym}: first {c['first_date']} (prereg {c['listing_prereg']}), {c['rows']} rows, "
                f"{c['n_dates']} dates, serial {c['serial_rows']}, missing days {len(c['missing_trading_days'])}"
            )
    lines.append("header variants:")
    for h in rep.get("header_variants") or []:
        lines.append(f"  {h['first']} → {h['last']} ({h['n_files']} files): {h['header']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="CZCE daily option quotes → options_daily.parquet")
    ap.add_argument("--dest", type=Path, required=True, help="data/external/alt/czce_options")
    ap.add_argument("--start", default=FIRST_DAY)
    ap.add_argument("--end", default=LAST_DAY)
    ap.add_argument("--no-fetch", action="store_true", help="only rebuild from raw/")
    ap.add_argument("--no-crosscheck", action="store_true", help="skip the annual-file sample cross-check")
    args = ap.parse_args(None if argv is None else list(argv))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dest: Path = args.dest
    if not args.no_fetch:
        fetch(dest, args.start, args.end)
    df = build(dest)
    print(summary(df, dest))
    if not args.no_crosscheck:
        print(crosscheck(dest, df).to_string(index=False))


if __name__ == "__main__":
    main()
