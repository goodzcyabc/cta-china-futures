"""上期所/能源中心期权日行情(cta.data.alt.shfe_options):嵌入真实文件节选测解析、双边折半、代码规范化、可得日、
幂等下载;有本地数据时检查整表(唯一性、可得日、看跌 delta 符号、IV 范围、预注册品种覆盖)。"""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from cta.data.alt import shfe_options as so
from cta.data.exchanges.base import normalize_contract

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "external" / "alt" / "shfe_options"
TABLE = DEST / "options_daily.parquet"

# ---------------------------------------------------------------------------------------------
# 嵌入样例(逐字节摘自交易所文件;只删掉了其余行)
# ---------------------------------------------------------------------------------------------

# kx20190614.dat:2024-03 前格式(字符串右侧补空格、print_date、PRODUCTSORTNO),2020 年前双边计数。
KX_20190614 = """{"o_curinstrument": [
{"PRODUCTID": "cu_o    ", "PRODUCTSORTNO": 10, "PRODUCTNAME": "铜期权              ", "INSTRUMENTID": "cu1907C47000                  ", "PRESETTLEMENTPRICE": 225, "OPENPRICE": 170, "HIGHESTPRICE": 224, "LOWESTPRICE": 136, "CLOSEPRICE": 136, "SETTLEMENTPRICE": 210, "ZD1_CHG": -89, "ZD2_CHG": -15, "VOLUME": 1760, "OPENINTEREST": 1646, "OPENINTERESTCHG": -196, "ORDERNO": 0, "EXECVOLUME": "", "TURNOVER": 159.716, "DELTA": 0.30392, "UNDERLYINGINSTRID": "cu1907                        ", "STRIKEPRICE": 47000, "OPTIONSTYPE": "1", "PRODUCTGROUPID": "cu      "},
{"PRODUCTID": "cu_o    ", "PRODUCTSORTNO": 10, "PRODUCTNAME": "铜期权              ", "INSTRUMENTID": "cu1907P47000                  ", "PRESETTLEMENTPRICE": 895, "OPENPRICE": 810, "HIGHESTPRICE": 877, "LOWESTPRICE": 650, "CLOSEPRICE": 844, "SETTLEMENTPRICE": 790, "ZD1_CHG": -51, "ZD2_CHG": -105, "VOLUME": 1102, "OPENINTEREST": 1024, "OPENINTERESTCHG": -28, "ORDERNO": 0, "EXECVOLUME": "", "TURNOVER": 410.658, "DELTA": -0.695628, "UNDERLYINGINSTRID": "cu1907                        ", "STRIKEPRICE": 47000, "OPTIONSTYPE": "2", "PRODUCTGROUPID": "cu      "},
{"PRODUCTID": "cu_o    ", "PRODUCTSORTNO": 10, "PRODUCTNAME": "铜期权              ", "INSTRUMENTID": "小计", "PRESETTLEMENTPRICE": "", "OPENPRICE": "", "HIGHESTPRICE": "", "LOWESTPRICE": "", "CLOSEPRICE": "", "SETTLEMENTPRICE": "", "ZD1_CHG": "", "ZD2_CHG": "", "VOLUME": 23284, "OPENINTEREST": 74472, "OPENINTERESTCHG": -270, "ORDERNO": 0, "EXECVOLUME": "", "TURNOVER": 6387.915, "DELTA": "", "UNDERLYINGINSTRID": "小计", "STRIKEPRICE": 99999999, "OPTIONSTYPE": "", "PRODUCTGROUPID": "cu      "},
{"PRODUCTID": "总计", "PRODUCTSORTNO": 9999, "PRODUCTNAME": "总计", "INSTRUMENTID": "", "PRESETTLEMENTPRICE": "", "OPENPRICE": "", "HIGHESTPRICE": "", "LOWESTPRICE": "", "CLOSEPRICE": "", "SETTLEMENTPRICE": "", "ZD1_CHG": "", "ZD2_CHG": "", "VOLUME": 28914, "OPENINTEREST": 110156, "OPENINTERESTCHG": 568, "ORDERNO": 0, "EXECVOLUME": 0, "TURNOVER": 8544.395, "DELTA": "", "UNDERLYINGINSTRID": "总计", "STRIKEPRICE": 99999999, "OPTIONSTYPE": "", "PRODUCTGROUPID": "总计"}
],
"o_cursigma": [
{"PRODUCTID": "cu_o    ", "PRODUCTSORTNO": 10, "PRODUCTNAME": "铜期权              ", "INSTRUMENTID": "cu1907                        ", "VOLUME": 12938, "OPENINTEREST": 27380, "OPENINTERESTCHG": -774, "EXECVOLUME": "", "TURNOVER": 3813.485, "SIGMA": 0.136347, "PRODUCTGROUPID": "cu      "}
],
"o_curproduct": [],
"o_year": "2019", "o_month": "06", "o_day": "14", "o_weekday": "五", "o_year_num": "108", "o_total_num": "173", "o_trade_day": "173", "showlength": "2", "o_code": 0, "o_msg": "期权交易快讯查询成功", "report_date": "20190614", "update_date": "20200617 19:32:03", "print_date": "20200617 20:02:17"}"""

