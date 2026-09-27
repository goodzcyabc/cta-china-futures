"""独立信息两条(预注册 docs/fundamental_signal_prereg.md;回顾性诊断,不进生产):

A. 全市场持仓兴趣(Hong–Yogo 2012 口径):四所全部合约持仓量按品种汇总 → 单边口径 → 全市场名义持仓 12 个月对数增长;
B. PMI 新订单 / 产成品库存(国家统计局制造业 PMI 分项,按公布日 info_date 点时对齐)。

两条候选都走生产同一条路径:候选合成信号(篮子内品种同一数值)→ vol_target_positions → cap_gross_exposure →(与基线 50/50 混合)→
暴露缓冲 → run_backtest。本模块只做数据对齐、信号构造、暴露拼装与统计汇总;所有常数在预注册里写死,不提供搜索接口。
时间语义:
- 月末持仓量在月末交易日 T 收盘后可得 → 目标暴露记在 T(引擎 T+1 开盘成交);
- 宏观值在公布日 D 可得 → 在 D 之后第一个交易日开盘建仓 → 目标暴露记在该交易日的前一个交易日(≤ D);
- 值只从自己的公布日起生效,修订值只从修订公布日起生效,不回填历史;超过 STALE_DAYS 没有新公布 → 信号失效(NaN,仓位 0)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from cta.config import StrategyConfig
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable
from cta.risk.metrics import TRADING_DAYS
from cta.signals.core import cap_gross_exposure, log_returns, trade_buffer, vol_target_positions

Frame = pd.DataFrame

OI_SINGLE_SIDE_FROM = pd.Timestamp(
    "2020-01-01"
)  # 四所自 2020-01-01 起成交量/持仓量改单边计数;此前的持仓量 ×0.5 统一为单边口径
OI_PRE2020_SCALE = 0.5
GROWTH_MONTHS = 12  # Hong–Yogo:12 个月增长
MIN_OBS_Z = 24  # 扩展窗口标准化的最少观测数(2 年)
CLIP_Z = 2.0  # 与项目现有信号标准化一致:clip ±2 再 /2
STALE_DAYS = 45  # 公布日之后超过 45 个日历日没有新值 → 信号失效
REG_NW_LAGS = 3  # 月频预测回归的 Newey–West 阶数(与 perf_stats 的月频 NW t 相同)


# ---------- A:持仓量汇总 ----------
@dataclass(frozen=True)
class OIPanel:
    contracts: Frame  # date × symbol:全部合约持仓量之和(单边口径),缺失 = NaN
    notional: Frame  # date × symbol:Σ 持仓量 × 结算价 × 乘数(元),缺失 = NaN
    coverage: Frame  # symbol 行:首末日期、合约-日数、结算价回退到收盘价的行数、持仓量缺失行数


def contract_open_interest(src: DataSource, symbols: list[str], specs: InstrumentTable) -> OIPanel:
    """逐品种把全部合约的持仓量按日求和;名义持仓用该合约的官方结算价(缺失时回退收盘价并计数)× 乘数。
    2020-01-01 之前的持仓量乘 OI_PRE2020_SCALE(双边 → 单边)。任何一天全部合约都缺持仓量 → 该品种当日 NaN,不补 0。"""
    oi_cols: dict[str, pd.Series[Any]] = {}
    nt_cols: dict[str, pd.Series[Any]] = {}
    cov_rows: list[dict[str, Any]] = []
    for s in symbols:
        c = src.contracts(s)
        if len(c) == 0:
            raise ValueError(f"{s}: no contract rows")
        d = c.reset_index()
        d["date"] = pd.to_datetime(d["date"])
        oi = pd.to_numeric(d["open_interest"], errors="coerce")
        px = (
            pd.to_numeric(d["settle"], errors="coerce")
            if "settle" in d.columns
            else pd.Series(np.nan, index=d.index)
        )
        close = pd.to_numeric(d["close"], errors="coerce")
        fallback = px.isna() & close.notna() & (oi > 0)
        px = px.where(px.notna(), close)
        scale = np.where(d["date"] < OI_SINGLE_SIDE_FROM, OI_PRE2020_SCALE, 1.0)
        oi_s = oi * scale
        nt = oi_s * px * float(specs[s].multiplier)
        # 有持仓但无价格的合约-日:名义记缺失(不补 0),持仓量照常计入
        nt = nt.where(~(oi.notna() & px.isna()), np.nan)
        g_oi = oi_s.groupby(d["date"]).sum(min_count=1)
        g_nt = nt.groupby(d["date"]).sum(min_count=1)
        bad_price = (oi.notna() & (oi > 0) & px.isna()).groupby(d["date"]).any()
        g_nt = g_nt.where(~bad_price.reindex(g_nt.index).fillna(False), np.nan)
        oi_cols[s] = g_oi
        nt_cols[s] = g_nt
        cov_rows.append(
            {
                "symbol": s,
                "exchange": specs[s].exchange,
                "first": g_oi.index.min(),
                "last": g_oi.index.max(),
                "contract_days": int(len(d)),
                "settle_fallback_to_close": int(fallback.sum()),
                "oi_missing_rows": int(oi.isna().sum()),
                "days_notional_missing": int(g_nt.isna().sum()),
            }
        )
    contracts = pd.DataFrame(oi_cols).sort_index()
    notional = pd.DataFrame(nt_cols).sort_index()
    contracts.index = pd.DatetimeIndex(contracts.index)
    notional.index = pd.DatetimeIndex(notional.index)
    return OIPanel(contracts, notional, pd.DataFrame(cov_rows).set_index("symbol"))


def month_end_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """交易日历中每个日历月的最后一个交易日。"""
    s = pd.Series(dates, index=dates)
    return pd.DatetimeIndex(s.groupby(dates.to_period("M")).max().to_numpy())


def aggregate_growth(
    oi: Frame, month_ends: pd.DatetimeIndex, k: int = GROWTH_MONTHS, symbols: list[str] | None = None
) -> Frame:
    """全市场(或给定品种集合)月末持仓的 k 个月对数增长:
    G_t = log(Σ_{i∈S_t} OI_{i,t} / Σ_{i∈S_t} OI_{i,t−k}),S_t = 在 t 与 t−k 两个月末都有有限持仓量的品种(链式,避免品种上市/缺失造成的跳变)。
    返回月末索引的表:growth、n_symbols、oi_now、oi_lag;S_t 为空 → NaN。"""
    cols = list(oi.columns) if symbols is None else [c for c in symbols if c in oi.columns]
    me = [d for d in month_ends if d in oi.index]
    rows = []
    for i, t in enumerate(me):
        if i < k:
            rows.append({"date": t, "growth": np.nan, "n_symbols": 0, "oi_now": np.nan, "oi_lag": np.nan})
            continue
        lag = me[i - k]
        now_v = oi.reindex(index=[t], columns=cols).iloc[0].astype(float)
        lag_v = oi.reindex(index=[lag], columns=cols).iloc[0].astype(float)
        ok = now_v.notna() & lag_v.notna() & (now_v > 0) & (lag_v > 0)
        n = int(ok.sum())
        if n == 0:
            rows.append({"date": t, "growth": np.nan, "n_symbols": 0, "oi_now": np.nan, "oi_lag": np.nan})
            continue
        a, b = float(now_v[ok].sum()), float(lag_v[ok].sum())
        rows.append({"date": t, "growth": float(np.log(a / b)), "n_symbols": n, "oi_now": a, "oi_lag": b})
    return pd.DataFrame(rows).set_index("date")


def sector_ew_growth(
    oi: Frame, month_ends: pd.DatetimeIndex, sector_of: dict[str, str], k: int = GROWTH_MONTHS
) -> Frame:
    """Hong–Yogo 口径的"商品市场兴趣":板块内名义持仓求和 → 板块月对数增长(链式)→ 有效板块等权平均 → 过去 k 个月的算术平均
    (对数增长的算术平均 = 几何平均增长率)。返回月末索引:g_<板块>、agg_1m、n_sectors、x(k 个月几何平均;不足 k 个有效月 → NaN)。"""
    sectors = sorted(set(sector_of.values()))
    cols: dict[str, pd.Series[Any]] = {}
    for sec in sectors:
        members = [s for s, a in sector_of.items() if a == sec and s in oi.columns]
        if not members:
            continue
        g = aggregate_growth(oi, month_ends, k=1, symbols=members)
        cols[f"g_{sec}"] = g["growth"]
    out = pd.DataFrame(cols)
    out["n_sectors"] = out.notna().sum(axis=1)
    out["agg_1m"] = out[[c for c in out.columns if c.startswith("g_")]].mean(axis=1, skipna=True)
    out.loc[out["n_sectors"] == 0, "agg_1m"] = np.nan
    out["x"] = out["agg_1m"].rolling(k, min_periods=k).mean()
    return out


def sector_ew_basket_daily(adj: Frame, symbols: list[str], sector_of: dict[str, str]) -> pd.Series[Any]:
    """论文口径的收益篮子(只作对照):板块内品种等权 → 板块间等权;日对数收益;缺价品种当日不参与。"""
    r = log_returns(adj[symbols])
    parts = []
    for sec in sorted(set(sector_of[s] for s in symbols)):
        members = [s for s in symbols if sector_of[s] == sec]
        parts.append(r[members].mean(axis=1, skipna=True))
    out: pd.Series[Any] = pd.concat(parts, axis=1).mean(axis=1, skipna=True)
    return out


# ---------- B:宏观点时对齐 ----------
@dataclass(frozen=True)
class Release:
    info_date: pd.Timestamp  # 公布日(可得日)
    period_end: pd.Timestamp  # 数据所属期末
    value: float


def load_macro(path: str) -> list[Release]:
    """米筐宏观文件(index = (factor, info_date);列 start_date/end_date/value/rice_create_tm)→ 按公布日排序的发布记录。"""
    m = pd.read_parquet(path).reset_index()
    out = [
        Release(pd.Timestamp(i), pd.Timestamp(e), float(v))
        for i, e, v in zip(m["info_date"].tolist(), m["end_date"].tolist(), m["value"].tolist())
        if pd.notna(v)
    ]
    return sorted(out, key=lambda r: (r.info_date, r.period_end))


def pmi_ratio_releases(new_orders: list[Release], fg_inventory: list[Release]) -> list[Release]:
    """同一期末的两个分项合成 新订单 / 产成品库存;公布日取二者中较晚者(都可得时才可得);任一缺失 → 该期不生成。"""
    by_no = {r.period_end: r for r in new_orders}
    by_fg = {r.period_end: r for r in fg_inventory}
    out = []
    for pe in sorted(set(by_no) & set(by_fg)):
        a, b = by_no[pe], by_fg[pe]
        if b.value == 0 or not np.isfinite(a.value) or not np.isfinite(b.value):
            continue
        out.append(Release(max(a.info_date, b.info_date), pe, a.value / b.value))
    return sorted(out, key=lambda r: (r.info_date, r.period_end))


def effective_target_day(info_date: pd.Timestamp, dates: pd.DatetimeIndex) -> pd.Timestamp | None:
    """公布日 D → 之后第一个交易日开盘建仓 → 目标暴露记在该交易日的前一个交易日(≤ D)。日历外 → None。"""
    after = dates[dates > info_date]
    if len(after) == 0:
        return None
    exec_day = after[0]
    pos = dates.get_loc(exec_day)
    if not isinstance(pos, (int, np.integer)) or pos == 0:
        return None
    return pd.Timestamp(dates[int(pos) - 1])


def releases_to_daily(
    releases: list[Release], dates: pd.DatetimeIndex, stale_days: int = STALE_DAYS
) -> pd.Series[Any]:
    """按公布顺序把值铺到交易日:每条记录从其目标日(见 effective_target_day)起生效,直到下一条记录的目标日;
    同一期末的修订值只从修订公布日起覆盖,不回填;超过 stale_days 无新公布 → NaN。返回 date → value。"""
    out = pd.Series(np.nan, index=dates, dtype=float)
    for r in releases:
        t = effective_target_day(r.info_date, dates)
        if t is None:
            continue
        out[out.index >= t] = r.value
        # 失效:公布日之后 stale_days 个日历日仍无新值 → NaN(后续记录按公布顺序重新覆盖)
        expiry = r.info_date + pd.Timedelta(days=stale_days)
        out.loc[out.index > expiry] = np.nan
    return out


def expanding_z(x: pd.Series[Any], min_obs: int = MIN_OBS_Z) -> pd.Series[Any]:
    """扩展窗口 z:(x_t − mean(x_1..x_t)) / std(x_1..x_t),不足 min_obs 个观测 → NaN。只用 ≤ t 的值。"""
    v = x.astype(float)
    mu = v.expanding(min_periods=min_obs).mean()
    sd = v.expanding(min_periods=min_obs).std(ddof=1)
    z: pd.Series[Any] = (v - mu) / sd.replace(0.0, np.nan)
    return z


def signal_from_z(z: pd.Series[Any], clip: float = CLIP_Z) -> pd.Series[Any]:
    s: pd.Series[Any] = z.clip(-clip, clip) / clip
    return s


def broadcast_signal(daily: pd.Series[Any], basket: list[str], columns: list[str]) -> Frame:
    """一个数值铺到篮子内全部品种;篮子外为 NaN(合成层不参与)。"""
    out = pd.DataFrame(np.nan, index=daily.index, columns=columns, dtype=float)
    for s in basket:
        if s in out.columns:
            out[s] = daily.to_numpy(dtype=float)
    return out


# ---------- 暴露拼装(与 compute_signals 尾部同一顺序) ----------
def raw_exposure(comb: Frame, eligible: Frame, vol: Frame, adj: Frame, cfg: StrategyConfig) -> Frame:
    """合成信号 → 波动率目标(风险平价 + 事前协方差缩放)→ 总名义上限;不含暴露缓冲。"""
    raw = vol_target_positions(
        comb.where(eligible.reindex(comb.index)),
        vol,
        adj,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    )
    return cap_gross_exposure(raw, cfg.portfolio.max_gross_exposure)


def apply_buffer(raw: Frame, cfg: StrategyConfig, start: pd.Timestamp, end: pd.Timestamp) -> Frame:
    """暴露缓冲(状态连续,从序列首日起),返回 [start, end] 的目标暴露。"""
    tgt = raw.copy()
    prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        row = tgt.loc[d].fillna(0.0)
        b = trade_buffer(row, prev, cfg.portfolio.exposure_buffer)
        tgt.loc[d] = b
        prev = b
    idx = pd.DatetimeIndex(tgt.index)
    return tgt[(idx >= start) & (idx <= end)]


def blend_exposure(base_raw: Frame, cand_raw: Frame, w_cand: float = 0.5) -> Frame:
    """事前风险预算 50/50:两条各自已缩放到目标波动的暴露按 (1−w, w) 凸组合;不再放大(混合后事前波动 ≤ 目标)。"""
    a = base_raw.fillna(0.0)
    b = cand_raw.reindex(index=a.index, columns=a.columns).fillna(0.0)
    out: Frame = (1.0 - w_cand) * a + w_cand * b
    return out


# ---------- 预测回归与篮子 ----------
def equal_risk_basket_daily(
    adj: Frame, vol: Frame, symbols: list[str], month_ends: pd.DatetimeIndex
) -> pd.Series[Any]:
    """固定等风险篮子的日对数收益:权重 w_i ∝ 1/σ_i,在每个月末 t 用当时的 σ 定权、下月内冻结;缺 σ 或缺价的品种当月不参与。"""
    r = log_returns(adj[symbols])
    idx = pd.DatetimeIndex(r.index)
    out = pd.Series(np.nan, index=idx, dtype=float)
    me = [d for d in month_ends if d in idx]
    for i, t in enumerate(me):
        nxt = me[i + 1] if i + 1 < len(me) else idx[-1]
        sig = vol.reindex(index=[t], columns=symbols).iloc[0].astype(float)
        w = (1.0 / sig).where(sig > 0)
        w = w / w.sum()
        m = (idx > t) & (idx <= nxt)
        seg = r.loc[m]
        contrib = seg.mul(w, axis=1)
        out.loc[m] = contrib.sum(axis=1, min_count=1).to_numpy(dtype=float)
    return out


def monthly_from_daily(daily: pd.Series[Any], month_ends: pd.DatetimeIndex) -> pd.Series[Any]:
    """日对数收益 → 月末标签的月收益(t 月末之后到 t+1 月末,标签 = t,即"下一月收益")。"""
    idx = pd.DatetimeIndex(daily.index)
    me = [d for d in month_ends if d in idx]
    rows = {}
    for i in range(len(me) - 1):
        m = (idx > me[i]) & (idx <= me[i + 1])
        rows[me[i]] = float(daily.loc[m].sum()) if m.any() else np.nan
    return pd.Series(rows, dtype=float)


def predictive_regression(
    x: pd.Series[Any], y_next: pd.Series[Any], nw_lags: int = REG_NW_LAGS
) -> dict[str, float]:
    """y_{t+1} = a + b·x_t + e;HAC(Newey–West,nw_lags)标准误。返回 beta、se、t、p、r2、n,以及 x 一个标准差对应的 y 变化。"""
    df = pd.concat([x.rename("x"), y_next.rename("y")], axis=1).dropna()
    if len(df) < 12:
        return {
            "n": float(len(df)),
            "beta": np.nan,
            "se": np.nan,
            "t": np.nan,
            "p": np.nan,
            "r2": np.nan,
            "beta_per_sd": np.nan,
        }
    x_mat = sm.add_constant(df["x"].to_numpy(dtype=float))
    fit = sm.OLS(df["y"].to_numpy(dtype=float), x_mat).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})
    beta = float(fit.params[1])
    return {
        "n": float(len(df)),
        "beta": beta,
        "se": float(fit.bse[1]),
        "t": float(fit.tvalues[1]),
        "p": float(fit.pvalues[1]),
        "r2": float(fit.rsquared),
        "beta_per_sd": beta * float(df["x"].std(ddof=1)),
    }


# ---------- 事件路径 ----------
def event_paths(
    basket_daily: pd.Series[Any], target_days: list[pd.Timestamp], signs: list[float], horizon: int = 21
) -> Frame:
    """每个目标日之后 1..horizon 个交易日的累计篮子对数收益(按信号符号取向);只描述,不选持有期。"""
    idx = pd.DatetimeIndex(basket_daily.index)
    rows = []
    for t, sgn in zip(target_days, signs):
        if t not in idx or not np.isfinite(sgn) or sgn == 0:
            continue
        loc = idx.get_loc(t)
        if not isinstance(loc, (int, np.integer)):
            continue
        pos = int(loc)
        seg = basket_daily.iloc[pos + 1 : pos + 1 + horizon].to_numpy(dtype=float)
        if len(seg) < horizon or np.isnan(seg).any():
            continue
        rows.append(np.sign(sgn) * np.cumsum(seg))
    if not rows:
        return pd.DataFrame(columns=[f"h{h}" for h in range(1, horizon + 1)])
    arr = np.vstack(rows)
    out = pd.DataFrame(
        {"mean": arr.mean(axis=0), "se": arr.std(axis=0, ddof=1) / np.sqrt(len(arr)), "n": len(arr)},
        index=[f"h{h}" for h in range(1, horizon + 1)],
    )
    return out


@dataclass
class ArmResult:
    name: str
    target: Frame
    equity: pd.Series[Any]
    result: Any
    extras: dict[str, Any] = field(default_factory=dict)


def annualize_costs(res: Any, equity: pd.Series[Any]) -> dict[str, float]:
    """年化手续费、滑点(占平均权益)与名义换手(倍/年)。"""
    days = float(len(equity))
    avg_eq = float(equity.mean())
    years = days / TRADING_DAYS
    fees = float(res.costs.sum()) if len(res.costs) else 0.0
    slip = float(res.slippage.sum()) if len(res.slippage) else 0.0
    return {
        "fees_ann": fees / years / avg_eq,
        "slip_ann": slip / years / avg_eq,
        "fees_total": fees,
        "slip_total": slip,
    }
