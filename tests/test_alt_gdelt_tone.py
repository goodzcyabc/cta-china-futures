"""候选 N:GDELT DOC 2.0 API 新闻语调模块。(a) 解析用内嵌样例;(b) 可得规则用合成输入;(c) 有真实 observations.csv 时整表核验。
不联网:抓取测试把 HTTP 层与 sleep 替换成假对象。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cta.data.alt import gdelt_tone as gt

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "external" / "alt" / "gdelt_tone"
OBS = DEST / "observations.csv"

BOM = b"\xef\xbb\xbf"
TONE_SAMPLE = BOM + b"\n".join(
    [
        b"Date,Series,Value",
        b"2017-11-29,Average Tone,-0.4018",
        b"2017-11-30,Average Tone,-0.7884",
        # 2017-12-01 / 12-02:API 空洞,无行
        b"2017-12-03,Average Tone,-1.2002",
        b"2017-12-04,Average Tone,0.25",
        b"2017-12-31,Average Tone,1.5",
        b"",
    ]
)
VOL_SAMPLE = BOM + b"\n".join(
    [
        b"Date,Series,Value",
        b"2017-11-29,Article Count,126",
        b"2017-11-29,Total Monitored Articles,427906",
        b"2017-11-30,Article Count,257",
        b"2017-11-30,Total Monitored Articles,592774",
        b"2017-12-03,Article Count,0",  # 零文章日:语调无定义
        b"2017-12-03,Total Monitored Articles,347532",
        b"2017-12-04,Article Count,40",
        b"2017-12-04,Total Monitored Articles,300000",
        # 2017-12-31:volraw 缺该日(tone 有)→ 计数 NaN,行保留
        b"",
    ]
)
REJECT_BODY = b"The query contains a keyword that is too short. Please use at least 3 characters."
THROTTLE_BODY = (
    b"Please limit requests to one every 5 seconds or contact kalev.leetaru5@gmail.com for larger queries."
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """保险:任何测试都不得真的请求 GDELT;需要 HTTP 的测试再用 _FakeHttp 覆盖。"""

    def _blocked(params: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        raise AssertionError(f"network disabled in tests: {params}")

    monkeypatch.setattr(gt, "_open", _blocked)
    monkeypatch.setattr(gt, "_sleep", lambda _s: None)


def _write_raw(
    dest: Path, symbol: str, mode: str, body: bytes, fetched_at: str, error: str | None = None
) -> None:
    raw = gt.raw_dir(dest)
    raw.mkdir(parents=True, exist_ok=True)
    meta = {
        "symbol": symbol,
        "key": gt.KEY_PREFIX + symbol,
        "phrase": gt.PHRASES[symbol],
        "mode": mode,
        "fetched_at_utc": fetched_at,
        "http_status": 200,
        "last_modified_utc": None,
        "bytes": len(body),
        "sha256": gt._sha256(body),
        "error": error,
    }
    if error is None:
        gt.raw_path(dest, symbol, mode).write_bytes(body)
    gt.meta_path(dest, symbol, mode).write_text(json.dumps(meta))


# ---------------------------------------------------------------------------------------------
# (a) 解析
# ---------------------------------------------------------------------------------------------


def test_parse_timeline_strips_bom_keeps_holes() -> None:
    df = gt.parse_timeline(TONE_SAMPLE)
    assert list(df.columns) == ["date", "series", "value"]
    assert list(df["date"]) == ["2017-11-29", "2017-11-30", "2017-12-03", "2017-12-04", "2017-12-31"]
    assert (df["series"] == gt.SERIES_TONE).all()
    assert df["value"].tolist() == pytest.approx([-0.4018, -0.7884, -1.2002, 0.25, 1.5])
    assert "2017-12-01" not in set(df["date"])  # 空洞不填补


def test_parse_timeline_volraw_two_series() -> None:
    df = gt.parse_timeline(VOL_SAMPLE)
    counts = gt._series(df, gt.SERIES_COUNT)
    totals = gt._series(df, gt.SERIES_TOTAL)
    assert counts.to_dict() == {
        "2017-11-29": 126.0,
        "2017-11-30": 257.0,
        "2017-12-03": 0.0,
        "2017-12-04": 40.0,
    }
    assert totals["2017-11-29"] == 427906.0 and len(totals) == 4


def test_parse_timeline_rejects_non_csv_bodies() -> None:
    assert gt.api_error_message(TONE_SAMPLE) is None
    assert gt.api_error_message(REJECT_BODY) is not None and "too short" in str(
        gt.api_error_message(REJECT_BODY)
    )
    with pytest.raises(gt.ApiRejectedError, match="too short"):
        gt.parse_timeline(REJECT_BODY)
    with pytest.raises(gt.ApiRejectedError, match="5 seconds"):
        gt.parse_timeline(THROTTLE_BODY)
    assert gt.api_error_message(b"") == "(empty body)"


def test_parse_timeline_refuses_subdaily_and_duplicates() -> None:
    with pytest.raises(ValueError, match="sub-daily"):
        gt.parse_timeline(b"Date,Series,Value\n2026-09-01T06:00:00Z,Average Tone,1.0\n")
    with pytest.raises(ValueError, match="duplicate"):
        gt.parse_timeline(b"Date,Series,Value\n2026-09-01,Average Tone,1.0\n2026-09-01,Average Tone,2.0\n")


def test_query_params_quote_phrase_exactly() -> None:
    p = gt.query_params("iron ore", gt.MODE_TONE, "2017-01-01", "2026-12-31")
    assert p == {
        "query": '"iron ore"',
        "mode": "timelinetone",
        "format": "csv",
        "startdatetime": "20170101000000",
        "enddatetime": "20261231235959",
    }
    assert len(gt.PHRASES) == 22 and gt.PHRASES["TA"] == "purified terephthalic acid"


def test_load_joins_counts_drops_zero_article_days(tmp_path: Path) -> None:
    _write_raw(tmp_path, "I", gt.MODE_TONE, TONE_SAMPLE, "2018-01-05T03:00:00Z")
    _write_raw(tmp_path, "I", gt.MODE_VOL, VOL_SAMPLE, "2018-01-05T03:00:10Z")
    obs = gt.load(tmp_path)
    assert list(obs.columns) == gt.OBS_COLS
    assert (obs["key"] == "N-I").all()
    # 零文章日 2017-12-03 不入表;volraw 缺失日 2017-12-31 保留且计数为空
    assert obs["obs_date"].tolist() == ["2017-11-29", "2017-11-30", "2017-12-04", "2017-12-31"]
    assert obs["value"].tolist() == pytest.approx([-0.4018, -0.7884, 0.25, 1.5])
    assert obs["n_articles"].tolist()[:3] == [126, 257, 40] and pd.isna(obs["n_articles"].iloc[3])
    assert obs["total_monitored"].iloc[0] == 427906
    assert (obs["fetched_at_utc"] == "2018-01-05T03:00:00Z").all()
    assert obs["available_day"].tolist() == ["2017-12-01", "2017-12-02", "2017-12-06", "2018-01-02"]


def test_load_skips_rejected_and_unfetched_symbols(tmp_path: Path) -> None:
    _write_raw(tmp_path, "TA", gt.MODE_TONE, b"", "2026-10-02T00:00:00Z", error="HTTP 200: keyword too short")
    _write_raw(tmp_path, "TA", gt.MODE_VOL, b"", "2026-10-02T00:00:00Z", error="HTTP 200: keyword too short")
    _write_raw(tmp_path, "AU", gt.MODE_TONE, TONE_SAMPLE, "2026-10-02T00:00:00Z")
    obs = gt.load(tmp_path)
    assert set(obs["key"]) == {"N-AU"}
    assert obs["n_articles"].isna().all()  # AU 无 volraw → 计数空,语调仍保留
    med = gt.counts_median(tmp_path).set_index("symbol")
    assert med.loc["TA", "status"] == "rejected" and pd.isna(med.loc["TA", "median_daily_articles"])
    assert med.loc["AU", "status"] == "missing" and med.loc["CU", "status"] == "missing"
    assert list(med.columns) == gt.COUNT_COLS[1:] and len(med) == 22


def test_counts_median_window_2017_2019_only(tmp_path: Path) -> None:
    rows = ["Date,Series,Value"]
    for d, c in [
        ("2016-12-31", 999),
        ("2017-01-01", 5),
        ("2018-06-01", 20),
        ("2019-12-31", 30),
        ("2020-01-01", 999),
    ]:
        rows += [f"{d},Article Count,{c}", f"{d},Total Monitored Articles,100000"]
    _write_raw(tmp_path, "CU", gt.MODE_VOL, "\n".join(rows).encode(), "2026-10-02T00:00:00Z")
    med = gt.counts_median(tmp_path).set_index("symbol")
    assert med.loc["CU", "status"] == "ok"
    assert med.loc["CU", "n_days"] == 3 and med.loc["CU", "median_daily_articles"] == 20.0


# ---------------------------------------------------------------------------------------------
# (b) 可得规则:A = UTC 日 D + 2 日历日,与抓取时刻无关
# ---------------------------------------------------------------------------------------------


def test_available_day_is_obs_date_plus_two_calendar_days() -> None:
    assert gt.LAG_DAYS == 2
    assert gt.available_day_of("2017-01-01") == "2017-01-03"
    assert gt.available_day_of("2017-12-31") == "2018-01-02"  # 跨年
    assert gt.available_day_of("2020-02-28") == "2020-03-01"  # 闰年
    days = pd.Series(pd.date_range("2017-01-01", "2026-10-01").strftime("%Y-%m-%d"))
    av = gt.available_days(days)
    gap = (pd.to_datetime(av) - pd.to_datetime(days)).dt.days
    assert (gap == 2).all() and (pd.to_datetime(av) >= pd.to_datetime(days) + pd.Timedelta(days=2)).all()


def test_available_day_independent_of_fetch_time_but_frontier_flagged(tmp_path: Path) -> None:
    """同一原始文件在不同时刻解析,可得日逐位相同;抓取时距 D 不足 2 天的前沿日只打标记,不提前也不推迟可得日。"""
    body = b"Date,Series,Value\n2026-09-29,Average Tone,0.1\n2026-09-30,Average Tone,0.2\n2026-10-01,Average Tone,0.3\n"
    _write_raw(tmp_path, "AU", gt.MODE_TONE, body, "2026-10-02T23:38:22Z")
    early = gt.load(tmp_path)
    _write_raw(tmp_path, "AU", gt.MODE_TONE, body, "2026-12-25T08:00:00Z")
    late = gt.load(tmp_path)
    assert (
        early["available_day"].tolist()
        == late["available_day"].tolist()
        == ["2026-10-01", "2026-10-02", "2026-10-03"]
    )
    assert early["complete_at_fetch"].tolist() == [True, True, False]
    assert late["complete_at_fetch"].all()
    for df in (early, late):
        lag = (pd.to_datetime(df["available_day"]) - pd.to_datetime(df["obs_date"])).dt.days
        assert (lag >= gt.LAG_DAYS).all()


class _FakeHttp:
    """按队列返回 (status, body, headers);记录请求参数。"""

    def __init__(self, queue: list[tuple[int, bytes]]) -> None:
        self.queue = list(queue)
        self.calls: list[dict[str, str]] = []

    def __call__(self, params: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        self.calls.append(dict(params))
        status, body = self.queue.pop(0)
        return status, body, {"Date": "Fri, 02 Oct 2026 23:38:22 GMT", "Content-Type": "text/csv"}


def test_fetch_retries_429_records_rejection_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(gt, "_sleep", sleeps.append)
    monkeypatch.setattr(gt, "PHRASES", {"AU": "gold price", "TA": "purified terephthalic acid"})
    fake = _FakeHttp(
        [
            (429, THROTTLE_BODY),  # AU tone:先 429,再 200 但正文是限流提示,第三次成功
            (200, THROTTLE_BODY),
            (200, TONE_SAMPLE),
            (200, VOL_SAMPLE),  # AU volraw
            (200, REJECT_BODY),  # TA tone:短语被拒 → 记录错误,不换词
            (200, REJECT_BODY),  # TA volraw
        ]
    )
    monkeypatch.setattr(gt, "_open", fake)
    metas = gt.fetch(tmp_path)
    assert len(fake.calls) == 6 and all(c["query"].startswith('"') for c in fake.calls)
    assert (
        fake.calls[0]["query"] == '"gold price"' and fake.calls[-1]["query"] == '"purified terephthalic acid"'
    )
    assert any(s >= 20 for s in sleeps)  # 429 后退避 ≥ 20 s
    by = {(m["symbol"], m["mode"]): m for m in metas}
    assert by[("AU", gt.MODE_TONE)]["attempts"] == 3 and by[("AU", gt.MODE_TONE)]["error"] is None
    assert by[("AU", gt.MODE_TONE)]["last_modified_utc"] is None  # API 不给 Last-Modified,如实记 null
    assert "too short" in by[("TA", gt.MODE_TONE)]["error"]
    assert gt.raw_path(tmp_path, "AU", gt.MODE_TONE).read_bytes() == TONE_SAMPLE
    assert not gt.raw_path(tmp_path, "TA", gt.MODE_TONE).exists()
    assert gt.raw_path(tmp_path, "TA", gt.MODE_TONE).with_suffix(".error.txt").read_bytes() == REJECT_BODY
    # 幂等:再跑一次不发请求;截断的文件(字节数与元数据不符)会重抓
    gt.fetch(tmp_path)
    assert len(fake.calls) == 6
    gt.raw_path(tmp_path, "AU", gt.MODE_VOL).write_bytes(VOL_SAMPLE[:10])
    fake.queue.append((200, VOL_SAMPLE))
    gt.fetch(tmp_path)
    assert len(fake.calls) == 7 and fake.calls[-1]["mode"] == gt.MODE_VOL
    obs_path, med_path = gt.write_outputs(tmp_path)
    obs = pd.read_csv(obs_path)
    assert set(obs["key"]) == {"N-AU"} and len(obs) == 4
    med = pd.read_csv(med_path).set_index("symbol")
    assert med.loc["TA", "status"] == "rejected" and med.loc["AU", "status"] == "ok"


def test_fetch_gives_up_after_max_tries_and_resumes_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一条查询 10 次都被限流:不落盘、记 unfetched、继续其余查询;命令行退出码 1;下次运行只补抓那一条。"""
    monkeypatch.setattr(gt, "_sleep", lambda _s: None)
    monkeypatch.setattr(gt, "PHRASES", {"AU": "gold price"})
    fake = _FakeHttp(
        [(429, THROTTLE_BODY)] * gt.MAX_TRIES + [(429, THROTTLE_BODY)] * gt.MAX_TRIES + [(200, VOL_SAMPLE)]
    )
    monkeypatch.setattr(gt, "_open", fake)
    with pytest.raises(RuntimeError, match="after 10 tries"):
        gt._http_get(gt.query_params("gold price", gt.MODE_TONE, "2017-01-01", "2026-12-31"))
    assert len(fake.calls) == gt.MAX_TRIES
    rc = gt.main(["--dest", str(tmp_path)])
    assert rc == 1 and len(fake.calls) == 2 * gt.MAX_TRIES + 1
    assert gt.read_meta(tmp_path, "AU", gt.MODE_TONE) is None  # 失败的查询不写任何文件
    assert gt.read_meta(tmp_path, "AU", gt.MODE_VOL) is not None
    assert (tmp_path / "observations.csv").exists()
    fake.queue.append((200, TONE_SAMPLE))
    assert gt.main(["--dest", str(tmp_path)]) == 0
    assert len(fake.calls) == 2 * gt.MAX_TRIES + 2 and fake.calls[-1]["mode"] == gt.MODE_TONE
    assert len(pd.read_csv(tmp_path / "observations.csv")) == 4


