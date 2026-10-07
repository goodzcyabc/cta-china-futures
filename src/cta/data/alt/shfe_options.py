"""上期所 + 能源中心(SHFE/INE)商品期权日行情 → options_daily.parquet(预注册 docs/research/options_prereg.md 第 2–3 节)。

来源(官方、免登录、纯 GET):
- 期权日交易快讯 ``https://www.shfe.com.cn/data/tradedata/option/dailydata/kx{YYYYMMDD}.dat``(JSON,含能源中心期权;
  404 = 休市日;首日 2018-09-21)。``o_curinstrument`` 一行一个期权(PRODUCTID ``cu_o``、INSTRUMENTID ``cu2611C90000``、
  UNDERLYINGINSTRID ``cu2611``、OPTIONSTYPE ``1``=看涨 ``2``=看跌、STRIKEPRICE、SETTLEMENTPRICE、CLOSEPRICE、VOLUME、
  OPENINTEREST、TURNOVER(万元)、DELTA);``o_cursigma`` 一行一个标的月份(系列):SIGMA(交易所隐含波动率,小数)、
  系列 VOLUME、OPENINTEREST。两表都有 ``小计``/``总计`` 汇总行,此处丢弃。
- 期权合约基础信息 ``https://www.shfe.com.cn/data/busiparamdata/option/ContractBaseInfo{YYYYMMDD}.dat``
  (键 OptionContractBaseInfo:INSTRUMENTID、EXPIREDATE、TRADEUNIT …),每个 kx 存在的交易日都抓一份(简单、可交叉核对)。

已处理的口径/格式问题:
- 2024-03-20 前的字符串右侧补空格(strip);数值字段时而为数字时而为字符串(空串 → NaN)。
- 2020-01-01 前成交量/持仓量/成交额为双边计数(样例中 2019 年全部 VOLUME/OPENINTEREST 为偶数):
  volume/oi/turnover 与 series_volume/series_oi 按单边折半,原值存 *_raw(turnover_raw 已换算成元、未折半)。
- TURNOVER 单位万元 → ×1e4 为元。
- iv_exchange = 该期权标的系列的 SIGMA(``o_cursigma``),空白或 ≤ 0 → NaN;零成交系列的 SIGMA 是交易所借用的相邻月份值,
  下游用 series_volume == 0 识别。
- 未成交期权的 CLOSEPRICE 等于结算价(交易所原样);本表照原样保留,下游以 volume == 0 剔除。
- exchange:品种属于 INE_SYMBOLS(SC/LU/NR/BC/EC)记 'INE',否则 'SHFE'(ContractBaseInfo 的 EXCHANGEID 一律写 SHFE,不可用)。
- underlying 用 ``normalize_contract`` 规范成项目期货口径(cu2611 → CU2611);product = 其大写品种代码。
- expire_date 取同一期权代码在 日期 ≤ T 的最新合约基础信息中的 EXPIREDATE(时点值:交易所会因假期安排改已上市系列的
  到期日,2018–2026 共 35 次系列修订,故不能用后来的文件回填);≤ T 的文件里没有该代码时依次回退到同系列 ≤ T 的值、
  之后文件的值(后两者属前视,只作缺数兜底,build 报告计数;全量历史中从未触发)。
- 有少量 VOLUME > 0 的期权行没有开/高/低价,CLOSEPRICE = SETTLEMENTPRICE,且 TURNOVER 折算的成交均价恰等于结算价
  (成交全部按结算价发生,非竞价成交);另有部分行成交均价落在 [最低价, 最高价] 之外但总在 [min(最低价, 结算价),
  max(最高价, 结算价)] 之内(部分成交按结算价)。本表照原样保留,build 报告计数(traded_no_ohlc)。

可得规则(预注册第 3 节,写死):available_day = 日 T 之后(严格)第一个项目交易日;交易日历 = 项目期货行情
``data/exchanges/*/quotes_all.parquet`` 日期并集 ∪ 本期权文件日期;超出日历末端的日期用 工作日 − configs/holidays.csv 推算。
不用 Last-Modified/update_date 推可得日(2024-03-20 前的文件在网站迁移时整体重发,2018-09→2020-06 的文件在 2020-06-17 重生成),
但每个原始文件的 HTTP 状态、Last-Modified(UTC)、抓取时刻、文件内 update_date/print_date 都写进同名 .meta.json 与 files.csv。

落盘:dest/raw/kx/{YYYY}/kx{YYYYMMDD}.dat.gz、dest/raw/baseinfo/{YYYY}/ContractBaseInfo{YYYYMMDD}.dat.gz(各带 .meta.json),
404 记 dest/raw/not_found.csv;输出 dest/options_daily.parquet 与 dest/files.csv。

命令行:``PYTHONPATH=src python3 -m cta.data.alt.shfe_options --dest data/external/alt/shfe_options``
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import http.client
import json
import logging
import os
import re
import time
import urllib.parse
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from cta.data.exchanges.base import DEFAULT_ROOT, normalize_contract, symbol_of
from cta.data.exchanges.calendar import load_holidays
from cta.data.exchanges.shfe import INE_SYMBOLS, SINGLE_SIDED_FROM, USER_AGENT

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------------------------

BASE_URL = "https://www.shfe.com.cn"
KX_URL = BASE_URL + "/data/tradedata/option/dailydata/kx{d}.dat"
BASEINFO_URL = BASE_URL + "/data/busiparamdata/option/ContractBaseInfo{d}.dat"
KINDS = ("kx", "baseinfo")

FIRST_DAY = "2018-09-21"  # 上期所第一个期权交易日(铜期权)
DEFAULT_END = "2026-09-30"
NOT_FOUND_STABLE_DAYS = 7  # 日期 7 天后仍 404 → 视为休市,不再重探
TURNOVER_UNIT = 10_000.0  # 文件成交额单位万元

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
MIN_INTERVAL = 1.0  # 秒;两次请求开始时刻的最小间隔(≤ 1 次/秒)
RETRIES = 4
TIMEOUT = 60
BEIJING = timezone(timedelta(hours=8))

# 预注册第 3 节的上期所/能源中心品种与期权上市日(用于覆盖率报告与真实数据测试)。
PREREG_LISTING: dict[str, str] = {
    "CU": "2018-09-21",
    "RU": "2019-01-28",
    "AU": "2019-12-20",
    "AL": "2020-08-10",
    "SC": "2021-06-21",
    "AG": "2022-12-26",
    "RB": "2022-12-26",
    "NI": "2024-09-02",
    "SN": "2024-09-02",
}

OUTPUT_COLUMNS: list[str] = [
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
    "volume_raw",
    "oi",
    "oi_raw",
    "turnover",
    "turnover_raw",
    "delta",
    "iv_exchange",
    "series_volume",
    "series_oi",
    "expire_date",
    "available_day",
    "source_file",
    "last_modified_utc",
    "update_date",
    "has_ohlc",
]
FILES_COLUMNS: list[str] = [
    "kind",
    "date",
    "path",
    "url",
    "http_status",
    "size",
    "gz_size",
    "sha256",
    "fetched_at_utc",
    "last_modified_utc",
    "report_date",
    "update_date",
    "print_date",
    "n_rows",
]

_OPTION_RE = re.compile(r"^([A-Za-z]{1,2}\d{3,4})-?([CP])-?(\d+(?:\.\d+)?)$")
_TOTAL_WORDS = ("小计", "总计", "合计")


class FetchError(RuntimeError):
    """重试耗尽后的下载失败(非 404)。"""


class ParseError(ValueError):
    """原始文件内容与预期格式不符。"""


# ---------------------------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------------------------


def _num(v: Any) -> float:
    """数值单元格:int/float 原样;字符串去空白与逗号;空串、'-' → NaN。"""
    if v is None or isinstance(v, bool):
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--"):
        return float("nan")
    try:
        return float(s)
    except ValueError as e:
        raise ParseError(f"non-numeric cell {v!r}") from e


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


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


def _load_json(raw: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ParseError(f"not JSON ({e})") from e
    if not isinstance(doc, dict):
        raise ParseError("JSON root is not an object")
    return cast(dict[str, Any], doc)


def _is_total(*cells: Any) -> bool:
    return any(any(w in _text(c) for w in _TOTAL_WORDS) for c in cells)


def parse_option_code(code: str) -> tuple[str, str, float]:
    """'cu2611C90000' → ('cu2611', 'C', 90000.0);也接受 'SR001C5000'、'm2101-C-2800'。"""
    m = _OPTION_RE.match(code.strip())
    if m is None:
        raise ParseError(f"unrecognised option code {code!r}")
    return m.group(1), m.group(2), float(m.group(3))


def normalize_underlying(code: str, file_date: date | pd.Timestamp) -> str:
    """期权标的期货代码 → 项目期货口径(CU2611);郑商所 3 位年月用文件日期补十年位。"""
    sym = re.sub(r"\d.*$", "", code.strip()).upper()
    ex = "INE" if sym in INE_SYMBOLS else "SHFE"
    return normalize_contract(code, ex, pd.Timestamp(file_date))


def exchange_of(product: str) -> str:
    return "INE" if product.upper() in INE_SYMBOLS else "SHFE"


def is_double_sided(d: date | pd.Timestamp) -> bool:
    """2020-01-01 前成交量/持仓量/成交额为双边计数。"""
    return pd.Timestamp(d) < SINGLE_SIDED_FROM


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


@dataclass
class KxFile:
    """一个 kx 文件解析结果:期权行(已折单边)+ 文件内时间戳 + 一致性计数。"""

    rows: pd.DataFrame
    report_date: str = ""
    update_date: str = ""
    print_date: str = ""
    sigma_nonpositive: int = 0  # SIGMA ≤ 0 被置 NaN 的系列数
    series_missing: int = 0  # 期权行的标的在 o_cursigma 中无行(系列量/持仓改用期权行合计)
    series_mismatch: int = 0  # o_cursigma 的量/持仓与期权行合计不一致的系列数
    blank_volume_as_zero: int = (
        0  # 2018–2019 文件对无成交期权把 VOLUME/TURNOVER 留空:无开盘/最高/最低价时记 0
    )
    blank_volume_traded: int = 0  # VOLUME 空白但有成交价(保留 NaN)
    traded_no_ohlc: int = 0  # VOLUME > 0 但开/高/低价全空(成交全部按结算价,收盘价 = 结算价)


_KX_ROW_COLUMNS = [
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
    "volume_raw",
    "oi",
    "oi_raw",
    "turnover",
    "turnover_raw",
    "delta",
    "iv_exchange",
    "series_volume",
    "series_oi",
    "has_ohlc",
]


def parse_kx(raw: bytes, file_date: date) -> KxFile:
    """kx{YYYYMMDD}.dat → 期权行(OUTPUT_COLUMNS 中除 expire_date/available_day/文件元数据外的全部列)。

    丢弃 小计/总计 行;校验期权代码 = 标的 + C/P + 执行价 且与 OPTIONSTYPE/STRIKEPRICE/UNDERLYINGINSTRID 一致;
    2020-01-01 前的成交量/持仓量/成交额与系列量/持仓折半。"""
    doc = _load_json(raw)
    ymd = _ymd(file_date)
    report_date = _text(doc.get("report_date"))
    if report_date and report_date != ymd:
        raise ParseError(f"{ymd}: embedded report_date {report_date} differs from file date")
    inst = doc.get("o_curinstrument")
    if not isinstance(inst, list):
        raise ParseError(f"{ymd}: no o_curinstrument list")
    sig_rows = doc.get("o_cursigma") or []
    if not isinstance(sig_rows, list):
        raise ParseError(f"{ymd}: o_cursigma is not a list")
    out = KxFile(
        rows=pd.DataFrame(columns=_KX_ROW_COLUMNS),
        report_date=report_date,
        update_date=_text(doc.get("update_date")),
        print_date=_text(doc.get("print_date")),
    )
    ts = pd.Timestamp(file_date)
    half = 0.5 if is_double_sided(file_date) else 1.0

    # 系列(标的月份):SIGMA、系列成交量/持仓
    sigma: dict[str, float] = {}
    s_vol: dict[str, float] = {}
    s_oi: dict[str, float] = {}
    for r in sig_rows:
        if not isinstance(r, dict):
            continue
        und = _text(r.get("INSTRUMENTID"))
        if not und or _is_total(und, r.get("PRODUCTID")):
            continue
        if und in sigma:
            raise ParseError(f"{ymd}: duplicate o_cursigma row {und}")
        sv = _num(r.get("SIGMA"))
        if not np.isnan(sv) and sv <= 0:
            out.sigma_nonpositive += 1
            sv = float("nan")
        sigma[und] = sv
        s_vol[und] = _num(r.get("VOLUME"))
        if np.isnan(s_vol[und]) and _text(r.get("TURNOVER")) == "":
            s_vol[und] = 0.0  # 零成交系列的 VOLUME/TURNOVER 在 2019 年文件中留空
        s_oi[und] = _num(r.get("OPENINTEREST"))

    cols: dict[str, list[Any]] = {c: [] for c in _KX_ROW_COLUMNS}
    norm_cache: dict[str, tuple[str, str, str]] = {}
    sum_vol: dict[str, float] = {}
    sum_oi: dict[str, float] = {}
    for r in inst:
        if not isinstance(r, dict):
            continue
        code = _text(r.get("INSTRUMENTID"))
        und_raw = _text(r.get("UNDERLYINGINSTRID"))
        if _is_total(code, und_raw, r.get("PRODUCTID")) or (not code and not und_raw):
            continue
        und_code, cp_code, strike_code = parse_option_code(code)
        if und_code != und_raw:
            raise ParseError(f"{ymd}: {code} underlying {und_raw!r} differs from code")
        otype = _text(r.get("OPTIONSTYPE"))
        cp = {"1": "C", "2": "P"}.get(otype)
        if cp is None or cp != cp_code:
            raise ParseError(f"{ymd}: {code} OPTIONSTYPE {otype!r} inconsistent with code")
        strike = _num(r.get("STRIKEPRICE"))
        if strike != strike_code:
            raise ParseError(f"{ymd}: {code} STRIKEPRICE {strike} differs from code")
        if und_raw not in norm_cache:
            und = normalize_underlying(und_raw, ts)
            prod = symbol_of(und)
            pid = _text(r.get("PRODUCTID")).lower()
            if pid and pid.split("_")[0].upper() != prod:
                raise ParseError(f"{ymd}: {code} PRODUCTID {pid!r} differs from underlying {und}")
            norm_cache[und_raw] = (und, prod, exchange_of(prod))
        und, prod, ex = norm_cache[und_raw]
        vol_raw = _num(r.get("VOLUME"))
        oi_raw = _num(r.get("OPENINTEREST"))
        to_raw = _num(r.get("TURNOVER")) * TURNOVER_UNIT
        if np.isnan(vol_raw):
            no_trade = all(_text(r.get(k)) == "" for k in ("OPENPRICE", "HIGHESTPRICE", "LOWESTPRICE"))
            if no_trade and _text(r.get("TURNOVER")) == "":
                vol_raw, to_raw = 0.0, 0.0
                out.blank_volume_as_zero += 1
            else:
                out.blank_volume_traded += 1
        elif vol_raw > 0 and all(_text(r.get(k)) == "" for k in ("OPENPRICE", "HIGHESTPRICE", "LOWESTPRICE")):
            out.traded_no_ohlc += 1
        sum_vol[und_raw] = sum_vol.get(und_raw, 0.0) + (0.0 if np.isnan(vol_raw) else vol_raw)
        sum_oi[und_raw] = sum_oi.get(und_raw, 0.0) + (0.0 if np.isnan(oi_raw) else oi_raw)
        cols["date"].append(ts)
        cols["exchange"].append(ex)
        cols["product"].append(prod)
        cols["underlying"].append(und)
        cols["option_code"].append(code)
        cols["cp"].append(cp)
        cols["strike"].append(strike)
        cols["settle"].append(_num(r.get("SETTLEMENTPRICE")))
        cols["close"].append(_num(r.get("CLOSEPRICE")))
        cols["volume_raw"].append(vol_raw)
        cols["oi_raw"].append(oi_raw)
        cols["turnover_raw"].append(to_raw)
        cols["volume"].append(vol_raw * half)
        cols["oi"].append(oi_raw * half)
        cols["turnover"].append(to_raw * half)
        cols["delta"].append(_num(r.get("DELTA")))
        cols["iv_exchange"].append(sigma.get(und_raw, float("nan")))
        cols["series_volume"].append(und_raw)  # 先放原代码,下面替换
        cols["series_oi"].append(und_raw)
        cols["has_ohlc"].append(
            any(_text(r.get(k)) != "" for k in ("OPENPRICE", "HIGHESTPRICE", "LOWESTPRICE"))
        )

    # 系列量/持仓:优先 o_cursigma,缺行时用期权行合计;两者不一致计数
    ser_v: dict[str, float] = {}
    ser_o: dict[str, float] = {}
    for und_raw, tot_v in sum_vol.items():
        tot_o = sum_oi[und_raw]
        if und_raw in s_vol:
            v, o = s_vol[und_raw], s_oi[und_raw]
            if v != tot_v or o != tot_o:
                out.series_mismatch += 1
        else:
            out.series_missing += 1
            v, o = tot_v, tot_o
        ser_v[und_raw], ser_o[und_raw] = v * half, o * half
    cols["series_volume"] = [ser_v[u] for u in cols["series_volume"]]
    cols["series_oi"] = [ser_o[u] for u in cols["series_oi"]]

    df = pd.DataFrame(cols, columns=_KX_ROW_COLUMNS)
    if len(df) == 0:
        df = pd.DataFrame({c: pd.Series(dtype=object) for c in _KX_ROW_COLUMNS})
    df["date"] = pd.to_datetime(df["date"])
    for c in _KX_ROW_COLUMNS[6:-1]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["has_ohlc"] = df["has_ohlc"].astype(bool)
    if bool(df["option_code"].duplicated().any()):
        dups = df.loc[df["option_code"].duplicated(), "option_code"].head().tolist()
        raise ParseError(f"{ymd}: duplicated option rows {dups}")
    out.rows = df
    return out


def parse_baseinfo(raw: bytes, file_date: date) -> dict[str, str]:
    """ContractBaseInfo{YYYYMMDD}.dat → {期权代码: EXPIREDATE 'YYYYMMDD'}。"""
    doc = _load_json(raw)
    rows = doc.get("OptionContractBaseInfo")
    if not isinstance(rows, list):
        raise ParseError(f"{_ymd(file_date)}: no OptionContractBaseInfo list")
    out: dict[str, str] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        code = _text(r.get("INSTRUMENTID"))
        exp = _text(r.get("EXPIREDATE"))
        if not code or _is_total(code):
            continue
        if not re.fullmatch(r"\d{8}", exp):
            raise ParseError(f"{_ymd(file_date)}: {code} EXPIREDATE {exp!r}")
        out[code] = exp
    return out


# ---------------------------------------------------------------------------------------------
# 交易日历与可得日(预注册第 3 节)
# ---------------------------------------------------------------------------------------------


def project_calendar(exchanges_root: Path = DEFAULT_ROOT) -> pd.DatetimeIndex:
    """项目期货行情日期并集:data/exchanges/*/quotes_all.parquet 的 date 列。"""
    days: set[pd.Timestamp] = set()
    for p in sorted(exchanges_root.glob("*/quotes_all.parquet")):
        d = pd.read_parquet(p, columns=["date"])["date"]
        days.update(pd.DatetimeIndex(pd.to_datetime(d.unique())).normalize())
    return pd.DatetimeIndex(sorted(days))


