"""上海期货交易所(SHFE)公开日频数据:日行情(kx)、会员成交持仓排名(pm)、仓单日报(dailystock)。

上期能源(INE)的网站与上期所同一套结构,ine.py 只换域名与交易所标签,解析全部复用本模块(Site 参数化)。
URL 模式、字段映射、口径切换与已知坑见 docs/data_exchanges_shfe.md。

用法:
    PYTHONPATH=src python3 -m cta.data.exchanges.shfe backfill --start 2016-01-04 --end 2026-09-16 \
        --kinds quotes,positions,receipts
"""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, cast

import pandas as pd

from cta.data.exchanges.base import (
    POSITION_COLS,
    QUOTE_COLS,
    RECEIPT_COLS,
    Exchange,
    Kind,
    Store,
    normalize_contract,
    symbol_of,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# 常量:口径与站点
# ---------------------------------------------------------------------------------------------

# 成交量/持仓量计数口径:2020-01-01 起上期所与能源中心均由"双边"改为"单边"(上期所 2019-10-29 公告,证监会统一安排)。
# 规范化数据保存交易所原值,不折算;2020-01-01 之前的 volume/open_interest 是双边数,之后是单边数。
SINGLE_SIDED_FROM = pd.Timestamp("2020-01-01")
# 行情文件逐合约 TURNOVER(成交额,万元)字段出现的首日(上期所与能源中心同日);之前 turnover 为 NaN。由回填结果确定。
TURNOVER_FROM = pd.Timestamp("2021-07-28")
# 仓单日报接口切换:旧 JSON 接口(…/dailydata/{d}dailystock.dat)最后可用日 与 新 HTML 接口(…/stockdata/dailystock_{d}/ZH/all.html)首日。
RECEIPT_HTML_FROM = pd.Timestamp("2025-11-13")
RECEIPT_DAT_UNTIL = pd.Timestamp("2025-11-17")

# 能源中心品种:上期所的 kx/仓单文件里也会出现这些品种(同一套系统),SHFE 解析时剔除,INE 解析时只保留。
INE_SYMBOLS: frozenset[str] = frozenset({"SC", "LU", "NR", "BC", "EC"})

# 仓单日报品种中文名 → 品种代码(旧 JSON 在 2022 年前没有 VARID,只能按名字映射;新 HTML 只有名字)。
RECEIPT_SYMBOLS: dict[str, str] = {
    "铜": "CU",
    "铜(BC)": "BC",
    "铝": "AL",
    "锌": "ZN",
    "铅": "PB",
    "镍": "NI",
    "锡": "SN",
    "氧化铝": "AO",
    "铸造铝合金": "AD",
    "黄金": "AU",
    "白银": "AG",
    "螺纹钢": "RB",
    "线材": "WR",
    "热轧卷板": "HC",
    "不锈钢": "SS",
    "中质含硫原油": "SC",
    "低硫燃料油": "LU",
    "燃料油": "FU",
    "石油沥青": "BU",
    "沥青": "BU",
    "丁二烯橡胶": "BR",
    "天然橡胶": "RU",
    "20号胶": "NR",
    "纸浆": "SP",
    "胶版印刷纸": "OP",
}
# 排名文件里的合计行:RANK -1 = 期货公司会员合计,0 = 非期货公司会员合计,999 = 前 20 名合计。
POSITION_TOTAL_LABELS: dict[int, str] = {-1: "期货公司会员", 0: "非期货公司会员", 999: "合计"}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
MIN_INTERVAL = 0.5  # 秒,同一进程内两次请求的最小间隔
RETRIES = 3
TIMEOUT = 60
KINDS: tuple[Kind, ...] = ("quotes", "positions", "receipts")


@dataclass(frozen=True)
class Site:
    """一个交易所站点:交易所标签、域名、它拥有的品种(None = 除能源中心品种外的全部)。"""

    exchange: Exchange
    base_url: str
    symbols: frozenset[str] | None = None
    # 新版仓单 HTML 从哪个域名取:两站文件内容相同,ine.cn 的 HTML 路径有 WAF(JS 挑战),INE 改用上期所域名
    receipts_html_base: str | None = None

    def owns(self, symbol: str) -> bool:
        if self.symbols is None:
            return symbol not in INE_SYMBOLS
        return symbol in self.symbols

    def quotes_url(self, date: pd.Timestamp) -> str:
        return f"{self.base_url}/data/tradedata/future/dailydata/kx{date:%Y%m%d}.dat"

    def positions_url(self, date: pd.Timestamp) -> str:
        return f"{self.base_url}/data/tradedata/future/dailydata/pm{date:%Y%m%d}.dat"

    def receipts_dat_url(self, date: pd.Timestamp) -> str:
        return f"{self.base_url}/data/tradedata/future/dailydata/{date:%Y%m%d}dailystock.dat"

    def receipts_html_url(self, date: pd.Timestamp) -> str:
        base = self.receipts_html_base or self.base_url
        return f"{base}/data/tradedata/future/stockdata/dailystock_{date:%Y%m%d}/ZH/all.html"


SHFE = Site("SHFE", "https://www.shfe.com.cn")


# ---------------------------------------------------------------------------------------------
# HTTP:限速、退避重试、404 → None
# ---------------------------------------------------------------------------------------------


class FetchError(RuntimeError):
    """重试耗尽后的下载失败(非 404)。"""


_last_request_at: list[float] = [0.0]  # 进程内上次请求时刻(monotonic)
_connections: dict[
    str, http.client.HTTPSConnection
] = {}  # host → keep-alive 连接(省掉每次 TCP+TLS 握手,约快一倍)


def _throttle() -> None:
    wait = MIN_INTERVAL - (time.monotonic() - _last_request_at[0])
    if wait > 0:
        time.sleep(wait)
    _last_request_at[0] = time.monotonic()


def _connection(host: str, timeout: int) -> http.client.HTTPSConnection:
    conn = _connections.get(host)
    if conn is None:
        conn = http.client.HTTPSConnection(host, timeout=timeout)
        _connections[host] = conn
    return conn


def _drop_connection(host: str) -> None:
    conn = _connections.pop(host, None)
    if conn is not None:
        conn.close()


def _get_once(url: str, timeout: int) -> tuple[int, bytes]:
    u = urllib.parse.urlsplit(url)
    host = u.netloc
    path = u.path + (f"?{u.query}" if u.query else "")
    conn = _connection(host, timeout)
    try:
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Host": host})
        resp = conn.getresponse()
        body = resp.read()
        if resp.getheader("Connection", "").lower() == "close":
            _drop_connection(host)
        return resp.status, body
    except BaseException:
        _drop_connection(host)
        raise


def http_get(url: str, retries: int = RETRIES, timeout: int = TIMEOUT) -> bytes | None:
    """下载 url。404 返回 None(节假日/未发布);其他错误指数退避重试 retries 次后抛 FetchError。"""
    delay = 1.0
    last: BaseException | None = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            status, body = _get_once(url, timeout)
            if status == 404:
                return None
            if 200 <= status < 300:
                return body
            last = urllib.error.HTTPError(url, status, f"HTTP {status}", None, None)  # type: ignore[arg-type]
        except (http.client.HTTPException, socket.timeout, ConnectionError, OSError) as e:
            last = e
        if attempt < retries:
            log.warning("fetch %s failed (%s); retry in %.0fs", url, last, delay)
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"{url}: {last}")


