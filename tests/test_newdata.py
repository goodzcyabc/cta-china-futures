"""新数据因子:合成数据上的套保压力、仓单因子方向、会员净持仓聚合与评分数学。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cta.factors import newdata as nd


def test_zscores_and_receipt_direction() -> None:
    idx = pd.bdate_range("2020-01-01", periods=300)
    rec = pd.DataFrame({"A": np.linspace(100, 1000, 300), "B": np.linspace(1000, 100, 300)}, index=idx)
    elig = pd.DataFrame(True, index=idx, columns=["A", "B"])
    f = nd.hrec(rec, idx, ["A", "B"], elig).dropna()
    # A 仓单持续增加 → 因子为负(做空);B 减少 → 正
    assert (f["A"] < 0).all() and (f["B"] > 0).all()
    lvl = nd.hrec_level(rec, idx, ["A", "B"], elig).dropna()
    assert (lvl["A"] < 0).all() and (lvl["B"] > 0).all()
    hp = pd.DataFrame({"A": np.linspace(-0.2, 0.2, 300)}, index=idx)  # 产业净多头上升
    a = nd.hpos_a(hp, idx, ["A"]).dropna()
    assert (a["A"] < 0).all()  # −HP 的 z 为负 → 做空


def test_member_scores_reward_right_direction() -> None:
    idx = pd.bdate_range("2020-01-01", periods=120)
    px = pd.DataFrame(
        {"A": 100 * np.exp(np.cumsum(np.where(np.arange(120) % 2 == 0, 0.01, -0.005)))}, index=idx
    )
    notional = px * 10
    rows = []
    step = np.where(np.arange(120) % 2 == 0, 1.0, -1.0)  # 偶数日加多(次日收益为正),奇数日减多
    good = 100 + np.cumsum(step)
    for i, d in enumerate(idx[:-8]):
        rows.append({"date": d, "symbol": "A", "member": "good", "net": float(good[i])})
        rows.append({"date": d, "symbol": "A", "member": "bad", "net": float(200 - good[i])})
    net = pd.DataFrame(rows)
    sc = nd.member_scores(net, px, notional, idx[0], idx[-1], h=1, min_events=10)
    assert sc.loc[("A", "good")] > 0 > sc.loc[("A", "bad")]
