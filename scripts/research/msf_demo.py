"""多源基本面合成因子 MSF 的演示评估(预注册 docs/research/msf_prereg.md;试验 60;样本内演示,不构成证据)。

步骤:
1. 12 个成分(cta.factors.composite)各自点时审计 + 发布类成分公布日 ≤ 目标日 + 截断不变性(交易日历与面板截到 cut 重算,
   cut 及之前的信号须不变;原始数据的点时由各成分的可得日规则与审计保证,截断检查验证的是日历/面板这一层);
2. 生产接线核对:`pipeline._extra_factors_of` 走出来的 MSF 与本脚本逐位一致,v0.6 目标暴露可由同一路径复现;
3. 三臂(MSF 单独 / 静态基线 / 50-50 混合),基线分别为 v0.3(champion)与 v0.1(纯量价);
4. 系统级:v0.6(时序动量 + 展期收益 + MSF)全流程回测对 v0.3、v0.1;
5. 分散化:12 个成分信号加权收益的相关矩阵、合成相对各成分的波动与夏普、每个品种平均有几个成分在发声。
用法:PYTHONPATH=src python3 scripts/research/msf_demo.py
输出:results/msf_demo/、docs/research/msf_demo.md(表格;结论由人写在标记之间,重跑保留)。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cta.analysis import candidate_eval as ce  # noqa: E402
from cta.analysis import fundamental_signals as fs  # noqa: E402
from cta.analysis.stats import newey_west_mean, paired_summary  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors import composite as cp  # noqa: E402
from cta.pipeline import (  # noqa: E402
    _extra_factors_of,
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    git_sha,
)
from cta.risk.metrics import TRADING_DAYS  # noqa: E402

OUT = Path("results/msf_demo")
DOC = Path("docs/research/msf_demo.md")
DATA = Path("data/ricecta/data")
SEED = 20261005
V01_REF = "results/settle_baseline/equity_v0.1_full_D_unified_official.csv"
# 周日 PMI 前的周五、春节前月末、普通周三、周六 PPI 前的周五、周日 PMI 前的周五
TRUNC_CUTS = ("2019-06-28", "2020-01-23", "2023-03-15", "2024-03-08", "2024-03-29")
HUMAN_START, HUMAN_END = "<!-- human:start -->", "<!-- human:end -->"


def prereg_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "log", "--follow", "--format=%h", "--diff-filter=A", "--", "docs/research/msf_prereg.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        return out[-1] if out else "uncommitted"
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def msf_candidate(cands: dict[str, ce.Candidate]) -> ce.Candidate:
    audits = []
    for k, c in cands.items():
        a = c.audit.copy()
        a.insert(0, "component", k)
        audits.append(a)
    audit = pd.concat(audits, ignore_index=True)
    msf = cp.combine_msf({k: c.signal for k, c in cands.items()})
    return ce.Candidate("MSF", "多源基本面合成因子(12 个成分等权:11 个非量价 + 全市场持仓)", msf, audit)


def truncation_check(src: Any, cfg: Any, specs: Any, full: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """交易日历与面板截断到 cut(实盘 as-of 的样子)重算全部成分;cut 及之前的信号须与完整日历下相同。"""
    out: dict[str, Any] = {}
    msf_full = cp.combine_msf(full)
    for cut in TRUNC_CUTS:
        t = pd.Timestamp(cut)
        panels_c = build_panels(src, cfg, specs, end=t)
        comps = cp.build_components(src, cfg, specs, panels_c)
        res: dict[str, float] = {}
        for k in [*cp.COMPONENTS, "MSF"]:
            part = cp.combine_msf(comps) if k == "MSF" else comps[k]
            ref = msf_full if k == "MSF" else full[k]
            idx = part.index[part.index <= t]
            a = part.loc[idx].to_numpy(dtype=float)
            b = ref.reindex(index=idx, columns=part.columns).to_numpy(dtype=float)
            nan_mismatch = int((np.isnan(a) != np.isnan(b)).sum())
            both = ~np.isnan(a) & ~np.isnan(b)
            diff = float(np.max(np.abs(a[both] - b[both]))) if both.any() else 0.0
            res[k] = diff if nan_mismatch == 0 else float("inf")
            if nan_mismatch:
                res[f"{k}_nan_mismatch"] = nan_mismatch
        out[cut] = res
        print(
            f"截断 {cut}: 最大差异 {max(v for k, v in res.items() if not k.endswith('mismatch')):.3g}",
            flush=True,
        )
    return out


def swr_stats(r: pd.Series[Any]) -> dict[str, float]:
    x = r.dropna()
    nw = newey_west_mean(x.to_numpy(dtype=float), 5)
    sd = float(x.std())
    return {
        "ann_mean": float(x.mean() * TRADING_DAYS),
        "ann_vol": sd * float(np.sqrt(TRADING_DAYS)),
        "sharpe": float(x.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else float("nan"),
        "nw_t": float(nw.t),
        "n_days": int(nw.n),
    }


def diversification(ctx: ce.Context, cands: dict[str, ce.Candidate], msf: ce.Candidate) -> dict[str, Any]:
    swr = {k: ce.signal_weighted_returns(ctx, c) for k, c in cands.items()}
    swr["MSF"] = ce.signal_weighted_returns(ctx, msf)
    df = pd.DataFrame(swr)
    oos = df[df.index >= ctx.oos_start]
    stats = {k: {"FULL": swr_stats(df[k]), "OOS": swr_stats(oos[k])} for k in df.columns}
    corr = df[list(cands)].corr(min_periods=120)
    off = corr.to_numpy(dtype=float)[~np.eye(len(corr), dtype=bool)]
    # 信号层:MSF 与每个成分的合并(日 × 品种)相关;每个品种平均有几个成分在发声
    win = (msf.signal.index >= ctx.start) & (msf.signal.index <= ctx.end)
    m = msf.signal[win]
    sig_corr = {}
    for k, c in cands.items():
        a, b = m.to_numpy(dtype=float).ravel(), c.signal[win].to_numpy(dtype=float).ravel()
        ok = ~np.isnan(a) & ~np.isnan(b)
        sig_corr[k] = float(np.corrcoef(a[ok], b[ok])[0, 1]) if ok.sum() > 100 else float("nan")
    n_active = sum(c.signal[win].notna().astype(int) for c in cands.values())
    assert isinstance(n_active, pd.DataFrame)
    per_symbol = n_active.mean().round(2).to_dict()
    by_year = n_active.mean(axis=1).groupby(pd.DatetimeIndex(n_active.index).year).mean().round(2).to_dict()
    df.to_csv(OUT / "component_signal_weighted_returns.csv")
    corr.to_csv(OUT / "component_corr.csv")
    return {
        "stats": stats,
        "corr": corr.round(3).to_dict(),
        "mean_offdiag_corr": float(np.nanmean(off)),
        "median_offdiag_corr": float(np.nanmedian(off)),
        "signal_corr_msf_vs_component": sig_corr,
        "n_active_per_symbol": per_symbol,
        "n_active_by_year": {str(k): v for k, v in by_year.items()},
    }


def system_level(
    ctx3: ce.Context, ctx1: ce.Context, src: Any, msf: pd.DataFrame
) -> tuple[dict[str, Any], pd.Series[Any]]:
    cfg6 = load_config(Path("configs/strategy_v06_msf.yaml"))
    wired = _extra_factors_of(src, cfg6, ctx3.specs, ctx3.panels)
    assert wired is not None
    wiring_identical = bool(
        np.allclose(
            wired["msf"].to_numpy(dtype=float),
            msf.reindex(index=wired["msf"].index, columns=wired["msf"].columns).to_numpy(dtype=float),
            equal_nan=True,
        )
    )
    sig6 = compute_signals(
        ctx3.panels,
        cfg6,
        receipts=_receipts_of(src),
        specs=ctx3.specs,
        reg_events=_reg_events_of(src, cfg6),
        extra_factors=wired,
    )
    raw6 = fs.raw_exposure(sig6.combined, sig6.eligible, sig6.vol, sig6.adj_close, cfg6)
    tgt6 = fs.apply_buffer(raw6, cfg6, ctx3.start, ctx3.end)
    target_reproduces = bool(
        np.allclose(
            tgt6.to_numpy(dtype=float),
            sig6.target.reindex(index=tgt6.index, columns=tgt6.columns).to_numpy(dtype=float),
            equal_nan=True,
        )
    )
    res6 = ce.engine_run(tgt6, ctx3.panels, ctx3.specs, cfg6)
    res6.equity.to_csv(OUT / "equity_v06_msf.csv")
    res6.trades.to_csv(OUT / "trades_v06_msf.csv", index=False)
    rows = []
    for name, res in (
        ("v0.6 (tsmom+carry+MSF)", res6),
        ("v0.3 champion", ctx3.res_base),
        ("v0.1 量价", ctx1.res_base),
    ):
        for per, s, e in (
            ("FULL", ctx3.start, ctx3.end),
            ("IS", ctx3.start, ctx3.is_end),
            ("OOS", ctx3.oos_start, ctx3.end),
        ):
            st = ce.arm_stats(res, ctx3.specs, s, e)
            rows.append({"arm": name, "period": per, **st})
    summ = pd.DataFrame(rows)
    kw = {"lags": 5, "block": 10, "n_boot": 2000, "seed": SEED}
    paired = {
        base: {
            "FULL": paired_summary(eq, res6.equity, start=ctx3.start, **kw),
            "OOS": paired_summary(eq, res6.equity, start=ctx3.oos_start, **kw),
        }
        for base, eq in (("v0.3", ctx3.res_base.equity), ("v0.1", ctx1.res_base.equity))
    }
    r6 = res6.equity.pct_change().dropna()
    corr = {}
    for base, eq in (("v0.3", ctx3.res_base.equity), ("v0.1", ctx1.res_base.equity)):
        rb = eq.pct_change().dropna()
        common = r6.index.intersection(rb.index)
        corr[base] = float(np.corrcoef(r6.loc[common], rb.loc[common])[0, 1])
    yearly = {}
    for name, res in (("v0.6", res6), ("v0.3", ctx3.res_base), ("v0.1", ctx1.res_base)):
        eq = res.equity
        yearly[name] = {
            str(y): float(g.iloc[-1] / eq[eq.index < g.index[0]].iloc[-1] - 1)
            if (eq.index < g.index[0]).any()
            else float(g.iloc[-1] / g.iloc[0] - 1)
            for y, g in eq.groupby(pd.DatetimeIndex(eq.index).year)
        }
    out = {
        "wiring_identical": wiring_identical,
        "target_reproduces_production": target_reproduces,
        "summary": summ.to_dict(orient="records"),
        "paired_v06_minus": paired,
        "corr_daily": corr,
        "yearly_return": yearly,
    }
    summ.to_csv(OUT / "system_summary.csv", index=False)
    return out, res6.equity


def arm_row(ev: ce.CandidateEval, arm: str, period: str) -> dict[str, Any]:
    s = ev.summary
    m = (s["arm"] == arm) & (s["period"] == period)
    return s[m].iloc[0].to_dict() if m.any() else {}


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    ctx3 = ce.build_context(seed=SEED)
    ctx1 = ce.build_context(config_path="configs/strategy.yaml", reference_equity=V01_REF, seed=SEED)
    print(
        f"基线复现:v0.3 {ctx3.baseline_matches_reference} / v0.1 {ctx1.baseline_matches_reference}",
        flush=True,
    )
    if ctx3.baseline_matches_reference is False or ctx1.baseline_matches_reference is False:
        print("STOP: 基线不能复现", file=sys.stderr)
        return 2
    src = default_stitched(DATA, official_settle=True)
    cands = cp.build_component_candidates(src, ctx3.cfg, ctx3.specs, ctx3.panels)
    audits = {}
    for k, c in cands.items():
        ok, a = ce.audit_candidate(c)
        audits[k] = ok
        a.to_csv(OUT / f"point_in_time_audit_{k}.csv", index=False)
    msf = msf_candidate(cands)
    ok_msf, _ = ce.audit_candidate(msf)
    timing = {k: cp.release_timing_ok(cands[k].audit) for k in ("A", "B", "P")}
    print(f"点时审计:{audits};MSF {ok_msf};发布类公布日 ≤ 目标日 {timing}", flush=True)
    if not (all(audits.values()) and ok_msf and all(timing.values())):
        print("STOP: 点时审计失败", file=sys.stderr)
        return 3
    trunc = truncation_check(src, ctx3.cfg, ctx3.specs, {k: c.signal for k, c in cands.items()})
    trunc_ok = all(
        np.isfinite(v) and v < 1e-9 and not k.endswith("mismatch")
        for r in trunc.values()
        for k, v in r.items()
    )
    print(f"截断不变性 {trunc_ok}", flush=True)
    if not trunc_ok:
        (OUT / "truncation.json").write_text(json.dumps(trunc, indent=1), encoding="utf-8")
        print("STOP: 截断不变性失败(见 truncation.json)", file=sys.stderr)
        return 4
    msf.signal.to_csv(OUT / "signal_MSF.csv")

    ev3 = ce.evaluate(ctx3, msf)
    ce.write_eval(OUT / "vs_v03", ev3)
    ev1 = ce.evaluate(ctx1, msf)
    ce.write_eval(OUT / "vs_v01", ev1)
    div = diversification(ctx3, cands, msf)
    sysl, _ = system_level(ctx3, ctx1, src, msf.signal)
    print(
        f"生产接线一致 {sysl['wiring_identical']};v0.6 目标复现 {sysl['target_reproduces_production']}",
        flush=True,
    )

    log: dict[str, Any] = {
        "git_sha": git_sha(),
        "prereg_commit": prereg_commit(),
        "seed": SEED,
        "window": [str(ctx3.start.date()), str(ctx3.end.date())],
        "baseline_matches_reference": {
            "v0.3": ctx3.baseline_matches_reference,
            "v0.1": ctx1.baseline_matches_reference,
        },
        "point_in_time_ok": {**audits, "MSF": ok_msf},
        "release_timing_ok": timing,
        "truncation": trunc,
        "truncation_ok": trunc_ok,
        "evals": {
            base: {
                "verdict": ev.verdict,
                "checks": ev.checks,
                "first_active": str(ev.first_active.date()),
                "summary": ev.summary.to_dict(orient="records"),
                "paired": ev.paired,
                "regression": ev.regression,
                "top3_share": ev.contrib["MSF_standalone"]["top3_share"],
                "symbol_net_full": ev.contrib["MSF_standalone"]["symbol_table"]["net_FULL"]
                .round(0)
                .to_dict(),
                "year": ev.contrib["MSF_standalone"]["year"].round(0).to_dict(),
                "sector": ev.contrib["MSF_standalone"]["sector_table"].round(0).to_dict(),
            }
            for base, ev in (("v0.3", ev3), ("v0.1", ev1))
        },
        "diversification": div,
        "system": sysl,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (OUT / "run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    write_doc(log, ev3, ev1)
    for base, ev in (("v0.3", ev3), ("v0.1", ev1)):
        sa, bl = arm_row(ev, "MSF_standalone", "SINCE_ACTIVE"), arm_row(ev, "MSF_blend", "SINCE_ACTIVE")
        b = arm_row(ev, "baseline", "SINCE_ACTIVE")
        p = ev.paired["MSF_blend"]["since_active"]
        print(
            f"vs {base}: MSF 单独夏普 {sa['夏普(月频)']:.2f} | 混合 {bl['夏普(月频)']:.2f} vs 基线 {b['夏普(月频)']:.2f} | 配对差 {p['ann_mean']:+.2%} (t {p['t']:.2f}) | {ev.verdict}",
            flush=True,
        )
    print(f"-> {OUT} / {DOC} ({round(time.time() - t0, 1)} s)")
    return 0


def _pct(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"{f:+.2%}" if np.isfinite(f) else "n/a"


def _f(v: Any, nd: int = 2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"{f:.{nd}f}" if np.isfinite(f) else "n/a"


def write_doc(log: dict[str, Any], ev3: ce.CandidateEval, ev1: ce.CandidateEval) -> None:
    human = ""
    if DOC.exists():
        old = DOC.read_text(encoding="utf-8")
        if HUMAN_START in old and HUMAN_END in old:
            human = old[old.index(HUMAN_START) + len(HUMAN_START) : old.index(HUMAN_END)]
    lines = [
        "# 多源基本面合成因子 MSF:演示结果(样本内演示;预注册 `docs/research/msf_prereg.md`;试验 60)",
        "",
        "> 第 0 节由人撰写(标记之间,重跑保留);第 1–5 节由 `scripts/research/msf_demo.py` 生成。除新成分 P 外,其余 11 个成分在 2016–2026 上都已单独看过,本文数字**只是演示,不是证据**。",
        "",
        f"git `{log['git_sha']}`;预注册提交 `{log['prereg_commit']}`;窗口 {log['window'][0]} → {log['window'][1]};种子 {log['seed']};基线复现 v0.3 {log['baseline_matches_reference']['v0.3']} / v0.1 {log['baseline_matches_reference']['v0.1']}。",
        "",
        "## 0. 结论",
        HUMAN_START + (human if human else "\n(待写)\n") + HUMAN_END,
        "",
        "## 1. 点时与接线核对",
        "",
        f"- 12 个成分各自点时审计(决策日 ≤ 信息日 < 建仓日):{log['point_in_time_ok']}",
        f"- 发布类成分(A 月末持仓、B PMI、P PPI−PPIRM)实际公布日 ≤ 目标日(目标日 T 的成交在 T 日 21:00 夜盘或 T+1 日盘,均晚于 09:30 公布):{log['release_timing_ok']}",
        f"- 截断不变性(面板与数据截到 {', '.join(TRUNC_CUTS)} 重算,截止日及之前的信号与完整数据下的最大差异):"
        + "; ".join(
            f"{cut}: " + ", ".join(f"{k} {v:.1e}" for k, v in r.items() if not k.endswith("mismatch"))
            for cut, r in log["truncation"].items()
        )
        + f" → {log['truncation_ok']}",
        f"- 生产接线(`pipeline._extra_factors_of` 构造的 MSF)与本脚本逐位一致:{log['system']['wiring_identical']};v0.6 目标暴露由同一路径复现:{log['system']['target_reproduces_production']}",
        "",
        "## 2. 三臂(MSF 单独 / 静态基线 / 50-50 事前风险预算混合;自 MSF 首个持仓日起)",
        "",
        "| 基线 | 臂 | 年化 | 月频夏普 | NW t | 最大回撤 | OOS 夏普 | 年化成本 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for base, ev in (("v0.3", ev3), ("v0.1", ev1)):
        for arm, label in (
            ("MSF_standalone", "MSF 单独"),
            ("baseline", f"{base} 静态"),
            ("MSF_blend", "50/50 混合"),
        ):
            r, o = arm_row(ev, arm, "SINCE_ACTIVE"), arm_row(ev, arm, "OOS")
            cost = (r.get("年化手续费占权益", np.nan) or 0) + (r.get("年化滑点占权益", np.nan) or 0)
            lines.append(
                f"| {base} | {label} | {_pct(r.get('年化收益'))} | {_f(r.get('夏普(月频)'))} | {_f(r.get('月频NW t'))} | {_pct(r.get('最大回撤'))} | {_f(o.get('夏普(月频)'))} | {_pct(cost)} |"
            )
    lines += [
        "",
        "| 基线 | 首个持仓日 | 混合 − 基线 年化 (t) | 95% CI | OOS 混合 − 基线 | MSF 单独与基线日相关 | 前三品种占正贡献 | 信号加权毛收益 NW t | 判读(R0–R14) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for base, ev in (("v0.3", ev3), ("v0.1", ev1)):
        p, po = ev.paired["MSF_blend"]["since_active"], ev.paired["MSF_blend"]["oos"]
        lines.append(
            f"| {base} | {ev.first_active.date()} | {_pct(p['ann_mean'])} ({_f(p['t'])}) | [{_pct(p['boot_ci_low_ann'])}, {_pct(p['boot_ci_high_ann'])}] | {_pct(po['ann_mean'])} ({_f(po['t'])}) | {_f(ev.paired['MSF_standalone']['corr_daily_with_baseline'])} | {_pct(ev.contrib['MSF_standalone']['top3_share'])} | {_f(ev.regression.get('signal_weighted_nw_t'))} | {ev.verdict}(样本内演示) |"
        )
    sysl = log["system"]
    lines += [
        "",
        "## 3. 系统级:v0.6 = 时序动量 + 展期收益 + MSF(其余参数与 v0.3 相同)",
        "",
        "| 方案 | 区间 | 年化 | 月频夏普 | NW t | 最大回撤 | 年化换手 | 年化成本 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sysl["summary"]:
        cost = r["年化手续费占权益"] + r["年化滑点占权益"]
        lines.append(
            f"| {r['arm']} | {r['period']} | {_pct(r['年化收益'])} | {_f(r['夏普(月频)'])} | {_f(r['月频NW t'])} | {_pct(r['最大回撤'])} | {_f(r['年化名义换手'], 0)}× | {_pct(cost)} |"
        )
    lines += ["", "| v0.6 相对 | 区间 | 配对差年化 (t) | 95% CI | 日相关 |", "|---|---|---|---|---|"]
    for base, d in sysl["paired_v06_minus"].items():
        for per, p in d.items():
            lines.append(
                f"| {base} | {per} | {_pct(p['ann_mean'])} ({_f(p['t'])}) | [{_pct(p['boot_ci_low_ann'])}, {_pct(p['boot_ci_high_ann'])}] | {_f(sysl['corr_daily'][base])} |"
            )
    yrs = sorted(sysl["yearly_return"]["v0.6"])
    lines += [
        "",
        "逐年收益:",
        "",
        "| 方案 | " + " | ".join(yrs) + " |",
        "|---|" + "---|" * len(yrs),
    ]
    for name, d in sysl["yearly_return"].items():
        lines.append(f"| {name} | " + " | ".join(_pct(d.get(y)) for y in yrs) + " |")
    div = log["diversification"]
    comps = list(cp.COMPONENTS)
    lines += [
        "",
        "## 4. 分散化(信号加权的等风险毛收益,不含成本;评估器口径,与引擎回测不可直接比)",
        "",
        "| 成分 | 全区间年化 | 年化波动 | 夏普 | NW t | OOS 夏普 | 与 MSF 的信号相关 |",
        "|---|---|---|---|---|---|---|",
    ]
    for k in [*comps, "MSF"]:
        s, so = div["stats"][k]["FULL"], div["stats"][k]["OOS"]
        sc = div["signal_corr_msf_vs_component"].get(k, np.nan) if k != "MSF" else 1.0
        lines.append(
            f"| {k} | {_pct(s['ann_mean'])} | {_pct(s['ann_vol'])} | {_f(s['sharpe'])} | {_f(s['nw_t'])} | {_f(so['sharpe'])} | {_f(sc)} |"
        )
    lines += [
        "",
        f"成分两两相关:平均 {_f(div['mean_offdiag_corr'], 3)},中位数 {_f(div['median_offdiag_corr'], 3)}(矩阵见 `results/msf_demo/component_corr.csv`)。",
        "",
        "| | " + " | ".join(comps) + " |",
        "|---|" + "---|" * len(comps),
    ]
    for a in comps:
        lines.append(f"| {a} | " + " | ".join(_f(div["corr"][a].get(b), 2) for b in comps) + " |")
    lines += [
        "",
        "每个品种平均有几个成分在发声(窗口内,12 个里):"
        + ", ".join(f"{k} {v}" for k, v in div["n_active_per_symbol"].items()),
        "",
        "按年:" + ", ".join(f"{k} {v}" for k, v in div["n_active_by_year"].items()),
        "",
        "## 5. 逐品种 / 逐年 / 板块(MSF 单独,对 v0.3 口径,元)",
        "",
        "品种:"
        + ", ".join(f"{k} {v / 1e4:+.0f} 万" for k, v in log["evals"]["v0.3"]["symbol_net_full"].items()),
        "",
        "年份:" + ", ".join(f"{k} {v / 1e4:+.0f} 万" for k, v in log["evals"]["v0.3"]["year"].items()),
        "",
    ]
    DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
