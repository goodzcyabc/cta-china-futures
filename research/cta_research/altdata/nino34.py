"""来源 E:NOAA CPC 周度 OISST Niño 3.4 海温异常(预注册 docs/research/altdata_prereg.md 第 4 节,试验 53)。

数据文件(均为固定宽度文本,负异常可能与海温粘连,如 "20.6-0.1",因此用正则解析):
- ``wksst8110.for``:冻结版,1981–2010 基期,行 1990-01-03 → 2021-01-27(核验者证实 2014-09 起只追加、无修订);
- ``wksst9120.for``:实时版,1991–2020 基期,1981-09-02 → 现在;2021 年被整体重写两次(基期切换、OISST v2 → v2.1),
  所以 2021-02-03 起的"首次刊出值"只能从 Wayback Machine 的历史快照恢复。

序列构造(预注册第 4 节,不得更改):
- 周 W ≤ 2021-01-27:冻结版 8110 的异常值,原样使用(source_file = "8110";vintage_first_print = False,
  该列只标记"值来自最早 Wayback 快照",冻结文件行由 source_file 区分);
- 周 W ≥ 2021-02-03:取**最早**包含该周的 Wayback 快照里的值(source_file = "wayback:<ts>",vintage_first_print = True);
  没有任何快照包含该周时退回当前实时文件(source_file = "live",vintage_first_print = False);
- 拼接常数 c = 2016-01-06 → 2021-01-27 重叠期内 (实时文件异常 − 冻结文件异常) 的均值;2021-01-27 之后的所有异常值减去 c。
  value = 拼接后的异常;anomaly_raw、sst 为文件原值。

可得规则(预注册第 4 节,核验者给出的生成时间:2013 → 2023 年中 10:56/11:58 UTC,2023-08 起 06:56 UTC,2026 年 07:00:12 UTC,
行在周中周三 W 之后的下周一才出现,周一收盘是竞态):**available_day = W + 7 日**(下周三),与文件时间戳无关。

原始文件落盘 ``<dest>/raw/``:
- ``wksst8110.for`` + ``.meta.json``(HTTP Last-Modified、抓取时间、大小);
- ``live/wksst9120.for.<LastModified-UTC>`` + ``.meta.json``:实时文件每个不同 Last-Modified 存一份,load 用最新一份;
- ``wayback/cdx_wksst9120.txt``:CDX 清单;``wayback/wksst9120.for.<ts>`` + ``.meta.json``(含 x-archive-orig-last-modified);
  ``wayback/skipped.json``:超时/重定向而跳过的快照(重跑时会再试)。
输出 ``observations.csv``(obs_date、available_day、key、value + meta 列)、``vintage_coverage.csv``(2021-02-03 起每周
用的是首印快照还是实时回退)、``splice.json``(c 与重叠期统计)。

本模块不读取任何价格数据,也不计算与收益的关系。
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

log = logging.getLogger(__name__)

KEY = "E-NINO34"
CPC_INDICES = "https://www.cpc.ncep.noaa.gov/data/indices/"
FROZEN_NAME = "wksst8110.for"
LIVE_NAME = "wksst9120.for"
FROZEN_URL = CPC_INDICES + FROZEN_NAME
LIVE_URL = CPC_INDICES + LIVE_NAME
CDX_URL = (
    "https://web.archive.org/cdx/search/cdx?url=www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"
    "&output=txt&fl=timestamp,statuscode,digest,length"
)
WAYBACK_URL = "https://web.archive.org/web/{ts}id_/https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"

FROZEN_END = pd.Timestamp("2021-01-27")  # 冻结文件最后一行;≤ 此周用 8110
SPLICE_START = pd.Timestamp("2021-02-03")  # 此周起用 Wayback 首印 / 实时回退,并减去 c
OVERLAP_START = pd.Timestamp("2016-01-06")  # 拼接常数 c 的重叠期(含两端)
OVERLAP_END = FROZEN_END
AVAIL_LAG_DAYS = 7  # available_day = W + 7(预注册第 4 节,binding)

DEFAULT_START = "2021-01-01"  # Wayback 快照时间戳范围(日历日,含两端);更早的快照不可能含 2021-02-03 之后的周
DEFAULT_END = "2099-12-31"

CPC_MIN_INTERVAL = 1.0  # 秒;同一主机 ≤ 1 请求/秒
WAYBACK_MIN_INTERVAL = 5.0  # 秒;Wayback 要求 ≥ 5 秒间隔
TIMEOUT = 60
RETRIES = 4
USER_AGENT = "cta-china-futures altdata nino34 fetcher (research; python-urllib)"

OBS_COLUMNS = [
    "obs_date",
    "available_day",
    "key",
    "value",
    "sst",
    "anomaly_raw",
    "source_file",
    "vintage_first_print",
    "last_modified_utc",
    "vintage_ts",
    "vintage_lag_days",
    "splice_offset",
]

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
# 行格式:" 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3";8 个数(SST、SSTA × 4 区),负号可与前一个数粘连。
_ROW_RE = re.compile(r"^\s*(\d{2})([A-Z]{3})(\d{4})" + r"\s*(-?\d+\.\d+)" * 8 + r"\s*$")
_HEADER_MARK = "Weekly SST data"
_WEEK_COLS = [
    "nino12_sst",
    "nino12_anom",
    "nino3_sst",
    "nino3_anom",
    "nino34_sst",
    "nino34_anom",
    "nino4_sst",
    "nino4_anom",
]


class FetchError(RuntimeError):
    """下载失败(重试用尽)。"""


class RedirectError(FetchError):
    """快照返回重定向(Wayback 没有该时间戳的精确内容),按规则跳过。"""


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


def parse_wksst(text: str) -> pd.DataFrame:
    """解析 CPC 周度文件。返回列 week(datetime64,周中周三)+ 8 个数值列;无数据行返回空表。

    用正则而不是空白切分:负异常会与海温粘连("20.6-0.1")。重复周视为文件损坏,抛 ValueError。
    """
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m is None:
            continue
        mon = _MONTHS.get(m.group(2))
        if mon is None:
            raise ValueError(f"unknown month in row: {line!r}")
        week = pd.Timestamp(year=int(m.group(3)), month=mon, day=int(m.group(1)))
        rec: dict[str, Any] = {"week": week}
        for name, val in zip(_WEEK_COLS, m.groups()[3:]):
            rec[name] = float(val)
        rows.append(rec)
    if not rows:
        return pd.DataFrame(columns=["week", *_WEEK_COLS])
    df = pd.DataFrame(rows)
    if df["week"].duplicated().any():
        dup = df.loc[df["week"].duplicated(), "week"].iloc[0]
        raise ValueError(f"duplicate week {pd.Timestamp(dup).date()} in wksst file")
    return df.sort_values("week").reset_index(drop=True)


def is_wksst_file(text: str) -> bool:
    """快照是否为真正的数据文件(而不是 HTML 错误页等)。"""
    return _HEADER_MARK in text[:400] and any(_ROW_RE.match(line) for line in text.splitlines())


def _nino34_map(df: pd.DataFrame) -> dict[pd.Timestamp, tuple[float, float]]:
    out: dict[pd.Timestamp, tuple[float, float]] = {}
    for week, sst, anom in zip(df["week"], df["nino34_sst"], df["nino34_anom"]):
        out[pd.Timestamp(week)] = (float(sst), float(anom))
    return out


# ---------------------------------------------------------------------------------------------
# 可得规则 / 拼接(纯函数,便于测试)
# ---------------------------------------------------------------------------------------------


def available_day(obs_date: pd.Timestamp) -> pd.Timestamp:
    """预注册第 4 节:行日期 W(周中周三)→ 可得日 W + 7 日。文件时间戳不参与计算(只能更晚,不能更早)。"""
    return pd.Timestamp(obs_date).normalize() + pd.Timedelta(days=AVAIL_LAG_DAYS)


def splice_offset(frozen: pd.DataFrame, live: pd.DataFrame) -> tuple[float, int, float]:
    """c = 重叠期 2016-01-06 → 2021-01-27(含)内 (实时异常 − 冻结异常) 的均值。返回 (c, n, 差的标准差)。"""
    f = _nino34_map(frozen)
    lv = _nino34_map(live)
    diffs = [lv[w][1] - f[w][1] for w in sorted(f) if OVERLAP_START <= w <= OVERLAP_END and w in lv]
    if not diffs:
        raise ValueError("no overlapping weeks between frozen and live files; cannot compute splice offset")
    s = pd.Series(diffs, dtype=float)
    return float(s.mean()), int(len(diffs)), float(s.std(ddof=0))


@dataclass(frozen=True)
class Vintage:
    """一个 Wayback 快照(或实时快照)的解析结果。"""

    ts: str  # Wayback 时间戳 YYYYMMDDhhmmss,或实时快照的 Last-Modified 紧凑形式
    last_modified_utc: str  # 原始服务器 Last-Modified(ISO,UTC);缺失为 ""
    capture_utc: pd.Timestamp  # 快照抓取时刻(UTC,naive)
    data: dict[pd.Timestamp, tuple[float, float]]


def build_observations(
    frozen: pd.DataFrame,
    frozen_last_modified_utc: str,
    live: Vintage,
    vintages: list[Vintage],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """按预注册第 4 节构造观测表。返回 (observations, vintage_coverage, splice_info)。

    - W ≤ 2021-01-27:冻结文件,value = anomaly_raw;
    - W ≥ 2021-02-03:最早包含 W 的快照(按 ts 排序),否则实时文件;value = anomaly_raw − c;
    - available_day = W + 7。
    """
    c, n_overlap, sd = splice_offset(
        frozen,
        pd.DataFrame(
            [{"week": w, "nino34_sst": v[0], "nino34_anom": v[1]} for w, v in sorted(live.data.items())],
            columns=["week", "nino34_sst", "nino34_anom"],
        ),
    )
    c_round = round(c, 6)
    vintages_sorted = sorted(vintages, key=lambda v: v.ts)

    recs: list[dict[str, Any]] = []
    for w, (sst, anom) in sorted(_nino34_map(frozen).items()):
        if w > FROZEN_END:
            continue
        recs.append(
            {
                "obs_date": w,
                "available_day": available_day(w),
                "key": KEY,
                "value": round(anom, 6) + 0.0,  # + 0.0:把文件里的 "-0.0" 规范为 0.0
                "sst": sst,
                "anomaly_raw": anom,
                "source_file": "8110",
                "vintage_first_print": False,
                "last_modified_utc": frozen_last_modified_utc,
                "vintage_ts": "",
                "vintage_lag_days": float("nan"),
                "splice_offset": 0.0,
            }
        )

    post_weeks: set[pd.Timestamp] = {w for w in live.data if w >= SPLICE_START}
    for v in vintages_sorted:
        post_weeks.update(w for w in v.data if w >= SPLICE_START)

    cov: list[dict[str, Any]] = []
    for w in sorted(post_weeks):
        first: Vintage | None = None
        n_containing = 0
        for v in vintages_sorted:
            if w in v.data:
                n_containing += 1
                if first is None:
                    first = v
        if first is not None:
            sst, anom = first.data[w]
            source = f"wayback:{first.ts}"
            lm = first.last_modified_utc
            ts = first.ts
            lag = float((first.capture_utc.normalize() - w).days)
            first_print = True
        else:
            sst, anom = live.data[w]
            source = "live"
            lm = live.last_modified_utc
            ts = live.ts
            lag = float((live.capture_utc.normalize() - w).days)
            first_print = False
        recs.append(
            {
                "obs_date": w,
                "available_day": available_day(w),
                "key": KEY,
                "value": round(anom - c_round, 6) + 0.0,
                "sst": sst,
                "anomaly_raw": anom,
                "source_file": source,
                "vintage_first_print": first_print,
                "last_modified_utc": lm,
                "vintage_ts": ts,
                "vintage_lag_days": lag,
                "splice_offset": c_round,
            }
        )
        cov.append(
            {
                "obs_date": w,
                "available_day": available_day(w),
                "source_file": source,
                "vintage_first_print": first_print,
                "vintage_ts": ts,
                "last_modified_utc": lm,
                "vintage_lag_days": lag,
                "n_vintages_containing": n_containing,
                "in_live": w in live.data,
            }
        )

    obs = pd.DataFrame(recs, columns=OBS_COLUMNS)
    obs = obs.sort_values(["key", "obs_date"]).reset_index(drop=True)
    if obs.duplicated(["key", "obs_date"]).any():
        raise ValueError("duplicate (key, obs_date) in observations")
    coverage = (
        pd.DataFrame(
            cov,
            columns=[
                "obs_date",
                "available_day",
                "source_file",
                "vintage_first_print",
                "vintage_ts",
                "last_modified_utc",
                "vintage_lag_days",
                "n_vintages_containing",
                "in_live",
            ],
        )
        .sort_values("obs_date")
        .reset_index(drop=True)
    )
    info: dict[str, Any] = {
        "splice_offset_c": c_round,
        "splice_offset_c_full": c,
        "n_overlap_weeks": n_overlap,
        "overlap_diff_std": round(sd, 6),
        "overlap_start": str(OVERLAP_START.date()),
        "overlap_end": str(OVERLAP_END.date()),
        "frozen_last_modified_utc": frozen_last_modified_utc,
        "live_snapshot": live.ts,
        "live_last_modified_utc": live.last_modified_utc,
        "n_wayback_vintages": len(vintages_sorted),
        "n_post_weeks": len(cov),
        "n_first_print": int(sum(1 for r in cov if r["vintage_first_print"])),
        "n_live_fallback": int(sum(1 for r in cov if not r["vintage_first_print"])),
    }
    return obs, coverage, info


# ---------------------------------------------------------------------------------------------
# HTTP(限速 + 退避)
# ---------------------------------------------------------------------------------------------

_LAST_REQUEST: dict[str, float] = {}


def _throttle(host: str, min_interval: float) -> None:
    last = _LAST_REQUEST.get(host)
    if last is not None:
        wait = min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _LAST_REQUEST[host] = time.monotonic()


def _min_interval(url: str) -> float:
    return WAYBACK_MIN_INTERVAL if "web.archive.org" in url else CPC_MIN_INTERVAL


@dataclass(frozen=True)
class Response:
    """一次成功(200)的 HTTP 响应:正文(已解 gzip)+ 头(键小写)。"""

    status: int
    content: bytes
    headers: dict[str, str]

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随重定向:Wayback 没有该时间戳的精确内容时会 302 到邻近快照,按规则跳过。"""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect())


