"""板块因子菜单与因子加权(design_log 十二):菜单屏蔽、品种覆盖、逆波动率权重的因果性与归一。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cta.signals.core import combine, combine_tv, inverse_vol_weights, menu_masks


def test_menu_masks_sector_and_symbol_override() -> None:
    m = menu_masks(
        ["tsmom", "carry", "receipts_level"],
        ["AU", "CU", "JD", "C"],
        {"AU": "precious", "CU": "metal", "JD": "agri", "C": "agri"},
        {"precious": ["tsmom"], "metal": ["tsmom", "carry", "receipts_level"]},
        {"JD": ["tsmom"]},
    )
    assert m["tsmom"].all()
    assert (
        not m["carry"]["AU"] and m["carry"]["CU"] and not m["carry"]["JD"] and m["carry"]["C"]
    )  # agri 未列出 = 全部允许
    assert not m["receipts_level"]["AU"] and not m["receipts_level"]["JD"]


def test_masked_factor_leaves_denominator() -> None:
    idx = pd.bdate_range("2021-01-01", periods=5)
    ts = pd.DataFrame(0.5, index=idx, columns=["AU", "CU"])
    cr = pd.DataFrame(-0.5, index=idx, columns=["AU", "CU"])
    cr["AU"] = np.nan  # 贵金属不用 carry
    comb = combine({"tsmom": ts, "carry": cr})
    assert np.allclose(comb["AU"], 0.5 * np.sqrt(0.5)) and (comb["CU"] == 0.0).all()  # 单因子品种 × √(1/2)


def test_inverse_vol_weights_causal_and_normalised() -> None:
    idx = pd.bdate_range("2019-01-01", periods=400)
    rng = np.random.default_rng(0)
    a = pd.DataFrame(0.2 * rng.standard_normal((400, 6)), index=idx)  # 低离散
    b = pd.DataFrame(0.6 * rng.standard_normal((400, 6)), index=idx)  # 高离散
    w = inverse_vol_weights({"a": a, "b": b}, window=100, min_periods=50)
    tot = w["a"] + w["b"]
    assert np.allclose(tot.dropna(), 1.0)
    assert (w["a"].dropna() > w["b"].dropna()).all()  # 离散小的因子权重大 → 等方差贡献
    # 因果:截断数据后,截断日前的权重不变
    w2 = inverse_vol_weights({"a": a.iloc[:300], "b": b.iloc[:300]}, window=100, min_periods=50)
    pd.testing.assert_series_equal(w["a"].iloc[:300], w2["a"])
    comb = combine_tv({"a": a, "b": b}, w)
    assert comb.abs().max().max() <= 1.0 + 1e-9 and comb.iloc[:50].isna().all().all()  # 权重未定义时不合成


def test_compute_signals_applies_menu_on_synthetic_panels() -> None:
    """走完整的 compute_signals 路径:贵金属只留 tsmom → 其合成信号等于 tsmom;有色三因子都在。"""
    from cta.config import load_config
    from cta.continuous.roll import PANEL_COLS, SymbolPanel
    from cta.pipeline import compute_signals

    idx = pd.bdate_range("2019-01-01", periods=700)
    rng = np.random.default_rng(1)

    def panel(sym: str, mult: float, drift: float) -> SymbolPanel:
        px = 100 * np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(len(idx))))
        f = pd.DataFrame(index=idx)
        f["contract"] = f"{sym}2101"
        f["open"] = f["high"] = f["low"] = f["close"] = f["settle"] = px
        f["prev_settle"] = f["settle"].shift(1)
        f["limit_up"], f["limit_down"] = px * 1.1, px * 0.9
        f["volume"], f["open_interest"] = 50000.0, 100000.0
        f["multiplier"], f["margin_rate"], f["maturity"] = mult, 0.1, pd.Timestamp("2021-01-15")
        f["roll"], f["roll_from"], f["roll_from_open"] = False, None, np.nan
        f["adj_close"] = px
        f["next_contract"], f["next_close"], f["days_to_next"] = f"{sym}2102", px * 1.02, 30.0
        f["oi_total"], f["volume_total"], f["tick"] = 200000.0, 60000.0, 1.0
        f["sched_next"] = f["contract"]
        return SymbolPanel(sym, f[PANEL_COLS])

    panels = {"AU": panel("AU", 1000.0, 0.0008), "CU": panel("CU", 5.0, -0.0005), "C": panel("C", 10.0, 0.0)}
    cfg = load_config()
    cfg = cfg.model_copy(
        update={
            "signals": cfg.signals.model_copy(
                update={"sector_menu": {"precious": ["tsmom"]}, "symbol_menu": {"C": ["tsmom"]}}
            )
        }
    )
    s = compute_signals(panels, cfg)
    tail = s.combined.iloc[-50:]
    k = np.sqrt(0.5)  # 两因子配置里只剩一个因子 → × √(1/2)
    assert np.allclose(tail["AU"].to_numpy(), k * s.tsmom.iloc[-50:]["AU"].to_numpy())  # 贵金属:仅 tsmom
    assert np.allclose(tail["C"].to_numpy(), k * s.tsmom.iloc[-50:]["C"].to_numpy())  # 品种覆盖:仅 tsmom
    assert not np.allclose(
        tail["CU"].to_numpy(), s.tsmom.iloc[-50:]["CU"].to_numpy()
    )  # 有色:tsmom+carry 平均
    s_iv = compute_signals(
        panels,
        cfg.model_copy(
            update={"signals": cfg.signals.model_copy(update={"factor_weighting": "inverse_vol"})}
        ),
    )
    assert s_iv.factor_weights is not None and set(s_iv.factor_weights.columns) == {"tsmom", "carry"}


def test_reg_overlay_mask_window_and_filters() -> None:
    from cta.signals.core import reg_overlay_mask

    idx = pd.bdate_range("2021-01-01", periods=60)
    ev = pd.DataFrame(
        {
            "event_date": ["2021-01-11", "2021-01-11", "2021-02-01", "2021-02-01"],
            "symbol": ["CU", "AL", "CU", "ZZ"],
            "param": ["margin", "margin", "fee", "margin"],
            "direction": ["up", "up", "down", "up"],
            "reason": ["derived", "holiday", "derived", "derived"],
        }
    )
    m = reg_overlay_mask(ev, idx, ["CU", "AL"], window=5, scale=0.5)
    d = pd.Timestamp("2021-01-11")
    i = idx.get_loc(d)
    assert m.loc[d, "CU"] == 1.0  # 事件日当天不生效(收盘后才可见)
    assert (m.iloc[i + 1 : i + 6]["CU"] == 0.5).all() and m.iloc[i + 6]["CU"] == 1.0
    assert (m["AL"] == 1.0).all()  # 节假日事件不算
    assert (m.loc["2021-02":, "CU"] == 1.0).all()  # 下调不算;未知品种忽略
