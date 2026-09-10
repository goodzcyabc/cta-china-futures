import numpy as np
import pandas as pd

from cta.signals.core import (
    cap_gross_exposure,
    carry,
    carry_signal,
    combine,
    realized_vol,
    trade_buffer,
    tsmom,
    vol_target_positions,
)


def _px(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    noise = 0.002 * rng.normal(size=n)  # 噪声远小于漂移,方向确定
    up = 100 * np.exp(np.cumsum(0.003 + noise))  # 趟势向上
    dn = 100 * np.exp(np.cumsum(-0.003 + noise))  # 趟势向下
    return pd.DataFrame({"UP": up, "DN": dn}, index=idx)


def test_tsmom_signs_and_range() -> None:
    px = _px()
    s = tsmom(px)
    assert s.iloc[-1]["UP"] > 0 and s.iloc[-1]["DN"] < 0
    assert ((s.abs() <= 1) | s.isna()).all().all()
    v = realized_vol(px)
    s2 = tsmom(px, vol=v)
    assert ((s2.abs() <= 1) | s2.isna()).all().all()
    # 前 252 天至少有一个回看期缺失,但 21 天期有值 -> 不应全 NaN
    assert s.iloc[30].notna().all()


def test_carry_direction_and_units() -> None:
    idx = pd.bdate_range("2021-01-01", periods=3)
    near = pd.DataFrame({"A": [105.0, 105.0, 105.0]}, index=idx)
    nxt = pd.DataFrame({"A": [100.0, 100.0, 100.0]}, index=idx)
    days = pd.DataFrame({"A": [60, 60, 60]}, index=idx)
    c = carry(near, nxt, days)
    assert abs(c.iloc[0, 0] - 0.05 * 365 / 60) < 1e-12  # 5% 升水,60 天 -> 年化 30.4%
    assert 0 < carry_signal(c).iloc[0, 0] < 1
    assert carry_signal(-c).iloc[0, 0] < 0


def test_combine_and_vol_target() -> None:
    idx = pd.bdate_range("2021-01-01", periods=5)
    a = pd.DataFrame({"X": [1, 1, 1, 1, 1.0], "Y": [np.nan] * 5}, index=idx)
    b = pd.DataFrame({"X": [-1, -1, -1, -1, -1.0], "Y": [0.5] * 5}, index=idx)
    c = combine({"a": a, "b": b})
    assert (c["X"] == 0).all() and (c["Y"] == 0.5).all()  # Y 只有 b 有值 -> 不被 NaN 拉低
    # 事前波动缩放:两只不相关、日波动 1% 的品种,等权做多,目标年化 10% -> 组合年化波动应≈10%
    rng = np.random.default_rng(1)
    n = 300
    px = pd.DataFrame(
        100 * np.exp(np.cumsum(0.01 * rng.normal(size=(n, 2)), axis=0)),
        index=pd.bdate_range("2020-01-01", periods=n),
        columns=["X", "Y"],
    )
    vol = realized_vol(px, 40)
    sig = pd.DataFrame(1.0, index=px.index, columns=px.columns)
    w = vol_target_positions(sig, vol, px, target_vol=0.10, window=60, max_leverage_per_symbol=5.0)
    last = w.iloc[-1]
    r = np.log(px).diff().iloc[-60:]
    port_vol = float(np.sqrt(last.to_numpy() @ r.cov().to_numpy() @ last.to_numpy() * 243))
    assert abs(port_vol - 0.10) < 1e-6
    assert ((w.abs() <= 5.0) | w.isna()).all().all() and w.iloc[:60].isna().all().all()


def test_trade_buffer() -> None:
    tgt = pd.Series({"X": 1.0, "Y": 0.0, "Z": -1.0})
    cur = pd.Series({"X": 0.9, "Y": 0.1, "Z": 0.0})
    out = trade_buffer(tgt, cur, band=0.2)
    assert out["X"] == 0.9  # 差 0.1 < 0.2 -> 不动
    assert out["Y"] == 0.0  # 目标 0,阈值 0 -> 平掉
    assert out["Z"] == -1.0  # 差 1 > 0.2 -> 交易


def test_cap_gross_exposure() -> None:
    idx = pd.bdate_range("2021-01-01", periods=2)
    w = pd.DataFrame({"X": [2.0, 0.5], "Y": [-2.0, 0.5]}, index=idx)
    out = cap_gross_exposure(w, 3.0)
    assert (
        abs(out.iloc[0].abs().sum() - 3.0) < 1e-12 and (out.iloc[1] == w.iloc[1]).all()
    )  # 超限缩到 3,未超限不动
