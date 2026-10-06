"""design_log 14.2:滚动流程测试——每年末按 P1(截至当年的全部历史里 IS 净贡献 ≤0 的品种剔除)重选品种池,下一年按新池交易。
全部用完整引擎;报告拼接 2020–2026 的净夏普与不剔除的 v0.3 对照。只报告,不选择。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import _receipts_of, build_panels, compute_signals  # noqa: E402

cfg = load_config(Path("configs/strategy_v03.yaml"))
specs = load_instruments()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
signals = compute_signals(panels, cfg, receipts=_receipts_of(src), specs=specs)
END = pd.Timestamp("2026-06-05")


def run(
    target: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    idx = target.index
    res = run_backtest(
        panels,
        target.loc[(idx >= start) & (idx <= end)],
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    return res.equity, res.pnl_by_symbol, res.trades


def net_by_symbol(pnl: pd.DataFrame, trades: pd.DataFrame) -> pd.Series:
    fees = pd.Series(0.0, index=pnl.columns)
    if len(trades):
        f = pd.Series(
            [specs[s].fee(p, q) for s, p, q in zip(trades["symbol"], trades["price"], trades["lots"])]
        )
        fees = fees.add(f.groupby(trades["symbol"].to_numpy()).sum(), fill_value=0.0)
    return pnl.sum() - fees.reindex(pnl.columns).fillna(0.0)


start0 = pd.Timestamp("2016-01-04")
rows, nets = [], []
for year in range(2020, 2027):
    sel_end = pd.Timestamp(f"{year - 1}-12-31")
    _, pnl, tr = run(signals.target, start0, sel_end)
    net = net_by_symbol(pnl, tr)
    keep = sorted(net[net > 0].index)
    y0, y1 = pd.Timestamp(f"{year}-01-01"), min(pd.Timestamp(f"{year}-12-31"), END)
    tgt = signals.target.copy()
    tgt.loc[:, [c for c in tgt.columns if c not in keep]] = 0.0
    eq_p, _, _ = run(tgt, y0, y1)
    eq_b, _, _ = run(signals.target, y0, y1)
    r_p, r_b = eq_p.pct_change().dropna(), eq_b.pct_change().dropna()
    nets.append(pd.DataFrame({"流程(逐年剔除)": r_p, "v0.3 不剔除": r_b}))
    sh = lambda r: float(r.mean() / r.std() * np.sqrt(243)) if r.std() > 0 else np.nan  # noqa: E731
    rows.append(
        {
            "年份": year,
            "年初品种数": len(keep),
            "剔除": ",".join(sorted(set(net.index) - set(keep))),
            "流程夏普": round(sh(r_p), 2),
            "v0.3夏普": round(sh(r_b), 2),
        }
    )
    print(rows[-1])
tab = pd.DataFrame(rows).set_index("年份")
allr = pd.concat(nets)
m = (1 + allr).resample("ME").prod() - 1
summary = (m.mean() / m.std() * np.sqrt(12)).rename("2020–2026-06 拼接月频夏普").round(2)
out = Path("results/prune_walkforward")
out.mkdir(parents=True, exist_ok=True)
tab.to_csv(out / "by_year.csv")
allr.to_csv(out / "daily_returns.csv")
md = [
    "# 品种剔除的滚动流程测试(design_log 14.2)",
    "",
    "每年末按 P1 用截至当年的全部历史重选品种池(IS 净贡献 ≤0 剔除),下一年按新池交易;完整引擎。",
    "",
    tab.to_markdown(),
    "",
    summary.to_frame().to_markdown(),
    "",
]
Path("docs/prune_walkforward.md").write_text("\n".join(md), encoding="utf-8")
print(tab.to_string())
print(summary.to_string())
