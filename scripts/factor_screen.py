"""v0.2 因子筛选(docs/design_log.md 第四节的执行脚本)。默认只跑样本内(≤ 2021-12-31)。

用法:
  PYTHONPATH=src python3 scripts/factor_screen.py                       # IS
  PYTHONPATH=src python3 scripts/factor_screen.py --end 2026-06-05 --confirm-holdout   # OOS(选择冻结后只跑一次)
输出:docs/factor_research_<tag>.md 与 results/factors/<tag>/*.csv。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.source import RicequantParquetSource  # noqa: E402
from cta.factors.base import FactorInputs  # noqa: E402
from cta.factors.evaluate import (  # noqa: E402
    FactorResult,
    correlation_table,
    deflated_sharpe,
    evaluate_factor,
    expected_max_sharpe,
)
from cta.factors.library import ALL_FACTORS  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--n-trials", type=int, default=20, help="DSR 用的试验总数(v0.1 9 + 本轮 11)")
ap.add_argument("--confirm-holdout", action="store_true")
ap.add_argument("--tag", default=None)
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END:
    print(
        "=" * 78
        + "\nHOLDOUT:end > 2021-12-31,这是样本外评估。只有在因子选择已写入设计日志后才允许。\n"
        + "=" * 78
    )
    if not args.confirm_holdout:
        sys.exit("拒绝运行:请加 --confirm-holdout 并确认设计日志'五'已写好。")
tag = args.tag or ("is" if end <= IS_END else f"oos_{end.date()}")

cfg = load_config()
specs = load_instruments()
src = RicequantParquetSource(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
x = FactorInputs.from_panels(panels, cfg)

results: dict[str, FactorResult] = {}
signals: dict[str, pd.DataFrame] = {}
for spec in ALL_FACTORS:
    sig = spec.compute(x)
    signals[spec.name] = sig
    results[spec.name] = evaluate_factor(spec.name, sig, x, specs, cfg, start, end)
    print(f"{spec.name:12s} 夏普(月) {results[spec.name].stats.get('夏普(月频)', np.nan):6.2f}")
combo = combine({"tsmom": signals["tsmom"], "carry": signals["carry"]})
results["combo_v01"] = evaluate_factor("combo_v01", combo, x, specs, cfg, start, end)
signals["combo_v01"] = combo

corr = correlation_table(results)
sr_all = pd.Series(
    {k: v.stats.get("夏普(月频)", np.nan) for k, v in results.items() if k not in ("combo_v01",)}
)
sr_std_obs = float(np.nanstd(sr_all.to_numpy(dtype=float)))
# 夏普估计的离散度取零假设解析值 1/√(有仓位年数):观测离散度被真实为负的因子撑大,不代表噪声
yrs_pos = max((end - pd.Timestamp("2017-01-01")).days / 365.25, 1.0)
sr_std = 1.0 / np.sqrt(yrs_pos)

rows = []
for name, r in results.items():
    st, ic = r.stats, r.ic
    dsr = deflated_sharpe(r.net, args.n_trials, sr_std)
    ys = r.yearly_sharpe
    rows.append(
        {
            "因子": name,
            "夏普(月频)": st.get("夏普(月频)", np.nan),
            "NW t": st.get("月频NW t", np.nan),
            "毛夏普": st.get("毛夏普(月频)", np.nan),
            "年化": st.get("年化收益", np.nan),
            "波动": st.get("年化波动", np.nan),
            "最大回撤": st.get("最大回撤", np.nan),
            "换手/年": st.get("年化换手(Σ|Δw|)", np.nan),
            "成本/年": st.get("年化成本", np.nan),
            "TS-IC1": ic.get("ts_ic_1", np.nan),
            "TS-IC5": ic.get("ts_ic_5", np.nan),
            "TS-IC21": ic.get("ts_ic_21", np.nan),
            "XS-IC5": ic.get("xs_ic_5", np.nan),
            "XS-IC5 t": ic.get("xs_ic_t_5", np.nan),
            "与v0.1组合相关": corr.at[name, "combo_v01"] if name != "combo_v01" else 1.0,
            "正夏普年数": int((ys > 0).sum()),
            "年数": int(ys.notna().sum()),
            "DSR": dsr["DSR"],
        }
    )
table = pd.DataFrame(rows).set_index("因子")

# 4.4 选入规则(机械判定)
verdicts = {}
chosen: list[str] = []
cands = [f.name for f in ALL_FACTORS if not f.reference]
for name in sorted(cands, key=lambda n: -float(np.nan_to_num(table.at[n, "夏普(月频)"], nan=-9))):
    t = table.loc[name]
    reasons = []
    if not (t["夏普(月频)"] > 0):
        reasons.append("方向与预期相反或为零")
    if not (t["夏普(月频)"] >= 0.40):
        reasons.append("夏普<0.40")
    if not (t["NW t"] >= 2.0):
        reasons.append("NW t<2.0")
    if not (t["与v0.1组合相关"] <= 0.60):
        reasons.append("与v0.1组合相关>0.60")
    if not (t["正夏普年数"] >= 4):
        reasons.append("正夏普年数<4")
    if any(abs(corr.at[name, c]) > 0.80 for c in chosen):
        reasons.append("与已选因子相关>0.80")
    ok = not reasons
    if ok:
        chosen.append(name)
    verdicts[name] = "选入" if ok else "剔除:" + ";".join(reasons)

out_dir = Path("results/factors") / tag
out_dir.mkdir(parents=True, exist_ok=True)
table.to_csv(out_dir / "summary.csv")
corr.to_csv(out_dir / "corr.csv")
pd.DataFrame({k: v.net for k, v in results.items()}).to_csv(out_dir / "net_returns.csv")
pd.DataFrame({k: v.yearly_sharpe for k, v in results.items()}).T.to_csv(out_dir / "yearly_sharpe.csv")
for k, s in signals.items():
    s.to_csv(out_dir / f"signal_{k}.csv")

fmt = table.copy()
pct = ["年化", "波动", "最大回撤", "成本/年"]
for c in fmt.columns:
    if c in pct:
        fmt[c] = fmt[c].map(lambda v: f"{v:+.1%}")
    elif c in ("正夏普年数", "年数"):
        fmt[c] = fmt[c].astype(int)
    elif c == "换手/年":
        fmt[c] = fmt[c].map(lambda v: f"{v:.1f}")
    else:
        fmt[c] = fmt[c].map(lambda v: f"{v:.2f}")
ys_tab = pd.DataFrame({k: v.yearly_sharpe for k, v in results.items()}).T.round(2)
md = [
    f"# 因子研究 v0.2 — {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"配置 {cfg.digest()} / 参数表 {specs.digest()};{len(panels)} 个品种;快速评估口径见 design_log 4.3;试验数 N={args.n_trials}。",
    f"零假设下 N 次试验的期望最大夏普(夏普估计离散度取解析值 1/√{yrs_pos:.0f}年 = {sr_std:.2f};观测离散度 {sr_std_obs:.2f} 含真实为负的因子,不用):**{expected_max_sharpe(args.n_trials, sr_std):.2f}**。",
    "",
    "## 1. 单因子(扣成本,波动率目标 10%,T+1 收盘近似)",
    "",
    fmt.to_markdown(),
    "",
    "## 2. 逐年夏普(日频年化)",
    "",
    ys_tab.to_markdown(),
    "",
    "## 3. 日收益相关系数",
    "",
    corr.round(2).to_markdown(),
    "",
    "## 4. 4.4 选入规则的机械判定",
    "",
    "\n".join(f"- {k}:{v}" for k, v in verdicts.items()),
    "",
    f"**选入:{chosen if chosen else '无'}**",
    "",
]
out_md = Path("docs") / f"factor_research_{tag}.md"
out_md.write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print("选入:", chosen)
print(f"-> {out_md}")
