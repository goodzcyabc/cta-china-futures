"""候选 Q(河北四钢城 PM2.5)数据模块测试:解析、可得规则、真实全表自检。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.alt import hebei_pm25 as q

DATA_DIR = Path("data/external/alt/hebei_pm25")
OBS_CSV = DATA_DIR / "observations.csv"

TYPES = ("AQI", "PM2.5", "PM2.5_24h", "PM10", "SO2")


def _make_csv(
    day: date,
    header_cities: tuple[str, ...],
    pm25: dict[str, dict[int, str]],
    hours: tuple[int, ...] = tuple(range(24)),
    bom: bool = True,
    extra_rows: tuple[str, ...] = (),
) -> bytes:
    """合成一个 china_cities 文件:所有 type 行都写,只有 PM2.5 行按 pm25 填值,其余填 7。"""
    lines = ["date,hour,type," + ",".join(header_cities)]
    ymd = day.strftime("%Y%m%d")
    for h in hours:
        for t in TYPES:
            cells = []
            for c in header_cities:
                cells.append(pm25.get(c, {}).get(h, "") if t == "PM2.5" else "7")
            lines.append(f"{ymd},{h},{t}," + ",".join(cells))
    lines.extend(extra_rows)
    text = "\n".join(lines) + "\n"
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


# ---------------------------------------------------------------------------------------------
# (a) 解析
# ---------------------------------------------------------------------------------------------


def test_parse_matches_cities_by_name_not_position() -> None:
    day = date(2021, 3, 15)
    # 列顺序故意打乱并夹入无关城市;2021 年起列数变化就是这种情形
    header = ("北京", "邢台", "天津", "唐山", "新城市", "石家庄", "邯郸")
    pm25 = {
        "唐山": {h: str(100 + h) for h in range(24)},
        "邯郸": {h: "50" for h in range(24)},
        "石家庄": {h: "80" for h in range(24)},
        "邢台": {h: "60" for h in range(24)},
        "北京": {h: "999" for h in range(24)},
    }
    parsed = q.parse_file(_make_csv(day, header, pm25), day)
    assert parsed.n_cols == 3 + len(header)
    assert parsed.cities_found == q.CITIES
    assert parsed.hours_pm25 == tuple(range(24))
    assert parsed.city_hours["唐山"][5] == 105.0
    assert parsed.city_hours["邯郸"][0] == 50.0
    daily = q.daily_values(parsed)
    assert daily["唐山"][0] == pytest.approx(100 + 11.5)
    assert daily["唐山"][1] == 24
    assert daily["邯郸"] == (50.0, 24)
    rows = q.observation_rows(
        parsed, {"last_modified_utc": "2021-03-15T16:23:14Z", "file_size": 1, "fetched_at_utc": "x"}
    )
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == {"Q-HEBEI4", "Q-唐山", "Q-邯郸", "Q-石家庄", "Q-邢台"}
    assert by_key["Q-HEBEI4"]["value"] == pytest.approx((111.5 + 50 + 80 + 60) / 4)
    assert by_key["Q-HEBEI4"]["n_cities"] == 4
    assert by_key["Q-唐山"]["n_hours"] == 24
    assert all(r["obs_date"] == "2021-03-15" and r["available_day"] == "2021-03-16" for r in rows)


def test_parse_uses_pm25_not_aqi_and_handles_bom_blanks_and_foreign_rows() -> None:
    day = date(2015, 1, 2)
    header = ("石家庄", "唐山", "邯郸", "邢台")
    # 唐山只有 7 个可用小时(→ 缺失);邯郸 8 个(→ 有值);石家庄全 24;邢台全空
    pm25 = {
        "唐山": {h: "10" for h in range(7)},
        "邯郸": {h: "20" for h in range(8)},
        "石家庄": {h: "30" for h in range(24)},
        "邢台": {},
    }
    extra = (
        "20150103,0,PM2.5,1,1,1,1",  # 别的日期的行:忽略
        "20150102,3,PM2.5,5,5,5,5",  # 重复 (hour, type):只保留首次出现
        "20150102,x,PM2.5,5,5,5,5",  # 坏小时:忽略
        "20150102,24,PM2.5,5,5,5,5",  # 越界小时:忽略
    )
    raw = _make_csv(day, header, pm25, bom=True, extra_rows=extra)
    assert raw[:3] == b"\xef\xbb\xbf"
    parsed = q.parse_file(raw, day)
    assert parsed.n_rows_other_date == 1
    assert parsed.n_dup_rows == 1
    assert parsed.city_hours["石家庄"][3] == 30.0  # 重复行没有覆盖
    assert len(parsed.city_hours["邢台"]) == 0
    daily = q.daily_values(parsed)
    assert "唐山" not in daily
    assert "邢台" not in daily
    assert "邯郸" not in daily  # 只有 8 个可用小时(缺 16 小时)→ 按预注册(缺 ≥ 8 小时 → NaN)不出值
    assert daily["石家庄"] == (30.0, 24)
    rows = q.observation_rows(parsed, {})
    by_key = {r["key"]: r for r in rows}
    assert set(by_key) == {"Q-HEBEI4", "Q-石家庄"}
    assert by_key["Q-HEBEI4"]["value"] == 30.0
    assert by_key["Q-HEBEI4"]["n_cities"] == 1
    # 没有 BOM 的文件同样可解析
    parsed2 = q.parse_file(_make_csv(day, header, pm25, bom=False), day)
    assert q.daily_values(parsed2)["石家庄"] == (30.0, 24)


def test_parse_all_cities_missing_gives_no_rows_and_missing_column_is_tolerated() -> None:
    day = date(2016, 6, 1)
    header = ("北京", "唐山")  # 其余三城列不存在
    pm25 = {"唐山": {h: "40" for h in range(5)}}
    parsed = q.parse_file(_make_csv(day, header, pm25), day)
    assert parsed.cities_found == ("唐山",)
    assert q.daily_values(parsed) == {}
    assert q.observation_rows(parsed, {}) == []
    assert q.parse_file(b"", day).n_cols == 0


def test_scan_builds_sorted_tables_from_raw_dir(tmp_path: Path) -> None:
    raw = q.raw_dir(tmp_path)
    raw.mkdir(parents=True)
    header = ("唐山", "邯郸", "石家庄", "邢台")
    for d in (date(2020, 1, 2), date(2020, 1, 1)):
        pm25 = {c: {h: str(10 * (i + 1)) for h in range(24)} for i, c in enumerate(header)}
        body = _make_csv(d, header, pm25)
        if d.day == 1:  # 填到 ≥ PARTIAL_BYTES 以得到 present;空白行被解析器跳过
            body += b" \n" * (q.PARTIAL_BYTES // 2)
        q.csv_path(tmp_path, d).write_bytes(body)
        q.meta_path(tmp_path, d).write_text(
            json.dumps(
                {
                    "date": str(d),
                    "status": 200,
                    "file_size": len(body),
                    "last_modified_utc": "2020-04-05T18:38:49Z",
                    "fetched_at_utc": "2026-10-02T00:00:00Z",
                }
            )
        )
    q.meta_path(tmp_path, date(2020, 1, 3)).write_text(json.dumps({"date": "2020-01-03", "status": 404}))
    obs, files = q.write_tables(tmp_path)
    assert list(obs.columns) == list(q.OBS_COLUMNS)
    assert obs[["key", "obs_date"]].values.tolist() == sorted(obs[["key", "obs_date"]].values.tolist())
    assert not obs.duplicated(["key", "obs_date"]).any()
    assert len(obs) == 2 * 5
    assert files["status"].tolist() == ["present", "partial", "missing"]
    assert files["n_hours_pm25"].tolist()[:2] == [24, 24]
    back = pd.read_csv(tmp_path / "observations.csv", dtype={"obs_date": str, "available_day": str})
    assert len(back) == len(obs)
    assert (back["available_day"] > back["obs_date"]).all()
    assert q.load(tmp_path).equals(obs)


# ---------------------------------------------------------------------------------------------
# (b) 可得规则:available_day = D + 1 日历日,与文件 Last-Modified 无关
# ---------------------------------------------------------------------------------------------


def test_available_day_is_obs_date_plus_one_calendar_day() -> None:
    for d in (date(2015, 1, 2), date(2016, 2, 28), date(2016, 2, 29), date(2020, 12, 31), date(2026, 10, 1)):
        a = q.available_day(d)
        assert a == d + timedelta(days=1)
        assert (a - d).days == q.AVAILABILITY_LAG_DAYS == 1


def test_availability_not_affected_by_last_modified_or_fetch_time() -> None:
    """文件 Last-Modified 晚(2020-04-05 批量上传)或早都不改变可得日;值不会比 D+1 更早可得。"""
    day = date(2015, 1, 2)
    header = ("唐山", "邯郸", "石家庄", "邢台")
    pm25 = {c: {h: "33" for h in range(24)} for c in header}
    parsed = q.parse_file(_make_csv(day, header, pm25), day)
    for lm in ("2020-04-05T18:11:29Z", "2015-01-02T16:30:00Z", None):
        rows = q.observation_rows(parsed, {"last_modified_utc": lm})
        assert rows
        for r in rows:
            obs = date.fromisoformat(r["obs_date"])
            avail = date.fromisoformat(r["available_day"])
            assert avail == obs + timedelta(days=1)
            assert r["last_modified_utc"] == lm


def test_default_end_only_includes_days_whose_file_is_final() -> None:
    """D 的文件在 D+1 01:00 北京之后视为写完:00:30 时最后一天是前天,01:30 时是昨天。"""
    early = pd.Timestamp("2026-10-03 00:30", tz="Asia/Shanghai")
    late = pd.Timestamp("2026-10-03 01:30", tz="Asia/Shanghai")
    assert q.default_end(early) == "2026-10-01"
    assert q.default_end(late) == "2026-10-02"
    # 以 UTC 给出的 now 也按北京日算
    assert q.default_end(pd.Timestamp("2026-10-02 16:30", tz="UTC")) == "2026-10-01"


def test_needs_fetch_skips_present_and_404_outside_recheck_window(tmp_path: Path) -> None:
    raw = q.raw_dir(tmp_path)
    raw.mkdir(parents=True)
    d_ok, d_404, d_bad, d_recent = date(2019, 1, 1), date(2019, 1, 2), date(2019, 1, 3), date(2019, 1, 9)
    q.csv_path(tmp_path, d_ok).write_bytes(b"abc")
    q.meta_path(tmp_path, d_ok).write_text(
        json.dumps({"date": str(d_ok), "status": 200, "file_size": 3, "etag": "e1"})
    )
    q.meta_path(tmp_path, d_404).write_text(json.dumps({"date": str(d_404), "status": 404}))
    q.csv_path(tmp_path, d_bad).write_bytes(b"ab")  # 大小对不上 → 重抓
    q.meta_path(tmp_path, d_bad).write_text(json.dumps({"date": str(d_bad), "status": 200, "file_size": 3}))
    q.csv_path(tmp_path, d_recent).write_bytes(b"abc")
    q.meta_path(tmp_path, d_recent).write_text(
        json.dumps({"date": str(d_recent), "status": 200, "file_size": 3, "etag": "e9"})
    )
    recheck_from = date(2019, 1, 7)
    assert q._needs_fetch(tmp_path, d_ok, recheck_from) == (False, None)
    assert q._needs_fetch(tmp_path, d_404, recheck_from) == (False, None)
    assert q._needs_fetch(tmp_path, d_bad, recheck_from) == (True, None)
    assert q._needs_fetch(tmp_path, d_recent, recheck_from) == (True, "e9")  # 复核窗口内:条件请求
    assert q._needs_fetch(tmp_path, date(2019, 1, 4), recheck_from) == (True, None)  # 从未请求过


def test_http_date_to_iso() -> None:
    assert q._http_date_to_iso("Sun, 05 Apr 2020 18:11:29 GMT") == "2020-04-05T18:11:29Z"
    assert q._http_date_to_iso(None) is None
    assert q._http_date_to_iso("garbage") is None


# ---------------------------------------------------------------------------------------------
# (c) 真实数据:全表满足规则、无重复、键齐全
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not OBS_CSV.exists(), reason="real data not fetched")
def test_real_observations_obey_rule_and_have_no_duplicates() -> None:
    obs = pd.read_csv(OBS_CSV, dtype={"obs_date": str, "available_day": str, "key": str})
    assert list(obs.columns) == list(q.OBS_COLUMNS)
    assert len(obs) > 1000
    assert not obs.duplicated(["key", "obs_date"]).any()
    assert obs[["key", "obs_date"]].values.tolist() == sorted(obs[["key", "obs_date"]].values.tolist())
    od = pd.to_datetime(obs["obs_date"], format="%Y-%m-%d")
    ad = pd.to_datetime(obs["available_day"], format="%Y-%m-%d")
    lag = (ad - od).dt.days
    assert (lag >= q.AVAILABILITY_LAG_DAYS).all()
    assert (lag == 1).all()  # 绑定规则 A = D + 1,精确
    assert set(obs["key"]) == {q.KEY_MEAN, *(q.KEY_PREFIX + c for c in q.CITIES)}
    assert obs["value"].notna().all()
    assert (obs["value"] >= 0).all()
    city = obs[obs["key"] != q.KEY_MEAN]
    assert (city["n_hours"] >= q.MIN_HOURS).all()
    assert (city["n_hours"] <= 24).all()
    mean = obs[obs["key"] == q.KEY_MEAN].set_index("obs_date")
    assert mean["n_cities"].between(1, 4).all()
    # 四城均值 = 当日城市行的均值,城市数一致
    per_day = city.groupby("obs_date")["value"].agg(["mean", "size"])
    joined = mean.join(per_day, how="inner")
    assert len(joined) == len(mean)
    assert (joined["size"] == joined["n_cities"]).all()
    assert (joined["mean"] - joined["value"]).abs().max() < 1e-9
    # 元数据齐全:每行都有 Last-Modified 与文件大小
    assert obs["last_modified_utc"].notna().all()
    assert (obs["file_size"] > 0).all()
    assert obs["obs_date"].min() >= "2015-01-01"


@pytest.mark.skipif(not OBS_CSV.exists(), reason="real data not fetched")
def test_real_load_reproduces_csv(tmp_path: Path) -> None:
    """重建结果与已存的 observations.csv 一致:非浮点列逐字相同,浮点列相对误差 ≤ 1e-12。
    已存文件在 Python 3.9 下生成;Python 3.12 起内置 sum() 对浮点用补偿求和,四城均值末位可能差 1 ULP。"""
    obs = q.load(DATA_DIR)
    obs.to_csv(tmp_path / "observations.csv", index=False)
    new = pd.read_csv(tmp_path / "observations.csv")
    old = pd.read_csv(OBS_CSV)
    assert list(new.columns) == list(old.columns) and len(new) == len(old)
    for c in old.columns:
        if pd.api.types.is_float_dtype(old[c]):
            a, b = old[c].to_numpy(dtype=float), new[c].to_numpy(dtype=float)
            assert np.array_equal(np.isnan(a), np.isnan(b))
            ok = ~np.isnan(a)
            assert np.allclose(a[ok], b[ok], rtol=1e-12, atol=0.0), c
        else:
            assert old[c].astype(str).equals(new[c].astype(str)), c
