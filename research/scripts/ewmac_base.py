"""ewmac 基本盘(试验 61;预注册 docs/research/ewmac_base_prereg.md,提交 0b2ae47)。

两种模式,口径全部按预注册,不另设参数:
  history   第 4.1 节:前提检查 → 前视截断 → 完整引擎三臂 → 2022 起分段、逐年、需求方口径 IC;
            区间 2016-01-04 → 2026-10-08,只跑一次。输出 results/ewmac_base/、docs/research/ewmac_base.md。
  forward   第 4.2/4.3 节:冻结代码对截至 D 的数据从 2016-01-04 连续回放,统计 2026-10-12 起的前向收益并给出判读;
            只在检查点运行(2026-12-15、2027-03-31 只报告,2027-09-30 判读)。

用法:python research/scripts/ewmac_base.py history
      python research/scripts/ewmac_base.py forward --date 2027-09-30
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/(cta_research)

from cta.analysis.loo import segment_stats  # noqa: E402
from cta.analysis.stats import paired_summary  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.pipeline import _wide, build_panels, eligible_mask  # noqa: E402
from cta.risk.metrics import TRADING_DAYS  # noqa: E402
from cta.signals.core import realized_vol  # noqa: E402
from cta_research.evaluation import candidate_eval as ce  # noqa: E402
from cta_research.factors import REGISTRY, FactorInputs  # noqa: E402
from cta_research.signals import fundamental_signals as fs  # noqa: E402

RQ = "data/ricecta/data"
START = "2016-01-04"
HIST_END = "2026-10-08"
CUTOVER = "2026-06-05"
FWD_START = pd.Timestamp("2026-10-12")
TRUNC_CUTS = ("2024-03-15", "2025-09-30")
TOL = 1e-9
OUT = Path("results/ewmac_base")
DOC = Path("docs/research/ewmac_base.md")


# ---------------------------------------------------------------- signal and arms
def ewmac_signal(panels: dict[str, Any], cfg: Any) -> pd.DataFrame:
    """预注册第 3 节:REGISTRY["ewmac"] 的输出(时序标准化,[−1, 1];可投条件在 raw_exposure 里施加)。"""
    out: pd.DataFrame = REGISTRY["ewmac"].compute(FactorInputs.from_panels(panels, cfg))
    return out


def candidate(sig: pd.DataFrame) -> ce.Candidate:
    """价格信号的点时审计:T 日收盘的数据、T 日可得、T 日为目标日、下一交易日建仓。"""
    dates = pd.DatetimeIndex(sig.dropna(how="all").index)
    audit = pd.DataFrame(
        {
            "data_date": dates,
            "info_date": dates,
            "target_day": dates,
            "exec_day": list(dates[1:]) + [pd.NaT],
        }
    )
    return ce.Candidate("ewmac", "ewmac 基本盘(单独,v0.3 同一组合与执行路径)", sig, audit)


def standalone_equity(ctx: ce.Context, sig: pd.DataFrame) -> pd.Series:
    """与 candidate_eval.evaluate 的"候选单独"一臂完全相同的三步(history 模式里逐位核对)。"""
    comb = sig.reindex(index=ctx.sig.adj_close.index, columns=ctx.sig.adj_close.columns)
    raw = fs.raw_exposure(comb, ctx.sig.eligible, ctx.sig.vol, ctx.sig.adj_close, ctx.cfg)
    tgt = fs.apply_buffer(raw, ctx.cfg, ctx.start, ctx.end)
    eq: pd.Series = ce.engine_run(tgt, ctx.panels, ctx.specs, ctx.cfg).equity
    return eq


def build(end: str) -> ce.Context:
    return ce.build_context(start=START, end=end, data_end=end, cutover=CUTOVER, data_root=RQ)


# ---------------------------------------------------------------- 4.1 checks
def full_target(ctx: ce.Context, sig: pd.DataFrame) -> pd.DataFrame:
    """全量目标暴露(状态连续的暴露缓冲从 2016-01-04 起);截断比较时取截断日及之前。"""
    raw = fs.raw_exposure(sig, ctx.sig.eligible, ctx.sig.vol, ctx.sig.adj_close, ctx.cfg)
    out: pd.DataFrame = fs.apply_buffer(raw, ctx.cfg, pd.Timestamp(START), ctx.end)
    return out


def truncation_check(
    ctx: ce.Context, sig_full: pd.DataFrame, tgt_f: pd.DataFrame, cut: str
) -> dict[str, Any]:
    """预注册 4.1:截断输入重算信号与目标暴露,与全量比较(空值位置相同、最大绝对差 ≤ 1e-9)。"""
    t = pd.Timestamp(cut)
    src = default_stitched(Path(RQ), cutover=pd.Timestamp(CUTOVER), official_settle=True)
    panels = build_panels(src, ctx.cfg, ctx.specs, end=t)
    adj = _wide(panels, "adj_close")
    sig_c = ewmac_signal(panels, ctx.cfg)
    vol = realized_vol(adj, ctx.cfg.signals.vol_window)
    elig = eligible_mask(panels, ctx.cfg)
    tgt_c = fs.apply_buffer(fs.raw_exposure(sig_c, elig, vol, adj, ctx.cfg), ctx.cfg, pd.Timestamp(START), t)

    def cmp(a: pd.DataFrame, b: pd.DataFrame) -> tuple[bool, float]:
        idx = a.index[(a.index >= pd.Timestamp(START)) & (a.index <= t)]
        cols = sorted(set(a.columns) | set(b.columns))
        x = a.reindex(index=idx, columns=cols).to_numpy(dtype=float)
        y = b.reindex(index=idx, columns=cols).to_numpy(dtype=float)
        same_nan = bool((np.isnan(x) == np.isnan(y)).all())
        diff = np.abs(x - y)
        mx = float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.0
        return same_nan, mx

    s_nan, s_max = cmp(sig_full, sig_c)
    t_nan, t_max = cmp(tgt_f, tgt_c)
    ok = s_nan and t_nan and s_max <= TOL and t_max <= TOL
    return {
        "cut": cut,
        "signal_nan_same": s_nan,
        "signal_maxdiff": s_max,
        "target_nan_same": t_nan,
        "target_maxdiff": t_max,
        "pass": ok,
    }


# ---------------------------------------------------------------- 4.2 / 4.3
def forward_stats(eq_ewmac: pd.Series, eq_v03: pd.Series, start: pd.Timestamp = FWD_START) -> dict[str, Any]:
    """预注册 4.2:前向日收益(第一天以 start 前一交易日为分母)→ 月度复利(首月不完整也计入)→ 月频夏普;
    配对差与最大回撤取 paired_summary(v0.3, ewmac, start)。"""
    e = eq_ewmac.dropna().astype(float)
    e.index = pd.DatetimeIndex(e.index)
    prev = e.index[e.index < start]
    if not len(prev):
        raise ValueError("no base date before the forward window")
    seg = e.loc[prev[-1] :]
    r = seg.pct_change().dropna()
    monthly = (1.0 + r).groupby(pd.DatetimeIndex(r.index).to_period("M")).prod() - 1.0
    sharpe = float(monthly.mean() / monthly.std(ddof=1) * np.sqrt(12)) if len(monthly) >= 2 else float("nan")
    ps = paired_summary(eq_v03, eq_ewmac, start=start)
    return {
        "base_date": str(prev[-1].date()),
        "first_date": str(r.index[0].date()) if len(r) else None,
        "last_date": str(r.index[-1].date()) if len(r) else None,
        "n_days": len(r),
        "n_months": len(monthly),
        "monthly_returns": {str(k): float(v) for k, v in monthly.items()},
        "sharpe_monthly": sharpe,
        "paired_ann_mean": float(ps["ann_mean"]),
        "paired_t": float(ps["t"]),
        "mdd_ewmac": float(ps["mdd_challenger"]),
        "mdd_v03": float(ps["mdd_champion"]),
    }


def judge(st: dict[str, Any]) -> str:
    """预注册 4.3,按 否定 → 未被否定 → 不优于 的顺序。"""
    sh = st["sharpe_monthly"]
    if not np.isfinite(sh):
        return "无法判读(月数不足)"
    if sh <= 0 or st["mdd_ewmac"] < st["mdd_v03"] - 0.05:
        return "否定"
    if st["paired_ann_mean"] >= 0:
        return "未被否定"
    return "不优于"


# ---------------------------------------------------------------- reporting helpers
def yearly_table(eq: pd.Series, first: pd.Timestamp, last_year: int) -> pd.DataFrame:
    e = eq.loc[first:]
    r = e.pct_change().dropna()
    yrs = pd.DatetimeIndex(r.index).year
    g = r.groupby(yrs)
    out = pd.DataFrame(
        {
            "收益": (1.0 + r).groupby(yrs).prod() - 1.0,
            "夏普(日频年化)": g.mean() / g.std() * np.sqrt(TRADING_DAYS),
        }
    )
    out.index.name = "年"
    return out[out.index <= last_year]


def _fmt_pct(x: float) -> str:
    return f"{x:+.1%}" if np.isfinite(x) else "—"


def run_history() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = build(HIST_END)  # 目标暴露复现失败时这里抛 RuntimeError
    if ctx.baseline_matches_reference is not True:
        print(f"STOP: baseline_matches_reference = {ctx.baseline_matches_reference}", file=sys.stderr)
        return 2
    sig = ewmac_signal(ctx.panels, ctx.cfg)
    tgt_full = full_target(ctx, sig)
    checks = [truncation_check(ctx, sig, tgt_full, c) for c in TRUNC_CUTS]
    (OUT / "truncation.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    print("truncation:", checks)
    if not all(c["pass"] for c in checks):
        print("STOP: truncation check failed (no returns computed)", file=sys.stderr)
        return 3

    ev = ce.evaluate(ctx, candidate(sig))
    ce.write_eval(OUT, ev)
    sa, bl = "ewmac_standalone", "ewmac_blend"
    eq = {sa: ev.arms[sa].equity, bl: ev.arms[bl].equity, "v0.3": ev.arms["baseline"].equity}
    mine = standalone_equity(ctx, sig)
    if not mine.equals(eq[sa]):
        print("STOP: standalone_equity differs from candidate_eval's standalone arm", file=sys.stderr)
        return 4

    # 2022 起(已复用窗口):以 2021-12-31 为基数
    seg22 = {k: segment_stats(v, pd.Timestamp("2021-12-31"), pd.Timestamp(HIST_END)) for k, v in eq.items()}
    firsts = {
        sa: ev.first_active,
        bl: ce.first_active(ev.arms[bl]),
        "v0.3": ce.first_active(ev.arms["baseline"]),
    }
    yearly = {k: yearly_table(eq[k], firsts[k], 2026) for k in eq}
    r = pd.DataFrame({k: v.pct_change() for k, v in eq.items()}).loc[ev.first_active :].dropna()
    corr = float(r[sa].corr(r["v0.3"]))

    # 需求方口径 IC:同一 context 的信号写出,再用 factor_ic_monthly.py
    sig.to_csv(OUT / "signal_ewmac.csv")
    ctx.sig.tsmom.to_csv(OUT / "signal_tsmom.csv")
    ctx.sig.carry.to_csv(OUT / "signal_carry.csv")
    if ctx.sig.receipts_level is not None:
        ctx.sig.receipts_level.to_csv(OUT / "signal_receipts_level.csv")
    ctx.sig.combined.to_csv(OUT / "signal_combined.csv")
    ctx.sig.eligible.to_csv(OUT / "eligible.csv")
    ic_cmd = [
        sys.executable,
        "research/scripts/factor_ic_monthly.py",
        "--run",
        str(OUT),
        "--signals",
        "ewmac,tsmom,carry,receipts_level,combined",
        "--last-signal-month",
        "2026-08",
    ]
    ic_out = subprocess.run(ic_cmd, capture_output=True, text=True, check=True).stdout
    (OUT / "ic_monthly.txt").write_text(ic_out, encoding="utf-8")
    from factor_ic_monthly import monthly_ic  # noqa: E402 —— 同目录脚本

    adj = ctx.sig.adj_close
    elig = ctx.sig.eligible
    last_ic = {}
    for name in ("ewmac", "tsmom", "carry", "receipts_level", "combined"):
        s = pd.read_csv(OUT / f"signal_{name}.csv", index_col=0, parse_dates=True)
        ic = monthly_ic(s, adj, elig)
        ic = ic[ic.index <= pd.Timestamp("2026-08-31")]
        last_ic[name] = str(pd.Timestamp(ic.index.max()).to_period("M"))
    if any(v != "2026-08" for v in last_ic.values()):
        print(f"STOP: last IC month is not 2026-08: {last_ic}", file=sys.stderr)
        return 5

    write_doc(ev, seg22, yearly, corr, checks, ic_out, firsts)
    print(f"-> {DOC}")
    return 0


def write_doc(
    ev: ce.CandidateEval,
    seg22: dict[str, dict[str, float]],
    yearly: dict[str, pd.DataFrame],
    corr: float,
    checks: list[dict[str, Any]],
    ic_out: str,
    firsts: dict[str, pd.Timestamp],
) -> None:
    sa, bl = "ewmac_standalone", "ewmac_blend"
    names = {sa: "ewmac 单独", bl: "50-50 混合", "baseline": "v0.3", "v0.3": "v0.3"}
    s = ev.summary
    lines = [
        "# ewmac 基本盘 —— 历史描述(试验 61,预注册 4.1;只描述,不构成证据)",
        "",
        "由 `research/scripts/ewmac_base.py history` 生成。区间 2016-01-04 → 2026-10-08,切换日 2026-06-05。",
        "候选是看过 2017–2026 逐年结果后挑出来的(预注册第 2 节),以下数字都含挑选偏差;证据只来自 2026-10-12 起的前向回放。",
        "",
        "## 前提检查",
        "",
        "- 目标暴露复现与 `baseline_matches_reference`:通过。",
    ]
    for c in checks:
        lines.append(
            f"- 截断 {c['cut']}:信号空值位置相同 {c['signal_nan_same']},最大差 {c['signal_maxdiff']:.2e};"
            f"目标空值位置相同 {c['target_nan_same']},最大差 {c['target_maxdiff']:.2e} → {'通过' if c['pass'] else '不通过'}"
        )
    lines += [
        "",
        "## 完整引擎三臂",
        "",
        "| 臂 | 区间 | 起 | 止 | 年化 | 夏普(月) | 最大回撤 |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in (sa, bl, "baseline"):
        for period, label in (("SINCE_ACTIVE", "全样本(自首个持仓日)"), ("IS", "2017–2021")):
            row = s[(s["arm"] == arm) & (s["period"] == period)]
            if len(row):
                r0 = row.iloc[0]
                lines.append(
                    f"| {names[arm]} | {label} | {r0['start']} | {r0['end']} | {_fmt_pct(float(r0['年化收益']))} | "
                    f"{float(r0['夏普(月频)']):.2f} | {_fmt_pct(float(r0['最大回撤']))} |"
                )
        k = "v0.3" if arm == "baseline" else arm
        st = seg22[k]
        lines.append(
            f"| {names[arm]} | 2022 起(已复用窗口) | 2021-12-31 | 2026-10-08 | {_fmt_pct(st['年化收益'])} | "
            f"{st['夏普(月频)']:.2f} | {_fmt_pct(st['最大回撤'])} |"
        )
    lines += [
        "",
        f"ewmac 单独与 v0.3 日收益相关 {corr:.2f}(自 ewmac 首个持仓日 {ev.first_active.date()})。",
        f"`candidate_eval` 配对差与 R0–R14 判定只作描述:判定 {ev.verdict}。配对差原始输出见 `results/ewmac_base/eval_ewmac.json`"
        '(其中 "oos" 段按 `oos_start=2022-01-04` 计,不叫样本外)。',
        "",
        "## 逐年(收益 / 夏普 日频年化;各臂自首个持仓日起,2026 至 10-08)",
        "",
        "| 年 | ewmac 单独 | v0.3 | 50-50 混合 |",
        "|---|---|---|---|",
    ]
    ys = yearly[sa].index.union(yearly["v0.3"].index)
    for y in ys:
        cells = []
        for k in (sa, "v0.3", bl):
            t = yearly[k]
            cells.append(
                f"{_fmt_pct(float(t.loc[y, '收益']))} / {float(t.loc[y, '夏普(日频年化)']):.2f}"
                if y in t.index
                else "—"
            )
        lines.append(f"| {y} | " + " | ".join(cells) + " |")
    pos = {k: f"{int((yearly[k]['夏普(日频年化)'] > 0).sum())}/{len(yearly[k])}" for k in (sa, "v0.3", bl)}
    lines += [
        "",
        f"逐年夏普为正的年数:ewmac 单独 {pos[sa]}、v0.3 {pos['v0.3']}、50-50 混合 {pos[bl]}"
        f"(ewmac 首个持仓日 {firsts[sa].date()},2017 年只含下半年)。",
        "",
        "## 需求方口径:月度横截面 IC(`factor_ic_monthly.py --last-signal-month 2026-08`)",
        "",
        "```",
        ic_out.strip(),
        "```",
        "",
        "<!-- human:start -->",
        "<!-- human:end -->",
        "",
    ]
    DOC.write_text("\n".join(lines), encoding="utf-8")


def run_forward(date: str) -> int:
    ctx = build(date)
    sig = ewmac_signal(ctx.panels, ctx.cfg)
    eq_e = standalone_equity(ctx, sig)
    eq_v = ctx.res_base.equity
    st = forward_stats(eq_e, eq_v)
    st["evaluation_date"] = date
    st["baseline_matches_reference"] = ctx.baseline_matches_reference  # 只报告,不是停止条件(4.2)
    st["verdict"] = judge(st)
    out = OUT / f"forward_{date}.json"
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(st, ensure_ascii=False, indent=1, default=str))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("history")
    f = sub.add_parser("forward")
    f.add_argument("--date", required=True, help="评估日 D(数据截至 D,含当日结算)")
    args = ap.parse_args()
    if args.mode == "history":
        return run_history()
    return run_forward(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
