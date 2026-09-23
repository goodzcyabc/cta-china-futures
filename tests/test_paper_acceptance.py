"""纸面验收:缺失日期 / blocked / FAILED 统计、权益对账发现注入错误、配置摘要漂移、PRELIMINARY 阶段报告、演练证据 PENDING。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from cta.analysis import paper_acceptance as pa

DAYS = pd.bdate_range("2026-09-23", periods=4)  # 周三→周一(跨周末)
HOL = pd.DatetimeIndex([])


def _book(
    root: Path,
    name: str,
    days: pd.DatetimeIndex,
    *,
    skip: set[int] = frozenset(),
    snaps: list[str] | None = None,
    failed_day: int | None = None,
    blocked: bool = False,
) -> Path:
    """合成账本:equity 按账本恒等式生成;fills 带 fee;快照带摘要;可选一日 FAILED 日志、一条 blocked。"""
    b = root / name
    (b / "fills").mkdir(parents=True)
    (b / "orders").mkdir()
    (b / "log").mkdir()
    eq, real, fee = 1_000_000.0, 0.0, 0.0
    rows = []
    for i, d in enumerate(days):
        if i in skip:
            continue
        day_fee = 6.0 if i > 0 else 0.0
        day_real = 100.0 * i if i > 1 else 0.0
        mtm = {"CU": 250.0 * i, "AL": -40.0 * i} if i > 0 else {}
        real += day_real
        fee += day_fee
        eq += day_real + sum(mtm.values()) - day_fee
        rows.append(
            {
                "date": str(d.date()),
                "equity": eq,
                "realized_pnl": real,
                "fees_paid": fee,
                "slippage_paid": 10.0 * i,
                "margin_used": 1000.0,
                "n_positions": 2,
                "pnl_by_symbol": json.dumps(mtm),
            }
        )
        fills = (
            [
                {
                    "date": str(d.date()),
                    "symbol": "CU",
                    "contract": "CU2610",
                    "lots": 1.0,
                    "status": "filled",
                    "reason": "",
                    "leg": "rebalance",
                    "price": 70000.0,
                    "fee": day_fee,
                    "slippage": 10.0,
                    "realized_pnl": day_real,
                }
            ]
            if i > 0
            else []
        )
        if blocked and i == 2:
            fills.append(
                {
                    "date": str(d.date()),
                    "symbol": "AL",
                    "contract": "AL2610",
                    "lots": 2.0,
                    "status": "limit_locked",
                    "reason": "limit_locked",
                    "leg": "rebalance",
                }
            )
        if fills:
            pd.DataFrame(fills).to_csv(b / "fills" / f"{d.date()}.csv", index=False)
        snap_digest = (snaps or ["cfg0"] * len(days))[i]
        (b / "orders" / str(d.date())).mkdir()
        (b / "orders" / str(d.date()) / "snapshot.json").write_text(
            json.dumps(
                {
                    "asof": str(d.date()),
                    "config_digest": snap_digest,
                    "instruments_digest": "ins0",
                    "git_sha": "abc1234",
                    "data_manifest": {
                        "primary": "{'sha256': 'p0'}",
                        "secondary": f"{{'coverage': 'SHFE:{i}', 'sha256': 's{i}'}}",
                    },
                }
            ),
            encoding="utf-8",
        )
        log: dict[str, Any] = {"date": str(d.date())}
        if failed_day == i:
            log["failed"] = {"stage": "settle", "error": "LedgerIntegrityError: x"}
        (b / "log" / f"{d.date()}.json").write_text(json.dumps(log), encoding="utf-8")
    pd.DataFrame(rows).to_csv(b / "equity.csv", index=False)
    (b / "state.json").write_text(
        json.dumps(
            {"equity": eq, "cash_start": 1_000_000.0, "last_settled": str(days[-1].date()), "positions": {}}
        ),
        encoding="utf-8",
    )
    return b


def _protocol(root: Path, declared: bool = False) -> Path:
    p = root / "paper_protocol.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    dec = (
        "declared_transitions:\n  - {effective: '2026-09-25', fields: [config_digest], note: 声明的切换}\n"
        if declared
        else "declared_transitions: []\n"
    )
    p.write_text(
        "champion: champ\nchallengers: [chal]\nbooks:\n  champ: {expected_config_digest: cfg0}\n  chal: {expected_config_digest: cfg0}\nexpected_instruments_digest: ins0\n"
        + dec,
        encoding="utf-8",
    )
    return p


def test_missing_days_blocked_and_failed_are_counted(tmp_path: Path) -> None:
    b = pa.load_book(
        _book(tmp_path, "champ", DAYS, skip={2}, failed_day=1, blocked=True), "champ", "champion"
    )
    c = pa.completeness(b, pa.expected_days(DAYS[0], DAYS[-1], HOL))
    assert c["expected"] == 4 and c["present"] == 3 and c["missing"] == str(DAYS[2].date())
    fs, bl = pa.fill_stats(b, DAYS[0], DAYS[-1])
    assert fs["filled"] == 2 and fs["blocked"] == 0  # 第 3 天被 skip,blocked 那条随之不存在
    b2 = pa.load_book(_book(tmp_path / "x", "champ", DAYS, blocked=True), "champ", "champion")
    fs2, bl2 = pa.fill_stats(b2, DAYS[0], DAYS[-1])
    assert (
        fs2["filled"] == 3
        and fs2["blocked"] == 1
        and fs2["fill_rate"] == 0.75
        and bl2.iloc[0]["status"] == "limit_locked"
    )
    f = pa.failures(b, DAYS[0], DAYS[-1])
    assert len(f) == 1 and f.iloc[0]["stage"] == "settle"


def test_expected_days_respect_holidays() -> None:
    d = pa.expected_days(
        pd.Timestamp("2026-09-23"), pd.Timestamp("2026-09-28"), pd.DatetimeIndex([pd.Timestamp("2026-09-25")])
    )
    assert [x.date().isoformat() for x in d] == ["2026-09-23", "2026-09-24", "2026-09-28"]


def test_reconciliation_passes_then_detects_injected_error(tmp_path: Path) -> None:
    root = _book(tmp_path, "champ", DAYS)
    b = pa.load_book(root, "champ", "champion")
    r = pa.reconcile_book(b, DAYS[0], DAYS[-1])
    assert len(r) == 4 and r["ok"].all() and abs(r["fills_fee_diff"].dropna()).max() < 1e-9
    eq = pd.read_csv(root / "equity.csv")
    eq.loc[2, "equity"] += 1.0  # 注入 1 元错误
    eq.to_csv(root / "equity.csv", index=False)
    b2 = pa.load_book(root, "champ", "champion")
    r2 = pa.reconcile_book(b2, DAYS[0], DAYS[-1])
    bad = r2[~r2["ok"]]
    # 权益的水平错误在逐日差里出现两次:注入日 +1,次日 −1(次日的基数被抬高)
    assert list(bad["date"]) == [DAYS[2], DAYS[3]] and list(bad["diff"].round(9)) == [1.0, -1.0]
    w = pa.weekly_reconciliation(r2)
    assert (~w["ok"]).sum() == 2  # 09-25 与 09-28 分属两个 ISO 周


def test_config_drift_is_reported_and_classified(tmp_path: Path) -> None:
    root = _book(tmp_path, "champ", DAYS, snaps=["cfg0", "cfg0", "cfg1", "cfg1"])
    b = pa.load_book(root, "champ", "champion")
    d = pa.drift(b, DAYS[0], DAYS[-1], pa.load_protocol(_protocol(tmp_path)))
    changes = d[d["field"] == "config_digest"]
    assert (changes["category"] == "策略配置变化").any() and not changes[
        changes["category"] == "策略配置变化"
    ]["declared"].iloc[0]
    assert (d["category"] == "与协议清单不符").sum() == 2  # cfg1 的两天不等于清单预期 cfg0
    assert (d[d["field"] == "secondary_sha"]["declared"]).all()  # 交易所段每日增量视为预期
    d2 = pa.drift(b, DAYS[0], DAYS[-1], pa.load_protocol(_protocol(tmp_path / "p2", declared=True)))
    assert d2[(d2["field"] == "config_digest") & (d2["category"] == "策略配置变化")]["declared"].iloc[0]


def test_preliminary_report_and_pending_drills(tmp_path: Path) -> None:
    _book(tmp_path, "champ", DAYS)
    _book(tmp_path, "chal", DAYS)
    proto = _protocol(tmp_path)
    out = tmp_path / "out"
    rep = tmp_path / "rep.md"
    r = pa.run_acceptance(
        tmp_path,
        DAYS[0],
        pd.Timestamp("2026-12-15"),
        out,
        rep,
        proto,
        holidays=HOL,
        n_boot=50,
        drills_dir=tmp_path / "drills",
    )
    assert r.status == "PRELIMINARY" and r.asof == DAYS[-1] and r.reconciliation_ok and r.completeness_ok
    txt = rep.read_text(encoding="utf-8")
    assert "PRELIMINARY" in txt and "PENDING" in txt and r.drills_status == "PENDING" and "样本量不足" in txt
    assert "显著" not in txt
    assert (out / "paired_differences.csv").exists() and (out / "completeness.csv").exists()
    (tmp_path / "drills").mkdir()
    (tmp_path / "drills" / "2026-10-01_x.json").write_text(
        json.dumps(
            {
                "date": "2026-10-01",
                "book": "champ",
                "injected": "rm quotes",
                "detected": True,
                "recovered": True,
                "outcome": "ok",
            }
        ),
        encoding="utf-8",
    )
    r2 = pa.run_acceptance(
        tmp_path, DAYS[0], DAYS[-1], out, rep, proto, holidays=HOL, n_boot=50, drills_dir=tmp_path / "drills"
    )
    assert r2.status == "FINAL" and r2.drills_status == "DONE" and "DONE" in rep.read_text(encoding="utf-8")
    # 只读:账本文件未被改动
    assert not (tmp_path / "champ" / "FAILED.json").exists() and sorted(
        p.name for p in (tmp_path / "champ").iterdir()
    ) == ["equity.csv", "fills", "log", "orders", "state.json"]
