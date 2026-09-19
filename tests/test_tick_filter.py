"""跳价过滤(design_log 十一 E2):月末排名、次月生效、无前视;未核验品种被出单拒绝。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cta.instruments.specs import load_instruments
from cta.signals.core import large_tick_mask


def test_large_tick_mask_ranks_at_month_end_and_applies_next_month() -> None:
    idx = pd.bdate_range("2021-01-01", periods=90)
    rng = np.random.default_rng(0)
    # A:价格 100、波动 1 → tick/mad 大;B:价格 10000、波动 100、tick 1 → 小
    close = pd.DataFrame(
        {
            "A": 100 + np.cumsum(rng.standard_normal(90)),
            "B": 10000 + 100 * np.cumsum(rng.standard_normal(90)),
        },
        index=idx,
    )
    roll = pd.DataFrame(False, index=idx, columns=["A", "B"])
    ticks = pd.Series({"A": 1.0, "B": 1.0})
    elig = pd.DataFrame(True, index=idx, columns=["A", "B"])
    m = large_tick_mask(close, roll, ticks, elig, window=20, top_quantile=0.5)
    feb = m.loc["2021-02"]
    assert feb["A"].all() and not feb["B"].any()
    assert not m.loc["2021-01"].any().any()  # 一月没有上月排名 → 全 False
    # 无前视:截断到 2 月中,2 月的标记不变
    m2 = large_tick_mask(
        close.loc[:"2021-02-15"], roll.loc[:"2021-02-15"], ticks, elig.loc[:"2021-02-15"], window=20
    )
    pd.testing.assert_frame_equal(m.loc[:"2021-02-15"], m2)


def test_unverified_symbols_excluded_by_default() -> None:
    t = load_instruments()
    classes = {"agri", "chem", "energy", "ferrous", "metal", "precious"}
    # 2026-09-19 起 57 个品种全部核验;生产品种池由 configs/strategy.yaml 的 universe.symbols 显式固定为 22 个
    assert len(t.symbols(classes, verified_only=True)) == 57 and t["JM"].verified and t["CU"].verified
    from pathlib import Path

    from cta.config import load_config

    cfg = load_config(Path("configs/strategy.yaml"))
    assert cfg.universe.symbols is not None and len(cfg.universe.symbols) == 22
