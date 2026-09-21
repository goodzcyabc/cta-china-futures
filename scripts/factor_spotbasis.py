"""design_log 十三 H-BASIS / H-BASIS-MOM 的执行脚本。默认样本内(≤2021-12-31);样本外需 --confirm-holdout。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors import newdata as nd  # noqa: E402
from cta.factors.base import REGISTRY, FactorInputs  # noqa: E402
from cta.factors.evaluate import FactorResult, deflated_sharpe, evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402,F401
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
ap.add_argument("--n-trials", type=int, default=39)
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:end > 2021-12-31 需要 --confirm-holdout(design_log 十三 已写,只跑一次)")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config()
specs = load_instruments()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
x = FactorInputs.from_panels(panels, cfg)
idx = pd.DatetimeIndex(x.adj_close.index)
cols = list(x.adj_close.columns)
sb = src.spot_basis()
br = nd.basis_rate_wide(sb, idx, cols)
print("现货基差覆盖(IS 内有值比例):", br.loc["2016":"2021"].notna().mean().round(2).to_dict())
signals = {"H-BASIS": nd.hbasis(br, x.eligible), "H-BASIS-MOM": nd.hbasis_mom(br, x.eligible)}
results: dict[str, FactorResult] = {
    k: evaluate_factor(k, v, x, specs, cfg, start, end) for k, v in signals.items()
}
ts, cr = REGISTRY["tsmom"].compute(x), REGISTRY["carry"].compute(x)
results["carry(参照)"] = evaluate_factor("carry", cr, x, specs, cfg, start, end)
results["combo_v01"] = evaluate_factor(
    "combo_v01", combine({"tsmom": ts, "carry": cr}), x, specs, cfg, start, end
)
corr = pd.DataFrame({k: v.net for k, v in results.items()}).corr()
yrs_pos = max((end - pd.Timestamp("2017-01-01")).days / 365.25, 1.0)
rows = []
for name, r in results.items():
    st, ic, ys = r.stats, r.ic, r.yearly_sharpe
    rows.append(
        {
            "因子": name,
            "夏普(月频)": st.get("夏普(月频)", np.nan),
            "NW t": st.get("月频NW t", np.nan),
            "年化": st.get("年化收益", np.nan),
            "最大回撤": st.get("最大回撤", np.nan),
            "换手/年": st.get("年化换手(Σ|Δw|)", np.nan),
            "成本/年": st.get("年化成本", np.nan),
            "TS-IC5": ic.get("ts_ic_5", np.nan),
            "XS-IC5 t": ic.get("xs_ic_t_5", np.nan),
            "与v0.1组合相关": corr.at[name, "combo_v01"],
            "与carry相关": corr.at[name, "carry(参照)"],
            "正夏普年数": int((ys > 0).sum()),
            "年数": int(ys.notna().sum()),
            "DSR": deflated_sharpe(r.net, args.n_trials, 1.0 / np.sqrt(yrs_pos))["DSR"],
        }
    )
table = pd.DataFrame(rows).set_index("因子")
verdict = {}
for name in signals:
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
    if not (t["正夏普年数"] >= max(4 * int(t["年数"]) // 5, 3)):
        reasons.append("正夏普年数不足")
    verdict[name] = "选入" if not reasons else "剔除:" + ";".join(reasons)
out_dir = Path("results/spotbasis") / tag
out_dir.mkdir(parents=True, exist_ok=True)
table.to_csv(out_dir / "summary.csv")
corr.to_csv(out_dir / "corr.csv")
for k, s in signals.items():
    s.to_csv(out_dir / f"signal_{k}.csv")
br.to_csv(out_dir / "basis_rate.csv")
fmt = table.copy()
for c in fmt.columns:
    if c in ("年化", "最大回撤", "成本/年"):
        fmt[c] = fmt[c].map(lambda v: f"{v:+.1%}")
    elif c in ("正夏普年数", "年数"):
        fmt[c] = fmt[c].astype(int)
    elif c == "换手/年":
        fmt[c] = fmt[c].map(lambda v: f"{v:.1f}")
    else:
        fmt[c] = fmt[c].map(lambda v: f"{v:.2f}")
ys_tab = pd.DataFrame({k: v.yearly_sharpe for k, v in results.items()}).T.round(2)
md = [
    f"# 现货基差因子(design_log 十三)— {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"配置 {cfg.digest()} / 参数表 {specs.digest()};数据 = 米筐导出 spot_basis(现货滞后 1 日);快速评估口径同四;试验数 N={args.n_trials}。",
    "",
    "## 1. 单因子(扣成本,波动率目标 10%,T+1 收盘近似)",
    "",
    fmt.to_markdown(),
    "",
    "## 2. 逐年夏普",
    "",
    ys_tab.to_markdown(),
    "",
    "## 3. 日收益相关",
    "",
    corr.round(2).to_markdown(),
    "",
    "## 4. 4.4 规则机械判定",
    "",
    "\n".join(f"- {k}:{v}" for k, v in verdict.items()),
    "",
]
Path("docs").joinpath(f"factor_spotbasis_{tag}.md").write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print("判定:", verdict)