# ---------------------------------------------------------------------------------------------
# 下载(存 raw)
# ---------------------------------------------------------------------------------------------


def _json_or_none(raw: bytes | None, url: str) -> bytes | None:
    """200 但不是 JSON(例如 WAF 挑战页)视为下载失败而不是缺数据。"""
    if raw is None:
        return None
    try:
        json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FetchError(f"{url}: response is not JSON ({e})") from e
    return raw


def fetch_quotes(date: pd.Timestamp, store: Store | None = None, site: Site = SHFE) -> bytes | None:
    """下载某日日行情 JSON 并存 raw;404 返回 None。"""
    st = store or Store()
    date = pd.Timestamp(date)
    cached = st.read_raw(site.exchange, "quotes", date, "json")
    if cached is not None:
        return cached
    url = site.quotes_url(date)
    raw = _json_or_none(http_get(url), url)
    if raw is not None:
        st.write_raw(site.exchange, "quotes", date, "json", raw)
    return raw


def fetch_positions(date: pd.Timestamp, store: Store | None = None, site: Site = SHFE) -> bytes | None:
    """下载某日会员成交持仓排名 JSON 并存 raw;404 返回 None。"""
    st = store or Store()
    date = pd.Timestamp(date)
    cached = st.read_raw(site.exchange, "positions", date, "json")
    if cached is not None:
        return cached
    url = site.positions_url(date)
    raw = _json_or_none(http_get(url), url)
    if raw is not None:
        st.write_raw(site.exchange, "positions", date, "json", raw)
    return raw


