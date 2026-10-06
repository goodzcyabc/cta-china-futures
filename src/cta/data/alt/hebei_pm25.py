"""候选 Q(试验 56):河北四钢城(唐山、邯郸、石家庄、邢台)PM2.5 日均 —— 限产代理。预注册 docs/research/altdata_prereg.md 第 7 节。

数据:中国环境监测总站实时城市小时数据的第三方逐日存档
    https://quotsoft.net/air/data/china_cities_YYYYMMDD.csv
每个文件 = 一个北京日历日,行 = 小时 × 指标(type 列:AQI、PM2.5、PM10、…),列 = date, hour, type, 然后每城一列。
列顺序与列数在 2021 年变过(370 → 378 列),所以**只按城市名匹配列**。变量只取 type == "PM2.5"(小时浓度,ug/m3),不用 AQI。
2018-09-01 起气态污染物(SO2/NO2/CO/O3)改为参比状态口径,PM2.5 的"实况"口径不受影响(核验者结论),本模块不做任何拼接处理。

特征(本模块只到日值;7 日均值与 z 在 cta.analysis.altdata_signals):
    城市日值 = 该北京日历日可用小时 PM2.5 的均值;可用小时 < 8 → 该城该日缺失(不写行)。
    四城均值 = 当日有值城市的日值均值(缺失城市剔除;四城全缺 → 该日缺失)。
可得规则(绑定):日 D 的小时值在 D+1 的 00:23–00:53 北京前写完,**available_day = D + 1 日历日**;不用当日小时值。

落盘:dest/raw/china_cities_YYYYMMDD.csv(原始文件,永不覆盖除非远端变化)+ 同名 .meta.json(HTTP 状态、
Last-Modified(UTC)、Content-Length、ETag、抓取时刻),404 只写 .meta.json(永久空洞)。
dest/observations.csv:obs_date, available_day, key, value, n_hours, n_cities, last_modified_utc, file_size, fetched_at_utc;
键 Q-HEBEI4(四城均值)与 Q-唐山 / Q-邯郸 / Q-石家庄 / Q-邢台;按 key、obs_date 排序;缺失 = 没有行。
dest/files.csv:每个日期的文件状态(present / missing / partial(< 150 KB)、列数、小时数、四城是否齐)。

礼貌抓取:单一私人服务器,每秒最多 1 个请求;失败按 5/20/60 s 退避重试;连续 5 个日期失败即停止(可续传)。

用法:
    PYTHONPATH=src python3 -m cta.data.alt.hebei_pm25 --dest data/external/alt/hebei_pm25
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import logging
import math
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# 常量(全部来自预注册第 7 节;不要改)
# ---------------------------------------------------------------------------------------------

SOURCE_URL = "https://quotsoft.net/air/data/china_cities_{ymd}.csv"
CITIES: tuple[str, ...] = ("唐山", "邯郸", "石家庄", "邢台")
KEY_MEAN = "Q-HEBEI4"
KEY_PREFIX = "Q-"
VARIABLE = "PM2.5"
MIN_HOURS = (
    17  # 城市日值至少需要的可用小时数:预注册第 7 节"缺少 ≥ 8 小时的日 → NaN",即 24 − 8 + 1 = 17 个可用小时
)
AVAILABILITY_LAG_DAYS = 1  # available_day = obs_date + 1 日历日
DEFAULT_START = "2015-01-01"
PARTIAL_BYTES = 150_000  # 小于此大小的文件记为 partial(通常只有部分小时)
BEIJING_TZ = "Asia/Shanghai"

USER_AGENT = "cta-china-futures-altdata/0.1 (research; python-urllib)"
MIN_INTERVAL = 1.0  # 秒,对该主机两次请求的最小间隔
TIMEOUT = 120.0  # 秒
RETRY_BACKOFF = (5.0, 20.0, 60.0)  # 秒;重试次数 = len(RETRY_BACKOFF)
MAX_CONSECUTIVE_FAILURES = 5  # 连续这么多个日期拿不到(非 404)就礼貌停止
RECHECK_DAYS = 3  # 距 end 不超过这些天的文件每次运行都用条件请求复核(当天文件会被逐小时追加)
FINAL_HOUR_BEIJING = 1  # D 的文件在 D+1 01:00 北京之后视为写完(核验者:00:23–00:53)

OBS_COLUMNS: tuple[str, ...] = (
    "obs_date",
    "available_day",
    "key",
    "value",
    "n_hours",
    "n_cities",
    "last_modified_utc",
    "file_size",
    "fetched_at_utc",
)
FILE_COLUMNS: tuple[str, ...] = (
    "obs_date",
    "status",
    "file_size",
    "last_modified_utc",
    "fetched_at_utc",
    "n_cols",
    "n_rows",
    "n_hours_pm25",
    "cities_found",
    "header_sig",
    "n_rows_other_date",
    "n_dup_rows",
)


# ---------------------------------------------------------------------------------------------
# 路径与元数据
# ---------------------------------------------------------------------------------------------


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def raw_dir(dest: Path) -> Path:
    return dest / "raw"


def csv_path(dest: Path, day: date) -> Path:
    return raw_dir(dest) / f"china_cities_{_ymd(day)}.csv"


def meta_path(dest: Path, day: date) -> Path:
    return raw_dir(dest) / f"china_cities_{_ymd(day)}.meta.json"


def _read_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    return {str(k): v for k, v in obj.items()}


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_date_to_iso(value: str | None) -> str | None:
    """HTTP Last-Modified(RFC 1123)→ 'YYYY-MM-DDTHH:MM:SSZ'(UTC);解析失败 → None。"""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def beijing_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz=BEIJING_TZ)


def default_end(now: pd.Timestamp | None = None) -> str:
    """默认抓到的最后一天:最近一个其文件已写完的北京日(now ≥ D+1 01:00 北京)。"""
    ts = beijing_now() if now is None else now.tz_convert(BEIJING_TZ)
    last = (ts - pd.Timedelta(hours=FINAL_HOUR_BEIJING)).normalize() - pd.Timedelta(days=1)
    return str(last.date())


# ---------------------------------------------------------------------------------------------
# 可得规则
# ---------------------------------------------------------------------------------------------


def available_day(obs_date: date) -> date:
    """绑定规则:日 D 的值在 D+1 日历日可得(存档对 D 的最后一次写入在 D+1 00:23–00:53 北京)。"""
    return obs_date + timedelta(days=AVAILABILITY_LAG_DAYS)


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedFile:
    """一个 china_cities 文件里与本候选有关的内容。"""

    obs_date: date
    n_cols: int
    n_rows: int
    header: tuple[str, ...]  # 去掉 date/hour/type 之后的城市列名,按文件顺序
    cities_found: tuple[str, ...]
    hours_pm25: tuple[int, ...]  # 该日有 PM2.5 行的小时(0–23)
    city_hours: dict[str, dict[int, float]]  # 城市 → 小时 → 浓度(只含可解析的数值)
    n_rows_other_date: int  # date 列 ≠ 文件日期的行数(被忽略)
    n_dup_rows: int  # 同一 (hour, type) 的重复行数(只保留首次出现)


def _to_float(cell: str) -> float | None:
    s = cell.strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def parse_file(raw: bytes, obs_date: date) -> ParsedFile:
    """解析一个 china_cities_YYYYMMDD.csv(UTF-8,可带 BOM)。按城市名找列;只取 date == 文件日期、type == PM2.5 的行。"""
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return ParsedFile(obs_date, 0, 0, (), (), (), {c: {} for c in CITIES}, 0, 0)
    header = [h.strip() for h in header]
    col_index: dict[str, int] = {}
    for city in CITIES:
        if city in header:
            col_index[city] = header.index(city)
    ymd = _ymd(obs_date)
    city_hours: dict[str, dict[int, float]] = {c: {} for c in CITIES}
    seen: set[tuple[int, str]] = set()
    hours: set[int] = set()
    n_rows = 0
    n_other = 0
    n_dup = 0
    for row in reader:
        if len(row) < 3:
            continue
        n_rows += 1
        if row[0].strip() != ymd:
            n_other += 1
            continue
        kind = row[2].strip()
        try:
            hour = int(row[1].strip())
        except ValueError:
            continue
        key = (hour, kind)
        if key in seen:
            n_dup += 1
            continue
        seen.add(key)
        if kind != VARIABLE or hour < 0 or hour > 23:
            continue
        hours.add(hour)
        for city, idx in col_index.items():
            if idx < len(row):
                v = _to_float(row[idx])
                if v is not None:
                    city_hours[city][hour] = v
    return ParsedFile(
        obs_date=obs_date,
        n_cols=len(header),
        n_rows=n_rows,
        header=tuple(header[3:]),
        cities_found=tuple(c for c in CITIES if c in col_index),
        hours_pm25=tuple(sorted(hours)),
        city_hours=city_hours,
        n_rows_other_date=n_other,
        n_dup_rows=n_dup,
    )


def header_signature(header: tuple[str, ...]) -> str:
    """城市列名序列的短指纹(列数 + 哈希),用于在 files.csv 里看出列重排/改名发生在哪一天。"""
    digest = hashlib.md5("\x1f".join(header).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
    return f"{len(header)}:{digest}"


def header_changes(dest: Path, files: pd.DataFrame) -> list[dict[str, Any]]:
    """files 表里 header_sig 每次变化的首个日期,以及相对上一种表头新增/删除/重排的列(只重读变化点的文件)。"""
    sig = files.loc[files["header_sig"].notna(), ["obs_date", "header_sig"]]
    change_points = sig[sig["header_sig"].ne(sig["header_sig"].shift())]
    out: list[dict[str, Any]] = []
    prev: tuple[str, ...] = ()
    for r in change_points.itertuples(index=False):
        day = _parse_day(str(r.obs_date))
        path = csv_path(dest, day)
        if not path.exists():
            continue
        header = parse_file(path.read_bytes(), day).header
        added = [c for c in header if c not in prev]
        removed = [c for c in prev if c not in header]
        reordered = bool(prev) and not added and not removed and header != prev
        out.append(
            {
                "obs_date": str(day),
                "n_cols": len(header),
                "added": added,
                "removed": removed,
                "reordered": reordered,
                "cities_found": [c for c in CITIES if c in header],
            }
        )
        prev = header
    return out


def daily_values(parsed: ParsedFile) -> dict[str, tuple[float, int]]:
    """城市日值:可用小时均值与小时数;可用小时 < MIN_HOURS 的城市不出现在结果里。"""
    out: dict[str, tuple[float, int]] = {}
    for city in CITIES:
        vals = parsed.city_hours.get(city, {})
        n = len(vals)
        if n >= MIN_HOURS:
            out[city] = (float(sum(vals.values())) / n, n)
    return out


def observation_rows(parsed: ParsedFile, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """一个文件 → observations 行(城市行 + 四城均值行);缺失不写行。"""
    per_city = daily_values(parsed)
    obs = str(parsed.obs_date)
    avail = str(available_day(parsed.obs_date))
    common = {
        "obs_date": obs,
        "available_day": avail,
        "last_modified_utc": meta.get("last_modified_utc"),
        "file_size": meta.get("file_size"),
        "fetched_at_utc": meta.get("fetched_at_utc"),
    }
    rows: list[dict[str, Any]] = []
    for city in CITIES:
        if city in per_city:
            value, n_hours = per_city[city]
            rows.append(
                {**common, "key": KEY_PREFIX + city, "value": value, "n_hours": n_hours, "n_cities": None}
            )
    if per_city:
        mean = float(sum(v for v, _ in per_city.values())) / len(per_city)
        rows.append({**common, "key": KEY_MEAN, "value": mean, "n_hours": None, "n_cities": len(per_city)})
    return rows


# ---------------------------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------------------------


class _Throttle:
    """对单一主机的最小请求间隔。"""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last = time.monotonic()


class FetchError(RuntimeError):
    """重试用尽后仍拿不到文件。"""


@dataclass(frozen=True)
class _Response:
    status: int
    content: bytes
    last_modified: str | None
    etag: str | None
    content_length: int | None


def _request(url: str, throttle: _Throttle, etag: str | None = None) -> _Response:
    """GET(可带 If-None-Match);404/304 直接返回;连接错误、5xx、429 按退避重试;校验 Content-Length。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if etag:
        headers["If-None-Match"] = etag
    last_err: str | None = None
    for attempt in range(len(RETRY_BACKOFF) + 1):
        if attempt:
            wait = RETRY_BACKOFF[attempt - 1]
            log.warning("retry %d for %s after %.0fs (%s)", attempt, url, wait, last_err)
            time.sleep(wait)
        throttle.wait()
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                status = int(resp.status)
                body = resp.read()
                last_modified = resp.headers.get("Last-Modified")
                etag_out = resp.headers.get("ETag")
                cl_text = resp.headers.get("Content-Length")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            if status in (404, 304):
                return _Response(status, b"", None, None, None)
            if status == 429 or status >= 500:
                last_err = f"HTTP {status}"
                continue
            raise FetchError(f"HTTP {status} for {url}") from exc
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            socket.timeout,
            OSError,
        ) as exc:  # 连接/超时
            last_err = f"{type(exc).__name__}: {exc}"
            continue
        if status == 304:
            return _Response(304, b"", None, None, None)
        if status != 200:
            last_err = f"HTTP {status}"
            continue
        cl = int(cl_text) if cl_text and cl_text.isdigit() else None
        if cl is not None and cl != len(body):
            last_err = f"size mismatch: header {cl} vs body {len(body)}"
            continue
        return _Response(200, body, last_modified, etag_out, cl)
    raise FetchError(f"{url}: {last_err}")


