"""来源 W(预注册 docs/altdata_prereg.md 第 3 节):NOAA CPC Global Unified Gauge-Based Daily
Precipitation,实时版(RT)、0.5°,2006 年起。

取值
----
走 NOAA PSL THREDDS 的 NetCDF-subset 服务(NCSS),每年、每个盒子一个请求,得到 netCDF-3 文件
(``raw/ncss/precip_{YYYY}_{KEY}.nc``,旁边 ``.json`` 记录请求 URL、抓取时刻与响应头)。盒子内"格点"=
中心严格落在盒子内的 0.5° 格(中心在 .25/.75,边界为整数度,无歧义);日值 = 盒子内有限值格点
(陆地格)的算术平均,单位 mm/日;``n_cells`` 记录当日参与平均的有限值格数,``n_box`` 为盒子格点总数。

盒子(纬 南..北,经 西..东,东经 0–360)与格点总数:
    W-P  : -5 .. 7,  99 .. 119  → 24 × 40 = 960 格(马来半岛、苏门答腊、加里曼丹油棕带)
    W-SR : 21 .. 26, 99 .. 111  → 10 × 24 = 240 格(广西、云南南部、广东西部甘蔗)
    W-RU : 5 .. 12,  98 .. 103  → 14 × 10 = 140 格(泰国南部、马来北部橡胶)
    W-AL : 21 .. 34, 97 .. 108  → 26 × 22 = 572 格(云南、四川水电流域)

可得日(核验者给定、不可改)
-----------------------------
CPC FTP 目录 ``RT/{YYYY}/`` 的逐日文件 ``PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{YYYYMMDD}.RT``
(2006–2008 为 ``...{YYYYMMDD}RT.gz`` / ``...{YYYYMMDD}.RT.gz``)首版约 D+1 17:25 UTC 写入,终版约
D+2 21:51 UTC(北京 D+3 05:51)覆盖,少数文件在更晚被整批重写。目录页(``raw/listing_{YYYY}.html``)
的 "Last modified" 为 UTC、分钟精度(与文件 HTTP Last-Modified 头逐一核对一致)。规则:

    available_day = max(D + 4,  LM 所在北京日 + (1 if LM 时刻 ≥ 07:00 UTC else 0))

其中 LM = 该日文件的 Last-Modified(UTC)。目录页只有分钟精度,"07:00" 可能是 07:00:59,因此
"晚于 07:00 UTC" 按 ≥ 07:00 处理(只会更晚、不会更早)。``rewrite_flag`` = available_day > D+4。
目录里没有对应文件的日子无法算可得日,直接不出观测(不补 0)。

命令行
------
    PYTHONPATH=src python3 -m cta.data.alt.cpc_precip --dest data/external/alt/cpc_precip
        [--start 2006-01-01] [--end 2026-12-31] [--spot-check] [--gauge-sample] [--no-fetch]

``--spot-check`` 用 HTTP Range 从 CPC 原始二进制(little-endian float32,2 × 360 × 720;第 0 层雨量
0.1 mm,第 1 层站数;行自 89.75S 向北,列自 0.25E 向东;-999 为缺测)抽若干日期逐格比对 PSL 值;
``--gauge-sample`` 每月 15 日抽样四个盒子的站数(PSL 文件不含站数层)。
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import numpy as np
import numpy.typing as npt
import pandas as pd

# ----------------------------------------------------------------------------- 常量

NCSS_URL = "https://psl.noaa.gov/thredds/ncss/grid/Datasets/cpc_global_precip/precip.{year}.nc"
LISTING_URL = "https://ftp.cpc.ncep.noaa.gov/precip/CPC_UNI_PRCP/GAUGE_GLB/RT/{year}/"

NLAT = 360
NLON = 720
LAT_CENTERS: npt.NDArray[np.float64] = -89.75 + 0.5 * np.arange(NLAT, dtype=np.float64)
LON_CENTERS: npt.NDArray[np.float64] = 0.25 + 0.5 * np.arange(NLON, dtype=np.float64)
LAYER_BYTES = NLAT * NLON * 4  # 一层 float32 的字节数(1,036,800)
RT_FILE_BYTES = 2 * LAYER_BYTES
MISSING_RT = -900.0  # 原始二进制缺测 -999(0.1 mm);小于 -900 一律视为缺测
MIN_LAG_DAYS = 4  # 规则的最小滞后:D + 4
CUTOFF_UTC = dtime(7, 0)  # 北京 15:00 = 07:00 UTC

DEFAULT_START = "2006-01-01"
DEFAULT_END = "2026-12-31"

MIN_INTERVAL_S = 1.0  # 同一主机两次请求的最小间隔
STABLE_AFTER_DAYS = 200  # 年份结束 200 天后目录与 PSL 年文件视为稳定(核验者:最晚重写 189 天)
REFRESH_AGE_H = 12.0  # 未稳定年份:抓取超过 12 小时就重新抓


@dataclass(frozen=True)
class Box:
    """0.5° 盒子:纬度 south..north,经度 west..east(东经 0–360)。"""

    key: str
    south: float
    north: float
    west: float
    east: float

    def lat_mask(self, lat: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
        return np.asarray((lat > self.south) & (lat < self.north), dtype=np.bool_)

    def lon_mask(self, lon: npt.NDArray[np.float64]) -> npt.NDArray[np.bool_]:
        return np.asarray((lon > self.west) & (lon < self.east), dtype=np.bool_)

    @property
    def n_box(self) -> int:
        return int(self.lat_mask(LAT_CENTERS).sum()) * int(self.lon_mask(LON_CENTERS).sum())


BOXES: dict[str, Box] = {
    "W-P": Box("W-P", -5.0, 7.0, 99.0, 119.0),
    "W-SR": Box("W-SR", 21.0, 26.0, 99.0, 111.0),
    "W-RU": Box("W-RU", 5.0, 12.0, 98.0, 103.0),
    "W-AL": Box("W-AL", 21.0, 34.0, 97.0, 108.0),
}

# 抽查日期(含一个已知被重写的 2017-11-08 与两个 2006–2008 的 gz 文件)
SPOT_CHECK_DATES: tuple[str, ...] = (
    "2006-08-01",
    "2008-03-10",
    "2009-07-15",
    "2012-01-10",
    "2016-07-15",
    "2017-11-08",
    "2020-07-15",
    "2023-03-01",
    "2025-07-15",
    "2026-09-28",
)


# ----------------------------------------------------------------------------- HTTP(礼貌 + 重试)

USER_AGENT = "cta-china-futures-altdata/0.1 (research; python-urllib)"
TIMEOUT_S = 600.0
RETRY_STATUS = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class _Response:
    status: int
    headers: dict[str, str]
    content: bytes


class _Http:
    """urllib 封装:同一主机 ≥ MIN_INTERVAL_S 间隔;连接错误 / 429 / 5xx 指数退避重试;404/416 原样返回。"""

    def __init__(self, min_interval: float = MIN_INTERVAL_S, retries: int = 5) -> None:
        self.min_interval = min_interval
        self.retries = retries
        self._last: dict[str, float] = {}

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last.get(host)
        if last is not None:
            gap = self.min_interval - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last[host] = time.monotonic()

    def _once(self, url: str, headers: dict[str, str]) -> _Response:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                content = resp.read()
                return _Response(int(resp.status), {k: v for k, v in resp.headers.items()}, content)
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp is not None else b""
            return _Response(int(exc.code), {k: v for k, v in exc.headers.items()}, body)

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> _Response:
        hdrs = {"User-Agent": USER_AGENT}
        if headers:
            hdrs.update(headers)
        delay = 5.0
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait(url)
            try:
                resp = self._once(url, hdrs)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:  # 连接 / 超时
                last_err = exc
            else:
                if resp.status < 400 or resp.status in (404, 416):
                    return resp
                last_err = RuntimeError(f"HTTP {resp.status} for {url}")
                if resp.status not in RETRY_STATUS:
                    raise last_err
            if attempt < self.retries:
                time.sleep(delay)
                delay = min(delay * 2, 120.0)
        assert last_err is not None
        raise last_err


def _utcnow() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _iso_utc(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")


def _write_sidecar(path: Path, url: str, resp: _Response, fetched_at: datetime, size: int) -> None:
    keep = ("date", "last-modified", "content-length", "content-type", "content-range", "etag", "server")
    meta: dict[str, Any] = {
        "url": url,
        "fetched_at_utc": _iso_utc(fetched_at),
        "status": resp.status,
        "size": size,
        "headers": {k: v for k, v in resp.headers.items() if k.lower() in keep},
    }
    path.with_suffix(path.suffix + ".json").write_text(json.dumps(meta, indent=1, sort_keys=True))


def _read_sidecar(path: Path) -> dict[str, Any] | None:
    side = path.with_suffix(path.suffix + ".json")
    if not side.exists():
        return None
    data: dict[str, Any] = json.loads(side.read_text())
    return data


def _is_stable(year: int, fetched_at: datetime) -> bool:
    return fetched_at >= datetime(year + 1, 1, 1) + timedelta(days=STABLE_AFTER_DAYS)


def _present_and_fresh(path: Path, year: int, now: datetime) -> bool:
    """已在盘上且(文件大小与记录一致)且(年份已稳定 或 抓取未过期)→ 跳过。"""
    side = _read_sidecar(path)
    if side is None or not path.exists():
        return False
    if int(side.get("size", -1)) != path.stat().st_size:
        return False
    fetched_at = _parse_iso_utc(str(side["fetched_at_utc"]))
    if _is_stable(year, fetched_at):
        return True
    return (now - fetched_at) < timedelta(hours=REFRESH_AGE_H)


def _download(http: _Http, url: str, path: Path, *, headers: dict[str, str] | None = None) -> bytes:
    fetched_at = _utcnow()
    resp = http.get(url, headers=headers)
    if resp.status >= 400:
        raise RuntimeError(f"HTTP {resp.status} for {url}")
    content = resp.content
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(content)
    tmp.replace(path)
    _write_sidecar(path, url, resp, fetched_at, len(content))
    return content


# ----------------------------------------------------------------------------- 目录页(可得时间)

_LISTING_RE = re.compile(
    r"lnx\.(?P<ymd>\d{8})\.?RT(?P<gz>\.gz)?</a>\s*</td>\s*<td[^>]*>\s*"
    r"(?P<lm>\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})\s*</td>\s*<td[^>]*>\s*(?P<size>[\d.]+[KMG]?)"
)


@dataclass(frozen=True)
class ListingEntry:
    obs_date: date
    filename_date: str
    last_modified_utc: datetime  # 分钟精度
    size_text: str
    gz: bool


def parse_listing(html: str) -> list[ListingEntry]:
    """解析 Apache 目录页;文件名日期 + "Last modified"(UTC,分钟精度)。两种命名(有无点、.gz)都接受。"""
    out: list[ListingEntry] = []
    for m in _LISTING_RE.finditer(html):
        ymd = m.group("ymd")
        lm = datetime.strptime(m.group("lm"), "%d-%b-%Y %H:%M")
        out.append(
            ListingEntry(
                obs_date=datetime.strptime(ymd, "%Y%m%d").date(),
                filename_date=ymd,
                last_modified_utc=lm,
                size_text=m.group("size"),
                gz=m.group("gz") is not None,
            )
        )
    return out


def listing_path(dest: Path, year: int) -> Path:
    return dest / "raw" / f"listing_{year}.html"


def fetch_listing(http: _Http, dest: Path, year: int, *, force: bool = False) -> Path:
    path = listing_path(dest, year)
    if not force and _present_and_fresh(path, year, _utcnow()):
        return path
    _download(http, LISTING_URL.format(year=year), path)
    return path


def listing_entries(dest: Path) -> dict[date, tuple[ListingEntry, str]]:
    """所有 raw/listing_*.html → {obs_date: (条目, 目录页抓取时刻 ISO)};同一天多次出现取最晚的 Last-Modified。"""
    out: dict[date, tuple[ListingEntry, str]] = {}
    for path in sorted((dest / "raw").glob("listing_*.html")):
        side = _read_sidecar(path)
        fetched = str(side["fetched_at_utc"]) if side else ""
        for e in parse_listing(path.read_text(errors="replace")):
            prev = out.get(e.obs_date)
            if prev is None or e.last_modified_utc >= prev[0].last_modified_utc:
                out[e.obs_date] = (e, fetched)
    return out


def load_listings(dest: Path) -> pd.DataFrame:
    """listing_entries 的表格形式(obs_date, last_modified_utc, size_text, gz, listing_fetched_at_utc)。"""
    entries = listing_entries(dest)
    rows: list[dict[str, Any]] = [
        {
            "obs_date": d,
            "last_modified_utc": e.last_modified_utc,
            "size_text": e.size_text,
            "gz": e.gz,
            "listing_fetched_at_utc": fetched,
        }
        for d, (e, fetched) in sorted(entries.items())
    ]
    columns = ["obs_date", "last_modified_utc", "size_text", "gz", "listing_fetched_at_utc"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def write_listing_csv(dest: Path) -> pd.DataFrame:
    df = load_listings(dest)
    out = df.copy()
    out["obs_date"] = pd.to_datetime(out["obs_date"]).dt.strftime("%Y-%m-%d")
    out["last_modified_utc"] = pd.to_datetime(out["last_modified_utc"]).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(dest / "raw" / "listings.csv", index=False)
    return df


# ----------------------------------------------------------------------------- 可得日规则


def available_day(obs_date: date, last_modified_utc: datetime) -> date:
    """available_day = max(D + 4, 北京日(LM) + [LM 时刻 ≥ 07:00 UTC])。

    LM 为 UTC;北京日 = (LM + 8h).date();若 LM 的 UTC 时刻 ≥ 07:00(北京 15:00 收盘之后)再加一天。
    """
    beijing = (last_modified_utc + timedelta(hours=8)).date()
    if last_modified_utc.time() >= CUTOFF_UTC:
        beijing = beijing + timedelta(days=1)
    floor = obs_date + timedelta(days=MIN_LAG_DAYS)
    return max(floor, beijing)


# ----------------------------------------------------------------------------- PSL NCSS 年度盒子子集


def ncss_url(year: int, box: Box) -> str:
    return (
        NCSS_URL.format(year=year)
        + f"?var=precip&north={box.north:g}&south={box.south:g}&west={box.west:g}&east={box.east:g}"
        + f"&time_start={year}-01-01T00:00:00Z&time_end={year}-12-31T00:00:00Z&accept=netcdf"
    )


def ncss_path(dest: Path, year: int, key: str) -> Path:
    return dest / "raw" / "ncss" / f"precip_{year}_{key}.nc"


def fetch_ncss(http: _Http, dest: Path, year: int, box: Box, *, force: bool = False) -> Path:
    path = ncss_path(dest, year, box.key)
    if not force and _present_and_fresh(path, year, _utcnow()):
        return path
    content = _download(http, ncss_url(year, box), path)
    if not content.startswith(b"CDF"):
        path.unlink(missing_ok=True)
        raise RuntimeError(f"NCSS did not return netCDF for {year}/{box.key}: {content[:200]!r}")
    return path


def read_ncss(
    path: Path,
) -> tuple[list[date], npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """读 netCDF-3:返回 (dates, lat, lon, precip[time, lat, lon]),缺测为 NaN,单位 mm。"""
    from scipy.io import netcdf_file

    with netcdf_file(str(path), "r", mmap=False) as f:
        tvar = f.variables["time"]
        units = tvar.units.decode() if isinstance(tvar.units, bytes) else str(tvar.units)
        m = re.match(r"(hours|days) since (\d{4}-\d{2}-\d{2})", units)
        if m is None:
            raise ValueError(f"unexpected time units {units!r} in {path}")
        origin = datetime.strptime(m.group(2), "%Y-%m-%d")
        scale = 1.0 if m.group(1) == "hours" else 24.0
        hours = np.asarray(tvar[:], dtype=np.float64) * scale
        dates = [(origin + timedelta(hours=float(h))).date() for h in hours]
        lat = np.asarray(f.variables["lat"][:], dtype=np.float64)
        lon = np.asarray(f.variables["lon"][:], dtype=np.float64)
        pvar = f.variables["precip"]
        arr = np.array(pvar[:], dtype=np.float64)
        missing = getattr(pvar, "missing_value", None)
        if missing is not None:
            arr[np.isclose(arr, float(missing), rtol=1e-6)] = np.nan
        arr[arr < MISSING_RT] = np.nan  # -999 之类的哨兵值
    return dates, lat, lon, arr


def box_daily_means(path: Path, box: Box) -> pd.DataFrame:
    """一个 NCSS 年文件 → (obs_date, value, n_cells, n_box);盒子内按中心选格,有限值格求均值。"""
    dates, lat, lon, arr = read_ncss(path)
    lmask = box.lat_mask(lat)
    omask = box.lon_mask(lon)
    n_box = int(lmask.sum()) * int(omask.sum())
    if n_box != box.n_box:
        raise ValueError(f"{path.name}: subset holds {n_box} cells of {box.key}, expected {box.n_box}")
    sub = arr[:, lmask, :][:, :, omask]
    finite = np.isfinite(sub)
    n_cells = finite.sum(axis=(1, 2))
    sums = np.where(finite, sub, 0.0).sum(axis=(1, 2))
    with np.errstate(invalid="ignore", divide="ignore"):
        means = np.where(n_cells > 0, sums / np.maximum(n_cells, 1), np.nan)
    keep = np.isfinite(means)
    return pd.DataFrame(
        {
            "obs_date": [d for d, k in zip(dates, keep) if k],
            "value": means[keep],
            "n_cells": n_cells[keep].astype(int),
            "n_box": n_box,
        }
    )


# ----------------------------------------------------------------------------- 观测表


OBS_COLUMNS = [
    "obs_date",
    "available_day",
    "key",
    "value",
    "n_cells",
    "n_box",
    "last_modified_utc",
    "rewrite_flag",
    "vintage",
]


def _vintage(obs_date: date, lm: datetime, listing_fetched_at: str) -> str:
    """终版约 D+2 21:51 UTC 写入;若目录抓取时终版尚未写出(LM 早于 D+2 21:00 且抓取早于 D+3 00:00 UTC)→ preliminary。"""
    if not listing_fetched_at:
        return "final"
    fetched = _parse_iso_utc(listing_fetched_at)
    d2 = datetime.combine(obs_date + timedelta(days=2), dtime(21, 0))
    d3 = datetime.combine(obs_date + timedelta(days=3), dtime(0, 0))
    return "preliminary" if (lm < d2 and fetched < d3) else "final"


def load(dest: Path) -> pd.DataFrame:
    """从 raw/ 重建观测表(重新计算 available_day)。列见 OBS_COLUMNS;按 key、obs_date 排序;无重复。"""
    lm_by_day: dict[date, tuple[datetime, str]] = {
        d: (e.last_modified_utc, fetched) for d, (e, fetched) in listing_entries(dest).items()
    }
    frames: list[pd.DataFrame] = []
    for key, box in BOXES.items():
        for path in sorted((dest / "raw" / "ncss").glob(f"precip_*_{key}.nc")):
            df = box_daily_means(path, box)
            df["key"] = key
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=OBS_COLUMNS)
    obs = pd.concat(frames, ignore_index=True)
    obs = obs.drop_duplicates(["key", "obs_date"], keep="last")
    has_lm = obs["obs_date"].map(lambda d: d in lm_by_day).to_numpy(dtype=bool)
    obs = obs[has_lm].copy()
    lm_list = [lm_by_day[d][0] for d in obs["obs_date"]]
    fetched_list = [lm_by_day[d][1] for d in obs["obs_date"]]
    obs["last_modified_utc"] = [_iso_utc(lm) for lm in lm_list]
    obs["available_day"] = [available_day(d, lm) for d, lm in zip(obs["obs_date"], lm_list)]
    obs["rewrite_flag"] = [
        a > d + timedelta(days=MIN_LAG_DAYS) for d, a in zip(obs["obs_date"], obs["available_day"])
    ]
    obs["vintage"] = [_vintage(d, lm, f) for d, lm, f in zip(obs["obs_date"], lm_list, fetched_list)]
    obs = obs.sort_values(["key", "obs_date"]).reset_index(drop=True)
    return obs[OBS_COLUMNS]


def write_observations(dest: Path) -> pd.DataFrame:
    obs = load(dest)
    out = obs.copy()
    out["obs_date"] = [d.strftime("%Y-%m-%d") for d in out["obs_date"]]
    out["available_day"] = [d.strftime("%Y-%m-%d") for d in out["available_day"]]
    out.to_csv(dest / "observations.csv", index=False, float_format="%.5f")
    return obs


# ----------------------------------------------------------------------------- 抓取


def _years(start: str, end: str) -> list[int]:
    y0 = datetime.strptime(start, "%Y-%m-%d").year
    y1 = datetime.strptime(end, "%Y-%m-%d").year
    return list(range(y0, y1 + 1))


def _fetched_at(path: Path) -> str | None:
    side = _read_sidecar(path)
    return str(side["fetched_at_utc"]) if side else None


def fetch(dest: Path, start: str = DEFAULT_START, end: str = DEFAULT_END, *, force: bool = False) -> None:
    """幂等、可续传:每年先取 4 个 NCSS 子集,再取该年目录页。已稳定年份且大小匹配的文件跳过。

    顺序关乎点时正确性:目录页的 Last-Modified 决定 available_day,PSL 值决定内容。若先取目录页、
    后取 PSL 值,两次请求之间 CPC 若重写了某日文件且 PSL 已跟进,表里就会是"重写后的值 + 重写前的
    时间戳"(可得日提前 = 前视)。反过来(先值、后目录)最多把时间戳记晚,只会更保守。因此本年任一
    NCSS 文件在本次被(重新)下载后,该年目录页一律强制重取,保证目录页抓取时刻不早于值的抓取时刻。
    """
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "raw" / "ncss").mkdir(parents=True, exist_ok=True)
    http = _Http()
    years = _years(start, end)
    for year in years:
        downloaded = False
        for box in BOXES.values():
            path = ncss_path(dest, year, box.key)
            before = _fetched_at(path)
            fetch_ncss(http, dest, year, box, force=force)
            downloaded = downloaded or _fetched_at(path) != before
            print(f"ncss {year} {box.key} {path.stat().st_size} B", file=sys.stderr)
        fetch_listing(http, dest, year, force=force or downloaded)
        print(f"listing {year} ok", file=sys.stderr)
    write_listing_csv(dest)


# ----------------------------------------------------------------------------- CPC 原始二进制:抽查与站数


def rt_filename(d: date, *, gz: bool | None = None, dotted: bool = True) -> str:
    ymd = d.strftime("%Y%m%d")
    if gz is None:
        gz = d.year <= 2008
    if not gz:
        return f"PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{ymd}.RT"
    return f"PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{ymd}{'.' if dotted else ''}RT.gz"


def _row_span() -> tuple[int, int]:
    """四个盒子覆盖的纬度行区间 [i0, i1](含)。"""
    rows = np.zeros(NLAT, dtype=bool)
    for box in BOXES.values():
        rows |= box.lat_mask(LAT_CENTERS)
    idx = np.flatnonzero(rows)
    return int(idx.min()), int(idx.max())


def _range_rows(http: _Http, url: str, path: Path, layer: int, i0: int, i1: int) -> npt.NDArray[np.float32]:
    """HTTP Range 取第 layer 层第 i0..i1 行 → float32[i1-i0+1, 720]。"""
    start = (layer * NLAT * NLON + i0 * NLON) * 4
    stop = (layer * NLAT * NLON + (i1 + 1) * NLON) * 4 - 1
    if path.exists() and path.stat().st_size == stop - start + 1:
        raw = path.read_bytes()
    else:
        raw = _download(http, url, path, headers={"Range": f"bytes={start}-{stop}"})
        if len(raw) != stop - start + 1:
            path.unlink(missing_ok=True)
            raise RuntimeError(f"Range request returned {len(raw)} bytes, expected {stop - start + 1}: {url}")
    return np.frombuffer(raw, dtype="<f4").reshape(i1 - i0 + 1, NLON)


def _full_rt(http: _Http, dest: Path, d: date) -> npt.NDArray[np.float32] | None:
    """2006–2008 的 gz 文件整文件下载并解压 → float32[2, 360, 720];两种文件名都试。"""
    for dotted in (False, True):
        name = rt_filename(d, gz=True, dotted=dotted)
        path = dest / "raw" / "rt" / name
        if path.exists():
            data = gzip.decompress(path.read_bytes())
        else:
            url = LISTING_URL.format(year=d.year) + name
            resp = http.get(url)
            if resp.status == 404:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            _write_sidecar(path, url, resp, _utcnow(), len(resp.content))
            data = gzip.decompress(resp.content)
        if len(data) != RT_FILE_BYTES:
            raise RuntimeError(f"{name}: decompressed {len(data)} bytes, expected {RT_FILE_BYTES}")
        return np.frombuffer(data, dtype="<f4").reshape(2, NLAT, NLON)
    return None


def rt_rows(http: _Http, dest: Path, d: date, layer: int) -> npt.NDArray[np.float32] | None:
    """CPC 原始文件第 layer 层、四盒子覆盖行(i0..i1)的数组;2006–2008 走整文件,其后走 Range。"""
    i0, i1 = _row_span()
    if d.year <= 2008:
        full = _full_rt(http, dest, d)
        return None if full is None else full[layer, i0 : i1 + 1, :]
    name = rt_filename(d, gz=False)
    url = LISTING_URL.format(year=d.year) + name
    path = dest / "raw" / "rt" / f"{name}.layer{layer}.rows{i0}-{i1}.bin"
    return _range_rows(http, url, path, layer, i0, i1)


def box_from_rows(rows: npt.NDArray[np.float32], box: Box, layer: int) -> tuple[float, int]:
    """行块 → (盒子均值, 有限格数);layer 0 为雨量(0.1 mm → mm),layer 1 为站数(求和)。"""
    i0, _ = _row_span()
    lmask = box.lat_mask(LAT_CENTERS)[i0 : i0 + rows.shape[0]]
    sub = np.asarray(rows[lmask, :][:, box.lon_mask(LON_CENTERS)], dtype=np.float64)
    if layer == 0:
        valid = sub > MISSING_RT
        n = int(valid.sum())
        return (float(sub[valid].mean() / 10.0) if n else float("nan")), n
    valid = sub > MISSING_RT
    return float(sub[valid].sum()), int((sub > 0).sum())


def spot_check(dest: Path, dates: tuple[str, ...] = SPOT_CHECK_DATES) -> pd.DataFrame:
    """逐格比对 PSL(NCSS)与 CPC 原始二进制;写 raw/spotcheck.csv,返回表。"""
    http = _Http()
    obs = load(dest)
    rows: list[dict[str, Any]] = []
    for text in dates:
        d = datetime.strptime(text, "%Y-%m-%d").date()
        rain = rt_rows(http, dest, d, 0)
        if rain is None:
            rows.append({"obs_date": text, "key": "*", "status": "rt file missing"})
            continue
        for key, box in BOXES.items():
            rt_mean, rt_n = box_from_rows(rain, box, 0)
            path = ncss_path(dest, d.year, key)
            dates_nc, lat, lon, arr = read_ncss(path)
            if d not in dates_nc:
                rows.append({"obs_date": text, "key": key, "status": "not in PSL file"})
                continue
            t = dates_nc.index(d)
            psl_cells = arr[t][box.lat_mask(lat), :][:, box.lon_mask(lon)]
            # 原始行块的盒子格,按纬度从南到北;PSL 纬度自北向南 → 翻转后逐格比
            i0, _ = _row_span()
            lmask_rows = box.lat_mask(LAT_CENTERS)[i0 : i0 + rain.shape[0]]
            rt_cells = np.asarray(rain[lmask_rows, :][:, box.lon_mask(LON_CENTERS)], dtype=np.float64)
            rt_cells = np.where(rt_cells > MISSING_RT, rt_cells / 10.0, np.nan)
            if lat[0] > lat[-1]:
                rt_cells = rt_cells[::-1, :]
            if lon[0] > lon[-1]:
                rt_cells = rt_cells[:, ::-1]
            both = np.isfinite(psl_cells) & np.isfinite(rt_cells)
            cell_max = float(np.abs(psl_cells[both] - rt_cells[both]).max()) if both.any() else float("nan")
            sel = obs[(obs["key"] == key) & (obs["obs_date"] == d)]
            table_val = float(sel["value"].iloc[0]) if len(sel) else float("nan")
            rows.append(
                {
                    "obs_date": text,
                    "key": key,
                    "status": "ok",
                    "psl_mean": float(np.nanmean(psl_cells)),
                    "rt_mean": rt_mean,
                    "table_value": table_val,
                    "n_cells_psl": int(np.isfinite(psl_cells).sum()),
                    "n_cells_rt": rt_n,
                    "mask_mismatch": int((np.isfinite(psl_cells) != np.isfinite(rt_cells)).sum()),
                    "cell_max_abs_diff": cell_max,
                    "mean_abs_diff": abs(float(np.nanmean(psl_cells)) - rt_mean),
                }
            )
    df = pd.DataFrame(rows)
    df.to_csv(dest / "raw" / "spotcheck.csv", index=False)
    return df


def gauge_sample(
    dest: Path, start: str = DEFAULT_START, end: str = DEFAULT_END, day: int = 15
) -> pd.DataFrame:
    """每月 day 日抽样四个盒子的站数(sum)与有站格数;写 raw/gauge_counts_monthly.csv。"""
    http = _Http()
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = min(datetime.strptime(end, "%Y-%m-%d").date(), date.today() - timedelta(days=MIN_LAG_DAYS))
    rows: list[dict[str, Any]] = []
    y, m = d0.year, d0.month
    while date(y, m, 1) <= d1:
        d = date(y, m, day)
        if d0 <= d <= d1:
            try:
                g = rt_rows(http, dest, d, 1)
            except RuntimeError as exc:
                print(f"gauge {d}: {exc}", file=sys.stderr)
                g = None
            if g is not None:
                for key, box in BOXES.items():
                    n_gauges, n_with = box_from_rows(g, box, 1)
                    rows.append(
                        {
                            "obs_date": d.isoformat(),
                            "key": key,
                            "n_gauges": int(n_gauges),
                            "n_cells_with_gauge": n_with,
                        }
                    )
            print(f"gauge {d} done", file=sys.stderr)
        m += 1
        if m > 12:
            m, y = 1, y + 1
    df = pd.DataFrame(rows)
    df.to_csv(dest / "raw" / "gauge_counts_monthly.csv", index=False)
    return df


# ----------------------------------------------------------------------------- 命令行


def summarize(obs: pd.DataFrame) -> str:
    if obs.empty:
        return "no observations"
    lines = [f"observations: {len(obs)} rows, {obs['key'].nunique()} keys"]
    for key, grp in obs.groupby("key"):
        d = pd.to_datetime(grp["obs_date"])
        full = pd.date_range(d.min(), d.max(), freq="D")
        missing = full.difference(pd.DatetimeIndex(d))
        lag = (pd.to_datetime(grp["available_day"]) - d).dt.days
        lines.append(
            f"  {key}: {d.min().date()} → {d.max().date()}, n={len(grp)}, missing days={len(missing)}, "
            f"n_cells={int(grp['n_cells'].min())}..{int(grp['n_cells'].max())} of {int(grp['n_box'].iloc[0])}, "
            f"rewrite_flag={int(grp['rewrite_flag'].sum())}, max lag={int(lag.max())} d, "
            f"preliminary={int((grp['vintage'] == 'preliminary').sum())}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "cpc_precip")
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--force", action="store_true", help="重新下载全部文件")
    ap.add_argument("--no-fetch", action="store_true", help="只从 raw/ 重建 observations.csv")
    ap.add_argument("--spot-check", action="store_true", help="用 HTTP Range 对照 CPC 原始二进制")
    ap.add_argument("--gauge-sample", action="store_true", help="每月 15 日抽样站数")
    args = ap.parse_args(argv)
    dest: Path = args.dest
    if not args.no_fetch:
        fetch(dest, args.start, args.end, force=args.force)
    obs = write_observations(dest)
    print(summarize(obs))
    if args.spot_check:
        sc = spot_check(dest)
        ok = sc[sc["status"] == "ok"] if "status" in sc.columns else sc
        print(sc.to_string(index=False))
        if len(ok):
            print(
                f"spot-check: {len(ok)} (date, box) pairs; max cell abs diff = {ok['cell_max_abs_diff'].max():.6g} mm; "
                f"max box-mean abs diff = {ok['mean_abs_diff'].max():.6g} mm; mask mismatches = {int(ok['mask_mismatch'].sum())}"
            )
    if args.gauge_sample:
        gs = gauge_sample(dest, args.start, args.end)
        if len(gs):
            print(gs.groupby("key")[["n_gauges", "n_cells_with_gauge"]].describe().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
