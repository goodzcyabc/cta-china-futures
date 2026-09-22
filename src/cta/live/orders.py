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
from cta.continuous.roll import SymbolPanel
from cta.data.source import DataSource
from cta.execution.plan import SymbolInputs, plan_lots
from cta.instruments.specs import InstrumentTable
from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals, git_sha


def _num(v: object) -> float:
    """Series 元素 → float(显式收窄,避免不同 pandas-stubs 版本下的类型分歧)。"""
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    raise TypeError(f"expected number, got {type(v).__name__}")


def sched_next(row: pd.Series[Any]) -> str:
    """T+1 将持有的合约(面板 sched_next;缺时退化为当日合约)。"""
    v = row["sched_next"] if "sched_next" in row.index else None
    return str(v) if isinstance(v, str) and v else str(row["contract"])


def ref_close(panel: SymbolPanel, contract: str, asof: pd.Timestamp) -> float:
    """定手数的参考价:T 日该合约自身的收盘价;缺则用面板收盘(当日持有合约)。"""
    c = panel.contracts
    if c is not None and (contract, asof) in c.index:
        px = float(c.at[(contract, asof), "close"])
        if np.isfinite(px) and px > 0:
            return px
    return _num(panel.frame.at[asof, "close"])


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
    inputs: dict[str, SymbolInputs] = {}
    info: dict[str, dict[str, Any]] = {}
    for s_, exp in tgt_exp.items():
        s = str(s_)
        f = panels[s].frame
        if asof_ts not in f.index:
            continue
        row = f.loc[asof_ts]
        assert isinstance(row, pd.Series)
        held_lots = float(cur.at[s, "lots"]) if s in cur.index else 0.0
        held_c = str(cur.at[s, "contract"]) if s in cur.index else None
        target_c = sched_next(row)
        ref_px = ref_close(panels[s], target_c, asof_ts)
        inputs[s] = SymbolInputs(
            float(exp), ref_px, _num(row["multiplier"]), _num(row["margin_rate"]), held_lots
        )
        info[s] = {
            "held_contract": held_c,
            "target_contract": target_c,
            "signal_tsmom": float(signals.tsmom.at[asof_ts, s])
            if not np.isnan(signals.tsmom.at[asof_ts, s])
            else None,
            "signal_carry": float(signals.carry.at[asof_ts, s])
            if not np.isnan(signals.carry.at[asof_ts, s])
            else None,
            "signal_receipts_level": (
                float(signals.receipts_level.at[asof_ts, s])
                if signals.receipts_level is not None and not np.isnan(signals.receipts_level.at[asof_ts, s])
                else None
            ),
            "eligible": bool(signals.eligible.at[asof_ts, s]),
        }
    # 唯一的手数规划函数(与引擎共用):T 收盘价定手数 → 保证金上限缩减 → 手数带
    plan = plan_lots(inputs, equity, cfg.portfolio.lot_band, cfg.portfolio.max_margin_usage)
    rows = []
    for s, x in inputs.items():
        want = plan.lots[s]
        i = info[s]
        roll = (
            i["held_contract"] is not None and x.held_lots != 0 and i["held_contract"] != i["target_contract"]
        )
        rows.append(
            {
                "symbol": s,
                "target_contract": i["target_contract"],
                "target_lots": want,
                "target_exposure": float(x.exposure),
                "held_contract": i["held_contract"],
                "held_lots": x.held_lots,
                "roll_required": roll,
                "delta_lots": want - (0.0 if roll else x.held_lots),
                "ref_close": x.ref_price,
                "multiplier": x.multiplier,
                "margin_rate": x.margin_rate,
                "est_margin_cny": abs(want) * x.ref_price * x.multiplier * x.margin_rate
                if np.isfinite(x.ref_price)
                else 0.0,
                "signal_tsmom": i["signal_tsmom"],
                "signal_carry": i["signal_carry"],
                "signal_receipts_level": i["signal_receipts_level"],
                "eligible": i["eligible"],
            }
        )
    orders = pd.DataFrame(rows).set_index("symbol")
    est_margin = plan.margin_after
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
    if plan.scaled and equity > 0:
        snap["warning"] = (
            f"预计保证金占用 {plan.margin_before / equity:.1%} 超上限 {cfg.portfolio.max_margin_usage:.0%},"
            f"已按比例缩减到 {plan.margin_after / equity:.1%};请人工复核"
        )
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