def test_http_get_retries_incomplete_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """读正文中途断开(IncompleteRead,HTTPException 而非 OSError)也走退避重试,不让整轮抓取崩掉。"""
    import http.client

    sleeps: list[float] = []
    monkeypatch.setattr(gt, "_sleep", sleeps.append)
    calls: list[int] = []

    def _flaky(params: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        calls.append(1)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"partial")
        return 200, TONE_SAMPLE, {}

    monkeypatch.setattr(gt, "_open", _flaky)
    res = gt._http_get(gt.query_params("gold price", gt.MODE_TONE, "2017-01-01", "2026-12-31"))
    assert res.attempts == 2 and res.body == TONE_SAMPLE and len(calls) == 2
    assert any(s >= 20 for s in sleeps)  # 断开后退避 ≥ 20 s(其余是 ≥ 5 s 的请求间隔)


def test_compare_refetch_detects_identical_and_changed(tmp_path: Path) -> None:
    d = gt.raw_dir(tmp_path) / "refetch"
    d.mkdir(parents=True)
    for stamp, body in [("20261002T000000Z", TONE_SAMPLE), ("20261002T001000Z", TONE_SAMPLE)]:
        (d / f"AU_timelinetone_{stamp}.csv").write_bytes(body)
        (d / f"AU_timelinetone_{stamp}.json").write_text(json.dumps({"fetched_at_utc": stamp}))
    r = gt.compare_refetch(tmp_path, "AU", gt.MODE_TONE)
    assert r["identical"] is True and r["n_diff_dates"] == 0
    changed = TONE_SAMPLE.replace(b"2017-12-31,Average Tone,1.5", b"2017-12-31,Average Tone,1.6")
    (d / "AU_timelinetone_20261002T002000Z.csv").write_bytes(changed)
    (d / "AU_timelinetone_20261002T002000Z.json").write_text(json.dumps({"fetched_at_utc": "x"}))
    r = gt.compare_refetch(tmp_path, "AU", gt.MODE_TONE)
    assert r["identical"] is False and r["diff_dates_head"] == ["2017-12-31"]


