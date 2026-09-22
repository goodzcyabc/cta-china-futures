"""实盘出单:与研究流程共用 build_panels / compute_signals,只是数据截止到 as-of 日。

输出:目标手数、与当前持仓的差异(含换月)、输入快照与指纹。所有判断都可在次日开盘前复核。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.config import StrategyConfig
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable
from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals, git_sha


def _num(v: object) -> float:
    """Series 元素 → float(显式收窄,避免不同 pandas-stubs 版本下的类型分歧)。"""
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    raise TypeError(f"expected number, got {type(v).__name__}")


def _load_positions(path: Path | None) -> pd.DataFrame:
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=["symbol", "contract", "lots"]).set_index("symbol")
    df = pd.read_csv(path, dtype={"symbol": str, "contract": str})
    return df.set_index("symbol")[["contract", "lots"]]


def generate_orders(
    cfg: StrategyConfig,
    src: DataSource,
    specs: InstrumentTable,
    asof: str,
    equity: float,
    positions_csv: Path | None,
    out_dir: Path,
    positions: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """positions(index=symbol,列 contract/lots)优先于 positions_csv;纸面路径直接传 DataFrame,不经过正式文件。"""
    asof_ts = pd.Timestamp(asof)
    panels = build_panels(src, cfg, specs, end=asof_ts)
    if not panels:
        raise RuntimeError("no panels built; check data path / as-of date")
    unverified = sorted(s for s in panels if not specs[s].verified)
    if unverified:
        raise RuntimeError(f"refusing to generate orders for unverified instruments: {unverified}")
    last_dates = {s: p.frame.index.max() for s, p in panels.items()}
    stale = {s: str(d.date()) for s, d in last_dates.items() if d < asof_ts - pd.Timedelta(days=7)}
    signals = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    if asof_ts not in signals.target.index:
        raise RuntimeError(
            f"as-of {asof} is not a trading day in data (last: {signals.target.index.max().date()})"
        )
    tgt_exp = signals.target.loc[asof_ts].fillna(0.0)
    cur = positions if positions is not None else _load_positions(positions_csv)
    rows = []
    for s_, exp in tgt_exp.items():
        s = str(s_)
        f = panels[s].frame
        row = f.loc[asof_ts] if asof_ts in f.index else None
        if row is None:
            continue
        ref_px = _num(row["close"])
        mult = _num(row["multiplier"])
        want = float(np.round(exp * equity / (ref_px * mult))) if ref_px > 0 else 0.0
        held_lots = float(cur.at[s, "lots"]) if s in cur.index else 0.0
        held_c = str(cur.at[s, "contract"]) if s in cur.index else None
        target_c = str(row["contract"])
        roll = held_c is not None and held_lots != 0 and held_c != target_c
        rows.append(
            {
                "symbol": s,
                "target_contract": target_c,
                "target_lots": want,
                "target_exposure": float(exp),
                "held_contract": held_c,
                "held_lots": held_lots,
                "roll_required": roll,
                "delta_lots": want - (0.0 if roll else held_lots),
                "ref_close": ref_px,
                "multiplier": mult,
                "margin_rate": _num(row["margin_rate"]),
                "est_margin_cny": abs(want) * ref_px * mult * _num(row["margin_rate"]),
                "signal_tsmom": float(signals.tsmom.at[asof_ts, s])
                if not np.isnan(signals.tsmom.at[asof_ts, s])
                else None,
                "signal_carry": float(signals.carry.at[asof_ts, s])
                if not np.isnan(signals.carry.at[asof_ts, s])
                else None,
                "signal_receipts_level": (
                    float(signals.receipts_level.at[asof_ts, s])
                    if signals.receipts_level is not None
                    and not np.isnan(signals.receipts_level.at[asof_ts, s])
                    else None
                ),
                "eligible": bool(signals.eligible.at[asof_ts, s]),
            }
        )
    orders = pd.DataFrame(rows).set_index("symbol")
    est_margin = float(orders["est_margin_cny"].sum())
    emu: float | None = est_margin / equity if equity > 0 else None
    out = out_dir / asof
    out.mkdir(parents=True, exist_ok=True)
    orders.to_csv(out / "orders.csv")
    snap = {
        "asof": asof,
        "equity": equity,
        "config_digest": cfg.digest(),
        "instruments_digest": specs.digest(),
        "git_sha": git_sha(),
        "data_manifest": src.manifest(),
        "stale_symbols": stale,
        "est_margin_usage": est_margin / equity if equity > 0 else None,
        "orders_sha256": hashlib.sha256(orders.to_csv().encode()).hexdigest()[:16],
    }
    if emu is not None and emu > cfg.portfolio.max_margin_usage:
        snap["warning"] = "预计保证金占用超上限,引擎会按比例缩减;请人工复核"
    (out / "snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {
        "summary": {
            "asof": asof,
            "warning": snap.get("warning"),
            "n_symbols": int(len(orders)),
            "n_trades": int((orders["delta_lots"] != 0).sum()),
            "n_rolls": int(orders["roll_required"].sum()),
            "est_margin_usage": snap["est_margin_usage"],
            "stale_symbols": stale,
            "out": str(out),
        },
        "orders": orders,
        "snapshot": snap,
    }
