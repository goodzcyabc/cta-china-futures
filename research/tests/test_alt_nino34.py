"""来源 E(NOAA CPC 周度 Niño 3.4):解析、可得规则(W + 7)、版本拼接(冻结 8110 / Wayback 首印 / 实时回退)与真实数据表。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cta_research.altdata import nino34 as m

OBS_CSV = Path("data/external/alt/nino34/observations.csv")

HEADER = (
    " Weekly SST data starts week centered on 3Jan1990\n"
    "\n"
    "                Nino1+2      Nino3        Nino34        Nino4\n"
    " Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA\n"
)
# 真实格式样本:负异常与海温粘连(23.4-0.4)、"-0.0"、正异常前有空格
SAMPLE = HEADER + (
    " 03JAN1990     23.4-0.4     25.1-0.3     26.6-0.0     28.6 0.3\n"
    " 10JAN1990     23.4-0.8     25.2-0.3     26.6 0.1     28.6 0.3\n"
    " 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3\n"
    " 23SEP2026     25.4 4.7     28.8 3.9     29.7 3.1     29.8 1.1\n"
    " 09SEP2026     25.2 4.5     28.6 3.7     29.6 2.9     29.6 0.9\n"
)


def _file(rows: dict[str, tuple[float, float]]) -> str:
    """用 {周三 'YYYY-MM-DD': (nino34_sst, nino34_anom)} 生成 wksst 文本(其他三区填常数)。"""
    lines = [HEADER]
    for d in sorted(rows):
        sst, anom = rows[d]
        ts = pd.Timestamp(d)
        tag = f"{ts.day:02d}{ts.strftime('%b').upper()}{ts.year}"
        lines.append(f" {tag}     20.0 0.0     25.0 0.0     {sst:4.1f}{anom:4.1f}     28.0 0.0\n")
    return "".join(lines)


def _weds(start: str, end: str) -> list[pd.Timestamp]:
    return [pd.Timestamp(d) for d in pd.date_range(start, end, freq="W-WED")]


# ---------------------------------------------------------------------------------------------
# (a) 解析
# ---------------------------------------------------------------------------------------------


def test_parse_fused_negative_and_columns() -> None:
    df = m.parse_wksst(SAMPLE)
    assert list(df.columns) == ["week", *m._WEEK_COLS]
    assert len(df) == 5
    assert (df["week"].dt.dayofweek == 2).all()  # 周三
    assert list(df["week"].dt.strftime("%Y-%m-%d")) == [
        "1981-09-02",
        "1990-01-03",
        "1990-01-10",
        "2026-09-09",
        "2026-09-23",
    ]
    r = df.set_index("week")
    assert r.loc[pd.Timestamp("1981-09-02"), "nino12_sst"] == 20.6
    assert r.loc[pd.Timestamp("1981-09-02"), "nino12_anom"] == -0.1
    assert r.loc[pd.Timestamp("1981-09-02"), "nino34_sst"] == 26.5
    assert r.loc[pd.Timestamp("1981-09-02"), "nino34_anom"] == -0.2
    assert r.loc[pd.Timestamp("1990-01-03"), "nino34_anom"] == 0.0  # "-0.0"
    assert r.loc[pd.Timestamp("1990-01-10"), "nino34_anom"] == 0.1
    assert r.loc[pd.Timestamp("2026-09-23"), "nino34_sst"] == 29.7
    assert r.loc[pd.Timestamp("2026-09-23"), "nino34_anom"] == 3.1
    assert r.loc[pd.Timestamp("2026-09-23"), "nino4_anom"] == 1.1


def test_parse_ignores_header_and_rejects_duplicates() -> None:
    assert m.parse_wksst(HEADER).empty
    assert m.parse_wksst("<html>Wayback error</html>").empty
    assert m.is_wksst_file(SAMPLE)
    assert not m.is_wksst_file("<html>Wayback error</html>")
    assert not m.is_wksst_file(HEADER)
    with pytest.raises(ValueError, match="duplicate week"):
        m.parse_wksst(SAMPLE + " 03JAN1990     23.4-0.4     25.1-0.3     26.6-0.0     28.6 0.3\n")


def test_parse_roundtrip_generator() -> None:
    txt = _file({"2021-02-03": (25.9, -0.7), "2021-02-10": (26.1, -0.5)})
    df = m.parse_wksst(txt).set_index("week")
    assert df.loc[pd.Timestamp("2021-02-03"), "nino34_anom"] == -0.7
    assert df.loc[pd.Timestamp("2021-02-10"), "nino34_sst"] == 26.1


def test_parse_cdx_and_http_date() -> None:
    cdx = "20210301014820 200 SKKB 21352\n20210317214056 - RI4J 634\nbad line\n20210512182655 301 X 1\n"
    rows = m._parse_cdx(cdx)
    assert [r[0] for r in rows] == ["20210301014820", "20210317214056", "20210512182655"]
    assert rows[0][1] == "200" and rows[2][1] == "301"
    assert m._http_date_to_iso("Fri, 02 Oct 2026 07:00:12 GMT") == "2026-10-02T07:00:12Z"
    assert m._http_date_to_iso("") == ""
    assert m._http_date_to_iso("garbage") == ""


# ---------------------------------------------------------------------------------------------
# (b) 可得规则 + 拼接(合成输入)
# ---------------------------------------------------------------------------------------------


def _write(path: Path, text: str, meta: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = text.encode()
    path.write_bytes(content)
    full = dict(meta)
    full["size"] = len(content)
    m._meta_path(path).write_text(json.dumps(full))


def _synthetic_dest(tmp_path: Path) -> tuple[Path, dict[str, float]]:
    """冻结 1990–2021-01-27(异常 = 0.1 的周序号 % 7 − 0.3),实时 = 冻结 + 0.2(重叠期)+ 2021-02-03 起新周;
    两个 Wayback 快照:ts 2021-03-01 含到 2021-02-24(首印值 = 实时值 + 1.0,用来证明取的是首印而非实时),
    ts 2021-06-01 含到 2021-05-26(2021-03 的周在这里首次出现,值 = 实时 + 0.5)。2021-06-02 起无快照 → 实时回退。
    """
    raw = tmp_path / "raw"
    frozen: dict[str, tuple[float, float]] = {}
    for i, w in enumerate(_weds("1990-01-03", "2021-01-27")):
        frozen[str(w.date())] = (26.0, round(0.1 * (i % 7) - 0.3, 1))
    live: dict[str, tuple[float, float]] = {}
    for i, w in enumerate(_weds("1990-01-03", "2021-08-25")):
        if w <= m.FROZEN_END:
            live[str(w.date())] = (26.2, round(frozen[str(w.date())][1] + 0.2, 1))
        else:
            live[str(w.date())] = (27.0, round(0.1 * (i % 5), 1))
    vint1 = {d: v for d, v in live.items() if pd.Timestamp(d) <= pd.Timestamp("2021-02-24")}
    for d in vint1:
        if pd.Timestamp(d) >= m.SPLICE_START:
            vint1[d] = (vint1[d][0], round(vint1[d][1] + 1.0, 1))
    vint2 = {d: v for d, v in live.items() if pd.Timestamp(d) <= pd.Timestamp("2021-05-26")}
    for d in vint2:
        if pd.Timestamp(d) >= m.SPLICE_START:
            vint2[d] = (vint2[d][0], round(vint2[d][1] + 0.5, 1))
    _write(raw / m.FROZEN_NAME, _file(frozen), {"last_modified_utc": "2021-02-09T18:00:06Z"})
    _write(
        raw / "live" / f"{m.LIVE_NAME}.20260928T070012Z",
        _file(live),
        {"last_modified_utc": "2026-09-28T07:00:12Z"},
    )
    _write(
        raw / "wayback" / f"{m.LIVE_NAME}.20210301014820",
        _file(vint1),
        {
            "last_modified_utc": "2021-02-28T11:58:00Z",
            "x_archive_orig_last_modified": "Sun, 28 Feb 2021 11:58:00 GMT",
        },
    )
    _write(
        raw / "wayback" / f"{m.LIVE_NAME}.20210601120000",
        _file(vint2),
        {
            "last_modified_utc": "2021-05-31T11:58:00Z",
            "x_archive_orig_last_modified": "Mon, 31 May 2021 11:58:00 GMT",
        },
    )
    # 一个坏快照(HTML)必须被忽略
    _write(raw / "wayback" / f"{m.LIVE_NAME}.20210401000000", "<html>error</html>", {})
    return tmp_path, {"live_minus_frozen": 0.2}


def test_available_day_rule_is_w_plus_7() -> None:
    for w in _weds("1990-01-03", "2026-09-23"):
        a = m.available_day(w)
        assert a == w + pd.Timedelta(days=7)
        assert (a - w).days >= m.AVAIL_LAG_DAYS
        assert a.dayofweek == 2  # 下周三


def test_build_observations_splice_and_vintages(tmp_path: Path) -> None:
    dest, _ = _synthetic_dest(tmp_path)
    obs, cov, info = m.load_all(dest)
    assert list(obs.columns) == m.OBS_COLUMNS
    assert (obs["key"] == m.KEY).all()
    assert not obs.duplicated(["key", "obs_date"]).any()
    assert obs["obs_date"].is_monotonic_increasing
    # 可得规则:每条 available_day = W + 7,无论来源
    assert ((obs["available_day"] - obs["obs_date"]).dt.days == 7).all()

    # c 只由重叠期 2016-01-06..2021-01-27 算出(实时 − 冻结 = 0.2)
    assert info["n_overlap_weeks"] == len(_weds("2016-01-06", "2021-01-27"))
    assert abs(info["splice_offset_c"] - 0.2) < 1e-9
    assert abs(info["overlap_diff_std"]) < 1e-9

    pre = obs[obs["obs_date"] <= m.FROZEN_END]
    post = obs[obs["obs_date"] >= m.SPLICE_START]
    assert len(pre) == len(_weds("1990-01-03", "2021-01-27"))
    assert (pre["source_file"] == "8110").all()
    assert (pre["value"] == pre["anomaly_raw"]).all()  # 冻结文件不减 c
    assert (pre["splice_offset"] == 0.0).all()
    assert (pre["sst"] == 26.0).all()
    assert (pre["last_modified_utc"] == "2021-02-09T18:00:06Z").all()
    assert not pre["vintage_first_print"].any()

    assert len(post) == len(_weds("2021-02-03", "2021-08-25"))
    assert ((post["anomaly_raw"] - post["value"] - 0.2).abs() < 1e-9).all()
    p = post.set_index("obs_date")
    # 2021-02-03..02-24:最早快照 20210301(值 = 实时 + 1.0),不是更晚的 20210601
    for d in _weds("2021-02-03", "2021-02-24"):
        assert p.loc[d, "source_file"] == "wayback:20210301014820"
        assert bool(p.loc[d, "vintage_first_print"])
        assert p.loc[d, "last_modified_utc"] == "2021-02-28T11:58:00Z"
    # 2021-03-03..05-26:首次出现在 20210601 快照(值 = 实时 + 0.5)
    for d in _weds("2021-03-03", "2021-05-26"):
        assert p.loc[d, "source_file"] == "wayback:20210601120000"
        assert bool(p.loc[d, "vintage_first_print"])
    # 2021-06-02 起无快照 → 实时回退
    for d in _weds("2021-06-02", "2021-08-25"):
        assert p.loc[d, "source_file"] == "live"
        assert not bool(p.loc[d, "vintage_first_print"])
        assert p.loc[d, "last_modified_utc"] == "2026-09-28T07:00:12Z"
    live_df = m.parse_wksst(
        (dest / "raw" / "live" / f"{m.LIVE_NAME}.20260928T070012Z").read_text()
    ).set_index("week")
    d1 = pd.Timestamp("2021-02-10")
    assert abs(p.loc[d1, "anomaly_raw"] - (live_df.loc[d1, "nino34_anom"] + 1.0)) < 1e-9
    d2 = pd.Timestamp("2021-04-07")
    assert abs(p.loc[d2, "anomaly_raw"] - (live_df.loc[d2, "nino34_anom"] + 0.5)) < 1e-9
    d3 = pd.Timestamp("2021-07-07")
    assert abs(p.loc[d3, "anomaly_raw"] - live_df.loc[d3, "nino34_anom"]) < 1e-9

    # 覆盖表与 2021-02-03 起的周一一对应
    assert len(cov) == len(post)
    assert info["n_first_print"] == len(_weds("2021-02-03", "2021-05-26"))
    assert info["n_live_fallback"] == len(_weds("2021-06-02", "2021-08-25"))
    assert info["n_wayback_vintages"] == 2  # HTML 坏快照被忽略


def test_late_vintage_does_not_change_availability(tmp_path: Path) -> None:
    """快照抓取时间(早于或晚于 W + 7)都不改变 available_day:规则只看 W。"""
    dest, _ = _synthetic_dest(tmp_path)
    obs = m.load(dest).set_index("obs_date")
    # 快照 20210601 在 2021-05-26 这周之后 6 天抓取(早于 W + 7),可得日仍是 W + 7,不提前
    w = pd.Timestamp("2021-05-26")
    assert obs.loc[w, "source_file"] == "wayback:20210601120000"
    assert obs.loc[w, "available_day"] == w + pd.Timedelta(days=7)
    assert obs.loc[w, "vintage_lag_days"] == 6.0
    # 快照 20210601 在 2021-03-03 这周之后 90 天才抓到(远晚于 W + 7),可得日也不因此延后
    w2 = pd.Timestamp("2021-03-03")
    assert obs.loc[w2, "available_day"] == w2 + pd.Timedelta(days=7)
    assert obs.loc[w2, "vintage_lag_days"] == 90.0


def test_splice_offset_uses_only_overlap() -> None:
    frozen = pd.DataFrame(
        {
            "week": _weds("2015-01-07", "2021-01-27"),
        }
    )
    frozen["nino34_sst"] = 26.0
    frozen["nino34_anom"] = 0.0
    live = frozen.copy()
    live["nino34_anom"] = 0.5  # 重叠期差 0.5
    live.loc[live["week"] < m.OVERLAP_START, "nino34_anom"] = 99.0  # 重叠期之前的巨大差异必须被忽略
    c, n, sd = m.splice_offset(frozen, live)
    assert abs(c - 0.5) < 1e-12
    assert n == len(_weds("2016-01-06", "2021-01-27"))
    assert sd == 0.0
    with pytest.raises(ValueError, match="no overlapping"):
        m.splice_offset(frozen, live[live["week"] < m.OVERLAP_START])


def test_write_outputs_roundtrip(tmp_path: Path) -> None:
    dest, _ = _synthetic_dest(tmp_path)
    obs, cov, info = m.write_outputs(dest)
    csv = pd.read_csv(dest / "observations.csv", dtype={"vintage_ts": str})
    assert list(csv.columns) == m.OBS_COLUMNS
    assert len(csv) == len(obs)
    assert csv["obs_date"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()
    assert csv["available_day"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()
    assert (pd.to_datetime(csv["available_day"]) - pd.to_datetime(csv["obs_date"])).dt.days.eq(7).all()
    assert (dest / "vintage_coverage.csv").exists()
    sj = json.loads((dest / "splice.json").read_text())
    assert abs(sj["splice_offset_c"] - 0.2) < 1e-9
    # 确定性:重跑逐字节相同
    before = (dest / "observations.csv").read_bytes()
    m.write_outputs(dest)
    assert (dest / "observations.csv").read_bytes() == before


# ---------------------------------------------------------------------------------------------
# (c) 真实数据
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not OBS_CSV.exists(), reason="real data not fetched")
def test_real_observations_table() -> None:
    df = pd.read_csv(OBS_CSV, dtype={"vintage_ts": str, "last_modified_utc": str})
    assert list(df.columns) == m.OBS_COLUMNS
    obs = pd.to_datetime(df["obs_date"])
    avail = pd.to_datetime(df["available_day"])
    assert (df["key"] == m.KEY).all()
    assert not df.duplicated(["key", "obs_date"]).any()
    assert obs.is_monotonic_increasing
    assert (obs.dt.dayofweek == 2).all()  # 周中周三
    # 可得规则:available_day = W + 7(≥ 最小滞后 7 日)
    assert ((avail - obs).dt.days == 7).all()
    assert ((avail - obs).dt.days >= m.AVAIL_LAG_DAYS).all()
    assert df["value"].notna().all() and df["anomaly_raw"].notna().all() and df["sst"].notna().all()
    assert obs.min() == pd.Timestamp("1990-01-03")
    assert obs.max() >= pd.Timestamp("2026-09-23")
    # 2021-01-27 前只用冻结文件、不减 c;之后只用 Wayback 首印或实时回退,并减去同一个 c
    pre = df[obs <= m.FROZEN_END]
    post = df[obs >= m.SPLICE_START]
    assert len(pre) + len(post) == len(df)
    assert (pre["source_file"] == "8110").all()
    assert (pre["value"] == pre["anomaly_raw"]).all()
    assert (pre["splice_offset"] == 0.0).all()
    assert post["source_file"].str.match(r"^(wayback:\d{14}|live)$").all()
    c = post["splice_offset"].unique()
    assert len(c) == 1
    assert ((post["anomaly_raw"] - post["value"] - c[0]).abs() < 1e-6).all()
    assert (post["vintage_first_print"] == post["source_file"].str.startswith("wayback:")).all()
    # 快照抓取时间必须在周 W 之后(不可能在 W 之前就包含 W 行)
    assert (post["vintage_lag_days"] > 0).all()
    # 周序列连续(每周一行,无缺周)
    gaps = obs.diff().dropna().dt.days
    assert (gaps == 7).all()
    sj = json.loads((OBS_CSV.parent / "splice.json").read_text())
    assert abs(sj["splice_offset_c"] - c[0]) < 1e-9
    assert sj["n_overlap_weeks"] == len(_weds("2016-01-06", "2021-01-27"))


@pytest.mark.skipif(not OBS_CSV.exists(), reason="real data not fetched")
def test_real_table_matches_raw_rebuild() -> None:
    """observations.csv 与从 raw 重算的表逐值一致(可得日重算)。"""
    dest = OBS_CSV.parent
    rebuilt = m.load(dest)
    df = pd.read_csv(OBS_CSV, dtype={"vintage_ts": str, "last_modified_utc": str})
    assert len(rebuilt) == len(df)
    assert (pd.to_datetime(df["available_day"]).to_numpy() == rebuilt["available_day"].to_numpy()).all()
    assert ((df["value"] - rebuilt["value"]).abs() < 1e-9).all()
    assert (df["source_file"] == rebuilt["source_file"]).all()
