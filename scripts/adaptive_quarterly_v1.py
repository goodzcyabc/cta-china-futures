"""季度自适应 v1(预注册 docs/adaptive_quarterly_v1_prereg.md,提交 97f525c):M1 主模型 + A1/A2 消融,对照 5 个已有臂。

用法:
  PYTHONPATH=src python3 scripts/adaptive_quarterly_v1.py --mode smoke   # 2022Q1/Q2 + 停止规则检查
  PYTHONPATH=src python3 scripts/adaptive_quarterly_v1.py --mode full
输出:results/adaptive_quarterly_v1/、docs/adaptive_quarterly_v1_report.md(表格部分;结论由人按预注册第 8 节判读后追加)。
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

from cta.analysis import adaptive_quarterly as aq  # noqa: E402
from cta.analysis import walkforward as wf  # noqa: E402
from cta.analysis.loo import segment_stats  # noqa: E402
from cta.analysis.stats import paired_summary  # noqa: E402
from cta.backtest.engine import BacktestResult, run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors.base import FactorInputs  # noqa: E402
from cta.factors.evaluate import evaluate_factor  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import (
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    git_sha,
)  # noqa: E402
from cta.signals.core import combine, tsmom  # noqa: E402

RQ = Path("data/ricecta/data")
PREV = Path("results/quarterly_walkforward")
HIST = pd.Timestamp("2016-01-04")
RUN_START = pd.Timestamp("2020-01-02")
OOS_START, OOS_END = pd.Timestamp("2022-01-04"), pd.Timestamp("2026-06-05")
SEED, N_BOOT, BLOCK, LAGS = 20260925, 2000, 10, 5
ARMS_PREV = {
    "静态v0.3": "equity_B_S3.csv",
    "固定v0.1": "equity_A_S.csv",
    "A_Q季度选择": "equity_A_Q.csv",
    "A_Y年度选择": "equity_A_Y.csv",
    "C3门控": "equity_B_C3.csv",
}
QREC_PREV = {
    "静态v0.3": "expB_quarters_S3.csv",
    "固定v0.1": "expA_quarters_S.csv",
    "A_Q季度选择": "expA_quarters_Q.csv",
    "A_Y年度选择": "expA_quarters_Y.csv",
    "C3门控": "expB_quarters_C3.csv",
}


def engine_run(target: pd.DataFrame, panels: dict[str, Any], specs: Any, cfg: Any) -> BacktestResult:
    return run_backtest(
        panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )


def annual_cost(rec: pd.DataFrame) -> float:
    """OOS 段年化成本(手续费 + 价内滑点,元/年)。"""
    o = rec[rec["formal_oos"]] if "formal_oos" in rec.columns else rec
    days = float(o["n_days"].sum()) if "n_days" in o.columns else float(len(o) * 61)
    return float((o["fees"].sum() + o["slippage_in_price"].sum()) / max(days / 243.0, 1e-9))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    ap.add_argument("--out", default="results/adaptive_quarterly_v1")
    ap.add_argument("--doc", default="docs/adaptive_quarterly_v1_report.md")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs = load_instruments()
    cfg = load_config(Path("configs/strategy_v03.yaml"))
    src = default_stitched(RQ, official_settle=True)
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    x = FactorInputs.from_panels(panels, cfg)
    dates = pd.DatetimeIndex(sig.adj_close.index)
    parts = {"tsmom": sig.tsmom, "carry": sig.carry, "receipts_level": sig.receipts_level}
    last = pd.Timestamp(dates.max())
    sleeves = {k: evaluate_factor(k, s, x, specs, cfg, HIST, last) for k, s in parts.items()}
    rets = pd.DataFrame({k: v.net for k, v in sleeves.items()})  # 因果的 sleeve 净日收益;训练时只切 ≤ cutoff
    quarters = wf.quarter_schedule(dates, "2020Q1", "2026Q2", end_clip=OOS_END, oos_start=OOS_START)
    rets.to_csv(out / "sleeve_returns.csv")  # 三个 sleeve 的净日收益(评估器口径),供根因分析复算
    log: dict[str, Any] = {
        "git_sha": git_sha(),
        "prereg_commit": "97f525c",
        "mode": args.mode,
        "n_quarters": len(quarters),
    }

    # ---------- 静态 v0.3 重算:等权走同一条 拼接 → 目标暴露 → 引擎 路径,须与已有臂逐位一致(两种模式都做) ----------
    eq_w = {f: 1 / 3 for f in aq.FACTORS}
    comb_eq = combine(parts, eq_w)
    # (a) 权重 1/3 与生产配置的 1.0 合成同一信号:全历史(缓冲状态自 2016 起)目标暴露与生产逐位相同
    tgt_full = wf.targets_from_comb(comb_eq, sig.eligible, sig.vol, sig.adj_close, cfg, HIST, last)
    assert np.allclose(
        tgt_full.to_numpy(dtype=float),
        sig.target.loc[tgt_full.index, tgt_full.columns].to_numpy(dtype=float),
        equal_nan=True,
    )
    # (b) 逐季拼接不改变信号;(c) 自 2020-01-02 空仓起步的同一路径与已有静态臂逐位相同
    st = wf.stitch_quarters([(q, comb_eq) for q in quarters], dates)
    assert np.allclose(
        st.to_numpy(dtype=float), comb_eq.loc[st.index, st.columns].to_numpy(dtype=float), equal_nan=True
    )
    tgt = wf.targets_from_comb(
        st, sig.eligible, sig.vol, sig.adj_close, cfg, quarters[0].start, quarters[-1].end
    )
    res_eq = engine_run(tgt, panels, specs, cfg)
    ref = pd.read_csv(PREV / "equity_B_S3.csv", index_col=0, parse_dates=True).iloc[:, 0]
    same = bool(
        np.allclose(
            res_eq.equity.to_numpy(dtype=float), ref.reindex(res_eq.equity.index).to_numpy(dtype=float)
        )
    )
    print(f"停止规则 ①:等权 ≡ 静态 v0.3(目标暴露逐位相同、权益与已有臂逐位相同)= {same}", flush=True)
    log["baseline_reproduced"] = same
    if not same:
        print("STOP: 静态基线无法复现", file=sys.stderr)
        return 2

    # ---------- 停止规则检查(smoke:2022Q1/Q2 截断面板重算权重) ----------
    if args.mode == "smoke":
        quarters = [q for q in quarters if q.quarter in ("2022Q1", "2022Q2")]
        for q in quarters:
            trunc = build_panels(src, cfg, specs, end=q.cutoff)
            assert all(pd.Timestamp(p.frame.index.max()) == q.cutoff for p in trunc.values())
            sig_t = compute_signals(
                trunc, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
            )
            x_t = FactorInputs.from_panels(trunc, cfg)
            rets_t = pd.DataFrame(
                {
                    k: evaluate_factor(k, s, x_t, specs, cfg, HIST, q.cutoff).net
                    for k, s in {
                        "tsmom": sig_t.tsmom,
                        "carry": sig_t.carry,
                        "receipts_level": sig_t.receipts_level,
                    }.items()
                }
            )
            ok = True
            for m in aq.METHODS:
                a, b = aq.vintage_weights(rets, q.cutoff, m), aq.vintage_weights(rets_t, q.cutoff, m)
                ok &= all(abs(a.w_final[f] - b.w_final[f]) < 1e-9 for f in aq.FACTORS)
            rec_min = pd.DatetimeIndex(src.receipts().index).min()
            print(
                f"停止规则 ②③ {q.quarter} cutoff {q.cutoff.date()}:截断面板重算权重不变(M1/A1/A2)= {ok};仓单最早 {rec_min.date()}",
                flush=True,
            )
            log.setdefault("truncation_checks", []).append({"quarter": q.quarter, "ok": bool(ok)})
            if not ok:
                print("STOP: 截断后权重改变(前视)", file=sys.stderr)
                return 3

    # ---------- 三个新模型 ----------
    static_eq = pd.read_csv(PREV / "equity_B_S3.csv", index_col=0, parse_dates=True).iloc[:, 0]
    static_rec = pd.read_csv(PREV / QREC_PREV["静态v0.3"], index_col=0)
    static_sym = pd.read_csv(PREV / "expB_symbol_contrib_S3.csv", index_col=0)
    results: dict[str, BacktestResult] = {}
    wtabs: dict[str, pd.DataFrame] = {}
    quarter_recs: dict[str, pd.DataFrame] = {}
    for m in aq.METHODS:
        rows, pieces = [], []
        prev: dict[str, float] | None = None
        for q in quarters:
            rec = aq.vintage_weights(rets, q.cutoff, m)
            aq.check_weights(rec.w_final)
            row = aq.record_row(rec, prev)
            row["quarter"], row["trade_start"], row["trade_end"], row["formal_oos"] = (
                q.quarter,
                q.start,
                q.end,
                q.formal_oos,
            )
            # 下一季 sleeve 净收益(评估器口径)与权重方向一致性
            nxt = {
                f: float(rets[f][(rets.index >= q.start) & (rets.index <= q.end)].sum()) for f in aq.FACTORS
            }
            for f in aq.FACTORS:
                row[f"next_sleeve_{f}"] = nxt[f]
                row[f"contrib_{f}"] = rec.w_final[f] * nxt[f]
            row["dir_agree"] = int(
                sum(
                    1
                    for f in aq.FACTORS
                    if np.sign(rec.w_final[f] - 1 / 3) == np.sign(nxt[f] - np.mean(list(nxt.values())))
                    and abs(rec.w_final[f] - 1 / 3) > 1e-9
                )
            )
            row["rank_corr_w_next"] = float(
                pd.Series([rec.w_final[f] for f in aq.FACTORS]).corr(
                    pd.Series([nxt[f] for f in aq.FACTORS]), method="spearman"
                )
            )
            rows.append(row)
            pieces.append((q, combine(parts, rec.w_final)))
            prev = rec.w_final
        wt = pd.DataFrame(rows).set_index("quarter")
        wtabs[m] = wt
        st = wf.stitch_quarters(pieces, dates)
        wf.assert_frozen(st, pieces)
        tgt = wf.targets_from_comb(
            st, sig.eligible, sig.vol, sig.adj_close, cfg, quarters[0].start, quarters[-1].end
        )
        res = engine_run(tgt, panels, specs, cfg)
        results[m] = res
        res.equity.to_csv(out / f"equity_{m}.csv")
        wt.to_csv(out / f"weights_{m}.csv")
        qr = wf.quarter_engine_records(res, specs, quarters)
        quarter_recs[m] = qr
        qr.to_csv(out / f"quarters_{m}.csv")
        sym = wf.quarter_symbol_contrib(res, specs, quarters)
        sym.to_csv(out / f"symbol_contrib_{m}.csv")
        wf.sector_contrib(sym, specs).to_csv(out / f"sector_contrib_{m}.csv")
        wf.paired_by_quarter(res.equity, static_eq, quarters).to_csv(out / f"paired_{m}_vs_static.csv")
        tail = []
        for q in quarters[-4:]:
            ws = "/".join(f"{wt.loc[q.quarter, 'w_' + f]:.2f}" for f in aq.FACTORS)
            tail.append(f"{q.quarter}:{ws}")
        print(f"{m}: 权重序列 " + " | ".join(tail), flush=True)

    # ---------- 汇总与判读 ----------
    if args.mode == "full":
        summary_rows: list[dict[str, Any]] = []
        prev_eq = {
            k: pd.read_csv(PREV / v, index_col=0, parse_dates=True).iloc[:, 0] for k, v in ARMS_PREV.items()
        }
        prev_rec = {k: pd.read_csv(PREV / v, index_col=0) for k, v in QREC_PREV.items()}
        base_oos = segment_stats(static_eq, OOS_START, OOS_END)
        base_cost = annual_cost(static_rec)
        oos_q = [q for q in quarters if q.formal_oos]
        for name, eq in list(prev_eq.items()) + [(f"新·{m}", results[m].equity) for m in aq.METHODS]:
            o = segment_stats(eq, OOS_START, OOS_END)
            rec = prev_rec[name] if name in prev_rec else quarter_recs[name[2:]]
            row: dict[str, Any] = {
                "arm": name,
                "OOS年化": o["年化收益"],
                "OOS夏普(月)": o["夏普(月频)"],
                "OOS回撤": o["最大回撤"],
                "OOS年化成本(元)": annual_cost(rec),
            }
            if name != "静态v0.3":
                ps = paired_summary(
                    static_eq, eq, lags=LAGS, block=BLOCK, n_boot=N_BOOT, seed=SEED, start=OOS_START
                )
                pq = wf.paired_by_quarter(eq, static_eq, oos_q)
                row.update(
                    {
                        "配对差年化": ps["ann_mean"],
                        "NW_SE年化": ps["nw_se_ann"],
                        "t": ps["t"],
                        "boot95低": ps["boot_ci_low_ann"],
                        "boot95高": ps["boot_ci_high_ann"],
                        "季度胜率": float(pq["dyn_wins"].mean()),
                        "胜出季数": int(pq["dyn_wins"].sum()),
                    }
                )
            summary_rows.append(row)
        summ = pd.DataFrame(summary_rows).set_index("arm")
        summ.to_csv(out / "summary.csv")
        # 预注册第 8 节八条判读(对三个新模型)
        crit_rows = []
        for m in aq.METHODS:
            eq = results[m].equity
            o = segment_stats(eq, OOS_START, OOS_END)
            ps = paired_summary(
                static_eq, eq, lags=LAGS, block=BLOCK, n_boot=N_BOOT, seed=SEED, start=OOS_START
            )
            pq = wf.paired_by_quarter(eq, static_eq, oos_q)
            wt = wtabs[m]
            wo = wt[wt["formal_oos"]]
            # ⑥ 单季占比;⑦ 去掉前三品种后配对差
            oos_names = [q.quarter for q in oos_q]
            diff_q = quarter_recs[m].loc[oos_names, "net_pnl"].astype(float) - static_rec.loc[
                oos_names, "net_pnl"
            ].astype(float)  # 逐季净盈亏差(元)
            total = float(diff_q.sum())
            top_share = float(diff_q.max() / total) if total > 0 else float("nan")
            sym_m = pd.read_csv(out / f"symbol_contrib_{m}.csv", index_col=0)
            sd = (
                sym_m.loc[[q.quarter for q in oos_q]]
                - static_sym.loc[[q.quarter for q in oos_q]].reindex(columns=sym_m.columns).fillna(0.0)
            ).sum()
            top3 = sd.sort_values(ascending=False).index[:3].tolist()
            ex_top3 = float(sd.drop(top3).sum())
            c = {
                "model": m,
                "①夏普≥基线+0.20": bool(o["夏普(月频)"] >= base_oos["夏普(月频)"] + 0.20),
                "②bootstrap区间不含0": bool(ps["boot_ci_low_ann"] > 0 or ps["boot_ci_high_ann"] < 0),
                "③≥11/18季跑赢": bool(int(pq["dyn_wins"].sum()) >= 11),
                "④回撤不恶化>3pp": bool(o["最大回撤"] >= base_oos["最大回撤"] - 0.03),
                "⑤年化成本≤基线125%": bool(annual_cost(quarter_recs[m]) <= 1.25 * base_cost),
                "⑥单季占改善≤50%": bool(np.isfinite(top_share) and top_share <= 0.5) if total > 0 else False,
                "⑦去前三品种仍>0": bool(ex_top3 > 0),
                "⑧撞界≤50%且L1中位≤0.3": bool(
                    float(wo["at_bound"].mean()) <= 0.5 and float(wo["l1_change"].median()) <= 0.3
                ),
                "OOS夏普": o["夏普(月频)"],
                "基线夏普": base_oos["夏普(月频)"],
                "配对差年化": ps["ann_mean"],
                "boot95": f"[{ps['boot_ci_low_ann']:+.2%}, {ps['boot_ci_high_ann']:+.2%}]",
                "胜出季数": int(pq["dyn_wins"].sum()),
                "回撤": o["最大回撤"],
                "基线回撤": base_oos["最大回撤"],
                "年化成本": annual_cost(quarter_recs[m]),
                "基线年化成本": base_cost,
                "单季最大占比": top_share,
                "净盈亏差合计(元)": total,
                "单季最大净盈亏差(元)": float(diff_q.max()),
                "单季最大净盈亏差季度": str(diff_q.idxmax()),
                "前三品种": ",".join(top3),
                "去前三配对差(元)": ex_top3,
                "撞界季度占比": float(wo["at_bound"].mean()),
                "L1变化中位": float(wo["l1_change"].median()),
                "L1变化最大": float(wo["l1_change"].max()),
                "carry首次<0.25": (wt.index[(wt["w_carry"] < aq.CARRY_DOWN)].tolist() or [None])[0],
                "carry最低权重": float(wt["w_carry"].min()),
                "HHI均值": float(wo["hhi"].mean()),
                "方向一致(均值/季,满分3)": float(wo["dir_agree"].mean()),
                "权重-下一季收益秩相关均值": float(wo["rank_corr_w_next"].mean()),
            }
            c["存在改善证据"] = all(
                c[k]
                for k in (
                    "①夏普≥基线+0.20",
                    "②bootstrap区间不含0",
                    "③≥11/18季跑赢",
                    "④回撤不恶化>3pp",
                    "⑤年化成本≤基线125%",
                    "⑥单季占改善≤50%",
                    "⑦去前三品种仍>0",
                    "⑧撞界≤50%且L1中位≤0.3",
                )
            )
            crit_rows.append(c)
        crit = pd.DataFrame(crit_rows).set_index("model")
        crit.to_csv(out / "criteria.csv")
        # 根因辅助:tsmom 快/慢 sleeve、receipts 独立性、仓位差异、carry 何时不可用
        fast = tsmom(x.adj_close, (21, 63), vol=x.vol)
        slow = tsmom(x.adj_close, (126, 252), vol=x.vol)
        speed = {}
        for nm, sg in (
            ("tsmom_fast_21_63", fast),
            ("tsmom_slow_126_252", slow),
            ("tsmom_all", parts["tsmom"]),
        ):
            r = evaluate_factor(nm, sg, x, specs, cfg, HIST, last).net
            speed[nm] = {
                "IS_2016_21_ann": float(
                    r[(r.index >= HIST) & (r.index <= pd.Timestamp("2021-12-31"))].mean() * 243
                ),
                "OOS_ann": float(r[(r.index >= OOS_START) & (r.index <= OOS_END)].mean() * 243),
                "IS_sharpe_d": float(
                    r[(r.index <= pd.Timestamp("2021-12-31"))].mean()
                    / r[(r.index <= pd.Timestamp("2021-12-31"))].std()
                    * np.sqrt(243)
                ),
                "OOS_sharpe_d": float(
                    r[(r.index >= OOS_START) & (r.index <= OOS_END)].mean()
                    / r[(r.index >= OOS_START) & (r.index <= OOS_END)].std()
                    * np.sqrt(243)
                ),
            }
        pd.DataFrame(speed).T.to_csv(out / "tsmom_speed.csv")
        r_oos = rets[(rets.index >= OOS_START) & (rets.index <= OOS_END)]
        r_is = rets[(rets.index >= HIST) & (rets.index <= pd.Timestamp("2021-12-31"))]
        indep = {
            "corr_OOS": r_oos.corr().round(3).to_dict(),
            "corr_IS": r_is.corr().round(3).to_dict(),
            "sleeve_ann_OOS": (r_oos.mean() * 243).round(4).to_dict(),
            "sleeve_ann_IS": (r_is.mean() * 243).round(4).to_dict(),
            "sleeve_sharpe_OOS": (r_oos.mean() / r_oos.std() * np.sqrt(243)).round(3).to_dict(),
            "sleeve_sharpe_IS": (r_is.mean() / r_is.std() * np.sqrt(243)).round(3).to_dict(),
        }
        yr_sh = {
            f: (
                rets[f]
                .groupby(rets.index.year)
                .apply(lambda s: float(s.mean() / s.std() * np.sqrt(243)) if s.std() > 0 else np.nan)
            )
            .round(2)
            .to_dict()
            for f in aq.FACTORS
        }
        # carry 何时不可用:EWMA(h=1y)夏普按季度末的轨迹;首次 ≤ 0 的 cutoff
        carry_track = {q.quarter: aq.ewma_stats(rets, q.cutoff)[2]["carry"] for q in quarters}
        first_neg = next((k for k, v in carry_track.items() if v <= 0), None)
        # 仓位差异:M1 vs 静态(同一引擎的 positions)
        pos_static = res_eq.positions  # 本次重算的静态 v0.3 仓位(与已有臂逐位一致)
        pos_diff = {}
        for m in aq.METHODS:
            pm = results[m].positions
            common = pm.index.intersection(pos_static.index)
            common = common[(common >= OOS_START) & (common <= OOS_END)]
            a = pm.loc[common].fillna(0.0)
            b = pos_static.loc[common, a.columns].fillna(0.0)
            pos_diff[m] = float(
                np.abs(a.to_numpy() - b.to_numpy()).sum() / max(np.abs(b.to_numpy()).sum(), 1e-9)
            )
        log.update(
            {
                "elapsed_s": round(time.time() - t0, 1),
                "seed": SEED,
                "n_boot": N_BOOT,
                "block": BLOCK,
                "lags": LAGS,
                "independence": indep,
                "yearly_sleeve_sharpe": yr_sh,
                "carry_ewma_sharpe_track": carry_track,
                "carry_ewma_first_nonpositive": first_neg,
                "position_l1_diff_vs_static_OOS": pos_diff,
            }
        )
        write_doc(
            Path(args.doc), log, summ, crit, wtabs, quarter_recs, speed, indep, yr_sh, carry_track, quarters
        )
        print(summ.round(4).to_string())
        print(
            crit[
                [c for c in crit.columns if c.startswith(("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "存在"))]
            ].to_string()
        )
    (out / "run.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"-> {out} / {args.doc} ({round(time.time() - t0, 1)} s)")
    return 0


def _pct(v: Any) -> str:
    return f"{float(v):+.2%}" if v is not None and np.isfinite(float(v)) else "n/a"


def write_doc(
    path: Path,
    log: dict[str, Any],
    summ: pd.DataFrame,
    crit: pd.DataFrame,
    wtabs: dict[str, pd.DataFrame],
    qrecs: dict[str, pd.DataFrame],
    speed: dict[str, dict[str, float]],
    indep: dict[str, Any],
    yr_sh: dict[str, dict[int, float]],
    carry_track: dict[str, float],
    quarters: list[wf.QuarterSpec],
) -> None:
    lines: list[str] = [
        "# 季度自适应 v1:结果(后验提出的历史 walk-forward 诊断;预注册 `docs/adaptive_quarterly_v1_prereg.md`,提交 97f525c)",
        "",
        "> 第 0 节(结论先行)与第 5–8 节由人撰写、保留在 HTML 标记之间;第 1–4 节表格由脚本生成,重跑只刷新表格;预注册第 1–12 节未改。",
        "",
        f"git `{log['git_sha']}`;季度模型 {len(quarters)} 个({sum(q.formal_oos for q in quarters)} 个在正式 OOS);引擎自 2020-01-02 空仓连续运行到 2026-06-05;同一数据、引擎、成本、初始资金。",
        "",
        "## 1. 八臂汇总(主指标 2022-01-04 → 2026-06-05;配对差相对静态 v0.3,NW lag 5,块 bootstrap 10 × 2000,种子 20260925)",
        "",
        "| 臂 | OOS 年化 | OOS 夏普(月) | OOS 回撤 | 年化成本(万元) | 配对差年化 | NW SE | t | bootstrap 95% | 胜出季/18 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, r in summ.iterrows():
        has = pd.notna(r.get("配对差年化", np.nan))
        ci = f"[{_pct(r['boot95低'])}, {_pct(r['boot95高'])}]" if has else "—"
        pd_s = _pct(r["配对差年化"]) if has else "—"
        se_s = _pct(r["NW_SE年化"]) if has else "—"
        t_s = f"{float(r['t']):.2f}" if has else "—"
        win_s = str(int(r["胜出季数"])) if has else "—"
        cost_s = f"{float(r['OOS年化成本(元)']) / 1e4:.1f}"
        sh_s = f"{float(r['OOS夏普(月)']):.2f}"
        lines.append(
            f"| {arm} | {_pct(r['OOS年化'])} | {sh_s} | {_pct(r['OOS回撤'])} | {cost_s} | {pd_s} | {se_s} | {t_s} | {ci} | {win_s} |"
        )
    lines += [
        "",
        "## 2. 预注册第 8 节判读(三个新模型)",
        "",
        crit.T.map(lambda v: round(v, 4) if isinstance(v, float) else v).to_markdown(),
        "",
    ]
    for m, wt in wtabs.items():
        cols = (
            ["cutoff", "n_eff"]
            + [f"sharpe_{f}" for f in aq.FACTORS]
            + [f"w_{f}" for f in aq.FACTORS]
            + ["l1_change", "hhi", "at_bound", "dir_agree"]
        )
        lines += [
            f"## 3.{m} 逐 vintage 权重(EWMA/滚动统计、原始→收缩→冻结见 CSV)",
            "",
            wt[cols].round(3).to_markdown(),
            "",
        ]
        lines += [
            f"### {m} 逐季引擎口径",
            "",
            qrecs[m][
                [
                    "ret",
                    "gross_pnl",
                    "fees",
                    "slippage_in_price",
                    "net_pnl",
                    "turnover_notional",
                    "mdd_in_quarter",
                ]
            ]
            .round(4)
            .to_markdown(),
            "",
        ]
    lines += [
        "## 4. 根因辅助",
        "",
        "### 4.1 趋势快/慢 sleeve(评估器口径)",
        "",
        pd.DataFrame(speed).T.round(4).to_markdown(),
        "",
        "### 4.2 三个 sleeve 的 IS/OOS 年化、夏普与相关",
        "",
        f"IS 年化 {indep['sleeve_ann_IS']};OOS 年化 {indep['sleeve_ann_OOS']}",
        "",
        f"IS 夏普 {indep['sleeve_sharpe_IS']};OOS 夏普 {indep['sleeve_sharpe_OOS']}",
        "",
        f"IS 相关 {indep['corr_IS']}",
        "",
        f"OOS 相关 {indep['corr_OOS']}",
        "",
        "### 4.3 逐年 sleeve 夏普",
        "",
        pd.DataFrame(yr_sh).round(2).to_markdown(),
        "",
        "### 4.4 carry 的 EWMA(h=1 年)夏普按季度 cutoff 的轨迹",
        "",
        pd.Series(carry_track).round(2).to_frame("carry_ewma_sharpe").T.to_markdown(),
        "",
        f"首次 ≤ 0 的 cutoff:{log.get('carry_ewma_first_nonpositive')};OOS 内 M1/A1/A2 相对静态的仓位 L1 差异:{log.get('position_l1_diff_vs_static_OOS')}",
        "",
    ]
    # 保留人工撰写的结论块(位于标记之间),重跑只刷新表格
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
