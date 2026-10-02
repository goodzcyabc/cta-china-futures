"""另类数据五条的信号构造(预注册 docs/altdata_prereg.md 第 2–7 节;常数写死,不提供搜索接口)。

输入是各数据管道的标准观测表(obs_date, available_day, key, value, meta...),输出是 cta.analysis.candidate_eval.Candidate。
点时规则由构造保证:
- 任一特征 f(D) 的可得日 = 其全部输入观测可得日的最大值(滚动窗口内取最大);
- 目标日 = 可得日或之后第一个交易日;信号从目标日起生效,直到下一条更新;超过失效期无新值 → NaN;
- 扩展 z 的均值/标准差只用"在目标日已可得"的特征值(按可得日累积),不是按观测日累积。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.analysis.candidate_eval import Candidate

Frame = pd.DataFrame

CLIP_Z = 2.0
MIN_OBS_DAILY = 500
MIN_OBS_WEEKLY = 104
STALE_DAYS = {"W": 10, "E": 21, "N": 7, "S": 14, "Q": 7}
MIN_LAG_DAYS = {"W": 4, "E": 7, "N": 2, "S": 1, "Q": 1}
W_WINDOW = 90
W_MIN_DAYS = 80
W_BASE_YEARS = (2006, 2015)
W_DOY_HALF = 15
N_SHORT, N_LONG = 7, 90
N_MIN_SHORT, N_MIN_LONG = 4, 60
N_COUNT_MIN = 20.0
Q_WINDOW, Q_MIN_DAYS = 7, 5
W_LEGS = {"W-P": ("P", -1.0), "W-SR": ("SR", -1.0), "W-RU": ("RU", 1.0), "W-AL": ("AL", -1.0)}
E_LEGS = {"P": 1.0, "SR": 1.0}
S_LEGS = {"S-CU": "CU", "S-AL": "AL", "S-NI": "NI", "S-SN": "SN", "S-RU": "RU"}
Q_LEGS = {"RB": 1.0, "I": -1.0, "J": -1.0}
N_PHRASES = {
    "AU": "gold price",
    "AG": "silver price",
    "CU": "copper price",
    "AL": "aluminium price",
    "NI": "nickel price",
    "SN": "tin price",
    "I": "iron ore",
    "J": "coking coal",
    "RB": "steel rebar",
    "MA": "methanol",
    "RU": "natural rubber",
    "SA": "soda ash",
    "TA": "purified terephthalic acid",
    "V": "polyvinyl chloride",
    "SC": "crude oil",
    "C": "corn futures",
    "CF": "cotton futures",
    "JD": "egg prices",
    "M": "soybean meal",
    "P": "palm oil",
    "SR": "sugar futures",
    "Y": "soybean oil",
}


@dataclass(frozen=True)
class Feature:
    """按观测日排序的特征值及其可得日。"""

    obs_date: pd.DatetimeIndex
    available_day: pd.DatetimeIndex
    value: np.ndarray[Any, Any]


def load_observations(path: Path) -> Frame:
    df = pd.read_csv(path)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    df["available_day"] = pd.to_datetime(df["available_day"])
    df = df.sort_values(["key", "obs_date"]).reset_index(drop=True)
    if df.duplicated(["key", "obs_date"]).any():
        raise ValueError(f"{path}: duplicate (key, obs_date)")
    return df


def check_min_lag(df: Frame, source: str) -> None:
    lag = (df["available_day"] - df["obs_date"]).dt.days
    if (lag < MIN_LAG_DAYS[source]).any():
        bad = df[lag < MIN_LAG_DAYS[source]].head()
        raise ValueError(f"{source}: available_day earlier than obs_date + {MIN_LAG_DAYS[source]}:\n{bad}")


def first_trading_day_on_or_after(day: pd.Timestamp, dates: pd.DatetimeIndex) -> pd.Timestamp | None:
    after = dates[dates >= day]
    return pd.Timestamp(after[0]) if len(after) else None


def rolling_feature(obs: Frame, window: int, min_count: int, agg: str) -> Feature:
    """按观测日的日历滚动窗口(window 个日历日,含当日)聚合 value;可得日 = 窗口内输入可得日的最大值。
    agg: 'sum' | 'mean'。窗口内有效观测少于 min_count → NaN。"""
    o = obs.sort_values("obs_date")
    idx = pd.DatetimeIndex(o["obs_date"])
    full = pd.date_range(idx.min(), idx.max(), freq="D")
    v = pd.Series(o["value"].to_numpy(dtype=float), index=idx).reindex(full)
    a = pd.Series(o["available_day"].to_numpy(), index=idx).reindex(full)
    cnt = v.notna().astype(float).rolling(window, min_periods=1).sum()
    if agg == "sum":
        f = v.rolling(window, min_periods=1).sum()
    elif agg == "mean":
        f = v.rolling(window, min_periods=1).mean()
    else:
        raise ValueError(agg)
    f = f.where(cnt >= min_count)
    av = (
        pd.to_datetime(a)
        .fillna(pd.Timestamp("1900-01-01"))
        .astype("int64")
        .rolling(window, min_periods=1)
        .max()
    )
    av_dt = pd.to_datetime(av.astype("int64"))
    keep = f.notna() & a.notna()
    return Feature(pd.DatetimeIndex(full[keep]), pd.DatetimeIndex(av_dt[keep]), f[keep].to_numpy(dtype=float))


def point_feature(obs: Frame) -> Feature:
    o = obs.sort_values("obs_date")
    return Feature(
        pd.DatetimeIndex(o["obs_date"]),
        pd.DatetimeIndex(o["available_day"]),
        o["value"].to_numpy(dtype=float),
    )


def pit_signal(
    feat: Feature, dates: pd.DatetimeIndex, min_obs: int, stale_days: int, sign: float
) -> tuple[pd.Series[Any], Frame]:
    """按可得日累积的扩展 z → clip ±2 / 2 × sign → 铺到交易日。返回 (日信号, 审计表)。
    每个交易日 t:可得集合 = {可得日 ≤ t 的特征};信号值用可得集合中观测日最新的那条;均值/标准差用整个可得集合(≥ min_obs 才有值);
    最新一条的可得日 + stale_days < t → NaN。"""
    order = np.lexsort((feat.obs_date.to_numpy(), feat.available_day.to_numpy()))
    av = feat.available_day.to_numpy()[order]
    od = feat.obs_date.to_numpy()[order]
    val = feat.value[order]
    out = pd.Series(np.nan, index=dates, dtype=float)
    audit_rows: list[dict[str, Any]] = []
    n = 0
    s1 = 0.0
    s2 = 0.0
    j = 0
    latest_obs = np.datetime64("1900-01-01")
    latest_val = np.nan
    latest_av = np.datetime64("1900-01-01")
    dates_np = dates.to_numpy()
    for i, t in enumerate(dates_np):
        while j < len(av) and av[j] <= t:
            x = val[j]
            if np.isfinite(x):
                n += 1
                s1 += x
                s2 += x * x
                if od[j] >= latest_obs:
                    latest_obs, latest_val, latest_av = od[j], x, av[j]
                    audit_rows.append(
                        {
                            "data_date": pd.Timestamp(od[j]),
                            "info_date": pd.Timestamp(t),
                            "available_day": pd.Timestamp(av[j]),
                            "target_day": pd.Timestamp(t),
                        }
                    )
            j += 1
        if n >= min_obs and np.isfinite(latest_val) and (t - latest_av) <= np.timedelta64(stale_days, "D"):
            mean = s1 / n
            var = (s2 - n * mean * mean) / (n - 1)
            if var > 0:
                z = (latest_val - mean) / np.sqrt(var)
                out.iloc[i] = sign * float(np.clip(z, -CLIP_Z, CLIP_Z) / CLIP_Z)
    audit = pd.DataFrame(audit_rows)
    if len(audit):
        pos_of = {pd.Timestamp(d): i for i, d in enumerate(dates)}
        exec_days = []
        for td in audit["target_day"]:
            pidx = pos_of.get(pd.Timestamp(td), -1)
            exec_days.append(pd.Timestamp(dates[pidx + 1]) if 0 <= pidx < len(dates) - 1 else pd.NaT)
        audit["exec_day"] = exec_days
    return out, audit


# ---------- W:产区 90 日降雨异常 ----------
def w_feature(obs_key: Frame) -> Feature:
    """log(1 + 90 日雨量和) − 同日历日(±15 日)在 2006–2015 的均值。基线只用基线年份,且只在该年份的观测可得后才算入(基线年份全在交易窗口之前)。"""
    roll = rolling_feature(obs_key, W_WINDOW, W_MIN_DAYS, "sum")
    x = pd.Series(np.log1p(roll.value), index=roll.obs_date)
    base = x[(x.index.year >= W_BASE_YEARS[0]) & (x.index.year <= W_BASE_YEARS[1])]
    doy = base.index.dayofyear.to_numpy()
    clim = np.full(367, np.nan)
    for d in range(1, 367):
        dist = np.minimum(np.abs(doy - d), 366 - np.abs(doy - d))
        m = dist <= W_DOY_HALF
        if m.sum() >= 5:
            clim[d] = float(base.to_numpy()[m].mean())
    f = x.to_numpy() - clim[x.index.dayofyear.to_numpy()]
    keep = np.isfinite(f)
    return Feature(roll.obs_date[keep], roll.available_day[keep], f[keep])


def build_w(obs: Frame, dates: pd.DatetimeIndex, columns: list[str]) -> Candidate:
    check_min_lag(obs, "W")
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    audits = []
    for key, (sym, sign) in W_LEGS.items():
        o = obs[obs["key"] == key]
        if len(o) == 0:
            continue
        s, a = pit_signal(w_feature(o), dates, MIN_OBS_DAILY, STALE_DAYS["W"], sign)
        sig[sym] = s
        a["key"] = key
        audits.append(a)
    return Candidate(
        "W", "产区 90 日降雨异常(CPC)", sig, pd.concat(audits, ignore_index=True), notes="W_LEGS"
    )


# ---------- E:ENSO 周度 Niño 3.4 ----------
def build_e(obs: Frame, dates: pd.DatetimeIndex, columns: list[str]) -> Candidate:
    check_min_lag(obs, "E")
    o = obs[obs["key"] == "E-NINO34"]
    feat = point_feature(o)
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    s, a = pit_signal(feat, dates, MIN_OBS_WEEKLY, STALE_DAYS["E"], 1.0)
    for sym, sign in E_LEGS.items():
        sig[sym] = s * sign
    a["key"] = "E-NINO34"
    x = pd.Series(feat.value, index=feat.obs_date)
    xa = pd.Series(
        x.to_numpy(),
        index=pd.DatetimeIndex(
            [first_trading_day_on_or_after(d, dates) or pd.NaT for d in feat.available_day]
        ),
    )
    xa = xa[pd.notna(xa.index)]
    xa = xa[~xa.index.duplicated(keep="last")]
    return Candidate("E", "ENSO 周度 Niño 3.4 异常", sig, a, x=xa, expected_sign=1)


# ---------- N:GDELT 语调 ----------
def n_feature(obs_key: Frame) -> Feature:
    short = rolling_feature(obs_key, N_SHORT, N_MIN_SHORT, "mean")
    long = rolling_feature(obs_key, N_LONG, N_MIN_LONG, "mean")
    s = pd.Series(short.value, index=short.obs_date)
    lg = pd.Series(long.value, index=long.obs_date)
    common = s.index.intersection(lg.index)
    f = (s.loc[common] - lg.loc[common]).to_numpy(dtype=float)
    av_s = pd.Series(short.available_day.to_numpy(), index=short.obs_date).loc[common]
    av_l = pd.Series(long.available_day.to_numpy(), index=long.obs_date).loc[common]
    av = np.maximum(av_s.to_numpy(), av_l.to_numpy())
    return Feature(pd.DatetimeIndex(common), pd.DatetimeIndex(av), f)


def n_basket(obs: Frame, count_col: str = "n_articles") -> dict[str, float]:
    """纳入规则:2017–2019 日文章数中位数 ≥ 20(只看计数)。返回每个品种的中位数。"""
    sub = obs[(obs["obs_date"] >= "2017-01-01") & (obs["obs_date"] <= "2019-12-31")]
    med = sub.groupby("key")[count_col].median()
    return {str(k).replace("N-", ""): float(v) for k, v in med.items()}


def build_n(obs: Frame, dates: pd.DatetimeIndex, columns: list[str]) -> tuple[Candidate, dict[str, float]]:
    check_min_lag(obs, "N")
    med = n_basket(obs)
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    audits = []
    for sym in columns:
        if med.get(sym, 0.0) < N_COUNT_MIN:
            continue
        o = obs[obs["key"] == f"N-{sym}"]
        if len(o) == 0:
            continue
        s, a = pit_signal(n_feature(o), dates, MIN_OBS_DAILY, STALE_DAYS["N"], 1.0)
        sig[sym] = s
        a["key"] = f"N-{sym}"
        audits.append(a)
    audit = (
        pd.concat(audits, ignore_index=True)
        if audits
        else pd.DataFrame(
            columns=["data_date", "info_date", "available_day", "target_day", "exec_day", "key"]
        )
    )
    return Candidate("N", "GDELT 新闻语调(7 日 − 90 日)", sig, audit, notes=str(med)), med


# ---------- S:上期所非仓单库存 ----------
def build_s(obs: Frame, dates: pd.DatetimeIndex, columns: list[str]) -> Candidate:
    check_min_lag(obs, "S")
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    audits = []
    for key, sym in S_LEGS.items():
        o = obs[obs["key"] == key].copy()
        if len(o) == 0:
            continue
        o["value"] = np.log1p(o["value"].clip(lower=0.0))
        s, a = pit_signal(point_feature(o), dates, MIN_OBS_WEEKLY, STALE_DAYS["S"], -1.0)
        sig[sym] = s
        a["key"] = key
        audits.append(a)
    return Candidate("S", "上期所周报非仓单可交割库存", sig, pd.concat(audits, ignore_index=True))


# ---------- Q:河北钢城 PM2.5 ----------
def build_q(obs: Frame, dates: pd.DatetimeIndex, columns: list[str]) -> Candidate:
    check_min_lag(obs, "Q")
    o = obs[obs["key"] == "Q-HEBEI4"].copy()
    roll = rolling_feature(o, Q_WINDOW, Q_MIN_DAYS, "mean")
    keep = roll.value > 0
    feat = Feature(roll.obs_date[keep], roll.available_day[keep], np.log(roll.value[keep]))
    s, a = pit_signal(feat, dates, MIN_OBS_DAILY, STALE_DAYS["Q"], 1.0)
    sig = pd.DataFrame(np.nan, index=dates, columns=columns, dtype=float)
    for sym, sign in Q_LEGS.items():
        sig[sym] = s * sign
    a["key"] = "Q-HEBEI4"
    return Candidate("Q", "河北四钢城 PM2.5 7 日均值", sig, a)
