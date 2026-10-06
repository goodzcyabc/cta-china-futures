"""官方结算价基线与执行统一的分解(design_log 17.6 第 5 项;写于 2026-09-22)。

四级阶梯,每级只改一件事:
  A 旧引擎(engine_legacy)+ 收盘价代结算 —— 2026-09-22 前报告的口径,用来确认复现;
  B 新引擎(cta.execution 统一语义)+ 收盘价代结算 —— 执行统一的影响;
  C 新引擎 + 交易所官方结算价,持仓路径固定为 B 的 —— 纯记账口径的影响;
  D 新引擎 + 交易所官方结算价,完整递归(结算权益继续影响次日定手数)—— **新的正式基线**。
每个配置 × {全样本, 样本内, 样本外};官方结算价覆盖率单列(official 模式缺一即报错,不会静默回退)。
输出:results/settle_baseline/<版本>_<期>_<级>.json / equity_*.csv、summary.csv,docs/settle_baseline.md。

用法:PYTHONPATH=src python3 scripts/settle_baseline.py [--only v0.3]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.backtest import engine, engine_legacy  # noqa: E402
from cta.config import DataCfg, load_config  # noqa: E402
from cta.data.exchanges.source import default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import (  # noqa: E402
    _receipts_of,
    _reg_events_of,
    build_panels,
    compute_signals,
    summarize_result,
)

RQ = Path("data/ricecta/data")
OUT = Path("results/settle_baseline")
CONFIGS = {
    "v0.1": "configs/strategy.yaml",
    "v0.3": "configs/strategy_v03.yaml",
    "v0.3p": "configs/strategy_v03p.yaml",
    "v0.1r": "configs/strategy_v01r.yaml",
    "v0.5": "configs/strategy_v05.yaml",
}
PERIODS = {
    "full": ("2016-01-04", "2026-09-18"),
    "is": ("2016-01-04", "2021-12-31"),
    "oos": ("2022-01-04", "2026-06-05"),
}
KEYS = [
    "年化收益",
    "夏普(月频)",
    "最大回撤",
    "年化名义换手(倍)",
    "年化手续费占权益",
    "年化滑点占权益",
    "未成交腿数",
    "未盯市持仓日数",
]


def _row(
    version: str, period: str, variant: str, stats: dict[str, float], extra: dict[str, Any]
) -> dict[str, Any]:
    r: dict[str, Any] = {"version": version, "period": period, "variant": variant}
    r.update({k: stats.get(k) for k in KEYS})
    r.update(extra)
    return r


def run(versions: list[str]) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    specs = load_instruments()
    rows: list[dict[str, Any]] = []
    for ver in versions:
        cfg = load_config(Path(CONFIGS[ver]))
        cfg_vc = cfg.model_copy(update={"data": DataCfg(settle="vendor_close")})
        src_off = default_stitched(RQ, official_settle=True)
        src_vc = default_stitched(RQ, official_settle=False)
        panels_off = build_panels(src_off, cfg, specs)  # official 模式:缺官方结算价即报错
        panels_vc = build_panels(src_vc, cfg_vc, specs)
        coverage = {s: float(p.frame["settle_official"].mean()) for s, p in panels_off.items()}
        assert min(coverage.values()) == 1.0, coverage
        sig = compute_signals(
            panels_off,
            cfg,
            receipts=_receipts_of(src_off),
            specs=specs,
            reg_events=_reg_events_of(src_off, cfg),
        )
        kw = dict(
            max_margin_usage=cfg.portfolio.max_margin_usage,
            slippage_ticks=cfg.execution.slippage_ticks,
            lot_band=cfg.portfolio.lot_band,
        )
        cap = cfg.backtest.initial_capital_cny
        for pname, (a, b) in PERIODS.items():
            idx = sig.target.index
            target = sig.target.loc[(idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(b))]
            results: dict[str, Any] = {}
            if pname == "full":
                results["A_legacy_close"] = engine_legacy.run_backtest(
                    panels_vc,
                    target,
                    specs,
                    cap,
                    cfg.portfolio.max_margin_usage,
                    cfg.execution.slippage_ticks,
                    cfg.portfolio.lot_band,
                )
            b_res = engine.run_backtest(panels_vc, target, specs, cap, **kw)
            results["B_unified_close"] = b_res
            results["C_unified_official_fixedpath"] = engine.run_backtest(
                panels_off, target, specs, cap, lots_override=b_res.positions, **kw
            )
            results["D_unified_official"] = engine.run_backtest(panels_off, target, specs, cap, **kw)
            for tag, res in results.items():
                stats, first_active = summarize_result(res, specs)
                stem = f"{ver}_{pname}_{tag}"
                res.equity.to_csv(OUT / f"equity_{stem}.csv")
                if tag == "D_unified_official":
                    res.positions.to_csv(OUT / f"positions_{stem}.csv")
                    res.pnl_by_symbol.to_csv(OUT / f"pnl_by_symbol_{stem}.csv")
                extra = {
                    "first_active": str(first_active.date()),
                    "period_start": str(res.equity.index[0].date()),
                    "period_end": str(res.equity.index[-1].date()),
                    "official_settle_coverage_min": min(coverage.values()),
                }
                (OUT / f"{stem}.json").write_text(
                    json.dumps({"stats": stats, **extra}, ensure_ascii=False, indent=1, default=str),
                    encoding="utf-8",
                )
                rows.append(_row(ver, pname, tag, stats, extra))
                print(
                    f"{ver:6s} {pname:4s} {tag:28s} 年化 {stats['年化收益']:+.2%} 夏普 {stats['夏普(月频)']:.3f} "
                    f"回撤 {stats['最大回撤']:.2%} 换手 {stats['年化名义换手(倍)']:.1f}x 费+滑 "
                    f"{stats['年化手续费占权益'] + stats['年化滑点占权益']:.2%}",
                    flush=True,
                )
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "summary.csv", index=False)
    return df


def write_doc(df: pd.DataFrame) -> None:
    lines = [
        "# 官方结算价基线与执行统一的分解(2026-09-22;脚本 `scripts/settle_baseline.py`)",
        "",
        "四级阶梯,每级只改一件事:A 旧引擎 + 收盘价代结算(旧报告口径)→ B 新引擎 + 收盘价代结算(执行统一的影响)"
        "→ C 新引擎 + 官方结算价、持仓路径固定为 B(纯记账口径)→ D 新引擎 + 官方结算价、完整递归(**新正式基线**)。",
        "官方结算价覆盖率:22 个生产品种、所有持有合约-日 = 100%(official 模式缺一即报错,不回退收盘价)。",
        "",
    ]
    for pname, title in [
        ("full", "全样本 2016-01-04 → 2026-09-18"),
        ("is", "样本内 2016 → 2021"),
        ("oos", "样本外 2022-01-04 → 2026-06-05"),
    ]:
        sub = df[df["period"] == pname]
        lines += [
            f"## {title}",
            "",
            "| 版本 | 级 | 年化 | 夏普(月) | 最大回撤 | 换手/年 | 费+滑/年 | 未成交腿 | 未盯市日 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in sub.iterrows():
            lines.append(
                f"| {r['version']} | {r['variant']} | {r['年化收益']:+.1%} | {r['夏普(月频)']:.2f} | {r['最大回撤']:.1%} | "
                f"{r['年化名义换手(倍)']:.0f}× | {r['年化手续费占权益'] + r['年化滑点占权益']:.2%} | {int(r['未成交腿数'])} | {int(r['未盯市持仓日数'])} |"
            )
        lines.append("")
    Path("docs/settle_baseline.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    df = run(args.only or list(CONFIGS))
    write_doc(df)
    print(df.to_string())
