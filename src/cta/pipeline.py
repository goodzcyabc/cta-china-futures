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
from cta.instruments.specs import InstrumentTable, load_instruments
from cta.risk.metrics import perf_stats, yearly
from cta.signals import core as sig


@dataclass
class Signals:
    adj_close: pd.DataFrame
    vol: pd.DataFrame
    tsmom: pd.DataFrame
    carry: pd.DataFrame
    receipts_level: pd.DataFrame | None
    factor_weights: pd.DataFrame | None  # 时变因子权重(inverse_vol 时);equal 为 None
    combined: pd.DataFrame
    eligible: pd.DataFrame
    target: pd.DataFrame  # 目标名义暴露/权益(已应用交易缓冲)


def build_panels(
    src: DataSource, cfg: StrategyConfig, specs: InstrumentTable, end: pd.Timestamp | None = None
) -> dict[str, SymbolPanel]:
    """为策略品种池里的每个品种构建合约面板;end 给定时只用 <= end 的数据(实盘 as-of)。"""
    by_class = specs.symbols(set(cfg.universe.asset_classes), verified_only=not cfg.universe.allow_unverified)
    if cfg.universe.symbols is not None:
        unknown = sorted(set(cfg.universe.symbols) - set(by_class))
        if unknown:
            raise ValueError(
                f"universe.symbols not in instrument table / asset classes / verified set: {unknown}"
            )
        universe = sorted(cfg.universe.symbols)
    else:
        universe = by_class
    dm = src.dominant_map()
    meta = src.contract_meta()
    out: dict[str, SymbolPanel] = {}
    for s in universe:
        if s not in src.symbols():
            continue
        c = src.contracts(s)
        if end is not None:
            c = c[c.index.get_level_values("date") <= end]
            dm_s = dm[dm["date"] <= end]
        else:
            dm_s = dm
        if len(c) == 0:
            continue
        out[s] = build_symbol_panel(
            s,
            c,
            dm_s,
            meta,
            limit_pct=specs[s].limit_pct,
            confirm_days=cfg.execution.roll_confirm_days,
            margin_rate=specs[s].margin_rate,
            tick=specs[s].tick,
        )
    return out


def _wide(panels: dict[str, SymbolPanel], col: str) -> pd.DataFrame:
    return pd.DataFrame({s: p.frame[col] for s, p in panels.items()}).sort_index()


def eligible_mask(panels: dict[str, SymbolPanel], cfg: StrategyConfig) -> pd.DataFrame:
    """可投掩码:历史足够 + 主力成交额足够(20 日均值,元)。信号与因子研究共用同一口径。"""
    adj, close = _wide(panels, "adj_close"), _wide(panels, "close")
    hist_ok = adj.notna().cumsum() >= cfg.universe.min_history_days
    turnover = (
        (_wide(panels, "volume") * close * _wide(panels, "multiplier")).rolling(20, min_periods=10).mean()
    )
    out: pd.DataFrame = hist_ok & (turnover >= cfg.universe.min_dominant_turnover_cny)
    return out


