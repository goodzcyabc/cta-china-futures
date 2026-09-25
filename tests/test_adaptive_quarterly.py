"""季度自适应 v1(预注册第 9/12 节要求的测试):权重约束与确定性、只用 cutoff 以前的数据、季内冻结与拼接、
静态 v0.3 逐位复现、训练状态不泄漏、引擎连续运行且成本全计入(真实数据部分无数据时跳过)。"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.analysis import adaptive_quarterly as aq
from cta.analysis import walkforward as wf

DATA = Path("data/ricecta/data")
needs_data = pytest.mark.skipif(not DATA.exists(), reason="需要本地米筐/交易所数据")


def _returns(
    n: int = 1500, seed: int = 0, means: tuple[float, float, float] = (0.0004, 0.0006, 0.0005)
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2016-01-04", periods=n)
    x = rng.normal(0, 0.006, size=(n, 3)) + np.array(means)
    return pd.DataFrame(x, index=d, columns=list(aq.FACTORS))


def test_weights_satisfy_constraints_and_edge_cases() -> None:
    lo = aq.KAPPA / 3
    for sh in (
        {"tsmom": 1.0, "carry": 1.5, "receipts_level": 1.2},
        {"tsmom": 2.0, "carry": -1.0, "receipts_level": -0.5},
        {"tsmom": -1.0, "carry": -2.0, "receipts_level": -0.1},
        {"tsmom": 5.0, "carry": 0.1, "receipts_level": 0.1},
    ):
        raw, shr, fin = aq.weights_from_scores(sh)
        aq.check_weights(fin)
        assert abs(sum(fin.values()) - 1) < 1e-12 and all(
            lo - 1e-12 <= v <= aq.W_MAX + 1e-12 for v in fin.values()
        )
    _, _, fin = aq.weights_from_scores({"tsmom": -1.0, "carry": -2.0, "receipts_level": -0.1})
    assert all(abs(v - 1 / 3) < 1e-12 for v in fin.values())  # 全部为负 → 等权
    _, _, fin = aq.weights_from_scores({"tsmom": 2.0, "carry": -1.0, "receipts_level": -0.5})
    assert (
        fin["tsmom"] == pytest.approx(0.5)
        and fin["carry"] == pytest.approx(0.25)
        and fin["receipts_level"] == pytest.approx(0.25)
    )  # 0.6 撞上限 → 再分配
    with pytest.raises(ValueError):
        aq.check_weights({"tsmom": 0.7, "carry": 0.2, "receipts_level": 0.1})


def test_cap_redistributes_proportionally() -> None:
    w = aq.cap_and_renormalize({"a": 0.8, "b": 0.15, "c": 0.05}, 0.5)
    assert (
        w["a"] == pytest.approx(0.5)
        and w["b"] == pytest.approx(0.15 + 0.3 * 0.75)
        and w["c"] == pytest.approx(0.05 + 0.3 * 0.25)
    )


def test_ewma_and_rolling_use_only_data_up_to_cutoff_and_are_deterministic() -> None:
    r = _returns()
    cut = pd.Timestamp("2021-12-31")
    a = aq.vintage_weights(r, cut, "M1")
    b = aq.vintage_weights(r.copy(), cut, "M1")
    assert a == b  # 确定性
    poisoned = r.copy()
    poisoned.loc[poisoned.index > cut] = 5.0  # cutoff 之后注入极端值
    c = aq.vintage_weights(poisoned, cut, "M1")
    assert c.w_final == a.w_final and c.sharpe == a.sharpe  # 未来数据不影响
    assert aq.vintage_weights(r[r.index <= cut], cut, "M1").w_final == a.w_final  # 截断等价
    for m in ("A1", "A2"):
        assert aq.vintage_weights(poisoned, cut, m).w_final == aq.vintage_weights(r, cut, m).w_final
    lam = aq.ewma_lambda()
    n = a.n_obs
    n_eff_exact = (1 + lam) / (1 - lam) * (1 - lam**n) ** 2 / (1 - lam ** (2 * n))  # 有限样本的 (Σw)²/Σw²
    assert (
        0.997 < lam < 0.9975
        and abs(a.n_eff - n_eff_exact) < 1e-6
        and 0.9 < a.n_eff / ((1 + lam) / (1 - lam)) < 1.0
    )  # 渐近 ≈ 701
    a1 = aq.vintage_weights(r, cut, "A1")
    assert a1.n_obs == aq.WINDOW_A1 and abs(a1.n_eff - aq.WINDOW_A1) < 1e-9


def test_mv_projection_is_nonnegative_and_reduces_to_mu_under_identity() -> None:
    mu = {"tsmom": 0.10, "carry": -0.05, "receipts_level": 0.05}
    vol = {"tsmom": 0.1, "carry": 0.1, "receipts_level": 0.1}
    w = aq.mv_raw_weights(
        mu, vol, {"tsmom~carry": 0.0, "tsmom~receipts_level": 0.0, "carry~receipts_level": 0.0}
    )
    assert (
        w["carry"] == 0.0
        and w["tsmom"] == pytest.approx(2 / 3)
        and w["receipts_level"] == pytest.approx(1 / 3)
    )
    w2 = aq.mv_raw_weights({k: -1.0 for k in mu}, vol, {})
    assert all(abs(v - 1 / 3) < 1e-12 for v in w2.values())


def test_weights_frozen_within_quarter_and_stitch_complete() -> None:
    from cta.signals.core import combine

    dates = pd.bdate_range("2021-12-01", "2022-09-30")
    qs = wf.quarter_schedule(dates, "2022Q1", "2022Q3")
    rng = np.random.default_rng(3)
    parts = {
        f: pd.DataFrame(rng.normal(size=(len(dates), 2)), index=dates, columns=["A", "B"]) for f in aq.FACTORS
    }
    ws = [
        {"tsmom": 0.5, "carry": 0.2, "receipts_level": 0.3},
        {"tsmom": 0.2, "carry": 0.3, "receipts_level": 0.5},
        {"tsmom": 1 / 3, "carry": 1 / 3, "receipts_level": 1 / 3},
    ]
    pieces = [(q, combine(parts, w)) for q, w in zip(qs, ws)]
    st = wf.stitch_quarters(pieces, dates)
    wf.assert_frozen(st, pieces)
    assert len(st) == int(((dates >= qs[0].start) & (dates <= qs[-1].end)).sum())
    # 季内任一天的合成值等于用该季冻结权重重新合成的值
    d = qs[1].start + pd.Timedelta(days=20)
    d = dates[dates >= d][0]
    assert np.allclose(st.loc[d].to_numpy(), combine(parts, ws[1]).loc[d].to_numpy(), equal_nan=True)


# ---------- 真实数据 ----------
@needs_data
def test_equal_weights_reproduce_static_v03_and_engine_runs_once_with_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cta.analysis import adaptive_quarterly as _aq  # noqa: F401
    from cta.backtest import engine as eng
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals
    from cta.signals.core import combine

    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    parts = {"tsmom": sig.tsmom, "carry": sig.carry, "receipts_level": sig.receipts_level}
    dates = pd.DatetimeIndex(sig.adj_close.index)
    qs = wf.quarter_schedule(dates, "2020Q1", "2026Q2", end_clip=pd.Timestamp("2026-06-05"))
    eq_w = {f: 1 / 3 for f in aq.FACTORS}
    comb_eq = combine(parts, eq_w)
    hist, last = pd.Timestamp("2016-01-04"), pd.Timestamp(dates.max())
    tgt_full = wf.targets_from_comb(comb_eq, sig.eligible, sig.vol, sig.adj_close, cfg, hist, last)
    off = sig.target.loc[tgt_full.index, tgt_full.columns]
    assert np.allclose(
        tgt_full.to_numpy(dtype=float), off.to_numpy(dtype=float), equal_nan=True
    )  # 等权 ≡ 静态 v0.3(全历史)
    pieces = [(q, comb_eq) for q in qs]
    st = wf.stitch_quarters(pieces, dates)
    assert np.allclose(
        st.to_numpy(dtype=float), comb_eq.loc[st.index, st.columns].to_numpy(dtype=float), equal_nan=True
    )
    tgt = wf.targets_from_comb(st, sig.eligible, sig.vol, sig.adj_close, cfg, qs[0].start, qs[-1].end)
    calls: list[int] = []
    real = eng.run_backtest

    def spy(*a: object, **k: object) -> object:
        calls.append(1)
        return real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(eng, "run_backtest", spy)
    res = eng.run_backtest(
        panels,
        tgt,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    assert len(calls) == 1  # 引擎只跑一次:季度边界不重置
    assert (
        res.equity.index[0] == qs[0].start
        and res.equity.index[-1] == qs[-1].end
        and len(res.equity) == len(tgt)
    )
    assert (
        abs(float(res.trades["fee"].sum()) - float(res.costs.sum())) < 1e-6 and float(res.slippage.sum()) > 0
    )  # 成本全计入
    ref = pd.read_csv("results/quarterly_walkforward/equity_B_S3.csv", index_col=0, parse_dates=True).iloc[
        :, 0
    ]
    assert np.allclose(
        res.equity.to_numpy(dtype=float), ref.reindex(res.equity.index).to_numpy(dtype=float)
    )  # 与已有静态 v0.3 臂逐位一致


@needs_data
def test_2022q1_weights_unchanged_when_future_truncated_or_perturbed() -> None:
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.factors.base import FactorInputs
    from cta.factors.evaluate import evaluate_factor
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals

    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    cut, hist = pd.Timestamp("2021-12-31"), pd.Timestamp("2016-01-04")

    def sleeve_returns(panels: dict) -> pd.DataFrame:  # type: ignore[type-arg]
        sig = compute_signals(
            panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
        )
        x = FactorInputs.from_panels(panels, cfg)
        end = pd.Timestamp(sig.adj_close.index.max())
        parts = {"tsmom": sig.tsmom, "carry": sig.carry, "receipts_level": sig.receipts_level}
        return pd.DataFrame(
            {k: evaluate_factor(k, s, x, specs, cfg, hist, end).net for k, s in parts.items()}
        )

    full = build_panels(src, cfg, specs)
    trunc = build_panels(src, cfg, specs, end=cut)
    assert all(pd.Timestamp(p.frame.index.max()) == cut for p in trunc.values())
    r_full, r_trunc = sleeve_returns(full), sleeve_returns(trunc)
    for m in aq.METHODS:
        a, b = aq.vintage_weights(r_full, cut, m), aq.vintage_weights(r_trunc, cut, m)
        assert all(abs(a.w_final[f] - b.w_final[f]) < 1e-9 for f in aq.FACTORS), (m, a.w_final, b.w_final)
        assert all(abs(a.sharpe[f] - b.sharpe[f]) < 1e-9 for f in aq.FACTORS)
    # cutoff 之后的 sleeve 收益注入噪声:权重不变
    rng = np.random.default_rng(7)
    pert = r_full.copy()
    fut = pert.index > cut
    pert.loc[fut] = pert.loc[fut] + rng.normal(0, 0.05, size=pert.loc[fut].shape)
    for m in aq.METHODS:
        assert aq.vintage_weights(pert, cut, m).w_final == aq.vintage_weights(r_full, cut, m).w_final
    w = dataclasses.asdict(aq.vintage_weights(r_full, cut, "M1"))
    assert min(w["w_final"].values()) >= 0.2 - 1e-9 and max(w["w_final"].values()) <= 0.5 + 1e-9
