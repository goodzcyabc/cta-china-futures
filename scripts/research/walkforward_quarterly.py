"""设计日志十九:实验 45(每季按 4.4 规则重选附加因子)与实验 46(C3:carry 滚动 3 年夏普开关)的历史 walk-forward。

协议见 design_log 19.2–19.4:季度 cutoff = 日历季度最后一个交易日;每季只用上一季度末(含)以前的数据做决定,配置冻结一季;
逐季决定的合成信号按季拼接,再连续做波动率目标缩放 → 总名义上限 → 暴露缓冲 → 引擎从 2020-01-02 空仓连续跑到 2026-09-18。
只作诊断;不据此替换 champion。输出 results/walkforward_quarterly/ 与 docs/walkforward_quarterly.md。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.analysis.loo import segment_stats  # noqa: E402
from cta.backtest.engine import run_backtest  # noqa: E402
from cta.config import StrategyConfig, load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.factors.base import FactorInputs  # noqa: E402
from cta.factors.evaluate import correlation_table, evaluate_factor  # noqa: E402
from cta.factors.library import ALL_FACTORS  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import (  # noqa: E402
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    git_sha,
    summarize_result,
)
from cta.signals.core import cap_gross_exposure, combine, trade_buffer, vol_target_positions  # noqa: E402

RQ = Path("data/ricecta/data")
OUT = Path("results/walkforward_quarterly")
RUN_START, RUN_END = pd.Timestamp("2020-01-02"), pd.Timestamp("2026-09-18")
OOS = (pd.Timestamp("2022-01-04"), pd.Timestamp("2026-06-05"))
HIST_START = pd.Timestamp("2016-01-04")
FIRST_Q, LAST_Q = pd.Period("2020Q1"), pd.Period("2026Q3")


def quarter_cutoffs(dates: pd.DatetimeIndex) -> list[tuple[pd.Period, pd.Timestamp]]:
    """(季度, 该季度开始前的最后一个交易日 = 上一季度末 cutoff)。"""
    out = []
    q = FIRST_Q
    while q <= LAST_Q:
        prev_end = (q - 1).end_time.normalize()
        cut = dates[dates <= prev_end].max()
        out.append((q, pd.Timestamp(cut)))
        q += 1
    return out


def stitched_targets(
    comb_by_q: list[tuple[pd.Period, pd.DataFrame]], x: FactorInputs, cfg: StrategyConfig
) -> pd.DataFrame:
    """按季拼接合成信号,再连续做 波动率目标 → 总名义上限 → 暴露缓冲(与 compute_signals 尾部同一顺序)。"""
    pieces = []
    for q, comb in comb_by_q:
        idx = comb.index
        pieces.append(comb[(idx >= q.start_time.normalize()) & (idx <= q.end_time.normalize())])
    stitched = pd.concat(pieces).sort_index()
    raw = vol_target_positions(
        stitched.where(x.eligible.reindex(stitched.index)),
        x.vol,
        x.adj_close,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    )
    raw = cap_gross_exposure(raw, cfg.portfolio.max_gross_exposure)
    tgt = raw.copy()
    prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        row = tgt.loc[d].fillna(0.0)
        b = trade_buffer(row, prev, cfg.portfolio.exposure_buffer)
        tgt.loc[d] = b
        prev = b
    i = tgt.index
    return tgt[(i >= RUN_START) & (i <= RUN_END)]


def engine_stats(
    target: pd.DataFrame, panels: dict[str, Any], specs: Any, cfg: StrategyConfig
) -> tuple[dict[str, Any], pd.Series[Any]]:
    res = run_backtest(
        panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    st, _ = summarize_result(res, specs)
    oos = segment_stats(res.equity, OOS[0], OOS[1])
    return {
        "年化": st["年化收益"],
        "夏普(月)": st["夏普(月频)"],
        "回撤": st["最大回撤"],
        "换手": st["年化名义换手(倍)"],
        "OOS年化": oos["年化收益"],
        "OOS夏普(月)": oos["夏普(月频)"],
        "OOS回撤": oos["最大回撤"],
    }, res.equity


def main() -> int:
    t0 = time.time()
    specs = load_instruments()
    cfg1 = load_config(Path("configs/strategy.yaml"))
    cfg3 = load_config(Path("configs/strategy_v03.yaml"))
    src = default_stitched(RQ, official_settle=True)
    panels = build_panels(src, cfg3, specs)
    x1 = FactorInputs.from_panels(panels, cfg1)
    dates = pd.DatetimeIndex(x1.adj_close.index)
    cuts = quarter_cutoffs(dates)
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, Any]] = {}
    equities: dict[str, pd.Series[Any]] = {}

    # ---------------- 实验 45 ----------------
    sigs = {f.name: f.compute(x1) for f in ALL_FACTORS}
    cands = [f.name for f in ALL_FACTORS if not f.reference]
    combo_v01 = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"]})
    cache: dict[pd.Timestamp, list[str]] = {}

    def select(end: pd.Timestamp) -> list[str]:  # 6.2 脚本逐字
        if end in cache:
            return cache[end]
        res = {
            k: evaluate_factor(k, sigs[k], x1, specs, cfg1, HIST_START, end)
            for k in [*cands, "tsmom", "carry"]
        }
        res["combo_v01"] = evaluate_factor("combo_v01", combo_v01, x1, specs, cfg1, HIST_START, end)
        corr = correlation_table(res)
        chosen: list[str] = []
        order = sorted(
            cands, key=lambda n: -float(np.nan_to_num(res[n].stats.get("夏普(月频)", np.nan), nan=-9))
        )
        for n in order:
            st, ys = res[n].stats, res[n].yearly_sharpe
            n_years = int(ys.notna().sum())
            ok = (
                st.get("夏普(月频)", -9) >= 0.40
                and st.get("月频NW t", -9) >= 2.0
                and corr.at[n, "combo_v01"] <= 0.60
                and int((ys > 0).sum()) >= max(4 * n_years // 5, 3)
                and all(abs(corr.at[n, c]) <= 0.80 for c in chosen)
            )
            if ok:
                chosen.append(n)
        cache[end] = chosen
        return chosen

    rows45 = []
    comb_q, comb_a, comb_s = [], [], []
    fast45: dict[str, list[pd.Series[Any]]] = {"Q": [], "A": [], "S": []}
    for q, cut in cuts:
        ch_q = select(cut)
        year_cut = pd.Timestamp(dates[dates <= pd.Timestamp(f"{q.year - 1}-12-31")].max())
        ch_a = select(year_cut)
        sig_q = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"], **{c: sigs[c] for c in ch_q}})
        sig_a = combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"], **{c: sigs[c] for c in ch_a}})
        comb_q.append((q, sig_q))
        comb_a.append((q, sig_a))
        comb_s.append((q, combo_v01))
        q0, q1 = q.start_time.normalize(), min(q.end_time.normalize(), RUN_END)
        for arm, sg in (("Q", sig_q), ("A", sig_a), ("S", combo_v01)):
            fast45[arm].append(evaluate_factor(arm, sg, x1, specs, cfg1, q0, q1).net)
        rows45.append(
            {
                "quarter": str(q),
                "cutoff": str(cut.date()),
                "annual_cutoff": str(year_cut.date()),
                "Q_chosen": ",".join(ch_q) or "(无)",
                "A_chosen": ",".join(ch_a) or "(无)",
            }
        )
        print(f"45 {q} cut {cut.date()} Q={ch_q or '-'} A={ch_a or '-'}", flush=True)
    tab45 = pd.DataFrame(rows45)
    tab45.to_csv(OUT / "exp45_quarters.csv", index=False)
    for arm, cb in (("45_Q_季度重选", comb_q), ("45_A_年度重选", comb_a), ("45_S_固定v0.1", comb_s)):
        st, eq = engine_stats(stitched_targets(cb, x1, cfg1), panels, specs, cfg1)
        key = arm[3:4]
        m = pd.concat(fast45[key]).resample("ME").sum()
        st["次指标:快速评估器拼接月夏普"] = float(m.mean() / m.std() * np.sqrt(12)) if m.std() > 0 else np.nan
        summary[arm] = st
        equities[arm] = eq
        eq.to_csv(OUT / f"equity_{arm}.csv")
        print(arm, {k: round(v, 4) for k, v in st.items()}, flush=True)
    changes_q = int((tab45["Q_chosen"] != tab45["Q_chosen"].shift(1)).sum() - 1)
    changes_a = int((tab45["A_chosen"] != tab45["A_chosen"].shift(1)).sum() - 1)

    # ---------------- 实验 46 ----------------
    x3 = FactorInputs.from_panels(panels, cfg3)
    sig3 = compute_signals(
        panels, cfg3, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg3)
    )
    parts = {"tsmom": sig3.tsmom, "carry": sig3.carry, "receipts_level": sig3.receipts_level}
    rows46 = []
    comb_dyn, comb_static = [], []
    w_prev = 1.0
    for q, cut in cuts:
        w0 = cut - pd.DateOffset(years=3) + pd.Timedelta(days=1)
        r = evaluate_factor("carry", sig3.carry, x3, specs, cfg3, w0, cut)
        sh = float(r.stats.get("夏普(月频)", np.nan))
        w = 0.5 if (np.isfinite(sh) and sh <= 0.0) else 1.0
        comb_dyn.append((q, combine(parts, {"tsmom": 1.0, "carry": w, "receipts_level": 1.0})))
        comb_static.append((q, combine(parts, dict(cfg3.signals.weights))))
        rows46.append(
            {
                "quarter": str(q),
                "cutoff": str(cut.date()),
                "carry_3y_net_sharpe": sh,
                "carry_weight": w,
                "switched": w != w_prev,
            }
        )
        w_prev = w
        print(f"46 {q} cut {cut.date()} carry 3y sharpe {sh:+.2f} → w={w}", flush=True)
    tab46 = pd.DataFrame(rows46)
    tab46.to_csv(OUT / "exp46_quarters.csv", index=False)
    for arm, cb in (("46_C3_carry开关", comb_dyn), ("46_静态v0.3", comb_static)):
        st, eq = engine_stats(stitched_targets(cb, x3, cfg3), panels, specs, cfg3)
        summary[arm] = st
        equities[arm] = eq
        eq.to_csv(OUT / f"equity_{arm}.csv")
        print(arm, {k: round(v, 4) for k, v in st.items()}, flush=True)
    first_trigger = (
        tab46.loc[tab46["carry_weight"] < 1.0, "quarter"].iloc[0]
        if (tab46["carry_weight"] < 1.0).any()
        else None
    )

    df = pd.DataFrame(summary).T
    df.to_csv(OUT / "summary.csv")
    meta = {
        "git_sha": git_sha(),
        "elapsed_s": round(time.time() - t0, 1),
        "cutoffs": [(str(q), str(c.date())) for q, c in cuts],
        "exp45_changes": {"Q": changes_q, "A": changes_a},
        "exp46_first_trigger": first_trigger,
        "exp46_switches": int(tab46["switched"].sum()),
    }
    (OUT / "run.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    lines = [
        "# 季度重选(45)与 carry 开关(46)的历史 walk-forward(design_log 十九;后验提出,只作诊断)",
        "",
        f"git `{meta['git_sha']}`;主指标 = 引擎连续运行 2020-01-02 → 2026-09-18(空仓起跑,官方结算价);OOS 段 = 2022-01-04 → 2026-06-05 切段。",
        "",
        "## 汇总",
        "",
        "| 臂 | 年化 | 夏普(月) | 回撤 | 换手 | OOS 年化 | OOS 夏普 | OOS 回撤 | 次指标(6.2 口径) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, st in summary.items():
        fx = st.get("次指标:快速评估器拼接月夏普", np.nan)
        lines.append(
            f"| {arm} | {st['年化']:+.1%} | {st['夏普(月)']:.2f} | {st['回撤']:.1%} | {st['换手']:.0f}× | {st['OOS年化']:+.1%} | {st['OOS夏普(月)']:.2f} | {st['OOS回撤']:.1%} | {(f'{fx:.2f}') if np.isfinite(fx) else '—'} |"
        )
    lines += [
        "",
        f"实验 45 因子集合变化次数:季度臂 {changes_q},年度臂 {changes_a}。",
        "",
        "## 实验 45 逐季选择",
        "",
        tab45.to_markdown(index=False),
        "",
        f"## 实验 46 逐季 carry 开关(首次触发:{first_trigger},切换 {meta['exp46_switches']} 次)",
        "",
        tab46.round(3).to_markdown(index=False),
        "",
    ]
    Path("docs/walkforward_quarterly.md").write_text("\n".join(lines), encoding="utf-8")
    print(df.round(3).to_string())
    print(f"-> {OUT} / docs/walkforward_quarterly.md ({meta['elapsed_s']} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
