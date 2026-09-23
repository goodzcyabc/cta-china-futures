"""配对差统计(纸面验收,设计日志 18.3):日收益构造、Newey–West 均值标准误、固定种子的块 bootstrap、配对汇总。

- 每本账的日收益 r_t = equity_t / equity_{t−1} − 1,分母是**自身**前一交易日权益;
- 配对差只用双方共同有效日期:t 与 t 的前一交易日都在两本账里,且两本账在 (t−1, t] 之间都没有多出来的日期;
- d_t = r_t^challenger − r_t^champion。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from cta.risk.metrics import TRADING_DAYS, drawdown


@dataclass(frozen=True)
class NWResult:
    mean: float
    se: float
    t: float
    n: int
    lags: int


@dataclass(frozen=True)
class BootResult:
    ci_low: float
    ci_high: float
    n_boot: int
    block: int
    seed: int
    mean_of_means: float


def daily_returns(equity: pd.Series[Any]) -> pd.Series[Any]:
    eq = equity.dropna().astype(float)
    out: pd.Series[Any] = eq / eq.shift(1) - 1.0
    return out.dropna()


def paired_differences(champion: pd.Series[Any], challenger: pd.Series[Any]) -> pd.DataFrame:
    """共同有效日期上的 (r_champion, r_challenger, d)。"""
    a = champion.dropna().astype(float)
    b = challenger.dropna().astype(float)
    a.index, b.index = pd.DatetimeIndex(a.index), pd.DatetimeIndex(b.index)
    common = a.index.intersection(b.index).sort_values()
    pos_a = {ts: i for i, ts in enumerate(a.index)}
    pos_b = {ts: i for i, ts in enumerate(b.index)}
    rows = []
    for i in range(1, len(common)):
        t, p = common[i], common[i - 1]
        ia, ib = pos_a[t], pos_b[t]
        if (
            a.index[ia - 1] != p or b.index[ib - 1] != p
        ):  # 任一本在 (p, t] 之间多了一天 → 两边的"日收益"跨度不同,跳过
            continue
        ra, rb = float(a.loc[t] / a.loc[p] - 1.0), float(b.loc[t] / b.loc[p] - 1.0)
        rows.append({"date": t, "r_champion": ra, "r_challenger": rb, "d": rb - ra})
    return pd.DataFrame(rows, columns=["date", "r_champion", "r_challenger", "d"]).set_index("date")


def newey_west_mean(x: np.ndarray[Any, Any], lags: int = 5) -> NWResult:
    """均值的 Newey–West(Bartlett 核)标准误:S = γ0 + 2 Σ_{l=1..L} (1 − l/(L+1)) γ_l,se = sqrt(S / n)。"""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    n = int(len(v))
    if n < 2:
        return NWResult(float(v.mean()) if n else float("nan"), float("nan"), float("nan"), n, lags)
    m = float(v.mean())
    e = v - m
    lag_max = min(lags, n - 1)
    s = float(np.dot(e, e) / n)
    for lag in range(1, lag_max + 1):
        gamma = float(np.dot(e[lag:], e[:-lag]) / n)
        s += 2.0 * (1.0 - lag / (lag_max + 1.0)) * gamma
    se = float(np.sqrt(max(s, 0.0) / n))
    t = m / se if se > 0 else float("nan")
    return NWResult(m, se, t, n, lag_max)


def block_bootstrap_mean(
    x: np.ndarray[Any, Any],
    block: int = 10,
    n_boot: int = 2000,
    seed: int = 20260923,
    alpha: float = 0.05,
) -> BootResult:
    """移动块 bootstrap:块起点在 [0, n−block] 均匀有放回抽取,拼到长度 n;固定种子可复现。"""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    n = int(len(v))
    if n == 0:
        return BootResult(float("nan"), float("nan"), n_boot, block, seed, float("nan"))
    b = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / b))
    starts = rng.integers(0, n - b + 1, size=(n_boot, n_blocks))
    offs = np.arange(b)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = v[idx].mean(axis=1)
    lo, hi = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return BootResult(float(lo), float(hi), n_boot, b, seed, float(means.mean()))


def sharpe_daily(r: pd.Series[Any]) -> float:
    v = r.to_numpy(dtype=float)
    return (
        float(v.mean() / v.std(ddof=1) * np.sqrt(TRADING_DAYS))
        if len(v) > 2 and v.std(ddof=1) > 0
        else float("nan")
    )


def max_drawdown(equity: pd.Series[Any]) -> float:
    eq = equity.dropna().astype(float)
    return float(drawdown(eq).min()) if len(eq) else float("nan")


def paired_summary(
    champion: pd.Series[Any],
    challenger: pd.Series[Any],
    lags: int = 5,
    block: int = 10,
    n_boot: int = 2000,
    seed: int = 20260923,
    min_days: int = 60,
) -> dict[str, Any]:
    """配对差的年化均值、NW 标准误与 t、块 bootstrap 95% 区间;各账净夏普(日频年化)与最大回撤;回撤差;样本量标记。"""
    pdf = paired_differences(champion, challenger)
    d = pdf["d"].to_numpy(dtype=float)
    nw = newey_west_mean(d, lags)
    bt = block_bootstrap_mean(d, block, n_boot, seed)
    common = pdf.index
    eq_a = champion.dropna().astype(float)
    eq_b = challenger.dropna().astype(float)
    eq_a.index, eq_b.index = pd.DatetimeIndex(eq_a.index), pd.DatetimeIndex(eq_b.index)
    if len(common):
        lo, hi = common.min(), common.max()
        first = eq_a.index[eq_a.index < lo].max() if (eq_a.index < lo).any() else lo
        eq_a, eq_b = eq_a.loc[first:hi], eq_b.loc[first:hi]
    mdd_a, mdd_b = max_drawdown(eq_a), max_drawdown(eq_b)
    return {
        "n_days": int(nw.n),
        "sample_sufficient": bool(nw.n >= min_days),
        "mean_daily": nw.mean,
        "ann_mean": nw.mean * TRADING_DAYS,
        "nw_se_ann": nw.se * TRADING_DAYS,
        "nw_lags": nw.lags,
        "t": nw.t,
        "boot_ci_low_ann": bt.ci_low * TRADING_DAYS,
        "boot_ci_high_ann": bt.ci_high * TRADING_DAYS,
        "boot_n": bt.n_boot,
        "boot_block": bt.block,
        "boot_seed": bt.seed,
        "sharpe_champion_daily": sharpe_daily(pdf["r_champion"]) if len(pdf) else float("nan"),
        "sharpe_challenger_daily": sharpe_daily(pdf["r_challenger"]) if len(pdf) else float("nan"),
        "mdd_champion": mdd_a,
        "mdd_challenger": mdd_b,
        "dd_diff": mdd_b - mdd_a,  # 负值 = challenger 回撤更深
        "first_date": str(common.min().date()) if len(common) else None,
        "last_date": str(common.max().date()) if len(common) else None,
    }