def fetch_receipts(
    date: pd.Timestamp, store: Store | None = None, site: Site = SHFE
) -> tuple[str, bytes] | None:
    """下载某日仓单日报并存 raw,返回 (ext, content),ext 为 'json'(旧接口)或 'html'(2025-11 起的新接口)。

    两个接口按日期先后顺序尝试,都 404 才算缺数据。"""
    st = store or Store()
    date = pd.Timestamp(date)
    for ext in ("json", "html"):
        cached = st.read_raw(site.exchange, "receipts", date, ext)
        if cached is not None:
            return ext, cached
    order: list[str] = ["json", "html"] if date <= RECEIPT_DAT_UNTIL else ["html", "json"]
    if date < RECEIPT_HTML_FROM:
        order = ["json"]
    for ext in order:
        url = site.receipts_dat_url(date) if ext == "json" else site.receipts_html_url(date)
        raw = http_get(url)
        if raw is None:
            continue
        if ext == "json":
            raw = _json_or_none(raw, url)
        elif b"<table" not in raw:
            raise FetchError(f"{url}: response has no table (WAF page?)")
        assert raw is not None
        st.write_raw(site.exchange, "receipts", date, ext, raw)
        return ext, raw
    return None


# ---------------------------------------------------------------------------------------------
# 解析:raw → base 规范化 DataFrame
# ---------------------------------------------------------------------------------------------


def _num(v: Any) -> float:
    if v is None:
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in {"", "-"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _zh(v: Any) -> str:
    """'铜$$COPPER' → '铜'(旧 JSON 的中英双语字段)。"""
    return _text(v).split("$$")[0].strip()


def _load_json(raw: bytes) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(raw.decode("utf-8-sig")))


def parse_quotes(raw: bytes, date: pd.Timestamp, site: Site = SHFE) -> pd.DataFrame:
    """kx JSON → QUOTE_COLS。只保留期货合约行(PRODUCTID 以 _f 结尾且 DELIVERYMONTH 为 4 位数字);
    剔除 小计/总计、期转现(efp)、TAS、期权;只保留本站点拥有的品种。价格/成交量/持仓量为交易所原值,turnover 单位万元。"""
    date = pd.Timestamp(date)
    data = _load_json(raw)
    rows = cast(list[dict[str, Any]], data.get("o_curinstrument") or [])
    out: list[dict[str, Any]] = []
    for r in rows:
        pid = _text(r.get("PRODUCTID"))
        dm = _text(r.get("DELIVERYMONTH"))
        if not pid.endswith("_f") or not re.fullmatch(r"\d{4}", dm):
            continue
        group = _text(r.get("PRODUCTGROUPID")) or pid[:-2]
        contract = normalize_contract(group + dm, site.exchange, date)
        sym = symbol_of(contract)
        if not site.owns(sym):
            continue
        settle = _num(r.get("SETTLEMENTPRICE"))
        close = _num(r.get("CLOSEPRICE"))
        prev = _num(r.get("PRESETTLEMENTPRICE"))
        if not settle > 0:  # 交易所偶有结算价留空(极少):按 收盘价 → 昨结 补,便于通过 validate;文档已记
            settle = close if close > 0 else prev
            log.warning(
                "%s %s %s: empty settle, filled with %.4g", site.exchange, date.date(), contract, settle
            )
        out.append(
            {
                "date": date,
                "exchange": site.exchange,
                "symbol": sym,
                "contract": contract,
                "open": _num(r.get("OPENPRICE")),
                "high": _num(r.get("HIGHESTPRICE")),
                "low": _num(r.get("LOWESTPRICE")),
                "close": close,
                "settle": settle,
                "prev_settle": prev,
                "volume": _num(r.get("VOLUME")),
                "open_interest": _num(r.get("OPENINTEREST")),
                "turnover": _num(r.get("TURNOVER")) if "TURNOVER" in r else float("nan"),
            }
        )
    return pd.DataFrame(out, columns=QUOTE_COLS)


