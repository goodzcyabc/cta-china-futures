"""多源基本面合成因子 MSF(docs/msf_prereg.md 第 4 节):接入不改变现有配置、缺数据时报错、成分点时、合成归一。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.factors import composite as cp

DATA = Path("data/ricecta/data")
needs_data = pytest.mark.skipif(not DATA.exists(), reason="需要本地米筐/交易所数据")


def _bday_next(d: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(d) + pd.offsets.BDay(0)


def test_completed_month_ends_drops_partial_last_month() -> None:
    d = pd.bdate_range("2024-01-02", "2024-03-14")
    me = cp.completed_month_ends(d, next_session=_bday_next)
    assert list(me) == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29")]
    d2 = pd.bdate_range("2024-01-02", "2024-03-29")
    assert cp.completed_month_ends(d2, next_session=_bday_next)[-1] == pd.Timestamp("2024-03-29")


def test_completed_month_ends_pre_holiday_month_end_is_complete() -> None:
    """2020-01-23 之后春节休市到 2020-02-02:按交易所日历这是 1 月最后一个交易日,实盘 as-of 当天应算作完整月。"""
    hol = pd.date_range("2020-01-24", "2020-01-31")

    def nxt(d: pd.Timestamp) -> pd.Timestamp:
        x = pd.Timestamp(d) + pd.offsets.BDay(0)
        while x in hol:
            x = x + pd.offsets.BDay(1)
        return pd.Timestamp(x)

    d = pd.bdate_range("2019-12-02", "2020-01-23")
    assert cp.completed_month_ends(d, next_session=nxt)[-1] == pd.Timestamp("2020-01-23")
    assert cp.completed_month_ends(d, next_session=_bday_next)[-1] == pd.Timestamp("2019-12-31")
    if Path("data/exchanges").exists():  # 真实交易所日历
        assert cp.completed_month_ends(d)[-1] == pd.Timestamp("2020-01-23")


def test_release_audit_weekend_publication_targets_next_session() -> None:
    from cta.analysis import fundamental_signals as fs

    dates = pd.bdate_range("2024-03-25", "2024-04-05")
    rel = [
        fs.Release(pd.Timestamp("2024-03-27"), pd.Timestamp("2024-02-29"), 1.0),  # 周三
        fs.Release(pd.Timestamp("2024-03-31"), pd.Timestamp("2024-03-31"), 0.5),  # 周日
    ]
    a = cp.release_audit(rel, dates)
    assert list(a["target_day"]) == [pd.Timestamp("2024-03-27"), pd.Timestamp("2024-04-01")]
    assert cp.release_timing_ok(a)
    daily = fs.releases_to_daily(rel, dates, target_rule="on_or_after")
    assert daily.loc["2024-03-29"] == 1.0 and daily.loc["2024-04-01"] == 0.5
    legacy = fs.releases_to_daily(rel, dates)  # 试验 51 的旧规则保持不变(周日公布记到周五)
    assert legacy.loc["2024-03-29"] == 0.5


def test_combine_msf_equal_weight_sqrt_n() -> None:
    idx = pd.bdate_range("2024-01-02", periods=3)
    comps = {k: pd.DataFrame(np.nan, index=idx, columns=["A", "B"]) for k in cp.COMPONENTS}
    comps["R"].loc[:, "A"] = 0.4
    comps["S"].loc[:, "A"] = 0.2
    out = cp.combine_msf(comps)
    assert out["A"].iloc[0] == pytest.approx(0.3 * np.sqrt(2 / 12))
    assert out["B"].isna().all()


def _write_macro(tmp: Path, name: str, rows: list[tuple[str, str, float]]) -> None:
    df = pd.DataFrame(
        {
            "factor": name,
            "info_date": [pd.Timestamp(r[0]) for r in rows],
            "start_date": [pd.Timestamp(r[1]) - pd.offsets.MonthBegin(1) for r in rows],
            "end_date": [pd.Timestamp(r[1]) for r in rows],
            "value": [r[2] for r in rows],
            "rice_create_tm": pd.Timestamp("2026-01-01"),
        }
    ).set_index(["factor", "info_date"])
    df.to_parquet(tmp / name)


def test_component_p_definition_and_point_in_time(tmp_path: Path) -> None:
    months = pd.date_range("2016-01-31", periods=60, freq="ME")
    rng = np.random.default_rng(0)
    ppi = rng.normal(0, 3, 60)
    ppirm = rng.normal(0, 3, 60)
    info = [m + pd.Timedelta(days=10) for m in months]
    _write_macro(
        tmp_path,
        cp.PPI_FILE,
        [(str(i.date()), str(m.date()), float(v)) for i, m, v in zip(info, months, ppi)],
    )
    _write_macro(
        tmp_path,
        cp.PPIRM_FILE,
        [(str(i.date()), str(m.date()), float(v)) for i, m, v in zip(info, months, ppirm)],
    )
    dates = pd.bdate_range("2016-01-04", "2020-12-31")
    sig = cp.component_p(dates, ["CU"], ["CU", "C"], macro_dir=tmp_path)
    assert sig["C"].isna().all()
    s = sig["CU"]
    # 公布日之前看不到:第 k 次公布的值从公布日当天或之后第一个交易日起生效(周末公布 → 下周一)
    first = s.first_valid_index()
    assert first is not None and first >= info[3 + 23]  # 3 个月变化 + 24 个观测
    # 截断:只给 2018 年底之前公布的数据,2018 年底之前信号不变
    cut = pd.Timestamp("2018-12-31")
    keep = [k for k, i in enumerate(info) if i <= cut]
    tmp2 = tmp_path / "trunc"
    tmp2.mkdir()
    _write_macro(
        tmp2, cp.PPI_FILE, [(str(info[k].date()), str(months[k].date()), float(ppi[k])) for k in keep]
    )
    _write_macro(
        tmp2, cp.PPIRM_FILE, [(str(info[k].date()), str(months[k].date()), float(ppirm[k])) for k in keep]
    )
    s2 = cp.component_p(dates, ["CU"], ["CU", "C"], macro_dir=tmp2)["CU"]
    m = s.index <= cut
    assert np.allclose(s[m].to_numpy(), s2[m].to_numpy(), equal_nan=True)
    # 周五截断、周末公布:截断日历下的信号与完整日历相同(公布前不可用)
    sat = next(i for i in info[30:] if i.weekday() == 5)
    fri = sat - pd.Timedelta(days=1)
    s3 = cp.component_p(dates[dates <= fri], ["CU"], ["CU", "C"], macro_dir=tmp_path)["CU"]
    assert np.allclose(s3.to_numpy(), s.reindex(s3.index).to_numpy(), equal_nan=True)
    # 方向:剪刀差 3 个月变化为正且偏大 → 信号为正
    g = ppi - ppirm
    chg = g[3:] - g[:-3]
    k_hi = int(np.argmax(chg[30:])) + 30 + 3
    t = pd.Timestamp(info[k_hi])
    after = s[s.index >= t].dropna()
    assert len(after) and after.iloc[0] > 0


@needs_data
def test_existing_configs_unchanged_and_missing_extra_raises() -> None:
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals

    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    cfg3 = load_config(Path("configs/strategy_v03.yaml"))
    panels = build_panels(src, cfg3, specs)
    base = compute_signals(
        panels, cfg3, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg3)
    )
    junk = pd.DataFrame(0.7, index=base.adj_close.index, columns=base.adj_close.columns)
    again = compute_signals(
        panels,
        cfg3,
        receipts=_receipts_of(src),
        specs=specs,
        reg_events=_reg_events_of(src, cfg3),
        extra_factors={"msf": junk},
    )
    assert base.target.equals(again.target) and base.combined.equals(again.combined) and again.extra == {}
    cfg6 = load_config(Path("configs/strategy_v06_msf.yaml"))
    with pytest.raises(ValueError, match="msf"):
        compute_signals(
            panels, cfg6, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg6)
        )
    six = compute_signals(
        panels,
        cfg6,
        receipts=_receipts_of(src),
        specs=specs,
        reg_events=_reg_events_of(src, cfg6),
        extra_factors={"msf": junk},
    )
    assert set(six.extra) == {"msf"} and not six.target.equals(base.target)


@needs_data
def test_components_a_b_p_truncation_invariance() -> None:
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments
    from cta.pipeline import _wide, build_panels

    specs = load_instruments()
    src = default_stitched(DATA, official_settle=True)
    cfg = load_config(Path("configs/strategy_v06_msf.yaml"))
    panels = build_panels(src, cfg, specs)
    adj = _wide(panels, "adj_close")
    dates = pd.DatetimeIndex(adj.index)
    cols = [str(c) for c in adj.columns]
    ind = [s for s in cols if specs[s].asset_class in cp.INDUSTRIAL_CLASSES]
    fns = {
        "A": lambda d: cp.component_a(src, specs, d, cols),
        "B": lambda d: cp.component_b(d, ind, cols),
        "P": lambda d: cp.component_p(d, ind, cols),
    }
    full = {k: fn(dates) for k, fn in fns.items()}
    # 周三公布日、周日 PMI 之前的周五、春节前月末、周六 PPI 之前的周五
    for cut in ("2021-06-30", "2019-06-28", "2020-01-23", "2024-03-08"):
        dt = dates[dates <= pd.Timestamp(cut)]
        for k, fn in fns.items():
            a = full[k].reindex(dt).to_numpy(dtype=float)
            b = fn(dt).to_numpy(dtype=float)
            assert np.allclose(a, b, equal_nan=True), (k, cut)
