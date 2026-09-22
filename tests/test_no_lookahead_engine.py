"""引擎级截断不变(design_log 14.3 b):用截至 T 的数据跑完整流程(面板 → 信号 → 引擎),
在 ≤ T−1 的每一天,权益、持仓、成交与全量数据的结果逐项相等。T 日成交依赖 T 日开盘价,故比到 T−1。真实数据,无数据则跳过。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

DATA = Path("data/ricecta/data")
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="需要米筐导出与交易所直连数据")


def _run(cfg, specs, src, end):  # type: ignore[no-untyped-def]
    from cta.backtest.engine import run_backtest
    from cta.pipeline import _receipts_of, build_panels, compute_signals

    panels = build_panels(src, cfg, specs, end=end)
    rec = _receipts_of(src)
    if rec is not None and end is not None:
        rec = rec[rec.index <= end]
    sig = compute_signals(panels, cfg, receipts=rec, specs=specs)
    idx = sig.target.index
    tgt = sig.target.loc[
        (idx >= pd.Timestamp(cfg.backtest.start)) & (idx <= (end or pd.Timestamp(cfg.backtest.end)))
    ]
    return run_backtest(
        panels,
        tgt,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )


def test_engine_path_identical_when_future_removed() -> None:
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.instruments.specs import load_instruments

    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA)
    cut = pd.Timestamp("2025-03-14")
    full = _run(cfg, specs, src, pd.Timestamp("2025-09-30"))
    trunc = _run(cfg, specs, src, cut)
    upto = cut - pd.Timedelta(days=1)
    e_full, e_trunc = full.equity.loc[:upto], trunc.equity.loc[:upto]
    assert len(e_trunc) > 200 and len(e_full) == len(e_trunc)
    assert np.allclose(e_full.to_numpy(), e_trunc.to_numpy(), rtol=1e-9, atol=1e-6), (
        "权益路径在截断日前不一致 → 存在前视"
    )
    p_full, p_trunc = full.positions.loc[:upto], trunc.positions.loc[:upto]
    pd.testing.assert_frame_equal(p_full, p_trunc[p_full.columns], check_exact=True)
    t_full = full.trades[pd.to_datetime(full.trades["date"]) <= upto].reset_index(drop=True)
    t_trunc = trunc.trades[pd.to_datetime(trunc.trades["date"]) <= upto].reset_index(drop=True)
    pd.testing.assert_frame_equal(t_full, t_trunc, check_exact=False, rtol=1e-9)
