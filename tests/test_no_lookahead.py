"""无前视检验(依赖真实数据,缺数据时跳过):
把数据截止到 T 日重新构建面板与信号,T 日的目标暴露必须与用全量数据算出的 T 日目标逐品种一致。"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.config import DataCfg, load_config
from cta.data.source import RicequantParquetSource
from cta.instruments.specs import load_instruments
from cta.pipeline import build_panels, compute_signals

DATA = Path(__file__).resolve().parents[1] / "data" / "ricecta" / "data"


@pytest.mark.skipif(not DATA.exists(), reason="no market data")
def test_targets_identical_when_future_removed() -> None:
    cfg = load_config().model_copy(update={"data": DataCfg(settle="vendor_close")})  # 纯米筐源无官方结算价
    specs = load_instruments()
    src = RicequantParquetSource(DATA)
    t = pd.Timestamp("2021-06-30")
    full = compute_signals(build_panels(src, cfg, specs), cfg)
    trunc = compute_signals(build_panels(src, cfg, specs, end=t), cfg)
    a = full.target.loc[t].fillna(0.0)
    b = trunc.target.loc[t].reindex(a.index).fillna(0.0)
    assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-12), (a - b).abs().sort_values().tail()
    # 回溯复权连续价的"水平"依赖未来 roll 比率,但信号只用比率(收益率),因此信号也必须一致
    assert np.allclose(
        full.combined.loc[t].fillna(0).to_numpy(),
        trunc.combined.loc[t].reindex(a.index).fillna(0).to_numpy(),
        atol=1e-12,
    )
