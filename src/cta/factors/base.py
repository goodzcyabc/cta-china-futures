"""因子基础设施:输入容器、因子规格、注册表、统一标准化。

约定(与 cta.signals 一致):因子原值经 fn 已带方向,"正 = 做多";标准化后取值在 [-1, 1]。
时序(ts)因子:原值 / 自身 252 日滚动标准差(center=True 时先减滚动均值),clip ±2 再 /2;
横截面(xs)因子:每日在可投品种内做 z-score,clip ±2 再 /2。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from cta.config import StrategyConfig
from cta.continuous.roll import SymbolPanel
from cta.pipeline import _wide, eligible_mask
from cta.signals.core import realized_vol

Frame = pd.DataFrame
Kind = Literal["ts", "xs"]


@dataclass(frozen=True)
class FactorInputs:
    """因子计算所需的宽表(index=日期, columns=品种)。全部由 SymbolPanel 派生,不读文件。"""

    adj_close: Frame
    close: Frame
    high: Frame
    low: Frame
    volume: Frame
    open_interest: Frame
    next_close: Frame
    days_to_next: Frame
    contract: Frame
    next_contract: Frame
    oi_total: Frame
    volume_total: Frame
    vol: Frame
    eligible: Frame

    @classmethod
    def from_panels(cls, panels: dict[str, SymbolPanel], cfg: StrategyConfig) -> FactorInputs:
        adj = _wide(panels, "adj_close")
        return cls(
            adj_close=adj,
            close=_wide(panels, "close"),
            high=_wide(panels, "high"),
            low=_wide(panels, "low"),
            volume=_wide(panels, "volume"),
            open_interest=_wide(panels, "open_interest"),
            next_close=_wide(panels, "next_close"),
            days_to_next=_wide(panels, "days_to_next"),
            contract=_wide(panels, "contract"),
            next_contract=_wide(panels, "next_contract"),
            oi_total=_wide(panels, "oi_total"),
            volume_total=_wide(panels, "volume_total"),
            vol=realized_vol(adj, cfg.signals.vol_window),
            eligible=eligible_mask(panels, cfg),
        )


@dataclass(frozen=True)
class FactorSpec:
    name: str
    family: str
    kind: Kind
    description: str
    source: str
    fn: Callable[[FactorInputs], Frame]
    center: bool = False  # ts 因子原值若不居中,标准化前先减滚动均值
    prestandardized: bool = False  # 已在 [-1,1](v0.1 参照信号),不再标准化
    reference: bool = False  # 参照信号,不计新试验

    def compute(self, x: FactorInputs) -> Frame:
        raw = self.fn(x)
        return raw if self.prestandardized else standardize(raw, self.kind, x.eligible, center=self.center)


REGISTRY: dict[str, FactorSpec] = {}


def register(spec: FactorSpec) -> FactorSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"factor {spec.name} already registered")
    REGISTRY[spec.name] = spec
    return spec


def standardize(
    raw: Frame,
    kind: Kind,
    eligible: Frame,
    *,
    center: bool = False,
    window: int = 252,
    min_periods: int = 126,
) -> Frame:
    if kind == "xs":
        r = raw.where(eligible.reindex_like(raw).fillna(False).astype(bool))
        z = r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)
    else:
        r = raw - raw.rolling(window, min_periods=min_periods).mean() if center else raw
        z = r / r.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    out: Frame = (z.clip(-2, 2) / 2.0).where(raw.notna())
    return out
