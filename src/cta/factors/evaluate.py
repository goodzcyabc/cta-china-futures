"""因子快速评估:单因子波动率目标组合(与生产同一套缩放)、IC、逐年、成本、多重检验(Deflated Sharpe)。

用于筛选,不替代完整引擎:仓位 T 日收盘算、T+1 生效,按收盘对收盘对数收益近似(比引擎的开盘成交略乐观)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy import stats as sps

from cta.config import StrategyConfig
from cta.factors.base import FactorInputs
from cta.instruments.specs import InstrumentTable
from cta.risk.metrics import perf_stats
from cta.signals.core import cap_gross_exposure, log_returns, vol_target_positions

Frame = pd.DataFrame
Series = "pd.Series[Any]"
TRADING_DAYS = 243


@dataclass
class FactorResult:
    name: str
    signal: Frame
    net: pd.Series[Any]
    gross: pd.Series[Any]
    cost: pd.Series[Any]
    turnover: pd.Series[Any]
    stats: dict[str, float] = field(default_factory=dict)
    yearly_sharpe: pd.Series[Any] = field(default_factory=lambda: pd.Series(dtype=float))
    ic: dict[str, float] = field(default_factory=dict)


def cost_rate(x: FactorInputs, specs: InstrumentTable, slippage_ticks: float) -> Frame:
    """每单位名义的单边交易成本:手续费(万分比 + 元/手折算)+ 滑点(跳数 × 跳价 / 价格)。"""
    out = pd.DataFrame(np.nan, index=x.close.index, columns=x.close.columns)
    for s in x.close.columns:
        sp = specs[s]
        px = x.close[s]
        out[s] = (
            sp.fee_notional_bp / 1e4 + sp.fee_per_lot / (px * sp.multiplier) + slippage_ticks * sp.tick / px
        )
    return out


def portfolio_returns(
    signal: Frame,
    x: FactorInputs,
    specs: InstrumentTable,
    cfg: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[pd.Series[Any], pd.Series[Any], pd.Series[Any], pd.Series[Any]]:
    tgt = vol_target_positions(
        signal.where(x.eligible),
        x.vol,
        x.adj_close,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    )
    tgt = cap_gross_exposure(tgt, cfg.portfolio.max_gross_exposure)
    idx = tgt.index
    tgt = tgt.loc[(idx >= start) & (idx <= end)]
    w = tgt.shift(1).fillna(0.0)
    r = log_returns(x.adj_close).reindex(w.index).fillna(0.0)
    gross = (w * r).sum(axis=1)
    dw = (w - w.shift(1).fillna(0.0)).abs()
    c = (dw * cost_rate(x, specs, cfg.execution.slippage_ticks).reindex(w.index).fillna(0.0)).sum(axis=1)
    net = gross - c
    return net, gross, c, dw.sum(axis=1)


def _spearman_rows(a: Frame, b: Frame, min_n: int = 8) -> pd.Series[Any]:
    """逐行(逐日)横截面 Spearman;有效样本 < min_n 的日子为 NaN。"""
    mask = a.notna() & b.notna()
    ra = a.where(mask).rank(axis=1)
    rb = b.where(mask).rank(axis=1)
    n = mask.sum(axis=1)
    da = ra.sub(ra.mean(axis=1), axis=0)
    db = rb.sub(rb.mean(axis=1), axis=0)
    num = (da * db).sum(axis=1)
    den = np.sqrt((da**2).sum(axis=1) * (db**2).sum(axis=1))
    out: pd.Series[Any] = (num / den.replace(0, np.nan)).where(n >= min_n)
    return out


def information_coefficients(
    signal: Frame,
    adj_close: Frame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    horizons: tuple[int, ...] = (1, 5, 21),
) -> dict[str, float]:
    """TS-IC:信号与未来 h 日收益的池化 Spearman;XS-IC:逐日横截面 Spearman 的均值与 t。
    只用 t+h ≤ end 的日期,避免 IS 指标用到窗口后的数据。"""
    out: dict[str, float] = {}
    px = adj_close
    dates_le = px.index[px.index <= end]
    for h in horizons:
        fwd = cast(Frame, np.log(px.shift(-h) / px))
        last = dates_le[max(len(dates_le) - 1 - h, 0)]
        sig = signal.loc[(signal.index >= start) & (signal.index <= last)]
        f = fwd.reindex(sig.index)
        a = sig.to_numpy(dtype=float).ravel()
        b = f.to_numpy(dtype=float).ravel()
        ok = ~(np.isnan(a) | np.isnan(b))
        out[f"ts_ic_{h}"] = float(sps.spearmanr(a[ok], b[ok]).statistic) if ok.sum() > 100 else np.nan
        xs = _spearman_rows(sig, f).dropna()
        out[f"xs_ic_{h}"] = float(xs.mean()) if len(xs) else np.nan
        out[f"xs_ic_t_{h}"] = float(xs.mean() / xs.std() * np.sqrt(len(xs))) if len(xs) > 10 else np.nan
    return out


def yearly_sharpe(net: pd.Series[Any]) -> pd.Series[Any]:
    g = net.groupby(pd.DatetimeIndex(net.index).year)
    out: pd.Series[Any] = g.mean() / g.std().replace(0, np.nan) * np.sqrt(TRADING_DAYS)
    return out


def evaluate_factor(
    name: str,
    signal: Frame,
    x: FactorInputs,
    specs: InstrumentTable,
    cfg: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> FactorResult:
    net, gross, cost, to = portfolio_returns(signal, x, specs, cfg, start, end)
    eq = 1e6 * np.exp(net.cumsum())
    active = (to > 0).cummax()
    eq_a = eq[active]
    st = perf_stats(eq_a) if len(eq_a) > 30 else {}
    yrs = max((eq_a.index[-1] - eq_a.index[0]).days / 365.25, 1e-9) if len(eq_a) else np.nan
    st["年化换手(Σ|Δw|)"] = float(to.sum() / yrs)
    st["年化成本"] = float(cost.sum() / yrs)
    st["毛夏普(月频)"] = float(_monthly_sharpe(gross[active]))
    res = FactorResult(name, signal, net, gross, cost, to, st, yearly_sharpe(net[active]))
    res.ic = information_coefficients(signal, x.adj_close, start, end)
    return res


def _monthly_sharpe(r: pd.Series[Any]) -> float:
    m = r.resample("ME").sum()
    return float(m.mean() / m.std() * np.sqrt(12)) if len(m) > 3 and m.std() > 0 else np.nan


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """N 次独立试验下,零假设(真实夏普 0)的期望最大夏普(Bailey & López de Prado 2014 式 (3))。"""
    if n_trials <= 1:
        return 0.0
    g = 0.5772156649
    return float(
        sr_std * ((1 - g) * sps.norm.ppf(1 - 1 / n_trials) + g * sps.norm.ppf(1 - 1 / (n_trials * np.e)))
    )


def deflated_sharpe(
    net: pd.Series[Any], n_trials: int, sr_std_annual: float, periods_per_year: int = 12
) -> dict[str, float]:
    """Deflated Sharpe Ratio(月频):P(真实夏普 > 0 | 试验数、偏度、峰度、样本长度)。
    sr_std_annual:各试验夏普估计的离散度(年化),不知道时可用 1/√年数。"""
    m = net.resample("ME").sum().dropna()
    if len(m) < 12 or m.std() == 0:
        return {"SR0": np.nan, "DSR": np.nan}
    sr = float(m.mean() / m.std())  # 月频、未年化
    sr0 = expected_max_sharpe(n_trials, sr_std_annual / np.sqrt(periods_per_year))
    g3 = float(sps.skew(m))
    g4 = float(sps.kurtosis(m, fisher=False))
    denom = np.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    z = (sr - sr0) * np.sqrt(len(m) - 1) / denom
    return {"SR0": sr0 * np.sqrt(periods_per_year), "DSR": float(sps.norm.cdf(z))}


def correlation_table(results: dict[str, FactorResult]) -> Frame:
    return pd.DataFrame({k: v.net for k, v in results.items()}).corr()
