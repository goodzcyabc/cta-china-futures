"""信号的纯函数实现。输入输出都是 pandas 对象,不读文件、不依赖全局状态,便于单测和复用。

约定:所有信号的取值方向为"正 = 做多",量纲统一为"目标风险方向 × 强度",强度在 [-1, 1]。
价格输入为**回溯复权(back-adjusted)的主力连续价格**,只用于计算收益率;名义金额与保证金一律用真实合约价格。
"""

from __future__ import annotations

from functools import reduce
from typing import cast

import numpy as np
import pandas as pd

Frame = pd.DataFrame

TRADING_DAYS = 243  # 中国期货市场每年约 243 个交易日(不含夜盘日切)


def log_returns(px: Frame) -> Frame:
    out: Frame = cast(Frame, np.log(px)).diff()
    return out


def realized_vol(px: Frame, window: int = 40, min_periods: int = 20) -> Frame:
    """年化已实现波动率(EWMA 也可,此处用简单滚动便于审计)。"""
    out: Frame = log_returns(px).rolling(window, min_periods=min_periods).std() * np.sqrt(TRADING_DAYS)
    return out


def tsmom(px: Frame, lookbacks: tuple[int, ...] = (21, 63, 126, 252), vol: Frame | None = None) -> Frame:
    """时序动量:各回看期收益的符号(或波动率标准化后的 clip),对**当时可得**的回看期等权平均。
    Moskowitz-Ooi-Pedersen (2012)。vol 给定时用 收益/(vol×sqrt(h/243)) 再 clip 到 [-2,2] 后除 2,否则用符号。"""
    num = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    den = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for h in lookbacks:
        r = np.log(px / px.shift(h))
        s: Frame = (
            cast(Frame, np.sign(r))
            if vol is None
            else (r / (vol * np.sqrt(h / TRADING_DAYS))).clip(-2, 2) / 2.0
        )
        num = num + s.fillna(0.0)
        den = den + s.notna().astype(float)
    out: Frame = num / den.where(den > 0)
    return out.where(px.notna())


def carry(near_px: Frame, next_px: Frame, days_between: Frame) -> Frame:
    """期限结构展期收益(年化):(近月 - 次近月)/次近月 × 365/两合约交割间隔天数。
    正值 = 现货升水(backwardation)= 做多有展期收益。Koijen-Moskowitz-Pedersen-Vrugt (2018)。"""
    raw: Frame = (near_px / next_px - 1.0) * (365.0 / days_between.clip(lower=15))
    return raw


def carry_signal(carry_ann: Frame, scale: float = 0.20) -> Frame:
    """把年化展期收益压到 [-1,1]:tanh(carry/scale),scale=20% 年化时 carry=20% 对应约 0.76 的强度。"""
    out = cast(Frame, np.tanh(carry_ann / scale))
    return out


def combine(signals: dict[str, Frame], weights: dict[str, float] | None = None, sqrt_n: bool = True) -> Frame:
    """等权(或给定权重)合成,缺失的信号不参与分母。
    sqrt_n:按活跃因子数归一 —— k 个弱相关标准化信号的平均值幅度约为单个的 1/√k,若不归一,因子少的品种会被机械放大
    (design_log 12.5 记录的缺陷,13.2 修正)。合成 = mean(s_f) × √(n_active / n_max),n_max = 因子总数;全因子可用的品种不受影响。"""
    names = list(signals)
    w = {k: 1.0 for k in names} if weights is None else weights
    num = reduce(lambda a, b: a + b, [signals[k].fillna(0.0) * w[k] for k in names])
    den = reduce(lambda a, b: a + b, [signals[k].notna().astype(float) * w[k] for k in names])
    mean: Frame = num / den.where(den > 0)
    if sqrt_n and len(names) > 1:
        n_active = reduce(lambda a, b: a + b, [signals[k].notna().astype(float) for k in names])
        mean = mean * np.sqrt(n_active / float(len(names)))
    out: Frame = mean.clip(-1, 1)
    return out


