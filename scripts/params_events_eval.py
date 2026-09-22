"""推导事件(params 逐日比对)vs 公告事件(events.csv 公告行)的召回/精确;docs/data_exchange_params.md §6 的数字由此而来。

    PYTHONPATH=src python3 scripts/params_events_eval.py --exchanges SHFE,INE

公告事件 = events.csv 中 notice_id 非空、param ∈ {margin, fee}、direction=up 的行按 (品种, 参数, 生效交易日) 去重;
生效日不是交易日的取其后第一个交易日,晚于最后一个参数文件的不计。匹配 = 同品种同参数、事件日与生效日相差 ≤tol 个交易日。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.data.exchanges import params as xp  # noqa: E402
from cta.data.exchanges.base import Store  # noqa: E402


def notice_events(ev: pd.DataFrame, exchange: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    n = ev[
        (ev.exchange == exchange)
        & (ev.notice_id != "")
        & ev.param.isin(["margin", "fee"])
        & (ev.direction == "up")
    ].copy()
    n = n.dropna(subset=["effective_date"])
    n = n[(n.effective_date <= sessions[-1]) & (n.effective_date >= sessions[0])]
    pos = np.minimum(sessions.searchsorted(n["effective_date"].values, side="left"), len(sessions) - 1)
    n["eff_session"] = sessions[pos]
    n["new_f"] = pd.to_numeric(n["new_value"], errors="coerce")
    g = (
        n.groupby(["symbol", "param", "eff_session"])
        .agg(
            new_vals=("new_f", lambda s: tuple(sorted(set(s.dropna())))),
            scope_all=("contract_scope", lambda s: bool((s == "all").any())),
            holiday=("reason", lambda s: bool(s.str.contains("holiday").any())),
            notice=("notice_id", "first"),
        )
        .reset_index()
    )
    return g


def evaluate(
    exchange: str, ev: pd.DataFrame, store: Store, tols: tuple[int, ...] = (0, 1, 2)
) -> pd.DataFrame:
    df = store.read_days(exchange, "params")
    sessions = pd.DatetimeIndex(sorted(df["date"].unique()))
    der = xp.derive_events(store, exchange, df=df).reset_index(drop=True)
    der["effective_date"] = pd.to_datetime(der["effective_date"])
    der["new_value"] = der["new_value"].astype(float)
    g = notice_events(ev, exchange, sessions)
    sess_pos = {d: i for i, d in enumerate(sessions)}
    der["pos"] = der["effective_date"].map(sess_pos)
    g["pos"] = g["eff_session"].map(sess_pos)
    rows = []
    for tol in tols:
        matched_n = np.zeros(len(g), dtype=bool)
        matched_d = np.zeros(len(der), dtype=bool)
        value_ok = np.zeros(len(g), dtype=bool)
        for i, r in enumerate(g.itertuples(index=False)):
            cand = der[(der.symbol == r.symbol) & (der.param == r.param) & ((der.pos - r.pos).abs() <= tol)]
            if len(cand):
                matched_n[i] = True
                matched_d[cand.index] = True
                value_ok[i] = any(abs(v - c) < 1e-9 for v in r.new_vals for c in cand.new_value)
        non_hol_d = (der.reason != "holiday").to_numpy()
        rows.append(
            {
                "exchange": exchange,
                "tol": tol,
                "notice_events": len(g),
                "notice_scope_all": int(g.scope_all.sum()),
                "notice_nonholiday": int((~g.holiday).sum()),
                "recall": matched_n.mean(),
                "recall_scope_all": matched_n[g.scope_all.to_numpy()].mean(),
                "recall_nonholiday": matched_n[~g.holiday.to_numpy()].mean(),
                "value_match_among_matched": value_ok[matched_n].mean(),
                "derived": len(der),
                "derived_nonholiday": int(non_hol_d.sum()),
                "precision": matched_d.mean(),
                "precision_nonholiday": matched_d[non_hol_d].mean(),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exchanges", default="SHFE,INE")
    ap.add_argument("--events", default="data/external/exchange_events/events.csv")
    args = ap.parse_args()
    ev = pd.read_csv(args.events, dtype=str).fillna("")
    ev["effective_date"] = pd.to_datetime(ev["effective_date"], errors="coerce")
    st = Store()
    parts = [evaluate(e.strip().upper(), ev, st) for e in args.exchanges.split(",")]
    out = pd.concat(parts, ignore_index=True)
    pd.set_option("display.width", 250)
    print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
