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
    allow_unverified: bool = (
        False  # True 只允许出现在研究配置:让 instruments.yaml 里 verified: false 的品种进池
    )
    # Python 3.9 运行时 pydantic 无法求值 `list[str] | None`(字符串注解),故用 Optional;显式品种清单,生产配置必填
    symbols: Optional[list[str]] = None


class TickFilterCfg(BaseModel):
    """跳价过滤(design_log 十一 E2):每月末按 tick/EWMA(|Δp|) 排名,前 top_quantile 的大跳价品种次月 tsmom 只用 slow_lookbacks。"""

    enabled: bool = False
    window: int = Field(default=336, gt=10)
    top_quantile: float = Field(default=0.5, gt=0, lt=1)
    slow_lookbacks: list[int] = Field(default_factory=lambda: [126, 252])


class RegOverlayCfg(BaseModel):
    """监管事件覆盖层(design_log 13.6):交易所上调保证金/手续费(非节假日)后 window 个交易日,该品种 tsmom × scale。
    事件每日由数据层 params 机械推导(require_restore=False:实盘不能等 10 日看是否恢复,节前上调用休市日历判定)。"""

    enabled: bool = False
    window: int = Field(default=21, gt=0)
    scale: float = Field(default=0.5, ge=0, le=1)


class SignalCfg(BaseModel):
    tsmom_lookbacks: list[int]
    vol_window: int = Field(gt=1)
    carry_scale: float = Field(gt=0)
    weights: dict[str, float]
    tick_filter: TickFilterCfg = Field(default_factory=TickFilterCfg)
    # 板块因子菜单(design_log 十二):asset_class → 允许的因子名;未列出的板块 = 全部因子。symbol_menu 为品种级覆盖(如 JD)。
    sector_menu: dict[str, list[str]] = Field(default_factory=dict)
    symbol_menu: dict[str, list[str]] = Field(default_factory=dict)
    # 因子加权规则:equal = 菜单内等权;inverse_vol = 按各因子信号的池化滚动波动率倒数加权(不含收益信息)
    factor_weighting: Literal["equal", "inverse_vol"] = "equal"
    reg_overlay: RegOverlayCfg = Field(default_factory=RegOverlayCfg)


class PortfolioCfg(BaseModel):
    target_vol: float = Field(gt=0, le=1)
    max_leverage_per_symbol: float = Field(gt=0)
    max_gross_exposure: float = Field(gt=0)
    max_margin_usage: float = Field(gt=0, le=1)
    exposure_buffer: float = Field(
        ge=0, le=1, description="信号层暴露缓冲:|新目标−旧目标| ≤ band×|新目标| 时目标不变"
    )
    lot_band: float = Field(
        ge=0, le=1, description="执行层手数带:|目标手数−持仓| < band×max(1,|持仓|) 时不交易(清仓除外)"
    )
    vol_scale_update: Literal["daily", "weekly"] = "daily"


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


def load_config(path: Path | None = None) -> StrategyConfig:
    p = path or DEFAULT_PATH
    return StrategyConfig(**yaml.safe_load(p.read_text(encoding="utf-8")))
