"""研究流程:数据源 -> 合约面板 -> 信号 -> 目标暴露 -> 回测 -> 结果落盘。实盘出单复用前四步(见 live)。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.backtest.engine import BacktestResult, run_backtest
from cta.config import StrategyConfig
from cta.continuous.roll import SymbolPanel, build_symbol_panel
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable
from cta.risk.metrics import perf_stats, yearly
from cta.signals import core as sig


@dataclass
class Signals:
    adj_close: pd.DataFrame
    vol: pd.DataFrame
    tsmom: pd.DataFrame
    carry: pd.DataFrame
    combined: pd.DataFrame
    eligible: pd.DataFrame
    target: pd.DataFrame  # 目标名义暴露/权益(已应用交易缓冲)


def build_panels(
    src: DataSource, cfg: StrategyConfig, specs: InstrumentTable, end: pd.Timestamp | None = None
) -> dict[str, SymbolPanel]:
    """为策略品种池里的每个品种构建合约面板;end 给定时只用 <= end 的数据(实盘 as-of)。"""
    universe = specs.symbols(set(cfg.universe.asset_classes))
    dm = src.dominant_map()
    meta = src.contract_meta()
    out: dict[str, SymbolPanel] = {}
    for s in universe:
        if s not in src.symbols():
            continue
        c = src.contracts(s)
        dd = src.dominant_daily(s)
        if end is not None:
            c = c[c.index.get_level_values("date") <= end]
            dd = dd[dd.index <= end]
            dm_s = dm[dm["date"] <= end]
        else:
            dm_s = dm
        if len(c) == 0:
            continue
        out[s] = build_symbol_panel(s, c, dm_s, meta, dd, confirm_days=cfg.execution.roll_confirm_days)
    return out


def _wide(panels: dict[str, SymbolPanel], col: str) -> pd.DataFrame:
    return pd.DataFrame({s: p.frame[col] for s, p in panels.items()}).sort_index()


def compute_signals(panels: dict[str, SymbolPanel], cfg: StrategyConfig) -> Signals:
    adj = _wide(panels, "adj_close")
    close, nxt, days = _wide(panels, "close"), _wide(panels, "next_close"), _wide(panels, "days_to_next")
    vol = sig.realized_vol(adj, cfg.signals.vol_window)
    ts = sig.tsmom(adj, tuple(cfg.signals.tsmom_lookbacks), vol=vol)
    cr = sig.carry_signal(sig.carry(close, nxt, days), cfg.signals.carry_scale)
    comb = sig.combine({"tsmom": ts, "carry": cr}, cfg.signals.weights)
    # 可投:历史足够 + 主力成交额足够(20 日均值,元)
    hist_ok = adj.notna().cumsum() >= cfg.universe.min_history_days
    turnover = (
        (_wide(panels, "volume") * close * _wide(panels, "multiplier")).rolling(20, min_periods=10).mean()
    )
    eligible = hist_ok & (turnover >= cfg.universe.min_dominant_turnover_cny)
    raw_target = sig.vol_target_positions(
        comb.where(eligible),
        vol,
        cfg.portfolio.target_vol,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
    )
    # 交易缓冲:逐日相对上一日实际目标
    tgt = raw_target.copy()
    prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        row = tgt.loc[d].fillna(0.0)
        buffered = sig.trade_buffer(row, prev, cfg.portfolio.trade_buffer)
        tgt.loc[d] = buffered
        prev = buffered
    return Signals(adj, vol, ts, cr, comb, eligible, tgt)


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_research(
    cfg: StrategyConfig, src: DataSource, specs: InstrumentTable, out_dir: Path
) -> dict[str, Any]:
    panels = build_panels(src, cfg, specs)
    signals = compute_signals(panels, cfg)
    start, end = pd.Timestamp(cfg.backtest.start), pd.Timestamp(cfg.backtest.end)
    idx = signals.target.index
    target = signals.target.loc[(idx >= start) & (idx <= end)]
    res: BacktestResult = run_backtest(
        panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
    )
    stats = perf_stats(res.equity)
    yrs = (res.equity.index[-1] - res.equity.index[0]).days / 365.25
    gross_traded = (
        res.trades["lots"].abs()
        * res.trades["price"]
        * res.trades["symbol"].map(lambda s: specs[s].multiplier)
    ).sum()
    stats["年化名义换手(倍)"] = float(gross_traded / res.equity.mean() / yrs)
    stats["年化成本占权益"] = float(res.costs.sum() / res.equity.mean() / yrs)
    stats["平均保证金占用"] = float(res.margin_usage.mean())
    stats["未成交顺延次数"] = float(res.unfilled.sum())
    out_dir.mkdir(parents=True, exist_ok=True)
    res.equity.to_csv(out_dir / "equity.csv")
    res.positions.to_csv(out_dir / "positions.csv")
    res.exposure.to_csv(out_dir / "exposure.csv")
    res.trades.to_csv(out_dir / "trades.csv", index=False)
    res.margin_usage.to_csv(out_dir / "margin_usage.csv")
    res.costs.to_csv(out_dir / "costs.csv")
    signals.combined.to_csv(out_dir / "signal_combined.csv")
    signals.tsmom.to_csv(out_dir / "signal_tsmom.csv")
    signals.carry.to_csv(out_dir / "signal_carry.csv")
    signals.eligible.to_csv(out_dir / "eligible.csv")
    yearly(res.equity).to_csv(out_dir / "yearly.csv")
    meta = {
        "config_digest": cfg.digest(),
        "config": cfg.model_dump(),
        "data_manifest": src.manifest(),
        "git_sha": git_sha(),
        "n_symbols": len(panels),
        "period": [str(res.equity.index[0].date()), str(res.equity.index[-1].date())],
        "stats": {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in stats.items()},
    }
    (out_dir / "run.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return meta
