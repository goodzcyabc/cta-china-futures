"""真实数据上的因子无前视测试:截断未来数据后,每个因子在截断日前的取值逐品种一致。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

DATA = Path("data/ricecta/data")
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="需要米筐导出数据")


def test_factors_identical_when_future_removed() -> None:
    from cta.config import load_config
    from cta.data.source import RicequantParquetSource
    from cta.factors.base import FactorInputs
    from cta.factors.library import ALL_FACTORS
    from cta.instruments.specs import load_instruments
    from cta.pipeline import build_panels

    cfg = load_config()
    specs = load_instruments()
    src = RicequantParquetSource(DATA)
    cut = pd.Timestamp("2021-06-30")
    full = FactorInputs.from_panels(build_panels(src, cfg, specs), cfg)
    trunc = FactorInputs.from_panels(build_panels(src, cfg, specs, end=cut), cfg)
    for spec in ALL_FACTORS:
        a = spec.compute(full)
        b = spec.compute(trunc)
        common = b.index[b.index <= cut][-300:]  # 截断前最后 300 个交易日
        cols = [c for c in b.columns if c in a.columns]
        pd.testing.assert_frame_equal(
            a.loc[common, cols], b.loc[common, cols], check_exact=False, rtol=1e-6, atol=1e-9, obj=spec.name
        )
