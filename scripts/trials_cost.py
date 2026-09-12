"""二b 成本导向试验(见 design_log)。每个候选用配置副本跑完整流程,输出对比表。"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cta.config import load_config
from cta.data.source import RicequantParquetSource
from cta.instruments.specs import load_instruments
from cta.pipeline import run_research

base = load_config()
specs = load_instruments()
src = RicequantParquetSource(Path("data/ricecta/data"))
variants = {
    "主方案": {},
    "a 缓冲带0.3": {"portfolio": {"trade_buffer": 0.30}},
    "b 缩放按周": {"portfolio": {"vol_scale_update": "weekly"}},
    "c a+b": {"portfolio": {"trade_buffer": 0.30, "vol_scale_update": "weekly"}},
    "d 单品种上限0.25": {"portfolio": {"max_leverage_per_symbol": 0.25}},
}
rows = {}
for name, upd in variants.items():
    d = base.model_dump()
    for k, v in upd.items():
        d[k].update(v)
    cfg = type(base)(**d)
    meta = run_research(cfg, src, specs, Path("results") / "trials" / f"{cfg.digest()}_{specs.digest()}")
    st = meta["stats"]
    rows[name] = {
        k: st.get(k)
        for k in [
            "年化收益",
            "年化波动",
            "夏普(月频)",
            "月频NW t",
            "最大回撤",
            "年化名义换手(倍)",
            "年化滑点占权益",
            "年化手续费占权益",
            "平均总名义暴露",
        ]
    }
    rows[name]["digest"] = cfg.digest()
    print(name, "done", flush=True)
t = pd.DataFrame(rows).T
pd.set_option("display.width", 220)
print(t.to_string())
t.to_csv("results/trials/cost_trials.csv")