def _needs_fetch(dest: Path, day: date, recheck_from: date) -> tuple[bool, str | None]:
    """(是否需要请求, 条件请求用的 ETag)。已有 200 文件且大小一致、或已有 404 标记,且日期早于复核窗口 → 跳过。"""
    meta = _read_meta(meta_path(dest, day))
    if meta is None:
        return True, None
    status = meta.get("status")
    path = csv_path(dest, day)
    if status == 200:
        size = meta.get("file_size")
        ok = path.exists() and isinstance(size, int) and path.stat().st_size == size
        if not ok:
            return True, None
        etag = meta.get("etag")
        if day >= recheck_from:
            return True, (etag if isinstance(etag, str) else None)
        return False, None
    if status == 404:
        return day >= recheck_from, None
    return True, None


def fetch(dest: Path, start: str = DEFAULT_START, end: str | None = None) -> None:
    """抓取 [start, end] 每天的 china_cities 文件到 dest/raw(幂等、可续传)。end 默认 = 最近一个已写完的北京日。

    已存在且大小一致的文件不再请求;距 end ≤ RECHECK_DAYS 的日期用 If-None-Match 复核(304 = 未变)。
    404 写 .meta.json 作为永久空洞标记(复核窗口内会再试)。连续 MAX_CONSECUTIVE_FAILURES 个日期失败则停止。
    """
    end_s = default_end() if end is None else end
    start_d, end_d = _parse_day(start), _parse_day(end_s)
    if end_d < start_d:
        raise ValueError(f"end {end_s} < start {start}")
    raw_dir(dest).mkdir(parents=True, exist_ok=True)
    recheck_from = end_d - timedelta(days=RECHECK_DAYS)
    throttle = _Throttle(MIN_INTERVAL)
    days = [start_d + timedelta(days=i) for i in range((end_d - start_d).days + 1)]
    n_req = n_new = n_404 = n_skip = n_same = 0
    consecutive_failures = 0
    for i, day in enumerate(days, start=1):
        need, etag = _needs_fetch(dest, day, recheck_from)
        if not need:
            n_skip += 1
            continue
        url = SOURCE_URL.format(ymd=_ymd(day))
        try:
            resp = _request(url, throttle, etag=etag)
        except FetchError as exc:
            consecutive_failures += 1
            log.error("%s (%d consecutive)", exc, consecutive_failures)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                log.error(
                    "stopping politely after %d consecutive failures; rerun to resume", consecutive_failures
                )
                break
            continue
        consecutive_failures = 0
        n_req += 1
        fetched_at = _utc_now_iso()
        if resp.status == 304:
            n_same += 1
            continue
        if resp.status == 404:
            n_404 += 1
            path = csv_path(dest, day)
            if path.exists():
                path.unlink()
            _write_meta(
                meta_path(dest, day),
                {"date": str(day), "url": url, "status": 404, "fetched_at_utc": fetched_at},
            )
            continue
        path = csv_path(dest, day)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(resp.content)
        tmp.replace(path)
        _write_meta(
            meta_path(dest, day),
            {
                "date": str(day),
                "url": url,
                "status": 200,
                "last_modified_utc": _http_date_to_iso(resp.last_modified),
                "last_modified_http": resp.last_modified,
                "etag": resp.etag,
                "content_length": resp.content_length,
                "file_size": len(resp.content),
                "fetched_at_utc": fetched_at,
            },
        )
        n_new += 1
        if n_new % 100 == 0:
            log.info(
                "%d/%d days: %d downloaded, %d missing(404), %d unchanged, %d skipped",
                i,
                len(days),
                n_new,
                n_404,
                n_same,
                n_skip,
            )
    log.info(
        "fetch done: %d requests, %d downloaded, %d missing(404), %d unchanged(304), %d skipped (already present)",
        n_req,
        n_new,
        n_404,
        n_same,
        n_skip,
    )