# kx20260930.dat:新格式(无补空格,o_code '0000',无 print_date),含能源中心原油期权。
KX_20260930 = """{"showlength": "1", "o_day": "30", "o_weekday": "三",
"o_curinstrument": [
{"INSTRUMENTID": "sc2611P425", "OPENINTEREST": 8, "HIGHESTPRICE": 0.2, "TURNOVER": 0.05, "PRODUCTGROUPID": "sc", "CLOSEPRICE": 0.2, "DELTA": -0.000694, "VOLUME": 3, "OPENINTERESTCHG": -2, "STRIKEPRICE": 425, "OPTIONSTYPE": "2", "EXECVOLUME": 0, "PRODUCTID": "sc_o", "PRODUCTNAME": "原油期权", "ZD2_CHG": 0, "OPENPRICE": 0.15, "ZD1_CHG": 0.15, "SETTLEMENTPRICE": 0.05, "PRESETTLEMENTPRICE": 0.05, "LOWESTPRICE": 0.15, "UNDERLYINGINSTRID": "sc2611"},
{"INSTRUMENTID": "sc2611P580", "OPENINTEREST": 398, "HIGHESTPRICE": 8.65, "TURNOVER": 519.375, "PRODUCTGROUPID": "sc", "CLOSEPRICE": 4.6, "DELTA": -0.10962, "VOLUME": 819, "OPENINTERESTCHG": 64, "STRIKEPRICE": 580, "OPTIONSTYPE": "2", "EXECVOLUME": 0, "PRODUCTID": "sc_o", "PRODUCTNAME": "原油期权", "ZD2_CHG": 1.1, "OPENPRICE": 8.05, "ZD1_CHG": -0.55, "SETTLEMENTPRICE": 6.25, "PRESETTLEMENTPRICE": 5.15, "LOWESTPRICE": 4.5, "UNDERLYINGINSTRID": "sc2611"},
{"INSTRUMENTID": "小计", "OPENINTEREST": 77056, "HIGHESTPRICE": "", "TURNOVER": 251108.775, "PRODUCTGROUPID": "sc", "CLOSEPRICE": "", "DELTA": "", "VOLUME": 187577, "OPENINTERESTCHG": 2105, "STRIKEPRICE": 99999999, "OPTIONSTYPE": "", "EXECVOLUME": 1, "PRODUCTID": "sc_o", "PRODUCTNAME": "原油期权", "ZD2_CHG": "", "OPENPRICE": "", "ZD1_CHG": "", "SETTLEMENTPRICE": "", "PRESETTLEMENTPRICE": "", "LOWESTPRICE": "", "UNDERLYINGINSTRID": "小计"},
{"INSTRUMENTID": "cu2611P128000", "OPENINTEREST": 8, "HIGHESTPRICE": "", "TURNOVER": 0, "PRODUCTGROUPID": "cu", "CLOSEPRICE": 18430, "DELTA": -0.99855, "VOLUME": 0, "OPENINTERESTCHG": 0, "STRIKEPRICE": 128000, "OPTIONSTYPE": "2", "EXECVOLUME": 0, "PRODUCTID": "cu_o", "PRODUCTNAME": "铜期权", "ZD2_CHG": -270, "OPENPRICE": "", "ZD1_CHG": -270, "SETTLEMENTPRICE": 18430, "PRESETTLEMENTPRICE": 18700, "LOWESTPRICE": "", "UNDERLYINGINSTRID": "cu2611"}
],
"o_cursigma": [
{"INSTRUMENTID": "sc2611", "OPENINTEREST": 58879, "TURNOVER": 235255.495, "PRODUCTGROUPID": "sc", "SIGMA": 0.784848, "VOLUME": 179555, "OPENINTERESTCHG": 774, "EXECVOLUME": 1, "PRODUCTID": "sc_o", "PRODUCTNAME": "原油期权"},
{"INSTRUMENTID": "小计", "OPENINTEREST": 77056, "TURNOVER": 251108.775, "PRODUCTGROUPID": "sc", "SIGMA": "", "VOLUME": 187577, "OPENINTERESTCHG": 2105, "EXECVOLUME": 1, "PRODUCTID": "sc_o", "PRODUCTNAME": "原油期权"},
{"INSTRUMENTID": "cu2611", "OPENINTEREST": 81820, "TURNOVER": 26017.916, "PRODUCTGROUPID": "cu", "SIGMA": 0.204635, "VOLUME": 79622, "OPENINTERESTCHG": 3204, "EXECVOLUME": 0, "PRODUCTID": "cu_o", "PRODUCTNAME": "铜期权"}
],
"o_year_num": "181", "o_code": "0000", "update_date": "20260930 15:34:43", "o_year": "2026", "o_month": "09", "o_msg": "查询成功", "o_curproduct": [], "o_total_num": "1945", "o_trade_day": "1945", "report_date": "20260930"}"""