_INST_RE = re.compile(r"^([a-z]{1,2})(\d{4})$")
_PRODUCT_AGG_RE = re.compile(r"^([a-z]{1,2})(all|actv)$")


def parse_positions(raw: bytes, date: pd.Timestamp, site: Site = SHFE) -> pd.DataFrame:
    """pm JSON → POSITION_COLS。每行三榜并排(成交量榜 / 多头榜 / 空头榜)。
    INSTRUMENTID 为合约(cu2610)或品种合计(cuall / 2016 年的 cuactv,contract 记为品种代码本身如 'CU')。
    RANK -1/0/999(期货公司会员合计 / 非期货公司会员合计 / 前 20 名合计)→ is_total=True、rank=0,member_* 为对应标签。"""
    date = pd.Timestamp(date)
    data = _load_json(raw)
    rows = cast(list[dict[str, Any]], data.get("o_cursor") or [])
    out: list[dict[str, Any]] = []
    for r in rows:
        inst = _text(r.get("INSTRUMENTID")).lower()
        m = _INST_RE.match(inst)
        if m:
            contract = normalize_contract(inst, site.exchange, date)
            sym = symbol_of(contract)
        else:
            m2 = _PRODUCT_AGG_RE.match(inst)
            if not m2:
                log.warning("%s %s: unrecognised INSTRUMENTID %r skipped", site.exchange, date.date(), inst)
                continue
            sym = m2.group(1).upper()
            contract = sym
        if not site.owns(sym):
            continue
        rank = int(_num(r.get("RANK")))
        label = POSITION_TOTAL_LABELS.get(rank)
        is_total = label is not None

        def member(key: str, row: dict[str, Any] = r, total: str | None = label) -> str | None:
            if total is not None:
                return total
            s = _text(row.get(key))
            return s or None

        out.append(
            {
                "date": date,
                "exchange": site.exchange,
                "symbol": sym,
                "contract": contract,
                "is_total": is_total,
                "rank": 0 if is_total else rank,
                "member_vol": member("PARTICIPANTABBR1"),
                "vol": _num(r.get("CJ1")),
                "vol_chg": _num(r.get("CJ1_CHG")),
                "member_long": member("PARTICIPANTABBR2"),
                "long_oi": _num(r.get("CJ2")),
                "long_chg": _num(r.get("CJ2_CHG")),
                "member_short": member("PARTICIPANTABBR3"),
                "short_oi": _num(r.get("CJ3")),
                "short_chg": _num(r.get("CJ3_CHG")),
            }
        )
    return pd.DataFrame(out, columns=POSITION_COLS)


_WH_SUFFIX_RE = re.compile(r"[（(]?(仓库|厂库)[)）]?$")


def receipt_symbol(varname: str, varid: str = "") -> tuple[str | None, bool]:
    """仓单日报品种名 → (品种代码, 是否厂库表)。'螺纹钢厂库' → ('RB', True),'氧化铝(仓库)' → ('AO', False)。
    有 VARID(2022 年起的 JSON)优先用它;名字不认识返回 (None, …)。"""
    name = _zh(varname)
    factory = "厂库" in name
    base = _WH_SUFFIX_RE.sub("", name).strip()
    vid = _text(varid).upper()
    if re.fullmatch(r"[A-Z]{1,2}", vid):
        return vid, factory
    return RECEIPT_SYMBOLS.get(base), factory


def _receipt_row(
    date: pd.Timestamp,
    site: Site,
    sym: str,
    factory: bool,
    warehouse: str,
    is_total: bool,
    receipts: float,
    change: float,
) -> dict[str, Any]:
    return {
        "date": date,
        "exchange": site.exchange,
        "symbol": sym,
        "warehouse": warehouse + ("(厂库)" if factory else ""),
        "is_total": is_total,
        "receipts": receipts,
        "change": change,
    }


