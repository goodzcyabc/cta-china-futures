"""纸面账本:成交、换月、涨跌停顺延、盯市与权益对账(合成数据,不联网)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cta.instruments.specs import load_instruments
from cta.paper.book import PaperBook, Position


def _dq(rows: dict[str, tuple[float, float, float]]) -> pd.DataFrame:
    """contract -> (open, settle, prev_settle)。"""
    return pd.DataFrame({c: {"open": v[0], "settle": v[1], "prev_settle": v[2]} for c, v in rows.items()}).T


def test_fill_mark_and_roll_reconcile(tmp_path: Path) -> None:
    specs = load_instruments()
    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    cu = specs["CU"]
    d1 = pd.Timestamp("2026-09-10")
    orders = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2610",
                "target_lots": 2.0,
                "held_contract": None,
                "held_lots": 0.0,
                "roll_required": False,
                "delta_lots": 2.0,
            }
        ]
    )
    q1 = _dq({"CU2610": (70000.0, 70500.0, 69800.0)})
    fills = book.fill_orders(orders, q1, specs, d1, slippage_ticks=1.0)
    assert fills.iloc[0]["status"] == "filled" and fills.iloc[0]["price"] == 70000.0 + cu.tick
    pnl = book.mark_to_market(q1, specs, d1)
    fee = cu.fee(70000.0 + cu.tick, 2)  # 手续费按含滑点的成交价(与引擎同口径)
    expected = 1_000_000.0 - fee + 2 * (70500.0 - (70000.0 + cu.tick)) * cu.multiplier
    assert np.isclose(book.state.equity, expected) and np.isclose(pnl["CU"], 2 * (70500.0 - 70010.0) * 5)
    # 次日换月:平 CU2610、开 CU2611 各 2 手;开盘价与结算价不同
    d2 = pd.Timestamp("2026-09-11")
    orders2 = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2611",
                "target_lots": 2.0,
                "held_contract": "CU2610",
                "held_lots": 2.0,
                "roll_required": True,
                "delta_lots": 2.0,
            }
        ]
    )
    q2 = _dq({"CU2610": (70600.0, 70400.0, 70500.0), "CU2611": (70900.0, 70800.0, 70700.0)})
    f2 = book.fill_orders(orders2, q2, specs, d2, slippage_ticks=1.0)
    assert len(f2) == 2 and set(f2["contract"]) == {"CU2610", "CU2611"}
    eq_before_mark = book.state.equity
    book.mark_to_market(q2, specs, d2)
    close_pnl = 2 * ((70600.0 - cu.tick) - 70500.0) * 5  # 平旧合约:开盘价−1跳 相对上日结算
    open_pnl = 2 * (70800.0 - (70900.0 + cu.tick)) * 5  # 新合约:结算 相对 成交价
    fees = cu.fee(70600.0 - cu.tick, 2) + cu.fee(70900.0 + cu.tick, 2)
    assert np.isclose(book.state.equity, expected + close_pnl + open_pnl - fees)
    assert book.state.positions["CU"].contract == "CU2611" and book.state.positions["CU"].lots == 2.0
    assert eq_before_mark == expected + close_pnl - fees  # 盯市前:平仓盈亏已实现,新仓未盯市
    # 涨停开盘:买单顺延,不成交
    d3 = pd.Timestamp("2026-09-14")
    orders3 = pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2611",
                "target_lots": 3.0,
                "held_contract": "CU2611",
                "held_lots": 2.0,
                "roll_required": False,
                "delta_lots": 1.0,
            }
        ]
    )
    q3 = _dq({"CU2611": (70800.0 * (1 + cu.limit_pct), 71000.0, 70800.0)})
    f3 = book.fill_orders(orders3, q3, specs, d3, slippage_ticks=1.0)
    assert f3.iloc[0]["status"] == "limit_locked" and book.state.positions["CU"].lots == 2.0
    book.mark_to_market(q3, specs, d3)
    book.append_equity(d3, {}, book.margin_used(q3, specs))
    eq = pd.read_csv(tmp_path / "equity.csv")
    assert len(eq) == 1 and eq.iloc[0]["n_positions"] == 1
    # 状态持久化往返
    book.save()
    book2 = PaperBook(tmp_path)
    assert book2.state.equity == book.state.equity and book2.state.positions["CU"].ref_price == 71000.0


def test_settlement_gate() -> None:
    from cta.paper.runner import settlement_published

    d = pd.Timestamp("2026-09-17")
    assert not settlement_published(d, now=pd.Timestamp("2026-09-17 11:21"))
    assert settlement_published(d, now=pd.Timestamp("2026-09-17 16:30"))
    assert settlement_published(d, now=pd.Timestamp("2026-09-18 09:00"))
    assert not settlement_published(pd.Timestamp("2026-09-18"), now=pd.Timestamp("2026-09-17 23:00"))


def test_intraday_snapshot_is_rejected() -> None:
    import gzip
    import json
    from pathlib import Path

    import pytest

    from cta.data.exchanges import shfe
    from cta.data.exchanges.base import NotFinalError

    fx = Path("tests/fixtures/exchanges/shfe")
    raw_files = sorted(fx.glob("*kx*")) or sorted(fx.glob("*quotes*"))
    assert raw_files, "需要 shfe quotes fixture"
    f = raw_files[0]
    if f.suffix == ".gz":
        with gzip.open(f, "rb") as fh:
            raw = fh.read()
    else:
        raw = f.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    for r in data.get("o_curinstrument", []):
        r["SETTLEMENTPRICE"] = ""  # 模拟盘中快照:结算价全空
    with pytest.raises(NotFinalError):
        shfe.parse_quotes(json.dumps(data).encode("utf-8"), pd.Timestamp("2026-09-11"))


# ---- 2026-09-22 防线:有限值、换月原子性、盯市完整性、幂等落盘、日步全有或全无 ----


def test_nan_open_is_not_filled(tmp_path: Path) -> None:
    """当日零成交/停牌(交易所 open 为空):不成交、记 no_quote、权益不变。此前会按 NaN 价成交并把权益污染成 NaN。"""
    specs = load_instruments()
    book = PaperBook(tmp_path, initial_capital=3_000_000.0)
    orders = pd.DataFrame([{"symbol": "NI", "target_contract": "NI2204", "target_lots": 2.0}])
    dq = _dq({"NI2204": (np.nan, 267700.0, 267700.0)})  # 2022-03-10 上期所镍停牌
    f = book.fill_orders(orders, dq, specs, pd.Timestamp("2022-03-10"), slippage_ticks=1.0)
    assert f.iloc[0]["status"] == "no_quote" and "NI" not in book.state.positions
    assert book.state.equity == 3_000_000.0


def test_roll_is_atomic(tmp_path: Path) -> None:
    """换月两腿同进退:旧腿撞停或新腿缺行情时两腿都不动,不抛异常、不留空仓。"""
    specs = load_instruments()
    cu = specs["CU"]
    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    book.state.positions["CU"] = Position("CU2610", 2.0, 70000.0)
    orders = pd.DataFrame([{"symbol": "CU", "target_contract": "CU2611", "target_lots": 2.0}])
    # 旧腿(平多 = 卖)开盘跌停:此前旧腿 continue 后新腿走到 _apply_fill 抛 RuntimeError
    q_old_locked = _dq(
        {"CU2610": (70000.0 * (1 - cu.limit_pct), 69000.0, 70000.0), "CU2611": (70900.0, 70800.0, 70700.0)}
    )
    f = book.fill_orders(orders, q_old_locked, specs, pd.Timestamp("2026-09-11"), slippage_ticks=1.0)
    assert len(f) == 2 and set(f["status"]) == {"roll_blocked"}
    assert book.state.positions["CU"].contract == "CU2610" and book.state.positions["CU"].lots == 2.0
    # 新腿缺行情:此前会平掉旧腿、把账本留在空仓
    q_new_missing = _dq({"CU2610": (70600.0, 70400.0, 70500.0)})
    f2 = book.fill_orders(orders, q_new_missing, specs, pd.Timestamp("2026-09-12"), slippage_ticks=1.0)
    assert set(f2["status"]) == {"roll_blocked"} and book.state.positions["CU"].contract == "CU2610"
    assert book.state.equity == 1_000_000.0


def test_mark_to_market_requires_finite_settle(tmp_path: Path) -> None:
    import pytest

    from cta.paper.book import BookIntegrityError

    specs = load_instruments()
    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    book.state.positions["CU"] = Position("CU2610", 2.0, 70000.0)
    d = pd.Timestamp("2026-09-11")
    with pytest.raises(BookIntegrityError):  # 持仓合约当日无行情:此前静默跳过 = 当天零盈亏
        book.mark_to_market(_dq({"CU2611": (1.0, 1.0, 1.0)}), specs, d)
    with pytest.raises(BookIntegrityError):  # 结算价非有限
        book.mark_to_market(_dq({"CU2610": (70000.0, np.nan, 70000.0)}), specs, d)
    assert book.state.equity == 1_000_000.0 and book.state.positions["CU"].ref_price == 70000.0


def test_equity_csv_is_idempotent_per_date(tmp_path: Path) -> None:
    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    d = pd.Timestamp("2026-09-11")
    book.append_equity(d, {"CU": 1.0}, 0.0)
    book.state.equity = 999.0
    book.append_equity(d, {"CU": 2.0}, 0.0)  # 重跑同一日:替换而不是追加
    eq = pd.read_csv(tmp_path / "equity.csv")
    assert len(eq) == 1 and eq.iloc[0]["equity"] == 999.0


def test_save_refuses_non_finite_state(tmp_path: Path) -> None:
    import pytest

    from cta.paper.book import BookIntegrityError

    book = PaperBook(tmp_path, initial_capital=1_000_000.0)
    book.state.equity = float("nan")
    with pytest.raises(BookIntegrityError):
        book.save()
    assert PaperBook(tmp_path).state.equity == 1_000_000.0  # 磁盘上的状态没被污染


def test_step_is_all_or_nothing(tmp_path: Path, monkeypatch: object) -> None:
    """出单失败 → 当日不落盘、写 FAILED.json、抛 PaperStepError;修复后重跑同一日成功且 equity.csv 无重复行。"""
    import pytest

    from cta.config import load_config
    from cta.paper import runner

    specs = load_instruments()
    cfg = load_config(Path("configs/strategy.yaml"))
    d0, d1 = pd.Timestamp("2026-09-10"), pd.Timestamp("2026-09-11")
    book = PaperBook(tmp_path, initial_capital=cfg.backtest.initial_capital_cny)
    book.state.positions["CU"] = Position("CU2610", 2.0, 70000.0)
    book.state.last_settled, book.state.pending_orders_date = str(d0.date()), str(d0.date())
    book.save()
    od = tmp_path / "orders" / str(d0.date())
    od.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "CU",
                "target_contract": "CU2610",
                "target_lots": 3.0,
                "held_contract": "CU2610",
                "held_lots": 2.0,
                "roll_required": False,
                "delta_lots": 1.0,
            }
        ]
    ).to_csv(od / "orders.csv", index=False)
    quotes = pd.DataFrame(
        [{"date": d1, "contract": "CU2610", "open": 70000.0, "settle": 70500.0, "prev_settle": 69800.0}]
    )

    class _Ex:
        def quotes(self) -> pd.DataFrame:
            return quotes

    kw = dict(cfg=cfg, specs=specs, src=object(), ex=_Ex(), paper_dir=tmp_path, do_ingest=False)
    kw["holidays"] = pd.DatetimeIndex([])

    def boom(*a: object, **k: object) -> dict[str, object]:
        raise RuntimeError("as-of 2026-09-11 is not a trading day in data")

    monkeypatch.setattr(runner, "generate_orders", boom)  # type: ignore[attr-defined]
    with pytest.raises(runner.PaperStepError):
        runner.step(d1, **kw)  # type: ignore[arg-type]
    st = PaperBook(tmp_path).state
    assert st.last_settled == str(d0.date()) and st.positions["CU"].lots == 2.0  # 状态未推进
    assert (tmp_path / "FAILED.json").exists() and not (tmp_path / "equity.csv").exists()
    assert (tmp_path / "log" / f"{d1.date()}.json").exists()
    # 修复后重跑同一日
    monkeypatch.setattr(  # type: ignore[attr-defined]
        runner, "generate_orders", lambda *a, **k: {"summary": {"n_trades": 0, "warning": None}}
    )
    log = runner.step(d1, **kw)  # type: ignore[arg-type]
    st = PaperBook(tmp_path).state
    assert st.last_settled == str(d1.date()) and st.positions["CU"].lots == 3.0
    assert st.pending_orders_date == str(d1.date()) and not (tmp_path / "FAILED.json").exists()
    eq = pd.read_csv(tmp_path / "equity.csv")
    assert len(eq) == 1 and str(eq.iloc[0]["date"]) == str(d1.date()) and "failed" not in log
    assert (tmp_path / "fills" / f"{d1.date()}.csv").exists()


def test_step_leaves_no_partial_artifacts_when_order_writing_fails(
    tmp_path: Path, monkeypatch: object
) -> None:
    """出单函数写出一半文件后失败:正式 orders/、positions.csv、equity.csv、state.json 一个不动;修复后重跑全部就位。"""
    import pytest

    from cta.config import load_config
    from cta.paper import runner

    specs = load_instruments()
    cfg = load_config(Path("configs/strategy.yaml"))
    d0, d1 = pd.Timestamp("2026-09-10"), pd.Timestamp("2026-09-11")
    book = PaperBook(tmp_path, initial_capital=cfg.backtest.initial_capital_cny)
    book.state.positions["CU"] = Position("CU2610", 2.0, 70000.0)
    book.state.last_settled, book.state.pending_orders_date = str(d0.date()), str(d0.date())
    book.save()
    book.positions_csv()  # 正式 positions.csv 记录旧持仓 2 手
    od = tmp_path / "orders" / str(d0.date())
    od.mkdir(parents=True)
    pd.DataFrame([{"symbol": "CU", "target_contract": "CU2610", "target_lots": 3.0}]).to_csv(
        od / "orders.csv", index=False
    )
    quotes = pd.DataFrame(
        [{"date": d1, "contract": "CU2610", "open": 70000.0, "settle": 70500.0, "prev_settle": 69800.0}]
    )

    class _Ex:
        def quotes(self) -> pd.DataFrame:
            return quotes

    kw = dict(cfg=cfg, specs=specs, src=object(), ex=_Ex(), paper_dir=tmp_path, do_ingest=False)
    kw["holidays"] = pd.DatetimeIndex([])

    def half_written(
        cfg: object, src: object, specs: object, asof: str, *a: object, **k: object
    ) -> dict[str, object]:
        out = Path(str(a[2]))  # 第 7 个位置参数 out_dir(runner 传的是 .txn/<日>/orders)
        (out / asof).mkdir(parents=True, exist_ok=True)
        (out / asof / "orders.csv").write_text(
            "symbol,target_contract,target_lots\nCU,CU2610,", encoding="utf-8"
        )
        raise RuntimeError("disk full while writing snapshot")

    monkeypatch.setattr(runner, "generate_orders", half_written)  # type: ignore[attr-defined]
    with pytest.raises(runner.PaperStepError):
        runner.step(d1, **kw)  # type: ignore[arg-type]
    assert not (tmp_path / "orders" / str(d1.date())).exists()  # 半个订单文件没有进正式目录
    pos = pd.read_csv(tmp_path / "positions.csv")
    assert pos.iloc[0]["lots"] == 2.0  # 正式持仓文件仍是旧持仓
    assert not (tmp_path / "equity.csv").exists() and PaperBook(tmp_path).state.positions["CU"].lots == 2.0
    assert (
        tmp_path / ".txn" / str(d1.date()) / "orders" / str(d1.date()) / "orders.csv"
    ).exists()  # 取证留在 .txn

    def good(
        cfg: object, src: object, specs: object, asof: str, *a: object, **k: object
    ) -> dict[str, object]:
        out = Path(str(a[2]))
        (out / asof).mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"symbol": "CU", "target_contract": "CU2610", "target_lots": 3.0}]).to_csv(
            out / asof / "orders.csv", index=False
        )
        return {"summary": {"n_trades": 0}}

    monkeypatch.setattr(runner, "generate_orders", good)  # type: ignore[attr-defined]
    runner.step(d1, **kw)  # type: ignore[arg-type]
    assert (tmp_path / "orders" / str(d1.date()) / "orders.csv").exists()
    assert pd.read_csv(tmp_path / "positions.csv").iloc[0]["lots"] == 3.0
    assert PaperBook(tmp_path).state.positions["CU"].lots == 3.0
    assert not (tmp_path / ".txn" / str(d1.date())).exists() and not (tmp_path / "FAILED.json").exists()
    assert len(pd.read_csv(tmp_path / "equity.csv")) == 1
