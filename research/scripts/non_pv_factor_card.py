"""非量价因子说明书的数字(描述性报告,不计试验,不据此改动任何配置)。

站在"已有量价因子"的视角评估生产中的非量价因子 receipts_level(仓单水平,v0.3 的第三个因子):
- 量价基线 = v0.1(时序动量 + 展期收益,configs/strategy.yaml),与正式 D 臂逐位一致;
- 候选 = v0.3 流水线算出的 receipts_level 信号(与生产完全相同);
- 三臂:仓单单独 / 量价基线 / 50-50 事前风险预算混合(cta_research.evaluation.candidate_eval,同一引擎、成本、执行);
- 另附因子评估器口径的 sleeve 相关性(results/adaptive_quarterly_v1/sleeve_returns.csv)与逐品种覆盖。
用法:python research/scripts/non_pv_factor_card.py
输出:results/non_pv_factor_card/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/(cta_research)

from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.pipeline import _receipts_of, _reg_events_of, compute_signals  # noqa: E402
from cta_research.evaluation import candidate_eval as ce  # noqa: E402

OUT = Path("results/non_pv_factor_card")
SEED = 20261005
IS_END, OOS_START, END = pd.Timestamp("2021-12-31"), pd.Timestamp("2022-01-04"), pd.Timestamp("2026-06-05")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = ce.build_context(
        config_path="configs/strategy.yaml",
        reference_equity="results/settle_baseline/equity_v0.1_full_D_unified_official.csv",
        seed=SEED,
    )
    print(f"量价基线 v0.1 与正式 D 臂逐位一致 = {ctx.baseline_matches_reference}", flush=True)
    cfg3 = load_config(Path("configs/strategy_v03.yaml"))
    src = default_stitched(Path("data/ricecta/data"), official_settle=True)
    sig3 = compute_signals(
        ctx.panels, cfg3, receipts=_receipts_of(src), specs=ctx.specs, reg_events=_reg_events_of(src, cfg3)
    )
    rl = sig3.receipts_level
    assert rl is not None
    cols = list(ctx.sig.adj_close.columns)
    signal = rl.reindex(index=ctx.sig.adj_close.index, columns=cols)
    # 点时:仓单为 T 日收盘后公布的 T 日数据,与结算价同批;信号在 T 日数据公布后生成,T+1 开盘(夜盘品种为 T 日 21:00)成交
    d = pd.DatetimeIndex(signal.index)
    d = d[(d >= ctx.start) & (d <= ctx.end)]
    exec_days = list(d[1:]) + [pd.NaT]
    audit = pd.DataFrame(
        {"data_date": d, "info_date": d, "available_day": d, "target_day": d, "exec_day": exec_days}
    )
    cand = ce.Candidate("R", "仓单水平 receipts_level(生产 v0.3 的非量价因子)", signal, audit)
    ev = ce.evaluate(ctx, cand)
    ce.write_eval(OUT, ev)
    s = ev.summary
    print(
        s[
            [
                "arm",
                "period",
                "年化收益",
                "夏普(月频)",
                "月频NW t",
                "最大回撤",
                "年化名义换手",
                "年化手续费占权益",
                "年化滑点占权益",
            ]
        ]
        .round(3)
        .to_string(),
        flush=True,
    )
    for arm, p in ev.paired.items():
        for per in ("since_active", "oos"):
            x = p[per]
            print(
                f"{arm} {per}: 配对差 {x['ann_mean']:+.2%} t {x['t']:.2f} CI [{x['boot_ci_low_ann']:+.2%}, {x['boot_ci_high_ann']:+.2%}] | 日相关 {p['corr_daily_with_baseline']:.3f} 月相关 {p['corr_monthly_with_baseline']:.3f}",
                flush=True,
            )
    # sleeve 口径(因子评估器,已存于季度自适应 v1 结果)
    sleeve: dict[str, Any] = {}
    sp = Path("results/adaptive_quarterly_v1/sleeve_returns.csv")
    if sp.exists():
        r = pd.read_csv(sp, index_col=0, parse_dates=True).dropna()
        for name, mask in (
            ("IS_2016_2021", r.index <= IS_END),
            ("OOS_2022_2026", (r.index >= OOS_START) & (r.index <= END)),
        ):
            x = r[mask]
            sleeve[name] = {
                "sharpe_daily_ann": (x.mean() / x.std() * np.sqrt(243)).round(3).to_dict(),
                "ann_return": (x.mean() * 243).round(4).to_dict(),
                "corr": x.corr().round(3).to_dict(),
            }
        yr = r.groupby(r.index.year).apply(lambda g: (g.mean() / g.std() * np.sqrt(243)).round(2))
        sleeve["yearly_sharpe"] = {str(k): v for k, v in yr.to_dict(orient="index").items()}
    # 覆盖:每个品种有仓单信号的交易日占比(IS / OOS)
    cov = {}
    for name, a, b in (("IS", ctx.start, IS_END), ("OOS", OOS_START, END)):
        seg = signal[(signal.index >= a) & (signal.index <= b)]
        cov[name] = seg.notna().mean().round(3).to_dict()
    payload = {
        "baseline": "v0.1 (tsmom + carry), configs/strategy.yaml",
        "baseline_matches_reference_D": ctx.baseline_matches_reference,
        "verdict_by_R_rules": ev.verdict,
        "checks": ev.checks,
        "first_active": str(ev.first_active.date()),
        "summary": s.to_dict(orient="records"),
        "paired": ev.paired,
        "sleeve": sleeve,
        "coverage": cov,
        "contrib_symbol_full": ev.contrib["R_standalone"]["symbol_table"]["net_FULL"].round(0).to_dict(),
        "contrib_year": ev.contrib["R_standalone"]["year"].round(0).to_dict(),
        "sector": ev.contrib["R_standalone"]["sector_table"].round(0).to_dict(),
    }
    (OUT / "card.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: payload[k] for k in ("verdict_by_R_rules", "first_active", "coverage", "contrib_year")},
            ensure_ascii=False,
            default=str,
        )[:3000]
    )
    print(json.dumps(sleeve, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
