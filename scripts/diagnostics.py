"""研究诊断(不进包):信号分量单独表现、滑点敏感性、分品种 PnL。每次运行记入 design_log 试验计数。"""
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.backtest.engine import run_backtest
from cta.config import load_config
from cta.data.source import RicequantParquetSource
from cta.instruments.specs import load_instruments
from cta.pipeline import build_panels, compute_signals
from cta.risk.metrics import perf_stats
from cta.signals import core as sig

cfg = load_config(); specs = load_instruments(); src = RicequantParquetSource(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs); S = compute_signals(panels, cfg)
start, end = pd.Timestamp(cfg.backtest.start), pd.Timestamp(cfg.backtest.end)
def bt(target, **kw):
    idx = target.index; t = target.loc[(idx >= start) & (idx <= end)]
    r = run_backtest(panels, t, specs, cfg.backtest.initial_capital_cny, max_margin_usage=cfg.portfolio.max_margin_usage,
                     slippage_ticks=kw.pop("slip", cfg.execution.slippage_ticks), lot_band=cfg.portfolio.trade_buffer)
    st = perf_stats(r.equity); yrs = (r.equity.index[-1] - r.equity.index[0]).days / 365.25
    st["滑点占权益/年"] = float(r.slippage.sum() / r.equity.mean() / yrs); return st, r
def targets_from(comb):
    raw = sig.vol_target_positions(comb.where(S.eligible), S.vol, S.adj_close, cfg.portfolio.target_vol, window=cfg.signals.vol_window,
                                   max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol)
    tgt = raw.copy(); prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        b = sig.trade_buffer(tgt.loc[d].fillna(0.0), prev, cfg.portfolio.trade_buffer); tgt.loc[d] = b; prev = b
    return tgt
rows = {}
rows["合成(主方案)"], main = bt(S.target)
rows["仅时序动量"], _ = bt(targets_from(S.tsmom))
rows["仅展期收益"], _ = bt(targets_from(S.carry))
for k in (0, 2, 3):
    rows[f"滑点 {k} 跳"], _ = bt(S.target, slip=float(k))
K = ["年化收益", "年化波动", "夏普(月频)", "月频NW t", "最大回撤", "滑点占权益/年"]
pd.set_option("display.width", 200); t = pd.DataFrame(rows).T[K]; print(t.round(3).to_string())
# 分品种 PnL(按暴露×结算收益近似)
out = Path("results") / cfg.digest(); t.to_csv(out / "diagnostics.csv")
sym_pnl = {}
for s, p in panels.items():
    f = p.frame.reindex(main.exposure.index); r = f["settle"].pct_change()
    sym_pnl[s] = float((main.exposure[s].shift(1) * r).sum())
sp = pd.Series(sym_pnl).sort_values(ascending=False); sp.to_csv(out / "symbol_pnl_approx.csv")
print("\n分品种累计贡献(近似,占初始权益):"); print(sp.round(3).to_string())
