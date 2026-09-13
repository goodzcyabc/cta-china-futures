"""6.2 规则流程的滚动验证:每年末按 4.4 规则用全部历史重选因子,下一年按选出的因子 + tsmom + carry 等权交易。
报告用;不改任何规则。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.source import RicequantParquetSource  # noqa: E402
from cta.factors.base import FactorInputs  # noqa: E402
from cta.factors.evaluate import correlation_table, evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine  # noqa: E402

cfg = load_config()
specs = load_instruments()
panels = build_panels(RicequantParquetSource(Path("data/ricecta/data")), cfg, specs)
x = FactorInputs.from_panels(panels, cfg)
S = {f.name: f.compute(x) for f in ALL_FACTORS}
cands = [f.name for f in ALL_FACTORS if not f.reference]
start = pd.Timestamp("2016-01-04")
combo_v01 = combine({"tsmom": S["tsmom"], "carry": S["carry"]})


def select(end: pd.Timestamp) -> list[str]:
    res = {k: evaluate_factor(k, S[k], x, specs, cfg, start, end) for k in [*cands, "tsmom", "carry"]}
    res["combo_v01"] = evaluate_factor("combo_v01", combo_v01, x, specs, cfg, start, end)
    corr = correlation_table(res)
    chosen: list[str] = []
    order = sorted(cands, key=lambda n: -float(np.nan_to_num(res[n].stats.get("夏普(月频)", np.nan), nan=-9)))
    for n in order:
        st, ys = res[n].stats, res[n].yearly_sharpe
        n_years = int(ys.notna().sum())
        ok = (
            st.get("夏普(月频)", -9) >= 0.40
            and st.get("月频NW t", -9) >= 2.0
            and corr.at[n, "combo_v01"] <= 0.60
            and int((ys > 0).sum()) >= max(4 * n_years // 5, 3)  # 5 年中 ≥4 的比例,短样本按比例
            and all(abs(corr.at[n, c]) <= 0.80 for c in chosen)
        )
        if ok:
            chosen.append(n)
    return chosen


rows, nets = [], []
for year in range(2020, 2027):
    sel_end = pd.Timestamp(f"{year - 1}-12-31")
    chosen = select(sel_end)
    sig = combine({"tsmom": S["tsmom"], "carry": S["carry"], **{c: S[c] for c in chosen}})
    y0, y1 = pd.Timestamp(f"{year}-01-01"), min(pd.Timestamp(f"{year}-12-31"), pd.Timestamp("2026-06-05"))
    r_proc = evaluate_factor("proc", sig, x, specs, cfg, y0, y1)
    r_base = evaluate_factor("base", combo_v01, x, specs, cfg, y0, y1)
    nets.append(pd.DataFrame({"流程": r_proc.net, "v0.1": r_base.net}))
    rows.append(
        {
            "年份": year,
            "年末选出": ",".join(chosen) or "(无)",
            "流程夏普": r_proc.stats.get("夏普(月频)", np.nan),
            "v0.1夏普": r_base.stats.get("夏普(月频)", np.nan),
        }
    )
    print(rows[-1])
tab = pd.DataFrame(rows).set_index("年份")
allnet = pd.concat(nets)
m = allnet.resample("ME").sum()
summary = (m.mean() / m.std() * np.sqrt(12)).rename("2020–2026 拼接月频夏普")
out = Path("results/factors/walkforward")
out.mkdir(parents=True, exist_ok=True)
tab.to_csv(out / "by_year.csv")
allnet.to_csv(out / "net_returns.csv")
md = [
    "# 规则流程的滚动验证(design_log 6.2)",
    "",
    "每年末用截至当年的全部历史按 4.4 规则重选,下一年交易 tsmom + carry + 选出因子(等权)。",
    "",
    tab.round(2).to_markdown(),
    "",
    summary.round(2).to_frame().to_markdown(),
    "",
]
Path("docs/factor_walkforward.md").write_text("\n".join(md), encoding="utf-8")
print(tab.round(2).to_string())
print(summary.round(2).to_string())
