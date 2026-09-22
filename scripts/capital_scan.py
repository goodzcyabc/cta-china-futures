"""资金规模扫描(不进包):同一信号在不同初始资金下的回测,量化手数取整对小资金的影响。

朋友给的目标资金规模为 100–500 万;本脚本对 100/200/300/500/1000 万各跑一次引擎(信号相同,只有取整不同),
输出 results/capital_scan/summary.md:整体指标、对照窗口(2022-01-27 起,与洛书拾壹号成立日对齐)指标、
分品种一手名义占权益比例与持有天数占比。运行记入 design_log 试验计数(整个扫描计 1 次)。
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.source import RicequantParquetSource  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels, compute_signals  # noqa: E402
from cta.risk.metrics import perf_stats  # noqa: E402

CAPITALS = [1e6, 2e6, 3e6, 5e6, 1e7]
WINDOW = ("2022-01-27", None)  # 洛书管理期货拾壹号成立日起;None = 回测末日
OUT = Path("results/capital_scan")

cfg = load_config()
specs = load_instruments()
src = RicequantParquetSource(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
S = compute_signals(panels, cfg)
start, end = pd.Timestamp(cfg.backtest.start), pd.Timestamp(cfg.backtest.end)
idx = S.target.index
target = S.target.loc[(idx >= start) & (idx <= end)]


def window_stats(eq: pd.Series) -> dict[str, float]:
    w = eq.loc[WINDOW[0] : WINDOW[1]]
    return {
        "窗口累计收益": float(w.iloc[-1] / w.iloc[0] - 1),
        "窗口最大回撤": float((w / w.cummax() - 1).min()),
        "窗口夏普(月频)": float(perf_stats(w)["夏普(月频)"]),
    }


rows, sym_rows = [], {}
for cap in CAPITALS:
    r = run_backtest(
        panels,
        target,
        specs,
        cap,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    active = r.positions.abs().sum(axis=1) > 0
    eq = r.equity.loc[active[active].index.min() :]
    st = perf_stats(eq)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    held = r.positions.ne(0)
    rows.append(
        {
            "初始资金(万)": int(cap / 1e4),
            "年化收益": st["年化收益"],
            "年化波动": st["年化波动"],
            "夏普(月频)": st["夏普(月频)"],
            "最大回撤": st["最大回撤"],
            "日均持有品种数": float(held.loc["2017":].sum(axis=1).mean()),
            "年化手续费占权益": float(r.costs.sum() / eq.mean() / yrs),
            "年化滑点占权益": float(r.slippage.sum() / eq.mean() / yrs),
            **window_stats(r.equity),
        }
    )
    # 分品种:持有天数占比、持有日中恰为 1 手的占比、一手名义/保证金占权益(按最后一个持有日的价格)
    for s in r.positions.columns:
        h = held[s].loc["2017":]
        lots = r.positions[s]
        one_lot = float((lots.abs() == 1).loc["2017":].sum() / max(h.sum(), 1))
        last_held = lots[lots != 0]
        if len(last_held) == 0:
            continue
        d = last_held.index[-1]
        px = float(r.exposure.at[d, s] * r.equity.at[d] / (lots.at[d] * specs[s].multiplier))
        sym_rows.setdefault(s, {"品种": s, "一手名义(元)": round(px * specs[s].multiplier)})
        sym_rows[s][f"一手名义占权益@{int(cap / 1e4)}万"] = px * specs[s].multiplier / cap
        sym_rows[s][f"持有天数占比@{int(cap / 1e4)}万"] = float(h.mean())
        sym_rows[s][f"持有日中1手占比@{int(cap / 1e4)}万"] = one_lot

OUT.mkdir(parents=True, exist_ok=True)
df = pd.DataFrame(rows).set_index("初始资金(万)")
sym = pd.DataFrame(sym_rows.values()).set_index("品种").sort_values("一手名义(元)", ascending=False)
df.to_csv(OUT / "summary.csv")
sym.to_csv(OUT / "per_symbol.csv")
fmt = df.copy()
for c in fmt.columns:
    if c == "日均持有品种数":
        fmt[c] = fmt[c].map(lambda v: f"{v:.1f}")
    elif "夏普" in c:
        fmt[c] = fmt[c].map(lambda v: f"{v:.2f}")
    else:
        fmt[c] = fmt[c].map(lambda v: f"{v:+.1%}")
cols = (
    ["一手名义(元)"]
    + [c for c in sym.columns if c.startswith("一手名义占权益")]
    + [c for c in sym.columns if c.startswith("持有天数占比")]
)
symf = sym[cols].copy()
symf["一手名义(元)"] = symf["一手名义(元)"].map(lambda v: f"{v:,.0f}")
for c in cols[1:]:
    symf[c] = symf[c].map(lambda v: f"{v:.0%}")
md = [
    "# 资金规模扫描",
    "",
    f"信号与参数同 v{cfg.version}(digest {cfg.digest()}),仅初始资金不同;回测 {start.date()}–{end.date()},含手续费与滑点。",
    f"对照窗口 = {WINDOW[0]} 起(洛书管理期货拾壹号成立日)至回测末日。",
    "",
    fmt.to_markdown(),
    "",
    "## 分品种:一手名义占权益比例与持有天数占比",
    "",
    "一手名义按最后持有日价格计。占比越高,取整对该品种越粗:100 万时黄金/原油/铜/锡一手即占权益 40–100%,基本无法按目标持有。",
    "",
    symf.to_markdown(),
    "",
]
(OUT / "summary.md").write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print(symf.to_string())
print(f"-> {OUT / 'summary.md'}")
