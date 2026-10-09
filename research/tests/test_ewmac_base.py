"""ewmac 基本盘前向统计与判读(预注册 docs/research/ewmac_base_prereg.md 4.2/4.3):只用合成权益,不读真实数据。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ewmac_base as eb  # noqa: E402


def _equity(daily: dict[str, float], base: float = 1.0) -> pd.Series:
    """2026-10-09 为基数日,之后按给定日收益连乘;再往前放几天注册前的数据(不该进统计)。"""
    pre = pd.bdate_range("2026-09-28", "2026-10-09")
    s = pd.Series(np.linspace(0.9, base, len(pre)), index=pre)
    vals, cur = [], base
    idx = pd.DatetimeIndex(list(daily))
    for r in daily.values():
        cur *= 1.0 + r
        vals.append(cur)
    return pd.concat([s, pd.Series(vals, index=idx)])


def _days(start: str, end: str, r: float) -> dict[str, float]:
    return {str(d.date()): r for d in pd.bdate_range(start, end)}


def test_forward_window_uses_oct9_base_and_counts_partial_october() -> None:
    daily = {**_days("2026-10-12", "2026-10-30", 0.001), **_days("2026-11-02", "2026-11-30", 0.002)}
    eq = _equity(daily)
    st = eb.forward_stats(eq, eq)
    assert st["base_date"] == "2026-10-09"
    assert st["first_date"] == "2026-10-12"
    assert st["n_months"] == 2
    oct_r = st["monthly_returns"]["2026-10"]
    assert np.isclose(oct_r, 1.001 ** len(pd.bdate_range("2026-10-12", "2026-10-30")) - 1.0)
    # 注册前的日子(09-28 → 10-09)不进入任何统计
    assert st["n_days"] == len(daily)


def test_monthly_sharpe_formula() -> None:
    rs = [0.01, -0.005, 0.02, 0.0, 0.015]
    daily: dict[str, float] = {}
    for i, m in enumerate(pd.period_range("2026-10", periods=5, freq="M")):
        start = max(m.start_time, pd.Timestamp("2026-10-12"))
        d = pd.bdate_range(start, m.end_time)
        per_day = (1.0 + rs[i]) ** (1.0 / len(d)) - 1.0
        daily.update({str(x.date()): per_day for x in d})
    st = eb.forward_stats(_equity(daily), _equity(daily))
    m = np.array(list(st["monthly_returns"].values()))
    assert np.allclose(m, rs)
    assert np.isclose(st["sharpe_monthly"], np.mean(rs) / np.std(rs, ddof=1) * np.sqrt(12))


def test_judge_order_and_thresholds() -> None:
    base = {"sharpe_monthly": 0.5, "paired_ann_mean": 0.01, "mdd_ewmac": -0.10, "mdd_v03": -0.08}
    assert eb.judge(base) == "未被否定"
    assert eb.judge({**base, "sharpe_monthly": 0.0}) == "否定"  # 夏普 ≤ 0
    assert eb.judge({**base, "sharpe_monthly": -0.3}) == "否定"
    # 回撤深 5 个百分点以上 → 否定,即使配对差 ≥ 0(否定优先)
    assert eb.judge({**base, "mdd_ewmac": -0.1301, "mdd_v03": -0.08}) == "否定"
    # 恰好深 5 个百分点(略浅于阈值)不触发
    assert eb.judge({**base, "mdd_ewmac": -0.1299, "mdd_v03": -0.08}) == "未被否定"
    assert eb.judge({**base, "paired_ann_mean": -0.001}) == "不优于"
    assert eb.judge({**base, "sharpe_monthly": float("nan")}).startswith("无法判读")


def test_paired_difference_sign_positive_means_ewmac_better() -> None:
    better = {**_days("2026-10-12", "2026-12-31", 0.002)}
    worse = {**_days("2026-10-12", "2026-12-31", 0.001)}
    st = eb.forward_stats(_equity(better), _equity(worse))
    assert st["paired_ann_mean"] > 0
    assert eb.judge(st) == "未被否定"


def test_candidate_audit_is_point_in_time() -> None:
    idx = pd.bdate_range("2026-01-05", periods=5)
    sig = pd.DataFrame({"CU": [0.1, 0.2, np.nan, 0.3, 0.4]}, index=idx)
    ok, audit = eb.ce.audit_candidate(eb.candidate(sig))
    assert ok
    assert (pd.to_datetime(audit["exec_day"].dropna()) > pd.to_datetime(audit["info_date"].iloc[:-1])).all()
