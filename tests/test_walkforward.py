"""季度 walk-forward 诊断(docs/quarterly_walkforward_prereg.md 第 7 节的六项测试):
排程与拼接(合成数据);截断/扰动后选择不变、只用 cutoff 以前数据、静态基线复现报告数字(真实数据,无数据时跳过)。"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.analysis import walkforward as wf

DATA = Path("data/ricecta/data")
needs_data = pytest.mark.skipif(not DATA.exists(), reason="需要本地米筐/交易所数据")


# ---------- 合成数据 ----------
def test_quarter_schedule_cutoff_strictly_before_trading_window() -> None:
    dates = pd.bdate_range("2021-06-01", "2022-12-31")
    qs = wf.quarter_schedule(
        dates, "2021Q4", "2022Q4", end_clip=pd.Timestamp("2022-11-15"), oos_start=pd.Timestamp("2022-01-04")
    )
    assert [q.quarter for q in qs] == ["2021Q4", "2022Q1", "2022Q2", "2022Q3", "2022Q4"]
    q1 = qs[1]
    assert (
        q1.cutoff == pd.Timestamp("2021-12-31")
        and q1.start == pd.Timestamp("2022-01-03")
        and q1.end == pd.Timestamp("2022-03-31")
    )
    assert all(q.cutoff < q.start for q in qs) and not qs[0].formal_oos and qs[1].formal_oos
    assert qs[-1].end == pd.Timestamp("2022-11-15")  # end_clip 截断最后一季
    assert wf.annual_cutoff(dates, "2022Q3") == pd.Timestamp("2021-12-31")


def _piece(q: wf.QuarterSpec, value: float, dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(value, index=dates, columns=["A", "B"])


def test_stitch_has_no_overlap_no_gap_and_freezes_within_quarter() -> None:
    dates = pd.bdate_range("2021-12-01", "2022-09-30")
    qs = wf.quarter_schedule(dates, "2022Q1", "2022Q3")
    pieces = [(q, _piece(q, float(i + 1), dates)) for i, q in enumerate(qs)]
    st = wf.stitch_quarters(pieces, dates)
    assert (
        len(st) == int(((dates >= qs[0].start) & (dates <= qs[-1].end)).sum())
        and st.loc[qs[0].start : qs[0].end].eq(1.0).all().all()
        and st.loc[qs[2].start, "A"] == 3.0
    )
    wf.assert_frozen(st, pieces)  # 不抛错
    bad = st.copy()
    bad.loc[qs[1].start, "A"] = 9.0
    with pytest.raises(ValueError, match="frozen"):
        wf.assert_frozen(bad, pieces)
    with pytest.raises(ValueError, match="overlap"):  # 两季区间重叠
        wf.stitch_quarters(
            [
                (qs[0], _piece(qs[0], 1.0, dates)),
                (dataclasses.replace(qs[1], start=qs[0].end), _piece(qs[1], 2.0, dates)),
            ],
            dates,
        )
    with pytest.raises(ValueError, match="gap"):  # 某季少一天
        short = _piece(qs[1], 2.0, dates).drop(index=qs[1].start)
        wf.stitch_quarters(
            [(qs[0], _piece(qs[0], 1.0, dates)), (qs[1], short), (qs[2], _piece(qs[2], 3.0, dates))], dates
        )


def test_select_44_rules_and_determinism() -> None:
    cands = ["f1", "f2", "f3", "f4", "f5"]
    tab = pd.DataFrame(
        {
            "sharpe_m": [0.9, 0.8, 0.7, 0.5, np.nan],
            "nw_t": [3.0, 2.5, 1.5, 2.2, 3.0],
            "corr_v01": [0.1, 0.2, 0.1, 0.7, 0.1],
            "n_years": [5, 5, 5, 5, 5],
            "pos_years": [5, 4, 5, 5, 5],
        },
        index=cands,
    )
    corr = pd.DataFrame(np.eye(5), index=cands, columns=cands)
    corr.loc["f2", "f1"] = corr.loc["f1", "f2"] = 0.9  # f2 与已选 f1 相关过高
    tab.attrs["corr"] = corr
    chosen = wf.select_44(tab, cands)
    assert chosen == ["f1"]  # f2 相关高、f3 t 不够、f4 与基线相关高、f5 夏普 NaN
    assert wf.select_44(tab, cands) == chosen  # 确定性
    tab2 = tab.copy()
    tab2.attrs["corr"] = pd.DataFrame(np.eye(5), index=cands, columns=cands)
    assert wf.select_44(tab2, cands) == ["f1", "f2"]


def test_targets_from_comb_is_deterministic() -> None:
    from cta.config import load_config

    cfg = load_config()
    dates = pd.bdate_range("2021-01-01", periods=300)
    rng = np.random.default_rng(0)
    adj = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (300, 2)), axis=0)), index=dates, columns=["A", "B"]
    )
    from cta.signals.core import realized_vol

    vol = realized_vol(adj, cfg.signals.vol_window)
    comb = pd.DataFrame(np.sign(rng.normal(size=(300, 2))), index=dates, columns=["A", "B"])
    elig = pd.DataFrame(True, index=dates, columns=["A", "B"])
    t1 = wf.targets_from_comb(comb, elig, vol, adj, cfg, dates[100], dates[-1])
    t2 = wf.targets_from_comb(comb.copy(), elig.copy(), vol.copy(), adj.copy(), cfg, dates[100], dates[-1])
    assert t1.equals(t2) and t1.index[0] == dates[100] and t1.index[-1] == dates[-1]


# ---------- 真实数据 ----------
@needs_data
def test_static_v03_baseline_reproduces_report_numbers() -> None:
    """静态 v0.3 经本模块的 目标暴露 → 引擎 路径,与正式基线(results/settle_baseline D 臂)逐位一致。"""
    from cta.backtest.engine import run_backtest
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals, summarize_result

    ref = Path("results/settle_baseline/v0.3_full_D_unified_official.json")
    if not ref.exists():
        pytest.skip("需要 results/settle_baseline(先跑 scripts/settle_baseline.py)")
    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    tgt = wf.targets_from_comb(
        sig.combined,
        sig.eligible,
        sig.vol,
        sig.adj_close,
        cfg,
        pd.Timestamp("2016-01-04"),
        pd.Timestamp("2026-09-18"),
    )
    off = sig.target.loc[tgt.index, tgt.columns]
    assert np.allclose(
        tgt.to_numpy(dtype=float), off.to_numpy(dtype=float), equal_nan=True
    )  # 尾部实现与 compute_signals 一致
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
    assert abs(st["夏普(月频)"] - want["夏普(月频)"]) < 1e-9 and abs(st["年化收益"] - want["年化收益"]) < 1e-9
    assert abs(float(res.equity.iloc[-1]) - 3_000_000.0 - 6_461_935.82) < 1.0


@needs_data
def test_quarter_selection_only_uses_data_up_to_cutoff() -> None:
    """2022Q1 模型(cutoff 2021-12-31):用截断到 cutoff 的面板、以及在 cutoff 之后注入扰动的数据,训练统计与选择完全不变。"""
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.factors.base import FactorInputs
    from cta.factors.library import ALL_FACTORS
    from cta.instruments.specs import load_instruments
    from cta.pipeline import build_panels
    from cta.signals.core import combine

    cfg = load_config()
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    cutoff, hist = pd.Timestamp("2021-12-31"), pd.Timestamp("2016-01-04")
    cands = [f.name for f in ALL_FACTORS if not f.reference]

    def table_from(panels: dict) -> pd.DataFrame:  # type: ignore[type-arg]
        x = FactorInputs.from_panels(panels, cfg)
        sigs = {f.name: f.compute(x) for f in ALL_FACTORS}
        return wf.training_table(
            sigs,
            cands,
            combine({"tsmom": sigs["tsmom"], "carry": sigs["carry"]}),
            x,
            specs,
            cfg,
            hist,
            cutoff,
        )

    full = build_panels(src, cfg, specs)
    trunc = build_panels(src, cfg, specs, end=cutoff)
    assert all(
        pd.Timestamp(p.frame.index.max()) == cutoff for p in trunc.values()
    )  # 只用 cutoff 当日及以前的数据
    rec = src.receipts()
    assert pd.DatetimeIndex(rec.index).min() <= pd.Timestamp("2016-06-30")  # 仓单(date × 品种)自 2016 起可得
    t_full, t_trunc = table_from(full), table_from(trunc)
    assert wf.select_44(t_full, cands) == wf.select_44(t_trunc, cands)
    cols = ["sharpe_m", "nw_t", "corr_v01", "n_years", "pos_years"]
    assert np.allclose(
        t_full[cols].to_numpy(dtype=float), t_trunc[cols].to_numpy(dtype=float), equal_nan=True, atol=1e-9
    )
    # 在 cutoff 之后注入扰动(未来价格 ×(1 ± 5% 噪声)):结果仍不变
    x = FactorInputs.from_panels(full, cfg)
    rng = np.random.default_rng(1)
    adj = x.adj_close.copy()
    fut = adj.index > cutoff
    adj.loc[fut] = adj.loc[fut] * (1 + rng.normal(0, 0.05, size=adj.loc[fut].shape))
    xp = dataclasses.replace(x, adj_close=adj)
    sigs_p = {f.name: f.compute(xp) for f in ALL_FACTORS}
    t_pert = wf.training_table(
        sigs_p,
        cands,
        combine({"tsmom": sigs_p["tsmom"], "carry": sigs_p["carry"]}),
        xp,
        specs,
        cfg,
        hist,
        cutoff,
    )
    assert wf.select_44(t_pert, cands) == wf.select_44(t_full, cands)
    assert np.allclose(
        t_full[cols].to_numpy(dtype=float), t_pert[cols].to_numpy(dtype=float), equal_nan=True, atol=1e-9
    )
