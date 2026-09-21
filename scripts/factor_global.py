"""design_log 十三 H-GLOBAL 外盘趋势溢出。映射按 13.1 预注册(9 个品种,US 合约);外盘用 ≤ T−1 日的收盘(docs/data_global_futures.md 的时间戳结论)。
默认样本内;样本外需 --confirm-holdout。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors.base import REGISTRY, FactorInputs  # noqa: E402
from cta.factors.evaluate import FactorResult, deflated_sharpe, evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402,F401
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine, realized_vol, tsmom  # noqa: E402

MAP = {
    "AU": "@GC.1",
    "AG": "@SI.1",
    "CU": "@HG.1",
    "SC": "@CL.1",
    "M": "@SM.1",
    "Y": "@BO.1",
    "C": "@C.1",
    "CF": "@CT.1",
    "SR": "@SB.1",
}
IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
ap.add_argument("--n-trials", type=int, default=40)
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:需要 --confirm-holdout")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config()
specs = load_instruments()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
x = FactorInputs.from_panels(panels, cfg)
idx = pd.DatetimeIndex(x.adj_close.index)
cols = list(x.adj_close.columns)

g = pd.read_parquet("data/external/global_futures/daily.parquet")
g["date"] = pd.to_datetime(g["date"])
ext = (
    g[g["symbol_ext"].isin(MAP.values())]
    .pivot(index="date", columns="symbol_ext", values="close")
    .sort_index()
)
ext = ext.rename(columns={v: k for k, v in MAP.items()})
# 外盘 tsmom 在外盘自身日历上算,再对齐到中国 T 日:取日期 ≤ T−1 的最新值
ext_vol = realized_vol(ext, cfg.signals.vol_window)
ext_ts = tsmom(ext, tuple(cfg.signals.tsmom_lookbacks), vol=ext_vol)
aligned = ext_ts.reindex(ext_ts.index.union(idx - pd.Timedelta(days=1))).sort_index().ffill(limit=7)
sig_global = aligned.reindex(idx - pd.Timedelta(days=1))
sig_global.index = idx
sig_global = sig_global.reindex(columns=cols)  # 未映射品种为 NaN
print("覆盖:", {k: round(float(sig_global[k].loc["2016":"2021"].notna().mean()), 2) for k in MAP})

own_ts = REGISTRY["tsmom"].compute(x)
signals = {"H-GLOBAL": sig_global.where(x.eligible)}
results: dict[str, FactorResult] = {
    k: evaluate_factor(k, v, x, specs, cfg, start, end) for k, v in signals.items()
}
results["tsmom 同 9 品种(参照)"] = evaluate_factor(
    "own9", own_ts[list(MAP)].reindex(columns=cols).where(x.eligible), x, specs, cfg, start, end
)
results["combo_v01"] = evaluate_factor(
    "combo_v01", combine({"tsmom": own_ts, "carry": REGISTRY["carry"].compute(x)}), x, specs, cfg, start, end
)
corr = pd.DataFrame({k: v.net for k, v in results.items()}).corr()
# 信号级相关:外盘 tsmom vs 自身 tsmom(同品种同日)
sig_corr = {k: round(float(sig_global[k].corr(own_ts[k])), 2) for k in MAP}
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
            "与v0.1组合相关": corr.at[name, "combo_v01"],
            "正夏普年数": int((ys > 0).sum()),
            "年数": int(ys.notna().sum()),
            "DSR": deflated_sharpe(r.net, args.n_trials, 1.0 / np.sqrt(yrs_pos))["DSR"],
        }
    )
table = pd.DataFrame(rows).set_index("因子")
t = table.loc["H-GLOBAL"]
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
verdict = "选入" if not reasons else "剔除:" + ";".join(reasons)
out_dir = Path("results/global") / tag
out_dir.mkdir(parents=True, exist_ok=True)
table.to_csv(out_dir / "summary.csv")
sig_global.to_csv(out_dir / "signal_H-GLOBAL.csv")
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
md = [
    f"# 外盘趋势溢出 H-GLOBAL(design_log 十三)— {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"映射 {MAP};外盘 tsmom(同 4 个回看期,vol 标准化)取 ≤T−1 的外盘收盘;试验数 N={args.n_trials}。",
    "",
    "## 1. 结果",
    "",
    fmt.to_markdown(),
    "",
    "## 2. 逐年夏普",
    "",
    pd.DataFrame({k: v.yearly_sharpe for k, v in results.items()}).T.round(2).to_markdown(),
    "",
    "## 3. 外盘 tsmom 与自身 tsmom 的信号相关(同品种)",
    "",
    pd.Series(sig_corr).to_frame("corr").to_markdown(),
    "",
    f"## 4. 判定:{verdict}",
    "",
]
Path("docs").joinpath(f"factor_global_{tag}.md").write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print("信号相关:", sig_corr)
print("判定:", verdict)
