"""目标手数规划:回测引擎、实盘出单、纸面账本共用的唯一规则(design_log 十七 → 17.6 第 4 项)。

时间线:T 日收盘后,用 T+1 将持有的合约在 T 日的收盘价把目标暴露换成整手,写成**绝对目标手数**;T+1 开盘成交。
三步(顺序固定):
  ① 手数 = round(目标暴露 × 权益 / (参考价 × 乘数));无有效参考价的品种保持当前持仓;
  ② 预计保证金 = Σ|手数| × 参考价 × 乘数 × 保证金率 > 上限 × 权益 时,全体等比缩减并向零取整;
  ③ 手数带:目标 ≠ 0 且 |目标 − 持仓| < band × max(1, |持仓|) 时保持持仓(清仓不受限)。
暴露层的交易缓冲(signals.core.trade_buffer,配置 exposure_buffer)在信号层另算,量纲不同,两者不是重复。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SymbolInputs:
    exposure: float  # 目标名义暴露 / 权益(信号层输出)
    ref_price: float  # 定手数用的价格:T 日 T+1 将持有合约的收盘价(缺则该品种保持持仓)
    multiplier: float
    margin_rate: float
    held_lots: float


@dataclass(frozen=True)
class PlanResult:
    lots: dict[str, float]  # symbol → 绝对目标手数(正多负空)
    margin_before: float  # 缩减前预计保证金(元)
    margin_after: float  # 缩减后预计保证金(元)
    scaled: bool  # 是否触发了保证金上限缩减


def band_adjusted(want: float, held: float, band: float) -> float:
    """手数带:want != 0 且 |want − held| < band × max(1, |held|) 时保持 held。"""
    if want != 0 and abs(want - held) < band * max(1.0, abs(held)):
        return held
    return want


def projected_margin(inputs: dict[str, SymbolInputs], lots: dict[str, float]) -> float:
    """按参考价估计的保证金占用(元);无参考价的品种不计。"""
    return float(
        sum(
            abs(lots[s]) * x.ref_price * x.multiplier * x.margin_rate
            for s, x in inputs.items()
            if np.isfinite(x.ref_price)
        )
    )


def plan_lots(
    inputs: dict[str, SymbolInputs],
    equity: float,
    lot_band: float,
    max_margin_usage: float,
) -> PlanResult:
    want: dict[str, float] = {}
    priced: dict[str, bool] = {}
    for s, x in inputs.items():
        ok = bool(np.isfinite(x.ref_price) and x.ref_price > 0 and np.isfinite(x.exposure) and equity > 0)
        priced[s] = ok
        want[s] = float(np.round(x.exposure * equity / (x.ref_price * x.multiplier))) if ok else x.held_lots
    before = projected_margin(inputs, want)
    scaled = bool(equity > 0 and before > max_margin_usage * equity)
    if scaled:
        k = max_margin_usage * equity / before
        for s in inputs:
            if priced[s]:
                want[s] = float(np.trunc(want[s] * k))
    for s, x in inputs.items():
        want[s] = band_adjusted(want[s], x.held_lots, lot_band)
    return PlanResult(want, before, projected_margin(inputs, want), scaled)
