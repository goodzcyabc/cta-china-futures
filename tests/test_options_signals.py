"""商品期权三条(预注册 docs/options_prereg.md 第 8 节):Black-76 反解、系列选择只用当日信息、未成交不进 O1、
可得日与截断不变、RV 只用 ≤ T、双边计数不影响成交均价。真实数据存在时检查整表。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.analysis import options_signals as os_


def test_black76_roundtrip() -> None:
    rng = np.random.default_rng(0)
    n = 400
    f = rng.uniform(50, 5000, n)
    k = f * rng.uniform(0.7, 1.3, n)
    tau = rng.uniform(0.03, 0.8, n)
    sig = rng.uniform(0.08, 0.9, n)
    is_call = rng.random(n) < 0.5
    p = os_.black76_price(f, k, tau, sig, is_call)
    iv = os_.black76_iv(p, f, k, tau, is_call)
    ok = np.isfinite(iv)
    assert ok.mean() > 0.95
    assert np.allclose(iv[ok], sig[ok], atol=1e-4)  # 深度实值合约 vega 极小,反解精度受限
    # 价格低于折现内在价值 → NaN
    bad = os_.black76_iv(
        np.array([0.0]), np.array([100.0]), np.array([90.0]), np.array([0.2]), np.array([True])
    )
    assert np.isnan(bad[0])


def _day(t: str, rows: list[tuple[str, str, float, float, float, float, float]]) -> pd.DataFrame:
    """rows: (underlying, cp, strike, settle, volume, delta, iv)。series_oi / series_volume 按系列合计。"""
    df = pd.DataFrame(
        rows, columns=["underlying", "cp", "strike", "settle", "volume", "delta", "iv_exchange"]
    )
    df["date"] = pd.Timestamp(t)
    df["available_day"] = pd.Timestamp(t) + pd.Timedelta(days=1)
    df["oi"] = 100.0
    df["series_oi"] = df.groupby("underlying")["oi"].transform("sum")
    df["series_volume"] = df.groupby("underlying")["volume"].transform("sum")
    df["exchange"] = "CZCE"
    df["product"] = "SR"
    df["turnover"] = df["volume"] * df["settle"] * 10.0
    df["expire_date"] = pd.NaT
    df["close"] = df["settle"]
    df["option_code"] = [f"{u}{c}{int(k)}" for u, c, k in zip(df["underlying"], df["cp"], df["strike"])]
    return df


def test_series_selection_uses_month_rule_and_max_oi() -> None:
    d = _day(
        "2024-03-15",
        [("SR2405", "C", 6000, 50, 10, 0.3, 0.2)] * 5
        + [("SR2407", "C", 6000, 80, 5, 0.3, 0.2)] * 3
        + [("SR2409", "C", 6000, 90, 1, 0.3, 0.2)] * 2,
    )
    # 2405 交割月 = 3 月 + 2 → 允许;持仓最大 → 选中
    assert os_.select_series(d, pd.Timestamp("2024-03-15")) == "SR2405"
    # 4 月 1 日起 2405 不再满足 ≥ 当月 + 2
    assert os_.select_series(d, pd.Timestamp("2024-04-01")) == "SR2407"
    # 选中系列当日零成交 → None
    d0 = d.copy()
    d0.loc[d0["underlying"] == "SR2405", "series_volume"] = 0.0
    assert os_.select_series(d0, pd.Timestamp("2024-03-15")) is None


def _panel(n_days: int = 320, untraded_wing: bool = False) -> tuple[pd.DataFrame, pd.Series, pd.Series]:  # type: ignore[type-arg]
    dates = pd.bdate_range("2023-01-02", periods=n_days)
    frames = []
    settles = {}
    for i, t in enumerate(dates):
        und = "SR2409" if t < pd.Timestamp("2024-06-01") else "SR2501"
        f = 6000.0 + 10 * np.sin(i / 10)
        settles[(t, und)] = f
        call_iv = 0.20 + 0.02 * np.sin(i / 7)
        atm_iv = 0.19 + 0.03 * np.sin(i / 23)
        rows = [
            (und, "C", 6200, 50, 0 if untraded_wing else 20, 0.30, call_iv),
            (und, "P", 5800, 45, 20, -0.30, 0.20),
            (und, "C", 6000, 120, 50, 0.52, atm_iv),
            (und, "P", 6000, 118, 50, -0.48, atm_iv),
        ]
        frames.append(_day(str(t.date()), rows))
    opts = pd.concat(frames, ignore_index=True)
    adj = pd.Series(6000.0 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, n_days))), index=dates)
    return opts, pd.Series(settles), adj


def test_daily_features_skew_vrp_detrend_and_untraded_excluded() -> None:
    opts, settles, adj = _panel()
    feats = os_.product_daily_features(opts, settles, adj, "SR", multiplier=10.0)
    tab = feats.table
    i = 50
    expect = ((0.20 + 0.02 * np.sin(i / 7)) - 0.20) / 0.20
    assert tab["skew"].iloc[i] == pytest.approx(expect, abs=1e-12)
    assert tab["sigma_a"].iloc[i] == pytest.approx(0.19 + 0.03 * np.sin(i / 23))
    assert np.isnan(tab["rv"].iloc[10]) and np.isfinite(tab["rv"].iloc[30])
    assert np.isfinite(tab["iv_detrended"].iloc[200]) and np.isnan(tab["iv_detrended"].iloc[100])
    # 看涨翼未成交 → O1 无值
    opts2, settles2, adj2 = _panel(untraded_wing=True)
    tab2 = os_.product_daily_features(opts2, settles2, adj2, "SR", multiplier=10.0).table
    assert tab2["skew"].isna().all() and tab2["sigma_a"].notna().all()


def test_rv_uses_only_past_prices_and_truncation_invariance() -> None:
    opts, settles, adj = _panel()
    full = os_.product_daily_features(opts, settles, adj, "SR", 10.0).table
    cut = pd.Timestamp("2023-10-31")
    adj2 = adj.copy()
    adj2[adj2.index > cut] *= 1.5  # 未来价格改变
    opts2 = opts[opts["date"] <= cut]
    part = os_.product_daily_features(opts2, settles, adj2, "SR", 10.0).table
    cols = ["skew", "sigma_a", "rv", "vrp", "skew5", "vrp5", "iv_detrended"]
    a = full[full["date"] <= cut][cols].to_numpy(dtype=float)
    b = part[cols].to_numpy(dtype=float)
    assert np.allclose(a, b, equal_nan=True)


def test_candidate_signal_availability_and_determinism() -> None:
    opts, settles, adj = _panel(n_days=480)
    feats = {"SR": os_.product_daily_features(opts, settles, adj, "SR", 10.0)}
    dates = pd.bdate_range("2023-01-02", "2024-10-31")
    c1 = os_.build_candidate("O1", feats, dates, ["SR", "CU"])
    c2 = os_.build_candidate("O1", feats, dates, ["SR", "CU"])
    assert c1.signal.equals(c2.signal)
    assert c1.signal["CU"].isna().all()
    first = c1.signal["SR"].first_valid_index()
    assert first is not None and first > pd.Timestamp("2023-12-01")  # 至少 250 个可得观测
    assert (c1.audit["target_day"] >= c1.audit["available_day"]).all()
    o3 = os_.build_candidate("O3", feats, dates, ["SR"])
    assert o3.signal["SR"].dropna().abs().max() <= 1.0


@pytest.mark.parametrize("name", ["shfe_options", "czce_options"])
def test_real_option_tables_contract(name: str) -> None:
    path = Path("data/external/alt") / name / "options_daily.parquet"
    if not path.exists():
        pytest.skip(f"需要 {path}")
    df = pd.read_parquet(path)
    assert not df.duplicated(["date", "option_code"]).any()
    assert (pd.to_datetime(df["available_day"]) > pd.to_datetime(df["date"])).all()
    puts = df[df["cp"] == "P"]
    assert (puts["delta"].dropna() <= 1e-9).all()
