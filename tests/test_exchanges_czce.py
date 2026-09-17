"""郑商所数据层:解析(GBK/UTF-8、3 位年份代码、合计行)、离线落盘/断点续跑、与米筐导出对账(有数据才跑)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges import czce
from cta.data.exchanges.base import POSITION_COLS, QUOTE_COLS, RECEIPT_COLS, Store, validate

FIX = Path(__file__).parent / "fixtures" / "exchanges" / "czce"


def _raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ----------------------------------------------------------------------------- 行情


def test_parse_quotes_gbk_2016_three_digit_codes() -> None:
    q = czce.parse_quotes(_raw("FutureDataDaily_20160104.txt"), pd.Timestamp("2016-01-04"))
    assert list(q.columns) == QUOTE_COLS
    assert list(q["contract"]) == [
        "CF1601",
        "CF1603",
        "CF1605",
        "CF1607",
        "CF1609",
        "CF1611",
        "FG1601",
        "FG1602",
        "FG1603",
    ]
    assert (q["exchange"] == "CZCE").all() and (q["date"] == pd.Timestamp("2016-01-04")).all()
    cf = q.set_index("contract").loc["CF1601"]
    assert (cf["open"], cf["high"], cf["low"], cf["close"]) == (11850.0, 11890.0, 11805.0, 11805.0)
    assert (cf["settle"], cf["prev_settle"]) == (11845.0, 11905.0)
    assert (cf["volume"], cf["open_interest"]) == (11792.0, 47872.0)  # 2016 为双边口径,保留原值
    assert cf["turnover"] == pytest.approx(69852.12 * 10_000)  # 万元 → 元
    fg = q.set_index("contract").loc["FG1602"]
    assert fg["volume"] == 0 and np.isnan(fg["open"]) and fg["settle"] == 876.0  # 无成交:0 价 → NaN
    out = validate("quotes", q)
    assert len(out) == 9


def test_parse_quotes_utf8_2026_drops_subtotals() -> None:
    q = czce.parse_quotes(_raw("FutureDataDaily_20260911.txt"), pd.Timestamp("2026-09-11"))
    assert len(q) == 13 and set(q["symbol"]) == {"AP", "CF"}
    assert "CF2609" in set(q["contract"]) and "CF2701" in set(q["contract"])
    row = q.set_index("contract").loc["CF2701"]
    assert row["volume"] == 384882.0 and row["open_interest"] == 512156.0 and row["settle"] == 16450.0
    assert not q["contract"].str.contains("计").any()


def test_parse_quotes_zero_price_with_volume_kept_as_nan() -> None:
    text = (
        "合约代码|昨结算|今开盘|最高价|最低价|今收盘|今结算|涨跌1|涨跌2|成交量(手)|持仓量|增减量|成交额(万元)|交割结算价\n"
        "MA601 |1,764.00|0.00|0.00|0.00|0.00|1,760.00|0.00|0.00|3,900|9,584|0|6,747.00|\n"
        "小计 | | | | | | | | |3,900|9,584|0|6,747.00|\n"
    )
    q = czce.parse_quotes(text, pd.Timestamp("2016-01-11"))
    assert len(q) == 1 and q.loc[0, "contract"] == "MA1601"
    assert q.loc[0, "volume"] == 3900.0 and np.isnan(q.loc[0, "close"])
    validate("quotes", q)  # 有量无价的交割月行不再触发校验失败


def test_parse_annual_zip() -> None:
    z = czce.parse_annual_zip(_raw("ALLFUTURES2025_sample.zip"))
    assert set(z["symbol"]) == {"CF", "SR"}
    assert sorted(z["date"].unique()) == [np.datetime64("2025-01-02"), np.datetime64("2025-01-03")]
    row = z.set_index(["date", "contract"]).loc[(pd.Timestamp("2025-01-02"), "CF2501")]
    assert row["settle"] == 13475.0 and row["volume"] == 2637.0 and row["open_interest"] == 65628.0
    for _, g in z.groupby("date"):
        validate("quotes", g)


# ----------------------------------------------------------------------------- 持仓排名


def test_parse_positions_utf8_species_and_contract_blocks() -> None:
    p = czce.parse_positions(_raw("FutureDataHolding_20260911.txt"), pd.Timestamp("2026-09-11"))
    assert list(p.columns) == POSITION_COLS
    assert set(p["contract"]) == {"CF", "CF2609"} and (p["symbol"] == "CF").all()
    sp = p[p["contract"] == "CF"]
    assert len(sp) == 21 and sp["is_total"].sum() == 1
    r1 = sp[sp["rank"] == 1].iloc[0]
    assert r1["member_vol"] == "中信期货（代客）" and r1["vol"] == 130474.0 and r1["vol_chg"] == -1895.0
    assert r1["member_long"] == "中信期货（代客）" and r1["long_oi"] == 92677.0
    assert (
        r1["member_short"] == "中信期货（代客）" and r1["short_oi"] == 110344.0 and r1["short_chg"] == -295.0
    )
    tot = sp[sp["is_total"]].iloc[0]
    assert (
        tot["rank"] == 0
        and tot["vol"] == 817239.0
        and tot["long_oi"] == 635256.0
        and tot["short_oi"] == 721162.0
    )
    ct = p[p["contract"] == "CF2609"]
    assert ct[ct["is_total"]].iloc[0]["long_oi"] == 28963.0
    validate("positions", p)


def test_parse_positions_gbk_2016() -> None:
    p = czce.parse_positions(_raw("FutureDataHolding_20160104.txt"), pd.Timestamp("2016-01-04"))
    assert len(p) == 4 and list(p["rank"]) == [1, 2, 3, 0]
    assert p.loc[0, "member_vol"] == "永安期货" and p.loc[0, "vol"] == 13649.0
    assert p.loc[3, "is_total"] and p.loc[3, "vol"] == 134244.0 and p.loc[3, "short_chg"] == 3240.0


# ----------------------------------------------------------------------------- 仓单


def test_parse_receipts_utf8_skips_forecast_and_sums_bonded() -> None:
    r = czce.parse_receipts(_raw("FutureDataWhsheet_20260911.txt"), pd.Timestamp("2026-09-11"))
    assert list(r.columns) == RECEIPT_COLS
    assert set(r["symbol"]) == {"CJ", "TA", "ZC"}
    cj = r[r["symbol"] == "CJ"]
    assert cj["is_total"].sum() == 1  # 预报表被跳过,只有仓单表一个总计
    assert cj[cj["is_total"]].iloc[0]["receipts"] == 6275.0 and cj[cj["is_total"]].iloc[0]["change"] == -261.0
    wh = cj[~cj["is_total"]].set_index("warehouse")
    assert (
        len(wh) == 12
        and wh.loc["新疆叶河源", "receipts"] == 1846.0
        and wh.loc["新疆叶河源", "change"] == -96.0
    )
    assert wh["receipts"].sum() == 6275.0
    ta = r[r["symbol"] == "TA"]
    assert ta[ta["is_total"]].iloc[0]["receipts"] == 13435.0  # 完税 13435 + 保税 0
    assert len(ta[~ta["is_total"]]) == 6
    zc = r[r["symbol"] == "ZC"]
    assert len(zc) == 6 and zc["receipts"].sum() == 0.0
    validate("receipts", r)


def test_parse_receipts_gbk_2016_subrows_and_no_subtotal() -> None:
    r = czce.parse_receipts(_raw("FutureDataWhsheet_20160104.txt"), pd.Timestamp("2016-01-04"))
    cf = r[r["symbol"] == "CF"]
    wh = cf[~cf["is_total"]].set_index("warehouse")
    assert list(wh["receipts"]) == [20.0, 49.0, 314.0] and wh.loc["豫棉物流", "change"] == -2.0
    assert cf[cf["is_total"]].iloc[0]["receipts"] == 667.0  # 交易所总计原值(样例截断,不等于仓库之和)
    tc = r[r["symbol"] == "TC"]
    assert len(tc) == 11 and tc["is_total"].sum() == 1
    # 强麦块在总计之后还有"可交割品牌"附表(同样以 仓库编号|仓库简称 开头):不能当仓单行
    wh = r[r["symbol"] == "WH"]
    assert list(wh["warehouse"]) == ["济宁一库", "菏泽粮库", "合计"]
    assert list(wh["receipts"]) == [0.0, 0.0, 445.0] and wh["receipts"].notna().all()


def test_parse_receipts_wheat_confirmations_and_dash_members() -> None:
    text = (
        "品种：强麦WH   单位：张          日期：2026-09-11     每张确认书=1手合约*20吨/手=20吨\n"
        "机构编号  |机构简称  |品种  |等级  |确认书数量|当日增减  |有效入库预报|升贴水\n"
        "0101      |济宁一库  |      |      |12        |2         |0         |0\n"
        "小计      |          |      |      |12        |2         |0         |\n"
        "总计      |          |      |      |12        |2         |0         |\n"
    )
    r = czce.parse_receipts(text, pd.Timestamp("2026-09-11"))
    assert list(r["receipts"]) == [12.0, 12.0] and list(r["is_total"]) == [False, True]
    pos = (
        "合约：OI601              日期： 2016-01-04\n"
        "名次  |会员简称|成交量（手）|增减量|会员简称|持买仓量|增减量|会员简称|持卖仓量|增减量\n"
        "1     |-       |            |      |中粮期货|150     |0     |-       |        |\n"
        "合计  |        |0           |0     |        |150     |0     |        |0       |0\n"
    )
    pp = czce.parse_positions(pos, pd.Timestamp("2016-01-04"))
    assert pp.loc[0, "member_vol"] == "" and np.isnan(pp.loc[0, "vol"]) and pp.loc[0, "long_oi"] == 150.0
    assert pp.loc[0, "contract"] == "OI1601" and pp.loc[1, "is_total"]


def test_parse_receipts_synthesises_total_when_absent() -> None:
    text = (
        "品种：动力煤TC   单位：张          日期：2016-01-04\n"
        "厂库编号  |厂库简称  |仓单数量  |当日增减  |升贴水\n"
        "1201      |中煤能源  |5         |1         |0\n"
        "1202      |神华销售  |7         |-2        |0\n"
    )
    r = czce.parse_receipts(text, pd.Timestamp("2016-01-04"))
    assert (
        len(r) == 3
        and r.iloc[-1]["is_total"]
        and r.iloc[-1]["receipts"] == 12.0
        and r.iloc[-1]["change"] == -1.0
    )


# ----------------------------------------------------------------------------- 落盘 / 断点续跑(离线)


class _FakeFetcher(czce.Fetcher):
    """按 URL 返回 fixture;不存在的日期返回 404。记录请求次数。"""

    def __init__(self) -> None:
        super().__init__(sleep=0.0, cdp_proxy=None)
        self.calls: list[str] = []

    def get(self, url: str, allow_cdp: bool = True) -> tuple[int, bytes]:
        self.calls.append(url)
        name = url.rsplit("/", 1)[-1].replace(".txt", "")
        day = url.split("/")[-2]
        p = FIX / f"{name}_{day}.txt"
        return (200, p.read_bytes()) if p.exists() else (404, b"")


def test_ingest_day_and_backfill_resume(tmp_path: Path) -> None:
    st = Store(tmp_path)
    fx = _FakeFetcher()
    d = pd.Timestamp("2026-09-11")
    res = czce.ingest_day(d, czce.KINDS, st, fx)
    assert res == {"quotes": "ok", "positions": "ok", "receipts": "ok"}
    assert st.read_raw("CZCE", "quotes", d, "txt") == _raw("FutureDataDaily_20260911.txt")
    assert st.has_day("CZCE", "receipts", d)
    assert czce.ingest_day(d, ["quotes"], st, fx) == {"quotes": "exists"}
    # 回填 9/10(节假日样例:404)与 9/11(已有):404 记入 missing.log,第二次运行不再请求
    n0 = len(fx.calls)
    czce.backfill(pd.Timestamp("2026-09-10"), d, ["quotes"], st, fx, use_annual=False)
    assert len(fx.calls) == n0 + 1
    assert czce.load_missing(st) == {(pd.Timestamp("2026-09-10"), "quotes"): "404"}
    czce.backfill(pd.Timestamp("2026-09-10"), d, ["quotes"], st, fx, use_annual=False)
    assert len(fx.calls) == n0 + 1
    cov = czce.coverage(st)
    assert cov.loc[2026, "quotes"] == 1 and cov.loc[2026, "positions"] == 1
    assert czce.reparse(d, d, ["positions"], st) == 1


def test_urls_and_counting_basis() -> None:
    assert czce.daily_url("quotes", pd.Timestamp("2016-01-04")).endswith(
        "/Future/2016/20160104/FutureDataDaily.txt"
    )
    assert czce.daily_url("positions", pd.Timestamp("2026-09-11")).endswith(
        "/2026/20260911/FutureDataHolding.txt"
    )
    assert czce.annual_zip_url(2025).endswith("/2025/ALLFUTURES2025.zip")
    assert czce.annual_zip_url(2016).endswith("/2016/FutureDataHistory.zip")
    assert czce.counting_basis(pd.Timestamp("2019-12-31")) == "double"
    assert czce.counting_basis(pd.Timestamp("2020-01-02")) == "single"
    assert czce.decode_text("已解码") == "已解码" and czce.decode_text("棉花".encode("gbk")) == "棉花"


# ----------------------------------------------------------------------------- 与米筐导出对账(有数据才跑)

_HAVE_DATA = (czce.RQ_DIR / "CF.parquet").exists() and bool(Store().days("CZCE", "quotes"))


@pytest.mark.skipif(not _HAVE_DATA, reason="需要本地郑商所落盘数据与米筐导出")
def test_reconcile_with_ricequant_export() -> None:
    summary, mism = czce.reconcile(("CF", "SR", "TA", "MA", "SA"))
    assert not summary.empty and (summary["pairs"] > 1000).all()
    # 有成交的行 OHLC 完全一致;无成交行米筐用结算价填 OHLC
    assert (summary["ohlc_match_traded"] >= 0.999).all(), summary
    assert (summary["untraded_fill_settle"] >= 0.98).all(), summary
    # volume/OI 按交易所原值大部分一致;不一致时米筐总是偏小(交易所日报含结算后的期转现/交割配对)
    assert (summary["vol_match_raw"] >= 0.8).all() and (summary["oi_match_raw"] >= 0.8).all(), summary
    assert (summary["vol_mismatch_rq_lower"] >= 0.99).all(), summary
    # 口径:两段都是交易所原值,2020 年前除以 2 反而对不上
    pre = summary[summary["pre2020_pairs"] > 1000]
    assert (pre["oi_match_half_pre2020"] < pre["oi_match_raw"] - 0.3).all(), summary
    assert set(mism["reason"]) <= {"ohlc", "volume", "volume_efp", "open_interest"}
