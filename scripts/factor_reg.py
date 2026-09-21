"""design_log 十三 H-REG 监管事件覆盖层:公告上调保证金/手续费(非节假日)后 21 个交易日,该品种 tsmom 信号 ×0.5。
完整引擎,基线 v0.1;IS 决定(采用规则见 13.1);OOS 需 --confirm-holdout 只记录。"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta import signals as _sig  # noqa: E402,F401
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import _receipts_of, _wide, build_panels, compute_signals, eligible_mask  # noqa: E402
from cta.signals import core as sig  # noqa: E402

IS_END = pd.Timestamp("2021-12-31")
ap = argparse.ArgumentParser()
ap.add_argument("--events", default="data/external/exchange_events/events.csv")
ap.add_argument("--start", default="2016-01-04")
ap.add_argument("--end", default=str(IS_END.date()))
ap.add_argument("--confirm-holdout", action="store_true")
ap.add_argument("--window", type=int, default=21)
ap.add_argument("--scale", type=float, default=0.5)
args = ap.parse_args()
start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
if end > IS_END and not args.confirm_holdout:
    sys.exit("HOLDOUT:需要 --confirm-holdout")
tag = "is" if end <= IS_END else f"oos_{end.date()}"

cfg = load_config()
specs = load_instruments()
src = default_stitched(Path("data/ricecta/data"))
panels = build_panels(src, cfg, specs)
adj = _wide(panels, "adj_close")
idx = pd.DatetimeIndex(adj.index)
cols = list(adj.columns)

ev = pd.read_csv(args.events, dtype=str).fillna("")
ev["announce_date"] = pd.to_datetime(ev["announce_date"], errors="coerce")
ev["effective_date"] = pd.to_datetime(ev["effective_date"], errors="coerce")
# 事件日 = 公告日(T 日收盘后可知 → 从下一交易日起生效)。推导记录(无公告日)只能在生效日 D 的结算参数里被观察到,
# 事件日 = 生效日 D → 从 D+1 起生效。这是实盘可复现的最保守口径(此前用 D−1 对推导行偏乐观一天,已修)。
ev["event_date"] = ev["announce_date"].fillna(ev["effective_date"])
sel = ev[
    ev["param"].isin(["margin", "fee"])
    & (ev["direction"] == "up")
    & (ev["reason"] != "holiday")
    & ev["symbol"].isin(cols)
]
sel = sel.dropna(subset=["event_date"])
print(
    f"事件总数 {len(ev)};符合定义(保证金/手续费上调、非节假日、池内品种) {len(sel)};品种数 {sel.symbol.nunique()}"
)
print("按年:", sel.groupby(sel.event_date.dt.year).size().to_dict())

mask = pd.DataFrame(1.0, index=idx, columns=cols)
pos = pd.Series(np.arange(len(idx)), index=idx)
for _, r in sel.iterrows():
    d = r["event_date"]
    i = int(idx.searchsorted(d, side="right"))  # 下一交易日
    if i >= len(idx):
        continue
    mask.iloc[i : i + args.window, cols.index(r["symbol"])] = args.scale
covered = float((mask < 1).loc[start:end].mean().mean())
print(f"评估区间内被覆盖的品种-日比例 {covered:.1%}")

# 基线信号与覆盖后信号(只改 tsmom;其余与 compute_signals 完全一致)
base = compute_signals(panels, cfg, receipts=_receipts_of(src), specs=specs)
close, nxt, days = _wide(panels, "close"), _wide(panels, "next_close"), _wide(panels, "days_to_next")
vol = sig.realized_vol(adj, cfg.signals.vol_window)
ts = sig.tsmom(adj, tuple(cfg.signals.tsmom_lookbacks), vol=vol) * mask
cr = sig.carry_signal(sig.carry(close, nxt, days), cfg.signals.carry_scale)
eligible = eligible_mask(panels, cfg)
comb = sig.combine({"tsmom": ts, "carry": cr}, cfg.signals.weights)
raw = sig.cap_gross_exposure(
    sig.vol_target_positions(
        comb.where(eligible),
        vol,
        adj,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    ),
    cfg.portfolio.max_gross_exposure,
)
# 交易缓冲(与 pipeline 相同的逐日规则)
tgt = raw.copy()
prev = pd.Series(0.0, index=tgt.columns)
for d in tgt.index:
    row = tgt.loc[d].fillna(0.0)
    new = sig.trade_buffer(row, prev, cfg.portfolio.trade_buffer)
    tgt.loc[d] = new
    prev = new


def run(target: pd.DataFrame) -> pd.Series:
    t = target.loc[(target.index >= start) & (target.index <= end)]
    res = run_backtest(
        panels,
        t,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.trade_buffer,
    )
    return res.equity


def st(eq: pd.Series) -> dict[str, float]:
    m = eq.resample("ME").last().pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {
        "夏普(月)": float(m.mean() / m.std() * math.sqrt(12)),
        "年化": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1),
        "最大回撤": float((eq / eq.cummax() - 1).min()),
    }


eq_b, eq_r = run(base.target), run(tgt)
sb, sr = st(eq_b), st(eq_r)
tab = pd.DataFrame({"v0.1 基线": sb, "H-REG 覆盖": sr})
d_sr, d_mdd = sr["夏普(月)"] - sb["夏普(月)"], sr["最大回撤"] - sb["最大回撤"]
adopt = (d_sr >= -0.02 and d_mdd >= 0.02) or d_sr >= 0.05
verdict = "采用" if adopt else "不采用"
out = Path("results/reg") / tag
out.mkdir(parents=True, exist_ok=True)
pd.DataFrame({"base": eq_b, "reg": eq_r}).to_csv(out / "equity.csv")
sel.to_csv(out / "events_used.csv", index=False)
md = [
    f"# 监管事件覆盖层 H-REG(design_log 十三)— {'样本内' if end <= IS_END else '样本外(HOLDOUT)'} {start.date()} 至 {end.date()}",
    "",
    f"事件 = 公告上调保证金/手续费(非节假日),事件后 {args.window} 个交易日该品种 tsmom ×{args.scale};事件 {len(sel)} 条,覆盖品种-日 {covered:.1%}。完整引擎,基线 v0.1。",
    "",
    tab.round(3).to_markdown(),
    "",
    f"Δ夏普 {d_sr:+.3f},Δ最大回撤 {d_mdd:+.1%} → 规则(夏普 ≥ 基线 −0.02 且回撤改善 ≥2pp,或夏普 ≥ 基线 +0.05):**{verdict}**",
    "",
]
Path("docs").joinpath(f"factor_reg_{tag}.md").write_text("\n".join(md), encoding="utf-8")
print(tab.round(3).to_string())
print(f"Δ夏普 {d_sr:+.3f} Δ回撤 {d_mdd:+.1%} → {verdict}")
