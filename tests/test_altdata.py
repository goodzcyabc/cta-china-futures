"""另类数据五条(预注册 docs/research/altdata_prereg.md 第 9 节):可得日规则、目标日、冻结、截断不变、噪声不变、版本拼接、重写延后、确定性、失效、
基线复现与混合凸性由 tests/test_fundamental_signals.py 覆盖;真实数据存在时再检查整表。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.analysis import altdata_signals as alt

DATA = Path("data/external/alt")


def _dates(start: str = "2016-01-04", end: str = "2019-12-31") -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


def _obs(
    key: str, start: str, n: int, lag: int, values: np.ndarray[object, object] | None = None, freq: str = "D"
) -> pd.DataFrame:
    od = pd.date_range(start, periods=n, freq=freq)
    v = np.random.default_rng(0).normal(size=n) if values is None else values
    return pd.DataFrame(
        {"obs_date": od, "available_day": od + pd.Timedelta(days=lag), "key": key, "value": v}
    )


def test_min_lag_is_enforced() -> None:
    bad = _obs("Q-HEBEI4", "2016-01-01", 10, lag=0)
    with pytest.raises(ValueError, match="available_day earlier"):
        alt.check_min_lag(bad, "Q")
    alt.check_min_lag(_obs("Q-HEBEI4", "2016-01-01", 10, lag=1), "Q")


def test_target_day_is_first_trading_day_on_or_after_available_and_signal_frozen_until_next() -> None:
    dates = _dates()
    obs = _obs("X", "2015-01-01", 800, lag=1)  # 日频,可得日 = 次日
    feat = alt.point_feature(obs)
    s, audit = alt.pit_signal(feat, dates, min_obs=100, stale_days=7, sign=1.0)
    assert (audit["target_day"] >= audit["available_day"]).all()  # 目标日不早于可得日
    assert (audit["exec_day"] > audit["target_day"]).all()  # 建仓日严格晚于目标日
    # 周六可得的观测(周五观测 + 1 日)目标日是下周一
    fri = pd.Timestamp("2016-03-04")
    row = audit[audit["data_date"] == fri].iloc[0]
    assert row["available_day"] == fri + pd.Timedelta(days=1) and row["target_day"] == pd.Timestamp(
        "2016-03-07"
    )
    # 更新之间冻结:相邻两次更新的目标日之间信号不变
    tds = sorted(audit["target_day"].tolist())
    for a, b in zip(tds[:-1], tds[1:]):
        seg = s[(s.index >= a) & (s.index < b)].dropna()
        assert seg.nunique() <= 1


def test_expanding_z_uses_only_available_values_and_truncation_invariance() -> None:
    dates = _dates()
    obs = _obs("X", "2015-01-01", 1200, lag=4)
    feat = alt.point_feature(obs)
    s, _ = alt.pit_signal(feat, dates, min_obs=300, stale_days=10, sign=-1.0)
    cut = pd.Timestamp("2018-06-30")
    trunc = obs[obs["available_day"] <= cut]
    s2, _ = alt.pit_signal(alt.point_feature(trunc), dates, min_obs=300, stale_days=10, sign=-1.0)
    assert np.allclose(s[s.index <= cut].to_numpy(), s2[s2.index <= cut].to_numpy(), equal_nan=True)
    # cutoff 之后注入噪声:cutoff 及以前的信号不变
    noisy = obs.copy()
    fut = noisy["available_day"] > cut
    noisy.loc[fut, "value"] = noisy.loc[fut, "value"] + 100.0
    s3, _ = alt.pit_signal(alt.point_feature(noisy), dates, min_obs=300, stale_days=10, sign=-1.0)
    assert np.allclose(s[s.index <= cut].to_numpy(), s3[s3.index <= cut].to_numpy(), equal_nan=True)
    first_valid = s.first_valid_index()
    assert first_valid is not None and first_valid >= obs["available_day"].iloc[299]  # 不足 min_obs 时无信号
    assert s.abs().max() <= 1.0 + 1e-12
    assert s.equals(alt.pit_signal(feat, dates, min_obs=300, stale_days=10, sign=-1.0)[0])  # 确定性


def test_rewritten_file_delays_availability_of_every_window_containing_it() -> None:
    obs = _obs("W-P", "2015-01-01", 400, lag=4, values=np.ones(400))
    late = pd.Timestamp("2015-06-01")
    obs.loc[obs["obs_date"] == late, "available_day"] = late + pd.Timedelta(days=120)  # 该日文件 120 天后重写
    f = alt.rolling_feature(obs, 90, 80, "sum")
    tab = pd.DataFrame({"obs": f.obs_date, "av": f.available_day})
    inwin = (tab["obs"] >= late) & (tab["obs"] < late + pd.Timedelta(days=90))
    assert (tab.loc[inwin, "av"] == late + pd.Timedelta(days=120)).all()  # 含该日的 90 个窗口全部延后
    assert (tab.loc[~inwin, "av"] == tab.loc[~inwin, "obs"] + pd.Timedelta(days=4)).all()


def test_stale_expiry_and_no_zero_fill() -> None:
    dates = _dates("2016-01-04", "2017-12-31")
    obs = _obs("E-NINO34", "2010-01-06", 300, lag=7, freq="7D")
    obs = obs[obs["obs_date"] < "2016-06-01"]  # 2016-06 起停更
    s, _ = alt.pit_signal(alt.point_feature(obs), dates, min_obs=104, stale_days=21, sign=1.0)
    last_av = obs["available_day"].max()
    assert s[s.index > last_av + pd.Timedelta(days=21)].isna().all()
    assert (
        s[(s.index <= last_av + pd.Timedelta(days=21)) & (s.index >= pd.Timestamp("2016-02-01"))]
        .notna()
        .all()
    )


def test_w_climatology_uses_base_years_only() -> None:
    n = 365 * 12
    od = pd.date_range("2006-01-01", periods=n, freq="D")
    rng = np.random.default_rng(1)
    v = 5 + 3 * np.sin(2 * np.pi * od.dayofyear.to_numpy() / 365.25) + rng.normal(0, 0.5, n)
    v = np.clip(v, 0, None)
    obs = pd.DataFrame({"obs_date": od, "available_day": od + pd.Timedelta(days=4), "key": "W-P", "value": v})
    f1 = alt.w_feature(obs)
    obs2 = obs.copy()
    obs2.loc[obs2["obs_date"] >= "2016-01-01", "value"] *= 3.0  # 窗口内的值改变,基线(2006–2015)不变
    f2 = alt.w_feature(obs2)
    m = f1.obs_date < pd.Timestamp("2016-01-01")
    assert np.allclose(f1.value[m], f2.value[: int(m.sum())])


def test_n_feature_requires_min_presence_and_basket_rule() -> None:
    obs = _obs("N-CU", "2017-01-01", 400, lag=2)
    obs["n_articles"] = 50.0
    obs = obs.drop(obs.index[100:160])  # 60 天空洞
    f = alt.n_feature(obs)
    gap_days = pd.date_range(obs["obs_date"].iloc[99], periods=3, freq="D")[1:]
    assert not any(d in f.obs_date for d in gap_days)
    obs2 = obs.copy()
    obs2["key"] = "N-TA"
    obs2["n_articles"] = 3.0
    med = alt.n_basket(pd.concat([obs, obs2]))
    assert med["CU"] == 50.0 and med["TA"] == 3.0


# ---------- 真实数据(存在时) ----------
@pytest.mark.parametrize(
    "name,src,lag",
    [
        ("cpc_precip", "W", 4),
        ("nino34", "E", 7),
        ("gdelt_tone", "N", 2),
        ("shfe_weekly", "S", 1),
        ("hebei_pm25", "Q", 1),
    ],
)
def test_real_observation_tables_obey_lag_rule(name: str, src: str, lag: int) -> None:
    path = DATA / name / "observations.csv"
    if not path.exists():
        pytest.skip(f"需要 {path}")
    df = alt.load_observations(path)
    alt.check_min_lag(df, src)
    assert not df.duplicated(["key", "obs_date"]).any()
    assert (df["value"].abs() < 1e12).all() and df["value"].notna().all()
    assert ((df["available_day"] - df["obs_date"]).dt.days >= lag).all()
