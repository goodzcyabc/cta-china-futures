"""候选因子定义(docs/design_log.md 4.2 表逐条对应)。每个因子只有一个定义,窗口写死,不做参数搜索。"""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

from cta.factors.base import FactorInputs, FactorSpec, register
from cta.signals.core import carry, carry_signal, log_returns, realized_vol, tsmom

Frame = pd.DataFrame
TRADING_DAYS = 243


def _ema(px: Frame, n: int) -> Frame:
    """Baz 等 (2015) 的时间尺度 n:λ = 1 − 1/n。"""
    out: Frame = px.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    return out


def ewmac(x: FactorInputs) -> Frame:
    px = x.adj_close
    sd63 = px.rolling(63, min_periods=40).std().replace(0, np.nan)
    acc: Frame | None = None
    for s, lng in ((8, 24), (16, 48), (32, 96)):
        y = (_ema(px, s) - _ema(px, lng)) / sd63
        z = y / y.rolling(252, min_periods=126).std().replace(0, np.nan)
        u = z * cast(Frame, np.exp(-(z**2) / 4.0)) / 0.89
        acc = u if acc is None else acc + u
    assert acc is not None
    return acc / 3.0


def breakout(x: FactorInputs) -> Frame:
    px = x.adj_close
    acc = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    for n in (63, 252):
        lo = px.rolling(n, min_periods=n // 2).min()
        hi = px.rolling(n, min_periods=n // 2).max()
        acc = acc + 2.0 * ((px - lo) / (hi - lo).replace(0, np.nan) - 0.5)
    return (acc / 2.0).where(px.notna())


def reversal_st(x: FactorInputs) -> Frame:
    px = x.adj_close
    out: Frame = px.rolling(12, min_periods=12).mean() / px - 1.0
    return out


def basis_mom(x: FactorInputs) -> Frame:
    near = log_returns(x.close)
    nxt = log_returns(x.next_close)
    same = (x.contract == x.contract.shift(1)) & (x.next_contract == x.next_contract.shift(1))
    d = (near - nxt).where(same)
    out: Frame = d.rolling(63, min_periods=40).sum()
    return out.where(d.notna() | out.notna())


def skew_neg(x: FactorInputs) -> Frame:
    out: Frame = -log_returns(x.adj_close).rolling(63, min_periods=40).skew()
    return out


def oi_growth(x: FactorInputs) -> Frame:
    oi = x.oi_total.where(x.oi_total > 0)
    out: Frame = cast(Frame, np.log(oi / oi.shift(21)))
    return out


def seasonal(x: FactorInputs) -> Frame:
    """同一日历月在此前各年的平均月对数收益(≥3 个样本);月内为常数,只用过去年份 → 无前视。"""
    px = x.adj_close
    m_end = px.resample("ME").last()
    mret = cast(Frame, np.log(m_end / m_end.shift(1)))
    out = pd.DataFrame(np.nan, index=mret.index, columns=mret.columns)
    months = pd.DatetimeIndex(mret.index).month
    for col in mret.columns:
        s = mret[col]
        vals = s.to_numpy(dtype=float)
        for i in range(len(s)):
            prior = vals[:i][months[:i] == months[i]]
            prior = prior[~np.isnan(prior)]
            if len(prior) >= 3:
                out.iat[i, out.columns.get_loc(col)] = float(prior.mean())
    daily = out.reindex(px.index, method="bfill")
    return daily.where(px.notna())


def carry_xs(x: FactorInputs) -> Frame:
    return carry(x.close, x.next_close, x.days_to_next)


def mom_xs(x: FactorInputs) -> Frame:
    px = x.adj_close
    out: Frame = cast(Frame, np.log(px.shift(21) / px.shift(252)))
    return out


def lowrisk_xs(x: FactorInputs) -> Frame:
    return -realized_vol(x.adj_close, 63, min_periods=40)


def htfc_a19(x: FactorInputs) -> Frame:
    # 收益先四舍五入到 1e-12:复权价的整体比例常数会带来 1e-16 级噪声,足以翻转并列值的名次
    ret = log_returns(x.adj_close).round(12)
    tr_vol = x.volume.rolling(32, min_periods=32).rank(pct=True)
    tr_range = (x.close + x.high - x.low).rolling(16, min_periods=16).rank(pct=True)
    tr_ret = ret.rolling(32, min_periods=32).rank(pct=True)
    out: Frame = tr_vol * (1.0 - tr_range) * (1.0 - tr_ret)
    return out


def ref_tsmom(x: FactorInputs) -> Frame:
    return tsmom(x.adj_close, (21, 63, 126, 252), vol=x.vol)


def ref_carry(x: FactorInputs) -> Frame:
    return carry_signal(carry(x.close, x.next_close, x.days_to_next), 0.20)


ALL_FACTORS: list[FactorSpec] = [
    register(
        FactorSpec(
            "tsmom",
            "趋势",
            "ts",
            "v0.1 时序动量(参照)",
            "Moskowitz-Ooi-Pedersen 2012",
            ref_tsmom,
            prestandardized=True,
            reference=True,
        )
    ),
    register(
        FactorSpec(
            "carry",
            "期限结构",
            "ts",
            "v0.1 展期收益 tanh(参照)",
            "Koijen 等 2018",
            ref_carry,
            prestandardized=True,
            reference=True,
        )
    ),
    register(
        FactorSpec(
            "ewmac",
            "趋势",
            "ts",
            "三组 EMA 差,价格波动与自身波动双重标准化后过响应函数",
            "Baz 等 2015",
            ewmac,
        )
    ),
    register(
        FactorSpec(
            "breakout",
            "趋势",
            "ts",
            "63/252 日通道位置",
            "Donchian;Bianchi-Drew-Fan;Hurst-Ooi-Pedersen 2017",
            breakout,
        )
    ),
    register(
        FactorSpec("reversal_st", "反转", "ts", "12 日均价/收盘 − 1", "华泰期货 HTFC_Alpha1", reversal_st)
    ),
    register(
        FactorSpec(
            "basis_mom",
            "期限结构",
            "ts",
            "63 日 Σ(近月 − 次近月 日对数收益)",
            "Boons & Prado 2019",
            basis_mom,
        )
    ),
    register(FactorSpec("skew_neg", "风险", "ts", "−63 日收益偏度", "Fernandez-Perez 等 2018", skew_neg)),
    register(
        FactorSpec("oi_growth", "资金", "ts", "全合约持仓量 21 日对数增长", "Hong & Yogo 2012", oi_growth)
    ),
    register(
        FactorSpec("seasonal", "季节", "ts", "同月历史平均月收益(≥3 年)", "Keloharju 等 2016", seasonal)
    ),
    register(FactorSpec("carry_xs", "期限结构", "xs", "年化展期收益横截面 z", "Koijen 等 2018", carry_xs)),
    register(
        FactorSpec(
            "mom_xs", "趋势", "xs", "12−1 月收益横截面 z", "Miffre & Rallis 2007;Asness 等 2013", mom_xs
        )
    ),
    register(
        FactorSpec("lowrisk_xs", "风险", "xs", "−63 日波动率横截面 z", "Blitz & de Groot 2014", lowrisk_xs)
    ),
    register(
        FactorSpec(
            "htfc_a19",
            "量价",
            "ts",
            "TS_Rank 量价复合(滚动 z 居中)",
            "华泰期货 HTFC_Alpha19",
            htfc_a19,
            center=True,
        )
    ),
]
