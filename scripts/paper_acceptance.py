"""纸面交易验收(只读):完整率、成交率、权益对账、失败与漂移、共同日期、演练证据、champion/challenger 配对差。

用法:PYTHONPATH=src python3 scripts/paper_acceptance.py --start 2026-09-23 --end 2026-12-15 [--strict] [--asof YYYY-MM-DD]
验收期未结束 → 生成标有 PRELIMINARY 的阶段报告。--strict 时任一账本权益对账不一致 → 退出码 1。
只写 results/paper_acceptance/ 与 report/paper_acceptance_<end>.md;不修改任何 paper*/ 文件。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cta.analysis.paper_acceptance import run_acceptance  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--asof", default=None, help="截止日(默认 = min(end, 账本最新日期))")
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="results/paper_acceptance")
    ap.add_argument("--report", default=None, help="默认 report/paper_acceptance_<end>.md")
    ap.add_argument("--protocol", default="configs/paper_protocol.yaml")
    ap.add_argument("--drills", default="docs/drills")
    ap.add_argument("--strict", action="store_true", help="对账不一致时退出码 1")
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--block", type=int, default=10)
    ap.add_argument("--lags", type=int, default=5)
    args = ap.parse_args()
    end = pd.Timestamp(args.end)
    report = Path(args.report) if args.report else Path("report") / f"paper_acceptance_{end.date()}.md"
    r = run_acceptance(
        Path(args.root),
        pd.Timestamp(args.start),
        end,
        Path(args.out),
        report,
        Path(args.protocol),
        strict=args.strict,
        asof=pd.Timestamp(args.asof) if args.asof else None,
        lags=args.lags,
        block=args.block,
        n_boot=args.n_boot,
        seed=args.seed,
        drills_dir=Path(args.drills),
    )
    print(
        f"[{r.status}] 截至 {r.asof.date()}  对账 {'一致' if r.reconciliation_ok else '不一致'}  完整率 {'全满' if r.completeness_ok else '有缺失'}  未声明漂移 {r.undeclared_drift}  演练 {r.drills_status}"
    )
    print(r.summary.to_string(index=False))
    print(f"-> {r.report_path}")
    if args.strict and not r.reconciliation_ok:
        print("STRICT: 权益对账不一致", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
