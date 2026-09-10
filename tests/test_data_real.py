"""数据层对真实数据的冒烟测试(缺数据时跳过):形状、列名、日期类型、主力映射覆盖。"""

from pathlib import Path

import pandas as pd
import pytest

from cta.data.source import CONTRACT_COLS, DOM_DAILY_COLS, META_COLS, RicequantParquetSource

DATA = Path(__file__).resolve().parents[1] / "data" / "ricecta" / "data"
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="no market data")


def test_real_source_shapes() -> None:
    src = RicequantParquetSource(DATA)
    syms = src.symbols()
    assert len(syms) == 23 and "CU" in syms and "metadata" not in syms
    c = src.contracts("CU")
    assert list(c.index.names) == ["contract", "date"] and list(c.columns) == CONTRACT_COLS
    assert c.index.get_level_values("date").min() == pd.Timestamp("2016-01-04")
    dm = src.dominant_map()
    assert list(dm.columns) == ["date", "symbol", "contract"] and dm["date"].dtype.kind == "M"
    assert set(dm["symbol"]) >= set(syms)
    m = src.contract_meta()
    assert list(m.columns) == META_COLS and m.index.name == "contract" and "CU2106" in m.index
    assert (m.loc["CU2106", "maturity_date"] - pd.Timestamp("2021-06-01")).days < 31
    dd = src.dominant_daily("CU")
    assert list(dd.columns) == DOM_DAILY_COLS and dd.index.name == "date" and dd["settlement"].notna().all()
    sh = src.shibor()
    assert "ON" in sh.columns and sh.index.dtype.kind == "M"
    man = src.manifest()
    assert int(man["n_files"]) > 2000 and len(man["sha256"]) == 16