BASEINFO_20260930 = """{"OptionContractBaseInfo": [
{"INSTRUMENTID": "sc2611P425", "OPENDATE": "20260729", "PRICETICK": "0.05", "EXCHANGEID": "SHFE", "SETTLEMENTGROUPID": "00000001", "TRADINGDAY": "20260930", "COMMODITYNAME": "原油", "EXPIREDATE": "20261014", "COMMODITYID": "sc", "TRADEUNIT": "1000"},
{"INSTRUMENTID": "cu2611P128000", "OPENDATE": "20260911", "PRICETICK": "2", "EXCHANGEID": "SHFE", "SETTLEMENTGROUPID": "00000001", "TRADINGDAY": "20260930", "COMMODITYNAME": "铜", "EXPIREDATE": "20261026", "COMMODITYID": "cu", "TRADEUNIT": "5"}
], "update_date": "20260930 16:30:10", "report_date": "20260930"}"""

BASEINFO_20190614 = """{"OptionContractBaseInfo": [
{"COMMODITYID": "cu", "EXCHANGEID": "SHFE", "EXPIREDATE": "20190624", "INSTRUMENTID": "cu1907C47000", "OPENDATE": "20180921", "PRICETICK": "1.000", "SETTLEMENTGROUPID": "00000001", "TRADEUNIT": "5", "TRADINGDAY": "20190614", "UPDATE_DATE": "2019-06-14 20:00:04", "commodityName": "铜", "id": 30818609},
{"COMMODITYID": "cu", "EXCHANGEID": "SHFE", "EXPIREDATE": "20190624", "INSTRUMENTID": "cu1907P47000", "OPENDATE": "20180921", "PRICETICK": "1.000", "SETTLEMENTGROUPID": "00000001", "TRADEUNIT": "5", "TRADINGDAY": "20190614", "UPDATE_DATE": "2019-06-14 20:00:04", "commodityName": "铜", "id": 30818621}
], "report_date": "20190614", "update_date": "20190614 20:00:05", "print_date": "20190614 20:00:15"}"""


def _b(s: str) -> bytes:
    return s.encode("utf-8")


def _with_date(sample: str, old: str, new: str) -> bytes:
    return _b(sample.replace(f'"report_date": "{old}"', f'"report_date": "{new}"'))


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