def available_days(
    dates: pd.Series[Any] | pd.DatetimeIndex,
    calendar: pd.DatetimeIndex,
    holidays: Collection[pd.Timestamp] = (),
) -> pd.DatetimeIndex:
    """每个日期 T → 日历中严格晚于 T 的第一个交易日;T ≥ 日历末端时取 T 之后第一个非周末、非已公告假期的日子。"""
    cal = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(calendar).normalize())))
    hol = {pd.Timestamp(h).normalize() for h in holidays}
    d = pd.DatetimeIndex(pd.to_datetime(pd.Series(dates))).normalize()
    uniq = pd.DatetimeIndex(sorted(set(d)))
    pos = cal.searchsorted(uniq, side="right")
    mapping: dict[pd.Timestamp, pd.Timestamp] = {}
    for t, i in zip(uniq, pos):
        if i < len(cal):
            mapping[t] = cal[i]
            continue
        nxt = t + pd.Timedelta(days=1)
        while nxt.weekday() >= 5 or nxt in hol:
            nxt += pd.Timedelta(days=1)
        mapping[t] = nxt
    return pd.DatetimeIndex([mapping[t] for t in d])


# ---------------------------------------------------------------------------------------------
# 下载(存 raw,幂等可续传)
# ---------------------------------------------------------------------------------------------

