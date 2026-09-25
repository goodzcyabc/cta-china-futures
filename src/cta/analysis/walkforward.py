"""季度 walk-forward 诊断核心(只读;预注册见 docs/quarterly_walkforward_prereg.md)。

- 排程:每个季度模型的训练截止 = 上一季度最后一个交易日(含),交易区间 = 本季度交易日;程序断言 cutoff < 交易首日。
- 4.4 重选:训练窗口 2016-01-04 → cutoff,规则与 6.2 脚本逐字相同,并保留全部训练期统计;C3:carry 过去 3 年净夏普 ≤ 0 → 权重 0.5。
- 拼接:逐季冻结的合成信号按季拼接(断言无重叠、无遗漏、季内冻结),再连续做波动率目标缩放 → 总名义上限 → 暴露缓冲,交给引擎连续运行。
- 逐季记录:引擎口径(毛/费/滑/净/换手/回撤/成交笔数、逐品种与板块净贡献)与评估器口径(逐因子 sleeve)分开标注。
不做参数搜索;不改任何策略对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from cta.analysis.attribution import net_by_symbol_day
from cta.backtest.engine import BacktestResult
from cta.config import StrategyConfig
from cta.factors.base import FactorInputs
from cta.factors.evaluate import correlation_table, evaluate_factor
from cta.instruments.specs import InstrumentTable
from cta.risk.metrics import TRADING_DAYS, drawdown
from cta.signals.core import cap_gross_exposure, trade_buffer, vol_target_positions

Frame = pd.DataFrame
RULE = {"min_sharpe": 0.40, "min_t": 2.0, "max_corr_base": 0.60, "max_corr_pair": 0.80}


@dataclass(frozen=True)
class QuarterSpec:
    quarter: str
    cutoff: pd.Timestamp  # 训练截止(含)
    start: pd.Timestamp  # 交易区间首日
    end: pd.Timestamp  # 交易区间末日
    formal_oos: bool


def quarter_schedule(
    dates: pd.DatetimeIndex,
    first_q: str,
    last_q: str,
    end_clip: pd.Timestamp | None = None,
    oos_start: pd.Timestamp | None = None,
) -> list[QuarterSpec]:
    """季度模型排程;cutoff 必须严格早于交易首日。"""
    d = pd.DatetimeIndex(dates).sort_values()
    q, last = pd.Period(first_q, freq="Q"), pd.Period(last_q, freq="Q")
    out: list[QuarterSpec] = []
    while q <= last:
        prev_end = (q - 1).end_time.normalize()
        before = d[d <= prev_end]
        if len(before) == 0:
            raise ValueError(f"{q}: no trading day on or before {prev_end.date()}")
        q_end = q.end_time.normalize() if end_clip is None else min(q.end_time.normalize(), end_clip)
        win = d[(d >= q.start_time.normalize()) & (d <= q_end)]
        if len(win) == 0:
            break
        cutoff = pd.Timestamp(before.max())
        if cutoff >= win.min():
            raise ValueError(f"{q}: cutoff {cutoff.date()} not before trading start {win.min().date()}")
        out.append(
            QuarterSpec(
                str(q),
                cutoff,
                pd.Timestamp(win.min()),
                pd.Timestamp(win.max()),
                bool(oos_start is not None and q >= pd.Period(oos_start, freq="Q")),
            )
        )
        q += 1
    return out


def annual_cutoff(dates: pd.DatetimeIndex, quarter: str) -> pd.Timestamp:
    """年度流程的训练截止:该季度所在年的上一年 12-31(含)之前的最后一个交易日。"""
    y = pd.Period(quarter, freq="Q").year
    d = pd.DatetimeIndex(dates)
    return pd.Timestamp(d[d <= pd.Timestamp(f"{y - 1}-12-31")].max())


# ---------- 训练期统计与 4.4 重选 ----------
def training_table(
    sigs: dict[str, Frame],
    cands: list[str],
    combo_v01: Frame,
    x: FactorInputs,
    specs: InstrumentTable,
    cfg: StrategyConfig,
    hist_start: pd.Timestamp,
    cutoff: pd.Timestamp,
) -> Frame:
    """训练窗口 [hist_start, cutoff] 上每个候选与 tsmom/carry 的评估器统计;attrs['corr'] 存相关矩阵。"""
    names = [*cands, "tsmom", "carry"]
    res = {k: evaluate_factor(k, sigs[k], x, specs, cfg, hist_start, cutoff) for k in names}
    res["combo_v01"] = evaluate_factor("combo_v01", combo_v01, x, specs, cfg, hist_start, cutoff)
    corr = correlation_table(res)
    rows = []
    for k in names:
        st, ys = res[k].stats, res[k].yearly_sharpe
        rows.append(
            {
                "factor": k,
                "sharpe_m": float(st.get("夏普(月频)", np.nan)),
                "nw_t": float(st.get("月频NW t", np.nan)),
                "corr_v01": float(corr.at[k, "combo_v01"]),
                "n_years": int(ys.notna().sum()),
                "pos_years": int((ys > 0).sum()),
                "turnover": float(st.get("年化换手(Σ|Δw|)", np.nan)),
                "cost": float(st.get("年化成本", np.nan)),
            }
        )
    tab = pd.DataFrame(rows).set_index("factor")
    tab.attrs["corr"] = corr
    return tab


def select_44(tab: Frame, cands: list[str]) -> list[str]:
    """6.2 脚本 `select()` 逐字:按夏普从高到低,逐条门槛判定;NaN 一律不通过。"""
    corr: Frame = tab.attrs["corr"]
    chosen: list[str] = []
    order = sorted(cands, key=lambda n: -float(np.nan_to_num(tab.at[n, "sharpe_m"], nan=-9)))
    for n in order:
        n_years = int(tab.at[n, "n_years"])
        ok = bool(
            tab.at[n, "sharpe_m"] >= RULE["min_sharpe"]
            and tab.at[n, "nw_t"] >= RULE["min_t"]
            and tab.at[n, "corr_v01"] <= RULE["max_corr_base"]
            and int(tab.at[n, "pos_years"]) >= max(4 * n_years // 5, 3)
            and all(abs(float(corr.at[n, c])) <= RULE["max_corr_pair"] for c in chosen)
        )
        if ok:
            chosen.append(n)
    return chosen


def carry_gate(
    carry_sig: Frame,
    x: FactorInputs,
    specs: InstrumentTable,
    cfg: StrategyConfig,
    cutoff: pd.Timestamp,
    years: int = 3,
) -> tuple[float, float]:
    """C3:carry sleeve 过去 years 年净月频夏普 ≤ 0 → 下一季权重 0.5,否则 1.0(不归零)。"""
    w0 = cutoff - pd.DateOffset(years=years) + pd.Timedelta(days=1)
    r = evaluate_factor("carry", carry_sig, x, specs, cfg, w0, cutoff)
    sh = float(r.stats.get("夏普(月频)", np.nan))
    return sh, (0.5 if (np.isfinite(sh) and sh <= 0.0) else 1.0)


# ---------- 拼接、冻结校验、目标暴露 ----------
def stitch_quarters(pieces: list[tuple[QuarterSpec, Frame]], dates: pd.DatetimeIndex) -> Frame:
    """按各季交易区间拼接;断言无重叠、无遗漏(覆盖首季首日到末季末日的每个交易日恰好一次)。"""
    parts = []
    for q, f in pieces:
        idx = pd.DatetimeIndex(f.index)
        parts.append(f[(idx >= q.start) & (idx <= q.end)])
    out = pd.concat(parts).sort_index()
    if out.index.has_duplicates:
        raise ValueError("stitched quarters overlap")
    d = pd.DatetimeIndex(dates)
    expected = d[(d >= pieces[0][0].start) & (d <= pieces[-1][0].end)]
    missing, extra = expected.difference(out.index), pd.DatetimeIndex(out.index).difference(expected)
    if len(missing) or len(extra):
        raise ValueError(f"stitched quarters gap={len(missing)} extra={len(extra)}")
    return out


def assert_frozen(stitched: Frame, pieces: list[tuple[QuarterSpec, Frame]]) -> None:
    """季内冻结:拼接序列在每个季度里逐日等于该季冻结的合成信号。"""
    for q, f in pieces:
        ia, ib = pd.DatetimeIndex(stitched.index), pd.DatetimeIndex(f.index)
        a = stitched[(ia >= q.start) & (ia <= q.end)]
        b = f[(ib >= q.start) & (ib <= q.end)].reindex(columns=a.columns)
        if not np.allclose(a.to_numpy(dtype=float), b.to_numpy(dtype=float), equal_nan=True):
            raise ValueError(f"{q.quarter}: stitched signal differs from frozen quarter signal")


def targets_from_comb(
    comb: Frame,
    eligible: Frame,
    vol: Frame,
    adj: Frame,
    cfg: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> Frame:
    """与 compute_signals 尾部同一顺序:波动率目标 → 总名义上限 → 暴露缓冲(状态连续);返回 [start, end] 的目标暴露。"""
    raw = vol_target_positions(
        comb.where(eligible.reindex(comb.index)),
        vol,
        adj,
        cfg.portfolio.target_vol,
        window=cfg.signals.vol_window,
        max_leverage_per_symbol=cfg.portfolio.max_leverage_per_symbol,
        update=cfg.portfolio.vol_scale_update,
    )
    raw = cap_gross_exposure(raw, cfg.portfolio.max_gross_exposure)
    tgt = raw.copy()
    prev = pd.Series(0.0, index=tgt.columns)
    for d in tgt.index:
        row = tgt.loc[d].fillna(0.0)
        b = trade_buffer(row, prev, cfg.portfolio.exposure_buffer)
        tgt.loc[d] = b
        prev = b
    idx = pd.DatetimeIndex(tgt.index)
    return tgt[(idx >= start) & (idx <= end)]


# ---------- 逐季记录(引擎口径) ----------
def quarter_engine_records(res: BacktestResult, specs: InstrumentTable, quarters: list[QuarterSpec]) -> Frame:
    eq = res.equity
    idx = pd.DatetimeIndex(eq.index)
    net_sym = net_by_symbol_day(res, specs)
    tr = res.trades.copy()
    if len(tr):
        tr["date"] = pd.to_datetime(tr["date"])
        tr["notional"] = tr["lots"].abs() * tr["price"] * tr["symbol"].map(lambda s: specs[str(s)].multiplier)
    rows = []
    for q in quarters:
        m = (idx >= q.start) & (idx <= q.end)
        if not m.any():
            continue
        before = eq[idx < q.start]
        base = float(before.iloc[-1]) if len(before) else float(eq.iloc[0])
        seg = eq[m]
        gross = float(res.pnl_by_symbol.loc[m].to_numpy(dtype=float).sum())
        fees = float(res.costs.loc[m].sum())
        slip = float(res.slippage.loc[m].sum()) if len(res.slippage) else np.nan
        net = float(seg.iloc[-1]) - base
        trq = tr[(tr["date"] >= q.start) & (tr["date"] <= q.end)] if len(tr) else tr
        turnover = float(trq["notional"].sum() / seg.mean()) if len(trq) else 0.0
        dd = float(
            drawdown(pd.concat([pd.Series([base], index=[q.start - pd.Timedelta(days=1)]), seg])).min()
        )
        rows.append(
            {
                "quarter": q.quarter,
                "start": q.start,
                "end": q.end,
                "formal_oos": q.formal_oos,
                "equity_start": base,
                "equity_end": float(seg.iloc[-1]),
                "ret": net / base if base else np.nan,
                "gross_pnl": gross,
                "fees": fees,
                "slippage_in_price": slip,
                "net_pnl": net,
                "cost_share": (fees / abs(gross)) if gross else np.nan,
                "turnover_notional": turnover,
                "n_trades": int(len(trq)),
                "mdd_in_quarter": dd,
                "n_days": int(m.sum()),
                "net_symbol_sum": float(net_sym.loc[m].to_numpy(dtype=float).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("quarter")


def quarter_symbol_contrib(res: BacktestResult, specs: InstrumentTable, quarters: list[QuarterSpec]) -> Frame:
    """quarter × symbol 净贡献(引擎口径:盯市 + 已实现 − 按品种归属的手续费)。"""
    net = net_by_symbol_day(res, specs)
    idx = pd.DatetimeIndex(net.index)
    rows = {}
    for q in quarters:
        m = (idx >= q.start) & (idx <= q.end)
        if m.any():
            rows[q.quarter] = net.loc[m].sum()
    return pd.DataFrame(rows).T


def sector_contrib(sym: Frame, specs: InstrumentTable) -> Frame:
    groups: dict[str, list[str]] = {}
    for s in sym.columns:
        groups.setdefault(specs[str(s)].asset_class, []).append(str(s))
    return pd.DataFrame({ac: sym[cols].sum(axis=1) for ac, cols in groups.items()})


# ---------- 逐季 sleeve 表现(评估器口径) ----------
def sleeve_quarter_perf(
    sigs: dict[str, Frame],
    x: FactorInputs,
    specs: InstrumentTable,
    cfg: StrategyConfig,
    quarters: list[QuarterSpec],
) -> Frame:
    """quarter × factor:该季 sleeve 净收益(对数收益之和)与日频年化夏普;单季夏普只作记录,不作证据。"""
    rows = []
    for q in quarters:
        for k, s in sigs.items():
            r = evaluate_factor(k, s, x, specs, cfg, q.start, q.end)
            net = r.net.to_numpy(dtype=float)
            sd = float(net.std(ddof=1)) if len(net) > 2 else np.nan
            rows.append(
                {
                    "quarter": q.quarter,
                    "factor": k,
                    "net_ret": float(net.sum()),
                    "gross_ret": float(r.gross.sum()),
                    "cost": float(r.cost.sum()),
                    "sharpe_d": float(net.mean() / sd * np.sqrt(TRADING_DAYS)) if sd and sd > 0 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def paired_by_quarter(a: pd.Series[Any], b: pd.Series[Any], quarters: list[QuarterSpec]) -> Frame:
    """动态臂 a 相对基线 b 的逐季配对:季度净收益差、日收益差均值、动态是否胜出。"""
    ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
    common = ra.index.intersection(rb.index)
    d = (ra.loc[common] - rb.loc[common]).astype(float)
    ia, ib, idd = pd.DatetimeIndex(a.index), pd.DatetimeIndex(b.index), pd.DatetimeIndex(d.index)

    def q_ret(s: pd.Series[Any], idx: pd.DatetimeIndex, q: QuarterSpec) -> float:
        before, inside = s[idx < q.start], s[(idx >= q.start) & (idx <= q.end)]
        if len(before) == 0 or len(inside) == 0:
            return float("nan")
        return float(inside.iloc[-1] / before.iloc[-1] - 1.0)

    rows = []
    for q in quarters:
        m = (idd >= q.start) & (idd <= q.end)
        if not m.any():
            continue
        qa, qb = q_ret(a, ia, q), q_ret(b, ib, q)
        rows.append(
            {
                "quarter": q.quarter,
                "ret_dyn": qa,
                "ret_base": qb,
                "ret_diff": qa - qb,
                "daily_diff_mean": float(d[m].mean()),
                "dyn_wins": bool(qa > qb),
            }
        )
    return pd.DataFrame(rows).set_index("quarter")
