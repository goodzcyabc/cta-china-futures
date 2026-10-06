"""独立信息两条(预注册 docs/research/fundamental_signal_prereg.md 第 9 节)的防泄漏测试:
cutoff 严格早于交易日、月内冻结、公布日前不可见、cutoff 后噪声不改历史、月末持仓量只影响下一交易日、未来合约持仓不改过去、
修订不覆盖历史 vintage、确定性、静态基线逐位复现、候选关闭时基线不变、混合不偷杠杆、缺失不补 0 不无限前填。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.analysis import fundamental_signals as fs

DATA = Path("data/ricecta/data")
needs_data = pytest.mark.skipif(not DATA.exists(), reason="需要本地米筐/交易所数据")


def _dates(start: str = "2016-01-04", end: str = "2018-12-31") -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


# ---------- 公布日 → 目标日 ----------
def test_release_effective_strictly_after_info_date_and_target_before_exec() -> None:
    dates = _dates()
    for info in (
        pd.Timestamp("2016-03-01"),
        pd.Timestamp("2016-03-05"),
        pd.Timestamp("2016-03-06"),
    ):  # 周二、周六、周日
        t = fs.effective_target_day(info, dates)
        assert t is not None
        exec_day = dates[dates > info][0]
        assert (
            t < exec_day and t <= info and dates[dates.get_loc(t) + 1] == exec_day
        )  # 目标日 = 建仓日前一交易日
    assert fs.effective_target_day(pd.Timestamp("2015-12-31"), dates) is None  # 日历首日之前:无法建仓


def test_signal_frozen_between_releases_and_invisible_before_info_date() -> None:
    dates = _dates()
    rel = [
        fs.Release(pd.Timestamp("2016-02-01"), pd.Timestamp("2016-01-31"), 1.0),
        fs.Release(pd.Timestamp("2016-03-01"), pd.Timestamp("2016-02-29"), 2.0),
    ]
    d = fs.releases_to_daily(rel, dates, stale_days=45)
    t1, t2 = (
        fs.effective_target_day(rel[0].info_date, dates),
        fs.effective_target_day(rel[1].info_date, dates),
    )
    assert t1 is not None and t2 is not None
    assert d[d.index < t1].isna().all()  # 公布前不可见
    seg = d[(d.index >= t1) & (d.index < t2)]
    assert (seg == 1.0).all() and seg.nunique() == 1  # 月内冻结
    assert d.loc[t2] == 2.0
    # 把第二次公布推迟 10 天:推迟前的日子仍是第一个值,不会提前看到第二个值
    late = [rel[0], fs.Release(rel[1].info_date + pd.Timedelta(days=10), rel[1].period_end, 2.0)]
    d2 = fs.releases_to_daily(late, dates, stale_days=45)
    t2b = fs.effective_target_day(late[1].info_date, dates)
    assert t2b is not None and (d2[(d2.index >= t2) & (d2.index < t2b)] == 1.0).all() and d2.loc[t2b] == 2.0


def test_revision_does_not_overwrite_history_and_stale_expires() -> None:
    dates = _dates()
    orig = fs.Release(pd.Timestamp("2016-02-01"), pd.Timestamp("2016-01-31"), 1.0)
    rev = fs.Release(
        pd.Timestamp("2016-02-20"), pd.Timestamp("2016-01-31"), 9.0
    )  # 同一期末的修订,晚 19 天公布
    d = fs.releases_to_daily([orig, rev], dates, stale_days=45)
    t_o, t_r = fs.effective_target_day(orig.info_date, dates), fs.effective_target_day(rev.info_date, dates)
    assert t_o is not None and t_r is not None
    assert (d[(d.index >= t_o) & (d.index < t_r)] == 1.0).all()  # 修订公布前仍是原值
    assert (d[(d.index >= t_r) & (d.index <= rev.info_date + pd.Timedelta(days=45))] == 9.0).all()
    assert d[d.index > rev.info_date + pd.Timedelta(days=45)].isna().all()  # 没有新公布 → 失效,不无限前填


def test_expanding_z_uses_only_past_and_min_obs() -> None:
    x = pd.Series(np.arange(40, dtype=float))
    z = fs.expanding_z(x, min_obs=24)
    assert z.iloc[:23].isna().all() and np.isfinite(z.iloc[23])
    x2 = x.copy()
    x2.iloc[30:] = 1e6  # 未来极端值
    z2 = fs.expanding_z(x2, min_obs=24)
    assert np.allclose(z.iloc[:30].dropna(), z2.iloc[:30].dropna())
    assert fs.signal_from_z(pd.Series([-5.0, 0.0, 1.0, 5.0])).tolist() == [-1.0, 0.0, 0.5, 1.0]


# ---------- 持仓量汇总 ----------
def test_aggregate_growth_chain_links_and_never_fills_zero() -> None:
    dates = _dates("2016-01-04", "2017-12-31")
    me = fs.month_end_dates(dates)
    oi = pd.DataFrame(100.0, index=dates, columns=["A", "B", "C"])
    oi["B"] = 200.0
    oi.loc[oi.index >= "2017-01-01", "A"] = 110.0  # A 增长 10%
    oi.loc[oi.index >= "2017-06-01", "C"] = np.nan  # C 缺失:退出集合而不是当 0
    g = fs.aggregate_growth(oi, me, k=12)
    t = me[me >= "2017-06-30"][0]
    row = g.loc[t]
    assert row["n_symbols"] == 2 and abs(row["growth"] - np.log((110 + 200) / (100 + 200))) < 1e-12
    assert g.iloc[:12]["growth"].isna().all()
    # 全部缺失 → NaN 而不是 0
    oi2 = oi.copy()
    oi2.loc[t] = np.nan
    assert (
        np.isnan(fs.aggregate_growth(oi2, me, k=12).loc[t, "growth"])
        and fs.aggregate_growth(oi2, me, k=12).loc[t, "n_symbols"] == 0
    )


def test_month_end_oi_only_affects_next_trading_day_and_future_oi_does_not_change_past() -> None:
    dates = _dates("2016-01-04", "2018-12-31")
    me = fs.month_end_dates(dates)
    rng = np.random.default_rng(0)
    oi = pd.DataFrame(
        1000 + rng.normal(0, 10, size=(len(dates), 2)).cumsum(axis=0), index=dates, columns=["A", "B"]
    )
    g = fs.aggregate_growth(oi, me, k=12)
    rel = [fs.Release(pd.Timestamp(t), pd.Timestamp(t), float(v)) for t, v in g["growth"].dropna().items()]
    d = fs.releases_to_daily(rel, dates, stale_days=45)
    t = pd.Timestamp("2017-06-30")
    assert t in me
    exec_day = dates[dates > t][0]
    # 改动 t 当天的持仓量:t 及以后的信号才变(目标记在 t,T+1 开盘成交),t 之前逐日不变
    oi2 = oi.copy()
    oi2.loc[t, "A"] *= 1.5
    g2 = fs.aggregate_growth(oi2, me, k=12)
    d2 = fs.releases_to_daily(
        [fs.Release(pd.Timestamp(a), pd.Timestamp(a), float(v)) for a, v in g2["growth"].dropna().items()],
        dates,
        stale_days=45,
    )
    assert (
        d[d.index < t].equals(d2[d2.index < t])
        and d.loc[t] != d2.loc[t]
        and d.loc[exec_day] != d2.loc[exec_day]
    )
    # 未来合约持仓 ±5% 噪声(t 之后):t 及以前的信号完全不变
    oi3 = oi.copy()
    fut = oi3.index > t
    oi3.loc[fut] = oi3.loc[fut] * (1 + rng.normal(0, 0.05, size=oi3.loc[fut].shape))
    g3 = fs.aggregate_growth(oi3, me, k=12)
    assert np.allclose(g["growth"][g.index <= t].dropna(), g3["growth"][g3.index <= t].dropna())


# ---------- 暴露拼装 ----------
def _cfg() -> object:
    from cta.config import load_config

    return load_config(Path("configs/strategy_v03.yaml"))


def test_blend_is_convex_and_candidate_off_leaves_baseline_unchanged() -> None:
    dates = _dates("2016-01-04", "2016-06-30")
    rng = np.random.default_rng(1)
    a = pd.DataFrame(rng.normal(size=(len(dates), 3)), index=dates, columns=["A", "B", "C"])
    b = pd.DataFrame(rng.normal(size=(len(dates), 3)), index=dates, columns=["A", "B", "C"])
    bl = fs.blend_exposure(a, b, 0.5)
    assert np.allclose(bl.to_numpy(), 0.5 * a.to_numpy() + 0.5 * b.to_numpy())
    assert (
        bl.abs().sum(axis=1) <= 0.5 * a.abs().sum(axis=1) + 0.5 * b.abs().sum(axis=1) + 1e-12
    ).all()  # 不偷杠杆
    assert fs.blend_exposure(a, b, 0.0).equals(a.fillna(0.0))  # 候选关闭 = 基线
    assert (fs.blend_exposure(a, b * 0.0, 0.5).abs().sum(axis=1) <= a.abs().sum(axis=1) * 0.5 + 1e-12).all()


def test_raw_then_buffer_is_deterministic() -> None:
    cfg = _cfg()
    dates = pd.bdate_range("2021-01-01", periods=250)
    rng = np.random.default_rng(2)
    adj = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (250, 2)), axis=0)), index=dates, columns=["A", "B"]
    )
    from cta.signals.core import realized_vol

    vol = realized_vol(adj, 40)
    comb = pd.DataFrame(0.5, index=dates, columns=["A", "B"])
    elig = pd.DataFrame(True, index=dates, columns=["A", "B"])
    r1 = fs.raw_exposure(comb, elig, vol, adj, cfg)  # type: ignore[arg-type]
    r2 = fs.raw_exposure(comb.copy(), elig.copy(), vol.copy(), adj.copy(), cfg)  # type: ignore[arg-type]
    assert r1.equals(r2)
    t1 = fs.apply_buffer(r1, cfg, dates[60], dates[-1])  # type: ignore[arg-type]
    t2 = fs.apply_buffer(r2, cfg, dates[60], dates[-1])  # type: ignore[arg-type]
    assert t1.equals(t2) and t1.index[0] == dates[60]


def test_predictive_regression_recovers_slope() -> None:
    rng = np.random.default_rng(3)
    x = pd.Series(
        rng.normal(size=120), index=pd.period_range("2016-01", periods=120, freq="M").to_timestamp("M")
    )
    y = 0.01 + 0.02 * x + rng.normal(0, 0.01, size=120)
    out = fs.predictive_regression(x, y)
    assert abs(out["beta"] - 0.02) < 0.005 and out["t"] > 5 and out["n"] == 120


# ---------- 真实数据 ----------
@needs_data
def test_static_baseline_reproduces_production_target_and_reference_equity() -> None:
    """raw_exposure → apply_buffer 走的是 compute_signals 尾部同一条路径:与生产目标暴露逐位相同;引擎权益与正式基线 D 臂逐位一致。"""
    import json

    from cta.backtest.engine import run_backtest
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals, summarize_result

    ref = Path("results/settle_baseline/v0.3_full_D_unified_official.json")
    if not ref.exists():
        pytest.skip("需要 results/settle_baseline(先跑 scripts/research/settle_baseline.py)")
    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    raw = fs.raw_exposure(sig.combined, sig.eligible, sig.vol, sig.adj_close, cfg)
    tgt = fs.apply_buffer(raw, cfg, pd.Timestamp("2016-01-04"), pd.Timestamp("2026-09-18"))
    off = sig.target.loc[tgt.index, tgt.columns]
    assert np.allclose(tgt.to_numpy(dtype=float), off.to_numpy(dtype=float), equal_nan=True)
    res = run_backtest(
        panels,
        tgt,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    st, _ = summarize_result(res, specs)
    want = json.loads(ref.read_text(encoding="utf-8"))["stats"]
    assert (
        abs(st["夏普(月频)"] - want["夏普(月频)"]) < 1e-9
        and abs(float(res.equity.iloc[-1]) - 3_000_000.0 - 6_461_935.82) < 1.0
    )
    # 候选关闭(权重 0)的混合 = 基线,逐位
    zero = raw * 0.0
    bl = fs.blend_exposure(raw, zero, 0.0)
    assert np.allclose(bl.to_numpy(dtype=float), raw.fillna(0.0).to_numpy(dtype=float))


@needs_data
def test_real_predictors_are_point_in_time() -> None:
    """持仓增长:截断到 T 的合约数据与全量数据在 ≤T 的每个月末给出相同的增长;PMI:每条目标日 ≤ 公布日且早于建仓日。"""
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments

    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    syms = list(cfg.universe.symbols)
    oi = fs.contract_open_interest(src, syms, specs)
    dates = pd.DatetimeIndex(oi.contracts.index)
    dates = dates[(dates >= pd.Timestamp("2016-01-04")) & (dates <= pd.Timestamp("2026-06-05"))]
    me = fs.month_end_dates(dates)
    g = fs.aggregate_growth(oi.notional, me)
    cut = pd.Timestamp("2021-12-31")
    trunc = oi.notional[oi.notional.index <= cut]
    g_t = fs.aggregate_growth(trunc, me[me <= cut])
    common = g_t.index
    assert np.allclose(
        g.loc[common, "growth"].to_numpy(dtype=float), g_t["growth"].to_numpy(dtype=float), equal_nan=True
    )
    # 缺失只出现在品种上市之前(SA 2019-12、SC 2018-03),上市后没有静默补 0 也没有空洞
    for sym in oi.contracts.columns:
        col = oi.contracts[sym]
        first = col.first_valid_index()
        assert first is not None and col.loc[first:].isna().sum() == 0 and (col.loc[first:] > 0).all()
    no = fs.load_macro(str(DATA / "macro_factors/制造业采购经理指数PMI_新订单.parquet"))
    fg = fs.load_macro(str(DATA / "macro_factors/制造业采购经理指数PMI_产成品库存.parquet"))
    rel = fs.pmi_ratio_releases(no, fg)
    assert len(rel) >= 120
    for r in rel:
        t = fs.effective_target_day(r.info_date, dates)
        if t is None:
            continue
        exec_day = dates[dates > r.info_date][0]
        # 统计局可在月末前几天公布(春节等:2022-01-30、2025-01-27),数据仍属该月;可得性只由公布日决定
        assert t <= r.info_date < exec_day and r.period_end <= r.info_date + pd.Timedelta(days=7)
