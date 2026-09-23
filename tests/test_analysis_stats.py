"""配对差统计:日收益用各自前一日权益、共同日期规则、Newey–West 小样本手算核对、块 bootstrap 固定种子可复现。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cta.analysis.stats import (
    block_bootstrap_mean,
    daily_returns,
    newey_west_mean,
    paired_differences,
    paired_summary,
)


def test_paired_returns_use_each_books_own_previous_equity_and_common_dates() -> None:
    d = pd.bdate_range("2026-09-23", periods=5)
    a = pd.Series([100.0, 101.0, 102.0, 100.0, 104.0], index=d)  # champion 全有
    b = pd.Series([200.0, 202.0, 198.0, 206.0], index=d[[0, 1, 3, 4]])  # challenger 缺第 3 天
    p = paired_differences(a, b)
    # 只保留 t 与 t−1 在两本账里都相邻的日期:d1(相对 d0)与 d4(相对 d3);d3 被跳过(a 在 d2 多了一天)
    assert list(p.index) == [d[1], d[4]]
    assert p.loc[d[1], "r_champion"] == pytest.approx(101 / 100 - 1) and p.loc[
        d[1], "r_challenger"
    ] == pytest.approx(202 / 200 - 1)
    assert p.loc[d[4], "r_champion"] == pytest.approx(104 / 100 - 1)  # 用 a 自己前一日(d3=100)权益
    assert p.loc[d[4], "r_challenger"] == pytest.approx(206 / 198 - 1)  # 用 b 自己前一日(d3=198)权益
    assert p.loc[d[4], "d"] == pytest.approx((206 / 198 - 1) - (104 / 100 - 1))
    assert daily_returns(a).iloc[0] == pytest.approx(0.01)


def test_newey_west_matches_hand_computation() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    r0 = newey_west_mean(x, lags=0)
    assert r0.mean == 3.5 and r0.se == pytest.approx(
        np.sqrt(x.var(ddof=0) / 6)
    )  # lag 0 = 经典(总体方差)标准误
    r2 = newey_west_mean(x, lags=2)
    e = x - x.mean()
    g0 = float(np.dot(e, e) / 6)
    g1 = float(np.dot(e[1:], e[:-1]) / 6)
    g2 = float(np.dot(e[2:], e[:-2]) / 6)
    s = g0 + 2 * ((1 - 1 / 3) * g1 + (1 - 2 / 3) * g2)
    assert (
        r2.se == pytest.approx(np.sqrt(s / 6))
        and r2.t == pytest.approx(3.5 / np.sqrt(s / 6))
        and r2.lags == 2
    )
    assert r2.se == pytest.approx(0.91033, abs=1e-4)  # 手算:S = 29.8333/6
    assert newey_west_mean(x, lags=10).lags == 5  # lag 上限 n−1


def test_block_bootstrap_fixed_seed_reproducible() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(0.001, 0.01, size=120)
    a = block_bootstrap_mean(x, block=10, n_boot=500, seed=7)
    b = block_bootstrap_mean(x, block=10, n_boot=500, seed=7)
    c = block_bootstrap_mean(x, block=10, n_boot=500, seed=8)
    assert (
        (a.ci_low, a.ci_high) == (b.ci_low, b.ci_high) and a.seed == 7 and a.n_boot == 500 and a.block == 10
    )
    assert (a.ci_low, a.ci_high) != (c.ci_low, c.ci_high)
    assert a.ci_low < x.mean() < a.ci_high


def test_paired_summary_flags_short_samples_and_reports_seed() -> None:
    d = pd.bdate_range("2026-09-23", periods=12)
    a = pd.Series(np.linspace(100, 101, 12), index=d)
    b = pd.Series(np.linspace(100, 100.5, 12), index=d)
    s = paired_summary(a, b, lags=5, block=10, n_boot=100, seed=3)
    assert (
        s["n_days"] == 11 and s["sample_sufficient"] is False and s["boot_seed"] == 3 and s["boot_n"] == 100
    )
    assert s["dd_diff"] == pytest.approx(0.0) and s["first_date"] == str(d[1].date())
