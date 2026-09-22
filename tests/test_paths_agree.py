"""研究路径与实盘路径逐日一致性(真实数据,无数据时跳过):
同一段历史上,引擎(全历史面板 + 信号一次算完)与"逐日 as-of 出单 → 次日按合约行情成交 → 盯市"的纸面路径,
每一天的持仓手数、权益必须完全相等。这是 design_log 17.6 第 4 项"路径统一"的验收测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

DATA = Path("data/ricecta/data")
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="需要本地米筐/交易所数据")


def _quotes_for(panels: dict, d: pd.Timestamp) -> dict:  # type: ignore[type-arg]
    from cta.execution.ledger import quotes_from_frame

    parts = []
    for p in panels.values():
        c = p.contracts
        if c is not None and d in c.index.get_level_values("date"):
            parts.append(c.xs(d, level="date")[["open", "settle", "prev_settle"]])
    return quotes_from_frame(pd.concat(parts)) if parts else {}


def test_engine_and_paper_path_agree_day_by_day(tmp_path: Path) -> None:
    from cta.backtest.engine import run_backtest
    from cta.config import load_config
    from cta.data.exchanges.source import default_stitched
    from cta.execution import ledger
    from cta.instruments.specs import load_instruments
    from cta.live.orders import generate_orders
    from cta.pipeline import _receipts_of, _reg_events_of, build_panels, compute_signals

    cfg = load_config(Path("configs/strategy_v03.yaml"))
    specs = load_instruments()
    src = default_stitched(DATA)
    start, end = pd.Timestamp("2025-03-03"), pd.Timestamp("2025-04-11")  # ~28 个交易日,含多次换月
    panels = build_panels(src, cfg, specs)
    sig = compute_signals(
        panels, cfg, receipts=_receipts_of(src), specs=specs, reg_events=_reg_events_of(src, cfg)
    )
    target = sig.target.loc[(sig.target.index >= start) & (sig.target.index <= end)]
    res = run_backtest(
        panels,
        target,
        specs,
        cfg.backtest.initial_capital_cny,
        max_margin_usage=cfg.portfolio.max_margin_usage,
        slippage_ticks=cfg.execution.slippage_ticks,
        lot_band=cfg.portfolio.lot_band,
    )
    # 纸面路径:每天 as-of 出单(数据截到当天),次日用合约级行情成交、盯市;账本状态与引擎共用同一组函数
    state = ledger.Ledger(equity=cfg.backtest.initial_capital_cny)
    pending: pd.DataFrame | None = None
    symbols = list(res.positions.columns)
    n_rolls = 0
    for d in res.equity.index:
        q = _quotes_for(panels, d)
        if pending is not None:
            plan = {
                str(s): (str(r["target_contract"]), float(r["target_lots"])) for s, r in pending.iterrows()
            }
            fills = ledger.execute_day(state, plan, q, specs, cfg.execution.slippage_ticks, d)
            n_rolls += sum(1 for f in fills if f.get("leg") == "roll_open" and f["status"] == "filled")
        ledger.mark(state, q, specs, strict=False)
        rows = [{"symbol": s, "contract": p.contract, "lots": p.lots} for s, p in state.positions.items()]
        positions = pd.DataFrame(rows, columns=["symbol", "contract", "lots"]).set_index("symbol")
        meta = generate_orders(
            cfg, src, specs, str(d.date()), state.equity, None, tmp_path / "orders", positions=positions
        )
        pending = meta["orders"]
        eng = res.positions.loc[d]
        mine = {s: (state.positions[s].lots if s in state.positions else 0.0) for s in symbols}
        diff = {s: (mine[s], float(eng[s])) for s in symbols if mine[s] != float(eng[s])}
        assert not diff, f"{d.date()} 持仓不一致: {diff}"
        assert abs(state.equity - float(res.equity.loc[d])) < 1e-6, f"{d.date()} 权益不一致"
    assert n_rolls >= 1, "测试窗口应至少包含一次换月才有说服力"
