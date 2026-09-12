"""数据源接口与米筐 parquet 实现。

研究与实盘共用同一接口;换数据源只需实现 DataSource 协议。所有 DataFrame 的形状在 docstring 中写死,由 validate_* 校验。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

CONTRACT_COLS = ["open", "high", "low", "close", "volume", "open_interest"]
META_COLS = ["symbol", "exchange", "listed_date", "de_listed_date", "maturity_date", "margin_rate", "multiplier"]
DOM_DAILY_COLS = ["contract", "open", "high", "low", "close", "settlement", "prev_settlement", "limit_up", "limit_down",
                  "volume", "open_interest"]


class DataSource(Protocol):
    """研究/实盘共用的数据接口。"""

    def symbols(self) -> list[str]: ...

    def contracts(self, symbol: str) -> pd.DataFrame:
        """index: MultiIndex (contract, date); columns: CONTRACT_COLS。"""
        ...

    def dominant_map(self) -> pd.DataFrame:
        """columns: date, symbol, contract —— 数据商每日主力合约。"""
        ...

    def contract_meta(self) -> pd.DataFrame:
        """index: contract; columns: META_COLS。"""
        ...

    def dominant_daily(self, symbol: str) -> pd.DataFrame:
        """index: date; columns: DOM_DAILY_COLS —— 主力合约的结算价与官方涨跌停价。"""
        ...

    def shibor(self) -> pd.DataFrame:
        """index: date; columns: ON, 1W, ..., 1Y(百分数)。"""
        ...

    def manifest(self) -> dict[str, str]:
        """数据指纹,写入每次运行的结果。"""
        ...


def validate_contracts(df: pd.DataFrame) -> pd.DataFrame:
    if list(df.index.names) != ["contract", "date"]:
        raise ValueError(f"contracts index must be (contract, date), got {df.index.names}")
    missing = [c for c in CONTRACT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"contracts missing columns {missing}")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("non-positive prices in contracts")
    if (df[["volume", "open_interest"]] < 0).any().any():
        raise ValueError("negative volume/open_interest")
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()
    return df


def validate_meta(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in META_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"meta missing columns {missing}")
    if (df["maturity_date"] < df["listed_date"]).any():
        raise ValueError("maturity before listing")
    return df


class RicequantParquetSource:
    """读取 Uwater1/ricecta 仓库 data/ 目录下的米筐导出 parquet。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._meta: pd.DataFrame | None = None

    def symbols(self) -> list[str]:
        return sorted(p.stem for p in (self.root / "contracts_daily").glob("*.parquet") if p.stem != "metadata")

    def contracts(self, symbol: str) -> pd.DataFrame:
        df = pd.read_parquet(self.root / "contracts_daily" / f"{symbol}.parquet")
        df.index = df.index.set_names(["contract", "date"])
        return validate_contracts(df)

    @staticmethod
    def _flat(df: pd.DataFrame) -> pd.DataFrame:
        """把可能存放在索引里的字段还原为列,并去掉多余的 'index' 列。"""
        out = df.reset_index()
        return out.drop(columns=[c for c in out.columns if str(c) in ("index", "level_0")], errors="ignore")

    def dominant_map(self) -> pd.DataFrame:
        df = self._flat(pd.read_parquet(self.root / "dominant_contracts" / "dominant.parquet"))
        df = df.rename(columns={"dominant_contract": "contract", "underlying_symbol": "symbol"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "symbol", "contract"]].sort_values(["symbol", "date"]).reset_index(drop=True)

    def contract_meta(self) -> pd.DataFrame:
        if self._meta is None:
            m = self._flat(pd.read_parquet(self.root / "contracts_daily" / "metadata.parquet"))
            # 原表的 symbol 列是中文简称(如 铜2101),先改名以免与品种代码列冲突
            m = m.rename(columns={"symbol": "name"}).rename(
                columns={"order_book_id": "contract", "underlying_symbol": "symbol", "contract_multiplier": "multiplier"})
            for c in ["listed_date", "de_listed_date", "maturity_date"]:
                m[c] = pd.to_datetime(m[c])
            m = m.set_index("contract")[META_COLS]
            self._meta = validate_meta(m)
        return self._meta

    def dominant_daily(self, symbol: str) -> pd.DataFrame:
        df = self._flat(pd.read_parquet(self.root / "dominant_daily" / f"{symbol}.parquet"))
        df = df.rename(columns={"dominant_id": "contract"})
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")[DOM_DAILY_COLS].sort_index()

    def shibor(self) -> pd.DataFrame:
        df = pd.read_parquet(self.root / "shibor" / "shibor.parquet")
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def manifest(self) -> dict[str, str]:
        files = sorted(self.root.rglob("*.parquet"))
        h = hashlib.sha256()
        for f in files:
            st = f.stat()
            h.update(f"{f.relative_to(self.root)}|{st.st_size}|{int(st.st_mtime)}".encode())
        return {"root": str(self.root), "n_files": str(len(files)), "sha256": h.hexdigest()[:16]}


def write_manifest(src: DataSource, path: Path) -> None:
    path.write_text(json.dumps(src.manifest(), ensure_ascii=False, indent=2), encoding="utf-8")