_last_request_at: list[float] = [0.0]
_connections: dict[str, http.client.HTTPSConnection] = {}


def _throttle() -> None:
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    _last_request_at[0] = time.monotonic()


def _drop_connection(host: str) -> None:
    conn = _connections.pop(host, None)
    if conn is not None:
        conn.close()


def _get_once(url: str) -> tuple[int, bytes, dict[str, str]]:
    """单次 keep-alive GET:返回 (status, 解压后的 body, 小写头部)。"""
    u = urllib.parse.urlsplit(url)
    host = u.netloc
    conn = _connections.get(host)
    if conn is None:
        conn = http.client.HTTPSConnection(host, timeout=TIMEOUT)
        _connections[host] = conn
    try:
        conn.request("GET", u.path, headers={**HEADERS, "Host": host})
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        status = int(resp.status)
    except BaseException:
        _drop_connection(host)
        raise
    if headers.get("connection", "").lower() == "close":
        _drop_connection(host)
    if headers.get("content-encoding", "").lower() == "gzip" and body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return status, body, headers


def http_get(url: str, valid: Callable[[bytes], bool]) -> tuple[int, bytes, dict[str, str]]:
    """GET url。404 → (404, b'', headers);2xx 且通过 valid → (status, body, headers);
    其他状态、网络错误、2xx 但内容不对(WAF 页)→ 指数退避重试,用尽后抛 FetchError。"""
    delay = 2.0
    last = ""
    for attempt in range(RETRIES + 1):
        _throttle()
        try:
            status, body, headers = _get_once(url)
            if status == 404:
                return 404, b"", headers
            if 200 <= status < 300:
                if valid(body):
                    return status, body, headers
                last = f"HTTP {status} but body failed validation ({len(body)} bytes)"
            else:
                last = f"HTTP {status}"
        except (TimeoutError, http.client.HTTPException, ConnectionError, OSError, EOFError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < RETRIES:
            log.warning("GET %s failed (%s); retry in %.0fs", url, last, delay)
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"{url}: {last}")