def _open_once(url: str, method: str, timeout: int) -> Response:
    req = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Encoding": "identity"}
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        body: bytes = resp.read() if method != "HEAD" else b""
        headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}
        status = int(resp.status)
    if body[:2] == b"\x1f\x8b" or headers.get("content-encoding", "").lower() == "gzip":
        with contextlib.suppress(OSError, EOFError):
            body = gzip.decompress(body)
    return Response(status=status, content=body, headers=headers)


def _request(url: str, *, method: str = "GET", retries: int = RETRIES, timeout: int = TIMEOUT) -> Response:
    """限速 GET/HEAD;429/5xx/超时指数退避(429 至少等 20 秒);3xx 抛 RedirectError;其他 4xx 抛 FetchError。"""
    host = urlsplit(url).netloc
    delay = 5.0
    last_err = ""
    for attempt in range(retries + 1):
        _throttle(host, _min_interval(url))
        try:
            resp = _open_once(url, method, timeout)
        except urllib.error.HTTPError as e:
            code = int(e.code)
            last_err = f"HTTP {code}"
            if 300 <= code < 400:
                raise RedirectError(f"{url}: HTTP {code} -> {e.headers.get('Location', '')}") from e
            if code == 429:
                retry_after = str(e.headers.get("Retry-After", "") or "")
                delay = max(delay, float(retry_after) if retry_after.isdigit() else 30.0, 20.0)
            elif code < 500:
                raise FetchError(f"{url}: {last_err}") from e
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            last_err = f"{type(e).__name__}: {e}"
        else:
            if resp.status == 200:
                return resp
            last_err = f"HTTP {resp.status}"
        if attempt < retries:
            wait = min(delay, 60.0)
            log.warning(
                "%s %s failed (%s); retry %d/%d in %.0fs", method, url, last_err, attempt + 1, retries, wait
            )
            time.sleep(wait)
            delay *= 2
    raise FetchError(f"{url}: {last_err}")


