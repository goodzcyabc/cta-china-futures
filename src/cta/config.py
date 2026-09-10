"""策略配置:pydantic 模型 + 稳定哈希。每次运行把配置哈希写进结果,保证可追溯。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field


class UniverseCfg(BaseModel):
    asset_classes: list[str]
    min_history_days: int = Field(ge=0)
    min_dominant_turnover_cny: float = Field(ge=0)


class SignalCfg(BaseModel):
    tsmom_lookbacks: list[int]
    vol_window: int = Field(gt=1)
    carry_scale: float = Field(gt=0)
    weights: dict[str, float]


class PortfolioCfg(BaseModel):
    target_vol: float = Field(gt=0, le=1)
    max_leverage_per_symbol: float = Field(gt=0)
    max_margin_usage: float = Field(gt=0, le=1)
    trade_buffer: float = Field(ge=0, le=1)


class ExecutionCfg(BaseModel):
    fill: Literal["next_open", "next_close"]
    slippage_ticks: float = Field(ge=0)
    roll_confirm_days: int = Field(ge=1)


class BacktestCfg(BaseModel):
    start: str
    end: str
    initial_capital_cny: float = Field(gt=0)
    cash_rate: Literal["none", "shibor_on"]


class StrategyConfig(BaseModel):
    version: str
    universe: UniverseCfg
    signals: SignalCfg
    portfolio: PortfolioCfg
    execution: ExecutionCfg
    backtest: BacktestCfg

    def digest(self) -> str:
        """配置内容的 sha256 前 12 位;字段顺序无关。"""
        blob = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


DEFAULT_PATH = Path(__file__).resolve().parents[2] / "configs" / "strategy.yaml"


def load_config(path: Optional[Path] = None) -> StrategyConfig:
    p = path or DEFAULT_PATH
    return StrategyConfig(**yaml.safe_load(p.read_text(encoding="utf-8")))
