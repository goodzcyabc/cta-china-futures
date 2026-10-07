"""多源基本面合成因子 MSF(预注册 docs/research/msf_prereg.md;试验 60;演示)。

12 个成分(仓单、上期所非仓单库存、产区降雨、ENSO、新闻语调、河北 PM2.5、全市场持仓增长、PMI 订单/库存、
期权偏度、方差风险溢价、去趋势隐含波动率、工业品利润剪刀差;其中全市场持仓由持仓量 × 结算价构造,属量价数据,其余 11 个为非量价)各按自己预注册的定义、方向与可得规则算出 [−1, 1] 信号,
再用项目统一的 `combine`(等权、√(有值成分数/12) 归一)合成。不按收益、相关性给权重,不挑成分。
不是"世界模型":方法是多信号等权合成(预测组合)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from cta.config import StrategyConfig
from cta.continuous.roll import SymbolPanel
from cta.data.source import DataSource
from cta.instruments.specs import InstrumentTable
from cta.signals import core as sig
from cta_research.evaluation.candidate_eval import Candidate
from cta_research.signals import altdata_signals as alt
from cta_research.signals import fundamental_signals as fs
from cta_research.signals import options_signals as osig

Frame = pd.DataFrame

ALT_DIR = Path("data/external/alt")
MACRO_DIR = Path("data/ricecta/data/macro_factors")
EXCHANGE_DIR = Path("data/exchanges")
COMPONENTS = ("R", "S", "W", "E", "N", "Q", "A", "B", "O1", "O2", "O3", "P")
INDUSTRIAL_CLASSES = ("metal", "ferrous", "chem", "energy")
PMI_NO, PMI_FG = "制造业采购经理指数PMI_新订单.parquet", "制造业采购经理指数PMI_产成品库存.parquet"
PPI_FILE, PPIRM_FILE = (
    "PPI_全部工业品(全国_当期同比增长率_月).parquet",
    "PPIRM(全国_当期同比增长率_月).parquet",
)
P_CHANGE_MONTHS = 3


def _exchange_next_session(d: pd.Timestamp) -> pd.Timestamp:
    """交易所日历(历史 = 有行情文件的日期;未来 = 工作日 − configs/holidays.csv 已公告休市)上 ≥ d 的第一个交易日。
    休市安排都提前公告,不是前视。日历不可用时退回工作日(只会把节前月末当作未完成,晚一天,不会前视)。"""
    try:
        from cta.data.exchanges.calendar import TradingCalendar

        return TradingCalendar().next_session_on_or_after(d)
    except (OSError, ValueError, IndexError):
        return pd.Timestamp(d) + pd.offsets.BDay(0)


def completed_month_ends(
    dates: pd.DatetimeIndex, next_session: Callable[[pd.Timestamp], pd.Timestamp] | None = None
) -> pd.DatetimeIndex:
    """每个日历月的最后一个交易日;日历最后一天若不是该月最后一个交易日(按交易所日历,下一个交易日仍在同月)则不算,
    避免实盘用"月初至今"的半个月;节前月末(如 2020-01-23)按交易所日历算作完整月。"""
    me = fs.month_end_dates(dates)
    if len(me) and len(dates):
        last = pd.Timestamp(dates[-1])
        nxt = (next_session or _exchange_next_session)(last + pd.Timedelta(days=1))
        if (nxt.year, nxt.month) == (last.year, last.month):
            me = me[me < last]
    return pd.DatetimeIndex(me)


def _broadcast(daily: pd.Series[Any], basket: list[str], cols: list[str]) -> Frame:
    return fs.broadcast_signal(daily, basket, cols)


def _next_day(dates: pd.DatetimeIndex, t: pd.Timestamp) -> Any:
    after = dates[dates > t]
    return pd.Timestamp(after[0]) if len(after) else pd.NaT


TARGET_RULE = "on_or_after"  # 发布类成分(A、B、P)的目标日规则,见 fs.first_session_on_or_after


def release_audit(releases: list[fs.Release], dates: pd.DatetimeIndex) -> Frame:
    """每条发布一行:期末 data_date、实际公布日 publish_date、决策日 info_date = 目标日(公布日当天或之后第一个交易日)、
    建仓日 exec_day。publish_date ≤ target_day 由 release_timing_ok 单独检查;没有目标日的发布不产生信号。"""
    rows = []
    for r in releases:
        t = fs.first_session_on_or_after(r.info_date, dates)
        rows.append(
            {
                "data_date": r.period_end,
                "publish_date": r.info_date,
                "info_date": t if t is not None else pd.NaT,
                "available_day": t if t is not None else pd.NaT,
                "target_day": t if t is not None else pd.NaT,
                "exec_day": _next_day(dates, t) if t is not None else pd.NaT,
            }
        )
    cols = ["data_date", "publish_date", "info_date", "available_day", "target_day", "exec_day"]
    return pd.DataFrame(rows, columns=cols)


def release_timing_ok(audit: Frame) -> bool:
    """发布类成分:公布日(09:30)不晚于目标日;目标日 T 的成交在 T 日 21:00 夜盘或 T+1 日盘,均晚于公布。"""
    a = audit.dropna(subset=["target_day"])
    return bool((pd.to_datetime(a["publish_date"]) <= pd.to_datetime(a["target_day"])).all())


def _a_releases(
    src: DataSource, specs: InstrumentTable, dates: pd.DatetimeIndex, cols: list[str]
) -> list[fs.Release]:
    oi = fs.contract_open_interest(src, cols, specs)
    frame = oi.notional[(oi.notional.index >= dates[0]) & (oi.notional.index <= dates[-1])]
    me = completed_month_ends(dates)
    sector_of = {s: specs[s].asset_class for s in cols}
    x = fs.sector_ew_growth(frame, me, sector_of)["x"]
    sd = fs.signal_from_z(fs.expanding_z(x)).dropna()
    return [fs.Release(t, t, float(v)) for t, v in zip(pd.DatetimeIndex(sd.index), sd.to_numpy(dtype=float))]


def component_a(src: DataSource, specs: InstrumentTable, dates: pd.DatetimeIndex, cols: list[str]) -> Frame:
    """全市场名义持仓:六板块等权、12 个月几何平均增长 → 扩展 z → clip;月末收盘可得;全部品种同一信号。"""
    return _broadcast(
        fs.releases_to_daily(_a_releases(src, specs, dates, cols), dates, target_rule=TARGET_RULE), cols, cols
    )


def _signal_releases(
    values: pd.Series[Any], period_end: dict[pd.Timestamp, pd.Timestamp]
) -> list[fs.Release]:
    """values 以公布日为索引 → 扩展 z → clip → 发布记录。"""
    s = fs.signal_from_z(fs.expanding_z(values.sort_index()))
    sd = s.dropna()
    return [
        fs.Release(d, period_end[d], float(v))
        for d, v in zip(pd.DatetimeIndex(sd.index), sd.to_numpy(dtype=float))
    ]


def _b_releases(macro_dir: Path) -> list[fs.Release]:
    rel = fs.pmi_ratio_releases(
        fs.load_macro(str(macro_dir / PMI_NO)), fs.load_macro(str(macro_dir / PMI_FG))
    )
    ratio = pd.Series({r.info_date: r.value for r in rel}, dtype=float)
    pe = {r.info_date: r.period_end for r in rel}
    return _signal_releases(ratio, pe)


def component_b(
    dates: pd.DatetimeIndex, basket: list[str], cols: list[str], macro_dir: Path = MACRO_DIR
) -> Frame:
    """PMI 新订单 / 产成品库存:按公布日 → 扩展 z → clip;工业品 + 能源篮子。"""
    return _broadcast(
        fs.releases_to_daily(_b_releases(macro_dir), dates, target_rule=TARGET_RULE), basket, cols
    )


def _p_releases(macro_dir: Path) -> list[fs.Release]:
    ppi = {r.period_end: r for r in fs.load_macro(str(macro_dir / PPI_FILE))}
    ppirm = {r.period_end: r for r in fs.load_macro(str(macro_dir / PPIRM_FILE))}
    rows = sorted(
        (pe, max(ppi[pe].info_date, ppirm[pe].info_date), ppi[pe].value - ppirm[pe].value)
        for pe in sorted(set(ppi) & set(ppirm))
    )
    if len(rows) <= P_CHANGE_MONTHS:
        return []
    g = np.array([r[2] for r in rows], dtype=float)
    chg = g[P_CHANGE_MONTHS:] - g[:-P_CHANGE_MONTHS]
    info = [r[1] for r in rows[P_CHANGE_MONTHS:]]
    pe = {pd.Timestamp(r[1]): pd.Timestamp(r[0]) for r in rows[P_CHANGE_MONTHS:]}
    values = pd.Series(chg, index=pd.DatetimeIndex(info))
    values = values[~values.index.duplicated(keep="last")]
    return _signal_releases(values, pe)


def component_p(
    dates: pd.DatetimeIndex, basket: list[str], cols: list[str], macro_dir: Path = MACRO_DIR
) -> Frame:
    """工业品利润剪刀差:PPI 同比 − PPIRM 同比的 3 个月变化 → 扩展 z → clip(去极值);剪刀差扩大 → 多工业品。"""
    return _broadcast(
        fs.releases_to_daily(_p_releases(macro_dir), dates, target_rule=TARGET_RULE), basket, cols
    )


def _option_tables(alt_dir: Path) -> Frame:
    frames = [
        pd.read_parquet(alt_dir / name / "options_daily.parquet") for name in ("shfe_options", "czce_options")
    ]
    o = pd.concat(frames, ignore_index=True)
    o["date"] = pd.to_datetime(o["date"])
    o["available_day"] = pd.to_datetime(o["available_day"])
    return o[o["product"].isin(osig.PRODUCTS)]


def _futures_settles(exchange_dir: Path) -> pd.Series[Any]:
    parts = [
        pd.read_parquet(exchange_dir / ex / "quotes_all.parquet", columns=["date", "contract", "settle"])
        for ex in ("SHFE", "INE", "CZCE")
    ]
    q = pd.concat(parts, ignore_index=True)
    q["date"] = pd.to_datetime(q["date"])
    q = q.dropna(subset=["settle"]).drop_duplicates(["date", "contract"], keep="last")
    return pd.Series(
        q["settle"].to_numpy(dtype=float), index=pd.MultiIndex.from_arrays([q["date"], q["contract"]])
    )


def build_component_candidates(
    src: DataSource,
    cfg: StrategyConfig,
    specs: InstrumentTable,
    panels: dict[str, SymbolPanel],
    alt_dir: Path = ALT_DIR,
    macro_dir: Path = MACRO_DIR,
    exchange_dir: Path = EXCHANGE_DIR,
) -> dict[str, Candidate]:
    """12 个成分(信号 date × symbol,[−1, 1],篮子外 NaN;附点时审计表),全部按各自预注册的点时规则。"""
    from cta.pipeline import _wide, eligible_mask

    adj = _wide(panels, "adj_close")
    dates = pd.DatetimeIndex(adj.index)
    cols = [str(c) for c in adj.columns]
    eligible = eligible_mask(panels, cfg)
    industrial = [s for s in cols if specs[s].asset_class in INDUSTRIAL_CLASSES]
    out: dict[str, Candidate] = {}
    rl = sig.receipts_level(src.receipts(), dates, cols, eligible)
    # 仓单:T 日收盘后公布的 T 日数据 → T 日信号 → T+1 开盘(夜盘品种 T 日 21:00)成交
    out["R"] = Candidate(
        "R",
        "仓单水平",
        rl,
        pd.DataFrame(
            {
                "data_date": dates,
                "info_date": dates,
                "available_day": dates,
                "target_day": dates,
                "exec_day": [_next_day(dates, pd.Timestamp(d)) for d in dates],
            }
        ),
    )
    obs = {
        k: alt.load_observations(alt_dir / name / "observations.csv")
        for k, name in (
            ("W", "cpc_precip"),
            ("E", "nino34"),
            ("N", "gdelt_tone"),
            ("S", "shfe_weekly"),
            ("Q", "hebei_pm25"),
        )
    }
    out["S"] = alt.build_s(obs["S"], dates, cols)
    out["W"] = alt.build_w(obs["W"], dates, cols)
    out["E"] = alt.build_e(obs["E"], dates, cols)
    out["N"] = alt.build_n(obs["N"], dates, cols)[0]
    out["Q"] = alt.build_q(obs["Q"], dates, cols)
    rel_a = _a_releases(src, specs, dates, cols)
    out["A"] = Candidate(
        "A",
        "全市场名义持仓增长",
        _broadcast(fs.releases_to_daily(rel_a, dates, target_rule=TARGET_RULE), cols, cols),
        release_audit(rel_a, dates),
    )
    rel_b = _b_releases(macro_dir)
    out["B"] = Candidate(
        "B",
        "PMI 新订单 / 产成品库存",
        _broadcast(fs.releases_to_daily(rel_b, dates, target_rule=TARGET_RULE), industrial, cols),
        release_audit(rel_b, dates),
    )
    opts = _option_tables(alt_dir)
    settles = _futures_settles(exchange_dir)
    feats = {
        p: osig.product_daily_features(opts, settles, adj[p], p, float(specs[p].multiplier))
        for p in osig.PRODUCTS
        if p in cols
    }
    for tag in ("O1", "O2", "O3"):
        out[tag] = osig.build_candidate(tag, feats, dates, cols)
    rel_p = _p_releases(macro_dir)
    out["P"] = Candidate(
        "P",
        "工业品利润剪刀差(PPI − PPIRM 的 3 个月变化)",
        _broadcast(fs.releases_to_daily(rel_p, dates, target_rule=TARGET_RULE), industrial, cols),
        release_audit(rel_p, dates),
    )
    assert tuple(out) == COMPONENTS
    return {
        k: replace(c, signal=c.signal.reindex(index=dates, columns=cols).astype(float))
        for k, c in out.items()
    }


def build_components(
    src: DataSource,
    cfg: StrategyConfig,
    specs: InstrumentTable,
    panels: dict[str, SymbolPanel],
    alt_dir: Path = ALT_DIR,
    macro_dir: Path = MACRO_DIR,
    exchange_dir: Path = EXCHANGE_DIR,
) -> dict[str, Frame]:
    """12 个成分信号(date × symbol)。"""
    cands = build_component_candidates(src, cfg, specs, panels, alt_dir, macro_dir, exchange_dir)
    return {k: c.signal for k, c in cands.items()}


def combine_msf(components: dict[str, Frame]) -> Frame:
    """等权合成,√(有值成分数 / 成分总数) 归一,clip [−1, 1](与生产 combine 相同)。"""
    return sig.combine(components)


def build_msf(
    src: DataSource, cfg: StrategyConfig, specs: InstrumentTable, panels: dict[str, SymbolPanel]
) -> Frame:
    return combine_msf(build_components(src, cfg, specs, panels))
