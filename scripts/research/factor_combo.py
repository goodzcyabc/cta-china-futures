"""5.1 组合阶段试验(IS):T1 趋势 sleeve、T2 carry sleeve、T1+T2、4.5a 低波动降权、4.5b JD 不参与 carry。
规则见 docs/design_log.md 5.1;本脚本只输出数字与机械判定,不改任何规则。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.source import RicequantParquetSource  # noqa: E402
from cta.factors.base import REGISTRY, FactorInputs  # noqa: E402
from cta.factors.evaluate import FactorResult, evaluate_factor  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:end > 2021-12-31 需要 --confirm-holdout")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config()
specs = load_instruments()
panels = build_panels(RicequantParquetSource(Path("data/ricecta/data")), cfg, specs)
x = FactorInputs.from_panels(panels, cfg)
S = {k: REGISTRY[k].compute(x) for k in ("tsmom", "ewmac", "breakout", "carry", "carry_xs", "reversal_st")}

trend_v01, carry_v01 = S["tsmom"], S["carry"]
trend_t1 = combine({"tsmom": S["tsmom"], "ewmac": S["ewmac"], "breakout": S["breakout"]})
carry_t2 = combine({"carry": S["carry"], "carry_xs": S["carry_xs"]})
variants: dict[str, pd.DataFrame] = {
    "v0.1": combine({"trend": trend_v01, "carry": carry_v01}),
    "T1": combine({"trend": trend_t1, "carry": carry_v01}),
    "T2": combine({"trend": trend_v01, "carry": carry_t2}),
    "T1+T2": combine({"trend": trend_t1, "carry": carry_t2}),
}


def lowvol_downweight(sig: pd.DataFrame) -> pd.DataFrame:
    med = x.vol.rolling(252, min_periods=126).median()
    low = x.vol < 0.7 * med
    return sig.where(~low, sig * 0.5)


def carry_without_jd(carry_sig: pd.DataFrame) -> pd.DataFrame:
    c = carry_sig.copy()
    if "JD" in c.columns:
        c["JD"] = np.nan
    return c


res: dict[str, FactorResult] = {
    k: evaluate_factor(k, v, x, specs, cfg, start, end) for k, v in variants.items()
}


def row(r: FactorResult) -> dict[str, float]:
    return {
        "夏普(月频)": r.stats.get("夏普(月频)", np.nan),
        "NW t": r.stats.get("月频NW t", np.nan),
        "年化": r.stats.get("年化收益", np.nan),
        "最大回撤": r.stats.get("最大回撤", np.nan),
        "换手/年": r.stats.get("年化换手(Σ|Δw|)", np.nan),
        "成本/年": r.stats.get("年化成本", np.nan),
    }


base = res["v0.1"]
sr0, cost0 = base.stats["夏普(月频)"], base.stats["年化成本"]
verdict: dict[str, str] = {}
t1_ok = res["T1"].stats["夏普(月频)"] >= sr0 - 0.05 and res["T1"].stats["年化成本"] <= 0.9 * cost0
t2_ok = res["T2"].stats["夏普(月频)"] >= sr0 + 0.05
verdict["T1"] = "采用" if t1_ok else "不采用"
verdict["T2"] = "采用" if t2_ok else "不采用"
if t1_ok and t2_ok:
    both_ok = (
        res["T1+T2"].stats["夏普(月频)"]
        >= max(res["T1"].stats["夏普(月频)"], res["T2"].stats["夏普(月频)"]) - 0.05
    )
    verdict["T1+T2"] = "采用" if both_ok else "不采用"
else:
    verdict["T1+T2"] = "未评估(T1/T2 未同时达标)"
adopted = "T1+T2" if verdict.get("T1+T2") == "采用" else ("T1" if t1_ok else ("T2" if t2_ok else "v0.1"))
trend_b = trend_t1 if adopted in ("T1", "T1+T2") else trend_v01
carry_b = carry_t2 if adopted in ("T2", "T1+T2") else carry_v01
base_sig = variants[adopted]

# 4.5a / 4.5b 在采用后的基准上
res["4.5a 低波动降权"] = evaluate_factor("4.5a", lowvol_downweight(base_sig), x, specs, cfg, start, end)
res["4.5b JD 不参与 carry"] = evaluate_factor(
    "4.5b", combine({"trend": trend_b, "carry": carry_without_jd(carry_b)}), x, specs, cfg, start, end
)
carry_alone = evaluate_factor("carry_b", carry_b, x, specs, cfg, start, end)
carry_nojd = evaluate_factor("carry_b_nojd", carry_without_jd(carry_b), x, specs, cfg, start, end)
b = res[adopted]
a_ok = (
    res["4.5a 低波动降权"].stats["夏普(月频)"] >= b.stats["夏普(月频)"] - 0.05
    and res["4.5a 低波动降权"].stats["年化换手(Σ|Δw|)"] < b.stats["年化换手(Σ|Δw|)"]
)
b_ok = carry_nojd.stats["夏普(月频)"] >= carry_alone.stats["夏普(月频)"]
verdict["4.5a"] = "采用" if a_ok else "不采用"
verdict["4.5b"] = (
    f"{'采用' if b_ok else '不采用'}(carry 单独夏普 {carry_alone.stats['夏普(月频)']:.2f} → {carry_nojd.stats['夏普(月频)']:.2f})"
)
if end > IS_END:
    res["T3 12日延续(仅报告)"] = evaluate_factor("T3", -S["reversal_st"], x, specs, cfg, start, end)

tab = pd.DataFrame({k: row(v) for k, v in res.items()}).T
out_dir = Path("results/factors") / tag
out_dir.mkdir(parents=True, exist_ok=True)
tab.to_csv(out_dir / "combo_summary.csv")
pd.DataFrame({k: v.net for k, v in res.items()}).to_csv(out_dir / "combo_net_returns.csv")
fmt = tab.copy()
for c in fmt.columns:
    fmt[c] = fmt[c].map(
        (lambda v: f"{v:+.1%}") if c in ("年化", "最大回撤", "成本/年") else (lambda v: f"{v:.2f}")
    )
if end > IS_END:
    verdict = {k: f"[仅信息:OOS 不用于采用] {v}" for k, v in verdict.items()}
    adopted = f"{adopted}(OOS 机械判定仅供参考,采用以 IS 为准)"
print(fmt.to_string())
print("判定:", verdict, "| 采用基准:", adopted)
md = [
    f"# 组合阶段试验 — {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    "规则见 design_log 5.1(先写后跑)。快速评估口径同单因子。",
    "",
    fmt.to_markdown(),
    "",
    "判定:",
    "",
    "\n".join(f"- {k}:{v}" for k, v in verdict.items()),
    "",
    f"**采用基准:{adopted}**",
    "",
]
out_md = Path("docs") / f"factor_combo_{tag}.md"
out_md.write_text("\n".join(md), encoding="utf-8")
print(f"-> {out_md}")