def _parse_receipts_json(raw: bytes, date: pd.Timestamp, site: Site) -> pd.DataFrame:
    """旧 JSON:ROWSTATUS 0 = 仓库行,1 = 地区合计(warehouse='{地区}合计'),2 = 品种总计(保税商品总计/完税商品总计/总计)。"""
    data = _load_json(raw)
    rows = cast(list[dict[str, Any]], data.get("o_cursor") or [])
    out: list[dict[str, Any]] = []
    unknown: set[str] = set()
    for r in rows:
        sym, factory = receipt_symbol(_text(r.get("VARNAME")), _text(r.get("VARID")))
        if sym is None:
            unknown.add(_zh(r.get("VARNAME")))
            continue
        if _text(r.get("WHTYPE")) == "2":
            factory = True
        if not site.owns(sym):
            continue
        status = _text(r.get("ROWSTATUS"))
        wh = _zh(r.get("WHABBRNAME"))
        region = _zh(r.get("REGNAME"))
        if status == "1":
            warehouse, is_total = f"{region}合计", True
        elif status == "2":
            warehouse, is_total = wh, True
        else:
            warehouse, is_total = wh, False
        out.append(
            _receipt_row(
                date,
                site,
                sym,
                factory,
                warehouse,
                is_total,
                _num(r.get("WRTWGHTS")),
                _num(r.get("WRTCHANGE")),
            )
        )
    if unknown:
        log.warning(
            "%s %s receipts: unknown product names %s skipped", site.exchange, date.date(), sorted(unknown)
        )
    return pd.DataFrame(out, columns=RECEIPT_COLS)


@dataclass
class _Cell:
    text: str = ""
    attrs: dict[str, str] = field(default_factory=dict)