def test_parse_kx_old_format_drops_totals_strips_and_halves() -> None:
    kx = so.parse_kx(_b(KX_20190614), date(2019, 6, 14))
    df = kx.rows.set_index("option_code")
    assert list(df.index) == ["cu1907C47000", "cu1907P47000"]  # 小计/总计 已丢弃,代码去空格
    assert kx.update_date == "20200617 19:32:03"
    assert kx.print_date == "20200617 20:02:17"
    c, p = df.loc["cu1907C47000"], df.loc["cu1907P47000"]
    assert (c["exchange"], c["product"], c["underlying"], c["cp"]) == ("SHFE", "CU", "CU1907", "C")
    assert p["cp"] == "P" and p["delta"] == pytest.approx(-0.695628)
    assert c["strike"] == 47000.0 and c["settle"] == 210.0 and c["close"] == 136.0
    # 2020 年前双边:单边 = 原值 / 2;成交额 万元 → 元
    assert c["volume_raw"] == 1760.0 and c["volume"] == 880.0
    assert c["oi_raw"] == 1646.0 and c["oi"] == 823.0
    assert c["turnover_raw"] == pytest.approx(1_597_160.0) and c["turnover"] == pytest.approx(798_580.0)
    assert c["iv_exchange"] == pytest.approx(0.136347)
    assert c["series_volume"] == 12938.0 / 2 and c["series_oi"] == 27380.0 / 2
    # 成交均价不受双边计数影响:TURNOVER*1e4/(VOLUME*合约乘数 5) 落在当日高低价内
    vwap = c["turnover"] / (c["volume"] * 5)
    assert 136 <= vwap <= 224


def test_parse_kx_new_format_ine_and_untraded() -> None:
    kx = so.parse_kx(_b(KX_20260930), date(2026, 9, 30))
    df = kx.rows.set_index("option_code")
    assert set(df.index) == {"sc2611P425", "sc2611P580", "cu2611P128000"}
    sc = df.loc["sc2611P580"]
    assert (sc["exchange"], sc["product"], sc["underlying"]) == ("INE", "SC", "SC2611")
    assert sc["volume"] == sc["volume_raw"] == 819.0  # 2020 起单边,不折半
    assert sc["turnover"] == pytest.approx(5_193_750.0)
    assert sc["iv_exchange"] == pytest.approx(0.784848)
    assert sc["series_volume"] == 179555.0 and sc["series_oi"] == 58879.0
    cu = df.loc["cu2611P128000"]
    assert cu["exchange"] == "SHFE" and cu["volume"] == 0.0
    assert cu["close"] == cu["settle"] == 18430.0  # 未成交:收盘价 = 结算价,照原样保留
    assert (df["delta"] <= 0).all()  # 看跌 delta 为负
    # o_cursigma 的系列总量与节选的期权行合计不同(节选只保留几行)→ 记 mismatch,不改值
    assert kx.series_mismatch == 2


def test_blank_volume_on_untraded_rows_is_zero() -> None:
    """2018–2019 文件对无成交期权留空 VOLUME/TURNOVER(kx20181016 cu1910P49000 原样);系列行同理(kx20190128 ru1910)。"""
    doc = json.loads(KX_20190614)
    row = {
        "PRODUCTID": "cu_o    ",
        "PRODUCTSORTNO": 10,
        "PRODUCTNAME": "铜期权              ",
        "INSTRUMENTID": "cu1907P49000                  ",
        "PRESETTLEMENTPRICE": 2421,
        "OPENPRICE": "",
        "HIGHESTPRICE": "",
        "LOWESTPRICE": "",
        "CLOSEPRICE": 2531,
        "SETTLEMENTPRICE": 2531,
        "ZD1_CHG": 110,
        "ZD2_CHG": 110,
        "VOLUME": "",
        "OPENINTEREST": 0,
        "OPENINTERESTCHG": 0,
        "ORDERNO": 0,
        "EXECVOLUME": "",
        "TURNOVER": "",
        "DELTA": -0.386122,
        "UNDERLYINGINSTRID": "cu1907                        ",
        "STRIKEPRICE": 49000,
        "OPTIONSTYPE": "2",
        "PRODUCTGROUPID": "cu      ",
    }
    doc["o_curinstrument"].insert(2, row)
    doc["o_cursigma"].append(
        {
            "PRODUCTID": "ru_o    ",
            "INSTRUMENTID": "ru1910                        ",
            "VOLUME": "",
            "OPENINTEREST": 0,
            "TURNOVER": "",
            "SIGMA": 0.240682,
        }
    )
    kx = so.parse_kx(json.dumps(doc, ensure_ascii=False).encode(), date(2019, 6, 14))
    r = kx.rows.set_index("option_code").loc["cu1907P49000"]
    assert r["volume"] == 0.0 and r["turnover"] == 0.0 and r["close"] == r["settle"] == 2531.0
    assert kx.blank_volume_as_zero == 1 and kx.blank_volume_traded == 0
    row2 = dict(row, INSTRUMENTID="cu1907P50000", STRIKEPRICE=50000, OPENPRICE=2500)
    doc["o_curinstrument"].insert(2, row2)
    kx = so.parse_kx(json.dumps(doc, ensure_ascii=False).encode(), date(2019, 6, 14))
    assert np.isnan(kx.rows.set_index("option_code").loc["cu1907P50000", "volume"])
    assert kx.blank_volume_traded == 1


