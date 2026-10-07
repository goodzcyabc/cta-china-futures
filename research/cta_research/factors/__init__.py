"""因子研究:候选因子定义(library)、统一标准化(base)、快速评估与多重检验(evaluate)。
预注册见 docs/design_log.md 第四节;这里的代码不参与生产出单,生产信号仍在 cta.signals。"""

from cta_research.factors.base import REGISTRY, FactorInputs, FactorSpec, register, standardize
from cta_research.factors.library import ALL_FACTORS

__all__ = ["ALL_FACTORS", "REGISTRY", "FactorInputs", "FactorSpec", "register", "standardize"]