class _TableParser(HTMLParser):
    """把 HTML 里所有 <tr> 收成 [(row_class, [cell...])],跨表连续;只用标准库。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[str, list[_Cell]]] = []
        self._row: list[_Cell] | None = None
        self._row_class = ""
        self._cell: _Cell | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "tr":
            self._row, self._row_class = [], a.get("class", "")
        elif tag in ("td", "th") and self._row is not None:
            self._cell = _Cell("", a)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._cell.text = re.sub(r"\s+", " ", self._cell.text).strip()
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append((self._row_class, self._row))
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.text += data


def _parse_receipts_html(raw: bytes, date: pd.Timestamp, site: Site) -> pd.DataFrame:
    """新 HTML(2025-11 起):每个品种一张表;special_row_type 行给品种名与单位;地区单元格带 rowspan;
    isTotal 行为 '合计'(地区合计)或 colspan=2 的 保税商品总计/完税商品总计/总计。"""
    p = _TableParser()
    p.feed(raw.decode("utf-8", errors="replace"))
    out: list[dict[str, Any]] = []
    sym: str | None = None
    factory = False
    region = ""
    unknown: set[str] = set()
    for row_class, cells in p.rows:
        texts = [c.text for c in cells]
        if not cells:
            continue
        if "special_row_type" in row_class:
            name = texts[0]
            sym, factory = receipt_symbol(name)
            region = ""
            if sym is None:
                unknown.add(name)
            continue
        if sym is None or not site.owns(sym) or len(texts) < 3:
            continue
        if "isTotal" in row_class:
            label = texts[0]
            warehouse = f"{region}合计" if label == "合计" else label
            out.append(
                _receipt_row(date, site, sym, factory, warehouse, True, _num(texts[-2]), _num(texts[-1]))
            )
            continue
        if len(texts) >= 4:
            region = texts[0]
            wh = texts[1]
        else:
            wh = texts[0]
        if not re.fullmatch(r"-?[\d,]+(\.\d+)?", texts[-2] or "x") and texts[-2] != "":
            continue  # 表头等非数据行
        out.append(_receipt_row(date, site, sym, factory, wh, False, _num(texts[-2]), _num(texts[-1])))
    if unknown:
        log.warning(
            "%s %s receipts: unknown product names %s skipped", site.exchange, date.date(), sorted(unknown)
        )
    return pd.DataFrame(out, columns=RECEIPT_COLS)


def parse_receipts(raw: bytes, date: pd.Timestamp, site: Site = SHFE, ext: str = "json") -> pd.DataFrame:
    """仓单日报 → RECEIPT_COLS。仓库行 is_total=False;地区合计('上海合计')与品种总计(保税商品总计/完税商品总计/总计)
    is_total=True;厂库表的 warehouse 加后缀 '(厂库)'。单位:黄金/白银 千克、原油 桶、其余 吨(交易所原值,不换算)。"""
    date = pd.Timestamp(date)
    if ext == "html":
        return _parse_receipts_html(raw, date, site)
    return _parse_receipts_json(raw, date, site)


# ---------------------------------------------------------------------------------------------
# 落盘与回填
# ---------------------------------------------------------------------------------------------


def missing_log_path(store: Store, site: Site) -> Path:
    return store.root / site.exchange / "missing.log"


def load_missing(store: Store, site: Site) -> set[tuple[str, str]]:
    """missing.log 每行:YYYY-MM-DD\\tkind\\treason\\turl。返回 {(date, kind)}。"""
    p = missing_log_path(store, site)
    if not p.exists():
        return set()
    out: set[tuple[str, str]] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and not line.startswith("#"):
            out.add((parts[0], parts[1]))
    return out


def _log_missing(store: Store, site: Site, date: pd.Timestamp, kind: str, reason: str, url: str) -> None:
    p = missing_log_path(store, site)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{date:%Y-%m-%d}\t{kind}\t{reason}\t{url}\n")


def _url_of(site: Site, kind: str, date: pd.Timestamp) -> str:
    if kind == "quotes":
        return site.quotes_url(date)
    if kind == "positions":
        return site.positions_url(date)
    return site.receipts_dat_url(date) if date < RECEIPT_HTML_FROM else site.receipts_html_url(date)


def ingest_day(
    date: pd.Timestamp,
    kinds: Iterable[Kind] = KINDS,
    store: Store | None = None,
    site: Site = SHFE,
    overwrite: bool = False,
    record_missing: bool = True,
) -> dict[str, str]:
    """把某日各类数据落成 parquet。返回 {kind: 'written'|'exists'|'missing'|'empty'}。
    已存在(且不 overwrite)则跳过;404/空内容不算错误,record_missing 时写入 missing.log。"""
    st = store or Store()
    date = pd.Timestamp(date).normalize()
    status: dict[str, str] = {}
    for kind in kinds:
        if st.has_day(site.exchange, kind, date) and not overwrite:
            status[kind] = "exists"
            continue
        ext = "json"
        raw: bytes | None
        if kind == "quotes":
            raw = fetch_quotes(date, st, site)
        elif kind == "positions":
            raw = fetch_positions(date, st, site)
        else:
            got = fetch_receipts(date, st, site)
            ext, raw = got if got is not None else ("json", None)
        if raw is None:
            status[kind] = "missing"
            if record_missing:
                _log_missing(st, site, date, kind, "404", _url_of(site, kind, date))
            continue
        if kind == "quotes":
            df = parse_quotes(raw, date, site)
        elif kind == "positions":
            df = parse_positions(raw, date, site)
        else:
            df = parse_receipts(raw, date, site, ext)
        if df.empty:
            status[kind] = "empty"
            if record_missing:
                _log_missing(st, site, date, kind, "empty", _url_of(site, kind, date))
            continue
        st.write_day(site.exchange, kind, date, df, overwrite=overwrite)
        status[kind] = "written"
    return status


def backfill(
    start: pd.Timestamp,
    end: pd.Timestamp,
    kinds: Iterable[Kind] = KINDS,
    store: Store | None = None,
    site: Site = SHFE,
    retry_missing: bool = False,
    overwrite: bool = False,
    max_consecutive_errors: int = 10,
) -> dict[str, int]:
    """逐个工作日回填 [start, end]。周末不请求;missing.log 里的 (日期, 类型) 默认跳过(retry_missing 重试);
    已有 parquet 跳过;下载失败(重试耗尽)记入 errors 继续,连续失败 max_consecutive_errors 次则中止。可断点续跑。"""
    st = store or Store()
    kinds = tuple(kinds)
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    today = pd.Timestamp.today().normalize()
    known_missing = set() if retry_missing else load_missing(st, site)
    counts: dict[str, int] = {"written": 0, "exists": 0, "missing": 0, "empty": 0, "error": 0, "skipped": 0}
    consecutive = 0
    days = pd.bdate_range(start, end)
    t0 = time.monotonic()
    for i, d in enumerate(days, 1):
        todo = [k for k in kinds if (f"{d:%Y-%m-%d}", k) not in known_missing]
        counts["skipped"] += len(kinds) - len(todo)
        if not todo:
            continue
        try:
            status = ingest_day(d, todo, st, site, overwrite=overwrite, record_missing=d < today)
        except FetchError as e:
            counts["error"] += 1
            consecutive += 1
            log.error("%s %s: %s", site.exchange, d.date(), e)
            if consecutive >= max_consecutive_errors:
                raise RuntimeError(f"{consecutive} consecutive fetch errors, aborting at {d.date()}") from e
            continue
        except ValueError as e:  # 解析/校验失败:raw 已落盘,记错继续,事后 --overwrite 重解析
            counts["error"] += 1
            log.error("%s %s: parse/validate failed: %s", site.exchange, d.date(), e)
            continue
        consecutive = 0
        for s in status.values():
            counts[s] += 1
        if i % 50 == 0 or i == len(days):
            log.info(
                "%s %s [%d/%d] %s  %.0fs",
                site.exchange,
                d.date(),
                i,
                len(days),
                counts,
                time.monotonic() - t0,
            )
    return counts


def coverage(store: Store | None = None, site: Site = SHFE) -> pd.DataFrame:
    """每类每年的落盘天数(文档"覆盖率"表)。"""
    st = store or Store()
    recs: list[dict[str, Any]] = []
    for kind in KINDS:
        for d in st.days(site.exchange, kind):
            recs.append({"kind": kind, "year": d.year})
    if not recs:
        return pd.DataFrame(columns=["year", *KINDS])
    df = pd.DataFrame(recs)
    df["n"] = 1
    table = df.pivot_table(index="year", columns="kind", values="n", aggfunc="sum", fill_value=0)
    table = table.reindex(columns=list(KINDS), fill_value=0).astype(int)
    return table.reset_index()


# ---------------------------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------------------------


def _parse_kinds(s: str) -> list[Kind]:
    out: list[Kind] = []
    for item in s.split(","):
        k = item.strip()
        if k not in KINDS:
            raise argparse.ArgumentTypeError(f"unknown kind {k!r}; choose from {KINDS}")
        out.append(cast(Kind, k))
    return out


def build_cli(site: Site) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=f"cta.data.exchanges.{site.exchange.lower()}", description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="数据根目录(默认 data/exchanges)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bf = sub.add_parser("backfill", help="逐日回填(可断点续跑)")
    bf.add_argument("--start", required=True)
    bf.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    bf.add_argument("--kinds", type=_parse_kinds, default=list(KINDS))
    bf.add_argument("--retry-missing", action="store_true", help="重试 missing.log 里的日期")
    bf.add_argument("--overwrite", action="store_true", help="从 raw 重新解析并覆盖已有 parquet")
    day = sub.add_parser("day", help="抓取/解析单日")
    day.add_argument("--date", required=True)
    day.add_argument("--kinds", type=_parse_kinds, default=list(KINDS))
    day.add_argument("--overwrite", action="store_true")
    sub.add_parser("coverage", help="每类每年落盘天数")
    return ap


def main(argv: Sequence[str] | None = None, site: Site = SHFE) -> int:
    args = build_cli(site).parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    st = Store(args.root) if args.root else Store()
    if args.cmd == "backfill":
        counts = backfill(
            pd.Timestamp(args.start),
            pd.Timestamp(args.end),
            args.kinds,
            st,
            site,
            retry_missing=args.retry_missing,
            overwrite=args.overwrite,
        )
        print(json.dumps({"exchange": site.exchange, **counts}, ensure_ascii=False))
    elif args.cmd == "day":
        status = ingest_day(pd.Timestamp(args.date), args.kinds, st, site, overwrite=args.overwrite)
        print(json.dumps({"exchange": site.exchange, "date": args.date, **status}, ensure_ascii=False))
    else:
        print(coverage(st, site).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "SHFE",
    "Site",
    "INE_SYMBOLS",
    "SINGLE_SIDED_FROM",
    "TURNOVER_FROM",
    "RECEIPT_HTML_FROM",
    "RECEIPT_DAT_UNTIL",
    "RECEIPT_SYMBOLS",
    "fetch_quotes",
    "fetch_positions",
    "fetch_receipts",
    "parse_quotes",
    "parse_positions",
    "parse_receipts",
    "ingest_day",
    "backfill",
    "coverage",
]