def test_traded_rows_without_ohlc_are_counted_and_kept() -> None:
    """kx20260930 cu2612C96000 原样:VOLUME 1、开/高/低空、收盘 = 结算 = 成交均价(按结算价成交);照原样保留并计数。"""
    doc = json.loads(KX_20260930)
    doc["o_curinstrument"].append(
        {
            "INSTRUMENTID": "cu2612C96000",
            "VOLUME": 1,
            "TURNOVER": 6.663,
            "OPENINTEREST": 5,
            "OPENINTERESTCHG": -1,
            "EXECVOLUME": 0,
            "OPENPRICE": "",
            "HIGHESTPRICE": "",
            "LOWESTPRICE": "",
            "CLOSEPRICE": 13326,
            "SETTLEMENTPRICE": 13326,
            "PRESETTLEMENTPRICE": 13176,
            "DELTA": 0.954148,
            "STRIKEPRICE": 96000,
            "OPTIONSTYPE": "1",
            "PRODUCTID": "cu_o",
            "PRODUCTGROUPID": "cu",
            "UNDERLYINGINSTRID": "cu2612",
        }
    )
    kx = so.parse_kx(json.dumps(doc, ensure_ascii=False).encode(), date(2026, 9, 30))
    r = kx.rows.set_index("option_code").loc["cu2612C96000"]
    assert r["volume"] == 1.0 and r["close"] == r["settle"] == 13326.0
    assert r["turnover"] / (r["volume"] * 5) == pytest.approx(r["settle"])
    assert kx.traded_no_ohlc == 1  # cu2611P128000(VOLUME 0、无开高低)不计入


def test_halving_only_before_2020() -> None:
    before = so.parse_kx(_with_date(KX_20190614, "20190614", "20191231"), date(2019, 12, 31)).rows
    after = so.parse_kx(_with_date(KX_20190614, "20190614", "20200102"), date(2020, 1, 2)).rows
    for col in ("volume", "oi", "turnover", "series_volume", "series_oi"):
        np.testing.assert_allclose(before[col].to_numpy() * 2, after[col].to_numpy())
    np.testing.assert_allclose(before["volume_raw"], after["volume_raw"])
    np.testing.assert_allclose(after["volume"], after["volume_raw"])
    assert so.is_double_sided(date(2019, 12, 31)) and not so.is_double_sided(date(2020, 1, 1))


def test_sigma_blank_or_zero_is_nan() -> None:
    doc = json.loads(KX_20260930)
    doc["o_cursigma"][0]["SIGMA"] = ""
    doc["o_cursigma"][2]["SIGMA"] = 0
    kx = so.parse_kx(json.dumps(doc).encode(), date(2026, 9, 30))
    assert kx.rows["iv_exchange"].isna().all()
    assert kx.sigma_nonpositive == 1


def test_series_totals_fallback_when_sigma_row_missing() -> None:
    doc = json.loads(KX_20260930)
    doc["o_cursigma"] = [r for r in doc["o_cursigma"] if r["INSTRUMENTID"] != "sc2611"]
    kx = so.parse_kx(json.dumps(doc).encode(), date(2026, 9, 30))
    sc = kx.rows[kx.rows["product"] == "SC"]
    assert (sc["series_volume"] == 822.0).all() and (sc["series_oi"] == 406.0).all()
    assert sc["iv_exchange"].isna().all() and kx.series_missing == 1


def test_parse_kx_rejects_inconsistent_rows() -> None:
    doc = json.loads(KX_20260930)
    doc["o_curinstrument"][0]["OPTIONSTYPE"] = "1"  # 代码是 P
    with pytest.raises(so.ParseError):
        so.parse_kx(json.dumps(doc).encode(), date(2026, 9, 30))
    doc = json.loads(KX_20260930)
    doc["o_curinstrument"][0]["STRIKEPRICE"] = 430
    with pytest.raises(so.ParseError):
        so.parse_kx(json.dumps(doc).encode(), date(2026, 9, 30))
    with pytest.raises(so.ParseError):  # 文件内 report_date 与文件名日期不符
        so.parse_kx(_b(KX_20260930), date(2026, 9, 29))
    with pytest.raises(so.ParseError):
        so.parse_kx(b"<html>waf</html>", date(2026, 9, 30))


