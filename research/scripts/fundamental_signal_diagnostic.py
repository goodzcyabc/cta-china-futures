"""独立信息两条的回顾性诊断(预注册 docs/research/fundamental_signal_prereg.md;试验 50、51)。

A. 全市场持仓兴趣(Hong–Yogo 2012 口径):全市场名义持仓 12 个月对数增长 → 扩展窗口 z → clip ±2 / 2 → 全部 22 个品种同一信号;
B. PMI 新订单 / 产成品库存 → 扩展窗口 z → clip ±2 / 2 → 工业品 + 能源篮子(13 个品种)同一信号。
每条候选三个固定组合:candidate standalone / 静态正式基线 v0.3 / 50-50 事前风险预算混合;同一数据、引擎、成本、执行、风险模型。
用法:python research/scripts/fundamental_signal_diagnostic.py [--smoke]
输出:results/fundamental_signal_diagnostic/、docs/research/fundamental_signal_diagnostic.md(表格;结论由人按预注册第 7 节判读后追加在标记之间)。
不改任何策略对象、纸面账或正式报告。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/(cta_research)

from cta.analysis.attribution import (
    Period,
    concentration,
    net_by_symbol_day,
    per_symbol_table,
    sector_contribution,
)  # noqa: E402
from cta.analysis.loo import segment_stats  # noqa: E402
from cta.analysis.stats import (  # noqa: E402
    block_bootstrap_mean,
    newey_west_mean,
    paired_differences,
    paired_summary,
)
from cta.backtest.engine import BacktestResult, run_backtest  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import (
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    git_sha,
    summarize_result,
)  # noqa: E402
from cta.risk.metrics import TRADING_DAYS  # noqa: E402
from cta_research.signals import fundamental_signals as fs  # noqa: E402

RQ = Path("data/ricecta/data")
MACRO = RQ / "macro_factors"
HIST = pd.Timestamp("2016-01-04")
END = pd.Timestamp("2026-06-05")  # 正式 OOS 末日 = 配置 backtest.end;宏观导出止于 2026-05-31 公布
OOS_START = pd.Timestamp("2022-01-04")
IS_END = pd.Timestamp("2021-12-31")
SEED, N_BOOT, BLOCK, LAGS = 20260926, 2000, 10, 5
W_BLEND = 0.5
OI_MEASURE = "notional"  # 预注册第 3 节:名义持仓(合约数 × 结算价 × 乘数)
NO_FILE, FG_FILE = "制造业采购经理指数PMI_新订单.parquet", "制造业采购经理指数PMI_产成品库存.parquet"
INDUSTRIAL_CLASSES = ("metal", "ferrous", "chem", "energy")  # 预注册第 4 节:工业品 + 能源;不含贵金属、农产品


def prereg_commit() -> str:
    """预注册文件的首次提交(运行前已提交;从 git 历史取,不手填)。"""
    import subprocess

    try:
        out = subprocess.run(
            [
                "git",
                "log",
                "--follow",
                "--format=%h",
                "--diff-filter=A",
                "--",
                "docs/research/fundamental_signal_prereg.md",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        return out[-1] if out else "uncommitted"
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


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


def first_active(res: BacktestResult) -> pd.Timestamp:
    act = res.positions.abs().sum(axis=1) > 0
    return pd.Timestamp(act[act].index.min()) if act.any() else pd.Timestamp(res.equity.index[0])


def daily_ret(eq: pd.Series[Any]) -> pd.Series[Any]:
    r: pd.Series[Any] = eq.pct_change().dropna()
    return r


def arm_stats(res: BacktestResult, specs: Any, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    """[start, end] 段(权益切段):年化、月频夏普、月频 NW t、回撤;整段成本与换手(年化,占平均权益)。"""
    eq = res.equity
    idx = pd.DatetimeIndex(eq.index)
    m = (idx >= start) & (idx <= end)
    seg = eq[m]
    st, _ = summarize_result(res, specs)
    out = segment_stats(eq, start, end)
    from cta.risk.metrics import perf_stats

    ps = perf_stats(seg) if len(seg) > 40 else {}
    years = max(len(seg) / TRADING_DAYS, 1e-9)
    avg_eq = float(seg.mean()) if len(seg) else np.nan
    tr = res.trades.copy()
    if len(tr):
        tr["date"] = pd.to_datetime(tr["date"])
        tr = tr[(tr["date"] >= start) & (tr["date"] <= end)]
        notional = float(
            (tr["lots"].abs() * tr["price"] * tr["symbol"].map(lambda s: specs[str(s)].multiplier)).sum()
        )
    else:
        notional = 0.0
    fees = float(res.costs.loc[m].sum())
    slip = float(res.slippage.loc[m].sum()) if len(res.slippage) else 0.0
    out.update(
        {
            "月频NW t": float(ps.get("月频NW t", np.nan)),
            "月胜率": float(ps.get("月胜率", np.nan)),
            "年化名义换手": notional / years / avg_eq if avg_eq else np.nan,
            "年化手续费占权益": fees / years / avg_eq if avg_eq else np.nan,
            "年化滑点占权益": slip / years / avg_eq if avg_eq else np.nan,
            "手续费合计": fees,
            "滑点合计": slip,
            "净盈亏": float(seg.iloc[-1] - seg.iloc[0]) if len(seg) else np.nan,
            "期末权益": float(seg.iloc[-1]) if len(seg) else np.nan,
            "全样本夏普(首个持仓日起)": float(st["夏普(月频)"]),
        }
    )
    return out


def boot_samples(x: np.ndarray[Any, Any], block: int, n_boot: int, seed: int) -> np.ndarray[Any, Any]:
    """与 cta.analysis.stats.block_bootstrap_mean 同一算法、同一种子,返回全部 bootstrap 均值(用于落盘分布)。"""
    v = np.asarray(x, dtype=float)
    v = v[np.isfinite(v)]
    n = int(len(v))
    b = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / b))
    starts = rng.integers(0, n - b + 1, size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means: np.ndarray[Any, Any] = v[idx].mean(axis=1)
    return means


def period_table(net: pd.DataFrame, freq: str) -> pd.DataFrame:
    """date × symbol 净贡献 → 按年/季汇总:组合净盈亏、正贡献占比用的分子。"""
    g = net.groupby(pd.DatetimeIndex(net.index).to_period(freq)).sum()
    out = pd.DataFrame({"net_pnl": g.sum(axis=1)})
    out.index = out.index.astype(str)
    return out


def share_stats(x: pd.Series[Any]) -> dict[str, float]:
    pos = x[x > 0]
    tot, pos_tot = float(x.sum()), float(pos.sum())
    mx = float(pos.max()) if len(pos) else 0.0
    return {
        "max_item": str(pos.idxmax()) if len(pos) else "",
        "max_share_of_positive": mx / pos_tot if pos_tot > 0 else np.nan,
        "max_share_of_total": mx / tot if tot > 0 else np.nan,
        "positive_total": pos_tot,
        "total": tot,
    }


def stats_excluding(eq: pd.Series[Any], drop_mask: np.ndarray[Any, Any]) -> dict[str, float]:
    """剔除某段日收益后的年化 / 月频夏普(把剩余日收益重新复利)。"""
    r = daily_ret(eq)
    keep = r[~drop_mask[1:]] if len(drop_mask) == len(eq) else r
    if len(keep) < 40:
        return {"年化收益": np.nan, "夏普(月频)": np.nan}
    eq2 = (1 + keep).cumprod() * float(eq.iloc[0])
    return segment_stats(eq2, pd.Timestamp(eq2.index[0]), pd.Timestamp(eq2.index[-1]))


def long_short_split(
    res: BacktestResult, specs: Any, start: pd.Timestamp, end: pd.Timestamp
) -> dict[str, float]:
    net = net_by_symbol_day(res, specs)
    pos = res.positions.reindex(index=net.index, columns=net.columns).fillna(0.0)
    idx = pd.DatetimeIndex(net.index)
    m = (idx >= start) & (idx <= end)
    n, p = net.loc[m], pos.loc[m]
    return {
        "long_net": float(n.where(p > 0, 0.0).to_numpy().sum()),
        "short_net": float(n.where(p < 0, 0.0).to_numpy().sum()),
        "flat_net": float(n.where(p == 0, 0.0).to_numpy().sum()),
        "days_long_share": float((p > 0).to_numpy().sum() / max((p != 0).to_numpy().sum(), 1)),
    }


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="只做基线复现与点时检查,不跑候选引擎")
    ap.add_argument("--out", default="results/fundamental_signal_diagnostic")
    ap.add_argument("--doc", default="docs/research/fundamental_signal_diagnostic.md")
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
    syms = list(sig.adj_close.columns)
    dates_all = pd.DatetimeIndex(sig.adj_close.index)
    dates = dates_all[(dates_all >= HIST) & (dates_all <= END)]
    log: dict[str, Any] = {
        "git_sha": git_sha(),
        "prereg_commit": prereg_commit(),
        "config": "configs/strategy_v03.yaml",
        "config_digest": hashlib.sha256(Path("configs/strategy_v03.yaml").read_bytes()).hexdigest()[:12],
        "window": [str(HIST.date()), str(END.date())],
        "oos_start": str(OOS_START.date()),
        "seed": SEED,
        "n_boot": N_BOOT,
        "block": BLOCK,
        "nw_lags_daily": LAGS,
        "nw_lags_monthly_regression": fs.REG_NW_LAGS,
        "oi_measure": OI_MEASURE,
        "growth_months": fs.GROWTH_MONTHS,
        "min_obs_z": fs.MIN_OBS_Z,
        "clip_z": fs.CLIP_Z,
        "stale_days": fs.STALE_DAYS,
        "oi_single_side_from": str(fs.OI_SINGLE_SIDE_FROM.date()),
        "oi_pre2020_scale": fs.OI_PRE2020_SCALE,
    }

    # ---------- 基线:同一条路径逐位复现 ----------
    base_raw = fs.raw_exposure(sig.combined, sig.eligible, sig.vol, sig.adj_close, cfg)
    base_tgt = fs.apply_buffer(base_raw, cfg, HIST, END)
    assert np.allclose(
        base_tgt.to_numpy(dtype=float),
        sig.target.loc[base_tgt.index, base_tgt.columns].to_numpy(dtype=float),
        equal_nan=True,
    )
    res_base = engine_run(base_tgt, panels, specs, cfg)
    ref_path = Path("results/settle_baseline/equity_v0.3_full_D_unified_official.csv")
    if ref_path.exists():
        ref = pd.read_csv(ref_path, index_col=0, parse_dates=True).iloc[:, 0]
        common = res_base.equity.index.intersection(ref.index)
        same = bool(
            np.allclose(
                res_base.equity.loc[common].to_numpy(dtype=float), ref.loc[common].to_numpy(dtype=float)
            )
        )
        log["baseline_matches_reference_D"] = same
        print(f"基线权益与正式 D 臂在 {len(common)} 个共同日期逐位一致 = {same}", flush=True)
        if not same:
            print("STOP: 静态基线无法复现正式 D 臂", file=sys.stderr)
            return 2
    else:
        log["baseline_matches_reference_D"] = None
        print(
            "提示:results/settle_baseline 不存在,跳过与 D 臂的逐位对比(目标暴露已与生产逐位一致)", flush=True
        )

    # ---------- 候选 A:全市场持仓兴趣 ----------
    oi = fs.contract_open_interest(src, syms, specs)
    oi_frame = oi.notional if OI_MEASURE == "notional" else oi.contracts
    oi_frame = oi_frame[(oi_frame.index >= HIST) & (oi_frame.index <= END)]
    me = fs.month_end_dates(dates)
    sector_of = {s: specs[s].asset_class for s in syms}
    sec_tab = fs.sector_ew_growth(oi_frame, me, sector_of)
    one = fs.aggregate_growth(oi_frame, me, k=1)
    growth = pd.DataFrame({"growth": sec_tab["x"], "n_symbols": one["n_symbols"], "oi_now": one["oi_now"]})
    z_a = fs.expanding_z(growth["growth"])
    s_a = fs.signal_from_z(z_a)
    rel_a = [fs.Release(pd.Timestamp(t), pd.Timestamp(t), float(v)) for t, v in s_a.dropna().items()]
    daily_a = fs.releases_to_daily(rel_a, dates)
    tab_a = pd.DataFrame(
        {
            "x_12m_geo_avg": growth["growth"],
            "agg_1m": sec_tab["agg_1m"],
            "n_sectors": sec_tab["n_sectors"],
            "n_symbols": growth["n_symbols"],
            "notional_total": growth["oi_now"],
            "z": z_a,
            "signal": s_a,
        }
    )
    for c in [c for c in sec_tab.columns if c.startswith("g_")]:
        tab_a[c] = sec_tab[c]
    tab_a["target_day"] = [fs.effective_target_day(pd.Timestamp(t), dates) for t in tab_a.index]
    tab_a["exec_day"] = [
        dates[dates > pd.Timestamp(t)][0] if (dates > pd.Timestamp(t)).any() else pd.NaT for t in tab_a.index
    ]
    tab_a.to_csv(out / "A_monthly_signal.csv")
    oi.coverage.to_csv(out / "A_oi_coverage.csv")
    sec_tab.to_csv(out / "A_sector_growth.csv")

    # ---------- 候选 B:PMI 新订单 / 产成品库存 ----------
    no = fs.load_macro(str(MACRO / NO_FILE))
    fg = fs.load_macro(str(MACRO / FG_FILE))
    rel_b_raw = fs.pmi_ratio_releases(no, fg)
    ratio = pd.Series({r.info_date: r.value for r in rel_b_raw}, dtype=float).sort_index()
    z_b = fs.expanding_z(ratio)
    s_b = fs.signal_from_z(z_b)
    rel_b = [
        fs.Release(pd.Timestamp(d), next(r.period_end for r in rel_b_raw if r.info_date == d), float(v))
        for d, v in s_b.dropna().items()
    ]
    daily_b = fs.releases_to_daily(rel_b, dates)
    basket_b = [s for s in syms if sector_of[s] in INDUSTRIAL_CLASSES]
    tab_b = pd.DataFrame(
        {"period_end": [r.period_end for r in rel_b_raw], "ratio": [r.value for r in rel_b_raw]},
        index=[r.info_date for r in rel_b_raw],
    )
    tab_b["z"] = z_b
    tab_b["signal"] = s_b
    tab_b["target_day"] = [fs.effective_target_day(pd.Timestamp(d), dates) for d in tab_b.index]
    tab_b["exec_day"] = [
        dates[dates > pd.Timestamp(d)][0] if (dates > pd.Timestamp(d)).any() else pd.NaT for d in tab_b.index
    ]
    tab_b.index.name = "info_date"
    tab_b.to_csv(out / "B_releases_signal.csv")
    log["basket_A"] = syms
    log["basket_B"] = basket_b
    log["A_first_signal"] = str(daily_a.first_valid_index())
    log["B_first_signal"] = str(daily_b.first_valid_index())
    log["A_n_month_ends"] = int(len(me))
    log["B_n_releases"] = int(len(rel_b_raw))

    # 点时审计表:每条信号的 数据日 / 公布日 / 目标日 / 建仓日
    audit = pd.concat(
        [
            pd.DataFrame(
                {
                    "arm": "A",
                    "data_date": tab_a.index,
                    "info_date": tab_a.index,
                    "target_day": tab_a["target_day"].to_numpy(),
                    "exec_day": tab_a["exec_day"].to_numpy(),
                }
            ),
            pd.DataFrame(
                {
                    "arm": "B",
                    "data_date": tab_b["period_end"].to_numpy(),
                    "info_date": tab_b.index,
                    "target_day": tab_b["target_day"].to_numpy(),
                    "exec_day": tab_b["exec_day"].to_numpy(),
                }
            ),
        ]
    )
    has_target = pd.to_datetime(audit["target_day"]).notna()
    # 统计局在月末前公布(春节等)时 data_date > info_date,数据仍属该月;只作标记
    audit["early_release"] = pd.to_datetime(audit["data_date"]) > pd.to_datetime(audit["info_date"])
    audit["ok"] = (pd.to_datetime(audit["target_day"]) <= pd.to_datetime(audit["info_date"])) & (
        pd.to_datetime(audit["info_date"]) < pd.to_datetime(audit["exec_day"])
    )
    audit["ok"] = audit["ok"].astype(object)
    audit.loc[~has_target, "ok"] = pd.NA  # 没有目标日的记录不会产生信号(日历首日之前、窗口末日之后)
    audit.to_csv(out / "point_in_time_audit.csv", index=False)
    pit_ok = bool(audit.loc[has_target, "ok"].astype(bool).all()) and int(has_target.sum()) > 0
    log["point_in_time_rows_without_target"] = int((~has_target).sum())
    log["point_in_time_all_ok"] = pit_ok
    print(
        f"点时审计:全部信号 目标日 ≤ 公布日 < 建仓日 = {pit_ok};A 首个信号 {log['A_first_signal']},B 首个信号 {log['B_first_signal']}",
        flush=True,
    )
    if not pit_ok:
        print("STOP: 点时审计失败", file=sys.stderr)
        return 3
    if args.smoke:
        write_json(out / "run.json", log)
        print(f"smoke 完成({round(time.time() - t0, 1)} s)")
        return 0

    # ---------- 预测回归(paper-faithful,月频/发布频) ----------
    reg: dict[str, Any] = {}
    basket_daily_a = fs.equal_risk_basket_daily(sig.adj_close, sig.vol, syms, me)
    y_a = fs.monthly_from_daily(basket_daily_a, me)
    x_a = growth["growth"]
    for name, mask in (
        ("FULL", x_a.index <= END),
        ("IS", x_a.index <= IS_END),
        ("OOS", x_a.index >= OOS_START),
    ):
        reg[f"A_{name}"] = fs.predictive_regression(x_a[mask], y_a.reindex(x_a[mask].index))
    # 论文口径篮子(板块内等权、板块间等权)对同一预测变量的回归:只作对照,不用于判读
    reg["A_FULL_paper_basket"] = fs.predictive_regression(
        x_a,
        fs.monthly_from_daily(fs.sector_ew_basket_daily(sig.adj_close, syms, sector_of), me).reindex(
            x_a.index
        ),
    )
    # A 也报告每个板块篮子对全市场预测变量的回归(描述)
    for ac in sorted(set(sector_of.values())):
        bd = fs.equal_risk_basket_daily(sig.adj_close, sig.vol, [s for s in syms if sector_of[s] == ac], me)
        reg[f"A_sector_{ac}"] = fs.predictive_regression(
            x_a, fs.monthly_from_daily(bd, me).reindex(x_a.index)
        )
    # B:发布到发布的持有期收益(篮子 = 工业品 + 能源)
    tds_b = [t for t in tab_b["target_day"] if t is not None and not pd.isna(t)]
    basket_daily_b = fs.equal_risk_basket_daily(sig.adj_close, sig.vol, basket_b, pd.DatetimeIndex(tds_b))
    y_b = fs.monthly_from_daily(basket_daily_b, pd.DatetimeIndex(tds_b))
    x_b = pd.Series(
        tab_b["ratio"].to_numpy(dtype=float), index=pd.DatetimeIndex(tab_b["target_day"].to_numpy())
    )
    x_b = x_b[~x_b.index.isna()]
    for name, mask in (
        ("FULL", x_b.index <= END),
        ("IS", x_b.index <= IS_END),
        ("OOS", x_b.index >= OOS_START),
    ):
        reg[f"B_{name}"] = fs.predictive_regression(x_b[mask], y_b.reindex(x_b[mask].index))
    reg["B_agri_basket_descriptive"] = fs.predictive_regression(
        x_b,
        fs.monthly_from_daily(
            fs.equal_risk_basket_daily(
                sig.adj_close, sig.vol, [s for s in syms if sector_of[s] == "agri"], pd.DatetimeIndex(tds_b)
            ),
            pd.DatetimeIndex(tds_b),
        ).reindex(x_b.index),
    )
    pd.DataFrame(reg).T.to_csv(out / "predictive_regressions.csv")

    # ---------- 引擎:standalone / baseline / blend ----------
    arms: dict[str, BacktestResult] = {"baseline": res_base}
    raws = {"baseline": base_raw}
    for tag, daily, basket in (("A", daily_a, syms), ("B", daily_b, basket_b)):
        comb = fs.broadcast_signal(daily, basket, syms)
        raw_c = fs.raw_exposure(comb, sig.eligible, sig.vol, sig.adj_close, cfg)
        raws[tag] = raw_c
        tgt_c = fs.apply_buffer(raw_c, cfg, HIST, END)
        arms[f"{tag}_standalone"] = engine_run(tgt_c, panels, specs, cfg)
        bl_raw = fs.blend_exposure(base_raw, raw_c, W_BLEND)
        assert (
            bl_raw.abs().sum(axis=1)
            <= 0.5 * base_raw.fillna(0.0).abs().sum(axis=1) + 0.5 * raw_c.fillna(0.0).abs().sum(axis=1) + 1e-9
        ).all()
        tgt_bl = fs.apply_buffer(bl_raw, cfg, HIST, END)
        arms[f"{tag}_blend"] = engine_run(tgt_bl, panels, specs, cfg)
        tgt_c.to_csv(out / f"{tag}_standalone_target.csv")
        print(f"{tag}: standalone 首个持仓日 {first_active(arms[f'{tag}_standalone']).date()}", flush=True)
    for name, res in arms.items():
        res.equity.to_csv(out / f"equity_{name}.csv")
        res.trades.to_csv(out / f"trades_{name}.csv", index=False)

    # ---------- 统计汇总 ----------
    rows: list[dict[str, Any]] = []
    paired: dict[str, Any] = {}
    boot_dist: dict[str, np.ndarray[Any, Any]] = {}
    base_r = daily_ret(res_base.equity)
    for tag in ("A", "B"):
        fa = first_active(arms[f"{tag}_standalone"])
        for arm in (f"{tag}_standalone", f"{tag}_blend", "baseline"):
            res = arms[arm]
            for pname, s, e in (
                ("SINCE_ACTIVE", fa, END),
                ("OOS", max(fa, OOS_START), END),
                ("IS", fa, IS_END),
            ):
                if s >= e:
                    continue
                st = arm_stats(res, specs, s, e)
                st.update(
                    {
                        "candidate": tag,
                        "arm": arm,
                        "period": pname,
                        "start": str(s.date()),
                        "end": str(e.date()),
                    }
                )
                rows.append(st)
        # 相关性与配对差(相对基线;从候选首个持仓日起)
        r_c = daily_ret(arms[f"{tag}_standalone"].equity)
        common = r_c.index.intersection(base_r.index)
        common = common[common >= fa]
        corr_d = float(np.corrcoef(r_c.loc[common], base_r.loc[common])[0, 1])
        m_c = (1 + r_c.loc[common]).resample("ME").prod() - 1
        m_b = (1 + base_r.loc[common]).resample("ME").prod() - 1
        corr_m = float(np.corrcoef(m_c, m_b)[0, 1])
        for arm in (f"{tag}_standalone", f"{tag}_blend"):
            ps = paired_summary(
                res_base.equity, arms[arm].equity, lags=LAGS, block=BLOCK, n_boot=N_BOOT, seed=SEED, start=fa
            )
            ps_oos = paired_summary(
                res_base.equity,
                arms[arm].equity,
                lags=LAGS,
                block=BLOCK,
                n_boot=N_BOOT,
                seed=SEED,
                start=max(fa, OOS_START),
            )
            paired[arm] = {
                "since_active": ps,
                "oos": ps_oos,
                "corr_daily_with_baseline": corr_d,
                "corr_monthly_with_baseline": corr_m,
            }
            d = paired_differences(res_base.equity, arms[arm].equity, fa)["d"].to_numpy(dtype=float)
            boot_dist[arm] = boot_samples(d, BLOCK, N_BOOT, SEED) * TRADING_DAYS
            nw = newey_west_mean(d, LAGS)
            bt = block_bootstrap_mean(d, BLOCK, N_BOOT, SEED)
            paired[arm]["check"] = {
                "nw_t": nw.t,
                "boot_ci": [bt.ci_low * TRADING_DAYS, bt.ci_high * TRADING_DAYS],
            }
    summ = pd.DataFrame(rows)
    summ.to_csv(out / "summary.csv", index=False)
    pd.DataFrame(boot_dist).to_csv(out / "bootstrap_paired_diff_ann.csv", index=False)
    write_json(out / "paired.json", paired)

    # ---------- 贡献:品种 / 板块 / 年 / 季;集中度;剔除最好项;多空两侧;事件路径 ----------
    contrib: dict[str, Any] = {}
    for tag in ("A", "B"):
        fa = first_active(arms[f"{tag}_standalone"])
        periods = [Period("FULL", fa, END), Period("IS", fa, IS_END), Period("OOS", max(fa, OOS_START), END)]
        periods = [p for p in periods if p.start < p.end]
        for arm in (f"{tag}_standalone", f"{tag}_blend"):
            res = arms[arm]
            tab = per_symbol_table(res, specs, periods, cfg.backtest.initial_capital_cny)
            tab.to_csv(out / f"contrib_symbol_{arm}.csv")
            sector_contribution(tab, periods).to_csv(out / f"contrib_sector_{arm}.csv")
            conc = concentration(tab, periods, ks=(1, 3))
            conc.to_csv(out / f"concentration_{arm}.csv")
            net = net_by_symbol_day(res, specs)
            net = net[(net.index >= fa) & (net.index <= END)]
            yr, qt = period_table(net, "Y"), period_table(net, "Q")
            yr.to_csv(out / f"contrib_year_{arm}.csv")
            qt.to_csv(out / f"contrib_quarter_{arm}.csv")
            eq = res.equity[(res.equity.index >= fa) & (res.equity.index <= END)]
            eidx = pd.DatetimeIndex(eq.index)
            best_year = str(yr["net_pnl"].idxmax())
            best_q = str(qt["net_pnl"].idxmax())
            ex_year = stats_excluding(eq, np.asarray(eidx.to_period("Y").astype(str) == best_year))
            ex_q = stats_excluding(eq, np.asarray(eidx.to_period("Q").astype(str) == best_q))
            full_conc = conc[conc["period"] == "FULL"].set_index("k")
            top3 = str(full_conc.loc[3, "symbols"]).split(",") if 3 in full_conc.index else []
            # 剔除最好三个品种:目标暴露置 0 后完整重跑(引擎口径)
            tgt_src = fs.apply_buffer(
                raws[tag] if arm.endswith("standalone") else fs.blend_exposure(base_raw, raws[tag], W_BLEND),
                cfg,
                HIST,
                END,
            )
            t3 = tgt_src.copy()
            for s in top3:
                if s in t3.columns:
                    t3[s] = 0.0
            res3 = engine_run(t3, panels, specs, cfg)
            ex3 = segment_stats(res3.equity, fa, END)
            ls = long_short_split(res, specs, fa, END)
            contrib[arm] = {
                "first_active": str(fa.date()),
                "year": share_stats(yr["net_pnl"]),
                "quarter": share_stats(qt["net_pnl"]),
                "symbol_top1_share_of_positive": float(full_conc.loc[1, "share_of_positive"])
                if 1 in full_conc.index
                else np.nan,
                "symbol_top3_share_of_positive": float(full_conc.loc[3, "share_of_positive"])
                if 3 in full_conc.index
                else np.nan,
                "symbol_top3": top3,
                "ex_best_year": {"year": best_year, **ex_year},
                "ex_best_quarter": {"quarter": best_q, **ex_q},
                "ex_top3_symbols": ex3,
                "long_short": ls,
                "full": segment_stats(res.equity, fa, END),
            }
        # 事件路径(篮子对数收益,按信号符号取向)
        if tag == "A":
            td = [t for t in tab_a["target_day"] if t is not None and not pd.isna(t)]
            sg = [
                float(v)
                for t, v in zip(tab_a["target_day"], tab_a["signal"])
                if t is not None and not pd.isna(t)
            ]
            fs.event_paths(basket_daily_a, td, sg).to_csv(out / "A_event_path.csv")
        else:
            td = [t for t in tab_b["target_day"] if t is not None and not pd.isna(t)]
            sg = [
                float(v)
                for t, v in zip(tab_b["target_day"], tab_b["signal"])
                if t is not None and not pd.isna(t)
            ]
            fs.event_paths(basket_daily_b, td, sg).to_csv(out / "B_event_path.csv")
    write_json(out / "contributions.json", contrib)

    # ---------- 预注册第 7 节的机械判读 ----------
    verdicts: dict[str, Any] = {}
    for tag in ("A", "B"):
        sa, bl = f"{tag}_standalone", f"{tag}_blend"
        s_full = summ[(summ["arm"] == sa) & (summ["period"] == "SINCE_ACTIVE")].iloc[0]
        p_bl = paired[bl]["since_active"]
        p_bl_oos = paired[bl]["oos"]
        c = contrib[sa]
        checks = {
            "R1_standalone_net_sharpe_pos": bool(s_full["夏普(月频)"] > 0),
            "R2_blend_paired_point_pos": bool(p_bl["ann_mean"] > 0),
            "R3_blend_paired_ci_excludes_0": bool(p_bl["boot_ci_low_ann"] > 0),
            "R4_blend_paired_oos_point_pos": bool(p_bl_oos["ann_mean"] > 0),
            "R5_corr_with_baseline_le_0.3": bool(paired[sa]["corr_daily_with_baseline"] <= 0.3),
            "R6_not_single_quarter_gt_50pct": bool(not (c["quarter"]["max_share_of_positive"] > 0.5)),
            "R7_not_top3_symbols_gt_70pct": bool(not (c["symbol_top3_share_of_positive"] > 0.7)),
            "R8_not_single_year_gt_60pct": bool(not (c["year"]["max_share_of_positive"] > 0.6)),
            "R9_ex_top3_symbols_still_pos": bool(c["ex_top3_symbols"]["夏普(月频)"] > 0),
            "R10_ex_best_year_still_pos": bool(c["ex_best_year"]["夏普(月频)"] > 0),
            "R11_standalone_nw_t_ge_2": bool(s_full["月频NW t"] >= 2.0),
            "R12_blend_paired_ge_1pct_per_year": bool(p_bl["ann_mean"] >= 0.01),
            "R13_point_in_time_ok": pit_ok,
            "R0_regression_expected_sign_t_ge_2": bool(
                reg[f"{tag}_FULL"]["beta"] > 0 and reg[f"{tag}_FULL"]["t"] >= 2.0
            ),
            "R14_standalone_is_oos_same_sign": bool(
                np.sign(summ[(summ["arm"] == sa) & (summ["period"] == "IS")].iloc[0]["净盈亏"])
                == np.sign(summ[(summ["arm"] == sa) & (summ["period"] == "OOS")].iloc[0]["净盈亏"])
                if ((summ["arm"] == sa) & (summ["period"] == "IS")).any()
                and ((summ["arm"] == sa) & (summ["period"] == "OOS")).any()
                else True
            ),
        }
        noise = (
            (not checks["R1_standalone_net_sharpe_pos"])
            or (not checks["R2_blend_paired_point_pos"])
            or (not checks["R14_standalone_is_oos_same_sign"])
            or (not checks["R6_not_single_quarter_gt_50pct"])
            or (not checks["R7_not_top3_symbols_gt_70pct"])
            or (not checks["R5_corr_with_baseline_le_0.3"] and not checks["R3_blend_paired_ci_excludes_0"])
            or (not checks["R13_point_in_time_ok"])
        )
        candidate = all(checks[k] for k in sorted(checks))
        verdict = (
            "Invalid"
            if not pit_ok
            else ("Candidate signal" if candidate else ("Noise" if noise else "Weak evidence"))
        )
        verdicts[tag] = {"checks": checks, "verdict": verdict}
    write_json(out / "verdicts.json", verdicts)
    log.update(
        {"elapsed_s": round(time.time() - t0, 1), "verdicts": {k: v["verdict"] for k, v in verdicts.items()}}
    )
    write_json(out / "run.json", log)
    write_doc(Path(args.doc), log, summ, paired, contrib, reg, verdicts, tab_a, tab_b, oi.coverage)
    print(
        summ[
            [
                "candidate",
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
        .round(4)
        .to_string()
    )
    print({k: v["verdict"] for k, v in verdicts.items()})
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
    paired: dict[str, Any],
    contrib: dict[str, Any],
    reg: dict[str, Any],
    verdicts: dict[str, Any],
    tab_a: pd.DataFrame,
    tab_b: pd.DataFrame,
    coverage: pd.DataFrame,
) -> None:
    lines: list[str] = [
        "# 独立信息两条:全市场持仓兴趣与 PMI 订单/库存(回顾性诊断;预注册 `docs/research/fundamental_signal_prereg.md`)",
        "",
        "> 第 0 节(结论)与第 6 节以后由人撰写、保留在 HTML 标记之间;第 1–5 节表格由脚本生成,重跑只刷新表格;预注册第 1–10 节未改。",
        "",
        f"git `{log['git_sha']}`;预注册提交 `{log['prereg_commit']}`;配置 `{log['config']}`(摘要 {log['config_digest']});窗口 {log['window'][0]} → {log['window'][1]};OOS 自 {log['oos_start']};种子 {log['seed']}。",
        "",
        "## 1. 数据与点时",
        "",
        f"- A:持仓量口径 `{log['oi_measure']}`,{log['growth_months']} 个月增长;{log['oi_single_side_from']} 起单边计数,此前 ×{log['oi_pre2020_scale']};月末 {log['A_n_month_ends']} 个;首个可交易信号 {log['A_first_signal']};篮子 = 全部 {len(log['basket_A'])} 个品种。",
        f"- B:PMI 新订单 / 产成品库存,发布 {log['B_n_releases']} 条;首个可交易信号 {log['B_first_signal']};篮子 = {', '.join(log['basket_B'])}。",
        f"- 扩展窗口 z(最少 {log['min_obs_z']} 个观测)→ clip ±{log['clip_z']} / {log['clip_z']};超过 {log['stale_days']} 日无新公布 → 信号失效。",
        f"- 点时审计全部通过:{log['point_in_time_all_ok']};基线权益与正式 D 臂逐位一致:{log.get('baseline_matches_reference_D')}。",
        "",
        "### 1.1 持仓量覆盖",
        "",
        coverage.to_markdown(),
        "",
        "## 2. 预测回归(y_{t+1} = a + b·x_t;HAC 标准误)",
        "",
        pd.DataFrame(reg).T.round(4).to_markdown(),
        "",
        "## 3. 三个固定组合的绩效(自候选首个持仓日起;OOS 自 2022-01-04)",
        "",
    ]
    cols = [
        "candidate",
        "arm",
        "period",
        "start",
        "end",
        "年化收益",
        "夏普(月频)",
        "月频NW t",
        "最大回撤",
        "年化名义换手",
        "年化手续费占权益",
        "年化滑点占权益",
        "净盈亏",
    ]
    show = summ[cols].copy()
    for c in ("年化收益", "最大回撤", "年化手续费占权益", "年化滑点占权益"):
        show[c] = show[c].map(_pct)
    for c in ("夏普(月频)", "月频NW t", "年化名义换手"):
        show[c] = show[c].map(_f)
    show["净盈亏"] = show["净盈亏"].map(lambda v: f"{float(v) / 1e4:.1f} 万")
    lines += [
        show.to_markdown(index=False),
        "",
        "## 4. 相对基线的配对净收益差(NW lag 5;块 bootstrap 10 × 2000,种子固定)",
        "",
        "| 臂 | 区间 | 配对差年化 | NW SE | t | bootstrap 95% | 日相关 | 月相关 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm, p in paired.items():
        for per in ("since_active", "oos"):
            ps = p[per]
            lines.append(
                f"| {arm} | {per} | {_pct(ps['ann_mean'])} | {_pct(ps['nw_se_ann'])} | {_f(ps['t'])} | [{_pct(ps['boot_ci_low_ann'])}, {_pct(ps['boot_ci_high_ann'])}] | {_f(p['corr_daily_with_baseline'])} | {_f(p['corr_monthly_with_baseline'])} |"
            )
    lines += [
        "",
        "## 5. 集中度、剔除最好项、多空两侧",
        "",
        "| 臂 | 最大单季占正贡献 | 最大单年占正贡献 | 前 1 / 前 3 品种占正贡献 | 前 3 品种 | 去最好年 夏普 | 去最好季 夏普 | 去前三品种 夏普(重跑) | 多头净 / 空头净(万) | 多头日占比 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, c in contrib.items():
        lines.append(
            f"| {arm} | {_pct(c['quarter']['max_share_of_positive'])}({c['quarter']['max_item']}) | {_pct(c['year']['max_share_of_positive'])}({c['year']['max_item']}) | {_pct(c['symbol_top1_share_of_positive'])} / {_pct(c['symbol_top3_share_of_positive'])} | {','.join(c['symbol_top3'])} | {_f(c['ex_best_year']['夏普(月频)'])} | {_f(c['ex_best_quarter']['夏普(月频)'])} | {_f(c['ex_top3_symbols']['夏普(月频)'])} | {c['long_short']['long_net'] / 1e4:.1f} / {c['long_short']['short_net'] / 1e4:.1f} | {_pct(c['long_short']['days_long_share'])} |"
        )
    lines += [
        "",
        "### 5.1 预注册第 6 节的机械判读",
        "",
        pd.DataFrame({k: v["checks"] for k, v in verdicts.items()}).to_markdown(),
        "",
        f"判定:{ {k: v['verdict'] for k, v in verdicts.items()} }",
        "",
    ]
    lines += [
        "### 5.2 A 月度信号(节选:最近 12 个月末)",
        "",
        tab_a.tail(12).round(3).to_markdown(),
        "",
        "### 5.3 B 发布信号(节选:最近 12 次公布)",
        "",
        tab_b.tail(12).round(3).to_markdown(),
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