def vol_target_positions(
    signal: Frame,
    vol: Frame,
    px: Frame,
    target_vol: float = 0.10,
    window: int = 60,
    max_leverage_per_symbol: float = 1.0,
    update: str = "daily",
) -> Frame:
    """信号 -> 占组合资本的名义暴露比例。
    第一步 风险平价雏形:w_i ∝ s_i / σ_i(每单位信号承担相同风险);
    第二步 事前组合波动缩放:用最近 window 日收益的协方差算 σ_p = sqrt(wᵀΣw),整体乘 target_vol/σ_p;
    最后 单品种名义上限。相比"除以品种数"的写法,这里正确处理了分散化(N 个不相关头寸的组合波动是 σ/√N)。"""
    raw: Frame = (signal / vol.replace(0, np.nan)).fillna(0.0)
    rets = log_returns(px)
    k = pd.Series(np.nan, index=raw.index, dtype=float)
    cols = list(raw.columns)
    r_np = rets[cols].to_numpy(dtype=float)
    w_np = raw[cols].to_numpy(dtype=float)
    for i in range(len(raw)):
        if i < window:
            continue
        w = w_np[i]
        if not np.any(w):
            continue
        block = r_np[i - window + 1 : i + 1]
        ok = ~np.isnan(block).any(axis=0)
        wv = np.where(ok, w, 0.0)
        cov = np.cov(np.nan_to_num(block[:, ok]).T) if ok.sum() > 1 else np.array([[np.nanvar(block[:, ok])]])
        var = float(wv[ok] @ np.atleast_2d(cov) @ wv[ok]) * TRADING_DAYS
        if var > 0:
            k.iloc[i] = target_vol / np.sqrt(var)
    if update == "weekly":
        # 只在每周第一个交易日更新缩放系数,其余日子沿用(减少由 k 抖动带来的换手)
        wk = pd.Series(pd.DatetimeIndex(raw.index).to_period("W").astype(str), index=raw.index)
        first_of_week = wk != wk.shift(1)
        k = k.where(first_of_week).ffill()
    scaled: Frame = raw.mul(k, axis=0)
    return scaled.clip(-max_leverage_per_symbol, max_leverage_per_symbol)


def cap_gross_exposure(w: Frame, max_gross: float) -> Frame:
    """组合总名义暴露 Σ|w_i| 超过 max_gross 时,整行等比缩减到上限(只缩不放)。"""
    gross = w.abs().sum(axis=1)
    k = (max_gross / gross).clip(upper=1.0).where(gross > 0, 1.0)
    out: Frame = w.mul(k, axis=0)
    return out


def trade_buffer(target: pd.Series[float], current: pd.Series[float], band: float = 0.2) -> pd.Series[float]:
    """交易缓冲:目标与当前的差小于 band × |目标| 时不交易。降低换手,对信号价值几乎无损。"""
    cur = current.reindex(target.index).fillna(0.0)
    diff = target - cur
    thresh = band * target.abs()
    out: pd.Series[float] = target.where(diff.abs() > thresh, cur)
    return out


def zscore_xs(x: Frame, eligible: Frame) -> Frame:
    """每日横截面 z-score(只在可投品种内),clip ±2 再 /2 → [-1, 1]。"""
    r = x.where(eligible.reindex_like(x).fillna(False).astype(bool))
    z = r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)
    out: Frame = (z.clip(-2, 2) / 2.0).where(x.notna())
    return out


