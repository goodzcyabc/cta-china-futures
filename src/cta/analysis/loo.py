"""Leave-one-out 敏感性(只读诊断):逐一把某品种的目标暴露置 0 并**完整重跑引擎**。

不能用"组合收益 − 该品种贡献"代替:权益递归(次日手数按缩水后的权益定)、保证金上限缩减、手数取整都会改变其余品种的路径。
注意:目标暴露在信号层已经做过协方差波动率缩放;这里只把该品种的目标置 0,不重新做信号层缩放(与"从品种池删掉再跑"不同,
后者会让其余品种被重新放大到 10% 目标波动)。只作敏感性诊断,不产生任何删品种建议。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from cta.analysis.attribution import Period
from cta.backtest.engine import BacktestResult, run_backtest
from cta.continuous.roll import SymbolPanel
from cta.instruments.specs import InstrumentTable
from cta.risk.metrics import perf_stats

RunFn = Callable[..., BacktestResult]
SEG_KEYS = ("年化收益", "夏普(月频)", "最大回撤")


def segment_stats(equity: pd.Series[Any], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    """连续运行权益曲线在 [start, end] 段上的 年化收益 / 夏普(月频) / 最大回撤(复用 cta.risk.metrics.perf_stats)。"""
    eq = equity.dropna()
    idx = pd.DatetimeIndex(eq.index)
    seg = eq[(idx >= start) & (idx <= end)]
    if len(seg) < 40:
        return dict.fromkeys(SEG_KEYS, float("nan"))
    st = perf_stats(seg)
    return {k: float(st[k]) for k in SEG_KEYS}


def leave_one_out(
    panels: dict[str, SymbolPanel],
    target: pd.DataFrame,
    specs: InstrumentTable,
    initial_capital: float,
    symbols: list[str],
    full: Period,
    oos: Period,
    engine_kwargs: dict[str, Any],
    run_fn: RunFn = run_backtest,
    baseline: BacktestResult | None = None,
    dependency_sharpe_drop: float = 0.10,
    dependency_oos_cagr_drop: float = 0.02,
) -> pd.DataFrame:
    """每个品种一行:剔除后 FULL/OOS 段的 年化/月频夏普/回撤、相对完整组合的变化、依赖标记。
    依赖标记(诊断阈值,先写):剔除后 FULL 月频夏普下降 ≥ dependency_sharpe_drop,或 OOS 年化下降 ≥ dependency_oos_cagr_drop。"""
    base = (
        baseline if baseline is not None else run_fn(panels, target, specs, initial_capital, **engine_kwargs)
    )
    base_full = segment_stats(base.equity, full.start, full.end)
    base_oos = segment_stats(base.equity, oos.start, oos.end)
    rows: list[dict[str, Any]] = []
    for s in symbols:
        t = target.copy()
        if s in t.columns:
            t[s] = 0.0  # 目标暴露置 0:该品种全程不持仓,其余品种照常规划与执行
        res = run_fn(panels, t, specs, initial_capital, **engine_kwargs)
        f = segment_stats(res.equity, full.start, full.end)
        o = segment_stats(res.equity, oos.start, oos.end)
        d_sharpe = f["夏普(月频)"] - base_full["夏普(月频)"]
        d_oos_cagr = o["年化收益"] - base_oos["年化收益"]
        dependent = bool((d_sharpe <= -dependency_sharpe_drop) or (d_oos_cagr <= -dependency_oos_cagr_drop))
        rows.append(
            {
                "symbol": s,
                "full_cagr": f["年化收益"],
                "full_sharpe_m": f["夏普(月频)"],
                "full_mdd": f["最大回撤"],
                "oos_cagr": o["年化收益"],
                "oos_sharpe_m": o["夏普(月频)"],
                "oos_mdd": o["最大回撤"],
                "d_full_cagr": f["年化收益"] - base_full["年化收益"],
                "d_full_sharpe_m": d_sharpe,
                "d_full_mdd": f["最大回撤"] - base_full["最大回撤"],
                "d_oos_cagr": d_oos_cagr,
                "d_oos_sharpe_m": o["夏普(月频)"] - base_oos["夏普(月频)"],
                "d_oos_mdd": o["最大回撤"] - base_oos["最大回撤"],
                "dependent": dependent,
                "final_equity": float(res.equity.iloc[-1]) if len(res.equity) else np.nan,
            }
        )
    out = pd.DataFrame(rows).set_index("symbol")
    out.attrs["baseline_full"] = base_full
    out.attrs["baseline_oos"] = base_oos
    return out
