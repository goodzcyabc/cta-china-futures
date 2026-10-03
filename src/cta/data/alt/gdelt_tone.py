"""候选 N(试验 54):GDELT DOC 2.0 API 新闻语调(预注册 docs/altdata_prereg.md 第 5 节)。

来源:https://api.gdeltproject.org/api/v2/doc/doc ,mode=timelinetone(日均语调)与 mode=timelinevolraw
(日匹配文章数与当日监测总量),format=csv,日频、UTC 日,历史自 2017-01-01 起。每个品种一个固定英文短语
(PHRASES,带引号整句匹配,不加语言/国家过滤),短语被 API 拒绝时只记录错误,不换词。

原始落盘(raw/,全部保留,管道可重放):
- ``<SYM>_<mode>.csv``       API 原样返回的字节(含 BOM);
- ``<SYM>_<mode>.json``      抓取元数据:URL/参数、fetched_at_utc、HTTP 状态与 Date 头、Last-Modified(API 不给,记 null)、
                             字节数、sha256、重试次数;短语被拒时 ``error`` 字段存 API 原话,正文另存 ``.error.txt``;
- ``refetch/``               同一查询的二次快照(核对历史是否不变);
- ``counts_2017_2019_median.csv``  每品种 2017-01-01..2019-12-31 的日文章数中位数(篮子纳入规则 ≥ 20 由预注册执行,这里只算数)。

可得规则(预注册,固定):**available_day = UTC 日 D + 2 个日历日**。规则不依赖抓取时刻;核验者确认已完成 UTC 日的
数值在 2020–2026 的 9 个 Wayback 快照间逐位不变,因此今天抓到的历史值等于 D+2 当天公开的值。抓取时距 D 不足 2 天的
"前沿"日可能尚未索引完(实时滞后不定),用 meta 列 complete_at_fetch=False 标出,不改规则。

观测表(observations.csv):obs_date(UTC 日)、available_day、key("N-<SYM>")、value(Average Tone)、
n_articles(同日 Article Count)、total_monitored(同日 Total Monitored Articles)、fetched_at_utc、complete_at_fetch。
API 空洞日(无行)不填补;Article Count 为 0 的日子语调无定义,不入表(等价于缺失,不填 0)。

礼貌抓取:请求间隔 ≥ 5 s(这里 6 s),429/5xx 退避 20–60 s 重试最多 10 次;某条查询 10 次仍失败则不落盘、跳过并继续,
命令行退出码 1,重跑同一命令只补抓缺的(幂等——已有且字节数与元数据一致的文件跳过)。实测 2026-10-02 晚间 API 对本 IP 限流
极重(单条查询常需数分钟到十余分钟),全量抓取靠反复重跑完成。
命令行:``PYTHONPATH=src python3 -m cta.data.alt.gdelt_tone --dest data/external/alt/gdelt_tone``。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import http.client
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
HISTORY_START = "2017-01-01"  # API 最早日期;更早返回 "Invalid query start date."
DEFAULT_END = "2026-12-31"  # 预注册端点写死的 enddatetime;API 只返回到其索引前沿
LAG_DAYS = 2  # 预注册可得规则:A = D + 2 日历日
KEY_PREFIX = "N-"
MODE_TONE = "timelinetone"
MODE_VOL = "timelinevolraw"
MODES: tuple[str, ...] = (MODE_TONE, MODE_VOL)
SERIES_TONE = "Average Tone"
SERIES_COUNT = "Article Count"
SERIES_TOTAL = "Total Monitored Articles"
MIN_GAP_SECONDS = 6.0  # GDELT 要求 ≥ 5 s
MAX_TRIES = 10
TIMEOUT_SECONDS = 180
COUNT_WINDOW = ("2017-01-01", "2019-12-31")

# 预注册第 5 节:每品种一个固定英文短语(顺序即落盘顺序)。
PHRASES: dict[str, str] = {
    "AU": "gold price",
    "AG": "silver price",
    "CU": "copper price",
    "AL": "aluminium price",
    "NI": "nickel price",
    "SN": "tin price",
    "I": "iron ore",
    "J": "coking coal",
    "RB": "steel rebar",
    "MA": "methanol",
    "RU": "natural rubber",
    "SA": "soda ash",
    "TA": "purified terephthalic acid",
    "V": "polyvinyl chloride",
    "SC": "crude oil",
    "C": "corn futures",
    "CF": "cotton futures",
    "JD": "egg prices",
    "M": "soybean meal",
    "P": "palm oil",
    "SR": "sugar futures",
    "Y": "soybean oil",
}

OBS_COLS = [
    "obs_date",
    "available_day",
    "key",
    "value",
    "n_articles",
    "total_monitored",
    "fetched_at_utc",
    "complete_at_fetch",
]
COUNT_COLS = ["symbol", "key", "phrase", "status", "n_days", "median_daily_articles"]


class ApiRejectedError(ValueError):
    """API 返回的不是 CSV 而是一句错误/提示(短语太短、日期非法、限流提示等)。"""


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    headers: dict[str, str]
    attempts: int


# ---------------------------------------------------------------------------------------------
# 路径与元数据
# ---------------------------------------------------------------------------------------------


def raw_dir(dest: Path) -> Path:
    return dest / "raw"


def raw_path(dest: Path, symbol: str, mode: str) -> Path:
    return raw_dir(dest) / f"{symbol}_{mode}.csv"


def meta_path(dest: Path, symbol: str, mode: str) -> Path:
    return raw_dir(dest) / f"{symbol}_{mode}.json"


def read_meta(dest: Path, symbol: str, mode: str) -> dict[str, Any] | None:
    p = meta_path(dest, symbol, mode)
    if not p.exists():
        return None
    obj: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    return obj


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _iso_utc(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def query_params(phrase: str, mode: str, start: str, end: str) -> dict[str, str]:
    """预注册端点的参数:短语整句加引号,无语言/国家过滤。"""
    return {
        "query": f'"{phrase}"',
        "mode": mode,
        "format": "csv",
        "startdatetime": start.replace("-", "") + "000000",
        "enddatetime": end.replace("-", "") + "235959",
    }


# ---------------------------------------------------------------------------------------------
# HTTP(限速 + 退避重试)
# ---------------------------------------------------------------------------------------------

_clock: dict[str, float] = {"last_request_at": 0.0}
_sleep = time.sleep  # 测试可替换


def _throttle() -> None:
    gap = time.monotonic() - _clock["last_request_at"]
    if gap < MIN_GAP_SECONDS:
        _sleep(MIN_GAP_SECONDS - gap)
    _clock["last_request_at"] = time.monotonic()


def _backoff_seconds(attempt: int, headers: dict[str, str]) -> float:
    ra = headers.get("Retry-After")
    if ra is not None and ra.strip().isdigit():
        return float(min(max(int(ra), 20), 60))
    return float(min(20 * (attempt + 1), 60))  # 20, 40, 60, 60, …(观测到限流常持续数分钟,尽快拉到上限)


def _open(params: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
    """一次 GET(urllib;仓库其他抓取模块同一做法)。HTTPError 当作带状态码的正常返回。"""
    url = API_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/csv,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return int(resp.status), bytes(resp.read()), {str(k): str(v) for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        body = e.read() if e.fp is not None else b""
        return int(e.code), bytes(body), {str(k): str(v) for k, v in e.headers.items()}


def _http_get(params: dict[str, str]) -> HttpResult:
    """带限速与退避的 GET:429/5xx/网络错误退避 20–60 s 重试(最多 MAX_TRIES);其余状态原样返回给调用方判断。"""
    last_err: BaseException | None = None
    for attempt in range(MAX_TRIES):
        _throttle()
        try:
            status, body, headers = _open(params)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            # 网络层错误(HTTPError 已在 _open 内处理);读正文中途断开是 IncompleteRead(HTTPException,非 OSError),同样重试
            last_err = e
            _sleep(_backoff_seconds(attempt, {}))
            continue
        throttled = status == 200 and body.lstrip(b"\xef\xbb\xbf \n").startswith(b"Please limit requests")
        if status == 429 or status >= 500 or throttled:  # 限流提示偶尔以 200 返回,同样退避重试
            last_err = RuntimeError(f"HTTP {status}: {body[:200]!r}")
            _sleep(_backoff_seconds(attempt, headers))
            continue
        return HttpResult(status=status, body=body, headers=headers, attempts=attempt + 1)
    raise RuntimeError(
        f"GDELT request failed after {MAX_TRIES} tries: {params.get('query')} {params.get('mode')}: {last_err}"
    )


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


def api_error_message(body: bytes) -> str | None:
    """正文不是 ``Date,Series,Value`` CSV 时返回 API 的提示文本(去空白、截断),否则 None。"""
    text = body.decode("utf-8-sig", errors="replace")
    first = text.lstrip().split("\n", 1)[0].strip()
    if [c.strip() for c in first.split(",")[:3]] == ["Date", "Series", "Value"]:
        return None
    msg = " ".join(text.split())
    return msg[:500] if msg else "(empty body)"


def parse_timeline(body: bytes) -> pd.DataFrame:
    """DOC API 时间线 CSV → columns=[date, series, value];date 为 ``YYYY-MM-DD`` 字符串(UTC 日),value 为 float。
    只接受日频行(时间部分非 0 说明查询窗口太短,API 退化为小时/15 分钟粒度,拒绝);不填补缺失日。"""
    err = api_error_message(body)
    if err is not None:
        raise ApiRejectedError(err)
    text = body.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    out: list[tuple[str, str, float]] = []
    for r in rows[1:]:
        if len(r) < 3 or not r[0].strip():
            continue
        ts = pd.Timestamp(r[0].strip())
        if ts != ts.normalize():
            raise ValueError(f"sub-daily timeline row {r[0]!r}; the query window must span many days")
        out.append((ts.strftime("%Y-%m-%d"), r[1].strip(), float(r[2])))
    df = pd.DataFrame(out, columns=["date", "series", "value"])
    if df.duplicated(["date", "series"]).any():
        raise ValueError("duplicate (date, series) rows in GDELT timeline")
    return df.sort_values(["series", "date"]).reset_index(drop=True)


def _series(df: pd.DataFrame, name: str) -> pd.Series[float]:
    sub = df[df["series"] == name]
    return pd.Series(sub["value"].to_numpy(), index=pd.Index(sub["date"].to_numpy(), name="date"), name=name)


# ---------------------------------------------------------------------------------------------
# 可得规则
# ---------------------------------------------------------------------------------------------


def available_day_of(obs_date: str) -> str:
    """预注册规则:UTC 日 D 的语调在 D + 2 个日历日(北京日)15:00 前一定已公开。"""
    return (pd.Timestamp(obs_date) + pd.Timedelta(days=LAG_DAYS)).strftime("%Y-%m-%d")


def available_days(obs_date: pd.Series[str]) -> pd.Series[str]:
    return (pd.to_datetime(obs_date) + pd.Timedelta(days=LAG_DAYS)).dt.strftime("%Y-%m-%d")


def complete_at_fetch(obs_date: pd.Series[str], fetched_at_utc: str) -> pd.Series[bool]:
    """抓取时 UTC 日 D 是否已过去 ≥ LAG_DAYS 天(前沿日索引可能未完,只做标记,不改可得日)。"""
    fetched_day = pd.Timestamp(fetched_at_utc).tz_convert(None).normalize()
    return pd.to_datetime(obs_date) <= fetched_day - pd.Timedelta(days=LAG_DAYS)


# ---------------------------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------------------------


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write_meta(path: Path, meta: dict[str, Any]) -> None:
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _already_fetched(dest: Path, symbol: str, mode: str) -> bool:
    """幂等判定:元数据存在,且(被拒短语)或(CSV 存在且字节数与元数据一致)。"""
    meta = read_meta(dest, symbol, mode)
    if meta is None:
        return False
    if meta.get("error") is not None:
        return True
    p = raw_path(dest, symbol, mode)
    return p.exists() and p.stat().st_size == int(meta.get("bytes", -1))


def fetch_one(
    dest: Path,
    symbol: str,
    mode: str,
    start: str,
    end: str,
    out_csv: Path | None = None,
    out_meta: Path | None = None,
) -> dict[str, Any]:
    """抓一个 (品种, mode) 查询并落盘;返回元数据。短语被拒(非 CSV 正文或 4xx)记入 meta['error'],不抛。"""
    phrase = PHRASES[symbol]
    params = query_params(phrase, mode, start, end)
    fetched_at = _utc_now()
    res = _http_get(params)
    csv_path = out_csv or raw_path(dest, symbol, mode)
    json_path = out_meta or meta_path(dest, symbol, mode)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    err: str | None = None
    if res.status != 200:
        err = f"HTTP {res.status}: {api_error_message(res.body) or res.body[:300]!r}"
    else:
        err = api_error_message(res.body)
    meta: dict[str, Any] = {
        "symbol": symbol,
        "key": KEY_PREFIX + symbol,
        "phrase": phrase,
        "mode": mode,
        "url": API_URL,
        "params": params,
        "fetched_at_utc": _iso_utc(fetched_at),
        "http_status": res.status,
        "server_date_header": res.headers.get("Date"),
        "last_modified_utc": res.headers.get("Last-Modified"),  # DOC API 不返回,记 null
        "content_type": res.headers.get("Content-Type"),
        "attempts": res.attempts,
        "bytes": len(res.body),
        "sha256": _sha256(res.body),
        "error": err,
    }
    if err is None:
        csv_path.write_bytes(res.body)
    else:
        csv_path.with_suffix(".error.txt").write_bytes(res.body)
    _write_meta(json_path, meta)
    return meta


def fetch(
    dest: Path, start: str = HISTORY_START, end: str = DEFAULT_END, force: bool = False
) -> list[dict[str, Any]]:
    """全量抓取 22 品种 × 2 mode(幂等、可续传:已有且字节数一致的文件跳过;``force`` 重抓)。返回各文件元数据;
    某条查询重试 MAX_TRIES 次仍失败时不写任何文件、记一条 ``unfetched`` 元数据并继续,下次运行自动补抓。"""
    raw_dir(dest).mkdir(parents=True, exist_ok=True)
    metas: list[dict[str, Any]] = []
    for symbol in PHRASES:
        for mode in MODES:
            if not force and _already_fetched(dest, symbol, mode):
                m = read_meta(dest, symbol, mode)
                if m is not None:
                    metas.append(m)
                continue
            try:
                m = fetch_one(dest, symbol, mode, start, end)
            except RuntimeError as e:  # 限流/网络持续失败:留给下次运行
                m = {"symbol": symbol, "mode": mode, "error": f"UNFETCHED: {e}", "unfetched": True}
            metas.append(m)
            status = "ERROR " + str(m["error"]) if m["error"] else f"{m['bytes']} bytes"
            print(f"[gdelt_tone] {symbol:>2} {mode:<14} {status}")
    return metas


# ---------------------------------------------------------------------------------------------
# 观测表
# ---------------------------------------------------------------------------------------------


def load(dest: Path) -> pd.DataFrame:
    """从 raw/ 重建观测表(重新计算 available_day)。只纳入 tone 文件存在的品种;计数来自同日 volraw(缺则 NaN)。"""
    frames: list[pd.DataFrame] = []
    for symbol in PHRASES:
        tone_meta = read_meta(dest, symbol, MODE_TONE)
        tone_csv = raw_path(dest, symbol, MODE_TONE)
        if tone_meta is None or tone_meta.get("error") is not None or not tone_csv.exists():
            continue
        tone = _series(parse_timeline(tone_csv.read_bytes()), SERIES_TONE)
        vol_csv = raw_path(dest, symbol, MODE_VOL)
        vol_meta = read_meta(dest, symbol, MODE_VOL)
        if vol_meta is not None and vol_meta.get("error") is None and vol_csv.exists():
            vol = parse_timeline(vol_csv.read_bytes())
            counts, totals = _series(vol, SERIES_COUNT), _series(vol, SERIES_TOTAL)
        else:
            counts = pd.Series(dtype=float, name=SERIES_COUNT)
            totals = pd.Series(dtype=float, name=SERIES_TOTAL)
        df = pd.DataFrame({"obs_date": tone.index.to_numpy(), "value": tone.to_numpy()})
        df["n_articles"] = df["obs_date"].map(counts)
        df["total_monitored"] = df["obs_date"].map(totals)
        df = df[~(df["n_articles"] == 0)].dropna(subset=["value"]).copy()  # 零文章日语调无定义 → 视为缺失
        fetched_at = str(tone_meta["fetched_at_utc"])
        df["key"] = KEY_PREFIX + symbol
        df["available_day"] = available_days(df["obs_date"])
        df["fetched_at_utc"] = fetched_at
        df["complete_at_fetch"] = complete_at_fetch(df["obs_date"], fetched_at)
        frames.append(df[OBS_COLS])
    if not frames:
        return pd.DataFrame(columns=OBS_COLS)
    out = pd.concat(frames, ignore_index=True).sort_values(["key", "obs_date"]).reset_index(drop=True)
    if out.duplicated(["key", "obs_date"]).any():
        raise ValueError("duplicate (key, obs_date) in GDELT observations")
    out["n_articles"] = out["n_articles"].astype("Int64")
    out["total_monitored"] = out["total_monitored"].astype("Int64")
    return out


def counts_median(dest: Path) -> pd.DataFrame:
    """每品种 2017-01-01..2019-12-31 的 timelinevolraw 日文章数中位数(API 空洞日不计;0 计入)。只算数,不应用 ≥ 20 规则。"""
    lo, hi = COUNT_WINDOW
    rows: list[dict[str, Any]] = []
    for symbol, phrase in PHRASES.items():
        meta = read_meta(dest, symbol, MODE_VOL)
        p = raw_path(dest, symbol, MODE_VOL)
        status, n_days, med = "missing", 0, float("nan")
        if meta is not None and meta.get("error") is not None:
            status = "rejected"
        elif meta is not None and p.exists():
            counts = _series(parse_timeline(p.read_bytes()), SERIES_COUNT)
            win = counts[(counts.index >= lo) & (counts.index <= hi)]
            status, n_days = "ok", int(len(win))
            med = float(win.median()) if n_days else float("nan")
        rows.append(
            {
                "symbol": symbol,
                "key": KEY_PREFIX + symbol,
                "phrase": phrase,
                "status": status,
                "n_days": n_days,
                "median_daily_articles": med,
            }
        )
    return pd.DataFrame(rows, columns=COUNT_COLS)


def write_outputs(dest: Path) -> tuple[Path, Path]:
    obs = load(dest)
    obs_path = dest / "observations.csv"
    obs.to_csv(obs_path, index=False)
    med_path = raw_dir(dest) / "counts_2017_2019_median.csv"
    counts_median(dest).to_csv(med_path, index=False)
    return obs_path, med_path


# ---------------------------------------------------------------------------------------------
# 二次抓取核对(同一查询相隔 ≥ 10 分钟再抓,比较是否逐字节相同)
# ---------------------------------------------------------------------------------------------


def refetch_snapshot(
    dest: Path, symbol: str, mode: str, start: str = HISTORY_START, end: str = DEFAULT_END
) -> Path:
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    d = raw_dir(dest) / "refetch"
    d.mkdir(parents=True, exist_ok=True)
    out_csv = d / f"{symbol}_{mode}_{stamp}.csv"
    fetch_one(dest, symbol, mode, start, end, out_csv=out_csv, out_meta=out_csv.with_suffix(".json"))
    return out_csv


def compare_refetch(dest: Path, symbol: str, mode: str) -> dict[str, Any]:
    """比较最近两次快照:字节是否相同、行级差异的日期列表、两次抓取时刻。"""
    d = raw_dir(dest) / "refetch"
    snaps = sorted(d.glob(f"{symbol}_{mode}_*.csv")) if d.exists() else []
    if len(snaps) < 2:
        return {"n_snapshots": len(snaps), "identical": None}
    a, b = snaps[-2], snaps[-1]
    ba, bb = a.read_bytes(), b.read_bytes()
    ta, tb = (
        json.loads(a.with_suffix(".json").read_text())["fetched_at_utc"],
        json.loads(b.with_suffix(".json").read_text())["fetched_at_utc"],
    )
    diff_dates: list[str] = []
    if ba != bb:
        sa, sb = parse_timeline(ba), parse_timeline(bb)
        ma = sa.set_index(["date", "series"])["value"]
        mb = sb.set_index(["date", "series"])["value"]
        both = ma.index.union(mb.index)
        xa, xb = ma.reindex(both), mb.reindex(both)
        changed = ~((xa == xb) | (xa.isna() & xb.isna()))
        diff_dates = sorted({str(i[0]) for i in both[changed.to_numpy()]})
    return {
        "n_snapshots": len(snaps),
        "identical": ba == bb,
        "first": str(a.name),
        "second": str(b.name),
        "first_fetched_at_utc": ta,
        "second_fetched_at_utc": tb,
        "bytes": [len(ba), len(bb)],
        "n_diff_dates": len(diff_dates),
        "diff_dates_head": diff_dates[:20],
    }


# ---------------------------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GDELT DOC 2.0 API 新闻语调:全量抓取并写 observations.csv")
    ap.add_argument("--dest", type=Path, default=Path("data/external/alt/gdelt_tone"))
    ap.add_argument("--start", default=HISTORY_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--force", action="store_true", help="忽略已有文件重新抓取")
    ap.add_argument(
        "--refetch", metavar="SYMBOL", help="只对一个品种做二次快照(raw/refetch/)并与上次比较,不改主文件"
    )
    ap.add_argument("--refetch-mode", default=MODE_TONE, choices=MODES)
    args = ap.parse_args(argv)
    dest: Path = args.dest
    if args.refetch:
        p = refetch_snapshot(dest, args.refetch, args.refetch_mode, args.start, args.end)
        print(f"[gdelt_tone] snapshot {p}")
        print(
            json.dumps(compare_refetch(dest, args.refetch, args.refetch_mode), ensure_ascii=False, indent=1)
        )
        return 0
    metas = fetch(dest, args.start, args.end, force=args.force)
    n_rejected = sum(1 for m in metas if m.get("error") and not m.get("unfetched"))
    unfetched = [f"{m['symbol']}_{m['mode']}" for m in metas if m.get("unfetched")]
    obs_path, med_path = write_outputs(dest)
    obs = pd.read_csv(obs_path)
    print(
        f"[gdelt_tone] files={len(metas) - len(unfetched)} rejected={n_rejected} unfetched={len(unfetched)} "
        f"observations={len(obs)} keys={obs['key'].nunique() if len(obs) else 0} "
        f"range={obs['obs_date'].min() if len(obs) else None}..{obs['obs_date'].max() if len(obs) else None} "
        f"-> {obs_path}, {med_path}"
    )
    if unfetched:
        print(f"[gdelt_tone] rerun the same command to resume: {unfetched}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
