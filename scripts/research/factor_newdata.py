"""design_log 九 的执行脚本:会员持仓排名与仓单因子。默认样本内(≤2021-12-31);样本外需 --confirm-holdout。
输出 docs/factor_newdata_<tag>.md 与 results/newdata/<tag>/。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.base import Store  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors import newdata as nd  # noqa: E402
from cta.factors.base import REGISTRY, FactorInputs  # noqa: E402
from cta.factors.evaluate import FactorResult, deflated_sharpe, evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402,F401  —— 注册因子
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402
from cta.signals.core import combine  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
ap.add_argument("--n-trials", type=int, default=30)
ap.add_argument("--placebo-draws", type=int, default=200)
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:end > 2021-12-31 需要 --confirm-holdout(设计日志 九 已写,且只跑一次)")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config()
specs = load_instruments()
store = Store()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
x = FactorInputs.from_panels(panels, cfg)
idx = pd.DatetimeIndex(x.adj_close.index)
cols = list(x.adj_close.columns)
notional = x.close * pd.Series({s: specs[s].multiplier for s in cols})

print("装载会员持仓与仓单(首次会缓存到 results/newdata)…")
hp = nd.hedging_pressure(store)
rec = nd.receipts_total(store)
sig_a = nd.hpos_a(hp, idx, cols)
sig_rec = nd.hrec(rec, idx, cols, x.eligible)
sig_recl = nd.hrec_level(rec, idx, cols, x.eligible)
# H-POS-B:IS 只用上期所 + 郑商所(大商所 2020-07 起,不进 IS;OOS 含大商所)
exchanges = ("SHFE", "CZCE") if end <= IS_END else ("SHFE", "CZCE", "DCE")
by_exch = {
    "SHFE": [s for s in cols if specs[s].exchange == "SHFE"],
    "CZCE": [s for s in cols if specs[s].exchange == "CZCE"],
    "DCE": [s for s in cols if specs[s].exchange == "DCE"],
}
net = pd.concat(
    [nd.member_net(store, e, tuple(by_exch[e])) for e in exchanges if by_exch[e]], ignore_index=True
)
years = range(2017, end.year + 1)
posb = nd.hpos_b(net, x.adj_close, notional, x.oi_total, x.eligible, years)
print(
    f"H-POS-B 评分持续性 Spearman ρ = {posb.persistence_rho:.3f} (p = {posb.persistence_p:.3g}, n = {posb.n_pairs} 对)"
)
gate_a = posb.persistence_rho >= 0.15 and posb.persistence_p <= 0.05
print("  门槛 (a):", "通过" if gate_a else "未通过 → 不进收益测试")
true_ic = nd.pooled_ic(posb.signal.loc[start:end], x.adj_close)
plac_path = Path("results/newdata") / tag / "placebo_ic.csv"
if plac_path.exists():
    plac = pd.read_csv(plac_path).iloc[:, 0].to_numpy(dtype=float)
    print(f"  安慰剂 IC 复用已有结果 {plac_path}")
else:
    plac = nd.placebo_queues(
        net, x.adj_close, notional, x.oi_total, x.eligible, posb, n_draws=args.placebo_draws
    )
q95 = float(np.nanpercentile(plac, 95))
gate_b = true_ic > q95
print(
    f"  真实队列池化 IC(5 日)= {true_ic:.4f};安慰剂 {len(plac)} 组 IC 95 分位 = {q95:.4f},中位 = {float(np.nanmedian(plac)):.4f} → 门槛 (b):",
    "通过" if gate_b else "未通过",
)
out_dir = Path("results/newdata") / tag
out_dir.mkdir(parents=True, exist_ok=True)
pd.Series(plac).to_csv(out_dir / "placebo_ic.csv", index=False)
(out_dir / "gates.json").write_text(
    __import__("json").dumps(
        {
            "rho": posb.persistence_rho,
            "p": posb.persistence_p,
            "n_pairs": posb.n_pairs,
            "true_ic": true_ic,
            "placebo_q95": q95,
            "placebo_median": float(np.nanmedian(plac)),
        },
        ensure_ascii=False,
        indent=1,
    ),
    encoding="utf-8",
)
signals = {"H-POS-A": sig_a, "H-REC": sig_rec, "H-REC-L": sig_recl}
if gate_a:
    signals["H-POS-B"] = posb.signal
results: dict[str, FactorResult] = {
    k: evaluate_factor(k, v, x, specs, cfg, start, end) for k, v in signals.items()
}
combo = combine({"tsmom": REGISTRY["tsmom"].compute(x), "carry": REGISTRY["carry"].compute(x)})
results["combo_v01"] = evaluate_factor("combo_v01", combo, x, specs, cfg, start, end)
corr = pd.DataFrame({k: v.net for k, v in results.items()}).corr()
yrs_pos = max((end - pd.Timestamp("2017-01-01")).days / 365.25, 1.0)
sr_std = 1.0 / np.sqrt(yrs_pos)

rows = []
for name, r in results.items():
    st, ic = r.stats, r.ic
    ys = r.yearly_sharpe
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
            "正夏普年数": int((ys > 0).sum()),
            "年数": int(ys.notna().sum()),
            "DSR": deflated_sharpe(r.net, args.n_trials, sr_std)["DSR"],
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
if not gate_a:
    verdict["H-POS-B"] = (
        f"判死 (a):评分持续性 ρ={posb.persistence_rho:.3f} p={posb.persistence_p:.3g},不进收益测试"
    )
elif not gate_b:
    verdict["H-POS-B"] += f";判死 (b):IC {true_ic:.4f} ≤ 安慰剂 95 分位 {q95:.4f}(规模效应)"
if "H-REC" in signals and "H-REC-L" in signals and abs(corr.at["H-REC", "H-REC-L"]) > 0.8:
    verdict["H-REC-L"] += ";与 H-REC 相关>0.8 只保留 H-REC"
chosen = [k for k, v in verdict.items() if v == "选入"]

table.to_csv(out_dir / "summary.csv")
corr.to_csv(out_dir / "corr.csv")
pd.DataFrame({k: v.net for k, v in results.items()}).to_csv(out_dir / "net_returns.csv")
for k, s in signals.items():
    s.to_csv(out_dir / f"signal_{k}.csv")
hp.to_csv(out_dir / "hedging_pressure.csv")
rec.to_csv(out_dir / "receipts_total.csv")
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
queue_lines = []
for y, q in sorted(posb.yearly_queue.items()):
    queue_lines.append(f"- {y}:" + ";".join(f"{s}[{','.join(m)}]" for s, m in sorted(q.items())))
md = [
    f"# 新数据因子(design_log 九)— {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"配置 {cfg.digest()} / 参数表 {specs.digest()};数据 = 交易所直连会员持仓排名 + 仓单日报;快速评估口径同四;试验数 N={args.n_trials}。",
    f"H-POS-B 评分数据来源:{'+'.join(exchanges)};每年队列见文末。",
    "",
    "## 1. 判死门槛(H-POS-B,看收益之前)",
    "",
    f"- (a) 会员评分在相邻 250 日窗口的 Spearman ρ = **{posb.persistence_rho:.3f}**(p = {posb.persistence_p:.3g},n = {posb.n_pairs} 对;门槛 ρ ≥ 0.15 且 p ≤ 0.05)→ {'通过' if gate_a else '**未通过**'}",
    f"- (b) 真实队列池化 IC(5 日)= {true_ic:.4f};规模匹配安慰剂 {args.placebo_draws} 组的 IC 中位 {float(np.nanmedian(plac)):.4f}、95 分位 {q95:.4f} → {'通过' if gate_b else '**未通过**'}",
    "",
    "## 2. 单因子(扣成本,波动率目标 10%,T+1 收盘近似)",
    "",
    fmt.to_markdown(),
    "",
    "## 3. 逐年夏普",
    "",
    ys_tab.to_markdown(),
    "",
    "## 4. 日收益相关",
    "",
    corr.round(2).to_markdown(),
    "",
    "## 5. 机械判定(4.4 规则 + 九 的门槛)",
    "",
    "\n".join(f"- {k}:{v}" for k, v in verdict.items()),
    "",
    f"**选入:{chosen if chosen else '无'}**",
    "",
    "## 附:H-POS-B 每年队列(评分窗口冻结于上一年末前 5 日)",
    "",
    "\n".join(queue_lines),
    "",
]
out_md = Path("docs") / f"factor_newdata_{tag}.md"
out_md.write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print("判定:", verdict)
print(f"-> {out_md}")
