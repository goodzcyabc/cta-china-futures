"""把交易所落盘数据装配成 DataSource 协议(ExchangeSource),以及"米筐历史 + 交易所增量"的拼接源(StitchedSource)。

约定:
- contracts(symbol) 的 OHLC 在无成交日用结算价填充(交易所无成交时 OHLC 为空),volume/open_interest 保留交易所原值。
- dominant_map:每品种每日的候选主力 = **前一交易日**持仓量最大的合约(T 日开盘前可知);首日用当日。
  持仓量口径若与米筐不同(单/双边),只影响绝对数,不影响主力判定。
- contract_meta:listed_date = 首次出现日,de_listed_date = 最后出现日(仍在交易的合约取到期日),maturity_date 按 rules.py,
  multiplier / margin_rate 取自 configs/instruments.yaml(交易所数据不含乘数)。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from cta.data.exchanges.base import QUOTE_COLS, Store
from cta.data.exchanges.calendar import TradingCalendar
from cta.data.exchanges.rules import maturity_date
from cta.data.source import (
    CONTRACT_COLS,
    DOM_DAILY_COLS,
    META_COLS,
    DataSource,
    validate_contracts,
    validate_meta,
)
from cta.instruments.specs import InstrumentTable, load_instruments

SYMBOL_EXCHANGE_DEFAULT = ("SHFE", "INE", "DCE", "CZCE")


class ExchangeSource:
    def __init__(
        self,
        store: Store | None = None,
        exchanges: tuple[str, ...] = SYMBOL_EXCHANGE_DEFAULT,
        specs: InstrumentTable | None = None,
        calendar: TradingCalendar | None = None,
    ):
        self.store = store or Store()
        self.exchanges = exchanges
        self.specs = specs or load_instruments()
        self._quotes: pd.DataFrame | None = None
        self._cal = calendar
        self._meta: pd.DataFrame | None = None

    # ---- 装载与缓存 ----
    def _load_exchange(self, exchange: str) -> pd.DataFrame:
        """逐日 parquet 很多,按交易所合并成一个缓存文件;新增日期后自动重建。"""
        days = self.store.days(exchange, "quotes")
        if not days:
            return pd.DataFrame(columns=QUOTE_COLS)
        cache = self.store.root / exchange / "quotes_all.parquet"
        stamp = f"{len(days)}:{days[-1].strftime('%Y%m%d')}"
        stamp_file = cache.with_suffix(".stamp")
        if cache.exists() and stamp_file.exists() and stamp_file.read_text() == stamp:
            return pd.read_parquet(cache)
        df = self.store.read_days(exchange, "quotes")
        df.to_parquet(cache, index=False)
        stamp_file.write_text(stamp)
        return df

    def quotes(self) -> pd.DataFrame:
        if self._quotes is None:
            parts = [self._load_exchange(e) for e in self.exchanges]
            q = (
                pd.concat([p for p in parts if len(p)], ignore_index=True)
                if any(len(p) for p in parts)
                else pd.DataFrame(columns=QUOTE_COLS)
            )
            q["date"] = pd.to_datetime(q["date"])
            self._quotes = q.sort_values(["symbol", "contract", "date"]).reset_index(drop=True)
        return self._quotes

    @property
    def calendar(self) -> TradingCalendar:
        if self._cal is None:
            self._cal = TradingCalendar(self.store)
        return self._cal

    # ---- DataSource 协议 ----
    def symbols(self) -> list[str]:
        return sorted(self.quotes()["symbol"].unique().tolist())

    def contracts(self, symbol: str) -> pd.DataFrame:
        q = self.quotes()
        q = q[q["symbol"] == symbol].copy()
        if q.empty:
            raise KeyError(f"no exchange quotes for {symbol}")
        for c in ["open", "high", "low", "close"]:
            q[c] = q[c].fillna(q["settle"])
        out = q.set_index(["contract", "date"])[[*CONTRACT_COLS, "settle", "prev_settle"]].sort_index()
        return validate_contracts(out)

    def dominant_map(self) -> pd.DataFrame:
        q = self.quotes()
        idx = q.groupby(["symbol", "date"])["open_interest"].idxmax()
        top = q.loc[idx, ["symbol", "date", "contract"]].sort_values(["symbol", "date"])
        # 前一交易日的最大持仓合约作为 T 日候选
        top["contract"] = top.groupby("symbol")["contract"].shift(1).fillna(top["contract"])
        return top[["date", "symbol", "contract"]].reset_index(drop=True)

    def contract_meta(self) -> pd.DataFrame:
        if self._meta is None:
            q = self.quotes()
            g = q.groupby("contract")
            first = g["date"].min()
            last = g["date"].max()
            exch = g["exchange"].first()
            sym = g["symbol"].first()
            rows = []
            last_day = q["date"].max()
            for c in first.index:
                s, e = str(sym[c]), str(exch[c])
                try:
                    mat = maturity_date(c, e, self.calendar)
                except Exception:  # noqa: BLE001 —— 规则缺失时退化为最后出现日
                    mat = last[c]
                spec = self.specs.specs.get(s)
                rows.append(
                    {
                        "contract": c,
                        "symbol": s,
                        "exchange": e,
                        "listed_date": first[c],
                        "de_listed_date": last[c] if last[c] < last_day else max(mat, last[c]),
                        "maturity_date": max(mat, first[c]),
                        "margin_rate": spec.margin_rate if spec else np.nan,
                        "multiplier": spec.multiplier if spec else np.nan,
                    }
                )
            m = pd.DataFrame(rows).set_index("contract")[META_COLS]
            self._meta = validate_meta(m)
        return self._meta

    def dominant_daily(self, symbol: str) -> pd.DataFrame:
        dm_all = self.dominant_map()
        dm = dm_all[dm_all["symbol"] == symbol][["date", "contract"]]
        c = self.contracts(symbol).reset_index()
        merged = dm.merge(c, on=["date", "contract"], how="left")
        merged["settlement"] = merged["settle"]
        merged["prev_settlement"] = merged["prev_settle"]
        merged["limit_up"] = np.nan
        merged["limit_down"] = np.nan
        return merged.set_index("date")[DOM_DAILY_COLS]

    def shibor(self) -> pd.DataFrame:
        return pd.DataFrame()

    def receipts(self) -> pd.DataFrame:
        """注册仓单合计(非合计行之和,四所拼接);index=date, columns=symbol。"""
        parts = []
        for e in self.exchanges:
            r = self.store.read_days(e, "receipts")
            if r.empty:
                continue
            parts.append(r[~r["is_total"]].groupby(["date", "symbol"])["receipts"].sum())
        if not parts:
            return pd.DataFrame()
        out: pd.DataFrame = pd.concat(parts).groupby(level=[0, 1]).sum().unstack("symbol").sort_index()
        out.index = pd.to_datetime(out.index)
        return out

    def manifest(self) -> dict[str, str]:
        h = hashlib.sha256()
        parts = []
        for e in self.exchanges:
            days = self.store.days(e, "quotes")
            parts.append(f"{e}:{len(days)}:{days[-1].strftime('%Y%m%d') if days else '-'}")
            for d in days:
                h.update(str(self.store.day_path(e, "quotes", d)).encode())
        return {"root": str(self.store.root), "coverage": ";".join(parts), "sha256": h.hexdigest()[:16]}


class StitchedSource:
    """cutover(含)之前用 primary(米筐历史导出),之后用 secondary(交易所直连)。品种与合约代码口径必须一致。"""

    def __init__(self, primary: DataSource, secondary: DataSource, cutover: pd.Timestamp):
        self.primary, self.secondary, self.cutover = primary, secondary, pd.Timestamp(cutover)

    def symbols(self) -> list[str]:
        return sorted(set(self.primary.symbols()) | set(self.secondary.symbols()))

    def contracts(self, symbol: str) -> pd.DataFrame:
        parts = []
        if symbol in self.primary.symbols():
            a = self.primary.contracts(symbol)
            parts.append(a[a.index.get_level_values("date") <= self.cutover])
        if symbol in self.secondary.symbols():
            b = self.secondary.contracts(symbol)
            parts.append(b[b.index.get_level_values("date") > self.cutover])
        if not parts:
            raise KeyError(symbol)
        # 列取并集:米筐段没有官方结算价,用收盘价近似(settle=close, prev_settle=前一日 settle);交易所段保留官方值
        filled = []
        for raw_part in parts:
            part = raw_part.copy()
            if "settle" not in part.columns:
                part["settle"] = part["close"]
                part["prev_settle"] = part.groupby(level="contract")["settle"].shift(1)
            filled.append(part)
        out = pd.concat(filled).sort_index()
        return validate_contracts(out)

    def dominant_map(self) -> pd.DataFrame:
        a = self.primary.dominant_map()
        b = self.secondary.dominant_map()
        out = pd.concat([a[a["date"] <= self.cutover], b[b["date"] > self.cutover]], ignore_index=True)
        return out.sort_values(["symbol", "date"]).reset_index(drop=True)

    def contract_meta(self) -> pd.DataFrame:
        a = self.primary.contract_meta()
        b = self.secondary.contract_meta()
        new = b[~b.index.isin(a.index)]
        return validate_meta(pd.concat([a, new]))

    def dominant_daily(self, symbol: str) -> pd.DataFrame:
        a = self.primary.dominant_daily(symbol)
        b = self.secondary.dominant_daily(symbol)
        return pd.concat([a[a.index <= self.cutover], b[b.index > self.cutover]]).sort_index()

    def shibor(self) -> pd.DataFrame:
        return self.primary.shibor()

    def receipts(self) -> pd.DataFrame:
        """仓单只有交易所直连源有;拼接源直接用 secondary 的全历史(它从 2016 起已回填)。"""
        return self.secondary.receipts()

    def manifest(self) -> dict[str, str]:
        mp, ms = self.primary.manifest(), self.secondary.manifest()
        return {
            "primary": str(mp),
            "secondary": str(ms),
            "cutover": str(self.cutover.date()),
            "sha256": hashlib.sha256((str(mp) + str(ms)).encode()).hexdigest()[:16],
        }


def default_stitched(rq_root: Path, cutover: pd.Timestamp | None = None) -> StitchedSource:
    """米筐导出(到其最后一日)+ 交易所直连(之后)。"""
    from cta.data.source import RicequantParquetSource

    rq = RicequantParquetSource(rq_root)
    ex = ExchangeSource()
    if cutover is None:
        cu = rq.contracts(rq.symbols()[0]).index.get_level_values("date").max()
        cutover = pd.Timestamp(cu)
    return StitchedSource(rq, ex, cutover)
