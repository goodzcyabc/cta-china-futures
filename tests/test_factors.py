"""因子库测试:合成数据上的方向与量纲、标准化、快速评估的成本与 IC 数学。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cta.factors.base import FactorInputs, standardize
from cta.factors.evaluate import _spearman_rows, deflated_sharpe, expected_max_sharpe
from cta.factors.library import (
    ALL_FACTORS,
    basis_mom,
    breakout,
    ewmac,
    oi_growth,
    reversal_st,
    seasonal,
    skew_neg,
)


def _inputs(px: pd.DataFrame, **over: pd.DataFrame) -> FactorInputs:
    ones = pd.DataFrame(1.0, index=px.index, columns=px.columns)
    kw = dict(
        adj_close=px,
        close=px,
        high=px * 1.01,
        low=px * 0.99,
        volume=ones * 1000,
        open_interest=ones * 5000,
        next_close=px * 1.02,
        days_to_next=ones * 30,
        contract=pd.DataFrame("C1", index=px.index, columns=px.columns),
        next_contract=pd.DataFrame("C2", index=px.index, columns=px.columns),
        oi_total=ones * 10000,
        volume_total=ones * 2000,
        vol=ones * 0.2,
        eligible=ones.astype(bool),
    )
    kw.update(over)
    return FactorInputs(**kw)  # type: ignore[arg-type]


def _trend_px(n: int = 700, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    up = 100 * np.exp(np.cumsum(0.0015 + 0.01 * rng.standard_normal(n)))
    down = 100 * np.exp(np.cumsum(-0.0015 + 0.01 * rng.standard_normal(n)))
    return pd.DataFrame({"UP": up, "DN": down}, index=idx)


def test_trend_factors_sign_and_range() -> None:
    x = _inputs(_trend_px())
    for fn in (ewmac, breakout):
        raw = fn(x)
        tail = raw.iloc[-100:]
        assert tail["UP"].mean() > 0 > tail["DN"].mean(), fn.__name__
    b = breakout(x).dropna()
    assert b.abs().max().max() <= 1.0 + 1e-9  # 通道位置在 [-1,1]


def test_reversal_and_skew_definitions() -> None:
    px = _trend_px()
    x = _inputs(px)
    r = reversal_st(x)
    # 价格突然跳高 → 12 日均价低于现价 → 因子为负(做空)
    px2 = px.copy()
    px2.iloc[-1] *= 1.10
    assert reversal_st(_inputs(px2)).iloc[-1]["UP"] < r.iloc[-1]["UP"]
    # 人造负偏:插入一次大跌 → 偏度为负 → skew_neg 为正
    px3 = px.copy()
    px3.iloc[-30:] *= 0.85
    assert skew_neg(_inputs(px3)).iloc[-1]["UP"] > 0


def test_basis_mom_only_counts_unchanged_contract_days() -> None:
    px = _trend_px()
    nxt = px * 1.0  # 次近月与近月同涨同跌 → 差为 0
    x = _inputs(px, next_close=nxt)
    assert np.allclose(basis_mom(x).dropna().to_numpy(), 0.0)
    # 换月日(合约身份变化)不计入
    c = pd.DataFrame("C1", index=px.index, columns=px.columns)
    c.iloc[-1] = "C9"
    nxt2 = nxt.copy()
    nxt2.iloc[-1] *= 0.5  # 只有换月当天差异巨大
    assert abs(basis_mom(_inputs(px, next_close=nxt2, contract=c)).iloc[-1]["UP"]) < 1e-9


def test_oi_growth_and_seasonal_no_lookahead() -> None:
    px = _trend_px(1000)
    oi = pd.DataFrame(10000.0, index=px.index, columns=px.columns)
    oi.iloc[-1] = 20000.0
    g = oi_growth(_inputs(px, oi_total=oi))
    assert abs(g.iloc[-1]["UP"] - np.log(2)) < 1e-9 and abs(g.iloc[-2]["UP"]) < 1e-9
    s_full = seasonal(_inputs(px))
    cut = px.index[-150]
    s_cut = seasonal(_inputs(px.loc[:cut]))
    common = s_cut.dropna(how="all").index
    assert len(common) > 0
    pd.testing.assert_frame_equal(s_full.loc[common], s_cut.loc[common])


def test_standardize_ranges_and_xs_uses_only_eligible() -> None:
    idx = pd.bdate_range("2019-01-01", periods=400)
    rng = np.random.default_rng(1)
    raw = pd.DataFrame(rng.standard_normal((400, 5)), index=idx, columns=list("ABCDE"))
    elig = pd.DataFrame(True, index=idx, columns=raw.columns)
    z_ts = standardize(raw, "ts", elig)
    assert z_ts.dropna().abs().max().max() <= 1.0 + 1e-9 and z_ts.iloc[:100].isna().all().all()
    elig["E"] = False
    z_xs = standardize(raw, "xs", elig)
    assert z_xs["E"].isna().all() and abs(z_xs[list("ABCD")].mean(axis=1)).max() < 1e-9


def test_spearman_rows_and_dsr_math() -> None:
    idx = pd.bdate_range("2020-01-01", periods=3)
    a = pd.DataFrame(np.arange(30, dtype=float).reshape(3, 10), index=idx)
    r = _spearman_rows(a, a)
    assert np.allclose(r.to_numpy(), 1.0)
    assert np.allclose(_spearman_rows(a, -a).to_numpy(), -1.0)
    assert (
        expected_max_sharpe(1, 0.4) == 0.0 and expected_max_sharpe(20, 0.4) > expected_max_sharpe(5, 0.4) > 0
    )
    idx2 = pd.bdate_range("2016-01-01", periods=1500)
    good = pd.Series(0.0008 + 0.006 * np.random.default_rng(2).standard_normal(1500), index=idx2)
    d1 = deflated_sharpe(good, 1, 0.4)
    d20 = deflated_sharpe(good, 20, 0.4)
    assert 0 <= d20["DSR"] < d1["DSR"] <= 1


def test_registry_covers_preregistered_ids() -> None:
    names = {f.name for f in ALL_FACTORS}
    expected = {
        "tsmom",
        "carry",
        "ewmac",
        "breakout",
        "reversal_st",
        "basis_mom",
        "skew_neg",
        "oi_growth",
        "seasonal",
        "carry_xs",
        "mom_xs",
        "lowrisk_xs",
        "htfc_a19",
    }
    assert names == expected
    assert sum(not f.reference for f in ALL_FACTORS) == 11
