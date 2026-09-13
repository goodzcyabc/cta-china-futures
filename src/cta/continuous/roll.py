"""换月与连续合约。

规则(预注册):
1. 候选主力 = 数据商每日主力;实际持有合约在候选**连续 confirm_days 天**不变后才切换,且只向更晚到期切换(不回滚)。
2. 切换日同时平旧开新,两笔都记成本(引擎负责);本模块只标记 roll 日与新旧合约。
3. 结算价用收盘价近似、涨跌停按前收盘自算(数据商的 dominant_daily 是复权后的连续价,不能与原始合约价混用)。
4. 回溯复权连续价(adj_close)只用于信号:在 roll 日用 新合约收盘/旧合约收盘 的比率把历史整体缩放。
5. 次主力 = 到期晚于持有合约、当日持仓量最大的合约;展期收益需要 (持有 − 次主力)/次主力 与两者到期间隔天数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

PANEL_COLS = [
    "contract",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "prev_settle",
    "limit_up",
    "limit_down",
    "volume",
    "open_interest",
    "multiplier",
    "margin_rate",
    "maturity",
    "roll",
    "roll_from",
    "roll_from_open",
    "adj_close",
    "next_contract",
    "next_close",
    "days_to_next",
    "oi_total",
    "volume_total",
]


@dataclass(frozen=True)
class SymbolPanel:
    symbol: str
    frame: pd.DataFrame  # index: date; columns: PANEL_COLS


def confirmed_dominant(cands: pd.Series[Any], maturity: pd.Series[Any], confirm_days: int) -> pd.Series[Any]:
    """把数据商每日候选主力变成实际持有序列:连续 confirm_days 天同一候选才切换,且到期只能变晚。"""
    held: list[str] = []
    cur: str | None = None
    run_c: str | None = None
    run_n = 0
    for c in cands.astype(str).tolist():
        if run_c == c:
            run_n += 1
        else:
            run_c, run_n = c, 1
        if cur is None:
            cur = c
        elif c != cur and run_n >= confirm_days:
            later = maturity.get(c, pd.NaT) > maturity.get(cur, pd.NaT)
            if bool(later):
                cur = c
        held.append(cur)
    return pd.Series(held, index=cands.index, name="contract")


def build_symbol_panel(
    symbol: str,
    contracts: pd.DataFrame,
    dominant_map: pd.DataFrame,
    meta: pd.DataFrame,
    limit_pct: float = 0.06,
    confirm_days: int = 3,
    margin_rate: float | None = None,
) -> SymbolPanel:
    dm = dominant_map[dominant_map["symbol"] == symbol].set_index("date")["contract"]
    maturity = meta.loc[meta["symbol"] == symbol, "maturity_date"]
    dates = contracts.index.get_level_values("date").unique().sort_values()
    dm = dm.reindex(dates).ffill().dropna()
    held = confirmed_dominant(dm, maturity, confirm_days)
    dates = held.index

    close = contracts["close"].unstack("contract").reindex(dates)
    openp = contracts["open"].unstack("contract").reindex(dates)
    oi = contracts["open_interest"].unstack("contract").reindex(dates)

    def pick(wide: pd.DataFrame, ids: pd.Series[Any]) -> pd.Series[Any]:
        arr = wide.reindex(columns=ids.unique())
        return pd.Series(
            [arr.at[d, c] if c in arr.columns else np.nan for d, c in ids.items()],
            index=ids.index,
            dtype=float,
        )

    f = pd.DataFrame(index=dates)
    f["contract"] = held.values
    for col in ["open", "high", "low", "close", "volume", "open_interest"]:
        f[col] = pick(contracts[col].unstack("contract").reindex(dates), held)
    # 结算价 ≈ 收盘价;涨跌停按前收盘与交易所幅度自算(合约级数据不含结算价与官方涨跌停)
    f["settle"] = f["close"].to_numpy(dtype=float)
    f["prev_settle"] = f["settle"].shift(1).to_numpy(dtype=float)
    prev_settle = f["prev_settle"].to_numpy(dtype=float)
    f["limit_up"] = prev_settle * (1 + limit_pct)
    f["limit_down"] = prev_settle * (1 - limit_pct)
    f["multiplier"] = held.map(meta["multiplier"]).values
    f["margin_rate"] = margin_rate if margin_rate is not None else held.map(meta["margin_rate"]).values
    f["maturity"] = held.map(maturity).values
    # roll 标记与旧合约当日开盘价(引擎在 roll 日按旧合约开盘平仓)
    prev = held.shift(1)
    roll_mask = np.asarray((prev.notna() & (prev != held)).to_numpy(), dtype=bool)
    f["roll"] = roll_mask
    f["roll_from"] = prev.where(roll_mask).to_numpy()
    f["roll_from_open"] = pd.Series(
        [
            openp.at[d, c] if isinstance(c, str) and c in openp.columns else np.nan
            for d, c in f["roll_from"].items()
        ],
        index=dates,
    ).values
    # 回溯复权:roll 日比率 = 新收盘/旧收盘(同一天两合约都有收盘)
    ratio = pd.Series(1.0, index=dates)
    for d in dates[roll_mask]:
        old = f.at[d, "roll_from"]
        if (
            isinstance(old, str)
            and old in close.columns
            and not np.isnan(close.at[d, old])
            and close.at[d, old] > 0
        ):
            ratio.at[d] = f.at[d, "close"] / close.at[d, old]
    cum = ratio[::-1].cumprod()[::-1].shift(-1).fillna(1.0)  # 历史乘以未来所有 roll 比率
    f["adj_close"] = f["close"].to_numpy(dtype=float) * cum.to_numpy(dtype=float)
    # 次主力:到期晚于持有、当日持仓量最大
    nxt: list[str | None] = []
    nxt_close: list[float] = []
    days: list[float] = []
    mat_by_c = maturity.to_dict()
    for d_, c in held.items():
        d = pd.Timestamp(str(d_))
        m_held = mat_by_c.get(c, pd.NaT)
        row = oi.loc[d].dropna() if d in oi.index else pd.Series(dtype=float)
        cand = [k for k in row.index if mat_by_c.get(k, pd.NaT) > m_held and row[k] > 0]
        if cand:
            best = max(cand, key=lambda k: row[k])
            nxt.append(best)
            nxt_close.append(close.at[d, best])
            days.append((mat_by_c[best] - m_held).days)
        else:
            nxt.append(None)
            nxt_close.append(np.nan)
            days.append(np.nan)
    f["next_contract"] = nxt
    f["next_close"] = nxt_close
    f["days_to_next"] = days
    # 全部合约合计(持仓量增长因子用):只在当日有任一合约数据时有值
    vol_all = contracts["volume"].unstack("contract").reindex(dates)
    f["oi_total"] = oi.sum(axis=1, min_count=1).to_numpy(dtype=float)
    f["volume_total"] = vol_all.sum(axis=1, min_count=1).to_numpy(dtype=float)
    return SymbolPanel(symbol, f[PANEL_COLS])