def test_parse_baseinfo() -> None:
    assert so.parse_baseinfo(_b(BASEINFO_20260930), date(2026, 9, 30)) == {
        "sc2611P425": "20261014",
        "cu2611P128000": "20261026",
    }
    assert so.parse_baseinfo(_b(BASEINFO_20190614), date(2019, 6, 14))["cu1907P47000"] == "20190624"


# ---------------------------------------------------------------------------------------------
# 代码规范化
# ---------------------------------------------------------------------------------------------


def test_parse_option_code_variants() -> None:
    assert so.parse_option_code("cu2611C90000  ") == ("cu2611", "C", 90000.0)
    assert so.parse_option_code("sc2406P425") == ("sc2406", "P", 425.0)
    assert so.parse_option_code("SR001C5000") == ("SR001", "C", 5000.0)
    assert so.parse_option_code("m2101-C-2800") == ("m2101", "C", 2800.0)
    with pytest.raises(so.ParseError):
        so.parse_option_code("小计")


def test_normalize_underlying_matches_project_futures_codes() -> None:
    assert so.normalize_underlying("cu2611", date(2026, 9, 30)) == "CU2611"
    assert so.normalize_underlying(" sc2406 ", date(2024, 3, 1)) == "SC2406"
    assert so.exchange_of("SC") == "INE" and so.exchange_of("BC") == "INE" and so.exchange_of("CU") == "SHFE"
    # 郑商所 3 位年月:十年位用文件日期推断,跨 2019→2020 十年边界
    ts = pd.Timestamp
    assert normalize_contract("SR001", "CZCE", ts("2019-12-20")) == "SR2001"
    assert normalize_contract("SR912", "CZCE", ts("2019-06-03")) == "SR1912"
    assert normalize_contract("CF009", "CZCE", ts("2020-01-03")) == "CF2009"
    assert normalize_contract("CF101", "CZCE", ts("2020-11-02")) == "CF2101"
    assert normalize_contract("TA909", "CZCE", ts("2019-01-02")) == "TA1909"
    und, _, _ = so.parse_option_code("SR001C5000")
    assert so.normalize_underlying(und, date(2019, 12, 20)) == "SR2001"
    assert so.normalize_underlying("SR101", date(2020, 12, 1)) == "SR2101"


# ---------------------------------------------------------------------------------------------
# 可得日
# ---------------------------------------------------------------------------------------------


def test_available_day_is_next_calendar_day_strictly_after() -> None:
    cal = pd.DatetimeIndex(["2018-09-21", "2018-09-25", "2018-09-26", "2026-09-29", "2026-09-30"])
    hol = [pd.Timestamp(f"2026-10-0{d}") for d in (1, 2, 5, 6, 7)]
    dates = pd.Series(pd.to_datetime(["2018-09-21", "2018-09-25", "2018-09-22", "2026-09-29", "2026-09-30"]))
    got = so.available_days(dates, cal, hol)
    exp = pd.to_datetime(["2018-09-25", "2018-09-26", "2018-09-25", "2026-09-30", "2026-10-08"])
    assert list(got) == list(exp)  # 中秋 09-24 不在日历中 → 跳过;日历末端之后用 工作日 − 公告假期
    assert (got > pd.DatetimeIndex(dates)).all()


# ---------------------------------------------------------------------------------------------
# 下载幂等 + 构建(假服务器)
# ---------------------------------------------------------------------------------------------