# ---------------------------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------------------------


def _scan(dest: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读 dest/raw 全部 .meta.json → (observations 表, 文件索引表)。available_day 在这里重算。"""
    obs_rows: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    rdir = raw_dir(dest)
    metas = sorted(rdir.glob("china_cities_*.meta.json")) if rdir.exists() else []
    for mp in metas:
        meta = _read_meta(mp)
        if meta is None:
            continue
        day = _parse_day(str(meta.get("date")))
        file_row: dict[str, Any] = {
            "obs_date": str(day),
            "status": "missing",
            "file_size": None,
            "last_modified_utc": meta.get("last_modified_utc"),
            "fetched_at_utc": meta.get("fetched_at_utc"),
            "n_cols": None,
            "n_rows": None,
            "n_hours_pm25": None,
            "cities_found": None,
            "header_sig": None,
            "n_rows_other_date": None,
            "n_dup_rows": None,
        }
        path = csv_path(dest, day)
        if meta.get("status") == 200 and path.exists():
            raw = path.read_bytes()
            parsed = parse_file(raw, day)
            meta = {**meta, "file_size": len(raw)}
            file_row.update(
                {
                    "status": "partial" if len(raw) < PARTIAL_BYTES else "present",
                    "file_size": len(raw),
                    "n_cols": parsed.n_cols,
                    "n_rows": parsed.n_rows,
                    "n_hours_pm25": len(parsed.hours_pm25),
                    "cities_found": "|".join(parsed.cities_found),
                    "header_sig": header_signature(parsed.header),
                    "n_rows_other_date": parsed.n_rows_other_date,
                    "n_dup_rows": parsed.n_dup_rows,
                }
            )
            obs_rows.extend(observation_rows(parsed, meta))
        file_rows.append(file_row)
    obs = pd.DataFrame(obs_rows, columns=list(OBS_COLUMNS))
    obs = obs.sort_values(["key", "obs_date"], kind="mergesort").reset_index(drop=True)
    if obs.duplicated(["key", "obs_date"]).any():
        raise RuntimeError("duplicate (key, obs_date) in observations")
    obs["n_hours"] = obs["n_hours"].astype("Int64")
    obs["n_cities"] = obs["n_cities"].astype("Int64")
    obs["file_size"] = obs["file_size"].astype("Int64")
    files = pd.DataFrame(file_rows, columns=list(FILE_COLUMNS))
    files = files.sort_values("obs_date", kind="mergesort").reset_index(drop=True)
    for col in ("file_size", "n_cols", "n_rows", "n_hours_pm25", "n_rows_other_date", "n_dup_rows"):
        files[col] = files[col].astype("Int64")
    return obs, files


def load(dest: Path) -> pd.DataFrame:
    """从原始文件重建观测表(obs_date, available_day, key, value, n_hours, n_cities, last_modified_utc, file_size, fetched_at_utc)。"""
    obs, _ = _scan(dest)
    return obs


def file_index(dest: Path) -> pd.DataFrame:
    """每个已请求日期的文件状态表(present / partial / missing 与解析统计)。"""
    _, files = _scan(dest)
    return files


def write_tables(dest: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    obs, files = _scan(dest)
    dest.mkdir(parents=True, exist_ok=True)
    obs.to_csv(dest / "observations.csv", index=False)
    files.to_csv(dest / "files.csv", index=False)
    return obs, files


def summarize(obs: pd.DataFrame, files: pd.DataFrame, dest: Path | None = None) -> str:
    """给报告用的几行摘要:文件状态、日期范围、观测数、空洞、表头变化(dest 给出时重读变化点文件)。"""
    lines: list[str] = []
    counts = files["status"].value_counts() if len(files) else pd.Series(dtype="int64")
    present = int(counts.get("present", 0))
    partial = int(counts.get("partial", 0))
    missing = int(counts.get("missing", 0))
    size_mb = float(files["file_size"].fillna(0).sum()) / 1e6
    lines.append(
        f"files: present={present} partial(<{PARTIAL_BYTES // 1000} KB)={partial} missing(404)={missing} total_size={size_mb:.1f} MB"
    )
    if len(files):
        lines.append(f"file dates: {files['obs_date'].iloc[0]} .. {files['obs_date'].iloc[-1]}")
        gaps = files.loc[files["status"] == "missing", "obs_date"].tolist()
        lines.append(f"missing dates ({len(gaps)}): {', '.join(gaps[:60])}{' ...' if len(gaps) > 60 else ''}")
        partials = files.loc[files["status"] == "partial", "obs_date"].tolist()
        lines.append(
            f"partial dates ({len(partials)}): {', '.join(partials[:60])}{' ...' if len(partials) > 60 else ''}"
        )
        if dest is not None:
            for k, ch in enumerate(header_changes(dest, files)):
                if k == 0:
                    lines.append(
                        f"initial header {ch['obs_date']}: {ch['n_cols']} city cols; cities found {ch['cities_found']}"
                    )
                    continue
                lines.append(
                    f"header change {ch['obs_date']}: {ch['n_cols']} city cols, +{ch['added']} -{ch['removed']}"
                    f"{' reordered' if ch['reordered'] else ''}; cities found {ch['cities_found']}"
                )
        else:
            nc = files.loc[files["n_cols"].notna(), ["obs_date", "n_cols"]]
            if len(nc):
                change = nc[nc["n_cols"].ne(nc["n_cols"].shift())]
                lines.append(
                    "n_cols changes: " + "; ".join(f"{r.obs_date}:{r.n_cols}" for r in change.itertuples())
                )
        short = files.loc[
            files["cities_found"].notna() & (files["cities_found"] != "|".join(CITIES)), "obs_date"
        ].tolist()
        lines.append(f"files lacking one of the four city columns: {len(short)}")
    if len(obs):
        lines.append(
            f"observations: {len(obs)} rows; obs_date {obs['obs_date'].min()} .. {obs['obs_date'].max()}"
        )
        per_key = obs.groupby("key").size()
        lines.append("rows per key: " + ", ".join(f"{k}={v}" for k, v in per_key.items()))
        mean_rows = obs[obs["key"] == KEY_MEAN]
        if len(files):
            have = set(mean_rows["obs_date"])
            no_value = [d for d in files["obs_date"] if d not in have]
            lines.append(f"dates with a file request but no {KEY_MEAN} value: {len(no_value)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0] if __doc__ else None)
    parser.add_argument("--dest", type=Path, required=True, help="数据目录,例如 data/external/alt/hebei_pm25")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=None, help="默认 = 最近一个已写完的北京日")
    parser.add_argument("--skip-fetch", action="store_true", help="只从已有原始文件重建 observations.csv")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    dest: Path = args.dest
    if not args.skip_fetch:
        fetch(dest, start=args.start, end=args.end)
    obs, files = write_tables(dest)
    print(summarize(obs, files, dest))
    print(f"wrote {dest / 'observations.csv'} and {dest / 'files.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