def compute_signals(
    panels: dict[str, SymbolPanel],
    cfg: StrategyConfig,
    receipts: pd.DataFrame | None = None,
    specs: InstrumentTable | None = None,
) -> Signals:
    """信号集合。cfg.signals.weights 里出现 receipts_level 时需要传入仓单表(交易所直连源 `src.receipts()`);
    配置了板块菜单时需要 specs(取 asset_class),缺省读默认参数表。"""
    adj = _wide(panels, "adj_close")
    close, nxt, days = _wide(panels, "close"), _wide(panels, "next_close"), _wide(panels, "days_to_next")
    vol = sig.realized_vol(adj, cfg.signals.vol_window)
    ts = sig.tsmom(adj, tuple(cfg.signals.tsmom_lookbacks), vol=vol)
    eligible = eligible_mask(panels, cfg)
    tf = cfg.signals.tick_filter
    if tf.enabled:
        # 大跳价品种(上月末排名前 top_quantile)本月只用慢回看期;排名只用 T−1 及之前的信息
        ticks = pd.Series(
            {s: float(p.frame["tick"].iloc[0]) if "tick" in p.frame else np.nan for s, p in panels.items()}
        )
        large = sig.large_tick_mask(close, _wide(panels, "roll"), ticks, eligible, tf.window, tf.top_quantile)
        ts_slow = sig.tsmom(adj, tuple(tf.slow_lookbacks), vol=vol)
        ts = ts_slow.where(large, ts)
    cr = sig.carry_signal(sig.carry(close, nxt, days), cfg.signals.carry_scale)
    parts: dict[str, pd.DataFrame] = {"tsmom": ts, "carry": cr}
    rl: pd.DataFrame | None = None
    if "receipts_level" in cfg.signals.weights:
        if receipts is None or receipts.empty:
            raise ValueError("config weights include receipts_level but no receipts data was provided")
        rl = sig.receipts_level(receipts, pd.DatetimeIndex(adj.index), list(adj.columns), eligible)
        parts["receipts_level"] = rl
    # 板块因子菜单(design_log 十二):不允许的因子在该品种上置 NaN,由 nan-aware 合成自动退出分母
    sc = cfg.signals
    if sc.sector_menu or sc.symbol_menu:
        specs = specs or load_instruments()
        sector_of = {s: specs[s].asset_class for s in adj.columns if s in specs.specs}
        masks = sig.menu_masks(list(parts), list(adj.columns), sector_of, sc.sector_menu, sc.symbol_menu)
        for f, frame in list(parts.items()):
            keep = masks[f].reindex(frame.columns).fillna(True).astype(bool)
            # 不允许的品种整列置 NaN(DataFrame.where 不接受按列广播的 Series,故用乘法广播)
            parts[f] = frame.mul(keep.map({True: 1.0, False: np.nan}), axis=1)
    fw: pd.DataFrame | None = None
    if sc.factor_weighting == "inverse_vol":
        tv = sig.inverse_vol_weights(parts)
        fw = pd.DataFrame(tv)
        comb = sig.combine_tv(parts, tv)
    else:
        comb = sig.combine(parts, sc.weights)
    raw_target = sig.vol_target_positions(
        comb.where(eligible),
        vol,
        adj,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    )
    raw_target = sig.cap_gross_exposure(raw_target, cfg.portfolio.max_gross_exposure)
    # 交易缓冲:逐日相对上一日实际目标
    tgt = raw_target.copy()
    prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        row = tgt.loc[d].fillna(0.0)
        buffered = sig.trade_buffer(row, prev, cfg.portfolio.trade_buffer)
        tgt.loc[d] = buffered
        prev = buffered
    return Signals(adj, vol, ts, cr, rl, fw, comb, eligible, tgt)


def _receipts_of(src: DataSource) -> pd.DataFrame | None:
    fn = getattr(src, "receipts", None)
    if fn is None:
        return None
    df: pd.DataFrame = fn()
    return None if df.empty else df


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run_research(
    cfg: StrategyConfig, src: DataSource, specs: InstrumentTable, out_dir: Path
) -> dict[str, Any]:
    panels = build_panels(src, cfg, specs)
    signals = compute_signals(panels, cfg, receipts=_receipts_of(src), specs=specs)
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
        lot_band=cfg.portfolio.trade_buffer,
    )
    active = res.positions.abs().sum(axis=1) > 0
    first_active = active[active].index.min() if active.any() else res.equity.index[0]
    eq_active = res.equity.loc[first_active:]
    stats = perf_stats(eq_active)
    yrs = (eq_active.index[-1] - eq_active.index[0]).days / 365.25
    gross_traded = (
        res.trades["lots"].abs()
        * res.trades["price"]
        * res.trades["symbol"].map(lambda s: specs[s].multiplier)
    ).sum()
    stats["年化名义换手(倍)"] = float(gross_traded / eq_active.mean() / yrs)
    stats["年化手续费占权益"] = float(res.costs.sum() / eq_active.mean() / yrs)
    stats["年化滑点占权益"] = float(res.slippage.sum() / eq_active.mean() / yrs)
    stats["平均总名义暴露"] = float(res.exposure.loc[first_active:].abs().sum(axis=1).mean())
    stats["平均保证金占用"] = float(res.margin_usage.mean())
    stats["未成交顺延次数"] = float(res.unfilled.sum())
    out_dir.mkdir(parents=True, exist_ok=True)
    res.equity.to_csv(out_dir / "equity.csv")
    res.positions.to_csv(out_dir / "positions.csv")
    res.exposure.to_csv(out_dir / "exposure.csv")
    res.trades.to_csv(out_dir / "trades.csv", index=False)
    res.margin_usage.to_csv(out_dir / "margin_usage.csv")
    res.costs.to_csv(out_dir / "costs.csv")
    res.slippage.to_csv(out_dir / "slippage.csv")
    res.pnl_by_symbol.to_csv(out_dir / "pnl_by_symbol.csv")
    signals.combined.to_csv(out_dir / "signal_combined.csv")
    signals.tsmom.to_csv(out_dir / "signal_tsmom.csv")
    signals.carry.to_csv(out_dir / "signal_carry.csv")
    if signals.receipts_level is not None:
        signals.receipts_level.to_csv(out_dir / "signal_receipts_level.csv")
    if signals.factor_weights is not None:
        signals.factor_weights.to_csv(out_dir / "factor_weights.csv")
    signals.eligible.to_csv(out_dir / "eligible.csv")
    yearly(res.equity).to_csv(out_dir / "yearly.csv")
    meta = {
        "config_digest": cfg.digest(),
        "instruments_digest": specs.digest(),
        "instruments_verified": specs.verified,
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