def _http_date_to_iso(value: str) -> str:
    """HTTP 日期(RFC 2822)→ ISO 8601 UTC(如 2026-10-02T07:00:12Z);空或无法解析返回 ""。"""
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_raw(path: Path, content: bytes, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)
    meta = dict(meta)
    meta["size"] = len(content)
    meta["sha256"] = hashlib.sha256(content).hexdigest()
    _meta_path(path).write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _read_meta(path: Path) -> dict[str, Any] | None:
    mp = _meta_path(path)
    if not path.exists() or not mp.exists():
        return None
    try:
        meta = json.loads(mp.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(meta, dict):
        return None
    return meta


def _is_complete(path: Path, expected_size: int | None = None) -> bool:
    """文件存在、meta 存在且 meta 记录的大小与磁盘一致(可选:与服务器 Content-Length 一致)。"""
    meta = _read_meta(path)
    if meta is None:
        return False
    size = path.stat().st_size
    if int(meta.get("size", -1)) != size:
        return False
    return expected_size is None or expected_size == size


# ---------------------------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------------------------


def _compact_ts(iso_utc: str) -> str:
    """2026-10-02T07:00:12Z → 20261002T070012Z(文件名用)。"""
    return iso_utc.replace("-", "").replace(":", "")


def _fetch_cpc_file(url: str, dest_dir: Path, *, versioned: bool) -> Path:
    """下载 CPC 文件。versioned=True 时按 Last-Modified 存一份(实时文件),否则存固定名(冻结文件)。

    先 HEAD 取 Last-Modified / Content-Length;本地已有同版本且大小一致则跳过 GET。
    """
    name = url.rsplit("/", 1)[-1]
    head = _request(url, method="HEAD")
    lm_iso = _http_date_to_iso(head.header("Last-Modified"))
    clen = head.header("Content-Length")
    expected = int(clen) if clen.isdigit() else None
    if versioned:
        if not lm_iso:
            raise FetchError(f"{url}: no Last-Modified header; cannot version the live file")
        path = dest_dir / "live" / f"{name}.{_compact_ts(lm_iso)}"
    else:
        path = dest_dir / name
    if _is_complete(path, expected):
        log.info("skip %s (present, %d bytes)", path.name, path.stat().st_size)
        return path
    resp = _request(url)
    content = resp.content
    lm_get = _http_date_to_iso(resp.header("Last-Modified"))
    if versioned and lm_get and lm_get != lm_iso:
        # HEAD 与 GET 之间文件被重新生成:以 GET 的版本为准
        lm_iso = lm_get
        path = dest_dir / "live" / f"{name}.{_compact_ts(lm_iso)}"
    if not is_wksst_file(resp.text):
        raise FetchError(f"{url}: response is not a wksst data file")
    _write_raw(
        path,
        content,
        {
            "url": url,
            "last_modified_http": resp.header("Last-Modified"),
            "last_modified_utc": lm_iso or lm_get,
            "fetched_at_utc": _now_iso(),
            "date_http": resp.header("Date"),
        },
    )
    log.info("saved %s (%d bytes, Last-Modified %s)", path.name, len(content), lm_iso)
    return path


def _parse_cdx(text: str) -> list[tuple[str, str, str, str]]:
    """CDX 文本 → [(timestamp, statuscode, digest, length)]。"""
    out: list[tuple[str, str, str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or not re.fullmatch(r"\d{14}", parts[0]):
            continue
        out.append((parts[0], parts[1], parts[2], parts[3]))
    return out


def _fetch_wayback(dest_dir: Path, start: str, end: str) -> None:
    """列出 CDX 并抓取 [start, end] 内每个 200 快照;超时/重定向跳过并记录到 skipped.json(重跑再试)。"""
    wb_dir = dest_dir / "wayback"
    wb_dir.mkdir(parents=True, exist_ok=True)
    cdx_resp = _request(CDX_URL)
    cdx_text = cdx_resp.text
    (wb_dir / "cdx_wksst9120.txt").write_text(cdx_text, encoding="utf-8")
    captures = _parse_cdx(cdx_text)
    lo = pd.Timestamp(start).strftime("%Y%m%d") + "000000"
    hi = pd.Timestamp(end).strftime("%Y%m%d") + "235959"
    todo = [c for c in captures if c[1] == "200" and lo <= c[0] <= hi]
    log.info("CDX: %d captures, %d with status 200 in [%s, %s]", len(captures), len(todo), start, end)
    skipped: dict[str, str] = {}
    skipped_path = wb_dir / "skipped.json"
    n_new = 0
    for ts, _status, digest, length in todo:
        path = wb_dir / f"{LIVE_NAME}.{ts}"
        if _is_complete(path):
            continue
        url = WAYBACK_URL.format(ts=ts)
        try:
            resp = _request(url)
        except RedirectError as e:
            log.warning("skip capture %s: redirect (%s)", ts, e)
            skipped[ts] = f"redirect: {e}"
            continue
        except FetchError as e:
            log.warning("skip capture %s: %s", ts, e)
            skipped[ts] = str(e)
            continue
        content = resp.content
        if not is_wksst_file(resp.text):
            log.warning("skip capture %s: not a wksst data file (%d bytes)", ts, len(content))
            skipped[ts] = "not a wksst data file"
            continue
        orig_lm = resp.header("x-archive-orig-last-modified")
        _write_raw(
            path,
            content,
            {
                "url": url,
                "timestamp": ts,
                "cdx_digest": digest,
                "cdx_length": length,
                "x_archive_orig_last_modified": orig_lm,
                "last_modified_utc": _http_date_to_iso(orig_lm),
                "x_archive_orig_date": resp.header("x-archive-orig-date"),
                "memento_datetime": resp.header("memento-datetime"),
                "fetched_at_utc": _now_iso(),
            },
        )
        n_new += 1
        log.info("saved capture %s (%d bytes, orig Last-Modified %s)", ts, len(content), orig_lm)
    skipped_path.write_text(json.dumps(skipped, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log.info("wayback: %d new captures saved, %d skipped", n_new, len(skipped))


def fetch(dest: Path, start: str = DEFAULT_START, end: str = DEFAULT_END) -> None:
    """抓取冻结文件、实时文件(按 Last-Modified 版本化)与 [start, end] 内的全部 Wayback 快照。幂等、可续传。"""
    dest = Path(dest)
    raw = dest / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    _fetch_cpc_file(FROZEN_URL, raw, versioned=False)
    _fetch_cpc_file(LIVE_URL, raw, versioned=True)
    _fetch_wayback(raw, start, end)


# ---------------------------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


def _wayback_ts_to_utc(ts: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.strptime(ts, "%Y%m%d%H%M%S"))


def load_frozen(dest: Path) -> tuple[pd.DataFrame, str]:
    """冻结文件 → (解析表, Last-Modified ISO UTC)。"""
    path = Path(dest) / "raw" / FROZEN_NAME
    if not path.exists():
        raise FileNotFoundError(path)
    meta = _read_meta(path) or {}
    df = parse_wksst(_read_text(path))
    if df.empty:
        raise ValueError(f"{path}: no data rows")
    return df, str(meta.get("last_modified_utc", ""))


def load_live(dest: Path) -> Vintage:
    """最新的实时快照(按 Last-Modified 最大者)。"""
    live_dir = Path(dest) / "raw" / "live"
    cands = sorted(p for p in live_dir.glob(f"{LIVE_NAME}.*") if not p.name.endswith((".meta.json", ".tmp")))
    if not cands:
        raise FileNotFoundError(f"no live snapshot under {live_dir}")
    path = cands[-1]
    meta = _read_meta(path) or {}
    df = parse_wksst(_read_text(path))
    if df.empty:
        raise ValueError(f"{path}: no data rows")
    lm = str(meta.get("last_modified_utc", ""))
    capture = pd.Timestamp(lm.rstrip("Z")) if lm else pd.Timestamp(datetime.now(UTC).replace(tzinfo=None))
    return Vintage(
        ts=path.name.split(".")[-1], last_modified_utc=lm, capture_utc=capture, data=_nino34_map(df)
    )


def load_vintages(dest: Path) -> list[Vintage]:
    """全部 Wayback 快照(按时间戳排序);解析不出数据行的快照忽略(并记日志)。"""
    wb_dir = Path(dest) / "raw" / "wayback"
    out: list[Vintage] = []
    if not wb_dir.exists():
        return out
    for path in sorted(wb_dir.glob(f"{LIVE_NAME}.*")):
        if path.name.endswith((".meta.json", ".tmp")):
            continue
        ts = path.name.split(".")[-1]
        if not re.fullmatch(r"\d{14}", ts):
            continue
        text = _read_text(path)
        if not is_wksst_file(text):
            log.warning("ignore capture %s: not a wksst data file", ts)
            continue
        df = parse_wksst(text)
        if df.empty:
            continue
        meta = _read_meta(path) or {}
        out.append(
            Vintage(
                ts=ts,
                last_modified_utc=str(meta.get("last_modified_utc", "")),
                capture_utc=_wayback_ts_to_utc(ts),
                data=_nino34_map(df),
            )
        )
    return out


def load_all(dest: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """从 raw 重建 (observations, vintage_coverage, splice_info)。"""
    frozen, frozen_lm = load_frozen(dest)
    live = load_live(dest)
    vintages = load_vintages(dest)
    return build_observations(frozen, frozen_lm, live, vintages)


def load(dest: Path) -> pd.DataFrame:
    """观测表(obs_date、available_day、key、value + meta),从 raw 文件重算 available_day 与拼接。"""
    obs, _cov, _info = load_all(dest)
    return obs


def vintage_revisions(vintages: list[Vintage]) -> pd.DataFrame:
    """相邻快照之间重叠周的 Niño 3.4 异常值改动统计(诊断用,不参与序列构造)。

    文件在同一数据版本内只追加(改动应为 0 或只涉及最近 1–4 周 ±0.1);整体重写(2021 年基期切换、OISSTv2 → v2.1)
    会表现为大量重叠周改动。每行:后一快照 ts、前一快照 ts、重叠周数、改动周数、最大绝对改动、最早改动周。
    """
    rows: list[dict[str, Any]] = []
    vs = sorted(vintages, key=lambda v: v.ts)
    for prev, cur in zip(vs[:-1], vs[1:]):
        common = sorted(set(prev.data) & set(cur.data))
        changed = [w for w in common if abs(cur.data[w][1] - prev.data[w][1]) > 1e-9]
        max_abs = max((abs(cur.data[w][1] - prev.data[w][1]) for w in changed), default=0.0)
        rows.append(
            {
                "vintage_ts": cur.ts,
                "prev_vintage_ts": prev.ts,
                "n_overlap": len(common),
                "n_changed": len(changed),
                "max_abs_change": round(max_abs, 3),
                "first_changed_week": str(changed[0].date()) if changed else "",
                "last_changed_week": str(changed[-1].date()) if changed else "",
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "vintage_ts",
            "prev_vintage_ts",
            "n_overlap",
            "n_changed",
            "max_abs_change",
            "first_changed_week",
            "last_changed_week",
        ],
    )


def write_outputs(dest: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """写 observations.csv、vintage_coverage.csv、vintage_revisions.csv、splice.json。"""
    dest = Path(dest)
    obs, cov, info = load_all(dest)
    vintage_revisions(load_vintages(dest)).to_csv(dest / "vintage_revisions.csv", index=False)
    out = obs.copy()
    out["obs_date"] = pd.to_datetime(out["obs_date"]).dt.strftime("%Y-%m-%d")
    out["available_day"] = pd.to_datetime(out["available_day"]).dt.strftime("%Y-%m-%d")
    out.to_csv(dest / "observations.csv", index=False)
    cov_out = cov.copy()
    cov_out["obs_date"] = pd.to_datetime(cov_out["obs_date"]).dt.strftime("%Y-%m-%d")
    cov_out["available_day"] = pd.to_datetime(cov_out["available_day"]).dt.strftime("%Y-%m-%d")
    cov_out.to_csv(dest / "vintage_coverage.csv", index=False)
    (dest / "splice.json").write_text(json.dumps(info, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return obs, cov, info


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="NOAA CPC weekly Nino 3.4 (source E): fetch raw files and write observations.csv"
    )
    ap.add_argument("--dest", type=Path, required=True, help="data/external/alt/nino34")
    ap.add_argument("--start", default=DEFAULT_START, help="first Wayback capture day (YYYY-MM-DD)")
    ap.add_argument("--end", default=DEFAULT_END, help="last Wayback capture day (YYYY-MM-DD)")
    ap.add_argument("--no-fetch", action="store_true", help="only rebuild observations.csv from raw/")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dest = Path(args.dest)
    if not args.no_fetch:
        fetch(dest, start=str(args.start), end=str(args.end))
    obs, cov, info = write_outputs(dest)
    first = pd.Timestamp(obs["obs_date"].min()).date()
    last = pd.Timestamp(obs["obs_date"].max()).date()
    print(
        f"{KEY}: {len(obs)} weeks {first} -> {last}; splice c = {info['splice_offset_c']} "
        f"(n = {info['n_overlap_weeks']}); post-2021 weeks {info['n_post_weeks']}: "
        f"{info['n_first_print']} first-print, {info['n_live_fallback']} live fallback"
    )


if __name__ == "__main__":
    main()
