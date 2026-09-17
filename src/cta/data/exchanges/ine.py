"""上海国际能源交易中心(INE):与上期所同一套数据接口,只差域名与交易所标签;解析全部复用 shfe.py。

品种:原油 SC(2018-03-26 上市)、20 号胶 NR(2019-08-12)、低硫燃料油 LU(2020-06-22)、国际铜 BC(2020-11-19)、
集运指数(欧线) EC(2023-08-18)。会员排名按能源中心公布标准(原油单合约持仓 ≥10 万手才公布)常年缺原油。

用法:
    PYTHONPATH=src python3 -m cta.data.exchanges.ine backfill --start 2018-03-26 --end 2026-09-16 \
        --kinds quotes,positions,receipts
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence

import pandas as pd

from cta.data.exchanges import shfe
from cta.data.exchanges.base import Kind, Store
from cta.data.exchanges.shfe import INE_SYMBOLS, Site

INE = Site("INE", "https://www.ine.cn", INE_SYMBOLS, receipts_html_base="https://www.shfe.com.cn")
INE_START = pd.Timestamp("2018-03-26")


def fetch_quotes(date: pd.Timestamp, store: Store | None = None) -> bytes | None:
    return shfe.fetch_quotes(date, store, INE)


def fetch_positions(date: pd.Timestamp, store: Store | None = None) -> bytes | None:
    return shfe.fetch_positions(date, store, INE)


def fetch_receipts(date: pd.Timestamp, store: Store | None = None) -> tuple[str, bytes] | None:
    return shfe.fetch_receipts(date, store, INE)


def parse_quotes(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    return shfe.parse_quotes(raw, date, INE)


def parse_positions(raw: bytes, date: pd.Timestamp) -> pd.DataFrame:
    return shfe.parse_positions(raw, date, INE)


def parse_receipts(raw: bytes, date: pd.Timestamp, ext: str = "json") -> pd.DataFrame:
    return shfe.parse_receipts(raw, date, INE, ext)


def ingest_day(
    date: pd.Timestamp,
    kinds: Iterable[Kind] = shfe.KINDS,
    store: Store | None = None,
    overwrite: bool = False,
) -> dict[str, str]:
    return shfe.ingest_day(date, kinds, store, INE, overwrite=overwrite)


def backfill(
    start: pd.Timestamp,
    end: pd.Timestamp,
    kinds: Iterable[Kind] = shfe.KINDS,
    store: Store | None = None,
    retry_missing: bool = False,
    overwrite: bool = False,
) -> dict[str, int]:
    return shfe.backfill(start, end, kinds, store, INE, retry_missing=retry_missing, overwrite=overwrite)


def coverage(store: Store | None = None) -> pd.DataFrame:
    return shfe.coverage(store, INE)


def main(argv: Sequence[str] | None = None) -> int:
    return shfe.main(argv, INE)


if __name__ == "__main__":
    sys.exit(main())