def receipts_level(
    receipts: Frame, index: pd.DatetimeIndex, columns: list[str], eligible: Frame, window: int = 252
) -> Frame:
    """仓单水平信号(design_log 九 H-REC-L):−(log(1+注册仓单) 在自身 window 日窗口的分位 − 0.5) 的横截面 z。
    仓单高(可交割现货充裕)→ 做空;仓单低(逼仓风险)→ 做多。receipts 为 date × symbol 的注册仓单合计,当日收盘后公布。"""
    r = cast(Frame, np.log1p(receipts.reindex(index).ffill(limit=5).reindex(columns=columns)))
    pct = r.rolling(window, min_periods=window // 2).rank(pct=True)
    return zscore_xs(-(pct - 0.5), eligible)


def large_tick_mask(
    close: Frame,
    roll: Frame,
    ticks: pd.Series[float],
    eligible: Frame,
    window: int = 336,
    top_quantile: float = 0.5,
) -> Frame:
    """跳价占日波动比例 ρ̄ = tick / EWMA_window(|Δclose|)(换月日的 Δ 剔除),每月末在可投品种内排名;
    排名前 top_quantile 的品种在**下一个月**为 True。月末排名只用当月及以前的数据,无前视。"""
    dp = close.diff().where(~roll.astype(bool))
    mad = dp.abs().ewm(span=window, adjust=False, min_periods=window // 5).mean()
    rho = mad.rdiv(ticks, axis=1)  # tick / mad
    rho = rho.where(eligible.reindex_like(rho).fillna(False).astype(bool))
    month = pd.DatetimeIndex(rho.index).to_period("M")
    month_end = rho.groupby(month).tail(1)
    rank = month_end.rank(axis=1, ascending=False, pct=True)  # 1/N = 最大跳价
    flag = rank <= top_quantile
    # 月末标记 → 下个月每天生效
    flag.index = pd.DatetimeIndex(flag.index) + pd.Timedelta(days=1)
    out: Frame = (
        flag.reindex(rho.index.union(flag.index)).ffill().reindex(rho.index).fillna(False).astype(bool)
    )
    return out


def menu_masks(
    factors: list[str],
    symbols: list[str],
    sector_of: dict[str, str],
    sector_menu: dict[str, list[str]],
    symbol_menu: dict[str, list[str]],
) -> dict[str, pd.Series[bool]]:
    """每个因子一条 品种 → 是否允许 的布尔序列。品种级覆盖优先;板块未列出 = 全部允许(design_log 十二 12.2)。"""
    out: dict[str, pd.Series[bool]] = {}
    for f in factors:
        allowed = []
        for s in symbols:
            if s in symbol_menu:
                allowed.append(f in symbol_menu[s])
            elif sector_of.get(s) in sector_menu:
                allowed.append(f in sector_menu[sector_of[s]])
            else:
                allowed.append(True)
        out[f] = pd.Series(allowed, index=symbols, dtype=bool)
    return out


def inverse_vol_weights(
    signals: dict[str, Frame], window: int = 252, min_periods: int = 126
) -> dict[str, pd.Series[float]]:
    """因子权重 w_f(t) ∝ 1/σ_f(t),σ_f = 该因子信号在全部品种上池化的滚动均方根(信号本身近似零均值),取 t−1 及之前。
    只用信号的离散度,不用收益,因此不可能拟合历史收益(design_log 十二 12.3)。"""
    inv: dict[str, pd.Series[float]] = {}
    for f, s in signals.items():
        ms = (s**2).mean(axis=1)  # 每日横截面均方
        sigma = np.sqrt(ms.rolling(window, min_periods=min_periods).mean()).shift(1)
        inv[f] = 1.0 / sigma.replace(0, np.nan)
    total = reduce(lambda a, b: a.fillna(0.0) + b.fillna(0.0), inv.values())
    return {f: (w / total.where(total > 0)) for f, w in inv.items()}


def combine_tv(signals: dict[str, Frame], weights: dict[str, pd.Series[float]]) -> Frame:
    """时变权重合成:Σ w_f(t)·s_f / Σ w_f(t)·1[s_f 非空];某日权重缺失时该因子不参与。"""
    names = list(signals)
    num = reduce(
        lambda a, b: a + b, [signals[k].fillna(0.0).mul(weights[k].fillna(0.0), axis=0) for k in names]
    )
    den = reduce(
        lambda a, b: a + b,
        [signals[k].notna().astype(float).mul(weights[k].fillna(0.0), axis=0) for k in names],
    )
    out: Frame = (num / den.where(den > 0)).clip(-1, 1)
    return out
