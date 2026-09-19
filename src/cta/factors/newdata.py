"""新数据因子(design_log 九):会员持仓排名与仓单日报 → 日频品种级序列与四个预注册因子。

数据来自 data/exchanges(交易所直连,点时落盘)。这里只做"数据 → 序列 → 信号",评估仍用 cta.factors.evaluate。
- H-POS-A 套保压力(仅上期所有"非期货公司会员"分类):HP = (非期货公司多头 − 空头)/品种总持仓;因子 = −HP 的 60 日 z(时序)。
- H-POS-B 知情席位跟随:会员评分冻结窗口 250 日 + 5 日禁运,每年重估;队列 = 每品种前 3;信号 = Σ队列 Δnp / OI 的 60 日 z。
- H-REC 仓单变化:−(log(1+仓单)_t − log(1+仓单)_{t−21}) 的横截面 z;H-REC-L:−仓单在自身 252 日窗口的分位 的横截面 z。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy import stats as sps

from cta.data.exchanges.base import Store

Frame = pd.DataFrame
CACHE = Path("results/newdata")
SHFE_HP_SYMBOLS = ("CU", "AL", "NI", "SN", "AU", "AG", "RB", "RU")
NONFC = "非期货公司会员"


# ---------------------------------------------------------------- 装载(带缓存)
def _cached(name: str, build: Callable[[], Frame]) -> Frame:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"{name}.parquet"
    if p.exists():
        loaded: Frame = pd.read_parquet(p)
        return loaded
    df: Frame = build()
    df.to_parquet(p, index=False)
    return df


def load_positions(store: Store, exchange: str) -> Frame:
    return _cached(f"positions_{exchange}", lambda: store.read_days(exchange, "positions"))


def load_receipts(store: Store, exchange: str) -> Frame:
    return _cached(f"receipts_{exchange}", lambda: store.read_days(exchange, "receipts"))


# ---------------------------------------------------------------- 品种级序列
def hedging_pressure(store: Store, symbols: tuple[str, ...] = SHFE_HP_SYMBOLS) -> Frame:
    """上期所 非期货公司会员 净多头 / 品种总持仓(合计行的 期货公司+非期货公司 多头之和)。index=date, columns=symbol。"""
    p = load_positions(store, "SHFE")
    p = p[p["is_total"] & p["symbol"].isin(symbols)]
    prod = p[p["contract"] == p["symbol"]]  # 新版:品种级分类行
    con = p[(p["contract"] != p["symbol"]) & (p["member_long"] != "合计")]  # 旧版:合约级分类行
    cat = pd.concat([prod, con])
    cat = cat.drop_duplicates(["date", "symbol", "contract", "member_long"])
    g = cat.groupby(["date", "symbol", "member_long"])[["long_oi", "short_oi"]].sum()
    tot = g.groupby(["date", "symbol"])["long_oi"].sum()
    non = g.xs(NONFC, level="member_long")
    hp = (non["long_oi"] - non["short_oi"]) / tot.reindex(non.index)
    out: Frame = hp.unstack("symbol").sort_index()
    return out


def receipts_total(store: Store, exchanges: tuple[str, ...] = ("SHFE", "INE", "CZCE", "DCE")) -> Frame:
    """注册仓单合计(非合计行之和;上期所含保税);index=date, columns=symbol。"""
    parts = []
    for e in exchanges:
        r = load_receipts(store, e)
        if r.empty:
            continue
        s = r[~r["is_total"]].groupby(["date", "symbol"])["receipts"].sum()
        parts.append(s)
    out: Frame = pd.concat(parts).groupby(level=[0, 1]).sum().unstack("symbol").sort_index()
    return out


def member_net(store: Store, exchange: str, symbols: tuple[str, ...]) -> Frame:
    """会员 × 品种 × 日 的净持仓(多头榜 − 空头榜,合约级加总;不在某榜按 0,两榜都不在则缺失)。
    columns: date, symbol, member, net, on_list。郑商所优先用品种级榜(contract==symbol)。"""
    p = load_positions(store, exchange)
    p = p[(~p["is_total"]) & p["symbol"].isin(symbols)]
    if exchange == "CZCE":
        prod = p[p["contract"] == p["symbol"]]
        p = prod if len(prod) else p
    else:
        p = p[p["contract"] != p["symbol"]]
    lng = p[["date", "symbol", "member_long", "long_oi"]].rename(
        columns={"member_long": "member", "long_oi": "q"}
    )
    lng = lng[lng["member"].astype(str).str.len() > 0]
    sht = p[["date", "symbol", "member_short", "short_oi"]].rename(
        columns={"member_short": "member", "short_oi": "q"}
    )
    sht = sht[sht["member"].astype(str).str.len() > 0]
    sht["q"] = -sht["q"]
    both = pd.concat([lng, sht])
    net = both.groupby(["date", "symbol", "member"])["q"].sum().rename("net").reset_index()
    net["date"] = pd.to_datetime(net["date"])
    return net


# ---------------------------------------------------------------- 因子
def zscore_ts(x: Frame, window: int = 60, min_periods: int = 30) -> Frame:
    mu = x.rolling(window, min_periods=min_periods).mean()
    sd = x.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    out: Frame = ((x - mu) / sd).clip(-2, 2) / 2.0
    return out


def zscore_xs(x: Frame, eligible: Frame) -> Frame:
    r = x.where(eligible.reindex_like(x).fillna(False).astype(bool))
    z = r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)
    out: Frame = (z.clip(-2, 2) / 2.0).where(x.notna())
    return out


def hpos_a(hp: Frame, index: pd.DatetimeIndex, columns: list[str]) -> Frame:
    x = hp.reindex(index).ffill(limit=5).reindex(columns=columns)
    return zscore_ts(-x)


def hrec(rec: Frame, index: pd.DatetimeIndex, columns: list[str], eligible: Frame) -> Frame:
    r = cast(Frame, np.log1p(rec.reindex(index).ffill(limit=5).reindex(columns=columns)))
    x = -(r - r.shift(21))
    return zscore_xs(x, eligible)


def hrec_level(rec: Frame, index: pd.DatetimeIndex, columns: list[str], eligible: Frame) -> Frame:
    r = cast(Frame, np.log1p(rec.reindex(index).ffill(limit=5).reindex(columns=columns)))
    pct = r.rolling(252, min_periods=126).rank(pct=True)
    return zscore_xs(-(pct - 0.5), eligible)


@dataclass
class PosBResult:
    signal: Frame
    persistence_rho: float
    persistence_p: float
    n_pairs: int
    yearly_queue: dict[int, dict[str, list[str]]]
    scores_by_window: dict[int, pd.Series[Any]]


def _forward_return(adj_close: Frame, h: int = 5) -> Frame:
    out: Frame = adj_close.shift(-(h + 1)) / adj_close.shift(-1) - 1.0  # T+1 → T+1+h(收盘对收盘)
    return out


def member_scores(
    net: Frame,
    adj_close: Frame,
    notional: Frame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    h: int = 5,
    min_events: int = 60,
) -> pd.Series[Any]:
    """评分窗口 [start, end] 内:α_{m,s} = Σ w·sign(Δnp)·r_{T+1→T+1+h} / Σ w,w=|Δnp|×名义;事件数 < min_events 的 (m,s) 剔除。"""
    fwd = _forward_return(adj_close, h)
    n = net[(net["date"] >= start) & (net["date"] <= end)].sort_values(["symbol", "member", "date"])
    n["dnp"] = n.groupby(["symbol", "member"])["net"].diff()
    prev_date = n.groupby(["symbol", "member"])["date"].shift(1)
    # 只保留连续两个交易日都在榜的变化(前一记录日期必须是上一个交易日)
    trading = pd.DatetimeIndex(adj_close.index)
    pos = pd.Series(np.arange(len(trading)), index=trading)
    ok = (pos.reindex(n["date"]).to_numpy() - pos.reindex(prev_date).to_numpy()) == 1
    n = n[ok & n["dnp"].notna() & (n["dnp"] != 0)]
    n["fwd"] = fwd.stack().reindex(pd.MultiIndex.from_frame(n[["date", "symbol"]])).to_numpy()
    n["px"] = notional.stack().reindex(pd.MultiIndex.from_frame(n[["date", "symbol"]])).to_numpy()
    n = n[n["fwd"].notna() & n["px"].notna()]
    n["w"] = n["dnp"].abs() * n["px"]
    n["wx"] = n["w"] * np.sign(n["dnp"]) * n["fwd"]
    g = n.groupby(["symbol", "member"])
    cnt = g.size()
    score: pd.Series[Any] = g["wx"].sum() / g["w"].sum()
    kept: pd.Series[Any] = score[cnt >= min_events]
    return kept


def hpos_b(
    net: Frame,
    adj_close: Frame,
    notional: Frame,
    oi_total: Frame,
    eligible: Frame,
    years: range,
    top_k: int = 3,
    window: int = 250,
    embargo: int = 5,
) -> PosBResult:
    trading = pd.DatetimeIndex(adj_close.index)
    sig = pd.DataFrame(np.nan, index=trading, columns=adj_close.columns)
    yearly: dict[int, dict[str, list[str]]] = {}
    scores: dict[int, pd.Series[Any]] = {}
    net = net.copy()
    net = net.sort_values(["symbol", "member", "date"])
    net["dnp"] = net.groupby(["symbol", "member"])["net"].diff()
    for y in years:
        first = trading[trading >= pd.Timestamp(year=y, month=1, day=1)]
        if len(first) == 0:
            continue
        i0 = int(trading.searchsorted(first[0]))
        s_end = trading[max(i0 - embargo - 1, 0)]
        s_start = trading[max(i0 - embargo - window, 0)]
        sc = member_scores(net, adj_close, notional, s_start, s_end)
        scores[y] = sc
        q: dict[str, list[str]] = {}
        for s in adj_close.columns:
            if s in sc.index.get_level_values(0):
                q[s] = list(sc.xs(s).sort_values(ascending=False).head(top_k).index)
        yearly[y] = q
        yr = net[(net["date"] >= first[0]) & (net["date"] <= pd.Timestamp(year=y, month=12, day=31))]
        for s, members in q.items():
            sub = yr[(yr["symbol"] == s) & (yr["member"].isin(members))]
            daily = sub.groupby("date")["dnp"].sum()
            sig.loc[daily.index, s] = daily.to_numpy()
    raw = sig / oi_total.reindex(sig.index).replace(0, np.nan)
    signal = zscore_ts(raw.fillna(0.0).where(raw.notna() | sig.isna()))
    # 判死门槛 (a):相邻评分窗口的 Spearman ρ
    ys = sorted(scores)
    pairs: list[tuple[float, float]] = []
    for a, b in zip(ys[:-1], ys[1:]):
        common = scores[a].index.intersection(scores[b].index)
        pairs += list(zip(scores[a][common].to_numpy(), scores[b][common].to_numpy()))
    if len(pairs) >= 10:
        arr = np.array(pairs)
        rho, pval = sps.spearmanr(arr[:, 0], arr[:, 1])
    else:
        rho, pval = np.nan, np.nan
    return PosBResult(
        signal.where(eligible.reindex_like(signal).fillna(False).astype(bool)),
        float(rho),
        float(pval),
        len(pairs),
        yearly,
        scores,
    )


def pooled_ic(signal: Frame, adj_close: Frame, h: int = 5) -> float:
    fwd = _forward_return(adj_close, h)
    a = signal.to_numpy(dtype=float).ravel()
    b = fwd.reindex_like(signal).to_numpy(dtype=float).ravel()
    ok = ~(np.isnan(a) | np.isnan(b))
    return float(sps.spearmanr(a[ok], b[ok]).statistic) if ok.sum() > 100 else float("nan")


def placebo_queues(
    net: Frame,
    adj_close: Frame,
    notional: Frame,
    oi_total: Frame,
    eligible: Frame,
    res: PosBResult,
    n_draws: int = 200,
    seed: int = 0,
    top_k: int = 3,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """按规模匹配的随机队列:每品种每年从"评分窗口内平均|净持仓|名义 与真实队列同一三分位"的会员里随机抽 3 个,重算信号的池化 IC。"""
    rng = np.random.default_rng(seed)
    trading = pd.DatetimeIndex(adj_close.index)
    net = net.sort_values(["symbol", "member", "date"]).copy()
    net["dnp"] = net.groupby(["symbol", "member"])["net"].diff()
    net["absn"] = (
        net["net"].abs()
        * notional.stack().reindex(pd.MultiIndex.from_frame(net[["date", "symbol"]])).to_numpy()
    )
    ics = np.full(n_draws, np.nan)
    # 预先按年、品种准备候选池
    pools: dict[tuple[int, str], tuple[list[str], list[str]]] = {}
    for y, q in res.yearly_queue.items():
        first = trading[trading >= pd.Timestamp(year=y, month=1, day=1)]
        if len(first) == 0:
            continue
        i0 = int(trading.searchsorted(first[0]))
        s_end, s_start = trading[max(i0 - 6, 0)], trading[max(i0 - 255, 0)]
        win = net[(net["date"] >= s_start) & (net["date"] <= s_end)]
        size = win.groupby(["symbol", "member"])["absn"].mean()
        for s, members in q.items():
            if s not in size.index.get_level_values(0):
                continue
            sz = size.xs(s).sort_values()
            terc = pd.qcut(sz.rank(method="first"), 3, labels=False)
            true_terc = set(terc.reindex(members).dropna().astype(int))
            cand = [m for m in sz.index if int(terc[m]) in true_terc and m not in members]
            pools[(y, s)] = (members, cand)
    net["year"] = net["date"].dt.year
    sub_by_key = {k: g for k, g in net.groupby(["year", "symbol"])}
    for d in range(n_draws):
        sig = pd.DataFrame(np.nan, index=trading, columns=adj_close.columns)
        for (y, s), (_members, cand) in pools.items():
            if len(cand) < top_k or (y, s) not in sub_by_key:
                continue
            pick = list(rng.choice(cand, size=top_k, replace=False))
            yr = sub_by_key[(y, s)]
            yr = yr[yr["member"].isin(pick)]
            daily = yr.groupby("date")["dnp"].sum()
            sig.loc[daily.index, s] = daily.to_numpy()
        raw = sig / oi_total.reindex(sig.index).replace(0, np.nan)
        z = zscore_ts(raw.fillna(0.0).where(raw.notna() | sig.isna())).where(
            eligible.reindex_like(sig).fillna(False).astype(bool)
        )
        ics[d] = pooled_ic(z, adj_close)
    return ics
