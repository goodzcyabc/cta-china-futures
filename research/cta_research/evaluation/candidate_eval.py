"""候选信号的统一三臂评价(从 research/scripts/fundamental_signal_diagnostic.py 抽出;该脚本保持原样不动)。

任何候选只需给出:date × symbol 的信号矩阵(取值 [−1, 1],篮子外 NaN)与点时审计表(数据日 / 公布日 / 目标日 / 建仓日)。
评价口径与 docs/research/fundamental_signal_prereg.md 第 5、6 节相同:
  candidate standalone / 静态正式基线 / 50-50 事前风险预算混合,同一条 raw_exposure → apply_buffer → run_backtest 路径;
  自候选首个持仓日起的绩效、配对差(NW + 块 bootstrap)、相关性、贡献与集中度、剔除最好项(前三品种为完整重跑)、多空两侧;
  判读 R0–R14 机械计算。本模块不含任何数据源或参数搜索。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.analysis.attribution import (
    Period,
    concentration,
    net_by_symbol_day,
    per_symbol_table,
    sector_contribution,
)
from cta.analysis.loo import segment_stats
from cta.analysis.stats import newey_west_mean, paired_differences, paired_summary
from cta.backtest.engine import BacktestResult, run_backtest
from cta.config import StrategyConfig, load_config
from cta.continuous.roll import SymbolPanel
from cta.data.exchanges.source import default_stitched
from cta.instruments.specs import InstrumentTable, load_instruments
from cta.pipeline import Signals, _receipts_of, _reg_events_of, build_panels, compute_signals
from cta.risk.metrics import TRADING_DAYS, perf_stats
from cta.signals.core import log_returns
from cta_research.signals import fundamental_signals as fs

Frame = pd.DataFrame


@dataclass(frozen=True)
class Candidate:
    tag: str
    name: str
    signal: Frame  # date × symbol,[−1, 1];NaN = 不参与
    audit: Frame  # 每次信号更新一行:data_date、info_date、target_day、exec_day
    x: pd.Series[Any] | None = None  # 单一预测变量(目标日索引);给定时 R0 用预测回归,否则用信号加权收益的 NW t
    expected_sign: int = 1
    notes: str = ""

    @property
    def basket(self) -> list[str]:
        return [str(c) for c in self.signal.columns if self.signal[c].notna().any()]


@dataclass
class Context:
    cfg: StrategyConfig
    specs: InstrumentTable
    panels: dict[str, SymbolPanel]
    sig: Signals
    dates: pd.DatetimeIndex
    start: pd.Timestamp
    end: pd.Timestamp
    oos_start: pd.Timestamp
    is_end: pd.Timestamp
    base_raw: Frame
    res_base: BacktestResult
    baseline_matches_reference: bool | None
    seed: int = 20261002
    n_boot: int = 2000
    block: int = 10
    lags: int = 5
    w_blend: float = 0.5


@dataclass
class CandidateEval:
    candidate: Candidate
    arms: dict[str, BacktestResult]
    summary: Frame
    paired: dict[str, Any]
    contrib: dict[str, Any]
    regression: dict[str, Any]
    checks: dict[str, bool]
    verdict: str
    first_active: pd.Timestamp
    extras: dict[str, Any] = field(default_factory=dict)


def engine_run(
    target: Frame, ctx_panels: dict[str, SymbolPanel], specs: InstrumentTable, cfg: StrategyConfig
) -> BacktestResult:
    return run_backtest(
        ctx_panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )


def build_context(
    config_path: str = "configs/strategy_v03.yaml",
    data_root: str = "data/ricecta/data",
    start: str = "2016-01-04",
    end: str = "2026-06-05",
    oos_start: str = "2022-01-04",
    is_end: str = "2021-12-31",
    reference_equity: str | None = "results/settle_baseline/equity_v0.3_full_D_unified_official.csv",
    seed: int = 20261002,
) -> Context:
    """载入生产数据与信号,按同一条路径重建静态基线;目标暴露须与生产逐位一致,权益与正式 D 臂逐位一致(参考文件存在时)。"""
    cfg = load_config(Path(config_path))
    specs = load_instruments()
    src = default_stitched(Path(data_root), official_settle=True)
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    t0, t1 = pd.Timestamp(start), pd.Timestamp(end)
    all_dates = pd.DatetimeIndex(sig.adj_close.index)
    dates = all_dates[(all_dates >= t0) & (all_dates <= t1)]
    base_raw = fs.raw_exposure(sig.combined, sig.eligible, sig.vol, sig.adj_close, cfg)
    base_tgt = fs.apply_buffer(base_raw, cfg, t0, t1)
    if not np.allclose(
        base_tgt.to_numpy(dtype=float),
        sig.target.reindex(index=base_tgt.index, columns=base_tgt.columns).to_numpy(dtype=float),
        equal_nan=True,
    ):
        raise RuntimeError("baseline target exposure does not reproduce the production target")
    res_base = engine_run(base_tgt, panels, specs, cfg)
    ok: bool | None = None
    if reference_equity is not None and Path(reference_equity).exists():
        ref = pd.read_csv(reference_equity, index_col=0, parse_dates=True).iloc[:, 0]
        common = res_base.equity.index.intersection(ref.index)
        ok = bool(
            np.allclose(
                res_base.equity.loc[common].to_numpy(dtype=float), ref.loc[common].to_numpy(dtype=float)
            )
        )
    return Context(
        cfg,
        specs,
        panels,
        sig,
        dates,
        t0,
        t1,
        pd.Timestamp(oos_start),
        pd.Timestamp(is_end),
        base_raw,
        res_base,
        ok,
        seed=seed,
    )


def first_active(res: BacktestResult) -> pd.Timestamp:
    act = res.positions.abs().sum(axis=1) > 0
    return pd.Timestamp(act[act].index.min()) if act.any() else pd.Timestamp(res.equity.index[0])


def audit_candidate(c: Candidate) -> tuple[bool, Frame]:
    """点时审计:有目标日的每条记录须 目标日 ≤ 公布日 < 建仓日;没有目标日的记录不产生信号。"""
    a = c.audit.copy()
    tgt, info, ex = (
        pd.to_datetime(a["target_day"]),
        pd.to_datetime(a["info_date"]),
        pd.to_datetime(a["exec_day"]),
    )
    has = tgt.notna() & ex.notna()  # 窗口末日的目标没有建仓日,不产生成交,不参与判定
    ok = (tgt <= info) & (info < ex)
    a["ok"] = ok.astype(object)
    a.loc[~has, "ok"] = pd.NA
    return bool(ok[has].all()) and int(has.sum()) > 0, a


def arm_stats(
    res: BacktestResult, specs: InstrumentTable, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, float]:
    eq = res.equity
    idx = pd.DatetimeIndex(eq.index)
    m = np.asarray((idx >= start) & (idx <= end))
    seg = eq[m]
    out = segment_stats(eq, start, end)
    ps = perf_stats(seg) if len(seg) > 40 else {}
    years = max(len(seg) / TRADING_DAYS, 1e-9)
    avg_eq = float(seg.mean()) if len(seg) else float("nan")
    tr = res.trades.copy()
    notional = 0.0
    if len(tr):
        tr["date"] = pd.to_datetime(tr["date"])
        tr = tr[(tr["date"] >= start) & (tr["date"] <= end)]
        mult = tr["symbol"].map(lambda s: specs[str(s)].multiplier)
        notional = float((tr["lots"].abs() * tr["price"] * mult).sum())
    fees = float(res.costs.loc[m].sum())
    slip = float(res.slippage.loc[m].sum()) if len(res.slippage) else 0.0
    out.update(
        {
            "月频NW t": float(ps.get("月频NW t", np.nan)),
            "年化名义换手": notional / years / avg_eq if avg_eq else float("nan"),
            "年化手续费占权益": fees / years / avg_eq if avg_eq else float("nan"),
            "年化滑点占权益": slip / years / avg_eq if avg_eq else float("nan"),
            "净盈亏": float(seg.iloc[-1] - seg.iloc[0]) if len(seg) else float("nan"),
        }
    )
    return out


def _period_table(net: Frame, freq: str) -> pd.Series[Any]:
    g = net.groupby(pd.DatetimeIndex(net.index).to_period(freq)).sum().sum(axis=1)
    g.index = g.index.astype(str)
    return g


def _share(x: pd.Series[Any]) -> dict[str, Any]:
    pos = x[x > 0]
    tot, pos_tot = float(x.sum()), float(pos.sum())
    mx = float(pos.max()) if len(pos) else 0.0
    return {
        "max_item": str(pos.idxmax()) if len(pos) else "",
        "max_share_of_positive": mx / pos_tot if pos_tot > 0 else float("nan"),
        "positive_total": pos_tot,
        "total": tot,
    }


def _stats_excluding(eq: pd.Series[Any], drop: np.ndarray[Any, Any]) -> dict[str, float]:
    r = eq.pct_change().dropna()
    keep = r[~drop[1:]]
    if len(keep) < 40:
        return {"年化收益": float("nan"), "夏普(月频)": float("nan"), "最大回撤": float("nan")}
    eq2 = (1 + keep).cumprod() * float(eq.iloc[0])
    return segment_stats(eq2, pd.Timestamp(eq2.index[0]), pd.Timestamp(eq2.index[-1]))


def signal_weighted_returns(ctx: Context, c: Candidate) -> pd.Series[Any]:
    """信号加权的等风险毛收益(信号 T → T+1 收盘到收盘;每品种按 1/σ 缩放后在有信号的品种间平均)。只用于 R0 与事件描述。
    口径说明:分母是 T+1 的 40 日波动率(含 T+1 当日收益),会轻微压缩大波动日;试验 52–60 的 R0 均为此口径,
    为可复现不改(2026-10-05 独立复核指出;不影响引擎回测)。"""
    r = log_returns(ctx.sig.adj_close)
    s = c.signal.reindex(index=r.index, columns=r.columns)
    scaled = (r / ctx.sig.vol.replace(0, np.nan)).shift(-1)  # T+1 的收益 / T+1 的波动率(见上方口径说明)
    contrib = s * scaled
    out: pd.Series[Any] = contrib.mean(axis=1, skipna=True)
    idx = pd.DatetimeIndex(out.index)
    return out[np.asarray((idx >= ctx.start) & (idx <= ctx.end))]


def evaluate(ctx: Context, c: Candidate) -> CandidateEval:
    cfg, specs = ctx.cfg, ctx.specs
    pit_ok, _ = audit_candidate(c)
    comb = c.signal.reindex(index=ctx.sig.adj_close.index, columns=ctx.sig.adj_close.columns)
    raw_c = fs.raw_exposure(comb, ctx.sig.eligible, ctx.sig.vol, ctx.sig.adj_close, cfg)
    tgt_c = fs.apply_buffer(raw_c, cfg, ctx.start, ctx.end)
    bl_raw = fs.blend_exposure(ctx.base_raw, raw_c, ctx.w_blend)
    gross_ok = bool(
        (
            bl_raw.abs().sum(axis=1)
            <= (1 - ctx.w_blend) * ctx.base_raw.fillna(0.0).abs().sum(axis=1)
            + ctx.w_blend * raw_c.fillna(0.0).abs().sum(axis=1)
            + 1e-9
        ).all()
    )
    if not gross_ok:
        raise RuntimeError(f"{c.tag}: blend gross exposure exceeds convex bound")
    tgt_bl = fs.apply_buffer(bl_raw, cfg, ctx.start, ctx.end)
    sa, bl = f"{c.tag}_standalone", f"{c.tag}_blend"
    arms = {
        sa: engine_run(tgt_c, ctx.panels, specs, cfg),
        bl: engine_run(tgt_bl, ctx.panels, specs, cfg),
        "baseline": ctx.res_base,
    }
    fa = first_active(arms[sa])
    rows: list[dict[str, Any]] = []
    for arm in (sa, bl, "baseline"):
        for pname, s, e in (
            ("SINCE_ACTIVE", fa, ctx.end),
            ("OOS", max(fa, ctx.oos_start), ctx.end),
            ("IS", fa, ctx.is_end),
        ):
            if s >= e:
                continue
            st: dict[str, Any] = dict(arm_stats(arms[arm], specs, s, e))
            st.update(
                {
                    "candidate": c.tag,
                    "arm": arm,
                    "period": pname,
                    "start": str(s.date()),
                    "end": str(e.date()),
                }
            )
            rows.append(st)
    summ = pd.DataFrame(rows)

    base_r = ctx.res_base.equity.pct_change().dropna()
    r_c = arms[sa].equity.pct_change().dropna()
    common = r_c.index.intersection(base_r.index)
    common = common[common >= fa]
    corr_d = (
        float(np.corrcoef(r_c.loc[common], base_r.loc[common])[0, 1]) if len(common) > 20 else float("nan")
    )
    m_c = (1 + r_c.loc[common]).resample("ME").prod() - 1
    m_b = (1 + base_r.loc[common]).resample("ME").prod() - 1
    corr_m = float(np.corrcoef(m_c, m_b)[0, 1]) if len(m_c) > 6 else float("nan")
    paired: dict[str, Any] = {}
    for arm in (sa, bl):
        kw = {"lags": ctx.lags, "block": ctx.block, "n_boot": ctx.n_boot, "seed": ctx.seed}
        paired[arm] = {
            "since_active": paired_summary(ctx.res_base.equity, arms[arm].equity, start=fa, **kw),
            "oos": paired_summary(ctx.res_base.equity, arms[arm].equity, start=max(fa, ctx.oos_start), **kw),
            "corr_daily_with_baseline": corr_d,
            "corr_monthly_with_baseline": corr_m,
        }
    _ = paired_differences  # 保留导入:配对差定义见 cta.analysis.stats

    # R0:预测回归(给定 x)或信号加权毛收益的 NW t
    swr = signal_weighted_returns(ctx, c).dropna()
    nw = newey_west_mean(swr.to_numpy(dtype=float), ctx.lags)
    reg: dict[str, Any] = {
        "signal_weighted_gross_ann": float(swr.mean() * TRADING_DAYS),
        "signal_weighted_nw_t": float(nw.t),
        "n_days": int(nw.n),
    }
    if c.x is not None:
        tds = pd.DatetimeIndex(sorted(set(pd.to_datetime(c.audit["target_day"].dropna()))))
        basket_daily = fs.equal_risk_basket_daily(ctx.sig.adj_close, ctx.sig.vol, c.basket, tds)
        y = fs.monthly_from_daily(basket_daily, tds)
        x = c.x[pd.notna(pd.Series(c.x.index, index=c.x.index))]
        for name, mask in (
            ("FULL", x.index <= ctx.end),
            ("IS", x.index <= ctx.is_end),
            ("OOS", x.index >= ctx.oos_start),
        ):
            reg[f"reg_{name}"] = fs.predictive_regression(x[mask], y.reindex(x[mask].index))
        r0 = bool(c.expected_sign * reg["reg_FULL"]["beta"] > 0 and abs(reg["reg_FULL"]["t"]) >= 2.0)
    else:
        r0 = bool(nw.t >= 2.0)

    # 贡献、集中度、剔除、多空
    contrib: dict[str, Any] = {}
    for arm in (sa, bl):
        res = arms[arm]
        periods = [
            p
            for p in (
                Period("FULL", fa, ctx.end),
                Period("IS", fa, ctx.is_end),
                Period("OOS", max(fa, ctx.oos_start), ctx.end),
            )
            if p.start < p.end
        ]
        tab = per_symbol_table(res, specs, periods, cfg.backtest.initial_capital_cny)
        conc = concentration(tab, periods, ks=(1, 3))
        net = net_by_symbol_day(res, specs)
        net = net[(net.index >= fa) & (net.index <= ctx.end)]
        yr, qt = _period_table(net, "Y"), _period_table(net, "Q")
        eq = res.equity[(res.equity.index >= fa) & (res.equity.index <= ctx.end)]
        eidx = pd.DatetimeIndex(eq.index)
        best_year, best_q = str(yr.idxmax()), str(qt.idxmax())
        full_conc = conc[conc["period"] == "FULL"].set_index("k")
        ks = [int(k) for k in full_conc.index.tolist()]
        sym_by_k = dict(zip(ks, [str(v) for v in full_conc["symbols"].tolist()]))
        share_by_k = dict(zip(ks, [float(v) for v in full_conc["share_of_positive"].tolist()]))
        top3 = [x3 for x3 in sym_by_k.get(3, "").split(",") if x3]
        src_raw = raw_c if arm == sa else bl_raw
        t3 = fs.apply_buffer(src_raw, cfg, ctx.start, ctx.end)
        for sym in top3:
            if sym in t3.columns:
                t3[sym] = 0.0
        ex3 = (
            segment_stats(engine_run(t3, ctx.panels, specs, cfg).equity, fa, ctx.end)
            if top3
            else {"夏普(月频)": float("nan")}
        )
        pos = res.positions.reindex(index=net.index, columns=net.columns).fillna(0.0)
        contrib[arm] = {
            "symbol_table": tab,
            "sector_table": sector_contribution(tab, periods),
            "year": yr,
            "quarter": qt,
            "year_share": _share(yr),
            "quarter_share": _share(qt),
            "top1_share": share_by_k.get(1, float("nan")),
            "top3_share": share_by_k.get(3, float("nan")),
            "top3": top3,
            "ex_best_year": {
                "item": best_year,
                **_stats_excluding(eq, np.asarray(eidx.to_period("Y").astype(str) == best_year)),
            },
            "ex_best_quarter": {
                "item": best_q,
                **_stats_excluding(eq, np.asarray(eidx.to_period("Q").astype(str) == best_q)),
            },
            "ex_top3_symbols": ex3,
            "long_net": float(net.where(pos > 0, 0.0).to_numpy().sum()),
            "short_net": float(net.where(pos < 0, 0.0).to_numpy().sum()),
            "days_long_share": float((pos > 0).to_numpy().sum() / max((pos != 0).to_numpy().sum(), 1)),
        }

    def row(arm: str, period: str) -> pd.Series[Any] | None:
        sel = summ[(summ["arm"] == arm) & (summ["period"] == period)]
        return sel.iloc[0] if len(sel) else None

    s_full = row(sa, "SINCE_ACTIVE")
    s_is, s_oos = row(sa, "IS"), row(sa, "OOS")
    p_bl, p_bl_oos = paired[bl]["since_active"], paired[bl]["oos"]
    cs = contrib[sa]
    sharpe_sa = float(s_full["夏普(月频)"]) if s_full is not None else float("nan")
    checks = {
        "R0_predictive_test_expected_sign_t_ge_2": r0,
        "R1_standalone_net_sharpe_pos": bool(sharpe_sa > 0),
        "R2_blend_paired_point_pos": bool(p_bl["ann_mean"] > 0),
        "R3_blend_paired_ci_excludes_0": bool(p_bl["boot_ci_low_ann"] > 0),
        "R4_blend_paired_oos_point_pos": bool(p_bl_oos["ann_mean"] > 0),
        "R5_corr_with_baseline_le_0.3": bool(corr_d <= 0.3),
        "R6_not_single_quarter_gt_50pct": bool(not (cs["quarter_share"]["max_share_of_positive"] > 0.5)),
        "R7_not_top3_symbols_gt_70pct": bool(not (cs["top3_share"] > 0.7)) if len(c.basket) > 4 else True,
        "R8_not_single_year_gt_60pct": bool(not (cs["year_share"]["max_share_of_positive"] > 0.6)),
        "R9_ex_top3_symbols_still_pos": bool(cs["ex_top3_symbols"]["夏普(月频)"] > 0)
        if len(c.basket) > 4
        else True,
        "R10_ex_best_year_still_pos": bool(cs["ex_best_year"]["夏普(月频)"] > 0),
        "R11_standalone_nw_t_ge_2": bool(float(s_full["月频NW t"]) >= 2.0) if s_full is not None else False,
        "R12_blend_paired_ge_1pct_per_year": bool(p_bl["ann_mean"] >= 0.01),
        "R13_point_in_time_ok": bool(pit_ok and ctx.baseline_matches_reference is not False),
        "R14_standalone_is_oos_same_sign": bool(
            np.sign(float(s_is["净盈亏"])) == np.sign(float(s_oos["净盈亏"]))
        )
        if s_is is not None and s_oos is not None
        else True,
    }
    noise = (
        (not checks["R1_standalone_net_sharpe_pos"])
        or (not checks["R2_blend_paired_point_pos"])
        or (not checks["R14_standalone_is_oos_same_sign"])
        or (not checks["R6_not_single_quarter_gt_50pct"])
        or (not checks["R7_not_top3_symbols_gt_70pct"])
        or (not checks["R5_corr_with_baseline_le_0.3"] and not checks["R3_blend_paired_ci_excludes_0"])
    )
    if not checks["R13_point_in_time_ok"]:
        verdict = "Invalid"
    elif all(checks.values()):
        verdict = "Candidate signal"
    elif noise:
        verdict = "Noise"
    else:
        verdict = "Weak evidence"
    return CandidateEval(c, arms, summ, paired, contrib, reg, checks, verdict, fa)


def write_eval(out: Path, ev: CandidateEval) -> None:
    """落盘:权益、成交、目标、汇总、配对、贡献、判读(机器可读)。"""
    import json

    out.mkdir(parents=True, exist_ok=True)
    tag = ev.candidate.tag
    for name, res in ev.arms.items():
        if name == "baseline":
            continue
        res.equity.to_csv(out / f"equity_{name}.csv")
        res.trades.to_csv(out / f"trades_{name}.csv", index=False)
    ev.summary.to_csv(out / f"summary_{tag}.csv", index=False)
    ok, audit = audit_candidate(ev.candidate)
    audit.to_csv(out / f"point_in_time_audit_{tag}.csv", index=False)
    for arm, cdict in ev.contrib.items():
        cdict["symbol_table"].to_csv(out / f"contrib_symbol_{arm}.csv")
        cdict["sector_table"].to_csv(out / f"contrib_sector_{arm}.csv")
        cdict["year"].to_csv(out / f"contrib_year_{arm}.csv")
        cdict["quarter"].to_csv(out / f"contrib_quarter_{arm}.csv")
    slim = {
        arm: {k: v for k, v in cdict.items() if k not in ("symbol_table", "sector_table", "year", "quarter")}
        for arm, cdict in ev.contrib.items()
    }
    payload = {
        "tag": tag,
        "name": ev.candidate.name,
        "basket": ev.candidate.basket,
        "first_active": str(ev.first_active.date()),
        "verdict": ev.verdict,
        "checks": ev.checks,
        "paired": ev.paired,
        "regression": ev.regression,
        "contributions": slim,
        "point_in_time_ok": ok,
    }
    (out / f"eval_{tag}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
