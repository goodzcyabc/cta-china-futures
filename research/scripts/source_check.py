"""数据路径校验:v0.3 champion 在"米筐历史 + 交易所增量"(stitched,正式基线)与"纯交易所公开数据"上各跑一遍。

不计试验:策略与参数一字不动,不据此做任何选择;目的是让没有米筐数据的人知道,只用交易所公开数据能复现到什么程度、差在哪里。
纯交易所数据分两种主力规则:max_oi(前一日持仓最大,纸面/实盘在用)与 oi_1.1x(复刻米筐主力表);
另做两个单变量互换(只换主力表,行情、元数据、仓单不动),定位差异来源。
分期是同一次回测按日期切开(不是像 docs/research/settle_baseline.md 那样每期重新起跑),所以与那张表不逐位相同。
输出:results/source_check/<路径>/(标准回测产物)、docs/research/source_check.md。

用法:python research/scripts/source_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # research/(cta_research)

from cta.analysis.stats import paired_summary  # noqa: E402
from cta.config import load_config  # noqa: E402
from cta.data.exchanges.source import ExchangeSource, default_stitched  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import run_research  # noqa: E402
from cta.risk.metrics import perf_stats  # noqa: E402

RQ = Path("data/ricecta/data")
CONFIG = Path("configs/strategy_v03.yaml")
OUT = Path("results/source_check")
DOC = Path("docs/research/source_check.md")
PERIODS = {
    "全样本": ("2016-01-04", "2026-06-05"),
    "样本内": ("2016-01-04", "2021-12-31"),
    "样本外": ("2022-01-04", "2026-06-05"),
}


class _SwapDominant:
    """只把主力表换成另一个源的,其余(行情、元数据、仓单)不动。"""

    def __init__(self, base: Any, dominant_from: Any):
        self.base, self.dominant_from = base, dominant_from

    def dominant_map(self) -> pd.DataFrame:
        out: pd.DataFrame = self.dominant_from.dominant_map()
        return out

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


def _period_stats(e: pd.Series, first_active: pd.Timestamp, a: str, b: str) -> dict[str, float]:
    """与 summarize_result 同口径:从首个持仓日起算;分期起点用前一日权益作分母。"""
    s = pd.Timestamp(a)
    if s <= first_active:
        return perf_stats(e.loc[first_active:b])
    return perf_stats(e.loc[e.index[e.index < s][-1] : b])


def _agree(
    a: pd.DataFrame, b: pd.DataFrame, syms: list[str], start: pd.Timestamp, end: pd.Timestamp
) -> float:
    m = a.merge(b, on=["date", "symbol"], suffixes=("_a", "_b"))
    m = m[m["symbol"].isin(syms) & (m["date"] >= start) & (m["date"] <= end)]
    return float((m["contract_a"] == m["contract_b"]).mean())


def main() -> int:
    cfg = load_config(CONFIG)
    specs = load_instruments()
    st_src = default_stitched(RQ, official_settle=True)
    ex_src = ExchangeSource()
    ex11 = ExchangeSource(dominant_rule="oi_1.1x")
    sources: dict[str, Any] = {
        "stitched": st_src,
        "exchange": ex_src,
        "exchange_oi1.1x": ex11,
        "swap_ex_dominant": _SwapDominant(st_src, ex_src),
        "swap_rq_dominant": _SwapDominant(ex_src, st_src),
    }
    labels = {
        "stitched": "米筐 + 交易所(正式基线)",
        "exchange": "纯交易所,max_oi 主力(纸面在用的规则)",
        "exchange_oi1.1x": "纯交易所,oi_1.1x 主力(复刻米筐)",
        "swap_ex_dominant": "正式基线,只把主力表换成 max_oi",
        "swap_rq_dominant": "纯交易所行情,只把主力表换成米筐的",
    }
    eq: dict[str, pd.Series] = {}
    pnl: dict[str, pd.Series] = {}
    for name, src in sources.items():
        run_research(cfg, src, specs, OUT / name)
        eq[name] = pd.read_csv(OUT / name / "equity.csv", index_col=0, parse_dates=True)["equity"]
        pnl[name] = pd.read_csv(OUT / name / "pnl_by_symbol.csv", index_col=0).sum()
    pos = pd.read_csv(OUT / "stitched" / "positions.csv", index_col=0, parse_dates=True)
    first_active = pos.index[pos.abs().sum(axis=1) > 0][0]
    syms = sorted(cfg.universe.symbols or [])
    # 米筐主力表本身(不是拼接源的:拼接源在切换日之后用的是交易所 max_oi)
    rq_dm, ex_dm, ex11_dm = st_src.primary.dominant_map(), ex_src.dominant_map(), ex11.dominant_map()
    cut = st_src.cutover

    lines = [
        "# 数据路径校验:只用交易所公开数据能否复现正式基线(v0.3,不计试验)",
        "",
        "由 `research/scripts/source_check.py` 生成。策略 = `configs/strategy_v03.yaml`,一字不动,不据此做任何选择。",
        "数据层的差别只有三处:行情来源(米筐导出 vs 交易所日报)、主力判定、合约元数据;仓单各路径都来自交易所。",
        f"统计从首个持仓日 {first_active.date()} 起;分期是同一次回测按日期切开,与 `settle_baseline.md` 的分期重跑口径不同。",
        "",
        "## 结果",
        "",
        "| 路径 | 全样本年化 | 全样本夏普(月) | 最大回撤 | 样本内夏普 | 样本外夏普 | 与基线配对差(年化,NW t) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sources:
        full, is_, oos = (_period_stats(eq[name], first_active, a, b) for a, b in PERIODS.values())
        if name == "stitched":
            diff = "—"
        else:
            ps = paired_summary(eq["stitched"], eq[name], start=first_active)
            diff = f"{ps['ann_mean']:+.2%}(t = {ps['t']:.2f})"
        lines.append(
            f"| {labels[name]} | {full['年化收益']:+.1%} | {full['夏普(月频)']:.2f} | {full['最大回撤']:.1%} "
            f"| {is_['夏普(月频)']:.2f} | {oos['夏普(月频)']:.2f} | {diff} |"
        )
    lines += [
        "",
        f"与米筐主力表的逐日一致率(22 个品种,{first_active.date()} → {cut.date()}):max_oi "
        f"{_agree(ex_dm, rq_dm, syms, first_active, cut):.2%};oi_1.1x "
        f"{_agree(ex11_dm, rq_dm, syms, first_active, cut):.2%}。",
        "",
        "米筐主力表的规则是近似复刻:2016 年以来 1,064 次切换中,新合约在 T−1 日的持仓都至少是旧合约的 1.10 倍;"
        "另有 3 次切到更早到期的合约、2 次切到的不是 T−1 持仓最大者。复刻规则取'T−1 持仓最大者超过当前主力 1.1 倍、"
        '且到期更晚才换\'(`ExchangeSource(dominant_rule="oi_1.1x")`)。',
        "",
        "行情来源(米筐 vs 交易所)在组合层面没有显著差异(上表最后一行,+0.10%/年),个别品种有差异(下表最后一列,"
        "如 SC)。上面的数字都在本机数据上算出;本机郑商所 2016–2025 年行情来自年度打包(经浏览器代理),"
        "`scripts/fetch_exchange_data.sh` 改用逐日 `.txt`,只做了抽查,没有从零完整重跑。",
        "",
        "## 分品种累计盈亏(万元,首个持仓日起)",
        "",
        "| 品种 | 正式基线 | 纯交易所 max_oi | 差 | 纯交易所 oi_1.1x | 差 |",
        "|---|---|---|---|---|---|",
    ]
    rows = []
    for s in syms:
        b, e, e11 = (float(pnl[k].get(s, 0.0)) / 1e4 for k in ("stitched", "exchange", "exchange_oi1.1x"))
        rows.append((s, b, e, e - b, e11, e11 - b))
    for s, b, e, d, e11, d11 in sorted(rows, key=lambda r: r[3]):
        lines.append(f"| {s} | {b:+.1f} | {e:+.1f} | {d:+.1f} | {e11:+.1f} | {d11:+.1f} |")
    lines.append(f"| 合计 | | | {sum(r[3] for r in rows):+.1f} | | {sum(r[5] for r in rows):+.1f} |")
    lines.append("")
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
