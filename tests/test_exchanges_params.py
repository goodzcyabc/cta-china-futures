"""每日风控参数(kind="params"):用 tests/fixtures 里的截断样例测解析与校验(不联网);推导逻辑用合成数据测;
有本地数据时与 docs/instruments_verification*.md 已核验的 2026 现行值对照。"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges import params as xp
from cta.data.exchanges.base import PARAM_COLS, Store, validate

FIX = Path(__file__).parent / "fixtures" / "exchanges" / "params"
ROOT = Path(__file__).resolve().parents[1]
EXCH = ROOT / "data" / "exchanges"


def _fx(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# 解析:上期所 / 能源中心
# ---------------------------------------------------------------------------------------------


def test_parse_shfe_new_format_fee_units_discount_and_limit() -> None:
    """2026 格式:比例手续费 → bp、按手数 → 元/手;平今 = 折扣率 × 开仓费;涨跌停取交易参数文件;能源中心品种剔除。"""
    df = xp.parse_shfe_params(
        _fx("Settlement20260918.dat"),
        _fx("ContractDailyTradeArgument20260918.dat"),
        pd.Timestamp("2026-09-18"),
    )
    assert list(df.columns) == PARAM_COLS
    assert sorted(df["contract"]) == ["AL2610", "AU2612", "CU2610", "CU2611", "FU2610", "RB2610", "RB2612"]
    assert (df["exchange"] == "SHFE").all()
    r = df.set_index("contract")
    cu = r.loc["CU2610"]
    assert (cu["margin_spec"], cu["margin_hedge"], cu["limit_pct"]) == (0.11, 0.10, 0.09)
    assert (cu["fee_open"], cu["fee_open_unit"]) == (0.5, "bp")  # 0.00005 → 万分之 0.5
    assert (cu["fee_close_today"], cu["fee_close_today_unit"]) == (1.0, "bp")  # 折扣率 2 → 平今双倍
    al = r.loc["AL2610"]
    assert (al["fee_open"], al["fee_open_unit"], al["fee_close_today"]) == (3.0, "CNY_per_lot", 3.0)
    au = r.loc["AU2612"]
    assert (au["fee_open"], au["fee_close_today"], au["margin_spec"], au["limit_pct"]) == (
        20.0,
        0.0,
        0.16,
        0.14,
    )
    assert r.loc["RB2612", "fee_open"] == pytest.approx(0.2)  # 合约月份分档:0.00002 → 0.2 bp
    assert math.isnan(r.loc["CU2611", "limit_pct"])  # 交易参数文件里没有的合约 → NaN
    validate("params", df)


def test_parse_shfe_ine_split_and_zero_margin_dropped() -> None:
    """同一份上期所文件按品种归属拆分;集运指数 EC 最后交易日保证金为 0 的行剔除。"""
    raw = _fx("Settlement20260918.dat")
    ine = xp.parse_shfe_params(
        raw, _fx("ContractDailyTradeArgument20260918.dat"), pd.Timestamp("2026-09-18"), xp.INE
    )
    assert sorted(ine["contract"]) == ["EC2610", "SC2610", "SC2612"]
    assert (ine["exchange"] == "INE").all()
    sc = ine.set_index("contract").loc["SC2610"]
    assert (sc["margin_spec"], sc["fee_open"], sc["fee_open_unit"], sc["limit_pct"]) == (
        0.18,
        20.0,
        "CNY_per_lot",
        0.16,
    )
    validate("params", ine)
    ec = xp.parse_shfe_params(_fx("Settlement20260831_ine.dat"), None, pd.Timestamp("2026-08-31"), xp.INE)
    assert sorted(ec["contract"]) == ["EC2610", "SC2610"]  # ec2608(保证金 0)被剔除
    assert ec["limit_pct"].isna().all()  # 没有交易参数文件


def test_parse_shfe_old_format_2016() -> None:
    """2016 格式:数值为 '.15000000' 样式的字符串;铜平今免收(折扣率 0);黄金按手数收费。"""
    df = xp.parse_shfe_params(
        _fx("Settlement20160104.dat"),
        _fx("ContractDailyTradeArgument20160104.dat"),
        pd.Timestamp("2016-01-04"),
    )
    r = df.set_index("contract")
    assert sorted(r.index) == ["AG1606", "AU1606", "CU1601", "CU1602"]
    assert (r.loc["CU1601", "margin_spec"], r.loc["CU1602", "margin_spec"]) == (0.15, 0.10)  # 交割月加档
    assert (
        r.loc["CU1602", "fee_open"],
        r.loc["CU1602", "fee_open_unit"],
        r.loc["CU1602", "fee_close_today"],
    ) == (
        0.5,
        "bp",
        0.0,
    )
    assert (r.loc["AU1606", "fee_open"], r.loc["AU1606", "fee_open_unit"]) == (10.0, "CNY_per_lot")
    assert (r["limit_pct"] > 0).all()
    validate("params", df)


def test_parse_params_dispatch_and_dce_not_implemented() -> None:
    raws = {"main": _fx("Settlement20260918.dat"), "aux": None}
    df = xp.parse_params(raws, pd.Timestamp("2026-09-18"), "SHFE")
    assert df["limit_pct"].isna().all() and len(df) == 7
    with pytest.raises(NotImplementedError):
        xp.fetch_params(pd.Timestamp("2026-09-18"), "DCE", Store(Path("/nonexistent")))
    with pytest.raises(ValueError):
        xp.parse_params({"main": None, "aux": None}, pd.Timestamp("2026-09-18"), "SHFE")


# ---------------------------------------------------------------------------------------------
# 解析:郑商所
# ---------------------------------------------------------------------------------------------


def test_parse_czce_new_format_with_trade_param() -> None:
    """2022-11 起格式:手续费收取方式(比例值 → bp / 绝对值 → 元/手);涨跌停取交易参数文件;套保保证金无 → NaN。"""
    df = xp.parse_czce_params(
        _fx("FutureDataClearParams_20260918.txt"),
        _fx("FutureTradeParam_20260918.txt"),
        pd.Timestamp("2026-09-18"),
    )
    assert list(df.columns) == PARAM_COLS
    assert sorted(df["contract"]) == [
        "AP2610",
        "AP2611",
        "CF2611",
        "CF2701",
        "MA2610",
        "MA2701",
        "SA2610",
        "SR2611",
    ]
    r = df.set_index("contract")
    assert r.loc["AP2610", "margin_spec"] == 0.10 and r.loc["AP2611", "margin_spec"] == 0.09
    assert (
        r.loc["AP2610", "fee_open"],
        r.loc["AP2610", "fee_open_unit"],
        r.loc["AP2610", "fee_close_today"],
    ) == (
        5.0,
        "CNY_per_lot",
        10.0,
    )
    assert (
        r.loc["MA2610", "fee_open"],
        r.loc["MA2610", "fee_open_unit"],
        r.loc["MA2610", "fee_close_today"],
    ) == (
        1.0,
        "bp",
        1.0,
    )
    assert r.loc["CF2611", "limit_pct"] == 0.06 and r.loc["SA2610", "limit_pct"] == 0.07
    assert math.isnan(r.loc["MA2701", "limit_pct"])  # 交易参数样例里没有 MA701
    assert r["margin_hedge"].isna().all()
    validate("params", df)


def test_parse_czce_2016_gbk_no_close_today_no_limit() -> None:
    """2016 文件为 GBK;只有 Y/N 的"平今手续费减半"→ fee_close_today NaN;无涨跌停列 → NaN;3 位合约代码按文件日期补十年。"""
    df = xp.parse_czce_params(_fx("FutureDataClearParams_20160104.txt"), None, pd.Timestamp("2016-01-04"))
    r = df.set_index("contract")
    assert sorted(r.index) == ["CF1601", "CF1603", "MA1601", "SR1601", "SR1605", "TA1605"]
    assert (r.loc["CF1601", "margin_spec"], r.loc["CF1603", "margin_spec"]) == (0.20, 0.05)
    assert (r.loc["CF1603", "fee_open"], r.loc["CF1603", "fee_open_unit"]) == (4.3, "CNY_per_lot")
    assert r["fee_close_today"].isna().all() and r["fee_close_today_unit"].isna().all()
    assert r["limit_pct"].isna().all()
    validate("params", df)


def test_parse_czce_limit_falls_back_to_previous_clear_params() -> None:
    """2019-09-02 起结算参数表有"涨跌停板"列(次日盘中适用);无交易参数文件时用前一交易日的该列补 limit_pct。"""
    d0, d1 = _fx("FutureDataClearParams_20190902.txt"), _fx("FutureDataClearParams_20190903.txt")
    first = xp.parse_czce_params(d0, None, pd.Timestamp("2019-09-02"))
    assert first["limit_pct"].isna().all()  # 没有前一日文件
    second = xp.parse_czce_params(d1, None, pd.Timestamp("2019-09-03"), prev_clear=d0)
    r = second.set_index("contract")
    assert r.loc["CF2001", "limit_pct"] == 0.04 and r.loc["MA2001", "limit_pct"] == 0.05
    assert math.isnan(r.loc["MA2003", "limit_pct"])  # 前一日不存在的合约
    assert (r.loc["MA2001", "fee_close_today"], r.loc["MA2001", "fee_close_today_unit"]) == (
        6.0,
        "CNY_per_lot",
    )
    validate("params", second)


# ---------------------------------------------------------------------------------------------
# 校验与落盘
# ---------------------------------------------------------------------------------------------


def _params(date: str, **over: object) -> pd.DataFrame:
    base = {
        "date": [date, date],
        "exchange": ["SHFE", "SHFE"],
        "symbol": ["CU", "CU"],
        "contract": ["CU2610", "CU2611"],
        "margin_spec": [0.11, 0.11],
        "margin_hedge": [0.10, np.nan],
        "fee_open": [0.5, 0.5],
        "fee_open_unit": ["bp", "bp"],
        "fee_close_today": [1.0, np.nan],
        "fee_close_today_unit": ["bp", None],
        "limit_pct": [0.09, np.nan],
    }
    base.update(over)
    return pd.DataFrame(base)


def test_validate_params_rules() -> None:
    out = validate("params", _params("2026-09-18"))
    assert out["fee_close_today_unit"].iloc[1] is None and math.isnan(out["limit_pct"].iloc[1])
    with pytest.raises(ValueError, match="margin_spec"):
        validate("params", _params("2026-09-18", margin_spec=[0.11, 0.0]))
    with pytest.raises(ValueError, match="margin_spec"):
        validate("params", _params("2026-09-18", margin_spec=[0.11, 1.5]))
    with pytest.raises(ValueError, match="limit_pct"):
        validate("params", _params("2026-09-18", limit_pct=[9.0, np.nan]))
    with pytest.raises(ValueError, match="units"):
        validate("params", _params("2026-09-18", fee_open_unit=["bp", "pct"]))
    with pytest.raises(ValueError, match="duplicated"):
        validate("params", _params("2026-09-18", contract=["CU2610", "CU2610"]))
    with pytest.raises(ValueError, match="bad contract"):
        validate("params", _params("2026-09-18", contract=["CU2610", "cu-2611"]))
    two_dates = _params("2026-09-18")
    two_dates["date"] = ["2026-09-18", "2026-09-17"]
    with pytest.raises(ValueError, match="one date"):
        validate("params", two_dates)


def test_store_roundtrip_and_ingest_from_local_raw(tmp_path: Path) -> None:
    """raw 已落盘时 ingest_day 不联网;parquet 往返保留 NaN/None;第二次调用返回 exists。"""
    st = Store(tmp_path)
    d = pd.Timestamp("2026-09-18")
    xp.write_raws(
        "SHFE",
        d,
        {"main": _fx("Settlement20260918.dat"), "aux": _fx("ContractDailyTradeArgument20260918.dat")},
        st,
    )
    xp.write_raws(
        "CZCE",
        d,
        {"main": _fx("FutureDataClearParams_20260918.txt"), "aux": _fx("FutureTradeParam_20260918.txt")},
        st,
    )
    status = xp.ingest_day(d, ("SHFE", "CZCE"), st)
    assert status == {"SHFE": "written", "CZCE": "written"}
    assert xp.ingest_day(d, ("SHFE", "CZCE"), st) == {"SHFE": "exists", "CZCE": "exists"}
    back = st.read_days("SHFE", "params")
    assert list(back.columns) == PARAM_COLS and len(back) == 7
    r = back.set_index("contract")
    assert math.isnan(r.loc["CU2611", "limit_pct"]) and r.loc["CU2610", "fee_open_unit"] == "bp"
    cz = st.read_days("CZCE", "params").set_index("contract")
    assert cz["margin_hedge"].isna().all() and cz.loc["MA2610", "fee_open_unit"] == "bp"
    assert xp.coverage(st, ("SHFE", "CZCE")).loc[2026].to_dict() == {"SHFE": 1, "CZCE": 1}


def test_local_raws_layout(tmp_path: Path) -> None:
    (tmp_path / "S20260918.json").write_bytes(b"{}")
    (tmp_path / "S20260919.json.404").write_text("")
    (tmp_path / "20260918.txt").write_bytes(b"x")
    assert xp.local_raws(tmp_path, "SHFE", pd.Timestamp("2026-09-18")) == (
        "found",
        {"main": b"{}", "aux": None},
    )
    assert xp.local_raws(tmp_path, "SHFE", pd.Timestamp("2026-09-19")) == ("missing", None)
    assert xp.local_raws(tmp_path, "SHFE", pd.Timestamp("2026-09-21")) == ("none", None)
    assert xp.local_raws(tmp_path, "CZCE", pd.Timestamp("2026-09-18"))[0] == "found"


def test_paper_ingest_all_includes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """纸面 ingest_all 默认拉 params:三所直连结果并入各所状态,大商所记 skipped_needs_browser;行情等仍按原 kinds 拉。"""
    from cta.data.exchanges import czce, dce, ine, shfe
    from cta.paper import runner

    calls: dict[str, object] = {}

    def _fake(tag: str, result: str) -> Callable[[pd.Timestamp, Iterable[str]], dict[str, str]]:
        def fn(d: pd.Timestamp, kinds: Iterable[str]) -> dict[str, str]:
            ks = tuple(kinds)
            calls.setdefault(tag, ks)
            return dict.fromkeys(ks, result)

        return fn

    monkeypatch.setattr(runner, "settlement_published", lambda d: True)
    monkeypatch.setattr(shfe, "ingest_day", _fake("shfe", "written"))
    monkeypatch.setattr(ine, "ingest_day", _fake("ine", "exists"))
    monkeypatch.setattr(czce, "ingest_day", _fake("czce", "ok"))

    class _NoBrowser:
        def __enter__(self) -> None:
            raise RuntimeError("no CDP proxy")

        def __exit__(self, *a: object) -> None:
            return None

    monkeypatch.setattr(dce, "CdpSession", _NoBrowser)
    monkeypatch.setattr(
        xp,
        "ingest_day",
        lambda d, exchanges: (
            calls.setdefault("params", tuple(exchanges))
            and {"SHFE": "written", "INE": "missing", "CZCE": "exists"}
        ),
    )
    status = runner.ingest_all(pd.Timestamp("2026-09-18"))
    assert calls["shfe"] == ("quotes", "positions", "receipts")  # params 不传给各所自己的 ingest_day
    assert calls["params"] == xp.EXCHANGES
    assert status["SHFE"] == "quotes:written,positions:written,receipts:written,params:written"
    assert status["INE"] == "quotes:exists,positions:exists,receipts:exists,params:missing"
    assert status["CZCE"] == "quotes:ok,positions:ok,receipts:ok,params:exists"
    assert status["DCE"].startswith("error:") and status["DCE"].endswith("params:skipped_needs_browser")
    only = runner.ingest_all(pd.Timestamp("2026-09-18"), kinds=("params",))
    assert only == {
        "SHFE": "params:written",
        "INE": "params:missing",
        "CZCE": "params:exists",
        "DCE": "params:skipped_needs_browser",
    }


# ---------------------------------------------------------------------------------------------
# 事件推导(合成数据)
# ---------------------------------------------------------------------------------------------


def _synthetic(
    dates: list[str], margins: dict[str, list[float]], fee: float = 3.0, unit: str = "CNY_per_lot"
) -> pd.DataFrame:
    """每个日期给若干合约的保证金列表(第一个视为交割月加档);手续费全程相同。"""
    rows = []
    for d in dates:
        for i, m in enumerate(margins[d]):
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "exchange": "SHFE",
                    "symbol": "CU",
                    "contract": f"CU26{i + 1:02d}",
                    "margin_spec": m,
                    "margin_hedge": m - 0.01,
                    "fee_open": fee,
                    "fee_open_unit": unit,
                    "fee_close_today": 0.0,
                    "fee_close_today_unit": unit,
                    "limit_pct": 0.06,
                }
            )
    return pd.DataFrame(rows, columns=PARAM_COLS)


def test_daily_levels_mode_ignores_delivery_month_tier() -> None:
    df = _synthetic(["2026-03-02"], {"2026-03-02": [0.15, 0.08, 0.08, 0.08, 0.10]})
    lv = xp.daily_levels(df)
    assert lv.loc[0, ["margin", "fee", "fee_unit", "n_contracts"]].tolist() == [0.08, 3.0, "CNY_per_lot", 5]
    tie = xp.daily_levels(_synthetic(["2026-03-02"], {"2026-03-02": [0.10, 0.08]}))
    assert tie.loc[0, "margin"] == 0.08  # 平票取小


def test_derive_events_up_only_holiday_and_restore() -> None:
    """连续 8 个交易日,中间隔一个周三休市日:休市前 1 日上调、节后恢复 → holiday;之后无关联上调 → derived;下调不输出。"""
    dates = [
        "2026-03-02",
        "2026-03-03",
        "2026-03-05",
        "2026-03-06",
        "2026-03-09",
        "2026-03-10",
        "2026-03-11",
        "2026-03-12",
    ]
    m = [0.08] * 4
    margins = {
        "2026-03-02": m,
        "2026-03-03": [0.11] * 4,  # 上调(休市日 03-04 前 1 个交易日)
        "2026-03-05": [0.11] * 4,
        "2026-03-06": m,  # 恢复原值
        "2026-03-09": m,
        "2026-03-10": [0.09] * 4,  # 与假期无关的上调
        "2026-03-11": [0.09] * 4,
        "2026-03-12": [0.07] * 4,  # 下调:up_only 不输出
    }
    df = _synthetic(dates, margins)
    ev = xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([]))
    assert list(ev.columns) == xp.EVENT_COLS
    assert len(ev) == 2
    a, b = ev.iloc[0], ev.iloc[1]
    assert (a["effective_date"], a["param"], a["direction"], a["old_value"], a["new_value"], a["reason"]) == (
        pd.Timestamp("2026-03-03"),
        "margin",
        "up",
        0.08,
        0.11,
        "holiday",
    )
    assert (b["effective_date"], b["new_value"], b["reason"]) == (pd.Timestamp("2026-03-10"), 0.09, "derived")
    assert (
        (ev["unit"] == "ratio").all()
        and (ev["notes"] == "DERIVED-daily").all()
        and (ev["contract_scope"] == "all").all()
    )
    assert ev["announce_date"].isna().all() and (ev["notice_id"] == "").all()
    assert ev["url"].iloc[0].endswith("Settlement20260303.dat")
    # 下调也输出
    both = xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([]), up_only=False)
    assert both["direction"].tolist() == ["up", "down", "up", "down"]
    # 只看"休市日前 ≤3 个交易日"时,节后无需恢复也标 holiday;而 03-10 的上调仍是 derived
    quick = xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([]), require_restore=False)
    assert quick["reason"].tolist() == ["holiday", "derived"]


def test_derive_events_pre_holiday_without_restore_is_derived_and_future_holiday_uses_calendar() -> None:
    """休市前上调但 10 个交易日内不恢复 → derived;最后一个观察日之后的假期用 holidays.csv 判定。"""
    dates = [str(d.date()) for d in pd.bdate_range("2026-03-02", "2026-03-20")]
    margins = {d: [0.08] * 3 for d in dates}
    for d in dates[3:]:
        margins[d] = [0.11] * 3  # 03-05 上调后一直不恢复
    df = _synthetic(dates, margins)
    # 03-06 不是交易日(缺文件)→ 03-05 在休市日前 1 个交易日,但不恢复 → derived
    df = df[df["date"] != pd.Timestamp("2026-03-06")]
    ev = xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([]))
    assert ev["reason"].tolist() == ["derived"]
    # 最后一日 03-20 上调,03-23 为公告假期(未来)→ 无法确认恢复:require_restore=False 才标 holiday
    df2 = _synthetic(dates, {d: [0.08] * 3 for d in dates[:-1]} | {dates[-1]: [0.12] * 3})
    hol = pd.DatetimeIndex([pd.Timestamp("2026-03-23")])
    assert xp.derive_events(None, "SHFE", df=df2, holidays=hol)["reason"].tolist() == ["derived"]
    assert xp.derive_events(None, "SHFE", df=df2, holidays=hol, require_restore=False)["reason"].tolist() == [
        "holiday"
    ]
    assert xp.derive_events(None, "SHFE", df=df2, holidays=pd.DatetimeIndex([]), require_restore=False)[
        "reason"
    ].tolist() == ["derived"]


def test_derive_events_composition_and_single_contract_guards_and_fee() -> None:
    """众数因分档合约上市/到期而翻转(无合约真的变)不算事件;≥4 个共同合约只有 1 个变不算;手续费上调算 fee 事件。"""
    d0, d1 = "2026-04-01", "2026-04-02"
    # 第 1 天 3 个合约 0.08 + 2 个 0.10;第 2 天 0.08 的一个到期、0.10 的一个上市 → 众数翻到 0.10,但无合约变
    rows0 = _synthetic([d0], {d0: [0.08, 0.08, 0.08, 0.10, 0.10]})
    rows1 = _synthetic([d1], {d1: [0.08, 0.08, 0.10, 0.10, 0.10]})
    rows1["contract"] = ["CU2602", "CU2603", "CU2604", "CU2605", "CU2606"]
    df = pd.concat([rows0, rows1], ignore_index=True)
    assert xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([])).empty
    # 单合约阶梯:5 个合约里只有 1 个从 0.08 → 0.10(打破平票)
    rows0 = _synthetic([d0], {d0: [0.08, 0.08, 0.10, 0.10, 0.09]})
    rows1 = _synthetic([d1], {d1: [0.08, 0.10, 0.10, 0.10, 0.09]})
    df = pd.concat([rows0, rows1], ignore_index=True)
    assert xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([])).empty
    # 手续费:3 元/手 → 6 元/手(全部合约)
    rows0 = _synthetic([d0], {d0: [0.08] * 4}, fee=3.0)
    rows1 = _synthetic([d1], {d1: [0.08] * 4}, fee=6.0)
    ev = xp.derive_events(
        None, "SHFE", df=pd.concat([rows0, rows1], ignore_index=True), holidays=pd.DatetimeIndex([])
    )
    assert len(ev) == 1 and ev.loc[0, ["param", "old_value", "new_value", "unit"]].tolist() == [
        "fee",
        3.0,
        6.0,
        "CNY_per_lot",
    ]
    # 单位变化(元/手 → bp)不可比,不出事件
    rows1 = _synthetic([d1], {d1: [0.08] * 4}, fee=1.0, unit="bp")
    assert xp.derive_events(
        None, "SHFE", df=pd.concat([rows0, rows1], ignore_index=True), holidays=pd.DatetimeIndex([])
    ).empty


def test_derive_events_gap_guard_and_symbol_filter() -> None:
    d0, d1 = "2026-04-01", "2026-04-20"  # 相距 19 天 > MAX_GAP_DAYS
    df = pd.concat(
        [_synthetic([d0], {d0: [0.08] * 3}), _synthetic([d1], {d1: [0.12] * 3})], ignore_index=True
    )
    assert xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([])).empty
    d1 = "2026-04-08"
    df = pd.concat(
        [_synthetic([d0], {d0: [0.08] * 3}), _synthetic([d1], {d1: [0.12] * 3})], ignore_index=True
    )
    assert len(xp.derive_events(None, "SHFE", df=df, holidays=pd.DatetimeIndex([]))) == 1
    assert xp.derive_events(None, "SHFE", ["AL"], df=df, holidays=pd.DatetimeIndex([])).empty


# ---------------------------------------------------------------------------------------------
# 有本地数据才跑:与已核验的 2026 现行值一致
# ---------------------------------------------------------------------------------------------

# 已核验的 2026 现行值(两名复核员在交易所官网核过;"一般月份/主力档"):
# docs/instruments_verification.md 的快照为 2026-09-11 结算参数 / 2026-09-14 交易参数,
# docs/instruments_verification_ext_shfe_czce.md 的快照为 2026-09-18(两者)。
V1, V2 = ("2026-09-11", "2026-09-14"), ("2026-09-18", "2026-09-18")
VERIFIED_2026 = [
    # exchange, symbol, contract, (结算参数日, 交易参数日), margin_spec, fee_open, fee_unit, fee_close_today, limit_pct
    ("SHFE", "CU", "CU2611", V1, 0.11, 0.5, "bp", 1.0, 0.09),
    ("SHFE", "AL", "AL2611", V1, 0.11, 3.0, "CNY_per_lot", 3.0, 0.09),
    ("SHFE", "NI", "NI2611", V1, 0.12, 3.0, "CNY_per_lot", 3.0, 0.10),
    ("SHFE", "SN", "SN2611", V1, 0.14, 3.0, "CNY_per_lot", 3.0, 0.12),
    ("SHFE", "AU", "AU2612", V1, 0.16, 20.0, "CNY_per_lot", 0.0, 0.14),
    ("SHFE", "AG", "AG2612", V1, 0.22, 0.5, "bp", 0.5, 0.20),
    ("SHFE", "RB", "RB2701", V1, 0.07, 1.0, "bp", 1.0, 0.05),
    ("SHFE", "RU", "RU2701", V1, 0.09, 3.0, "CNY_per_lot", 0.0, 0.07),
    ("SHFE", "ZN", "ZN2611", V2, 0.11, 3.0, "CNY_per_lot", 0.0, 0.09),
    ("SHFE", "HC", "HC2701", V2, 0.07, 1.0, "bp", 1.0, 0.05),
    ("SHFE", "BU", "BU2612", V2, 0.12, 0.5, "bp", 0.0, 0.10),
    ("SHFE", "SP", "SP2701", V2, 0.07, 0.2, "bp", 0.0, 0.05),
    ("INE", "SC", "SC2612", V1, 0.16, 20.0, "CNY_per_lot", 0.0, 0.14),
    ("CZCE", "CF", "CF2701", V1, 0.07, 4.3, "CNY_per_lot", 0.0, 0.06),
    ("CZCE", "SR", "SR2701", V1, 0.06, 2.0, "CNY_per_lot", 0.0, 0.05),
    ("CZCE", "TA", "TA2701", V1, 0.07, 3.0, "CNY_per_lot", 0.0, 0.06),
    ("CZCE", "MA", "MA2701", V1, 0.07, 1.0, "bp", 1.0, 0.06),
    ("CZCE", "SA", "SA2701", V1, 0.08, 1.0, "bp", 1.0, 0.07),
    ("CZCE", "AP", "AP2701", V2, 0.09, 5.0, "CNY_per_lot", 10.0, 0.08),
    ("CZCE", "FG", "FG2701", V2, 0.09, 2.0, "CNY_per_lot", 2.0, 0.08),
    ("CZCE", "PK", "PK2701", V2, 0.07, 2.0, "CNY_per_lot", 2.0, 0.06),
    ("CZCE", "UR", "UR2701", V2, 0.08, 1.0, "bp", 1.0, 0.07),
]


@pytest.mark.skipif(not (EXCH / "SHFE" / "params" / "2026").exists(), reason="需要本地 params 数据")
def test_params_match_verified_2026_values() -> None:
    st = Store()
    mismatches: list[str] = []
    for exch, sym, contract, (settle, trade), margin, fee, unit, close_today, limit in VERIFIED_2026:
        ps = st.read_days(exch, "params", pd.Timestamp(settle), pd.Timestamp(settle)).set_index("contract")
        pt = st.read_days(exch, "params", pd.Timestamp(trade), pd.Timestamp(trade)).set_index("contract")
        if contract not in ps.index or contract not in pt.index:
            mismatches.append(f"{exch} {contract}: not in store")
            continue
        got = (
            float(ps.loc[contract, "margin_spec"]),
            float(ps.loc[contract, "fee_open"]),
            str(ps.loc[contract, "fee_open_unit"]),
            float(ps.loc[contract, "fee_close_today"]),
            float(pt.loc[contract, "limit_pct"]),
        )
        want = (margin, fee, unit, close_today, limit)
        if not all(
            (a == b) if isinstance(a, str) else math.isclose(float(a), float(b), abs_tol=1e-9)
            for a, b in zip(got, want)
        ):
            mismatches.append(f"{exch} {sym} {contract}: got {got} want {want}")
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.skipif(not (EXCH / "SHFE" / "params" / "2026").exists(), reason="需要本地 params 数据")
def test_params_store_consistency() -> None:
    """每个落盘文件一天、合约不重复、保证金合法;当年落盘天数与行情天数一致(参数文件与行情同日发布)。"""
    st = Store()
    for exch in ("SHFE", "INE", "CZCE"):
        days = [d for d in st.days(exch, "params") if d.year == 2026]
        qdays = [d for d in st.days(exch, "quotes") if d.year == 2026 and d <= max(days)]
        assert set(qdays) <= set(days), (
            f"{exch}: quotes days without params {sorted(set(qdays) - set(days))[:5]}"
        )
        df = st.read_days(exch, "params", days[-1], days[-1])
        validate("params", df)
        assert df["symbol"].nunique() >= 5


def test_constants_documented() -> None:
    """模块常量与文档保持一致(文档改了要同步)。"""
    doc = (ROOT / "docs" / "data_exchange_params.md").read_text(encoding="utf-8")
    for c in (xp.CZCE_CLOSE_TODAY_FROM, xp.CZCE_LIMIT_FROM, xp.CZCE_FEE_STYLE_FROM, xp.CZCE_TRADE_PARAM_FROM):
        assert str(c.date()) in doc
    assert json.dumps(xp.EVENT_COLS) and "DERIVED-daily" in doc
