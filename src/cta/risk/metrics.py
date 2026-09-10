"""绩效指标(权益曲线口径)。日频与月频都给,月频 t 值用 Newey-West。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 243


def drawdown(equity: pd.Series[Any]) -> pd.Series[Any]:
    out: pd.Series[Any] = equity / equity.cummax() - 1.0
    return out


def perf_stats(equity: pd.Series[Any], rf: float = 0.0) -> dict[str, float]:
    eq = equity.dropna()
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else np.nan
    vol = float(r.std() * np.sqrt(TRADING_DAYS))
    dd = drawdown(eq)
    mdd = float(np.nanmin(dd.to_numpy(dtype=float)))
    m = eq.resample("ME").last().pct_change().dropna()
    sr_m = float(m.mean() / m.std() * np.sqrt(12)) if m.std() > 0 else np.nan
    try:
        import statsmodels.api as sm

        t_nw = float(
            sm.OLS(m.values, np.ones((len(m), 1))).fit(cov_type="HAC", cov_kwds={"maxlags": 3}).tvalues[0]
        )
    except Exception:  # noqa: BLE001
        t_nw = np.nan
    return {
        "年化收益": cagr,
        "年化波动": vol,
        "夏普(日频)": (float(r.mean() * TRADING_DAYS) - rf) / vol if vol > 0 else np.nan,
        "夏普(月频)": sr_m,
        "月频NW t": t_nw,
        "最大回撤": mdd,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "月胜率": float(np.mean(m.to_numpy() > 0)),
        "偏度(月)": float(np.asarray(m.skew(), dtype=float)),
        "期数(月)": float(len(m)),
    }


def yearly(equity: pd.Series[Any]) -> pd.Series[Any]:
    eq = equity.dropna()
    years = pd.DatetimeIndex(eq.index).year
    last = eq.groupby(years).last()
    first = eq.groupby(years).first()
    base = last.shift(1).fillna(first)
    out: pd.Series[Any] = last / base - 1.0
    return out
