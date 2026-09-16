"""交易所数据层公共部分:代码规范化、存储不覆盖、校验、到期规则。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges.base import QUOTE_COLS, Store, normalize_contract, symbol_of, validate
from cta.data.exchanges.calendar import TradingCalendar
from cta.data.exchanges.rules import maturity_date


def test_normalize_contract_codes() -> None:
    assert normalize_contract("cu2610", "SHFE") == "CU2610"
    assert normalize_contract("sc2612", "INE") == "SC2612"
    assert normalize_contract("c2701", "DCE") == "C2701"
    assert normalize_contract("CF609", "CZCE", pd.Timestamp("2026-09-11")) == "CF2609"
    assert normalize_contract("CF701", "CZCE", pd.Timestamp("2026-09-11")) == "CF2701"
    assert normalize_contract("SR911", "CZCE", pd.Timestamp("2019-05-06")) == "SR1911"
    assert normalize_contract("TA001", "CZCE", pd.Timestamp("2019-12-20")) == "TA2001"  # 跨十年
    assert symbol_of("MA2703") == "MA"
    with pytest.raises(ValueError):
        normalize_contract("cu-2610", "SHFE")


def _quotes(date: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date, date],
            "exchange": ["SHFE", "SHFE"],
            "symbol": ["CU", "CU"],
            "contract": ["CU2610", "CU2611"],
            "open": [100.0, 0.0],
            "high": [101.0, 0.0],
            "low": [99.0, 0.0],
            "close": [100.5, 0.0],
            "settle": [100.4, 100.9],
            "prev_settle": [100.0, 100.5],
            "volume": [1000.0, 0.0],
            "open_interest": [5000.0, 10.0],
            "turnover": [5e7, 0.0],
        }
    )


def test_store_never_overwrites_and_validates(tmp_path: Path) -> None:
    st = Store(tmp_path)
    d = pd.Timestamp("2026-09-11")
    st.write_raw("SHFE", "quotes", d, "json", b"{}")
    assert st.read_raw("SHFE", "quotes", d, "json") == b"{}"
    p = st.write_day("SHFE", "quotes", d, _quotes("2026-09-11"))
    assert p.exists()
    with pytest.raises(FileExistsError):
        st.write_day("SHFE", "quotes", d, _quotes("2026-09-11"))
    back = st.read_days("SHFE", "quotes")
    assert list(back.columns) == QUOTE_COLS and len(back) == 2
    assert np.isnan(back.loc[back.contract == "CU2611", "close"]).all()  # 无成交 → OHLC 置 NaN
    assert st.days("SHFE", "quotes") == [d]
    bad = _quotes("2026-09-11")
    bad.loc[0, "settle"] = 0.0
    with pytest.raises(ValueError):
        validate("quotes", bad)
    two_dates = _quotes("2026-09-11")
    two_dates.loc[1, "date"] = "2026-09-12"
    with pytest.raises(ValueError):
        validate("quotes", two_dates)


def test_maturity_rules_with_synthetic_calendar(tmp_path: Path) -> None:
    hol = pd.DatetimeIndex(["2027-01-01", "2027-03-15"])  # 假设 3 月 15 日休市以测试顺延
    cal = TradingCalendar(Store(tmp_path), holidays=hol)
    assert maturity_date("CU2703", "SHFE", cal) == pd.Timestamp("2027-03-16")
    assert maturity_date("C2701", "DCE", cal) == pd.Timestamp("2027-01-15")  # 第 10 个交易日
    assert maturity_date("CF2701", "CZCE", cal) == pd.Timestamp("2027-01-15")
    assert maturity_date("JD2703", "DCE", cal) == pd.Timestamp("2027-03-26")  # 倒数第 4 个交易日
    assert maturity_date("SC2812", "INE", cal) == pd.Timestamp("2028-11-30")
    assert maturity_date("TF2606", "CFFEX", cal) == pd.Timestamp("2026-06-12")
