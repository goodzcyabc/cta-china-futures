"""design_log 十六 X1(成交方式)/ X2(调仓频率)/ 16.4(滑点校准)。完整引擎、v0.3 配置。
默认 IS(≤2021-12-31)决定;--confirm-holdout 跑 OOS(≤2026-06-03,5 分钟线止于此)只记录。"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.continuous.roll import SymbolPanel  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import _receipts_of, build_panels, compute_signals  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--config", default="configs/strategy_v03.yaml")
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:需要 --confirm-holdout")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config(Path(args.config))
specs = load_instruments()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
signals = compute_signals(panels, cfg, receipts=_receipts_of(src), specs=specs)
fills = pd.read_parquet("results/exec/fills.parquet")
fills["date"] = pd.to_datetime(fills["date"])
FILL_COLS = {"F0": "F0_open", "F1": "F1_vwap30", "F2": "F2_vwap60", "F3": "F3_day_open", "F4": "F4_vwap_all"}


def panels_with_fill(col: str) -> dict[str, SymbolPanel]:
    """把每个面板的 open / roll_from_open 换成指定成交价(按当日持有合约 / 换月旧合约查表);查不到时回退为原 open。"""
    out = {}
    for s, p in panels.items():
        f = p.frame.copy()
        fs = fills[fills["symbol"] == s].set_index(["contract", "date"])[col]
        held = pd.MultiIndex.from_arrays([f["contract"].astype(str), f.index])
        alt = fs.reindex(held).to_numpy()
        f["open"] = np.where(np.isnan(alt), f["open"].to_numpy(), alt)
        rf = f["roll_from"].astype(object)
        mask = rf.notna()
        if mask.any():
            idx2 = pd.MultiIndex.from_arrays([rf[mask].astype(str), f.index[mask]])
            alt2 = fs.reindex(idx2).to_numpy()
            cur = f.loc[mask, "roll_from_open"].to_numpy(dtype=float)
            f.loc[mask, "roll_from_open"] = np.where(np.isnan(alt2), cur, alt2)
        out[s] = SymbolPanel(s, f)
    return out


def run(
    pn: dict[str, SymbolPanel], target: pd.DataFrame, slippage: float
) -> tuple[pd.Series, dict[str, float]]:
    t = target.loc[(target.index >= start) & (target.index <= end)]
    res = run_backtest(
        pn,
        t,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=slippage,
        lot_band=cfg.portfolio.trade_buffer,
    )
    eq = res.equity
    active = eq[eq.index >= t.index[(t.abs().sum(axis=1) > 0).to_numpy().argmax()]]
    m = active.resample("ME").last().pct_change().dropna()
    yrs = (active.index[-1] - active.index[0]).days / 365.25
    mult = pd.Series({s: specs[s].multiplier for s in pn})
    turn = float(
        (res.trades["lots"].abs() * res.trades["price"] * res.trades["symbol"].map(mult)).sum()
        / yrs
        / cfg.backtest.initial_capital_cny
    )
    stats = {
        "夏普(月)": float(m.mean() / m.std() * math.sqrt(12)),
        "年化": float((active.iloc[-1] / active.iloc[0]) ** (1 / yrs) - 1),
        "最大回撤": float((active / active.cummax() - 1).min()),
        "换手/年": turn,
        "滑点/年": float(res.slippage.sum() / yrs / cfg.backtest.initial_capital_cny),
        "手续费/年": float(res.costs.sum() / yrs / cfg.backtest.initial_capital_cny),
    }
    return active, stats


def yearly_ret(eq: pd.Series) -> pd.Series:
    return eq.resample("YE").last().pct_change().dropna()


# ---- X1 成交方式
rows, eqs = {}, {}
for k, col in FILL_COLS.items():
    pn = panels if k == "F0" else panels_with_fill(col)
    eq, st = run(pn, signals.target, cfg.execution.slippage_ticks)
    rows[k] = st
    eqs[k] = eq
    print(k, {a: round(b, 4) for a, b in st.items()}, flush=True)
half = {
    k: run(panels if k == "F0" else panels_with_fill(col), signals.target, 0.5)[1]["夏普(月)"]
    for k, col in FILL_COLS.items()
}
base_sr = rows["F0"]["夏普(月)"]
yr0 = yearly_ret(eqs["F0"])
verdict = {}
for k in FILL_COLS:
    if k == "F0":
        continue
    yr = yearly_ret(eqs[k]).reindex(yr0.index)
    ok = rows[k]["夏普(月)"] >= base_sr + 0.05 and int((yr >= yr0).sum()) >= 4
    verdict[k] = (
        "达标" if ok else "未达标"
    ) + f"(Δ夏普 {rows[k]['夏普(月)'] - base_sr:+.3f}, 年份不劣 {int((yr >= yr0).sum())}/5)"
qual = [k for k in ["F0", "F1", "F2", "F3", "F4"] if k != "F0" and verdict[k].startswith("达标")]
order = {"F3": 1, "F1": 2, "F2": 3, "F4": 4}  # 所需 bar 数由少到多(F3 只需一根日盘 bar)
chosen = sorted(qual, key=lambda k: order[k])[0] if qual else "F0"

# ---- X2 调仓频率(在 chosen 上)
pn_c = panels if chosen == "F0" else panels_with_fill(FILL_COLS[chosen])


def sparsify(target: pd.DataFrame, every: int) -> pd.DataFrame:
    t = target.copy()
    keep = np.zeros(len(t), dtype=bool)
    keep[::every] = True
    t.loc[~keep] = np.nan
    return t.ffill().fillna(0.0)


freq_rows = {}
for every in (1, 2, 5):
    tgt = signals.target if every == 1 else sparsify(signals.target, every)
    _, st = run(pn_c, tgt, cfg.execution.slippage_ticks)
    freq_rows[f"每{every}日"] = st
    print(f"每{every}日", {a: round(b, 4) for a, b in st.items()}, flush=True)
d1 = freq_rows["每1日"]
fq = {}
for k in ("每2日", "每5日"):
    st = freq_rows[k]
    fq[k] = st["夏普(月)"] >= d1["夏普(月)"] - 0.02 and st["换手/年"] <= 0.75 * d1["换手/年"]
freq_chosen = "每5日" if fq.get("每5日") else ("每2日" if fq.get("每2日") else "每1日")

# ---- 16.4 滑点校准(只报告)
fx = fills[fills["date"].between(start, end)].copy()
tick = pd.Series({s: specs[s].tick for s in fx["symbol"].unique()})
fx["dev_bar"] = (fx["F0_bar_vwap"] - fx["F0_open"]).abs() / fx["symbol"].map(tick)
fx["dev_30"] = (fx["F1_vwap30"] - fx["F0_open"]).abs() / fx["symbol"].map(tick)
cal = fx.groupby("symbol")[["dev_bar", "dev_30"]].agg(["median", lambda s: s.quantile(0.9)])
cal.columns = ["首bar VWAP 偏离(跳)中位", "首bar 90分位", "30分钟 VWAP 偏离(跳)中位", "30分钟 90分位"]

out = Path("results/exec") / tag
out.mkdir(parents=True, exist_ok=True)
tab = pd.DataFrame(rows).T
tab["0.5跳夏普"] = pd.Series(half)
tab.to_csv(out / "x1_fills.csv")
pd.DataFrame(freq_rows).T.to_csv(out / "x2_freq.csv")
cal.to_csv(out / "slippage_calibration.csv")
fmt = tab.copy()
for c in ("年化", "最大回撤", "滑点/年", "手续费/年"):
    fmt[c] = fmt[c].map(lambda v: f"{v:+.1%}")
fmt["换手/年"] = fmt["换手/年"].map(lambda v: f"{v:.1f}")
for c in ("夏普(月)", "0.5跳夏普"):
    fmt[c] = fmt[c].map(lambda v: f"{v:.2f}")
ff = pd.DataFrame(freq_rows).T
for c in ("年化", "最大回撤", "滑点/年", "手续费/年"):
    ff[c] = ff[c].map(lambda v: f"{v:+.1%}")
ff["换手/年"] = ff["换手/年"].map(lambda v: f"{v:.1f}")
ff["夏普(月)"] = ff["夏普(月)"].map(lambda v: f"{v:.2f}")
md = [
    f"# 执行与频率试验(design_log 十六)— {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"配置 {cfg.digest()};完整引擎;成交价来自 5 分钟线(缺失回退日线 open);滑点 1 跳。",
    "",
    "## X1 成交方式",
    "",
    fmt.to_markdown(),
    "",
    "判定(采用规则 16.2):",
    "",
    "\n".join(f"- {k}:{v}" for k, v in verdict.items()),
    "",
    f"**X1 选择:{chosen}**",
    "",
    f"## X2 调仓频率(在 {chosen} 上)",
    "",
    ff.to_markdown(),
    "",
    f"判定(16.3):{ {k: ('达标' if v else '未达标') for k, v in fq.items()} } → **{freq_chosen}**",
    "",
    "## 16.4 滑点校准(首 bar / 前 30 分钟 VWAP 相对首 bar open 的绝对偏离,跳数;只报告)",
    "",
    cal.round(2).to_markdown(),
    "",
]
Path("docs").joinpath(f"exec_trials_{tag}.md").write_text("\n".join(md), encoding="utf-8")
print(fmt.to_string())
print("X1:", verdict, "→", chosen)
print(ff.to_string())
print("X2:", fq, "→", freq_chosen)
print(cal.round(2).to_string())