def _valid_kx(body: bytes) -> bool:
    try:
        doc = _load_json(body)
    except ParseError:
        return False
    return isinstance(doc.get("o_curinstrument"), list)


def _valid_baseinfo(body: bytes) -> bool:
    try:
        doc = _load_json(body)
    except ParseError:
        return False
    return isinstance(doc.get("OptionContractBaseInfo"), list)


def url_for(kind: str, d: date) -> str:
    if kind == "kx":
        return KX_URL.format(d=_ymd(d))
    if kind == "baseinfo":
        return BASEINFO_URL.format(d=_ymd(d))
    raise ValueError(kind)


def raw_paths(raw: Path, kind: str, d: date) -> tuple[Path, Path]:
    """(gzip 数据文件, 旁车 meta)。"""
    name = f"kx{_ymd(d)}.dat.gz" if kind == "kx" else f"ContractBaseInfo{_ymd(d)}.dat.gz"
    f = raw / kind / f"{d.year}" / name
    return f, f.with_name(f.name + ".meta.json")


def _read_meta(meta_path: Path) -> dict[str, Any]:
    if not meta_path.exists():
        return {}
    try:
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(dict[str, Any], doc) if isinstance(doc, dict) else {}


def file_present(raw: Path, kind: str, d: date) -> bool:
    """数据文件与 meta 都在,且 gzip 大小与 meta 记录一致。"""
    f, m = raw_paths(raw, kind, d)
    if not (f.exists() and m.exists()):
        return False
    meta = _read_meta(m)
    return bool(meta.get("gz_size") == f.stat().st_size)


