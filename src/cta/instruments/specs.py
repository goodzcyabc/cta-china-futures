"""合约参数:从 configs/instruments.yaml 加载并校验。所有成本、保证金、涨跌停计算都从这里取数,禁止在别处写死。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Exchange = Literal["SHFE", "DCE", "CZCE", "INE", "CFFEX", "GFEX"]


class InstrumentSpec(BaseModel):
    symbol: str
    exchange: Exchange
    name: str
    multiplier: float = Field(gt=0, description="每手对应的标的数量(吨/克/桶/面值单位)")
    tick: float = Field(gt=0, description="最小变动价位")
    margin_rate: float = Field(gt=0, le=1)
    fee_per_lot: float = Field(ge=0, description="元/手,单边")
    fee_notional_bp: float = Field(ge=0, description="按成交金额万分比,单边")
    limit_pct: float = Field(gt=0, le=1, description="涨跌停幅度")
    asset_class: str
    fee_close_today: float = Field(
        default=0.0, ge=0, description="平今手续费(单位同开仓);仅记录,引擎不触发平今"
    )
    effective: str = Field(default="", description="现行值生效日或参数表日期")
    source: str = Field(default="", description="一手来源 URL")
    verified: bool = Field(
        default=True, description="False = 参数为占位/反推,只准用于研究,禁止进入纸面与实盘"
    )

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    def notional(self, price: float, lots: float = 1.0) -> float:
        return price * self.multiplier * lots

    def margin(self, price: float, lots: float = 1.0) -> float:
        return abs(self.notional(price, lots)) * self.margin_rate

    def fee(self, price: float, lots: float) -> float:
        """单边手续费(元)。"""
        lots = abs(lots)
        return lots * self.fee_per_lot + self.notional(price, lots) * self.fee_notional_bp / 1e4

    def slippage(self, lots: float, ticks: float) -> float:
        """滑点成本(元):每手 ticks 个最小变动价位。"""
        return abs(lots) * ticks * self.tick * self.multiplier


class InstrumentTable(BaseModel):
    verified: bool
    verified_date: str = ""
    note: str
    slippage_ticks_per_side: float = Field(ge=0)
    specs: dict[str, InstrumentSpec]

    def __getitem__(self, symbol: str) -> InstrumentSpec:
        return self.specs[symbol.upper()]

    def digest(self) -> str:
        """参数表指纹(8 位):同一策略配置在不同参数表下的结果目录必须不同。"""
        payload = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]

    def symbols(self, asset_classes: set[str] | None = None, verified_only: bool = False) -> list[str]:
        return sorted(
            s
            for s, sp in self.specs.items()
            if (asset_classes is None or sp.asset_class in asset_classes)
            and (sp.verified or not verified_only)
        )


DEFAULT_PATH = Path(__file__).resolve().parents[3] / "configs" / "instruments.yaml"


def load_instruments(path: Path = DEFAULT_PATH) -> InstrumentTable:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs = {k.upper(): InstrumentSpec(symbol=k, **v) for k, v in raw["symbols"].items()}
    return InstrumentTable(specs=specs, **raw["meta"])
