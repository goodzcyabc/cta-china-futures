"""交易所数据层的公共部分:统一字段、存储布局、校验、合约代码规范化。各交易所抓取模块只依赖这里。"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

Exchange = Literal["SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX"]
Kind = Literal["quotes", "positions", "receipts"]
EXCHANGES: tuple[Exchange, ...] = ("SHFE", "INE", "DCE", "CZCE", "CFFEX", "GFEX")

DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "data" / "exchanges"

# 行情:每个交易所每天一个文件,一行一个合约。无成交时 open/high/low/close 可为 NaN,settle 必须 > 0。
QUOTE_COLS = [
    "date",
    "exchange",
    "symbol",
    "contract",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "prev_settle",
    "volume",
    "open_interest",
    "turnover",
]
# 会员持仓排名:一行 = 某合约(或品种合计)某名次的三列并排(成交量榜 / 多头榜 / 空头榜),rank=0 为合计行。
POSITION_COLS = [
    "date",
    "exchange",
    "symbol",
    "contract",
    "is_total",
    "rank",
    "member_vol",
    "vol",
    "vol_chg",
    "member_long",
    "long_oi",
    "long_chg",
    "member_short",
    "short_oi",
    "short_chg",
]
# 仓单:一行 = 某品种某仓库(或合计)的注册仓单数量与当日增减。
RECEIPT_COLS = ["date", "exchange", "symbol", "warehouse", "is_total", "receipts", "change"]


class NotFinalError(RuntimeError):
    """交易所文件是盘中快照(结算价未出),不得落盘;调用方应删除已缓存的 raw 并稍后重试。"""


_COLS: dict[str, list[str]] = {"quotes": QUOTE_COLS, "positions": POSITION_COLS, "receipts": RECEIPT_COLS}
_CODE_RE = re.compile(r"^([A-Za-z]{1,2})(\d{3,4})$")


def normalize_contract(code: str, exchange: str, file_date: pd.Timestamp | None = None) -> str:
    """把各交易所的合约代码统一成 米筐/本仓库 口径:大写品种 + 4 位 YYMM,如 cu2610 → CU2610、CF609 → CF2609。
    郑商所用 3 位 yMM(年份个位数),十年位按文件日期推断:取与文件年份最接近且不早于文件年份前一年的十年。"""
    m = _CODE_RE.match(code.strip())
    if not m:
        raise ValueError(f"unrecognised contract code {code!r} ({exchange})")
    sym, num = m.group(1).upper(), m.group(2)
    if len(num) == 4:
        return f"{sym}{num}"
    if file_date is None:
        raise ValueError(f"3-digit contract {code!r} needs file_date to infer decade")
    y, mm = int(num[0]), num[1:]
    decade = (file_date.year // 10) * 10
    year = decade + y
    if year < file_date.year - 1:
        year += 10
    return f"{sym}{year % 100:02d}{mm}"


def symbol_of(contract: str) -> str:
    m = _CODE_RE.match(contract)
    if not m:
        raise ValueError(f"bad contract {contract!r}")
    return m.group(1).upper()


@dataclass(frozen=True)
class Store:
    """落盘布局。raw 存原始下载(gzip),规范化后的 parquet 按 kind/年/日存放;已有文件默认不覆盖。"""

    root: Path = DEFAULT_ROOT

    def raw_path(self, exchange: str, kind: str, date: pd.Timestamp, ext: str) -> Path:
        d = pd.Timestamp(date)
        return self.root / exchange / "raw" / kind / f"{d.year}" / f"{d.strftime('%Y%m%d')}.{ext}.gz"

    def day_path(self, exchange: str, kind: str, date: pd.Timestamp) -> Path:
        d = pd.Timestamp(date)
        return self.root / exchange / kind / f"{d.year}" / f"{d.strftime('%Y%m%d')}.parquet"

    def write_raw(self, exchange: str, kind: str, date: pd.Timestamp, ext: str, content: bytes) -> Path:
        p = self.raw_path(exchange, kind, date, ext)
        if p.exists():
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wb") as f:
            f.write(content)
        return p

    def read_raw(self, exchange: str, kind: str, date: pd.Timestamp, ext: str) -> bytes | None:
        p = self.raw_path(exchange, kind, date, ext)
        if not p.exists():
            return None
        with gzip.open(p, "rb") as f:
            return f.read()

    def write_day(
        self, exchange: str, kind: str, date: pd.Timestamp, df: pd.DataFrame, overwrite: bool = False
    ) -> Path:
        p = self.day_path(exchange, kind, date)
        if p.exists() and not overwrite:
            raise FileExistsError(f"{p} exists; point-in-time store never overwrites (use overwrite=True)")
        out = validate(kind, df)
        p.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(p, index=False)
        return p

    def has_day(self, exchange: str, kind: str, date: pd.Timestamp) -> bool:
        return self.day_path(exchange, kind, date).exists()

    def days(self, exchange: str, kind: str) -> list[pd.Timestamp]:
        base = self.root / exchange / kind
        if not base.exists():
            return []
        return sorted(pd.Timestamp(p.stem) for p in base.glob("*/*.parquet"))

    def read_days(
        self, exchange: str, kind: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None
    ) -> pd.DataFrame:
        days = [
            d
            for d in self.days(exchange, kind)
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        if not days:
            return pd.DataFrame(columns=_COLS[kind])
        frames = [pd.read_parquet(self.day_path(exchange, kind, d)) for d in days]
        return pd.concat(frames, ignore_index=True)

    def read_symbol(self, exchanges: Iterable[str], symbol: str) -> pd.DataFrame:
        """某品种全部合约的日线(跨年拼接)。"""
        parts = [self.read_days(e, "quotes") for e in exchanges]
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=QUOTE_COLS)
        return df[df["symbol"] == symbol].reset_index(drop=True)


def validate(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    cols = _COLS[kind]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{kind} missing columns {missing}")
    out = df[cols].copy()
    out["date"] = pd.to_datetime(out["date"])
    if out["date"].nunique() != 1:
        raise ValueError(f"{kind}: one file must hold exactly one date, got {out['date'].unique()[:5]}")
    if kind == "quotes":
        if (out["contract"].map(lambda c: _CODE_RE.match(str(c)) is None)).any():
            bad = out.loc[out["contract"].map(lambda c: _CODE_RE.match(str(c)) is None), "contract"].head()
            raise ValueError(f"quotes: bad contract codes {list(bad)}")
        if out["contract"].duplicated().any():
            raise ValueError("quotes: duplicated contract rows")
        for c in [
            "open",
            "high",
            "low",
            "close",
            "settle",
            "prev_settle",
            "volume",
            "open_interest",
            "turnover",
        ]:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
        traded = out["volume"].fillna(0) > 0
        if (out.loc[traded, ["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("quotes: non-positive OHLC on traded contracts")
        if (out["settle"] <= 0).any() or out["settle"].isna().any():
            raise ValueError("quotes: settle must be > 0 for every contract")
        if (out[["volume", "open_interest"]].fillna(0) < 0).any().any():
            raise ValueError("quotes: negative volume/open_interest")
        out.loc[~traded, ["open", "high", "low", "close"]] = np.nan
    elif kind == "positions":
        out["rank"] = out["rank"].astype(int)
        out["is_total"] = out["is_total"].astype(bool)
        for c in ["vol", "vol_chg", "long_oi", "long_chg", "short_oi", "short_chg"]:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    else:
        out["is_total"] = out["is_total"].astype(bool)
        for c in ["receipts", "change"]:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    return out.reset_index(drop=True)
