import pandas as pd
import pytest

from cta.data.source import validate_contracts, validate_meta


def _contracts() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [["X2101", "X2105"], pd.bdate_range("2020-01-01", periods=3)], names=["contract", "date"]
    )
    return pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 10.0, "open_interest": 50.0},
        index=idx,
    )


def test_validate_contracts_ok_and_bad() -> None:
    df = validate_contracts(_contracts())
    assert list(df.index.names) == ["contract", "date"]
    bad = _contracts()
    bad.loc[("X2101", bad.index.get_level_values(1)[0]), "close"] = -1.0
    with pytest.raises(ValueError):
        validate_contracts(bad)
    with pytest.raises(ValueError):
        validate_contracts(_contracts().reset_index())


def test_validate_meta() -> None:
    m = pd.DataFrame(
        {
            "symbol": ["X"],
            "exchange": ["SHFE"],
            "listed_date": [pd.Timestamp("2020-01-01")],
            "de_listed_date": [pd.Timestamp("2021-01-15")],
            "maturity_date": [pd.Timestamp("2021-01-15")],
            "margin_rate": [0.1],
            "multiplier": [5.0],
        },
        index=pd.Index(["X2101"], name="contract"),
    )
    assert validate_meta(m) is m
    m2 = m.copy()
    m2["maturity_date"] = pd.Timestamp("2019-01-01")
    with pytest.raises(ValueError):
        validate_meta(m2)
