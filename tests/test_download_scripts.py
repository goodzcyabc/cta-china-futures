"""download/ 的纯函数(不需要 rqdatac):合成连续合约排除、品种排序、分批、原子写 parquet、压缩编码判定、重试不吞配额错误。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "download"))
import rq_common as rc  # noqa: E402


def _universe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_book_id": ["CU2601", "CU2401", "CU88", "CU99", "RB2601", "IF2601"],
            "underlying_symbol": ["CU", "CU", "CU", "CU", "RB", "IF"],
            "exchange": ["SHFE", "SHFE", "SHFE", "SHFE", "SHFE", "CFFEX"],
            "listed_date": pd.to_datetime(
                ["2025-01-15", "2023-01-16", None, None, "2025-01-15", "2025-01-15"]
            ),
            "de_listed_date": pd.to_datetime(["2026-01-15", "2024-01-15", None, None, None, "2026-01-15"]),
        }
    )


def test_contracts_since_drops_synthetic_and_expired() -> None:
    uni = _universe()
    assert rc.contracts_since(uni, "CU", "2025-01-01") == ["CU2601"]  # CU2401 已退市,88/99 无上市日
    assert rc.contracts_since(uni, "CU", "2023-06-01") == ["CU2401", "CU2601"]
    assert rc.contracts_since(uni, "RB", "2016-01-01") == ["RB2601"]  # 未退市(NaT)


def test_commodity_symbols_production_first_and_no_cffex() -> None:
    uni = _universe()
    assert rc.commodity_symbols(uni) == ["CU", "RB"]  # 生产池顺序:CU 在 RB 前;IF(中金所)排除


def test_chunked() -> None:
    assert [list(c) for c in rc.chunked([1, 2, 3, 4, 5], 2)] == [[1, 2], [3, 4], [5]]
    assert list(rc.chunked([], 3)) == []


def test_write_parquet_is_atomic_and_skips_empty(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    p = tmp_path / "a" / "x.parquet"
    rc.write_parquet(pd.DataFrame(), p)
    assert not p.exists()  # 空表不落盘
    rc.write_parquet(pd.DataFrame({"v": [1.0]}, index=pd.Index(["c"], name="contract")), p)
    assert p.exists() and not p.with_name("x.parquet.tmp").exists()
    assert pd.read_parquet(p).index.name == "contract"


def test_retry_retries_network_errors_but_not_quota() -> None:
    calls = {"n": 0}

    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("x")
        return 7

    assert rc.retry(flaky, attempts=3, wait=0.0) == 7 and calls["n"] == 3
    with pytest.raises(rc.QuotaExhausted):
        rc.retry(lambda: (_ for _ in ()).throw(rc.QuotaExhausted("q")), attempts=3, wait=0.0)
    with pytest.raises(RuntimeError, match="重试 2 次仍失败"):
        rc.retry(lambda: (_ for _ in ()).throw(ValueError("bad")), attempts=2, wait=0.0)


def test_column_encodings_only_for_float_and_time_columns() -> None:
    df = pd.DataFrame({"v": [1.0, 2.0], "ts": pd.to_datetime(["2026-01-02", "2026-01-05"])})
    assert rc.column_encodings(df) == {"v": "BYTE_STREAM_SPLIT", "ts": "DELTA_BINARY_PACKED"}
    assert rc.column_encodings(df.assign(s=["a", "b"])) is None  # 混入字符串列 -> 默认编码
    assert rc.column_encodings(df.set_index(pd.Index(["c1", "c2"], name="contract"))) is None  # 字符串索引
    di = df.set_index(pd.DatetimeIndex(["2026-01-02", "2026-01-05"], name="datetime"))
    assert rc.column_encodings(di) == {
        "datetime": "DELTA_BINARY_PACKED",
        "v": "BYTE_STREAM_SPLIT",
        "ts": "DELTA_BINARY_PACKED",
    }