def _not_found_path(raw: Path) -> Path:
    return raw / "not_found.csv"


def _load_not_found(raw: Path) -> dict[tuple[str, str], str]:
    """(kind, YYYY-MM-DD) → 最近一次 404 的 probed_at_utc。"""
    p = _not_found_path(raw)
    out: dict[tuple[str, str], str] = {}
    if not p.exists():
        return out
    with p.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[(row["kind"], row["date"])] = row["probed_at_utc"]
    return out


def _record_not_found(raw: Path, kind: str, d: date, url: str, not_found: dict[tuple[str, str], str]) -> None:
    p = _not_found_path(raw)
    new = not p.exists()
    probed = _utc_now_iso()
    with p.open("a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        if new:
            w.writerow(["kind", "date", "url", "http_status", "probed_at_utc"])
        w.writerow([kind, d.isoformat(), url, 404, probed])
    not_found[(kind, d.isoformat())] = probed


def _not_found_is_final(d: date, probed_at_utc: str) -> bool:
    probed = datetime.strptime(probed_at_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (probed.astimezone(BEIJING).date() - d).days >= NOT_FOUND_STABLE_DAYS


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def ensure_file(raw: Path, kind: str, d: date, not_found: dict[tuple[str, str], str]) -> bool:
    """确保 (kind, d) 的原始文件在本地;返回文件是否存在。本地已有(大小匹配)或已知最终 404 则不发请求。"""
    if file_present(raw, kind, d):
        return True
    probed = not_found.get((kind, d.isoformat()))
    if probed is not None and _not_found_is_final(d, probed):
        return False
    url = url_for(kind, d)
    status, body, headers = http_get(url, _valid_kx if kind == "kx" else _valid_baseinfo)
    if status == 404:
        _record_not_found(raw, kind, d, url, not_found)
        log.info("%s %s: 404", d, kind)
        return False
    doc = _load_json(body)
    report_date = _text(doc.get("report_date"))
    if kind == "kx" and report_date and report_date != _ymd(d):
        raise FetchError(f"{url}: embedded report_date {report_date}")
    rows = doc.get("o_curinstrument") if kind == "kx" else doc.get("OptionContractBaseInfo")
    gz = gzip.compress(body, compresslevel=6, mtime=0)
    f, m = raw_paths(raw, kind, d)
    _atomic_write(f, gz)
    lm = headers.get("last-modified")
    meta: dict[str, Any] = {
        "url": url,
        "kind": kind,
        "date": d.isoformat(),
        "http_status": status,
        "content_encoding": headers.get("content-encoding", ""),
        "size": len(body),
        "gz_size": len(gz),
        "sha256": hashlib.sha256(body).hexdigest(),
        "fetched_at_utc": _utc_now_iso(),
        "last_modified_http": lm,
        "last_modified_utc": _last_modified_iso(lm),
        "report_date": report_date,
        "update_date": _text(doc.get("update_date")),
        "print_date": _text(doc.get("print_date")),
        "o_total_num": _text(doc.get("o_total_num")),
        "n_rows": len(rows) if isinstance(rows, list) else 0,
    }
    _atomic_write(m, json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    log.info("%s %s: saved %d bytes (gz %d), Last-Modified %s", d, kind, len(body), len(gz), lm)
    return True


def _weekdays(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def fetch(dest: Path, start: str = FIRST_DAY, end: str = DEFAULT_END) -> None:
    """抓取 [start, end] 每个工作日的 kx 文件;kx 存在的日子再抓 ContractBaseInfo。幂等、可续传;
    单个文件重试用尽时记下并继续,结束时若有失败抛 FetchError(重跑同一命令只补缺的)。"""
    start_d = max(_parse_iso(start), _parse_iso(FIRST_DAY))
    end_d = min(_parse_iso(end) if end else _today_beijing(), _today_beijing())
    raw = dest / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    not_found = _load_not_found(raw)
    failures: list[str] = []
    n_kx = n_base = 0
    for d in _weekdays(start_d, end_d):
        try:
            if not ensure_file(raw, "kx", d, not_found):
                continue
            n_kx += 1
            if ensure_file(raw, "baseinfo", d, not_found):
                n_base += 1
        except (FetchError, ParseError) as e:
            log.error("%s: %s", d, e)
            failures.append(f"{d}: {e}")
    log.info("fetch done: %d kx files, %d ContractBaseInfo files present", n_kx, n_base)
    if failures:
        raise FetchError(f"{len(failures)} downloads failed; rerun to resume. First: {failures[:3]}")


# ---------------------------------------------------------------------------------------------
# 构建 options_daily.parquet
# ---------------------------------------------------------------------------------------------


def iter_raw(raw: Path, kind: str) -> Iterator[tuple[date, Path]]:
    """按日期枚举本地原始文件(只认 meta 齐全的)。"""
    pat = "kx*.dat.gz" if kind == "kx" else "ContractBaseInfo*.dat.gz"
    items: list[tuple[date, Path]] = []
    for f in (raw / kind).glob(f"*/{pat}"):
        digits = re.sub(r"\D", "", f.name)
        d = datetime.strptime(digits[:8], "%Y%m%d").date()
        if file_present(raw, kind, d):
            items.append((d, f))
    items.sort()
    yield from items


def _read_gz(path: Path) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()


@dataclass
class BuildReport:
    """build 过程中的一致性计数,供命令行汇总。"""

    kx_days: int = 0
    baseinfo_days: int = 0
    expiry_conflicts: list[tuple[str, str, str, str]] = field(default_factory=list)
    update_date_not_t: list[tuple[str, str]] = field(default_factory=list)
    sigma_nonpositive: int = 0
    series_missing: int = 0
    series_mismatch: int = 0
    blank_volume_as_zero: int = 0
    blank_volume_traded: int = 0
    traded_no_ohlc: int = 0
    expire_fallback: dict[str, int] = field(default_factory=dict)  # 来源 → 行数(asof 以外)
    off_calendar_option_days: list[str] = field(default_factory=list)


class ExpiryBook:
    """到期日的时点视图。交易所会改已上市合约的到期日(例:2018-12-11 起 cu1901 系列由 20181225 改为 20181224,
    因元旦休市调整),所以 lookup 在 advance(T) 之后返回日期 ≤ T 的最新 ContractBaseInfo 值;
    ≤ T 的文件里没有该代码时,依次回退到:同系列 ≤ T 的值、之后文件中首次出现的代码值、之后文件中首次出现的系列值。"""

    def __init__(self, raw: Path, report: BuildReport | None = None) -> None:
        self._files = list(iter_raw(raw, "baseinfo"))
        self._next = 0
        self._report = report
        self.code: dict[str, str] = {}
        self.series: dict[str, str] = {}
        self.later_code: dict[str, str] = {}
        self.later_series: dict[str, str] = {}
        for d, f in self._files:
            for code, exp in parse_baseinfo(_read_gz(f), d).items():
                self.later_code.setdefault(code, exp)
                m = _OPTION_RE.match(code)
                if m is not None:
                    self.later_series.setdefault(m.group(1), exp)
        if report is not None:
            report.baseinfo_days = len(self._files)

    def advance(self, t: date) -> None:
        """吸收日期 ≤ t 的全部基础信息文件(按日期顺序,后者覆盖前者;值变化记入 report.expiry_conflicts)。"""
        while self._next < len(self._files) and self._files[self._next][0] <= t:
            d, f = self._files[self._next]
            self._next += 1
            for code, exp in parse_baseinfo(_read_gz(f), d).items():
                prev = self.code.get(code)
                if prev is not None and prev != exp and self._report is not None:
                    self._report.expiry_conflicts.append((code, d.isoformat(), prev, exp))
                self.code[code] = exp
                m = _OPTION_RE.match(code)
                if m is not None:
                    self.series[m.group(1)] = exp

    def lookup(self, code: str) -> tuple[str | None, str]:
        """(到期日 'YYYYMMDD' 或 None, 来源 asof/series/later/later_series/missing)。"""
        e = self.code.get(code)
        if e is not None:
            return e, "asof"
        m = _OPTION_RE.match(code)
        und = m.group(1) if m is not None else ""
        e = self.series.get(und)
        if e is not None:
            return e, "series"
        e = self.later_code.get(code)
        if e is not None:
            return e, "later"
        e = self.later_series.get(und)
        if e is not None:
            return e, "later_series"
        return None, "missing"


def build(
    dest: Path,
    exchanges_root: Path = DEFAULT_ROOT,
    holidays: Collection[pd.Timestamp] | None = None,
    report: BuildReport | None = None,
) -> pd.DataFrame:
    """raw/ → options_daily.parquet(一行一个 (date, option_code))与 files.csv;返回该表。"""
    rep = report if report is not None else BuildReport()
    raw = dest / "raw"
    book = ExpiryBook(raw, rep)
    frames: list[pd.DataFrame] = []
    file_rows: list[dict[str, Any]] = []
    for d, f in iter_raw(raw, "kx"):
        meta = _read_meta(f.with_name(f.name + ".meta.json"))
        kx = parse_kx(_read_gz(f), d)
        rep.kx_days += 1
        rep.sigma_nonpositive += kx.sigma_nonpositive
        rep.series_missing += kx.series_missing
        rep.series_mismatch += kx.series_mismatch
        rep.blank_volume_as_zero += kx.blank_volume_as_zero
        rep.blank_volume_traded += kx.blank_volume_traded
        rep.traded_no_ohlc += kx.traded_no_ohlc
        upd = kx.update_date or _text(meta.get("update_date"))
        if upd[:8] != _ymd(d):
            rep.update_date_not_t.append((d.isoformat(), upd))
        df = kx.rows
        book.advance(d)
        exp: list[str | None] = []
        for code in df["option_code"].tolist():
            e, src = book.lookup(code)
            if src != "asof":
                rep.expire_fallback[src] = rep.expire_fallback.get(src, 0) + 1
            exp.append(e)
        df["expire_date"] = pd.to_datetime(pd.Series(exp, dtype=object), format="%Y%m%d").values
        rel = f.relative_to(dest).as_posix()
        df["source_file"] = rel
        df["last_modified_utc"] = str(meta.get("last_modified_utc") or "")
        df["update_date"] = upd
        frames.append(df)
        file_rows.append(_file_row(dest, f, meta, d, "kx", len(df)))
    for d, f in iter_raw(raw, "baseinfo"):
        meta = _read_meta(f.with_name(f.name + ".meta.json"))
        file_rows.append(_file_row(dest, f, meta, d, "baseinfo", int(meta.get("n_rows") or 0)))

    if frames:
        out = pd.concat(frames, ignore_index=True)
    else:
        out = pd.DataFrame({c: pd.Series(dtype=object) for c in OUTPUT_COLUMNS})
    opt_days = pd.DatetimeIndex(sorted(set(pd.to_datetime(out["date"]))))
    fut_cal = project_calendar(exchanges_root)
    rep.off_calendar_option_days = [
        t.date().isoformat() for t in opt_days if len(fut_cal) and t <= fut_cal.max() and t not in fut_cal
    ]
    cal = pd.DatetimeIndex(sorted(set(fut_cal) | set(opt_days)))
    hol = holidays if holidays is not None else list(load_holidays())
    out["available_day"] = available_days(out["date"], cal, hol)
    out = finalize(out)
    dest.mkdir(parents=True, exist_ok=True)
    out.to_parquet(dest / "options_daily.parquet", index=False)
    files = pd.DataFrame(file_rows, columns=FILES_COLUMNS).sort_values(["kind", "date"], kind="mergesort")
    files.to_csv(dest / "files.csv", index=False, lineterminator="\n")
    return out


def _file_row(dest: Path, f: Path, meta: dict[str, Any], d: date, kind: str, n_rows: int) -> dict[str, Any]:
    return {
        "kind": kind,
        "date": d.isoformat(),
        "path": f.relative_to(dest).as_posix(),
        "url": meta.get("url", ""),
        "http_status": meta.get("http_status", ""),
        "size": meta.get("size", ""),
        "gz_size": meta.get("gz_size", ""),
        "sha256": meta.get("sha256", ""),
        "fetched_at_utc": meta.get("fetched_at_utc", ""),
        "last_modified_utc": meta.get("last_modified_utc", ""),
        "report_date": meta.get("report_date", ""),
        "update_date": meta.get("update_date", ""),
        "print_date": meta.get("print_date", ""),
        "n_rows": n_rows,
    }


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """列顺序与类型按输出约定;排序;(date, option_code) 唯一、available_day > date 校验。"""
    out = df[OUTPUT_COLUMNS].copy()
    for c in ("date", "expire_date", "available_day"):
        out[c] = pd.to_datetime(out[c]).astype("datetime64[ns]")
    for c in ("exchange", "product", "underlying", "option_code", "cp", "source_file", "last_modified_utc"):
        out[c] = out[c].astype(str)
    out["update_date"] = out["update_date"].fillna("").astype(str)
    for c in (
        "strike",
        "settle",
        "close",
        "volume",
        "volume_raw",
        "oi",
        "oi_raw",
        "turnover",
        "turnover_raw",
        "delta",
        "iv_exchange",
        "series_volume",
        "series_oi",
    ):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    out = out.sort_values(["date", "product", "underlying", "cp", "strike"], kind="mergesort")
    out = out.reset_index(drop=True)
    dup = out.duplicated(["date", "option_code"])
    if bool(dup.any()):
        raise ParseError(f"duplicate (date, option_code): {out.loc[dup, 'option_code'].head().tolist()}")
    if len(out) and not bool((out["available_day"] > out["date"]).all()):
        raise ParseError("available_day must be strictly after date")
    return out


# ---------------------------------------------------------------------------------------------
# 汇总与命令行
# ---------------------------------------------------------------------------------------------


def coverage(df: pd.DataFrame, listing: dict[str, str] | None = None) -> pd.DataFrame:
    """预注册品种:首个日期、行数、上市日起的期权文件日数与缺失日数(当日无该品种任何期权行)。"""
    lst = listing if listing is not None else PREREG_LISTING
    days = pd.DatetimeIndex(sorted(set(pd.to_datetime(df["date"]))))
    rows: list[dict[str, Any]] = []
    for prod, first in lst.items():
        g = df[df["product"] == prod]
        have = pd.DatetimeIndex(sorted(set(pd.to_datetime(g["date"]))))
        expect = days[days >= pd.Timestamp(first)]
        missing = expect.difference(have)
        rows.append(
            {
                "product": prod,
                "exchange": exchange_of(prod),
                "listing_prereg": first,
                "first_date": have.min().date().isoformat() if len(have) else "",
                "last_date": have.max().date().isoformat() if len(have) else "",
                "n_days": len(have),
                "n_rows": len(g),
                "n_traded_rows": int((g["volume"] > 0).sum()),
                "missing_days": len(missing),
                "first_missing": [t.date().isoformat() for t in missing[:5]],
            }
        )
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame, rep: BuildReport, exchanges_root: Path = DEFAULT_ROOT) -> str:
    lines = [
        f"options_daily: {len(df)} rows, {df['date'].nunique()} days, {df['product'].nunique()} products"
    ]
    if len(df) == 0:
        return "\n".join(lines)
    lines.append(f"date range: {df['date'].min().date()} → {df['date'].max().date()}")
    lines.append(f"kx files parsed: {rep.kx_days}; ContractBaseInfo files: {rep.baseinfo_days}")
    fut = project_calendar(exchanges_root)
    lo, hi = df["date"].min(), df["date"].max()
    fut_days = fut[(fut >= lo) & (fut <= hi)]
    opt_days = pd.DatetimeIndex(sorted(set(df["date"])))
    gaps = fut_days.difference(opt_days)
    lines.append(
        f"futures trading days in range without an option file: {len(gaps)} {[t.date().isoformat() for t in gaps[:10]]}"
    )
    lines.append(f"option days not in futures calendar: {rep.off_calendar_option_days[:10]}")
    lines.append(
        f"update_date[:8] != T: {len(rep.update_date_not_t)} files (first {rep.update_date_not_t[:3]}, last {rep.update_date_not_t[-3:]})"
    )
    changed = sorted({(parse_option_code(c[0])[0], c[1], c[2], c[3]) for c in rep.expiry_conflicts})
    n_codes = len({c[0] for c in rep.expiry_conflicts})
    lines.append(
        f"expiry: as-of changes {len(rep.expiry_conflicts)} rows / {n_codes} codes; "
        f"(series, file date, old, new) {changed}; fallback rows {rep.expire_fallback}"
    )
    lines.append(
        f"o_cursigma: SIGMA<=0 set NaN {rep.sigma_nonpositive}; series rows missing {rep.series_missing}; series totals mismatch {rep.series_mismatch}"
    )
    lines.append(
        f"blank VOLUME/TURNOVER on untraded rows set to 0: {rep.blank_volume_as_zero}; "
        f"blank VOLUME with trade prices (kept NaN): {rep.blank_volume_traded}"
    )
    lines.append(
        f"VOLUME > 0 with blank OPEN/HIGH/LOW (all volume at settlement price, close = settle): {rep.traded_no_ohlc}"
    )
    lines.append(f"iv_exchange NaN rows: {int(df['iv_exchange'].isna().sum())}")
    nan_cols = {c: int(df[c].isna().sum()) for c in ("settle", "close", "volume", "oi", "turnover", "delta")}
    lines.append(f"NaN counts: {nan_cols}")
    lines.append("per product (all): first date, rows")
    for prod, g in df.groupby("product", sort=True):
        lines.append(f"  {prod:>3} {g['exchange'].iloc[0]:>4} {g['date'].min().date()}  rows={len(g)}")
    cov = coverage(df)
    lines.append("prereg coverage:")
    lines.append(cov.to_string(index=False))
    # 标的能否在项目期货行情中找到(只是代码对齐检查,不涉及收益)
    fq: list[pd.DataFrame] = []
    for p in sorted(exchanges_root.glob("*/quotes_all.parquet")):
        fq.append(pd.read_parquet(p, columns=["date", "contract"]))
    if fq:
        q = pd.concat(fq, ignore_index=True).drop_duplicates()
        pairs = df[["date", "underlying"]].drop_duplicates()
        m = pairs.merge(q, left_on=["date", "underlying"], right_on=["date", "contract"], how="left")
        miss = m[m["contract"].isna()]
        lines.append(
            f"(date, underlying) pairs found in futures quotes: {len(pairs) - len(miss)}/{len(pairs)}; "
            f"missing examples {miss[['date', 'underlying']].head(5).values.tolist()}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="SHFE/INE option daily quotes → options_daily.parquet")
    ap.add_argument("--dest", type=Path, required=True, help="data/external/alt/shfe_options")
    ap.add_argument("--start", default=FIRST_DAY)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--no-fetch", action="store_true", help="only rebuild outputs from raw/")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dest: Path = args.dest
    if not args.no_fetch:
        fetch(dest, args.start, args.end)
    rep = BuildReport()
    df = build(dest, report=rep)
    print(summary(df, rep))


if __name__ == "__main__":
    main()
