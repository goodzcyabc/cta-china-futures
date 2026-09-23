"""纸面交易验收(只读;设计日志十八):数据完整率、成交率、权益对账、失败与漂移、共同日期、故障演练证据、champion/challenger 配对差。

只读约定:本模块只读取 paper*/ 目录,任何输出都写到调用方指定的输出目录;不修改账本、不新增账本、不选赢家。
权益对账按账本真实语义:当日权益变化 = 当日成交产生的 realized_pnl + 当日持仓盯市盈亏 − 当日手续费(滑点已在成交价里,不再扣)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from cta.analysis.stats import paired_differences, paired_summary
from cta.data.exchanges.calendar import load_holidays

EQUITY_COLS = [
    "equity",
    "realized_pnl",
    "fees_paid",
    "slippage_paid",
    "margin_used",
    "n_positions",
    "pnl_by_symbol",
]
DRIFT_CATEGORY = {
    "config_digest": "策略配置变化",
    "instruments_digest": "参数表变化",
    "git_sha": "代码变化",
    "primary_sha": "数据版本变化(米筐段)",
    "secondary_sha": "数据增量(交易所段,预期每日变化)",
}


@dataclass
class Book:
    name: str
    root: Path
    role: str
    equity: pd.DataFrame
    fills: pd.DataFrame
    snapshots: pd.DataFrame
    logs: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    failed: dict[str, Any] | None = None


@dataclass
class AcceptanceResult:
    status: str  # PRELIMINARY | FINAL
    asof: pd.Timestamp
    reconciliation_ok: bool
    completeness_ok: bool
    undeclared_drift: int
    drills_status: str
    report_path: Path
    summary: pd.DataFrame


# ---------- 读取 ----------
def load_protocol(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data


def _sha_from_manifest(s: str) -> str:
    m = re.search(r"'sha256':\s*'([0-9a-f]+)'", str(s))
    return m.group(1) if m else ""


def _coverage_from_manifest(s: str) -> str:
    m = re.search(r"'coverage':\s*'([^']*)'", str(s))
    return m.group(1) if m else ""


def load_book(root: Path, name: str, role: str) -> Book:
    root = Path(root)
    eq_path = root / "equity.csv"
    if eq_path.exists():
        eq = pd.read_csv(eq_path)
        eq["date"] = pd.to_datetime(eq["date"])
        eq = eq.set_index("date").sort_index()
    else:
        eq = pd.DataFrame(columns=EQUITY_COLS)
    parts = []
    for f in sorted((root / "fills").glob("*.csv")) if (root / "fills").exists() else []:
        try:
            df = pd.read_csv(f)
        except pd.errors.EmptyDataError:
            continue
        if df.empty:
            continue
        df["file_date"] = pd.Timestamp(f.stem)
        parts.append(df)
    fills = (
        pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["date", "symbol", "status"])
    )
    if "date" in fills.columns and len(fills):
        fills["date"] = pd.to_datetime(fills["date"])
    snaps = []
    for d in sorted((root / "orders").glob("*/snapshot.json")) if (root / "orders").exists() else []:
        try:
            j = json.loads(d.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        man = j.get("data_manifest", {}) or {}
        snaps.append(
            {
                "date": pd.Timestamp(j.get("asof", d.parent.name)),
                "config_digest": str(j.get("config_digest", "")),
                "instruments_digest": str(j.get("instruments_digest", "")),
                "git_sha": str(j.get("git_sha", "")),
                "primary_sha": _sha_from_manifest(man.get("primary", "")) if isinstance(man, dict) else "",
                "secondary_sha": _sha_from_manifest(man.get("secondary", ""))
                if isinstance(man, dict)
                else "",
                "coverage": _coverage_from_manifest(man.get("secondary", ""))
                if isinstance(man, dict)
                else "",
            }
        )
    snapshots = (
        pd.DataFrame(snaps).set_index("date").sort_index()
        if snaps
        else pd.DataFrame(
            columns=[
                "config_digest",
                "instruments_digest",
                "git_sha",
                "primary_sha",
                "secondary_sha",
                "coverage",
            ]
        )
    )
    logs: dict[str, dict[str, Any]] = {}
    for f in sorted((root / "log").glob("*.json")) if (root / "log").exists() else []:
        try:
            logs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logs[f.stem] = {"date": f.stem, "unreadable": True}
    state = (
        json.loads((root / "state.json").read_text(encoding="utf-8"))
        if (root / "state.json").exists()
        else {}
    )
    failed = (
        json.loads((root / "FAILED.json").read_text(encoding="utf-8"))
        if (root / "FAILED.json").exists()
        else None
    )
    return Book(name, root, role, eq, fills, snapshots, logs, state, failed)


# ---------- 工程验收 ----------
def expected_days(
    start: pd.Timestamp, end: pd.Timestamp, holidays: pd.DatetimeIndex | None = None
) -> pd.DatetimeIndex:
    """预期交易日:周一至周五且不在公告休市日(与纸面 runner 同一规则)。"""
    hol = holidays if holidays is not None else load_holidays()
    days = [d for d in pd.bdate_range(start, end) if d not in hol]
    return pd.DatetimeIndex(days)


def completeness(book: Book, days: pd.DatetimeIndex) -> dict[str, Any]:
    have = pd.DatetimeIndex(book.equity.index) if len(book.equity) else pd.DatetimeIndex([])
    missing = [d for d in days if d not in have]
    return {
        "book": book.name,
        "role": book.role,
        "expected": int(len(days)),
        "present": int(len(days) - len(missing)),
        "rate": (len(days) - len(missing)) / len(days) if len(days) else np.nan,
        "missing": ",".join(str(d.date()) for d in missing),
    }


def fill_stats(book: Book, start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict[str, Any], pd.DataFrame]:
    f = book.fills
    if f.empty or "date" not in f.columns:
        return {"book": book.name, "filled": 0, "blocked": 0, "fill_rate": np.nan}, pd.DataFrame()
    w = f[(f["date"] >= start) & (f["date"] <= end)]
    filled = int((w["status"] == "filled").sum())
    blocked_df = w[w["status"] != "filled"].copy()
    blocked = int(len(blocked_df))
    cols = [
        c
        for c in ("date", "symbol", "contract", "lots", "status", "reason", "leg")
        if c in blocked_df.columns
    ]
    blocked_df = blocked_df[cols]
    blocked_df.insert(0, "book", book.name)
    rate = filled / (filled + blocked) if (filled + blocked) else np.nan
    return {"book": book.name, "filled": filled, "blocked": blocked, "fill_rate": rate}, blocked_df


def _mtm_sum(cell: Any) -> float:
    if isinstance(cell, str) and cell.strip():
        try:
            return float(sum(float(v) for v in json.loads(cell).values()))
        except (json.JSONDecodeError, TypeError, ValueError):
            return float("nan")
    return 0.0


def reconcile_book(book: Book, start: pd.Timestamp, end: pd.Timestamp, abs_tol: float = 1e-4) -> pd.DataFrame:
    """逐日:Δ权益 vs Δ已实现 + 当日盯市 − Δ手续费;另用当日 fills 交叉核对手续费(与已实现盈亏,若有该列)。
    第一行(账本开立日)以 cash_start 为基;换月/多腿日:已实现与手续费都是当日累计量之差,天然涵盖多腿;无成交日:Δ已实现 = Δ手续费 = 0。"""
    eq = book.equity
    rows: list[dict[str, Any]] = []
    if eq.empty:
        return pd.DataFrame(
            columns=["book", "date", "d_equity", "d_realized", "mtm", "d_fees", "expected", "diff", "ok"]
        )
    cash_start = float(book.state.get("cash_start", eq["equity"].iloc[0]))
    idx = pd.DatetimeIndex(eq.index)
    for i, d in enumerate(idx):
        if d < start or d > end:
            continue
        cur = eq.iloc[i]
        if i == 0:
            prev_eq, prev_real, prev_fee = cash_start, 0.0, 0.0
        else:
            p = eq.iloc[i - 1]
            prev_eq, prev_real, prev_fee = float(p["equity"]), float(p["realized_pnl"]), float(p["fees_paid"])
        d_eq = float(cur["equity"]) - prev_eq
        d_real = float(cur["realized_pnl"]) - prev_real
        d_fee = float(cur["fees_paid"]) - prev_fee
        mtm = _mtm_sum(cur.get("pnl_by_symbol", "{}"))
        expected = d_real + mtm - d_fee
        diff = d_eq - expected
        fills_fee = fills_real = float("nan")
        fills_fee_diff = float("nan")
        if not book.fills.empty and "date" in book.fills.columns:
            fd = book.fills[(book.fills["date"] == d) & (book.fills["status"] == "filled")]
            if len(fd):
                fills_fee = float(fd["fee"].sum()) if "fee" in fd.columns else float("nan")
                if "realized_pnl" in fd.columns:
                    fills_real = float(fd["realized_pnl"].fillna(0.0).sum())
            else:
                fills_fee = 0.0
        if np.isfinite(fills_fee):
            fills_fee_diff = fills_fee - d_fee
        ok = bool(
            np.isfinite(diff)
            and abs(diff) <= abs_tol
            and (not np.isfinite(fills_fee_diff) or abs(fills_fee_diff) <= abs_tol)
        )
        rows.append(
            {
                "book": book.name,
                "date": d,
                "d_equity": d_eq,
                "d_realized": d_real,
                "mtm": mtm,
                "d_fees": d_fee,
                "expected": expected,
                "diff": diff,
                "fills_fee": fills_fee,
                "fills_fee_diff": fills_fee_diff,
                "fills_realized": fills_real,
                "ok": ok,
            }
        )
    return pd.DataFrame(rows)


def weekly_reconciliation(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame(columns=["book", "week", "n_days", "max_abs_diff", "ok"])
    d = daily.copy()
    d["week"] = pd.DatetimeIndex(d["date"]).strftime("%G-W%V")
    g = d.groupby(["book", "week"])
    out = pd.DataFrame(
        {
            "n_days": g.size(),
            "max_abs_diff": g["diff"].apply(lambda s: float(np.nanmax(np.abs(s.to_numpy(dtype=float))))),
            "ok": g["ok"].all(),
        }
    ).reset_index()
    return out


def failures(book: Book, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for day, j in book.logs.items():
        try:
            d = pd.Timestamp(day)
        except ValueError:
            continue
        if d < start or d > end:
            continue
        if "failed" in j:
            f = j["failed"] if isinstance(j["failed"], dict) else {"stage": "?", "error": str(j["failed"])}
            rows.append(
                {
                    "book": book.name,
                    "date": d,
                    "stage": f.get("stage", "?"),
                    "error": str(f.get("error", ""))[:200],
                    "source": "log.failed",
                }
            )
        if "orders_error" in j:
            rows.append(
                {
                    "book": book.name,
                    "date": d,
                    "stage": "orders",
                    "error": str(j["orders_error"])[:200],
                    "source": "log.orders_error(旧格式,已被吞的失败)",
                }
            )
    if book.failed is not None:
        rows.append(
            {
                "book": book.name,
                "date": pd.Timestamp(book.failed.get("date", start)),
                "stage": book.failed.get("stage", "?"),
                "error": str(book.failed.get("error", ""))[:200],
                "source": "FAILED.json(当前存在)",
            }
        )
    return pd.DataFrame(rows, columns=["book", "date", "stage", "error", "source"])


def drift(book: Book, start: pd.Timestamp, end: pd.Timestamp, protocol: dict[str, Any]) -> pd.DataFrame:
    """相邻订单快照之间的摘要变化(含验收期首日与其前一次快照的比较),按字段分类;与协议清单里声明的切换比对。"""
    s = book.snapshots
    rows: list[dict[str, Any]] = []
    if s.empty:
        return pd.DataFrame(
            rows, columns=["book", "date", "field", "old", "new", "category", "declared", "note"]
        )
    declared = protocol.get("declared_transitions", []) or []
    before = s[s.index < start]
    window = s[(s.index >= start) & (s.index <= end)]
    seq = pd.concat([before.tail(1), window]) if len(before) else window
    fields = ["config_digest", "instruments_digest", "git_sha", "primary_sha", "secondary_sha"]
    prev: pd.Series[Any] | None = None
    for d, row in seq.iterrows():
        if prev is not None and pd.Timestamp(str(d)) >= start:
            for f in fields:
                if str(row[f]) != str(prev[f]):
                    dec = [
                        t
                        for t in declared
                        if pd.Timestamp(t.get("effective")) == pd.Timestamp(str(d))
                        and f in (t.get("fields") or [])
                    ]
                    rows.append(
                        {
                            "book": book.name,
                            "date": pd.Timestamp(str(d)),
                            "field": f,
                            "old": str(prev[f]),
                            "new": str(row[f]),
                            "category": DRIFT_CATEGORY[f],
                            "declared": bool(dec) or f == "secondary_sha",
                            "note": dec[0].get("note", "")
                            if dec
                            else ("交易所数据每日增量" if f == "secondary_sha" else "未在协议清单中声明"),
                        }
                    )
        prev = row
    exp_cfg = ((protocol.get("books") or {}).get(book.name) or {}).get("expected_config_digest")
    exp_ins = protocol.get("expected_instruments_digest")
    for d, row in window.iterrows():
        if exp_cfg and str(row["config_digest"]) != str(exp_cfg):
            rows.append(
                {
                    "book": book.name,
                    "date": pd.Timestamp(str(d)),
                    "field": "config_digest",
                    "old": str(exp_cfg),
                    "new": str(row["config_digest"]),
                    "category": "与协议清单不符",
                    "declared": False,
                    "note": "快照配置摘要 ≠ 协议清单预期",
                }
            )
        if exp_ins and str(row["instruments_digest"]) != str(exp_ins):
            rows.append(
                {
                    "book": book.name,
                    "date": pd.Timestamp(str(d)),
                    "field": "instruments_digest",
                    "old": str(exp_ins),
                    "new": str(row["instruments_digest"]),
                    "category": "与协议清单不符",
                    "declared": False,
                    "note": "快照参数表摘要 ≠ 协议清单预期",
                }
            )
    return pd.DataFrame(rows, columns=["book", "date", "field", "old", "new", "category", "declared", "note"])


def common_range(books: list[Book]) -> dict[str, Any]:
    idx: pd.DatetimeIndex | None = None
    for b in books:
        bi = pd.DatetimeIndex(b.equity.index)
        idx = bi if idx is None else idx.intersection(bi)
    if idx is None or len(idx) == 0:
        return {"start": None, "end": None, "n_common_days": 0}
    return {"start": str(idx.min().date()), "end": str(idx.max().date()), "n_common_days": int(len(idx))}


DRILL_REQUIRED = ("date", "book", "injected", "detected", "recovered", "outcome")


def drill_evidence(evidence_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """故障恢复演练证据:evidence_dir/*.json,每个必须含 date/book/injected/detected/recovered/outcome;没有合格证据 → PENDING。"""
    items: list[dict[str, Any]] = []
    p = Path(evidence_dir)
    if p.exists():
        for f in sorted(p.glob("*.json")):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                items.append({"file": f.name, "valid": False, "reason": "JSON 解析失败"})
                continue
            missing = [k for k in DRILL_REQUIRED if k not in j]
            items.append(
                {
                    "file": f.name,
                    "valid": not missing,
                    "reason": f"缺字段 {missing}" if missing else "",
                    **{k: j.get(k) for k in DRILL_REQUIRED},
                }
            )
    status = "DONE" if any(i.get("valid") for i in items) else "PENDING"
    return status, items


# ---------- 汇总 ----------
def _stop_condition(
    champion: pd.Series[Any], challenger: pd.Series[Any], lags: int, seed: int, start: pd.Timestamp
) -> dict[str, Any]:
    """预注册停账条件:配对差 t < −3 且 challenger 回撤差 < −10pp,连续两个月末成立。触及 ≠ champion 更优。"""
    pdf = paired_differences(champion, challenger, start)
    if pdf.empty:
        return {"evaluable": False, "months_evaluated": 0, "triggered": False, "detail": "无共同日期"}
    dates = pd.Series(pd.DatetimeIndex(pdf.index), index=pdf.index)
    month_ends = dates.groupby(pd.DatetimeIndex(pdf.index).to_period("M")).max()
    flags = []
    for me in month_ends:
        me_ts = pd.Timestamp(me)
        ca = champion[pd.DatetimeIndex(champion.index) <= me_ts]
        cb = challenger[pd.DatetimeIndex(challenger.index) <= me_ts]
        s = paired_summary(ca, cb, lags=lags, n_boot=200, seed=seed, start=start)
        flags.append(bool(np.isfinite(s["t"]) and s["t"] < -3 and s["dd_diff"] < -0.10))
    if len(flags) < 2:
        return {
            "evaluable": False,
            "months_evaluated": len(flags),
            "triggered": False,
            "detail": "不足两个月末,无法评估",
        }
    return {
        "evaluable": True,
        "months_evaluated": len(flags),
        "triggered": bool(flags[-1] and flags[-2]),
        "detail": ",".join("触" if f else "否" for f in flags),
    }


def run_acceptance(
    root: Path,
    start: pd.Timestamp,
    end: pd.Timestamp,
    out_dir: Path,
    report_path: Path,
    protocol_path: Path,
    strict: bool = False,
    asof: pd.Timestamp | None = None,
    lags: int = 5,
    block: int = 10,
    n_boot: int = 2000,
    seed: int = 20260923,
    drills_dir: Path | None = None,
    holidays: pd.DatetimeIndex | None = None,
) -> AcceptanceResult:
    root, out_dir, report_path = Path(root), Path(out_dir), Path(report_path)
    protocol = load_protocol(protocol_path)
    champ_name = str(protocol["champion"])
    books = [load_book(root / champ_name, champ_name, "champion")] + [
        load_book(root / str(n), str(n), "challenger") for n in protocol.get("challengers", [])
    ]
    last = max((pd.Timestamp(b.equity.index.max()) for b in books if len(b.equity)), default=start)
    asof_ts = asof if asof is not None else min(end, last)
    status = "PRELIMINARY" if asof_ts < end else "FINAL"
    days = expected_days(start, asof_ts, holidays)
    comp = pd.DataFrame([completeness(b, days) for b in books])
    fill_rows, blocked_parts, rec_parts, fail_parts, drift_parts = [], [], [], [], []
    for b in books:
        fs, bl = fill_stats(b, start, asof_ts)
        fill_rows.append(fs)
        if len(bl):
            blocked_parts.append(bl)
        rec_parts.append(reconcile_book(b, start, asof_ts))
        fail_parts.append(failures(b, start, asof_ts))
        drift_parts.append(drift(b, start, asof_ts, protocol))
    fills_df = pd.DataFrame(fill_rows)
    blocked_df = (
        pd.concat(blocked_parts, ignore_index=True)
        if blocked_parts
        else pd.DataFrame(columns=["book", "date", "symbol", "contract", "lots", "status", "reason"])
    )
    rec_df = pd.concat(rec_parts, ignore_index=True) if rec_parts else pd.DataFrame()
    weekly = weekly_reconciliation(rec_df)
    fail_df = pd.concat(fail_parts, ignore_index=True)
    drift_df = pd.concat(drift_parts, ignore_index=True)
    cr = common_range(books)
    drills_status, drills = drill_evidence(drills_dir if drills_dir is not None else root / "docs" / "drills")
    champ = books[0]
    paired_rows = []
    stop_rows = []
    for b in books[1:]:
        if len(champ.equity) and len(b.equity):
            ce = champ.equity["equity"].loc[
                (champ.equity.index >= start - pd.Timedelta(days=10)) & (champ.equity.index <= asof_ts)
            ]
            be = b.equity["equity"].loc[
                (b.equity.index >= start - pd.Timedelta(days=10)) & (b.equity.index <= asof_ts)
            ]
            # 起算点:第一条配对差用 start 当日相对其前一交易日的收益,所以取 start 之前一条权益作基
            s = paired_summary(ce, be, lags=lags, block=block, n_boot=n_boot, seed=seed, start=start)
            s["challenger"] = b.name
            paired_rows.append(s)
            sc = _stop_condition(ce, be, lags, seed, start)
            sc["challenger"] = b.name
            stop_rows.append(sc)
    paired_df = pd.DataFrame(paired_rows)
    stop_df = pd.DataFrame(stop_rows)
    # ---- 输出 ----
    out_dir.mkdir(parents=True, exist_ok=True)
    comp.to_csv(out_dir / "completeness.csv", index=False)
    fills_df.to_csv(out_dir / "fills.csv", index=False)
    blocked_df.to_csv(out_dir / "blocked.csv", index=False)
    rec_df.to_csv(out_dir / "reconciliation.csv", index=False)
    weekly.to_csv(out_dir / "reconciliation_weekly.csv", index=False)
    fail_df.to_csv(out_dir / "failures.csv", index=False)
    drift_df.to_csv(out_dir / "config_drift.csv", index=False)
    paired_df.to_csv(out_dir / "paired_differences.csv", index=False)
    stop_df.to_csv(out_dir / "stop_condition.csv", index=False)
    rec_ok = bool(rec_df["ok"].all()) if len(rec_df) else True
    comp_ok = bool((comp["rate"].fillna(1.0) >= 1.0).all()) if len(comp) else False  # 尚无预期交易日 → 无缺失
    undeclared = int((~drift_df["declared"]).sum()) if len(drift_df) else 0
    summary = pd.DataFrame(
        {
            "book": comp["book"],
            "role": comp["role"],
            "present/expected": comp["present"].astype(str) + "/" + comp["expected"].astype(str),
            "fill_rate": fills_df["fill_rate"].round(4) if len(fills_df) else np.nan,
            "reconciled": [
                bool(rec_df[rec_df["book"] == b]["ok"].all()) if len(rec_df) else True for b in comp["book"]
            ],
            "failures": [int((fail_df["book"] == b).sum()) for b in comp["book"]],
            "undeclared_drift": [
                int(((drift_df["book"] == b) & (~drift_df["declared"])).sum()) if len(drift_df) else 0
                for b in comp["book"]
            ],
        }
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(
            status,
            start,
            end,
            asof_ts,
            days,
            comp,
            fills_df,
            blocked_df,
            rec_df,
            weekly,
            fail_df,
            drift_df,
            cr,
            drills_status,
            drills,
            paired_df,
            stop_df,
            protocol,
            protocol_path,
            lags,
            block,
            n_boot,
            seed,
            out_dir,
        ),
        encoding="utf-8",
    )
    return AcceptanceResult(status, asof_ts, rec_ok, comp_ok, undeclared, drills_status, report_path, summary)


def _rate(x: Any) -> str:
    return f"{float(x):.1%}" if x is not None and np.isfinite(float(x)) else "n/a"


def _fmt_pct(x: Any) -> str:
    return f"{float(x):+.2%}" if x is not None and np.isfinite(float(x)) else "n/a"


def _render_report(
    status: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    asof: pd.Timestamp,
    days: pd.DatetimeIndex,
    comp: pd.DataFrame,
    fills_df: pd.DataFrame,
    blocked_df: pd.DataFrame,
    rec_df: pd.DataFrame,
    weekly: pd.DataFrame,
    fail_df: pd.DataFrame,
    drift_df: pd.DataFrame,
    cr: dict[str, Any],
    drills_status: str,
    drills: list[dict[str, Any]],
    paired_df: pd.DataFrame,
    stop_df: pd.DataFrame,
    protocol: dict[str, Any],
    protocol_path: Path,
    lags: int,
    block: int,
    n_boot: int,
    seed: int,
    out_dir: Path,
) -> str:
    lines: list[str] = []
    banner = (
        f"**PRELIMINARY —— 验收期 {start.date()} → {end.date()} 尚未结束,本报告截至 {asof.date()},只是阶段性结果。**"
        if status == "PRELIMINARY"
        else f"FINAL —— 验收期 {start.date()} → {end.date()} 已结束。"
    )
    lines += [
        f"# 纸面交易验收报告({status},截至 {asof.date()})",
        "",
        banner,
        "",
        f"预注册规则:`docs/design_log.md` 十八;协议清单:`{protocol_path}`;champion = `{protocol['champion']}`,challenger = {', '.join('`' + str(c) + '`' for c in protocol.get('challengers', []))}。**不选赢家,不采用、不淘汰任何版本。**",
        "",
    ]
    lines += [
        "## 0. 摘要",
        "",
        "| 账本 | 角色 | 有数据/预期交易日 | 成交率 | 逐日对账 | 失败记录 | 未声明漂移 |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, c in comp.iterrows():
        fr = fills_df[fills_df["book"] == c["book"]]["fill_rate"]
        rec_ok = bool(rec_df[rec_df["book"] == c["book"]]["ok"].all()) if len(rec_df) else True
        nf = int((fail_df["book"] == c["book"]).sum())
        nd = int(((drift_df["book"] == c["book"]) & (~drift_df["declared"])).sum()) if len(drift_df) else 0
        lines.append(
            f"| {c['book']} | {c['role']} | {c['present']}/{c['expected']} | {_rate(fr.iloc[0]) if len(fr) else 'n/a'} | {'一致' if rec_ok else '**不一致**'} | {nf} | {nd} |"
        )
    if len(days) == 0:
        lines += [
            "",
            f"> 验收期从 {start.date()} 起算,账本最新日期为 {asof.date()}:**验收期尚未产生任何数据**,下面各节为空是正常的;"
            "09-16 → 09-22 的记录期数据不计入验收(设计日志 18.2 第 6 条)。",
        ]
    lines += [
        "",
        f"预期交易日 = 周一至周五且不在 `configs/holidays.csv`,{start.date()} → {asof.date()} 共 {len(days)} 天。五本账共同有效日期:{cr['start']} → {cr['end']}({cr['n_common_days']} 天)。",
        "",
    ]
    lines += ["## 1. 数据完整率", "", "| 账本 | 预期 | 有数据 | 完整率 | 缺失日期 |", "|---|---|---|---|---|"]
    for _, c in comp.iterrows():
        lines.append(
            f"| {c['book']} | {c['expected']} | {c['present']} | {float(c['rate']):.1%} | {c['missing'] or '—'} |"
        )
    lines += [
        "",
        "预注册阈值:验收期内每个交易日五本账都有权益行(FAILED 日在后续运行中修复重放算完整;最终仍缺失 → 不通过)。",
        "",
    ]
    lines += [
        "## 2. 成交率(按腿)",
        "",
        "| 账本 | filled | blocked | filled/(filled+blocked) |",
        "|---|---|---|---|",
    ]
    for _, f in fills_df.iterrows():
        lines.append(f"| {f['book']} | {f['filled']} | {f['blocked']} | {_rate(f['fill_rate'])} |")
    lines += ["", "阈值 ≥ 95%。blocked 逐条:", ""]
    if len(blocked_df):
        lines += ["| 账本 | 日期 | 品种 | 合约 | 手数 | 状态 | 原因 |", "|---|---|---|---|---|---|---|"]
        for _, r in blocked_df.iterrows():
            lines.append(
                f"| {r['book']} | {pd.Timestamp(r['date']).date()} | {r.get('symbol', '')} | {r.get('contract', '')} | {r.get('lots', '')} | {r['status']} | {r.get('reason', '')} |"
            )
    else:
        lines.append("(无)")
    lines += ["", "## 3. 权益对账(账本语义:Δ权益 = Δ已实现 + 当日盯市 − Δ手续费;滑点已在成交价内,不再扣)", ""]
    if len(rec_df):
        bad = rec_df[~rec_df["ok"]]
        lines += [
            f"逐日检查 {len(rec_df)} 条,不一致 {len(bad)} 条;容差 1e-4 元(浮点)。另用当日 fills 交叉核对手续费(旧格式 fills 无 realized_pnl 列,只核手续费)。",
            "",
        ]
        lines += ["| 账本 | 周 | 天数 | 最大|差| | 通过 |", "|---|---|---|---|---|"]
        for _, w in weekly.iterrows():
            lines.append(
                f"| {w['book']} | {w['week']} | {w['n_days']} | {float(w['max_abs_diff']):.6f} | {'是' if w['ok'] else '**否**'} |"
            )
        if len(bad):
            lines += [
                "",
                "**不一致明细**:",
                "",
                "| 账本 | 日期 | Δ权益 | 期望 | 差额 | fills 手续费差 |",
                "|---|---|---|---|---|---|",
            ]
            for _, r in bad.iterrows():
                lines.append(
                    f"| {r['book']} | {pd.Timestamp(r['date']).date()} | {float(r['d_equity']):,.2f} | {float(r['expected']):,.2f} | {float(r['diff']):,.6f} | {r['fills_fee_diff']} |"
                )
    else:
        lines.append("(验收期内无权益行)")
    lines += ["", "## 4. 失败记录(FAILED.json 与日志)", ""]
    if len(fail_df):
        lines += ["| 账本 | 日期 | 阶段 | 错误 | 来源 |", "|---|---|---|---|---|"]
        for _, r in fail_df.iterrows():
            lines.append(
                f"| {r['book']} | {pd.Timestamp(r['date']).date()} | {r['stage']} | {str(r['error']).replace('|', '/')} | {r['source']} |"
            )
    else:
        lines.append("(无)")
    lines += [
        "",
        "## 5. 配置 / 参数表 / 代码 / 数据漂移(基于订单快照 config_digest、instruments_digest、git_sha、data_manifest)",
        "",
    ]
    if len(drift_df):
        lines += [
            "| 账本 | 日期 | 字段 | 旧 | 新 | 分类 | 已声明 | 说明 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for _, r in drift_df.iterrows():
            lines.append(
                f"| {r['book']} | {pd.Timestamp(r['date']).date()} | {r['field']} | {str(r['old'])[:16]} | {str(r['new'])[:16]} | {r['category']} | {'是' if r['declared'] else '**否**'} | {r['note']} |"
            )
    else:
        lines.append("(验收期内无快照变化)")
    lines += [
        "",
        "默认只检测和报告,不阻止每日作业。协议清单声明的切换视为合法;未声明的策略配置/参数表/代码/数据版本变化需要解释。",
        "",
    ]
    lines += [
        "## 6. 故障恢复演练证据",
        "",
        f"状态:**{drills_status}**(证据目录 `docs/drills/*.json`,必需字段 {', '.join(DRILL_REQUIRED)};没有合格证据即 PENDING,不凭空判定通过)。",
        "",
    ]
    for it in drills:
        lines.append(
            f"- `{it['file']}`:{'合格' if it.get('valid') else '不合格 ' + str(it.get('reason', ''))}"
            + (
                f" —— {it.get('date')} {it.get('book')} 注入 {it.get('injected')} / 检出 {it.get('detected')} / 恢复 {it.get('recovered')} / 结果 {it.get('outcome')}"
                if it.get("valid")
                else ""
            )
        )
    lines += ["", "## 7. champion / challenger 配对差(预注册 18.3;只报告,不选择)", ""]
    if len(paired_df) and int(paired_df["n_days"].max()) > 0:
        insufficient = paired_df[~paired_df["sample_sufficient"]]
        if len(insufficient):
            lines += [
                f"> **样本量不足**:{', '.join(insufficient['challenger'])} 的共同交易日少于 60 天(当前 {int(paired_df['n_days'].max())} 天)。下面的数字只是记录,不能用来比较优劣;标准误按 17.5 的估计要 12 个月才降到 ±0.65。",
                "",
            ]
        lines += [
            "| challenger | 共同日 | 配对差年化均值 | NW SE(年化) | t | bootstrap 95% 区间(年化) | 夏普(日频,champion / challenger) | 最大回撤(champion / challenger) | 回撤差 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in paired_df.iterrows():
            lines.append(
                f"| {r['challenger']} | {int(r['n_days'])} | {_fmt_pct(r['ann_mean'])} | {_fmt_pct(r['nw_se_ann'])} | {float(r['t']):.2f} | [{_fmt_pct(r['boot_ci_low_ann'])}, {_fmt_pct(r['boot_ci_high_ann'])}] | {float(r['sharpe_champion_daily']):.2f} / {float(r['sharpe_challenger_daily']):.2f} | {_fmt_pct(r['mdd_champion'])} / {_fmt_pct(r['mdd_challenger'])} | {_fmt_pct(r['dd_diff'])} |"
            )
        lines += [
            "",
            f"方法:d_t = challenger 日收益 − champion 日收益,各自以自身前一交易日权益为分母,只用双方共同有效日期;Newey–West lag={lags};移动块 bootstrap 块长 {block} 个交易日、重采样 {n_boot} 次、随机种子 {seed}(可复现);夏普为日频年化({'243'} 个交易日),样本短时无意义。",
            "",
        ]
        lines += [
            "预注册停账条件(唯一允许的动作):配对差 t < −3 且 challenger 回撤差 < −10pp,连续两个月末成立 → 可停账止损。**触及停账条件 ≠ champion 已被统计证明更优;未触及也不说明 challenger 更好。**",
            "",
        ]
        lines += ["| challenger | 可评估 | 已评估月末数 | 是否触及 | 逐月 |", "|---|---|---|---|---|"]
        for _, r in stop_df.iterrows():
            lines.append(
                f"| {r['challenger']} | {'是' if r['evaluable'] else '否'} | {r['months_evaluated']} | {'**触及**' if r['triggered'] else '未触及'} | {r['detail']} |"
            )
    else:
        lines.append("(验收期内尚无配对日期,无法计算)")
    lines += [
        "",
        "## 8. 方法与参数",
        "",
        f"- 输出目录:`{out_dir}`;协议清单:`{protocol_path}`;随机种子 {seed};bootstrap {n_boot} 次、块长 {block};NW lag {lags};对账容差 1e-4 元。",
        "- 本报告只读取 paper*/ 目录,不修改任何账本文件;不新增账本;不据结果采用或淘汰版本。",
        f"- 与回测的比较(18.4)留到验收期结束再做;本阶段共同日期 {cr['n_common_days']} 天。",
        "",
    ]
    return "\n".join(lines)