def test_fetch_idempotent_and_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    pages = {
        so.url_for("kx", date(2026, 9, 30)): KX_20260930,
        so.url_for("baseinfo", date(2026, 9, 30)): BASEINFO_20260930,
    }

    def fake_get(url: str) -> tuple[int, bytes, dict[str, str]]:
        calls.append(url)
        if url in pages:
            return 200, _b(pages[url]), {"last-modified": "Wed, 30 Sep 2026 07:34:43 GMT"}
        return 404, b"<html>404</html>", {}

    monkeypatch.setattr(so, "_get_once", fake_get)
    monkeypatch.setattr(so, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(so, "_utc_now_iso", lambda: "2026-10-01T00:00:00Z")
    so.fetch(tmp_path, "2026-09-25", "2026-09-30")  # 09-25 中秋 404;09-28/29 假服务器无 → 404
    n_first = len(calls)
    assert n_first == 4 + 1  # 4 个工作日 kx + 09-30 baseinfo(09-26/27 周末不请求)
    meta: dict[str, Any] = json.loads(
        (tmp_path / "raw" / "kx" / "2026" / "kx20260930.dat.gz.meta.json").read_text(encoding="utf-8")
    )
    assert meta["http_status"] == 200 and meta["last_modified_utc"] == "2026-09-30T07:34:43Z"
    assert meta["update_date"] == "20260930 15:34:43" and meta["fetched_at_utc"] == "2026-10-01T00:00:00Z"
    with gzip.open(tmp_path / "raw" / "kx" / "2026" / "kx20260930.dat.gz") as fh:
        assert fh.read() == _b(KX_20260930)
    # 再跑:已有文件不再请求;日期后不足 7 天的 404 尚非最终,重探一次后(探于 10-20)成为最终
    monkeypatch.setattr(so, "_utc_now_iso", lambda: "2026-10-20T00:00:00Z")
    so.fetch(tmp_path, "2026-09-25", "2026-09-30")
    so.fetch(tmp_path, "2026-09-25", "2026-09-30")
    assert all("20260930" not in u for u in calls[n_first:])
    assert len(calls) - n_first == 3  # 第二次重探 3 个 404 日;第三次全部已是最终 404

    empty_root = tmp_path / "no_futures"
    empty_root.mkdir()
    rep = so.BuildReport()
    hol = [pd.Timestamp(f"2026-10-0{d}") for d in (1, 2, 5, 6, 7)]
    df = so.build(tmp_path, exchanges_root=empty_root, holidays=hol, report=rep)
    assert list(df.columns) == so.OUTPUT_COLUMNS
    assert len(df) == 3 and (df["available_day"] == pd.Timestamp("2026-10-08")).all()
    exp = df.set_index("option_code")["expire_date"]
    assert exp["sc2611P425"] == pd.Timestamp("2026-10-14")
    assert exp["sc2611P580"] == pd.Timestamp("2026-10-14")  # 基础信息无此代码 → 同系列到期日
    assert exp["cu2611P128000"] == pd.Timestamp("2026-10-26")
    assert rep.expire_fallback == {"series": 1}
    assert (df["source_file"] == "raw/kx/2026/kx20260930.dat.gz").all()
    assert (df["last_modified_utc"] == "2026-09-30T07:34:43Z").all()
    files = pd.read_csv(tmp_path / "files.csv")
    assert list(files["kind"]) == ["baseinfo", "kx"] and list(files["http_status"]) == [200, 200]
    again = pd.read_parquet(tmp_path / "options_daily.parquet")
    pd.testing.assert_frame_equal(again, df)


def _write_baseinfo(raw: Path, d: date, mapping: dict[str, str]) -> None:
    body = json.dumps(
        {
            "OptionContractBaseInfo": [{"INSTRUMENTID": k, "EXPIREDATE": v} for k, v in mapping.items()],
            "report_date": d.strftime("%Y%m%d"),
        }
    ).encode()
    f, m = so.raw_paths(raw, "baseinfo", d)
    f.parent.mkdir(parents=True, exist_ok=True)
    gz = gzip.compress(body, mtime=0)
    f.write_bytes(gz)
    m.write_text(json.dumps({"gz_size": len(gz)}), encoding="utf-8")


def test_expiry_book_is_point_in_time(tmp_path: Path) -> None:
    """交易所改到期日(2018-12-11 cu1901 由 20181225 → 20181224):T 当日只用 ≤ T 的文件。"""
    raw = tmp_path / "raw"
    _write_baseinfo(raw, date(2018, 12, 10), {"cu1901C46000": "20181225"})
    _write_baseinfo(raw, date(2018, 12, 11), {"cu1901C46000": "20181224", "cu1902C46000": "20190125"})
    rep = so.BuildReport()
    book = so.ExpiryBook(raw, rep)
    book.advance(date(2018, 12, 7))
    assert book.lookup("cu1901C46000") == ("20181225", "later")  # 无 ≤ T 文件 → 之后首次出现值
    book.advance(date(2018, 12, 10))
    assert book.lookup("cu1901C46000") == ("20181225", "asof")
    assert book.lookup("cu1901P46000") == ("20181225", "series")
    assert book.lookup("cu1902C46000") == ("20190125", "later")
    book.advance(date(2018, 12, 11))
    assert book.lookup("cu1901C46000") == ("20181224", "asof")
    assert book.lookup("cu1903C46000") == (None, "missing")
    assert rep.expiry_conflicts == [("cu1901C46000", "2018-12-11", "20181225", "20181224")]


# ---------------------------------------------------------------------------------------------
# 真实数据(本地已抓取时)
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real() -> pd.DataFrame:
    if not TABLE.exists():
        pytest.skip("options_daily.parquet not built")
    return pd.read_parquet(TABLE)


def test_real_schema_and_uniqueness(real: pd.DataFrame) -> None:
    assert list(real.columns) == so.OUTPUT_COLUMNS
    assert not real.duplicated(["date", "option_code"]).any()
    assert set(real["cp"]) == {"C", "P"}
    assert set(real["exchange"]) <= {"SHFE", "INE"}
    assert (real.loc[real["exchange"] == "INE", "product"].isin(["SC", "LU", "NR", "BC", "EC"])).all()
    assert real["underlying"].str.fullmatch(r"[A-Z]{1,2}\d{4}").all()
    assert (real["underlying"].str.replace(r"\d+$", "", regex=True) == real["product"]).all()


def test_real_available_day_strictly_after(real: pd.DataFrame) -> None:
    assert (real["available_day"] > real["date"]).all()
    per_day = real.groupby("date")["available_day"].nunique()
    assert (per_day == 1).all()
    days = pd.DatetimeIndex(sorted(real["date"].unique()))
    nxt = real.groupby("date")["available_day"].first().reindex(days)
    inner = nxt.iloc[:-1]
    assert (inner.to_numpy() <= days[1:].to_numpy()).all()  # 不会跳过下一个期权日


def test_real_put_delta_and_iv_range(real: pd.DataFrame) -> None:
    assert (real.loc[real["cp"] == "P", "delta"].dropna() <= 0).all()
    assert (real.loc[real["cp"] == "C", "delta"].dropna() >= 0).all()
    iv = real["iv_exchange"].dropna()
    assert ((iv > 0) & (iv < 3)).all()
    assert real["iv_exchange"].notna().mean() > 0.99


def test_real_double_sided_halving(real: pd.DataFrame) -> None:
    pre = real[real["date"] < pd.Timestamp("2020-01-01")]
    post = real[real["date"] >= pd.Timestamp("2020-01-01")]
    assert len(pre) > 0 and len(post) > 0
    np.testing.assert_allclose(pre["volume"] * 2, pre["volume_raw"])
    np.testing.assert_allclose(pre["oi"] * 2, pre["oi_raw"])
    assert (pre["volume_raw"] % 2 == 0).all()  # 双边计数必为偶数
    np.testing.assert_allclose(post["volume"], post["volume_raw"])
    np.testing.assert_allclose(post["turnover"], post["turnover_raw"])


def test_real_prereg_coverage_from_listing(real: pd.DataFrame) -> None:
    cov = so.coverage(real).set_index("product")
    for prod, first in so.PREREG_LISTING.items():
        assert cov.loc[prod, "first_date"] == first, prod
        assert cov.loc[prod, "missing_days"] == 0, (prod, cov.loc[prod, "first_missing"])
    assert real["date"].min() == pd.Timestamp(so.FIRST_DAY)
    assert real["expire_date"].notna().all()
    assert (real["expire_date"] >= real["date"]).all()


def test_has_ohlc_flag_marks_settlement_only_trades() -> None:
    """成交全部按结算价的合约(开/高/低为空)has_ohlc = False;有盘中成交的为 True(期权三条 O1 据此排除前者)。"""
    real = Path("data/external/alt/shfe_options/options_daily.parquet")
    if not real.exists():
        pytest.skip("需要真实表")
    d = pd.read_parquet(real, columns=["date", "option_code", "volume", "close", "settle", "has_ohlc"])
    row = d[(d["date"] == pd.Timestamp("2026-09-30")) & (d["option_code"] == "cu2612C96000")]
    assert len(row) == 1 and not bool(row["has_ohlc"].iloc[0]) and float(row["volume"].iloc[0]) > 0
    assert d["has_ohlc"].dtype == bool
    assert int(((d["volume"] > 0) & ~d["has_ohlc"]).sum()) == 8595
