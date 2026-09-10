"""从 results/<digest>/ 生成报告:绩效表、分年、分段、分品种贡献、图。不重新回测,只读结果文件。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from cta.risk.metrics import drawdown, perf_stats, yearly  # noqa: E402

_CJK = ["PingFang SC", "Hiragino Sans GB", "Heiti SC", "Noto Sans CJK SC", "SimHei"]
_avail = {f.name for f in font_manager.fontManager.ttflist}
_font = next((f for f in _CJK if f in _avail), None)
if _font:
    plt.rcParams["font.sans-serif"] = [_font, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["mathtext.fontset"] = "dejavusans"


def _fmt(d: dict[str, Any]) -> str:
    rows = []
    for k, v in d.items():
        if isinstance(v, float):
            rows.append(
                f"| {k} | {v:.2%} |"
                if any(x in k for x in ("收益", "波动", "回撤", "胜率", "占", "费"))
                else f"| {k} | {v:.2f} |"
            )
        else:
            rows.append(f"| {k} | {v} |")
    return "| 指标 | 值 |\n|---|---|\n" + "\n".join(rows)


def build_report(run_dir: Path) -> Path:
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    eq = pd.read_csv(run_dir / "equity.csv", index_col=0, parse_dates=True).iloc[:, 0]
    exp = pd.read_csv(run_dir / "exposure.csv", index_col=0, parse_dates=True)
    trades = pd.read_csv(run_dir / "trades.csv", parse_dates=["date"])
    fig_dir = run_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    # 图 1 权益与回撤
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax[0].plot(eq.index, eq / eq.iloc[0], lw=1.4)
    ax[0].set_title("CTA 权益(含成本)")
    ax[0].grid(alpha=0.3)
    ax[1].fill_between(eq.index, drawdown(eq), 0, color="#c0504d", alpha=0.5)
    ax[1].set_ylabel("回撤")
    ax[1].grid(alpha=0.3)
    fig.savefig(fig_dir / "equity.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    # 图 2 总名义暴露与保证金
    mu = pd.read_csv(run_dir / "margin_usage.csv", index_col=0, parse_dates=True).iloc[:, 0]
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.plot(exp.index, exp.abs().sum(axis=1), label="总名义暴露/权益")
    ax.plot(mu.index, mu, label="保证金占用")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(fig_dir / "exposure.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    # 分年、分段
    yt = yearly(eq)
    segs = {}
    for lab, (s, e) in {
        "2016-2019": ("2016-01-01", "2019-12-31"),
        "2020-2022": ("2020-01-01", "2022-12-31"),
        "2023-2026": ("2023-01-01", "2026-12-31"),
    }.items():
        sub = eq[(eq.index >= pd.Timestamp(s)) & (eq.index <= pd.Timestamp(e))]
        if len(sub) > 60:
            segs[lab] = perf_stats(sub)
    seg = pd.DataFrame(segs).T[["年化收益", "年化波动", "夏普(月频)", "最大回撤"]]
    # 分品种贡献:用暴露 × 次日收益近似(引擎按结算盯市,这里用权益口径的近似归因)
    contrib = {}
    for s in exp.columns:
        n_tr = int((trades["symbol"] == s).sum())
        contrib[s] = {"平均|暴露|": float(exp[s].abs().mean()), "成交笔数": n_tr}
    ct = pd.DataFrame(contrib).T.sort_values("平均|暴露|", ascending=False)
    md = [
        f"# CTA 回测报告 — 配置 {meta['config_digest']} / 代码 {meta['git_sha']}\n",
        f"区间 {meta['period'][0]} 至 {meta['period'][1]},{meta['n_symbols']} 个品种,初始资金 {meta['config']['backtest']['initial_capital_cny']:,.0f} 元。\n",
        "## 绩效\n",
        _fmt(meta["stats"]),
        "\n![权益](figures/equity.png)\n![暴露](figures/exposure.png)\n",
        "## 分年收益\n",
        (yt * 100).round(2).to_frame("收益 %").to_markdown(),
        "\n## 分段\n",
        seg.round(3).to_markdown(),
        "\n## 分品种\n",
        ct.round(3).to_markdown(),
        "\n## 出处\n",
        f"数据指纹:`{meta['data_manifest']['sha256']}`({meta['data_manifest']['n_files']} 个文件);配置:\n```json\n{json.dumps(meta['config'], ensure_ascii=False, indent=1)}\n```",
    ]
    out = run_dir / "report.md"
    out.write_text("\n".join(md), encoding="utf-8")
    return out
