"""组合诊断(只读):逐品种净归因、收益广度与集中度、IS→OOS 符号迁移、板块汇总、滚动广度、leave-one-out 敏感性。

正式基线:configs/strategy_v03.yaml + 当前统一执行引擎 + 交易所官方结算价 + 300 万;
主口径 = 2016-01-04 起连续运行到 2026-09-18,再切 IS(→2021-12-31)/ OOS(2022-01-04 → 2026-06-05)/ FULL;
另跑一遍"OOS 空仓独立起跑"只作敏感性,单独标注,不与主口径混用。
逐品种净贡献 = pnl_by_symbol(盯市 + 已实现,滑点已在成交价内)− 该品种逐笔手续费;不再扣滑点。
任一区间 Σ净贡献 ≠ 权益变化(超出浮点误差)→ 直接失败,不生成报告。

用法:PYTHONPATH=src python3 scripts/portfolio_diagnostics.py [--config configs/strategy_v03.yaml] [--skip-loo] [--no-oos-flat]
输出:results/portfolio_diagnostics/*.csv 与 docs/portfolio_diagnostics.md(只写这两处)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.analysis import attribution as attr  # noqa: E402
from cta.analysis.loo import leave_one_out, segment_stats  # noqa: E402
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals, git_sha  # noqa: E402

RQ = Path("data/ricecta/data")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/strategy_v03.yaml")
    ap.add_argument("--out", default="results/portfolio_diagnostics")
    ap.add_argument("--doc", default="docs/portfolio_diagnostics.md")
    ap.add_argument("--full-start", default="2016-01-04")
    ap.add_argument("--full-end", default="2026-09-18")
    ap.add_argument("--is-end", default="2021-12-31")
    ap.add_argument("--oos-start", default="2022-01-04")
    ap.add_argument("--oos-end", default="2026-06-05")
    ap.add_argument("--skip-loo", action="store_true")
    ap.add_argument("--no-oos-flat", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    out = Path(args.out)
    cfg = load_config(Path(args.config))
    specs = load_instruments()
    src = default_stitched(RQ, official_settle=(cfg.data.settle == "official"))
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    full = attr.Period("FULL", pd.Timestamp(args.full_start), pd.Timestamp(args.full_end))
    is_ = attr.Period("IS", pd.Timestamp(args.full_start), pd.Timestamp(args.is_end))
    oos = attr.Period("OOS", pd.Timestamp(args.oos_start), pd.Timestamp(args.oos_end))
    periods = [is_, oos, full]
    idx = sig.target.index
    target = sig.target.loc[(idx >= full.start) & (idx <= full.end)]
    cap = cfg.backtest.initial_capital_cny
    kw: dict[str, Any] = dict(
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    res = run_backtest(panels, target, specs, cap, **kw)
    recs = attr.assert_reconciled(res, specs, periods, cap)  # 不能对账 → 抛 ReconciliationError,不生成报告
    table = attr.per_symbol_table(res, specs, periods, cap)
    breadth = attr.breadth_table(table, periods)
    trans = attr.sign_transitions(table, "IS", "OOS")
    sector = attr.sector_contribution(table, periods)
    conc = attr.concentration(table, periods)
    roll = attr.rolling_breadth(res, specs)
    neg = attr.negative_lists(table)
    seg = {p.name: segment_stats(res.equity, p.start, p.end) for p in periods}
    # OOS 空仓独立起跑(敏感性,单独标注)
    flat_table: pd.DataFrame | None = None
    flat_rec: attr.Reconciliation | None = None
    if not args.no_oos_flat:
        tf = sig.target.loc[(idx >= oos.start) & (idx <= oos.end)]
        res_flat = run_backtest(panels, tf, specs, cap, **kw)
        flat_p = attr.Period("OOS_FLAT", oos.start, oos.end)
        flat_rec = attr.assert_reconciled(res_flat, specs, [flat_p], cap)[0]
        flat_table = attr.per_symbol_table(res_flat, specs, [flat_p], cap)
        seg["OOS_FLAT"] = segment_stats(res_flat.equity, oos.start, oos.end)
    loo: pd.DataFrame | None = None
    if not args.skip_loo:
        loo = leave_one_out(panels, target, specs, cap, list(target.columns), full, oos, kw, baseline=res)
    # ---- 输出 ----
    out.mkdir(parents=True, exist_ok=True)
    t_out = table.copy()
    if flat_table is not None:
        t_out = t_out.join(flat_table[[c for c in flat_table.columns if c.endswith("OOS_FLAT")]])
    t_out.to_csv(out / "per_symbol_net.csv")
    trans.to_csv(out / "sign_transitions.csv", index=False)
    sector.to_csv(out / "sector_contribution.csv")
    conc.to_csv(out / "concentration.csv", index=False)
    roll.to_csv(out / "rolling_breadth.csv", index=False)
    breadth.to_csv(out / "breadth.csv")
    if loo is not None:
        loo.to_csv(out / "leave_one_out.csv")
    meta = {
        "config": args.config,
        "config_digest": cfg.digest(),
        "config_summary": {
            "version": cfg.version,
            "data.settle": cfg.data.settle,
            "universe.symbols": cfg.universe.symbols,
            "signals.weights": cfg.signals.weights,
            "portfolio": cfg.portfolio.model_dump(),
            "execution": cfg.execution.model_dump(),
            "backtest": cfg.backtest.model_dump(),
        },
        "instruments_digest": specs.digest(),
        "instruments_summary": {
            "n_specs": len(specs.specs),
            "n_verified": sum(1 for s in specs.specs.values() if s.verified),
        },
        "git_sha": git_sha(),
        "data_manifest": src.manifest(),
        "periods": {p.name: [str(p.start.date()), str(p.end.date())] for p in periods},
        "reconciliation": [r.__dict__ | {"ok": r.ok} for r in recs]
        + ([flat_rec.__dict__ | {"ok": flat_rec.ok}] if flat_rec else []),
        "segment_stats": seg,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out / "run.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    Path(args.doc).write_text(
        render_doc(meta, table, breadth, trans, sector, conc, roll, neg, loo, flat_table, cap),
        encoding="utf-8",
    )
    print(
        "对账:"
        + "; ".join(
            f"{r.period} Σ净贡献 {r.sum_net:,.2f} vs 权益变化 {r.equity_change:,.2f} 差 {r.diff:.6f} {'OK' if r.ok else 'FAIL'}"
            for r in recs
        )
    )
    print(f"-> {out} / {args.doc}  ({meta['elapsed_s']} s)")
    return 0


def _pct(x: float) -> str:
    return f"{x:+.2%}"


def _cny(x: float) -> str:
    return f"{x / 1e4:+,.1f} 万"


def render_doc(
    meta: dict[str, Any],
    table: pd.DataFrame,
    breadth: pd.DataFrame,
    trans: pd.DataFrame,
    sector: pd.DataFrame,
    conc: pd.DataFrame,
    roll: pd.DataFrame,
    neg: dict[str, list[str]],
    loo: pd.DataFrame | None,
    flat: pd.DataFrame | None,
    cap: float,
) -> str:
    lines: list[str] = []
    lines += [
        "# 组合诊断:逐品种净归因、广度与集中度、leave-one-out(只读诊断,不是选池规则)",
        "",
        f"生成:git `{meta['git_sha']}`;脚本 `scripts/portfolio_diagnostics.py`;耗时 {meta['elapsed_s']} s。",
        "",
        "## 1. 口径",
        "",
        f"- 配置 `{meta['config']}`(摘要 `{meta['config_digest']}`):版本 {meta['config_summary']['version']};结算价口径 {meta['config_summary']['data.settle']};"
        f"品种 {len(meta['config_summary']['universe.symbols'] or [])} 个;因子 {list((meta['config_summary']['signals.weights'] or {}).keys())};"
        f"组合 {meta['config_summary']['portfolio']};执行 {meta['config_summary']['execution']}。",
        f"- 参数表摘要 `{meta['instruments_digest']}`({meta['instruments_summary']['n_specs']} 个品种,{meta['instruments_summary']['n_verified']} 个已核验)。",
        f"- 数据摘要:{meta['data_manifest']}。",
        f"- 区间:{meta['periods']}。**主口径 = 从 {meta['periods']['FULL'][0]} 起连续运行到 {meta['periods']['FULL'][1]},再切 IS/OOS**(持仓跨 2022-01-04 延续,与正式报告一致);"
        "'OOS_FLAT' 列 = 2022-01-04 空仓独立起跑,只作敏感性,不与主口径混用。",
        f"- 初始资金 {cap:,.0f} 元;手续费按核验参数表、逐笔按成交所属品种归属;滑点每边 1 跳已进成交价;引擎 = 当前统一执行引擎(T 收盘定手数、保证金缩减、手数带、两腿换月、官方结算价盯市)。",
        "- 逐品种净贡献 = pnl_by_symbol(盯市 + 已实现)− 该品种手续费;**不再扣滑点**(否则重复)。",
        "",
        "## 2. 对账(Σ品种净贡献 vs 区间权益变化;容差 1 分钱,只允许浮点误差;不通过则本报告不会生成)",
        "",
        "| 区间 | Σ净贡献(元) | 权益变化(元) | 差 | 通过 |",
        "|---|---|---|---|---|",
    ]
    for r in meta["reconciliation"]:
        lines.append(
            f"| {r['period']} | {r['sum_net']:,.2f} | {r['equity_change']:,.2f} | {r['diff']:.6f} | {'是' if r['ok'] else '否'} |"
        )
    lines += [
        "",
        "分段指标(perf_stats 于连续曲线的分段):",
        "",
        "| 区间 | 年化 | 夏普(月) | 最大回撤 |",
        "|---|---|---|---|",
    ]
    for k, v in meta["segment_stats"].items():
        lines.append(f"| {k} | {_pct(v['年化收益'])} | {v['夏普(月频)']:.2f} | {_pct(v['最大回撤'])} |")
    lines += [
        "",
        "## 3. 逐品种净贡献(元 / 占初始资金 %)",
        "",
        "| 品种 | 板块 | IS | OOS | FULL | IS% | OOS% | FULL% | 符号 IS/OOS/FULL |"
        + (" OOS_FLAT |" if flat is not None else ""),
        "|---|---|---|---|---|---|---|---|---|" + ("---|" if flat is not None else ""),
    ]
    for s, r in table.sort_values("net_FULL", ascending=False).iterrows():
        extra = (
            f" {_cny(float(flat.loc[s, 'net_OOS_FLAT']))} |" if flat is not None and s in flat.index else ""
        )
        lines.append(
            f"| {s} | {r['asset_class']} | {_cny(r['net_IS'])} | {_cny(r['net_OOS'])} | {_cny(r['net_FULL'])} | {_pct(r['pct_IS'])} | {_pct(r['pct_OOS'])} | {_pct(r['pct_FULL'])} | {r['sign_IS']}/{r['sign_OOS']}/{r['sign_FULL']} |"
            + extra
        )
    lines += [
        "",
        "## 4. 广度",
        "",
        "| 区间 | 参评品种 | 正 | 负 | 零 | 广度 = 正/参评 |",
        "|---|---|---|---|---|---|",
    ]
    for p, r in breadth.iterrows():
        lines.append(
            f"| {p} | {r['n_active']} | {r['n_pos']} | {r['n_neg']} | {r['n_zero']} | {float(r['breadth']):.1%} |"
        )
    lines += [
        "",
        "IS → OOS 符号迁移(两段都活跃的品种):",
        "",
        "| 从 | 到 | 数量 | 品种 |",
        "|---|---|---|---|",
    ]
    for _, r in trans.iterrows():
        lines.append(f"| {r['from']} | {r['to']} | {r['n']} | {r['symbols'] or '—'} |")
    lines += [
        "",
        "分年度与滚动两年正收益品种比例:",
        "",
        "| 窗口类型 | 窗口 | 参评 | 正 | 负 | 广度 |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in roll.iterrows():
        lines.append(
            f"| {r['window_type']} | {r['window']} | {r['n_active']} | {r['n_pos']} | {r['n_neg']} | {float(r['breadth']):.1%} |"
        )
    lines += [
        "",
        "## 5. 板块净贡献(按 asset_class)",
        "",
        "| 板块 | 品种数 | IS | OOS | FULL | OOS 正/负 |",
        "|---|---|---|---|---|---|",
    ]
    for ac, r in sector.sort_values("net_FULL", ascending=False).iterrows():
        lines.append(
            f"| {ac} | {r['n_symbols']} | {_cny(r['net_IS'])} | {_cny(r['net_OOS'])} | {_cny(r['net_FULL'])} | {r['n_pos_OOS']}/{r['n_neg_OOS']} |"
        )
    lines += [
        "",
        "## 6. 集中度",
        "",
        "定义:**share_of_positive** = 前 k 大正贡献之和 / 全部正贡献之和(分母只含正贡献品种,恒 ≤ 100%,是主口径);"
        "**share_of_total** = 前 k 大正贡献之和 / 组合总净贡献(分母含负贡献品种,因此可能 > 100%;总净贡献 ≤ 0 时不定义,记 n/a)。",
        "",
        "| 区间 | k | 品种 | 前 k 之和 | 正贡献总和 | share_of_positive | 总净贡献 | share_of_total |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in conc.iterrows():
        st = f"{float(r['share_of_total']):.1%}" if pd.notna(r["share_of_total"]) else "n/a"
        lines.append(
            f"| {r['period']} | {r['k']} | {r['symbols']} | {_cny(r['sum_topk'])} | {_cny(r['positive_total'])} | {float(r['share_of_positive']):.1%} | {_cny(r['total_net'])} | {st} |"
        )
    lines += [
        "",
        "## 7. 长期负贡献品种(只列出;**不得据此自动修改品种池**——设计日志十四已证明按历史盈亏剔品种在样本外为负价值)",
        "",
    ]
    for k, v in neg.items():
        lines.append(f"- {k}:{', '.join(v) if v else '(无)'}")
    if loo is not None:
        bf, bo = loo.attrs.get("baseline_full", {}), loo.attrs.get("baseline_oos", {})
        lines += [
            "",
            "## 8. Leave-one-out(逐一把该品种目标暴露置 0、完整重跑引擎;不是「组合 − 该品种贡献」)",
            "",
            f"完整 v0.3:FULL 年化 {_pct(bf.get('年化收益', float('nan')))} / 夏普 {bf.get('夏普(月频)', float('nan')):.2f} / 回撤 {_pct(bf.get('最大回撤', float('nan')))};"
            f"OOS 年化 {_pct(bo.get('年化收益', float('nan')))} / 夏普 {bo.get('夏普(月频)', float('nan')):.2f} / 回撤 {_pct(bo.get('最大回撤', float('nan')))}。",
            "依赖标记(诊断阈值,先写):剔除后 FULL 月频夏普下降 ≥ 0.10,或 OOS 年化下降 ≥ 2 个百分点。注意目标暴露置 0 后不重做信号层的协方差缩放,其余品种不会被放大到 10% 目标波动。",
            "",
            "| 剔除 | FULL 年化 | Δ | FULL 夏普 | Δ | FULL 回撤 | Δ | OOS 年化 | Δ | OOS 夏普 | Δ | OOS 回撤 | Δ | 依赖 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s, r in loo.sort_values("d_full_sharpe_m").iterrows():
            lines.append(
                f"| {s} | {_pct(r['full_cagr'])} | {_pct(r['d_full_cagr'])} | {r['full_sharpe_m']:.2f} | {r['d_full_sharpe_m']:+.2f} | {_pct(r['full_mdd'])} | {_pct(r['d_full_mdd'])} | "
                f"{_pct(r['oos_cagr'])} | {_pct(r['d_oos_cagr'])} | {r['oos_sharpe_m']:.2f} | {r['d_oos_sharpe_m']:+.2f} | {_pct(r['oos_mdd'])} | {_pct(r['d_oos_mdd'])} | {'**是**' if r['dependent'] else '否'} |"
            )
        dep = loo[loo["dependent"]].index.tolist()
        lines += [
            "",
            f"被标记为依赖的品种:{', '.join(dep) if dep else '(无)'} —— 这是敏感性诊断,不产生删除或保留任何品种的建议。",
        ]
    lines += [
        "",
        "## 9. 声明",
        "",
        "- 本文档由只读脚本生成,不修改策略信号、参数、品种池、风险规则或任何账本;不在 2016–2026 历史上选择参数。",
        "- 逐品种表、负贡献清单与 leave-one-out 都是诊断信息;是否调整品种池须另行预注册并只用前向数据检验。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
