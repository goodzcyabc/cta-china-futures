"""月度横截面 IC / ICIR 与逐年统计(需求方口径;定义见 docs/research/ewmac_base_prereg.md 4.1)。

IC:每个月最后一个交易日的信号,按当日可投条件置空,与下一个月 adj_close 对数收益做横截面 Spearman 相关,
当月有效品种 ≥ 8 才计;只用下一个月完整的信号月份(--last-signal-month 指定最后一个)。
ICIR = 月度 IC 均值 / 标准差(ddof = 1),同时给出不年化与 ×√12 两种。
描述性统计,不计试验。默认读一次已有研究回测的信号文件(signal_<名>.csv 与 eligible.csv)。

用法:python research/scripts/factor_ic_monthly.py [--run results/source_check/stitched] [--signals tsmom,carry,receipts_level,combined]
      [--last-signal-month 2026-05]   # 默认复现 ewmac_base_prereg.md 第 1 节的数字
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/(cta_research)

from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import _wide, build_panels  # noqa: E402

MIN_N = 8
IS_END = "2021-12-31"


def monthly_ic(signal: pd.DataFrame, adj_close: pd.DataFrame, eligible: pd.DataFrame) -> pd.Series:
    """月末信号(按可投条件置空)对下月对数收益的横截面 Spearman;index = 月末交易日。"""
    idx = pd.DatetimeIndex(adj_close.index)
    month_end = pd.DatetimeIndex(pd.Series(idx, index=idx).groupby(idx.to_period("M")).max().to_numpy())
    px = adj_close.reindex(month_end)
    fwd = np.log(px.shift(-1) / px)
    sig = signal.reindex(index=month_end, columns=adj_close.columns)
    sig = sig.where(eligible.reindex(index=month_end, columns=adj_close.columns).fillna(False).astype(bool))
    out = {}
    for t in month_end[:-1]:
        a, b = sig.loc[t], fwd.loc[t]
        ok = a.notna() & b.notna()
        if int(ok.sum()) >= MIN_N:
            out[t] = float(a[ok].rank().corr(b[ok].rank()))
    return pd.Series(out, name="ic", dtype=float)


def summarize(ic: pd.Series, last: str) -> pd.DataFrame:
    rows = []
    periods = {"2017–2021": ("2017-01-01", IS_END), f"2022-01 → {last}": ("2022-01-01", last)}
    for name, (a, b) in periods.items():
        x = ic[(ic.index >= a) & (ic.index <= b)]
        icir = x.mean() / x.std(ddof=1) if len(x) > 1 else np.nan
        rows.append(
            {"区间": name, "月数": len(x), "IC 均值": x.mean(), "ICIR": icir, "ICIR×√12": icir * np.sqrt(12)}
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=Path("results/source_check/stitched"))
    ap.add_argument("--signals", default="tsmom,carry,receipts_level,combined")
    ap.add_argument("--config", type=Path, default=Path("configs/strategy_v03.yaml"))
    ap.add_argument("--last-signal-month", default="2026-05", help="最后一个信号月份(其下一个月须完整)")
    ap.add_argument("--last-year", type=int, default=2025, help="逐年统计的最后一个完整年份")
    args = ap.parse_args()
    cfg = load_config(args.config)
    panels = build_panels(default_stitched(Path("data/ricecta/data")), cfg, load_instruments())
    adj = _wide(panels, "adj_close")
    elig = pd.read_csv(args.run / "eligible.csv", index_col=0, parse_dates=True)
    elig = elig.reindex(adj.index).fillna(False).astype(bool)
    yearly = {}
    for name in args.signals.split(","):
        sig = pd.read_csv(args.run / f"signal_{name}.csv", index_col=0, parse_dates=True)
        last = pd.Period(args.last_signal_month, "M").end_time.normalize()
        ic = monthly_ic(sig, adj, elig)
        ic = ic[ic.index <= last]
        print(f"== {name}")
        print(summarize(ic, str(last.date())).round(3).to_string(index=False))
        by_year = ic.groupby(pd.DatetimeIndex(ic.index).year).mean()
        by_year = by_year[(by_year.index >= 2017) & (by_year.index <= args.last_year)]
        yearly[name] = by_year
    y = pd.DataFrame(yearly)
    print("\n== 逐年月度 IC 均值")
    print(y.round(3).to_string())
    print("IC>0 的年数:", {c: f"{int((y[c] > 0).sum())}/{int(y[c].notna().sum())}" for c in y})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
