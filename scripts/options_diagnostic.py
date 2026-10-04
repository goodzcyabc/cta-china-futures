"""商品期权隐含信息三条的回顾性诊断(预注册 docs/options_prereg.md;试验 57–59)。

用法:PYTHONPATH=src python3 scripts/options_diagnostic.py [--smoke] [--only O1,O2,O3]
smoke:只做基线复现、点时审计与信号覆盖统计,不跑候选引擎、不看收益。
输出:results/options_diagnostic/、docs/options_diagnostic.md(表格;结论由人按预注册判读后追加在标记之间)。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.analysis import candidate_eval as ce  # noqa: E402
from cta.analysis import options_signals as osig  # noqa: E402
from cta.analysis.stats import block_bootstrap_mean, paired_differences  # noqa: E402
from cta.pipeline import git_sha  # noqa: E402
from cta.risk.metrics import TRADING_DAYS  # noqa: E402

DATA = Path("data/external/alt")
OPTION_TABLES = ("shfe_options", "czce_options")
SEED = 20261004


def prereg_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "log", "--format=%h", "--diff-filter=A", "--", "docs/options_prereg.md"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        return out[-1] if out else "uncommitted"
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def coverage(c: ce.Candidate, dates: pd.DatetimeIndex) -> dict[str, Any]:
    sig = c.signal.reindex(dates)
    per = {str(s): float(sig[s].notna().mean()) for s in c.basket}
    first = sig[c.basket].notna().any(axis=1)
    return {
        "basket": c.basket,
        "first_signal": str(first[first].index.min().date()) if first.any() else None,
        "share_days_with_signal": per,
        "mean_abs_signal": {str(s): float(sig[s].abs().mean()) for s in c.basket},
        "share_positive": {
            str(s): float((sig[s] > 0).sum() / max(sig[s].notna().sum(), 1)) for s in c.basket
        },
        "n_updates": int(len(c.audit)),
    }


def load_option_tables() -> pd.DataFrame:
    frames = []
    for name in OPTION_TABLES:
        p = DATA / name / "options_daily.parquet"
        if not p.exists():
            raise FileNotFoundError(p)
        frames.append(pd.read_parquet(p))
    o = pd.concat(frames, ignore_index=True)
    o["date"] = pd.to_datetime(o["date"])
    o["available_day"] = pd.to_datetime(o["available_day"])
    return o[o["product"].isin(osig.PRODUCTS)]


def futures_settles() -> pd.Series:  # type: ignore[type-arg]
    parts = []
    for ex in ("SHFE", "INE", "CZCE"):
        q = pd.read_parquet(
            Path("data/exchanges") / ex / "quotes_all.parquet", columns=["date", "contract", "settle"]
        )
        parts.append(q)
    q = pd.concat(parts, ignore_index=True)
    q["date"] = pd.to_datetime(q["date"])
    q = q.dropna(subset=["settle"]).drop_duplicates(["date", "contract"], keep="last")
    return pd.Series(
        q["settle"].to_numpy(dtype=float), index=pd.MultiIndex.from_arrays([q["date"], q["contract"]])
    )


def build_candidates(ctx: ce.Context, only: list[str]) -> tuple[dict[str, ce.Candidate], dict[str, Any]]:
    opts = load_option_tables()
    settles = futures_settles()
    cols = list(ctx.sig.adj_close.columns)
    feats: dict[str, osig.DailyFeatures] = {}
    meta: dict[str, Any] = {"products": {}}
    for prod in osig.PRODUCTS:
        if prod not in cols:
            continue
        mult = float(ctx.specs[prod].multiplier)
        f = osig.product_daily_features(opts, settles, ctx.sig.adj_close[prod], prod, mult)
        feats[prod] = f
        t = f.table
        meta["products"][prod] = {
            "option_days": int(len(t)),
            "first": str(t["date"].min().date()) if len(t) else None,
            "share_series_selected": float(t["underlying"].notna().mean()) if len(t) else 0.0,
            "share_skew": float(t["skew"].notna().mean()) if len(t) else 0.0,
            "share_sigma_a": float(t["sigma_a"].notna().mean()) if len(t) else 0.0,
            "median_sigma_a": float(t["sigma_a"].median()) if len(t) else float("nan"),
        }
        out = Path("results/options_diagnostic")
        out.mkdir(parents=True, exist_ok=True)
        t.to_csv(out / f"features_{prod}.csv", index=False)
    cands: dict[str, ce.Candidate] = {}
    for tag in only:
        cands[tag] = osig.build_candidate(tag, feats, ctx.dates, cols)
        meta[tag] = {
            "status": "ok",
            "n_obs": int(sum(len(f.table) for f in feats.values())),
            "obs_range": [str(opts["date"].min().date()), str(opts["date"].max().date())],
            "coverage": coverage(cands[tag], ctx.dates),
        }
    return cands, meta


def r15_bonferroni(ctx: ce.Context, ev: ce.CandidateEval, n_family: int) -> dict[str, Any]:
    """家族校正:混合配对差(自首个持仓日起)的块 bootstrap (1 − 0.05/n) 区间下限 > 0。"""
    bl = f"{ev.candidate.tag}_blend"
    d = paired_differences(ctx.res_base.equity, ev.arms[bl].equity, ev.first_active)["d"].to_numpy(
        dtype=float
    )
    alpha = 0.05 / n_family
    bt = block_bootstrap_mean(d, ctx.block, ctx.n_boot, ctx.seed, alpha=alpha)
    return {
        "alpha": alpha,
        "ci_low_ann": bt.ci_low * TRADING_DAYS,
        "ci_high_ann": bt.ci_high * TRADING_DAYS,
        "pass": bool(bt.ci_low > 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--only", default="O1,O2,O3")
    ap.add_argument("--out", default="results/options_diagnostic")
    ap.add_argument("--doc", default="docs/options_diagnostic.md")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = [t.strip() for t in args.only.split(",") if t.strip()]
    ctx = ce.build_context(seed=SEED)
    log: dict[str, Any] = {
        "git_sha": git_sha(),
        "prereg_commit": prereg_commit(),
        "seed": SEED,
        "window": [str(ctx.start.date()), str(ctx.end.date())],
        "baseline_matches_reference_D": ctx.baseline_matches_reference,
    }
    print(f"基线与正式 D 臂逐位一致 = {ctx.baseline_matches_reference}", flush=True)
    if ctx.baseline_matches_reference is False:
        print("STOP: 基线不能复现", file=sys.stderr)
        return 2
    cands, meta = build_candidates(ctx, only)
    log["sources"] = meta
    audits_ok = {}
    for tag, c in cands.items():
        ok, audit = ce.audit_candidate(c)
        audits_ok[tag] = ok
        audit.to_csv(out / f"point_in_time_audit_{tag}.csv", index=False)
        c.signal[c.basket].to_csv(out / f"signal_{tag}.csv")
        print(
            f"{tag}: 点时审计 {ok};篮子 {c.basket};首个信号 {meta[tag]['coverage']['first_signal']};更新 {len(c.audit)} 次",
            flush=True,
        )
    log["point_in_time_ok"] = audits_ok
    if not all(audits_ok.values()):
        print("STOP: 点时审计失败", file=sys.stderr)
        return 3
    if args.smoke:
        (out / "run.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print(f"smoke 完成({round(time.time() - t0, 1)} s)")
        return 0
    evals: dict[str, ce.CandidateEval] = {}
    rows = []
    verdicts: dict[str, Any] = {}
    n_family = len(cands)
    for tag, c in cands.items():
        ev = ce.evaluate(ctx, c)
        ce.write_eval(out, ev)
        r15 = r15_bonferroni(ctx, ev, n_family)
        verdict = ev.verdict
        if verdict == "Candidate signal" and not r15["pass"]:
            verdict = "Weak evidence"
        evals[tag] = ev
        verdicts[tag] = {
            "verdict": verdict,
            "verdict_before_R15": ev.verdict,
            "R15": r15,
            "checks": ev.checks,
            "first_active": str(ev.first_active.date()),
        }
        sa, bl = f"{tag}_standalone", f"{tag}_blend"
        s = ev.summary
        srow = s[(s["arm"] == sa) & (s["period"] == "SINCE_ACTIVE")].iloc[0]
        brow = s[(s["arm"] == bl) & (s["period"] == "SINCE_ACTIVE")].iloc[0]
        base = s[(s["arm"] == "baseline") & (s["period"] == "SINCE_ACTIVE")].iloc[0]
        p = ev.paired[bl]["since_active"]
        po = ev.paired[bl]["oos"]
        rows.append(
            {
                "candidate": tag,
                "name": c.name,
                "first_active": str(ev.first_active.date()),
                "basket": ",".join(c.basket),
                "sa_sharpe": srow["夏普(月频)"],
                "sa_nw_t": srow["月频NW t"],
                "sa_ann": srow["年化收益"],
                "sa_mdd": srow["最大回撤"],
                "sa_oos_sharpe": float(s[(s["arm"] == sa) & (s["period"] == "OOS")].iloc[0]["夏普(月频)"])
                if ((s["arm"] == sa) & (s["period"] == "OOS")).any()
                else np.nan,
                "base_sharpe": base["夏普(月频)"],
                "blend_sharpe": brow["夏普(月频)"],
                "paired_ann": p["ann_mean"],
                "paired_t": p["t"],
                "paired_ci95": [p["boot_ci_low_ann"], p["boot_ci_high_ann"]],
                "paired_oos_ann": po["ann_mean"],
                "paired_oos_ci95": [po["boot_ci_low_ann"], po["boot_ci_high_ann"]],
                "r15_ci_low": r15["ci_low_ann"],
                "corr_daily": ev.paired[sa]["corr_daily_with_baseline"],
                "cost_sa": srow["年化手续费占权益"] + srow["年化滑点占权益"],
                "max_quarter_share": ev.contrib[sa]["quarter_share"]["max_share_of_positive"],
                "top3_share": ev.contrib[sa]["top3_share"],
                "reg_or_swr_t": ev.regression.get("reg_FULL", {}).get(
                    "t", ev.regression.get("signal_weighted_nw_t")
                ),
                "verdict": verdict,
            }
        )
        print(
            f"{tag}: standalone 夏普 {srow['夏普(月频)']:.2f} | 混合 {brow['夏普(月频)']:.2f} vs 基线 {base['夏普(月频)']:.2f} | 配对差 {p['ann_mean']:+.2%} [{p['boot_ci_low_ann']:+.2%}, {p['boot_ci_high_ann']:+.2%}] | {verdict}",
            flush=True,
        )
    summ = pd.DataFrame(rows)
    summ.to_csv(out / "summary.csv", index=False)
    (out / "verdicts.json").write_text(
        json.dumps(verdicts, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    log.update(
        {"elapsed_s": round(time.time() - t0, 1), "verdicts": {k: v["verdict"] for k, v in verdicts.items()}}
    )
    (out / "run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    write_doc(Path(args.doc), log, summ, evals, verdicts, meta)
    print(
        summ[
            [
                "candidate",
                "sa_sharpe",
                "sa_nw_t",
                "blend_sharpe",
                "base_sharpe",
                "paired_ann",
                "paired_t",
                "corr_daily",
                "verdict",
            ]
        ]
        .round(3)
        .to_string()
    )
    print(f"-> {out} / {args.doc} ({round(time.time() - t0, 1)} s)")
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


def write_doc(
    path: Path,
    log: dict[str, Any],
    summ: pd.DataFrame,
    evals: dict[str, ce.CandidateEval],
    verdicts: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    lines = [
        "# 商品期权隐含信息三条:结果(回顾性诊断;预注册 `docs/options_prereg.md`)",
        "",
        "> 第 0 节(结论)与第 5 节以后由人撰写、保留在 HTML 标记之间;第 1–4 节表格由脚本生成,重跑只刷新表格;预注册第 1–10 节未改。",
        "",
        f"git `{log['git_sha']}`;预注册提交 `{log['prereg_commit']}`;窗口 {log['window'][0]} → {log['window'][1]};种子 {log['seed']};基线与正式 D 臂逐位一致 {log['baseline_matches_reference_D']}。",
        "",
        "## 1. 数据覆盖与点时",
        "",
        "| 候选 | 观测数 | 观测区间 | 篮子 | 首个信号 | 更新次数 | 有信号的交易日占比 | 信号为正占比 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for tag, m in meta.items():
        if not isinstance(m, dict) or m.get("status") != "ok":
            continue
        cov = m["coverage"]
        lines.append(
            f"| {tag} | {m['n_obs']} | {m['obs_range'][0]} → {m['obs_range'][1]} | {','.join(cov['basket'])} | {cov['first_signal']} | {cov['n_updates']} | {', '.join(f'{k} {v:.2f}' for k, v in cov['share_days_with_signal'].items())} | {', '.join(f'{k} {v:.2f}' for k, v in cov['share_positive'].items())} |"
        )
    if "N_count_median_2017_2019" in meta:
        lines += [
            "",
            f"N 的纳入规则(2017–2019 日文章数中位数 ≥ 20):{ {k: round(v, 1) for k, v in meta['N_count_median_2017_2019'].items()} }",
        ]
    lines += [
        "",
        "## 2. 汇总(自候选首个持仓日起;配对差 = 50/50 混合相对静态基线,NW 5 阶,块 bootstrap 10 × 2000)",
        "",
        "| 候选 | 首个持仓日 | standalone 夏普 / NW t / 年化 / 回撤 | OOS 夏普 | 混合夏普 vs 基线 | 配对差年化 (t) | 95% CI | OOS 配对差 | 99%/n CI 下限 (R15) | 日相关 | standalone 成本 | 最大单季 / 前三品种 占正贡献 | 主检验 t | 判定 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in summ.iterrows():
        ci = f"[{_pct(r['paired_ci95'][0])}, {_pct(r['paired_ci95'][1])}]"
        lines.append(
            f"| {r['candidate']} {r['name']} | {r['first_active']} | {_f(r['sa_sharpe'])} / {_f(r['sa_nw_t'])} / {_pct(r['sa_ann'])} / {_pct(r['sa_mdd'])} | {_f(r['sa_oos_sharpe'])} | {_f(r['blend_sharpe'])} vs {_f(r['base_sharpe'])} | {_pct(r['paired_ann'])} ({_f(r['paired_t'])}) | {ci} | {_pct(r['paired_oos_ann'])} | {_pct(r['r15_ci_low'])} | {_f(r['corr_daily'], 3)} | {_pct(r['cost_sa'])} | {_pct(r['max_quarter_share'])} / {_pct(r['top3_share'])} | {_f(r['reg_or_swr_t'])} | **{r['verdict']}** |"
        )
    lines += ["", "## 3. 判读明细(R0–R15)", ""]
    checks = pd.DataFrame({k: v["checks"] for k, v in verdicts.items()})
    lines += [
        checks.to_markdown(),
        "",
        "R15(家族校正,混合配对差 bootstrap 区间下限 > 0):"
        + ", ".join(f"{k}: {_pct(v['R15']['ci_low_ann'])} → {v['R15']['pass']}" for k, v in verdicts.items()),
        "",
    ]
    lines += ["## 4. 逐候选贡献与剔除", ""]
    for tag, ev in evals.items():
        sa = f"{tag}_standalone"
        c = ev.contrib[sa]
        lines += [
            f"### {tag} {ev.candidate.name}",
            "",
            f"- 最好年 {c['year_share']['max_item']}(占正贡献 {_pct(c['year_share']['max_share_of_positive'])}),最好季 {c['quarter_share']['max_item']}({_pct(c['quarter_share']['max_share_of_positive'])}),前三品种 {','.join(c['top3'])}({_pct(c['top3_share'])});去最好年夏普 {_f(c['ex_best_year']['夏普(月频)'])},去最好季 {_f(c['ex_best_quarter']['夏普(月频)'])},去前三品种(重跑){_f(c['ex_top3_symbols']['夏普(月频)'])};多头侧净 {c['long_net'] / 1e4:.1f} 万、空头侧净 {c['short_net'] / 1e4:.1f} 万、多头日占比 {_pct(c['days_long_share'])}。",
            "",
            "逐年净盈亏(万):" + ", ".join(f"{k} {v / 1e4:.1f}" for k, v in c["year"].items()),
            "",
            "回归/信号加权检验:"
            + json.dumps(
                {
                    k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in ev.regression.items()
                    if not isinstance(v, dict)
                },
                ensure_ascii=False,
            )
            + (
                "; 回归 "
                + json.dumps(
                    {
                        k: {kk: round(vv, 4) for kk, vv in v.items()}
                        for k, v in ev.regression.items()
                        if isinstance(v, dict)
                    },
                    ensure_ascii=False,
                )
                if any(isinstance(v, dict) for v in ev.regression.values())
                else ""
            ),
            "",
        ]
    top, bottom = "", ""
    if path.exists():
        prev = path.read_text(encoding="utf-8")
        for tag, dest in (("narrative-top", "top"), ("narrative-bottom", "bottom")):
            a, b = f"<!-- {tag} -->", f"<!-- /{tag} -->"
            if a in prev and b in prev:
                block = prev[prev.index(a) : prev.index(b) + len(b)]
                if dest == "top":
                    top = block
                else:
                    bottom = block
    if top:
        lines.insert(5, top)
    if bottom:
        lines.append(bottom)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
