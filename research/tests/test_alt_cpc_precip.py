"""候选 W(NOAA CPC 全球统一雨量格点,四个产区盒子)数据模块测试:解析、可得规则、真实全表自检。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta_research.altdata import cpc_precip as w

DATA_DIR = Path("data/external/alt/cpc_precip")
OBS_CSV = DATA_DIR / "observations.csv"

# 2015 年目录页(新命名)、2006 年(无点 .gz)、2008 年(有点 .gz)三种行;以及一个 .ctl 干扰行
LISTING_HTML = """<html><body><h1>Index of /precip/CPC_UNI_PRCP/GAUGE_GLB/RT/2015</h1>
<table>
<tr><td><a href="/precip/CPC_UNI_PRCP/GAUGE_GLB/RT/">Parent Directory</a></td><td>&nbsp;</td><td align="right">  - </td></tr>
<tr><td><a href="PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20150101.RT">PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20150101.RT</a></td><td align="right">03-Jan-2015 21:51  </td><td align="right">2.0M</td></tr>
<tr><td><a href="PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20150102.RT">PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20150102.RT</a></td><td align="right">06-Feb-2018 20:46  </td><td align="right">2.0M</td></tr>
<tr><td><a href="PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20060101RT.gz">PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20060101RT.gz</a></td><td align="right">02-May-2008 14:03  </td><td align="right">159K</td></tr>
<tr><td><a href="PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20080101.RT.gz">PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20080101.RT.gz</a></td><td align="right">19-Jun-2008 17:41  </td><td align="right">171K</td></tr>
<tr><td><a href="PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.RT.ctl">PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.RT.ctl</a></td><td align="right">02-Oct-2026 17:26  </td><td align="right">454 </td></tr>
</table></body></html>
"""


def _write_nc(path: Path, dates: list[date], lat: np.ndarray, lon: np.ndarray, precip: np.ndarray) -> None:
    """用 scipy 写一个与 PSL NCSS 同结构的 netCDF-3(time 为 hours since 1900-01-01,缺测 NaN)。"""
    from scipy.io import netcdf_file

    path.parent.mkdir(parents=True, exist_ok=True)
    with netcdf_file(str(path), "w") as f:
        f.createDimension("time", len(dates))
        f.createDimension("lat", len(lat))
        f.createDimension("lon", len(lon))
        t = f.createVariable("time", "d", ("time",))
        t[:] = np.array(
            [
                (datetime.combine(d, datetime.min.time()) - datetime(1900, 1, 1)).total_seconds() / 3600
                for d in dates
            ]
        )
        t.units = "hours since 1900-01-01 00:00:00"
        la = f.createVariable("lat", "f", ("lat",))
        la[:] = lat.astype("f4")
        lo = f.createVariable("lon", "f", ("lon",))
        lo[:] = lon.astype("f4")
        p = f.createVariable("precip", "f", ("time", "lat", "lon"))
        p[:] = precip.astype("f4")
        p.missing_value = np.float32(-9.96921e36)
        p.units = "mm"


def _write_listing(dest: Path, year: int, rows: list[tuple[date, datetime]], fetched_at: datetime) -> None:
    lines = []
    for d, lm in rows:
        name = f"PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.{d:%Y%m%d}.RT"
        lines.append(
            f'<tr><td><a href="{name}">{name}</a></td><td align="right">{lm:%d-%b-%Y %H:%M}  </td>'
            '<td align="right">2.0M</td></tr>'
        )
    path = dest / "raw" / f"listing_{year}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("<table>\n" + "\n".join(lines) + "\n</table>\n")
    path.with_suffix(".html.json").write_text(
        json.dumps({"fetched_at_utc": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "size": path.stat().st_size})
    )


# ---------------------------------------------------------------------------------------------
# (a) 解析
# ---------------------------------------------------------------------------------------------


def test_parse_listing_all_three_name_styles_and_skips_ctl() -> None:
    entries = w.parse_listing(LISTING_HTML)
    assert [e.obs_date for e in entries] == [
        date(2015, 1, 1),
        date(2015, 1, 2),
        date(2006, 1, 1),
        date(2008, 1, 1),
    ]
    assert entries[0].last_modified_utc == datetime(2015, 1, 3, 21, 51)
    assert entries[1].last_modified_utc == datetime(2018, 2, 6, 20, 46)
    assert entries[2].gz and entries[3].gz and not entries[0].gz
    assert entries[2].last_modified_utc == datetime(2008, 5, 2, 14, 3)
    assert entries[0].size_text == "2.0M"


def test_box_cell_counts_match_spec() -> None:
    # 中心严格落在盒子内:W-P 24×40、W-SR 10×24、W-RU 14×10、W-AL 26×22
    assert {k: b.n_box for k, b in w.BOXES.items()} == {"W-P": 960, "W-SR": 240, "W-RU": 140, "W-AL": 572}
    lat = w.LAT_CENTERS[w.BOXES["W-P"].lat_mask(w.LAT_CENTERS)]
    lon = w.LON_CENTERS[w.BOXES["W-P"].lon_mask(w.LON_CENTERS)]
    assert lat.min() == -4.75 and lat.max() == 6.75 and lon.min() == 99.25 and lon.max() == 118.75


def test_box_daily_means_ignores_nan_and_counts_cells(tmp_path: Path) -> None:
    box = w.BOXES["W-RU"]  # 5..12 N, 98..103 E → 14 × 10
    # 模拟 NCSS 返回略大的子集(多一圈边界格),纬度自北向南
    lat = np.arange(12.25, 4.74, -0.5)
    lon = np.arange(97.75, 103.26, 0.5)
    dates = [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]
    arr = np.full((3, len(lat), len(lon)), np.nan)
    inner = np.ix_(box.lat_mask(lat), box.lon_mask(lon))
    arr[0][inner] = 2.0
    # 盒子内一格缺测
    arr[0, np.flatnonzero(box.lat_mask(lat))[0], np.flatnonzero(box.lon_mask(lon))[0]] = np.nan
    arr[1][inner] = np.arange(140, dtype=float).reshape(14, 10)
    # 第 3 天盒子内全缺测 → 不出行;边界格给值不应影响任何一天
    arr[:, 0, :] = 999.0
    arr[:, :, 0] = 999.0
    nc = tmp_path / "precip_2020_W-RU.nc"
    _write_nc(nc, dates, lat, lon, arr)
    df = w.box_daily_means(nc, box)
    assert list(df["obs_date"]) == [date(2020, 1, 1), date(2020, 1, 2)]
    assert df["n_box"].tolist() == [140, 140]
    assert df["n_cells"].tolist() == [139, 140]
    assert df["value"].iloc[0] == pytest.approx(2.0)
    assert df["value"].iloc[1] == pytest.approx(np.arange(140).mean(), rel=1e-6)


def test_box_daily_means_rejects_incomplete_subset(tmp_path: Path) -> None:
    box = w.BOXES["W-SR"]
    lat = np.arange(25.75, 21.24, -0.5)[:-2]  # 少两行
    lon = np.arange(99.25, 110.76, 0.5)
    nc = tmp_path / "precip_2020_W-SR.nc"
    _write_nc(nc, [date(2020, 1, 1)], lat, lon, np.ones((1, len(lat), len(lon))))
    with pytest.raises(ValueError, match="expected 240"):
        w.box_daily_means(nc, box)


def test_rt_filename_styles() -> None:
    assert w.rt_filename(date(2015, 1, 1)) == "PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20150101.RT"
    assert w.rt_filename(date(2006, 1, 1), dotted=False) == "PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20060101RT.gz"
    assert w.rt_filename(date(2008, 1, 1)) == "PRCP_CU_GAUGE_V1.0GLB_0.50deg.lnx.20080101.RT.gz"


def test_box_from_rows_rain_and_gauge_layers() -> None:
    i0, i1 = w._row_span()
    assert (i0, i1) == (170, 247)  # -4.75N .. 33.75N
    rows = np.full((i1 - i0 + 1, w.NLON), -999.0, dtype="<f4")
    box = w.BOXES["W-AL"]
    lmask = box.lat_mask(w.LAT_CENTERS)[i0 : i1 + 1]
    sel = np.ix_(lmask, box.lon_mask(w.LON_CENTERS))
    rows[sel] = 25.0  # 2.5 mm
    mean, n = w.box_from_rows(rows, box, 0)
    assert n == 572 and mean == pytest.approx(2.5)
    gauges = np.zeros_like(rows)
    gauges[sel] = 2.0
    total, with_gauge = w.box_from_rows(gauges, box, 1)
    assert total == 1144.0 and with_gauge == 572


# ---------------------------------------------------------------------------------------------
# (b) 可得规则:available_day = max(D+4, 北京日(LM) + [LM ≥ 07:00 UTC])
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("obs", "lm", "expected"),
    [
        # 正常终版 D+2 21:51 UTC = 北京 D+3 05:51 → 北京日 D+3,早于 07:00 UTC → D+3;max → D+4
        (date(2015, 1, 1), datetime(2015, 1, 3, 21, 51), date(2015, 1, 5)),
        # 只有首版 D+1 17:25 UTC → 北京 D+2 01:25,时刻 ≥ 07:00 UTC → D+3;max → D+4
        (date(2015, 1, 1), datetime(2015, 1, 2, 17, 25), date(2015, 1, 5)),
        # D+3 23:30 UTC → 北京 D+4 07:30,≥ 07:00 UTC → D+5(晚于 D+4,延后)
        (date(2015, 1, 1), datetime(2015, 1, 4, 23, 30), date(2015, 1, 6)),
        # D+3 06:59 UTC → 北京 D+3 14:59,早于 07:00 → D+3;max → D+4
        (date(2015, 1, 1), datetime(2015, 1, 4, 6, 59), date(2015, 1, 5)),
        # 重写:2018-02-06 20:46 UTC → 北京 02-07 04:46,≥ 07:00 UTC → 02-08
        (date(2017, 11, 8), datetime(2018, 2, 6, 20, 46), date(2018, 2, 8)),
        # 重写在 06:59 UTC → 当天北京日即可得
        (date(2017, 11, 8), datetime(2018, 2, 6, 6, 59), date(2018, 2, 6)),
        # 恰好 07:00 UTC(目录页分钟精度,可能是 07:00:59)→ 保守按"之后"处理 → 次日
        (date(2017, 11, 8), datetime(2018, 2, 6, 7, 0), date(2018, 2, 7)),
        # 2006 年整批于 2008-05-02 14:03 UTC 写入 → 2008-05-03
        (date(2006, 1, 1), datetime(2008, 5, 2, 14, 3), date(2008, 5, 3)),
        # UTC 日 → 北京日跨日:LM 23:59 UTC D+5 → 北京 D+6 07:59 → ≥07:00 → D+7
        (date(2020, 6, 1), datetime(2020, 6, 6, 23, 59), date(2020, 6, 8)),
    ],
)
def test_available_day_rule(obs: date, lm: datetime, expected: date) -> None:
    assert w.available_day(obs, lm) == expected


def test_available_day_never_before_floor_or_beijing_date() -> None:
    rng = np.random.default_rng(20261002)
    base = datetime(2016, 1, 1)
    for _ in range(2000):
        obs = (base + timedelta(days=int(rng.integers(0, 3000)))).date()
        lm = datetime.combine(obs, datetime.min.time()) + timedelta(
            minutes=int(rng.integers(0, 300 * 24 * 60))
        )
        a = w.available_day(obs, lm)
        assert a >= obs + timedelta(days=w.MIN_LAG_DAYS)
        beijing = (lm + timedelta(hours=8)).date()
        assert a >= beijing
        if lm.time() >= w.CUTOFF_UTC:
            assert a > beijing


def test_vintage_flag() -> None:
    d = date(2026, 10, 1)
    # 目录在终版写出之前抓取、LM 仍是首版 → preliminary
    assert w._vintage(d, datetime(2026, 10, 2, 17, 26), "2026-10-02T23:39:18Z") == "preliminary"
    # 目录在 D+3 之后抓取 → final(无论 LM)
    assert w._vintage(d, datetime(2026, 10, 2, 17, 26), "2026-10-04T00:00:00Z") == "final"
    assert w._vintage(d, datetime(2026, 10, 3, 21, 51), "2026-10-03T23:00:00Z") == "final"


def test_load_end_to_end_synthetic(tmp_path: Path) -> None:
    """合成 raw/:目录页含正常日、重写日、缺目录日;观测表只出有目录的日子,重写日延后。"""
    dest = tmp_path / "cpc"
    lat = np.arange(25.75, 21.24, -0.5)
    lon = np.arange(99.25, 110.76, 0.5)
    dates = [date(2015, 1, 1), date(2015, 1, 2), date(2015, 1, 3)]
    arr = np.ones((3, len(lat), len(lon)))
    arr[1] = 3.0
    arr[2] = 5.0
    _write_nc(dest / "raw" / "ncss" / "precip_2015_W-SR.nc", dates, lat, lon, arr)
    _write_listing(
        dest,
        2015,
        [
            (date(2015, 1, 1), datetime(2015, 1, 3, 21, 51)),  # 正常
            (
                date(2015, 1, 2),
                datetime(2015, 3, 1, 20, 46),
            ),  # 整批重写 → 北京 03-02 04:46,≥07:00 UTC → 03-03
            # 2015-01-03 不在目录 → 不出观测
        ],
        fetched_at=datetime(2026, 10, 2, 23, 0),
    )
    obs = w.load(dest)
    assert list(obs.columns) == w.OBS_COLUMNS
    assert obs["key"].unique().tolist() == ["W-SR"]
    assert obs["obs_date"].tolist() == [date(2015, 1, 1), date(2015, 1, 2)]
    assert obs["available_day"].tolist() == [date(2015, 1, 5), date(2015, 3, 3)]
    assert obs["rewrite_flag"].tolist() == [False, True]
    assert obs["last_modified_utc"].tolist() == ["2015-01-03T21:51:00Z", "2015-03-01T20:46:00Z"]
    assert obs["value"].tolist() == pytest.approx([1.0, 3.0])
    assert obs["n_cells"].tolist() == [240, 240]
    assert obs["vintage"].tolist() == ["final", "final"]
    out = w.write_observations(dest)
    assert len(out) == 2
    back = pd.read_csv(dest / "observations.csv")
    assert list(back.columns) == w.OBS_COLUMNS
    assert back["available_day"].tolist() == ["2015-01-05", "2015-03-03"]


def test_fetch_takes_values_before_listing_and_forces_listing_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """点时顺序:每年先 NCSS 值、后目录页;该年任一 NCSS 被(重)下载 → 目录页强制重取(时间戳只会更晚)。"""
    calls: list[tuple[str, int, object]] = []

    def fake_ncss(http: object, dest: Path, year: int, box: w.Box, *, force: bool = False) -> Path:
        p = w.ncss_path(dest, year, box.key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"CDF")
        if year == 2026:  # 模拟本次真的下载了(sidecar 抓取时刻变化);2025 视为已稳定、跳过
            p.with_name(p.name + ".json").write_text(
                json.dumps({"fetched_at_utc": f"2026-10-03T00:00:{len(calls) % 60:02d}Z", "size": 3})
            )
        calls.append(("ncss", year, box.key))
        return p

    def fake_listing(http: object, dest: Path, year: int, *, force: bool = False) -> Path:
        calls.append(("listing", year, force))
        return w.listing_path(dest, year)

    monkeypatch.setattr(w, "fetch_ncss", fake_ncss)
    monkeypatch.setattr(w, "fetch_listing", fake_listing)
    monkeypatch.setattr(w, "write_listing_csv", lambda dest: pd.DataFrame())
    w.fetch(tmp_path, "2025-01-01", "2026-12-31")
    kinds = [(c[0], c[1]) for c in calls]
    assert kinds == [("ncss", 2025)] * 4 + [("listing", 2025)] + [("ncss", 2026)] * 4 + [("listing", 2026)]
    assert ("listing", 2025, False) in calls  # 未下载 → 不强制
    assert ("listing", 2026, True) in calls  # 下载了 → 强制重取目录页


def test_truncating_listing_does_not_change_earlier_rows(tmp_path: Path) -> None:
    """重跑(或后来目录页重写)只改被重写日期本身:同一 LM 下 available_day 确定且与其它日无关。"""
    d = date(2019, 5, 10)
    a1 = w.available_day(d, datetime(2019, 5, 12, 21, 51))
    a2 = w.available_day(d, datetime(2019, 9, 1, 20, 0))
    assert a1 == date(2019, 5, 14) and a2 == date(2019, 9, 3) and a2 > a1


# ---------------------------------------------------------------------------------------------
# (c) 真实数据
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not OBS_CSV.exists(), reason="full fetch not on disk")
def test_real_observations_obey_rule_and_have_no_duplicates() -> None:
    obs = pd.read_csv(OBS_CSV)
    assert list(obs.columns) == w.OBS_COLUMNS
    assert set(obs["key"]) == set(w.BOXES)
    assert not obs.duplicated(["key", "obs_date"]).any()
    # 排序:key 升序、其内 obs_date 升序
    sort_key = obs["key"] + " " + obs["obs_date"]
    assert sort_key.is_monotonic_increasing
    od = pd.to_datetime(obs["obs_date"])
    ad = pd.to_datetime(obs["available_day"])
    lm = pd.to_datetime(obs["last_modified_utc"], utc=True).dt.tz_convert(None)
    lag = (ad - od).dt.days
    assert (lag >= w.MIN_LAG_DAYS).all()
    # 逐行重算规则
    recomputed = [w.available_day(o.date(), m.to_pydatetime()) for o, m in zip(od, lm)]
    assert [a.date() for a in ad] == recomputed
    beijing = (lm + pd.Timedelta(hours=8)).dt.normalize()
    assert (ad >= beijing).all()
    assert (obs["rewrite_flag"] == (lag > w.MIN_LAG_DAYS)).all()
    assert obs["value"].notna().all() and (obs["value"] >= 0).all()
    assert (obs["n_cells"] > 0).all() and (obs["n_cells"] <= obs["n_box"]).all()
    expected_box = {k: b.n_box for k, b in w.BOXES.items()}
    assert obs.groupby("key")["n_box"].first().to_dict() == expected_box
    # 2006 年起、至少到 2026 年
    assert od.min().year == 2006 and od.max().year >= 2026


@pytest.mark.skipif(not OBS_CSV.exists(), reason="full fetch not on disk")
def test_real_load_recomputes_identically() -> None:
    obs = w.load(DATA_DIR)
    disk = pd.read_csv(OBS_CSV)
    assert len(obs) == len(disk)
    assert [d.isoformat() for d in obs["available_day"]] == disk["available_day"].tolist()
    assert obs["value"].to_numpy() == pytest.approx(disk["value"].to_numpy(), abs=1e-5)


@pytest.mark.skipif(not OBS_CSV.exists(), reason="full fetch not on disk")
def test_real_listing_fetched_no_earlier_than_values() -> None:
    """点时不变量:每年目录页(定可得日)的抓取时刻 ≥ 该年四个 NCSS 值文件的抓取时刻;否则两次抓取之间的
    重写会让"新值 + 旧时间戳"进表(前视)。反向偏差(目录更晚)只会更保守。"""
    for year in range(2006, 2027):
        side = w._read_sidecar(w.listing_path(DATA_DIR, year))
        assert side is not None, year
        listing_at = w._parse_iso_utc(str(side["fetched_at_utc"]))
        for key in w.BOXES:
            nc_side = w._read_sidecar(w.ncss_path(DATA_DIR, year, key))
            assert nc_side is not None, (year, key)
            assert listing_at >= w._parse_iso_utc(str(nc_side["fetched_at_utc"])), (year, key)


@pytest.mark.skipif(not (DATA_DIR / "raw" / "spotcheck.csv").exists(), reason="spot check not run")
def test_real_spotcheck_matches_cpc_binary() -> None:
    sc = pd.read_csv(DATA_DIR / "raw" / "spotcheck.csv")
    ok = sc[sc["status"] == "ok"]
    assert len(ok) >= 6 * len(w.BOXES)
    # 逐格:源分辨率 0.1 mm 的一半(实测除被重写的 2025-07-15 一格差 0.0089 mm 外全在 float32 舍入量级)
    assert (ok["cell_max_abs_diff"] < 0.05).all()
    assert (ok["mean_abs_diff"] < 1e-3).all()
    assert (ok["mask_mismatch"] == 0).all()
    assert (ok["n_cells_psl"] == ok["n_cells_rt"]).all()
