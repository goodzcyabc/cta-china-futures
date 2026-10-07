"""公开样例数据(data/sample/exchanges_sample.tar.gz,交易所官网数据)上的端到端检验。

不依赖本地私有数据,CI 也跑:解压样例 → 交易所直连源 → 完整研究回测;再做一次无前视检验
(数据截到 T 日重算,T 日目标暴露必须与全量数据算出的一致)。
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.config import load_config
from cta.data.exchanges.base import Store
from cta.data.exchanges.source import ExchangeSource
from cta.instruments.specs import load_instruments
from cta.pipeline import build_panels, compute_signals, run_research

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample" / "exchanges_sample.tar.gz"
CONFIG = ROOT / "configs" / "sample.yaml"


@pytest.fixture(scope="module")
def sample_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("sample")
    with tarfile.open(SAMPLE) as tar:
        tar.extractall(d, filter="data")
    return d / "exchanges"


def test_research_runs_on_sample(sample_root: Path, tmp_path: Path) -> None:
    src = ExchangeSource(Store(root=sample_root))
    assert src.symbols() == ["CU", "M", "RB", "SR"]
    meta = run_research(load_config(CONFIG), src, load_instruments(), tmp_path / "out")
    assert meta["n_symbols"] == 4
    assert meta["period"] == ["2021-01-04", "2024-12-31"]
    assert meta["settle_coverage_min"] == 1.0  # 交易所源:全部是官方结算价
    assert len(pd.read_csv(tmp_path / "out" / "trades.csv")) > 0
    rl = pd.read_csv(tmp_path / "out" / "signal_receipts_level.csv", index_col=0)
    assert rl.notna().to_numpy().any()  # 仓单信号确实用上了样例里的仓单数据


@pytest.mark.parametrize("t", ["2022-06-30", "2024-03-15"])
def test_targets_identical_when_future_removed(sample_root: Path, t: str) -> None:
    cfg = load_config(CONFIG)
    specs = load_instruments()
    src = ExchangeSource(Store(root=sample_root))
    ts = pd.Timestamp(t)
    receipts = src.receipts()
    full = compute_signals(build_panels(src, cfg, specs), cfg, receipts=receipts, specs=specs)
    trunc = compute_signals(
        build_panels(src, cfg, specs, end=ts), cfg, receipts=receipts.loc[:ts], specs=specs
    )
    a = full.target.loc[ts].fillna(0.0)
    b = trunc.target.loc[ts].reindex(a.index).fillna(0.0)
    assert a.abs().sum() > 0  # 该日确有持仓,检验不是空对空
    assert np.allclose(a.to_numpy(), b.to_numpy(), atol=1e-12), (a - b).abs().sort_values().tail()
