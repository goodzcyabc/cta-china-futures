"""诊断 T1/T2(design_log 七):不选因子、不改配置。
T1:标准化收益 z_t = r_t/σ_{t−1}(σ=√EWMA_33(r²))的自相关 ρ(m),分 2016–2021 / 2022–2026;按各趋势定义对滞后的隐含权重
    算"自相关通道"Σ_m w(m)ρ(m)/√Σw²(Sepp & Lucic 2026 式 4.22 的线性化形式)。
T2:跳价占日波动比例 ρ̄ = 月均(tick / EWMA_336(|Δp|))(Kurth 等 2026 式 6),换月日的 Δp 剔除。
输出 docs/diagnostics_acf_tick.md。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config  # noqa: E402
from cta.data.source import RicequantParquetSource  # noqa: E402
from cta.instruments.specs import load_instruments  # noqa: E402
from cta.pipeline import build_panels  # noqa: E402

cfg = load_config()
specs = load_instruments()
panels = build_panels(RicequantParquetSource(Path("data/ricecta/data")), cfg, specs)
adj = pd.DataFrame({s: p.frame["adj_close"] for s, p in panels.items()}).sort_index()
raw = pd.DataFrame({s: p.frame["close"] for s, p in panels.items()}).sort_index()
roll = (
    pd.DataFrame({s: p.frame["roll"] for s, p in panels.items()})
    .sort_index()
    .astype("boolean")
    .fillna(False)
    .astype(bool)
)

r = np.log(adj).diff()
sigma = np.sqrt((r**2).ewm(span=33, adjust=False, min_periods=20).mean())
z = r / sigma.shift(1)
z = z.where(z.abs() < 8)  # 极端值(涨跌停连板)截掉,不影响结论

PERIODS = {"2016–2021": ("2016-01-01", "2021-12-31"), "2022–2026": ("2022-01-01", "2026-06-05")}
M = 250


def acf_pooled(zz: pd.DataFrame, max_lag: int) -> pd.Series:
    """各品种 ρ(m) 的等权平均(池化自相关)。"""
    out = np.zeros(max_lag)
    n = 0
    for s in zz.columns:
        x = zz[s].dropna()
        if len(x) < 400:
            continue
        x = x - x.mean()
        v = float((x**2).mean())
        for m in range(1, max_lag + 1):
            out[m - 1] += float((x.iloc[m:].to_numpy() * x.iloc[:-m].to_numpy()).mean() / v)
        n += 1
    return pd.Series(out / n, index=range(1, max_lag + 1), name="rho")


def w_cum(n: int) -> np.ndarray:
    w = np.zeros(M)
    w[:n] = 1.0
    return w


def w_ewmac(fast: int, slow: int) -> np.ndarray:
    m = np.arange(1, M + 1)
    return (1 - 1 / slow) ** m - (1 - 1 / fast) ** m


def w_ls_span(span_l: int, span_s: int) -> np.ndarray:
    a_l, a_s = 2 / (span_l + 1), 2 / (span_s + 1)
    m = np.arange(1, M + 1)
    return (1 - a_l) ** m - (1 - a_s) ** m


def channel(w: np.ndarray, rho: pd.Series) -> float:
    return float((w * rho.to_numpy()).sum() / np.sqrt((w**2).sum()))


DEFS: dict[str, np.ndarray] = {
    "tsmom 21": w_cum(21),
    "tsmom 63": w_cum(63),
    "tsmom 126": w_cum(126),
    "tsmom 252": w_cum(252),
    "tsmom 等权(v0.1)": (
        w_cum(21) / np.sqrt(21)
        + w_cum(63) / np.sqrt(63)
        + w_cum(126) / np.sqrt(126)
        + w_cum(252) / np.sqrt(252)
    ),
    "ewmac 8/24": w_ewmac(8, 24),
    "ewmac 16/48": w_ewmac(16, 48),
    "ewmac 32/96": w_ewmac(32, 96),
    "ewmac 三速等权": (
        w_ewmac(8, 24) / np.linalg.norm(w_ewmac(8, 24))
        + w_ewmac(16, 48) / np.linalg.norm(w_ewmac(16, 48))
        + w_ewmac(32, 96) / np.linalg.norm(w_ewmac(32, 96))
    ),
    "LS(250,20)(Sepp–Lucic)": w_ls_span(250, 20),
    "LS(125,20)": w_ls_span(125, 20),
    "LS(63,20)": w_ls_span(63, 20),
}

rows = []
acfs = {}
drift_rows = {}
for name, (a, b) in PERIODS.items():
    rho = acf_pooled(z.loc[a:b], M)
    acfs[name] = rho
    mu_an = z.loc[a:b].mean() * np.sqrt(243)  # 标准化收益年化均值 = 品种自身夏普
    drift_rows[name] = mu_an
    row = {
        "区间": name,
        "漂移通道 mean(μ_an²)": float((mu_an**2).mean()),
        "|μ_an|>0.5 品种数": int((mu_an.abs() > 0.5).sum()),
        "Σρ(1..5)": rho.loc[1:5].sum(),
        "Σρ(6..21)": rho.loc[6:21].sum(),
        "Σρ(22..63)": rho.loc[22:63].sum(),
        "Σρ(64..250)": rho.loc[64:250].sum(),
    }
    for k, w in DEFS.items():
        row[k] = channel(w, rho)
    rows.append(row)
t1 = pd.DataFrame(rows).set_index("区间").T

# 隐含权重前 5 阶占比(说明各定义对短滞后的敏感度)
wshare = {k: float(np.abs(w[:5]).sum() / np.abs(w).sum()) for k, w in DEFS.items()}

# T2 跳价比例
dp = raw.diff().where(~roll)
mad = dp.abs().ewm(span=336, adjust=False, min_periods=60).mean()
tick = pd.Series({s: specs[s].tick for s in raw.columns})
rho_bar = (tick / mad).resample("ME").mean()
t2 = pd.DataFrame(
    {
        "2016–2021 中位": rho_bar.loc["2016":"2021"].median(),
        "2022–2026 中位": rho_bar.loc["2022":"2026"].median(),
        "最近 12 月": rho_bar.iloc[-12:].mean(),
        "1 跳 = 日波动的": rho_bar.iloc[-12:].mean().map(lambda v: f"{v:.1%}"),
    }
).sort_values("最近 12 月", ascending=False)

out = Path("docs/diagnostics_acf_tick.md")
md = [
    "# 诊断 T1/T2(2026-09-16;不选因子、不改配置)",
    "",
    "## T1 标准化收益的自相关与各趋势定义的隐含权重",
    "",
    "z_t = r_t/σ_{t−1},σ = √EWMA_33(r²);ρ(m) 为 23 品种池化自相关;'通道' = Σ_m w(m)ρ(m)/√Σw²,即零漂移下该定义的夏普方向(线性化,未含成本)。",
    "tsmom N = 过去 N 日累计收益(对 1..N 阶等权);ewmac S/L = 时间尺度 EMA 差,对 m 阶权重 (1−1/L)^m − (1−1/S)^m;LS(span_l, span_s) 为 Sepp–Lucic 的双 EWMA(span 口径)。",
    "",
    t1.round(3).to_markdown(),
    "",
    "各定义对 1..5 阶滞后的权重占比(|w| 之和的份额):",
    "",
    pd.Series(wshare).round(3).to_frame("前 5 阶占比").to_markdown(),
    "",
    "### 漂移通道:各品种标准化收益的年化均值 μ_an(= 品种自身夏普;趋势策略第二收益来源 ∝ μ_an²)",
    "",
    pd.DataFrame(drift_rows).round(2).to_markdown(),
    "",
    "## T2 跳价占日波动比例 ρ̄(Kurth 等 2026 式 6;论文云团主体 0.01–0.1,小 tick 组快趋势 2009 后失效)",
    "",
    t2.round(3).to_markdown(),
    "",
    "备注:ρ̄ 同时等于本项目'1 跳滑点'占日波动的比例。",
    "",
]
out.write_text("\n".join(md), encoding="utf-8")
pd.DataFrame(acfs).to_csv("results/diag_acf.csv")
print(t1.round(3).to_string())
print()
print(pd.Series(wshare).round(3).to_string())
print()
print(t2.round(3).to_string())
print("->", out)
