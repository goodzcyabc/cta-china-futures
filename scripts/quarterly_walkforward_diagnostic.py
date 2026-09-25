"""季度 walk-forward 诊断(预注册 docs/quarterly_walkforward_prereg.md;后验提出的历史 walk-forward,只作诊断)。

用法:
  PYTHONPATH=src python3 scripts/quarterly_walkforward_diagnostic.py --mode smoke   # 只跑 2022Q1、2022Q2 + 三项门槛检查
  PYTHONPATH=src python3 scripts/quarterly_walkforward_diagnostic.py --mode full    # 2020Q1–2026Q2 全部 vintage
输出:results/quarterly_walkforward/*.csv、run.json;docs/quarterly_walkforward_diagnostic.md(表格部分;结论由人写在文末)。
不改任何策略对象、纸面账或正式报告。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.analysis import walkforward as wf  # noqa: E402
from cta.analysis.loo import segment_stats  # noqa: E402
from cta.analysis.stats import paired_summary  # noqa: E402
from cta.backtest.engine import BacktestResult, run_backtest  # noqa: E402
from cta.config import StrategyConfig, load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors.base import FactorInputs  # noqa: E402
from cta.factors.evaluate import evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import (
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    git_sha,
    summarize_result,
)  # noqa: E402
from cta.signals.core import combine  # noqa: E402

RQ = Path("data/ricecta/data")
HIST = pd.Timestamp("2016-01-04")
RUN_START = pd.Timestamp("2020-01-02")
OOS_START, OOS_END = pd.Timestamp("2022-01-04"), pd.Timestamp("2026-06-05")
SEED, N_BOOT, BLOCK, LAGS = 20260925, 2000, 10, 5


def engine_run(
    target: pd.DataFrame, panels: dict[str, Any], specs: Any, cfg: StrategyConfig
) -> BacktestResult:
    return run_backtest(
        panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )


def seg(eq: pd.Series[Any], a: pd.Timestamp, b: pd.Timestamp) -> dict[str, float]:
    return segment_stats(eq, a, b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    ap.add_argument("--out", default="results/quarterly_walkforward")
    ap.add_argument("--doc", default="docs/quarterly_walkforward_diagnostic.md")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs = load_instruments()
    cfg1 = load_config(Path("configs/strategy.yaml"))
    cfg3 = load_config(Path("configs/strategy_v03.yaml"))
    src = default_stitched(RQ, official_settle=True)
    panels = build_panels(src, cfg3, specs)
    sig1 = compute_signals(panels, cfg1, specs=specs)
    sig3 = compute_signals(
        panels, cfg3, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg3)
    )
    x1, x3 = FactorInputs.from_panels(panels, cfg1), FactorInputs.from_panels(panels, cfg3)
    dates = pd.DatetimeIndex(x1.adj_close.index)
    sigs = {f.name: f.compute(x1) for f in ALL_FACTORS}
    cands = [f.name for f in ALL_FACTORS if not f.reference]
    combo_v01 = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"]})
    quarters = wf.quarter_schedule(dates, "2020Q1", "2026Q2", end_clip=OOS_END, oos_start=OOS_START)
    log: dict[str, Any] = {"git_sha": git_sha(), "mode": args.mode, "n_quarters": len(quarters)}

    # ---------- smoke 门槛 ----------
    if args.mode == "smoke":
        quarters = [q for q in quarters if q.quarter in ("2022Q1", "2022Q2")]
        # ⑥ 静态基线复现
        tgt = wf.targets_from_comb(
            sig3.combined, sig3.eligible, sig3.vol, sig3.adj_close, cfg3, HIST, pd.Timestamp("2026-09-18")
        )
        assert np.allclose(
            tgt.to_numpy(dtype=float),
            sig3.target.loc[tgt.index, tgt.columns].to_numpy(dtype=float),
            equal_nan=True,
        )
        st, _ = summarize_result(engine_run(tgt, panels, specs, cfg3), specs)
        ref = json.loads(
            Path("results/settle_baseline/v0.3_full_D_unified_official.json").read_text(encoding="utf-8")
        )["stats"]
        d_sh = abs(st["夏普(月频)"] - ref["夏普(月频)"])
        log["baseline_check"] = {"sharpe_m": st["夏普(月频)"], "ref": ref["夏普(月频)"], "abs_diff": d_sh}
        print(
            f"⑥ 静态基线复现:夏普 {st['夏普(月频)']:.4f} vs 正式 {ref['夏普(月频)']:.4f}(差 {d_sh:.2e})",
            flush=True,
        )
        if d_sh > 1e-9:
            print("STOP: 静态基线无法复现", file=sys.stderr)
            return 2
        # ①② 截断到 cutoff 后选择不变;截断面板末日 = cutoff;仓单可得
        for q in quarters:
            trunc = build_panels(src, cfg1, specs, end=q.cutoff)
            assert all(pd.Timestamp(p.frame.index.max()) == q.cutoff for p in trunc.values()), (
                "面板末日 ≠ cutoff"
            )
            xt = FactorInputs.from_panels(trunc, cfg1)
            st_ = {f.name: f.compute(xt) for f in ALL_FACTORS}
            tab_t = wf.training_table(
                st_,
                cands,
                combine({"tsmom": st_["tsmom"], "carry": st_["carry"]}),
                xt,
                specs,
                cfg1,
                HIST,
                q.cutoff,
            )
            tab_f = wf.training_table(sigs, cands, combo_v01, x1, specs, cfg1, HIST, q.cutoff)
            same = wf.select_44(tab_t, cands) == wf.select_44(tab_f, cands) and np.allclose(
                tab_t[["sharpe_m", "nw_t", "corr_v01"]].to_numpy(dtype=float),
                tab_f[["sharpe_m", "nw_t", "corr_v01"]].to_numpy(dtype=float),
                atol=1e-9,
                equal_nan=True,
            )
            rec_min = pd.DatetimeIndex(src.receipts().index).min()
            print(
                f"①② {q.quarter} cutoff {q.cutoff.date()}:截断后选择/统计不变={same};仓单最早 {rec_min.date()}",
                flush=True,
            )
            log.setdefault("truncation_checks", []).append({"quarter": q.quarter, "same": bool(same)})
            if not same:
                print("STOP: 截断后选择或统计改变(前视)", file=sys.stderr)
                return 3

    # ---------- 实验 A ----------
    cache: dict[pd.Timestamp, tuple[pd.DataFrame, list[str]]] = {}

    def train(cut: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
        if cut not in cache:
            tab = wf.training_table(sigs, cands, combo_v01, x1, specs, cfg1, HIST, cut)
            cache[cut] = (tab, wf.select_44(tab, cands))
        return cache[cut]

    rows_a, train_rows = [], []
    pieces: dict[str, list[tuple[wf.QuarterSpec, pd.DataFrame]]] = {"Q": [], "Y": [], "S": []}
    combo_train_rows = []
    prev_q: list[str] | None = None
    prev_y: list[str] | None = None
    for q in quarters:
        tab_q, ch_q = train(q.cutoff)
        cut_y = wf.annual_cutoff(dates, q.quarter)
        tab_y, ch_y = train(cut_y)
        sig_q = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"], **{c: sigs[c] for c in ch_q}})
        sig_y = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"], **{c: sigs[c] for c in ch_y}})
        pieces["Q"].append((q, sig_q))
        pieces["Y"].append((q, sig_y))
        pieces["S"].append((q, combo_v01))
        for arm, tab, ch, cut in (("Q", tab_q, ch_q, q.cutoff), ("Y", tab_y, ch_y, cut_y)):
            for f, r in tab.iterrows():
                train_rows.append(
                    {
                        "quarter": q.quarter,
                        "arm": arm,
                        "cutoff": cut,
                        "factor": f,
                        **r.to_dict(),
                        "selected": f in ch,
                    }
                )
        # 冻结组合在训练期(评估器口径)的夏普 —— 用于"每个 vintage 的 IS vs 下一季"对照
        for arm, sg, cut in (("Q", sig_q, q.cutoff), ("Y", sig_y, cut_y), ("S", combo_v01, q.cutoff)):
            tr = evaluate_factor(arm, sg, x1, specs, cfg1, HIST, cut)
            nx = evaluate_factor(arm, sg, x1, specs, cfg1, q.start, q.end)
            nxn = nx.net.to_numpy(dtype=float)
            combo_train_rows.append(
                {
                    "quarter": q.quarter,
                    "arm": arm,
                    "train_sharpe_m": float(tr.stats.get("夏普(月频)", np.nan)),
                    "next_q_net_ret": float(nxn.sum()),
                    "next_q_sharpe_d": float(nxn.mean() / nxn.std(ddof=1) * np.sqrt(243))
                    if len(nxn) > 2 and nxn.std(ddof=1) > 0
                    else np.nan,
                }
            )
        rows_a.append(
            {
                "quarter": q.quarter,
                "cutoff": q.cutoff,
                "annual_cutoff": cut_y,
                "trade_start": q.start,
                "trade_end": q.end,
                "formal_oos": q.formal_oos,
                "Q_selected": ",".join(ch_q) or "(无)",
                "Y_selected": ",".join(ch_y) or "(无)",
                "Q_n_factors": 2 + len(ch_q),
                "Y_n_factors": 2 + len(ch_y),
                "Q_changed": prev_q is not None and ch_q != prev_q,
                "Y_changed": prev_y is not None and ch_y != prev_y,
            }
        )
        prev_q, prev_y = ch_q, ch_y
        print(f"A {q.quarter} cut {q.cutoff.date()} Q={ch_q or '-'} Y={ch_y or '-'}", flush=True)
    tab_a = pd.DataFrame(rows_a).set_index("quarter")
    pd.DataFrame(train_rows).to_csv(out / "expA_training_stats.csv", index=False)
    pd.DataFrame(combo_train_rows).to_csv(out / "expA_vintage_train_vs_next.csv", index=False)
    res_a: dict[str, BacktestResult] = {}
    for arm in ("Q", "Y", "S"):
        stitched = wf.stitch_quarters(pieces[arm], dates)
        wf.assert_frozen(stitched, pieces[arm])
        tgt = wf.targets_from_comb(
            stitched, sig1.eligible, sig1.vol, sig1.adj_close, cfg1, quarters[0].start, quarters[-1].end
        )
        res_a[arm] = engine_run(tgt, panels, specs, cfg1)
        res_a[arm].equity.to_csv(out / f"equity_A_{arm}.csv")
    # 逐季记录(引擎口径)、逐品种/板块、配对
    rec_a = {arm: wf.quarter_engine_records(r, specs, quarters) for arm, r in res_a.items()}
    sym_a = {arm: wf.quarter_symbol_contrib(r, specs, quarters) for arm, r in res_a.items()}
    for arm in res_a:
        rec_a[arm].to_csv(out / f"expA_quarters_{arm}.csv")
        sym_a[arm].to_csv(out / f"expA_symbol_contrib_{arm}.csv")
        wf.sector_contrib(sym_a[arm], specs).to_csv(out / f"expA_sector_contrib_{arm}.csv")
    paired_a = {
        arm: wf.paired_by_quarter(res_a[arm].equity, res_a["S"].equity, quarters) for arm in ("Q", "Y")
    }
    for arm, p in paired_a.items():
        p.to_csv(out / f"expA_paired_{arm}_vs_S.csv")
    # 候选下一季 sleeve 表现(评估器口径):选中 vs 未选中
    sleeve = wf.sleeve_quarter_perf(sigs, x1, specs, cfg1, quarters)
    sleeve.to_csv(out / "expA_sleeve_next_quarter.csv", index=False)
    sel_map = {
        (r["quarter"], f): (f in r["Q_selected"].split(","))
        for _, r in tab_a.reset_index().iterrows()
        for f in cands
    }
    sleeve_c = sleeve[sleeve["factor"].isin(cands)].copy()
    sleeve_c["selected_Q"] = [sel_map[(q, f)] for q, f in zip(sleeve_c["quarter"], sleeve_c["factor"])]
    sel_summary = sleeve_c.groupby("selected_Q")[["net_ret", "sharpe_d"]].agg(["mean", "count"])
    sel_summary.to_csv(out / "expA_selected_vs_unselected.csv")

    # ---------- 实验 B ----------
    parts3 = {"tsmom": sig3.tsmom, "carry": sig3.carry, "receipts_level": sig3.receipts_level}
    rows_b, pieces_b, pieces_s3 = [], [], []
    w_prev = 1.0
    for q in quarters:
        sh, w = wf.carry_gate(sig3.carry, x3, specs, cfg3, q.cutoff)
        nx = evaluate_factor("carry", sig3.carry, x3, specs, cfg3, q.start, q.end)
        nxn = nx.net.to_numpy(dtype=float)
        pieces_b.append((q, combine(parts3, {"tsmom": 1.0, "carry": w, "receipts_level": 1.0})))
        pieces_s3.append((q, combine(parts3, dict(cfg3.signals.weights))))
        rows_b.append(
            {
                "quarter": q.quarter,
                "cutoff": q.cutoff,
                "formal_oos": q.formal_oos,
                "carry_3y_net_sharpe_m": sh,
                "carry_weight": w,
                "switched": w != w_prev,
                "carry_next_q_net_ret": float(nxn.sum()),
                "carry_next_q_sharpe_d": float(nxn.mean() / nxn.std(ddof=1) * np.sqrt(243))
                if len(nxn) > 2 and nxn.std(ddof=1) > 0
                else np.nan,
            }
        )
        w_prev = w
        print(f"B {q.quarter} cut {q.cutoff.date()} carry 3y {sh:+.2f} → w={w}", flush=True)
    tab_b = pd.DataFrame(rows_b).set_index("quarter")
    tab_b.to_csv(out / "expB_quarters.csv")
    res_b: dict[str, BacktestResult] = {}
    for arm, pcs in (("C3", pieces_b), ("S3", pieces_s3)):
        stitched = wf.stitch_quarters(pcs, dates)
        wf.assert_frozen(stitched, pcs)
        tgt = wf.targets_from_comb(
            stitched, sig3.eligible, sig3.vol, sig3.adj_close, cfg3, quarters[0].start, quarters[-1].end
        )
        res_b[arm] = engine_run(tgt, panels, specs, cfg3)
        res_b[arm].equity.to_csv(out / f"equity_B_{arm}.csv")
    rec_b = {arm: wf.quarter_engine_records(r, specs, quarters) for arm, r in res_b.items()}
    sym_b = {arm: wf.quarter_symbol_contrib(r, specs, quarters) for arm, r in res_b.items()}
    for arm in res_b:
        rec_b[arm].to_csv(out / f"expB_quarters_{arm}.csv")
        sym_b[arm].to_csv(out / f"expB_symbol_contrib_{arm}.csv")
        wf.sector_contrib(sym_b[arm], specs).to_csv(out / f"expB_sector_contrib_{arm}.csv")
    paired_b = wf.paired_by_quarter(res_b["C3"].equity, res_b["S3"].equity, quarters)
    paired_b.to_csv(out / "expB_paired_C3_vs_S3.csv")
    sleeve3 = wf.sleeve_quarter_perf(parts3, x3, specs, cfg3, quarters)
    sleeve3.to_csv(out / "expB_sleeve_next_quarter.csv", index=False)

    # ---------- 汇总 ----------
    summary = []
    for label, res, base in (
        ("A_Q_季度重选", res_a["Q"], res_a["S"]),
        ("A_Y_年度重选", res_a["Y"], res_a["S"]),
        ("A_S_固定v0.1", res_a["S"], None),
        ("B_C3_carry开关", res_b["C3"], res_b["S3"]),
        ("B_S3_静态v0.3", res_b["S3"], None),
    ):
        oos = seg(res.equity, OOS_START, OOS_END)
        ctx = seg(res.equity, RUN_START, OOS_END)
        row: dict[str, Any] = {
            "arm": label,
            "OOS年化": oos["年化收益"],
            "OOS夏普(月)": oos["夏普(月频)"],
            "OOS回撤": oos["最大回撤"],
            "2020起年化": ctx["年化收益"],
            "2020起夏普(月)": ctx["夏普(月频)"],
        }
        if base is not None:
            ps = paired_summary(
                base.equity, res.equity, lags=LAGS, block=BLOCK, n_boot=N_BOOT, seed=SEED, start=OOS_START
            )
            pq = wf.paired_by_quarter(res.equity, base.equity, [q for q in quarters if q.formal_oos])
            row.update(
                {
                    "配对差年化": ps["ann_mean"],
                    "NW_SE年化": ps["nw_se_ann"],
                    "t": ps["t"],
                    "boot95低": ps["boot_ci_low_ann"],
                    "boot95高": ps["boot_ci_high_ann"],
                    "季度胜率": float(pq["dyn_wins"].mean()) if len(pq) else np.nan,
                    "n_days": ps["n_days"],
                }
            )
        summary.append(row)
    summ = pd.DataFrame(summary).set_index("arm")
    summ.to_csv(out / "summary.csv")
    log.update(
        {
            "elapsed_s": round(time.time() - t0, 1),
            "seed": SEED,
            "n_boot": N_BOOT,
            "block": BLOCK,
            "lags": LAGS,
            "quarters": [q.quarter for q in quarters],
        }
    )
    (out / "run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    write_doc(
        Path(args.doc),
        args.mode,
        log,
        summ,
        tab_a,
        tab_b,
        rec_a,
        rec_b,
        paired_a,
        paired_b,
        sleeve,
        sleeve3,
        sel_summary,
        sym_a,
        sym_b,
        pd.DataFrame(combo_train_rows),
        specs,
        quarters,
    )
    print(summ.round(3).to_string())
    print(f"-> {out} / {args.doc} ({log['elapsed_s']} s)")
    return 0


def _pct(v: Any) -> str:
    return f"{float(v):+.2%}" if v is not None and np.isfinite(float(v)) else "n/a"


def write_doc(
    path: Path,
    mode: str,
    log: dict[str, Any],
    summ: pd.DataFrame,
    tab_a: pd.DataFrame,
    tab_b: pd.DataFrame,
    rec_a: dict[str, pd.DataFrame],
    rec_b: dict[str, pd.DataFrame],
    paired_a: dict[str, pd.DataFrame],
    paired_b: pd.DataFrame,
    sleeve: pd.DataFrame,
    sleeve3: pd.DataFrame,
    sel_summary: pd.DataFrame,
    sym_a: dict[str, pd.DataFrame],
    sym_b: dict[str, pd.DataFrame],
    vint: pd.DataFrame,
    specs: Any,
    quarters: list[wf.QuarterSpec],
) -> None:
    lines: list[str] = [
        f"# 季度 walk-forward 诊断({'SMOKE' if mode == 'smoke' else '全量'};后验提出的历史 walk-forward,只作诊断)",
        "",
        f"预注册:`docs/quarterly_walkforward_prereg.md`;git `{log['git_sha']}`;季度模型 {len(quarters)} 个({sum(q.formal_oos for q in quarters)} 个在正式 OOS 内);训练窗口相互重叠,不是独立实验;引擎自 2020-01-02 空仓连续运行到 2026-06-05。",
        "",
        "## 汇总(主指标:2022-01-04 → 2026-06-05 拼接段;配对差相对各自基线,NW lag 5,块 bootstrap 块长 10 × 2000 次,种子 20260925)",
        "",
        "| 臂 | OOS 年化 | OOS 夏普(月) | OOS 回撤 | 2020 起夏普 | 配对差年化 | NW SE | t | bootstrap 95% | 季度胜率 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, r in summ.iterrows():
        pd_ = (
            _pct(r.get("配对差年化", np.nan))
            if "配对差年化" in r and pd.notna(r.get("配对差年化", np.nan))
            else "—"
        )
        has = pd_ != "—"
        se = _pct(r.get("NW_SE年化", np.nan)) if has else "—"
        tv = f"{float(r['t']):.2f}" if has and pd.notna(r.get("t", np.nan)) else "—"
        ci = f"[{_pct(r['boot95低'])}, {_pct(r['boot95高'])}]" if has else "—"
        wr = f"{float(r['季度胜率']):.0%}" if has and pd.notna(r.get("季度胜率", np.nan)) else "—"
        lines.append(
            f"| {arm} | {_pct(r['OOS年化'])} | {r['OOS夏普(月)']:.2f} | {_pct(r['OOS回撤'])} | "
            f"{r['2020起夏普(月)']:.2f} | {pd_} | {se} | {tv} | {ci} | {wr} |"
        )
    lines += [
        "",
        "## 实验 A:逐季选择",
        "",
        tab_a.reset_index()[
            [
                "quarter",
                "cutoff",
                "annual_cutoff",
                "trade_start",
                "trade_end",
                "formal_oos",
                "Q_selected",
                "Y_selected",
                "Q_changed",
                "Y_changed",
            ]
        ].to_markdown(index=False),
        "",
    ]
    for arm in ("Q", "Y", "S"):
        r = rec_a[arm]
        lines += [
            f"### 实验 A 臂 {arm}:逐季引擎口径",
            "",
            r[
                [
                    "ret",
                    "gross_pnl",
                    "fees",
                    "net_pnl",
                    "cost_share",
                    "turnover_notional",
                    "n_trades",
                    "mdd_in_quarter",
                ]
            ]
            .round(4)
            .to_markdown(),
            "",
        ]
    for arm, p in paired_a.items():
        lines += [f"### 实验 A 臂 {arm} 相对 summ 的逐季配对", "", p.round(4).to_markdown(), ""]
    lines += [
        "### 实验 A:每个 vintage 冻结组合的训练期夏普 vs 下一季实现(评估器口径;单季夏普只作记录)",
        "",
        vint.round(3).to_markdown(index=False),
        "",
    ]
    lines += [
        "### 实验 A:被选中 vs 未被选中候选的下一季 sleeve 表现(评估器口径,均值)",
        "",
        sel_summary.round(4).to_markdown(),
        "",
    ]
    piv = sleeve.pivot(index="quarter", columns="factor", values="net_ret").round(4)
    lines += ["### 逐因子 sleeve 下一季净收益(评估器口径)", "", piv.to_markdown(), ""]
    lines += ["## 实验 B:carry 开关", "", tab_b.reset_index().round(3).to_markdown(index=False), ""]
    for arm in ("C3", "S3"):
        lines += [
            f"### 实验 B 臂 {arm}:逐季引擎口径",
            "",
            rec_b[arm][
                [
                    "ret",
                    "gross_pnl",
                    "fees",
                    "net_pnl",
                    "cost_share",
                    "turnover_notional",
                    "n_trades",
                    "mdd_in_quarter",
                ]
            ]
            .round(4)
            .to_markdown(),
            "",
        ]
    lines += ["### 实验 B:C3 相对静态 v0.3 的逐季配对", "", paired_b.round(4).to_markdown(), ""]
    lines += [
        "### 实验 B:v0.3 三因子 sleeve 逐季净收益(评估器口径)",
        "",
        sleeve3.pivot(index="quarter", columns="factor", values="net_ret").round(4).to_markdown(),
        "",
    ]
    for label, sym in (
        ("A_S 固定 v0.1", sym_a["S"]),
        ("A_Q 季度重选", sym_a["Q"]),
        ("B_S3 静态 v0.3", sym_b["S3"]),
        ("B_C3", sym_b["C3"]),
    ):
        sec = wf.sector_contrib(sym, specs)
        lines += [f"### 逐板块净贡献(元,引擎口径):{label}", "", (sec / 1e4).round(1).to_markdown(), ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
