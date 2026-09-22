"""design_log 十六 数据准备:从 5 分钟线为每个 (contract, trading_date) 计算候选成交价
F0 首 bar open、F1 前 30 分钟 VWAP、F2 前 60 分钟 VWAP、F3 日盘 09:00 开盘、F4 全时段 VWAP,以及首 bar VWAP;缓存到 results/exec/fills.parquet。
VWAP = Σ成交额/Σ成交量/乘数(米筐 total_turnover 为成交金额,成交量为手;乘数取自参数表)。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.instruments.specs import load_instruments  # noqa: E402

ROOT = Path("data/ricecta/data/futures_5minute")
OUT = Path("results/exec")
OUT.mkdir(parents=True, exist_ok=True)
specs = load_instruments()


def fills_for(symbol: str) -> pd.DataFrame:
    mult = specs[symbol].multiplier
    frames = []
    for f in sorted((ROOT / symbol).glob("*.parquet")):
        df = pd.read_parquet(f)
        if df.empty:
            continue
        df.index = pd.to_datetime(df.index)
        df = df[df["volume"] > 0].copy()
        if df.empty:
            continue
        df["contract"] = f.stem.upper()
        df["trading_date"] = pd.to_datetime(df["trading_date"])
        df["bar_end"] = df.index
        df["is_day"] = df.index.time >= pd.Timestamp("09:05").time()
        df["is_day"] &= df.index.time <= pd.Timestamp("15:00").time()
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    x = pd.concat(frames).sort_values(["contract", "trading_date", "bar_end"])
    g = x.groupby(["contract", "trading_date"], sort=False)
    x["k"] = g.cumcount()  # 时段内序号(含夜盘)
    x["amt"] = x["total_turnover"]
    x["qty"] = x["volume"] * mult

    def vwap(sub: pd.DataFrame) -> float:
        q = sub["qty"].sum()
        return float(sub["amt"].sum() / q) if q > 0 else np.nan

    rows = []
    for (c, d), sub in g:
        first = sub.iloc[0]
        day = sub[sub["is_day"]]
        rows.append(
            {
                "contract": c,
                "date": d,
                "F0_open": float(first["open"]),
                "F0_bar_vwap": vwap(sub.iloc[:1]),
                "F1_vwap30": vwap(sub.iloc[:6]),
                "F2_vwap60": vwap(sub.iloc[:12]),
                "F3_day_open": float(day.iloc[0]["open"]) if len(day) else np.nan,
                "F4_vwap_all": vwap(sub),
                "n_bars": len(sub),
                "has_night": bool(not first["is_day"]),
            }
        )
    out = pd.DataFrame(rows)
    out["symbol"] = symbol
    return out


if __name__ == "__main__":
    syms = [s for s in sorted(p.name for p in ROOT.iterdir()) if s != "TF"]
    parts = []
    for s in syms:
        df = fills_for(s)
        parts.append(df)
        print(
            s,
            len(df),
            "rows",
            df["date"].min().date() if len(df) else None,
            "→",
            df["date"].max().date() if len(df) else None,
            flush=True,
        )
    allf = pd.concat(parts, ignore_index=True)
    allf.to_parquet(OUT / "fills.parquet", index=False)
    print("saved", len(allf))
