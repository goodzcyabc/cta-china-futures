"""商品期权隐含信息三条的特征与信号(预注册 docs/options_prereg.md 第 3–6 节;常数写死,不提供搜索接口)。

输入:期权日行情标准表(cta.data.alt.shfe_options / czce_options 的 options_daily.parquet)、
标的期货逐合约结算价(data/exchanges/<EX>/quotes_all.parquet)、项目复权连续价(已实现波动)。
每个 (品种, T) 只用 T 当日及以前的数据;可得日 = 表中 available_day(T 之后第一个交易日)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import norm

from cta.analysis.altdata_signals import Feature, pit_signal
from cta.analysis.candidate_eval import Candidate

Frame = pd.DataFrame
FloatArr = npt.NDArray[np.float64]

PRODUCTS = ("CU", "RU", "AU", "AL", "SC", "AG", "RB", "NI", "SN", "SR", "CF", "MA", "TA", "SA")
RATE = 0.015
MIN_MONTHS_AHEAD = 2
DELTA_LO, DELTA_HI = 0.10, 0.40
SMOOTH_DAYS, SMOOTH_MIN = 5, 3
RV_DAYS = 21
DETREND_DAYS, DETREND_MIN = 243, 120
MIN_OBS = 250
STALE_DAYS = 10
SIGNS = {"O1": 1.0, "O2": 1.0, "O3": -1.0}


# ---------- Black-76 ----------
def black76_price(
    f: FloatArr, k: FloatArr, tau: FloatArr, sigma: FloatArr, is_call: npt.NDArray[np.bool_], r: float = RATE
) -> FloatArr:
    sq = sigma * np.sqrt(tau)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(f / k) + 0.5 * sigma * sigma * tau) / sq
    d2 = d1 - sq
    df = np.exp(-r * tau)
    call = df * (f * norm.cdf(d1) - k * norm.cdf(d2))
    put = df * (k * norm.cdf(-d2) - f * norm.cdf(-d1))
    out: FloatArr = np.where(is_call, call, put)
    return out


def black76_iv(
    price: FloatArr,
    f: FloatArr,
    k: FloatArr,
    tau: FloatArr,
    is_call: npt.NDArray[np.bool_],
    r: float = RATE,
    iters: int = 100,
) -> FloatArr:
    """向量化二分法反解 Black-76 隐含波动率;价格不在 (折现内在价值, 折现上界) 内 → NaN。"""
    price = np.asarray(price, dtype=float)
    f = np.asarray(f, dtype=float)
    k = np.asarray(k, dtype=float)
    tau = np.asarray(tau, dtype=float)
    df = np.exp(-r * tau)
    intrinsic = np.where(is_call, np.maximum(f - k, 0.0), np.maximum(k - f, 0.0)) * df
    upper = np.where(is_call, f, k) * df
    ok = (
        np.isfinite(price)
        & np.isfinite(f)
        & np.isfinite(k)
        & (tau > 0)
        & (price > intrinsic + 1e-12)
        & (price < upper)
    )
    lo = np.full(price.shape, 1e-4)
    hi = np.full(price.shape, 5.0)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p = black76_price(f, k, tau, mid, is_call, r)
        high = p > price
        hi = np.where(high, mid, hi)
        lo = np.where(high, lo, mid)
    iv: FloatArr = np.where(ok, 0.5 * (lo + hi), np.nan)
    return iv


# ---------- 系列选择 ----------
def contract_month_index(code: str) -> int:
    """CU2611 → 2026×12 + 11。"""
    digits = "".join(ch for ch in code if ch.isdigit())[-4:]
    return (2000 + int(digits[:2])) * 12 + int(digits[2:])


def select_series(day: Frame, t: pd.Timestamp) -> str | None:
    """交割月 ≥ T 所在月 + 2 的系列中期权总持仓最大者(并列取交割月更近者);该系列当日期权总成交量为 0 → None。"""
    ser = day.groupby("underlying", as_index=False).agg(
        series_oi=("series_oi", "first"), series_volume=("series_volume", "first")
    )
    ser["midx"] = ser["underlying"].map(contract_month_index)
    ser = ser[ser["midx"] >= t.year * 12 + t.month + MIN_MONTHS_AHEAD]
    if ser.empty:
        return None
    ser = ser.sort_values(["series_oi", "midx"], ascending=[False, True])
    top = ser.iloc[0]
    if not (float(top["series_volume"]) > 0):
        return None
    return str(top["underlying"])


@dataclass(frozen=True)
class DailyFeatures:
    product: str
    table: Frame  # date, available_day, underlying, F, skew, sigma_a, rv, vrp


def option_iv(rows: Frame, f: float, use_exchange_iv: bool, price_col: str, multiplier: float) -> FloatArr:
    if use_exchange_iv:
        out: FloatArr = rows["iv_exchange"].to_numpy(dtype=float)
        return out
    if price_col == "vwap":
        price = (rows["turnover"] / (rows["volume"] * multiplier)).to_numpy(dtype=float)
    else:
        price = rows[price_col].to_numpy(dtype=float)
    tau = (
        (pd.to_datetime(rows["expire_date"]) - pd.to_datetime(rows["date"])).dt.days.to_numpy(dtype=float)
        + 1.0
    ) / 365.0
    n = len(rows)
    return black76_iv(
        price, np.full(n, f), rows["strike"].to_numpy(dtype=float), tau, (rows["cp"] == "C").to_numpy()
    )


def product_daily_features(
    opts: Frame, settles: pd.Series[Any], adj_close: pd.Series[Any], product: str, multiplier: float
) -> DailyFeatures:
    """一个品种的逐日原始特征。opts:该品种全部期权行;settles:index=(date, contract) 的期货结算价;adj_close:复权连续价。"""
    o = opts[opts["product"] == product].copy()
    if "is_serial" in o.columns:  # 郑商所系列期权(到期更早)不属于常规系列,预注册的系列定义不含
        o = o[~o["is_serial"].fillna(False).astype(bool)]
    o["date"] = pd.to_datetime(o["date"])
    use_exch = bool((o["exchange"] == "CZCE").all()) if len(o) else False
    px = adj_close.astype(float)
    lr = pd.Series(np.log(px.to_numpy()), index=px.index).diff()
    rv = ((lr**2).rolling(RV_DAYS, min_periods=RV_DAYS).sum() * 243.0 / RV_DAYS) ** 0.5
    rows: list[dict[str, Any]] = []
    for _, day in o.groupby("date", sort=True):
        ts = pd.Timestamp(day["date"].iloc[0])
        und = select_series(day, ts)
        rec: dict[str, Any] = {
            "date": ts,
            "available_day": pd.Timestamp(day["available_day"].iloc[0]),
            "underlying": und,
            "F": np.nan,
            "skew": np.nan,
            "sigma_a": np.nan,
        }
        if und is not None:
            f = settles.get((ts, und), np.nan)
            rec["F"] = float(f) if f is not None else np.nan
            ser = day[day["underlying"] == und]
            if np.isfinite(rec["F"]):
                fval = float(rec["F"])
                # O1:成交的 0.10–0.40 delta 看涨 / 看跌
                traded = ser[ser["volume"] > 0]
                if (
                    "has_ohlc" in traded.columns
                ):  # 上期所:成交全部按结算价(无开高低)的合约不含偏度信息,视为未成交(预注册第 7 节)
                    traded = traded[traded["has_ohlc"].fillna(True).astype(bool)]
                calls = traded[
                    (traded["cp"] == "C") & (traded["delta"] >= DELTA_LO) & (traded["delta"] <= DELTA_HI)
                ]
                puts = traded[
                    (traded["cp"] == "P") & (traded["delta"] <= -DELTA_LO) & (traded["delta"] >= -DELTA_HI)
                ]
                if len(calls) and len(puts):
                    ivc = option_iv(calls, fval, use_exch, "vwap", multiplier)
                    ivp = option_iv(puts, fval, use_exch, "vwap", multiplier)
                    wc, wp = calls["volume"].to_numpy(dtype=float), puts["volume"].to_numpy(dtype=float)
                    mc, mp = np.isfinite(ivc), np.isfinite(ivp)
                    if mc.any() and mp.any():
                        c = float(np.average(ivc[mc], weights=wc[mc]))
                        p = float(np.average(ivp[mp], weights=wp[mp]))
                        if p > 0:
                            rec["skew"] = (c - p) / p
                # O2/O3:最接近 F 的执行价上看涨与看跌的结算价 IV 平均
                strikes = ser["strike"].astype(float)
                if len(strikes):
                    kstar = float(strikes.iloc[int(np.argmin(np.abs(strikes.to_numpy() - fval)))])
                    atm = ser[np.isclose(ser["strike"].astype(float), kstar)]
                    iv = option_iv(atm, fval, use_exch, "settle", multiplier)
                    iv = iv[np.isfinite(iv) & (iv > 0)]
                    if len(iv):
                        rec["sigma_a"] = float(iv.mean())
        rows.append(rec)
    tab = pd.DataFrame(rows)
    if tab.empty:
        return DailyFeatures(product, tab)
    tab["rv"] = rv.reindex(tab["date"]).to_numpy(dtype=float)
    tab["vrp"] = tab["sigma_a"] ** 2 - tab["rv"] ** 2
    tab["skew5"] = tab["skew"].rolling(SMOOTH_DAYS, min_periods=SMOOTH_MIN).mean()
    tab["vrp5"] = tab["vrp"].rolling(SMOOTH_DAYS, min_periods=SMOOTH_MIN).mean()
    base = tab["sigma_a"].rolling(DETREND_DAYS, min_periods=DETREND_MIN).mean()
    tab["iv_detrended"] = tab["sigma_a"] / base
    return DailyFeatures(product, tab)


def feature_of(tab: Frame, col: str) -> Feature:
    t = tab[np.isfinite(tab[col].to_numpy(dtype=float))]
    return Feature(
        pd.DatetimeIndex(t["date"]), pd.DatetimeIndex(t["available_day"]), t[col].to_numpy(dtype=float)
    )


FEATURE_COL = {"O1": "skew5", "O2": "vrp5", "O3": "iv_detrended"}
NAMES = {"O1": "期权偏度(看涨相对看跌溢价)", "O2": "方差风险溢价(ATM IV² − RV²)", "O3": "去趋势隐含波动率"}


def build_candidate(
    tag: str, feats: dict[str, DailyFeatures], dates: pd.DatetimeIndex, columns: list[str]
) -> Candidate:
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    audits = []
    for prod, df in feats.items():
        if prod not in columns or df.table.empty:
            continue
        if (df.table["available_day"] <= df.table["date"]).any():
            raise ValueError(f"{prod}: available_day not after date")
        s, a = pit_signal(feature_of(df.table, FEATURE_COL[tag]), dates, MIN_OBS, STALE_DAYS, SIGNS[tag])
        sig[prod] = s
        a["key"] = f"{tag}-{prod}"
        audits.append(a)
    audit = (
        pd.concat(audits, ignore_index=True)
        if audits
        else pd.DataFrame(
            columns=["data_date", "info_date", "available_day", "target_day", "exec_day", "key"]
        )
    )
    return Candidate(tag, NAMES[tag], sig, audit)