# ---------------------------------------------------------------------------------------------
# (c) 真实数据
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not OBS.exists(), reason="data/external/alt/gdelt_tone/observations.csv 未生成")
def test_real_observations_obey_rule_no_duplicates() -> None:
    obs = pd.read_csv(OBS, dtype={"obs_date": str, "available_day": str, "key": str})
    assert list(obs.columns) == gt.OBS_COLS
    assert not obs.duplicated(["key", "obs_date"]).any()
    assert obs.equals(obs.sort_values(["key", "obs_date"]).reset_index(drop=True))
    lag = (pd.to_datetime(obs["available_day"]) - pd.to_datetime(obs["obs_date"])).dt.days
    assert (lag == gt.LAG_DAYS).all()
    assert obs["available_day"].tolist() == gt.available_days(obs["obs_date"]).tolist()
    assert obs["value"].notna().all() and (obs["obs_date"] >= gt.HISTORY_START).all()
    assert obs["key"].str.startswith(gt.KEY_PREFIX).all()
    assert set(obs["key"].str[len(gt.KEY_PREFIX) :]) <= set(gt.PHRASES)
    assert not (obs["n_articles"] == 0).any()  # 零文章日已剔除
    # 从 raw 重算与落盘表逐位一致(可得日由规则重算)
    again = gt.load(DEST)
    assert again["available_day"].tolist() == obs["available_day"].tolist()
    assert again["value"].tolist() == pytest.approx(obs["value"].tolist())
    med = pd.read_csv(gt.raw_dir(DEST) / "counts_2017_2019_median.csv")
    assert list(med.columns) == gt.COUNT_COLS and len(med) == 22
