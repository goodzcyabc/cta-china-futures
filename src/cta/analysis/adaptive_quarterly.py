"""季度自适应 v1(预注册 docs/adaptive_quarterly_v1_prereg.md,提交 97f525c;试验 47–49)。

三个核心因子 sleeve(tsmom、carry、receipts_level)的组合权重每季度末重训、下一季冻结:
- M1(主):EWMA(半衰期 1 年)年化夏普评分 → score = max(ŝ, 0) 归一 → 向等权收缩 κ = 0.6 → 上限 0.5(超出按比例再分配);
- A1(消融):统计量改为 3 年硬滚动窗口;
- A2(消融):EWMA 均值与向对角收缩 50% 的协方差 → Σ⁻¹μ 非负投影 → 同样收缩与上限。
权重非负、和为 1、∈ [κ/3, w_max];因子信号本身仍多空;季内不重估;只用 ≤ cutoff 的 sleeve 收益。
所有常数在预注册第 3 节写定,本模块不提供任何搜索接口。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from cta.risk.metrics import TRADING_DAYS

FACTORS: tuple[str, ...] = ("tsmom", "carry", "receipts_level")
H_YEARS = 1.0  # EWMA 半衰期
KAPPA = 0.6  # 向等权收缩强度
W_MAX = 0.5  # 单因子上限
WINDOW_A1 = 729  # A1 硬滚动窗口(交易日)≈ 3 年
COV_SHRINK = 0.5  # A2 协方差向对角收缩
CARRY_DOWN = 0.25  # "carry 明显降权"阈值
METHODS = ("M1", "A1", "A2")


@dataclass(frozen=True)
class WeightRecord:
    cutoff: pd.Timestamp
    method: str
    n_obs: int
    n_eff: float
    mu_ann: dict[str, float]
    vol_ann: dict[str, float]
    sharpe: dict[str, float]
    corr: dict[str, float]  # "tsmom~carry" 等
    w_raw: dict[str, float]
    w_shr: dict[str, float]
    w_final: dict[str, float]
    at_bound: bool = field(default=False)


def ewma_lambda(h_years: float = H_YEARS) -> float:
    return float(0.5 ** (1.0 / (TRADING_DAYS * h_years)))


def _prep(returns: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """只用 ≤ cutoff 且三个 sleeve 都有值的行(升序)。"""
    r = returns.loc[:, list(FACTORS)].astype(float)
    r.index = pd.DatetimeIndex(r.index)
    r = r[r.index <= cutoff].dropna(how="any").sort_index()
    return r


def _weighted_stats(
    r: pd.DataFrame, w: npt.NDArray[np.float64]
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], float]:
    w = w / w.sum()
    x = r.to_numpy(dtype=float)
    mu = w @ x
    dev = x - mu
    cov = (dev * w[:, None]).T @ dev
    sd = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(sd, sd)
    n_eff = float(1.0 / np.sum(w**2))
    names = list(FACTORS)
    mu_ann = {f: float(mu[i] * TRADING_DAYS) for i, f in enumerate(names)}
    vol_ann = {f: float(sd[i] * np.sqrt(TRADING_DAYS)) for i, f in enumerate(names)}
    sharpe = {
        f: float(mu[i] / sd[i] * np.sqrt(TRADING_DAYS)) if sd[i] > 1e-9 else float("nan")
        for i, f in enumerate(names)
    }
    cr = {f"{names[i]}~{names[j]}": float(corr[i, j]) for i in range(3) for j in range(i + 1, 3)}
    return mu_ann, vol_ann, sharpe, cr, n_eff


def ewma_stats(
    returns: pd.DataFrame, cutoff: pd.Timestamp, h_years: float = H_YEARS
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], float, int]:
    r = _prep(returns, cutoff)
    if len(r) < 60:
        raise ValueError(f"{cutoff.date()}: only {len(r)} joint sleeve observations")
    lam = ewma_lambda(h_years)
    k = np.arange(len(r))[::-1]  # 最近一行 k=0
    w = lam**k
    mu, vol, sh, cr, n_eff = _weighted_stats(r, w)
    return mu, vol, sh, cr, n_eff, int(len(r))


def rolling_stats(
    returns: pd.DataFrame, cutoff: pd.Timestamp, window: int = WINDOW_A1
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float], float, int]:
    r = _prep(returns, cutoff).tail(window)
    if len(r) < 60:
        raise ValueError(f"{cutoff.date()}: only {len(r)} joint sleeve observations")
    w = np.ones(len(r))
    mu, vol, sh, cr, n_eff = _weighted_stats(r, w)
    return mu, vol, sh, cr, n_eff, int(len(r))


def cap_and_renormalize(w: dict[str, float], w_max: float = W_MAX) -> dict[str, float]:
    """截到上限,超出部分按其余未撞限权重的比例再分配;迭代直到无超限。"""
    out = {k: float(v) for k, v in w.items()}
    for _ in range(len(out) + 1):
        over = {k: v - w_max for k, v in out.items() if v > w_max + 1e-12}
        if not over:
            break
        excess = sum(over.values())
        for k in over:
            out[k] = w_max
        free = {k: v for k, v in out.items() if k not in over and v < w_max - 1e-12}
        tot = sum(free.values())
        if tot <= 0:
            n = len(free) or 1
            for k in free:
                out[k] += excess / n
        else:
            for k, v in free.items():
                out[k] = v + excess * v / tot
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def weights_from_scores(
    sharpe: dict[str, float], kappa: float = KAPPA, w_max: float = W_MAX
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """score = max(ŝ, 0) → 归一(全 0 则等权)→ 向等权收缩 → 上限。返回 (原始, 收缩后, 最终)。"""
    names = list(sharpe)
    n = len(names)
    score = {k: max(float(np.nan_to_num(v, nan=0.0)), 0.0) for k, v in sharpe.items()}
    tot = sum(score.values())
    w_raw = {k: (score[k] / tot if tot > 0 else 1.0 / n) for k in names}
    w_shr = {k: (1 - kappa) * w_raw[k] + kappa / n for k in names}
    w_final = cap_and_renormalize(w_shr, w_max)
    return w_raw, w_shr, w_final


def mv_raw_weights(
    mu_ann: dict[str, float], vol_ann: dict[str, float], corr: dict[str, float], shrink: float = COV_SHRINK
) -> dict[str, float]:
    """A2:Σ⁻¹μ 非负投影(负值截 0,全 ≤0 → 等权),Σ 先向对角收缩。"""
    names = list(mu_ann)
    n = len(names)
    sd = np.array([vol_ann[k] for k in names])
    c = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            c[i, j] = c[j, i] = corr.get(f"{names[i]}~{names[j]}", corr.get(f"{names[j]}~{names[i]}", 0.0))
    cov = np.outer(sd, sd) * c
    cov = (1 - shrink) * cov + shrink * np.diag(np.diag(cov))
    mu = np.array([mu_ann[k] for k in names])
    try:
        w = np.linalg.solve(cov, mu)
    except np.linalg.LinAlgError:
        w = mu / np.clip(np.diag(cov), 1e-12, None)
    w = np.clip(w, 0.0, None)
    if w.sum() <= 0:
        return {k: 1.0 / n for k in names}
    return {k: float(w[i] / w.sum()) for i, k in enumerate(names)}


def vintage_weights(returns: pd.DataFrame, cutoff: pd.Timestamp, method: str) -> WeightRecord:
    if method == "A1":
        mu, vol, sh, cr, n_eff, n_obs = rolling_stats(returns, cutoff)
    else:
        mu, vol, sh, cr, n_eff, n_obs = ewma_stats(returns, cutoff)
    if method == "A2":
        w_raw = mv_raw_weights(mu, vol, cr)
        n = len(w_raw)
        w_shr = {k: (1 - KAPPA) * w_raw[k] + KAPPA / n for k in w_raw}
        w_final = cap_and_renormalize(w_shr)
    else:
        w_raw, w_shr, w_final = weights_from_scores(sh)
    lo = KAPPA / len(FACTORS)
    at_bound = any(abs(v - W_MAX) < 1e-9 or abs(v - lo) < 1e-9 for v in w_final.values())
    return WeightRecord(
        pd.Timestamp(cutoff), method, n_obs, n_eff, mu, vol, sh, cr, w_raw, w_shr, w_final, at_bound
    )


def check_weights(w: dict[str, float]) -> None:
    vals = np.array(list(w.values()))
    if (
        (vals < -1e-12).any()
        or abs(vals.sum() - 1.0) > 1e-9
        or (vals > W_MAX + 1e-9).any()
        or (vals < KAPPA / len(w) - 1e-9).any()
    ):
        raise ValueError(f"weights violate constraints: {w}")


def hhi(w: dict[str, float]) -> float:
    return float(sum(v * v for v in w.values()))


def l1_change(prev: dict[str, float] | None, cur: dict[str, float]) -> float:
    if prev is None:
        return 0.0
    return float(sum(abs(cur[k] - prev.get(k, 0.0)) for k in cur))


def record_row(rec: WeightRecord, prev_final: dict[str, float] | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "cutoff": rec.cutoff,
        "method": rec.method,
        "n_obs": rec.n_obs,
        "n_eff": rec.n_eff,
        "at_bound": rec.at_bound,
        "hhi": hhi(rec.w_final),
        "l1_change": l1_change(prev_final, rec.w_final),
    }
    for f in FACTORS:
        row[f"mu_{f}"] = rec.mu_ann[f]
        row[f"vol_{f}"] = rec.vol_ann[f]
        row[f"sharpe_{f}"] = rec.sharpe[f]
        row[f"w_raw_{f}"] = rec.w_raw[f]
        row[f"w_shr_{f}"] = rec.w_shr[f]
        row[f"w_{f}"] = rec.w_final[f]
    row.update({f"corr_{k}": v for k, v in rec.corr.items()})
    return row
