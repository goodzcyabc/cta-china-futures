"""上期所 / 能源中心数据模块:用 tests/fixtures 里的截断样例测解析与规范化(不联网);有本地数据时与米筐导出对账。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges import ine, shfe
from cta.data.exchanges.base import POSITION_COLS, QUOTE_COLS, RECEIPT_COLS, Store, validate

FIX = Path(__file__).parent / "fixtures" / "exchanges"
ROOT = Path(__file__).resolve().parents[1]
RICE = ROOT / "data" / "ricecta" / "data" / "contracts_daily"
EXCH = ROOT / "data" / "exchanges"


def _fx(exchange: str, name: str) -> bytes:
    return (FIX / exchange / name).read_bytes()


# ---------------------------------------------------------------------------------------------
# 行情
# ---------------------------------------------------------------------------------------------


def test_parse_quotes_new_format_filters_rows() -> None:
    """2026 格式:剔除 小计/总计/TAS/期转现,剔除能源中心品种(sc),保留 TURNOVER。"""
    df = shfe.parse_quotes(_fx("shfe", "kx20260915.dat"), pd.Timestamp("2026-09-15"))
    assert list(df.columns) == QUOTE_COLS
    assert list(df["contract"]) == ["CU2609", "CU2610"]
    assert (df["exchange"] == "SHFE").all() and (df["symbol"] == "CU").all()
    r = df.set_index("contract").loc["CU2610"]
    assert (r["open"], r["high"], r["low"], r["close"]) == (106900.0, 107410.0, 106650.0, 107030.0)
    assert (r["settle"], r["prev_settle"]) == (106930.0, 108190.0)
    assert (r["volume"], r["open_interest"]) == (107989.0, 180076.0)
    assert r["turnover"] == pytest.approx(5774083.97)  # 万元,交易所原值
    validate("quotes", df)


def test_parse_quotes_old_format_and_zero_volume() -> None:
    """2016 格式:PRODUCTID 带空格、无 PRODUCTGROUPID/TURNOVER;无成交合约 OHLC 为 NaN;efp 行剔除。"""
    df = shfe.parse_quotes(_fx("shfe", "kx20160104.dat"), pd.Timestamp("2016-01-04"))
    assert list(df["contract"]) == ["CU1601", "CU1602", "PB1606"]
    assert df["turnover"].isna().all()
    cu = df.set_index("contract").loc["CU1601"]
    assert (cu["close"], cu["settle"], cu["volume"], cu["open_interest"]) == (
        36240.0,
        36270.0,
        14746.0,
        50400.0,
    )
    out = validate("quotes", df)
    pb = out.set_index("contract").loc["PB1606"]
    assert pb["volume"] == 0 and np.isnan(pb["open"]) and np.isnan(pb["close"]) and pb["settle"] == 12780.0


def test_parse_quotes_ine_old_format() -> None:
    df = ine.parse_quotes(_fx("ine", "kx20180326.dat"), pd.Timestamp("2018-03-26"))
    assert list(df["contract"]) == ["SC1809", "SC1810", "SC2103"]
    assert (df["exchange"] == "INE").all()
    assert df.iloc[0]["settle"] == 433.8 and df.iloc[0]["volume"] == 40656.0
    validate("quotes", df)


def test_site_ownership_splits_shfe_and_ine() -> None:
    assert shfe.SHFE.owns("CU") and not shfe.SHFE.owns("SC")
    assert ine.INE.owns("SC") and not ine.INE.owns("CU")
    # 同一份 kx 文件,两个站点各取各的
    raw = _fx("shfe", "kx20260915.dat")
    assert set(ine.parse_quotes(raw, pd.Timestamp("2026-09-15"))["contract"]) == {"SC2610"}


# ---------------------------------------------------------------------------------------------
# 会员持仓排名
# ---------------------------------------------------------------------------------------------


def test_parse_positions_totals_and_product_rows() -> None:
    df = shfe.parse_positions(_fx("shfe", "pm20260915.dat"), pd.Timestamp("2026-09-15"))
    assert list(df.columns) == POSITION_COLS
    validate("positions", df)
    prod = df[df["contract"] == "CU"]  # cuall → 品种合计,contract 记为品种代码
    assert list(prod["member_vol"]) == ["期货公司会员", "非期货公司会员"]
    assert prod["is_total"].all() and (prod["rank"] == 0).all()
    assert prod.iloc[0]["vol"] == 424984.0 and prod.iloc[1]["short_oi"] == 13897.0
    c = df[df["contract"] == "CU2609"].set_index("rank")
    assert c.loc[1, "member_vol"] == "金瑞期货" and c.loc[1, "member_long"] == "中信期货"
    assert c.loc[1, "member_short"] == "云晨期货" and c.loc[1, "short_chg"] == 110.0
    assert c.loc[20, "member_long"] is None and math.isnan(c.loc[20, "long_oi"])  # 榜单不齐的行
    tot = c.loc[0]
    assert (
        tot["is_total"] and tot["member_vol"] == "合计" and tot["vol"] == 4960.0 and tot["long_oi"] == 2925.0
    )


def test_parse_positions_2016_format() -> None:
    df = shfe.parse_positions(_fx("shfe", "pm20160104.dat"), pd.Timestamp("2016-01-04"))
    c = df[df["contract"] == "CU1601"]
    assert list(c["member_vol"]) == ["期货公司会员", "非期货公司会员", "金瑞期货", "合计"]
    assert list(c["rank"]) == [0, 0, 1, 0] and list(c["is_total"]) == [True, True, False, True]
    actv = df[df["contract"] == "CU"]  # cuactv → 品种合计
    assert len(actv) == 1 and actv.iloc[0]["rank"] == 1 and actv.iloc[0]["member_vol"] == "海通期货"


def test_parse_positions_ine() -> None:
    df = ine.parse_positions(_fx("ine", "pm20240603.dat"), pd.Timestamp("2024-06-03"))
    assert set(df["symbol"]) == {"LU", "NR"} and (df["exchange"] == "INE").all()
    lu = df[df["contract"] == "LU2407"].set_index("rank")
    assert lu.loc[0, "member_vol"] == "合计" and lu.loc[0, "vol"] == 9208.0
    assert lu.loc[2, "member_short"] == "西部期货"
    validate("positions", df)


# ---------------------------------------------------------------------------------------------
# 仓单日报
# ---------------------------------------------------------------------------------------------


def test_receipt_symbol_mapping() -> None:
    assert shfe.receipt_symbol("螺纹钢厂库$$Rebar Factory Warehouse") == ("RB", True)
    assert shfe.receipt_symbol("氧化铝(仓库)") == ("AO", False)
    assert shfe.receipt_symbol("铜(BC)$$COPPER(BC)") == ("BC", False)
    assert shfe.receipt_symbol("沥青厂库$$BITUMEN Factory Warehouse") == ("BU", True)
    assert shfe.receipt_symbol("不认识的品种", "xx") == ("XX", False)  # VARID 优先
    assert shfe.receipt_symbol("不认识的品种") == (None, False)


def test_parse_receipts_json_with_varid() -> None:
    df = shfe.parse_receipts(_fx("shfe", "20250603dailystock.dat"), pd.Timestamp("2025-06-03"))
    assert list(df.columns) == RECEIPT_COLS
    assert "SC" not in set(df["symbol"])  # 原油归能源中心
    cu = df[df["symbol"] == "CU"]
    assert list(cu["warehouse"]) == [
        "国储天威",
        "国储外高桥",
        "上海合计",
        "保税商品总计",
        "完税商品总计",
        "总计",
    ]
    assert list(cu["is_total"]) == [False, False, True, True, True, True]
    assert cu.iloc[-1]["receipts"] == 31404.0 and cu.iloc[-1]["change"] == -2724.0
    rb = df[df["symbol"] == "RB"]
    assert list(rb["warehouse"]) == ["鞍钢股份(厂库)"] and not rb.iloc[0]["is_total"]
    validate("receipts", df)


def test_parse_receipts_json_2016_no_varid() -> None:
    df = shfe.parse_receipts(_fx("shfe", "20160104dailystock.dat"), pd.Timestamp("2016-01-04"))
    assert set(df["symbol"]) == {"CU", "BU", "AU"}
    cu = df[df["symbol"] == "CU"].set_index("warehouse")
    assert cu.loc["期晟公司", "receipts"] == 6601.0 and cu.loc["上海合计", "is_total"]
    assert cu.loc["总计", "receipts"] == 30610.0 and cu.loc["总计", "change"] == -6263.0
    assert df[df["symbol"] == "BU"].iloc[0]["warehouse"] == "中油高富(厂库)"
    assert df[df["symbol"] == "AU"].iloc[0]["receipts"] == 1026.0  # 千克


def test_parse_receipts_html_new_format() -> None:
    df = shfe.parse_receipts(_fx("shfe", "dailystock_20260915.html"), pd.Timestamp("2026-09-15"), ext="html")
    cu = df[df["symbol"] == "CU"]
    assert list(cu["warehouse"]) == [
        "国储天威",
        "中储吴淞",
        "裕强闵行",
        "上海合计",
        "江西国储",
        "保税商品总计",
        "完税商品总计",
        "总计",
    ]
    assert list(cu["receipts"]) == [429.0, 5766.0, 991.0, 18164.0, 0.0, 0.0, 31850.0, 31850.0]
    assert list(cu["is_total"]) == [False, False, False, True, False, True, True, True]
    rb = df[df["symbol"] == "RB"]
    assert list(rb["warehouse"]) == ["物产中大金属(厂库)", "镔钢集团(厂库)", "厂库提货地合计(厂库)"]
    assert "SC" not in set(df["symbol"])
    validate("receipts", df)
    sc = ine.parse_receipts(_fx("ine", "dailystock_20260915.html"), pd.Timestamp("2026-09-15"), ext="html")
    assert set(sc["symbol"]) == {"SC"} and (sc["exchange"] == "INE").all()
    assert list(sc["warehouse"]) == ["中国石化册子岛", "中化兴中", "浙江合计", "总计"]
    assert sc.iloc[-1]["receipts"] == 2961000.0  # 桶


def test_parse_receipts_ine_json() -> None:
    df = ine.parse_receipts(_fx("ine", "20220601dailystock.dat"), pd.Timestamp("2022-06-01"))
    assert set(df["symbol"]) == {"SC", "BC"}
    sc = df[df["symbol"] == "SC"]
    assert sc.iloc[0]["warehouse"] == "洋山石油" and sc.iloc[0]["receipts"] == 190000.0
    assert sc.iloc[-1]["warehouse"] == "总计" and sc.iloc[-1]["receipts"] == 8071000.0
    assert df[df["symbol"] == "BC"].iloc[-1]["warehouse"] == "上海合计"


# ---------------------------------------------------------------------------------------------
# 落盘与回填(用 raw 缓存,不联网)
# ---------------------------------------------------------------------------------------------


def test_ingest_day_from_cached_raw(tmp_path: Path) -> None:
    st = Store(tmp_path)
    d = pd.Timestamp("2026-09-15")
    st.write_raw("SHFE", "quotes", d, "json", _fx("shfe", "kx20260915.dat"))
    st.write_raw("SHFE", "positions", d, "json", _fx("shfe", "pm20260915.dat"))
    st.write_raw("SHFE", "receipts", d, "html", _fx("shfe", "dailystock_20260915.html"))
    status = shfe.ingest_day(d, store=st)
    assert status == {"quotes": "written", "positions": "written", "receipts": "written"}
    assert shfe.ingest_day(d, store=st) == {"quotes": "exists", "positions": "exists", "receipts": "exists"}
    q = st.read_days("SHFE", "quotes")
    assert list(q["contract"]) == ["CU2609", "CU2610"]
    r = st.read_days("SHFE", "receipts")
    assert (r["symbol"] == "CU").sum() == 8 and (r["symbol"] == "RB").sum() == 3
    cov = shfe.coverage(st)
    assert cov.loc[0, "year"] == 2026 and int(cov.loc[0, "quotes"]) == 1


def test_backfill_skips_weekends_and_missing_log(tmp_path: Path) -> None:
    """missing.log 里的 (日期, 类型) 不再请求;周末不请求;已有 parquet 跳过 —— 全程无网络访问。"""
    st = Store(tmp_path)
    d = pd.Timestamp("2026-09-15")
    st.write_raw("SHFE", "quotes", d, "json", _fx("shfe", "kx20260915.dat"))
    shfe.ingest_day(d, ["quotes"], st)
    for day in ("2026-09-14", "2026-09-16", "2026-09-17", "2026-09-18"):
        shfe._log_missing(st, shfe.SHFE, pd.Timestamp(day), "quotes", "404", "test")
    assert shfe.load_missing(st, shfe.SHFE) == {
        (x, "quotes") for x in ("2026-09-14", "2026-09-16", "2026-09-17", "2026-09-18")
    }
    counts = shfe.backfill(pd.Timestamp("2026-09-12"), pd.Timestamp("2026-09-20"), ["quotes"], st)
    assert counts == {"written": 0, "exists": 1, "missing": 0, "empty": 0, "error": 0, "skipped": 4}


def test_constants_documented() -> None:
    assert pd.Timestamp("2020-01-01") == shfe.SINGLE_SIDED_FROM
    assert shfe.RECEIPT_HTML_FROM <= shfe.RECEIPT_DAT_UNTIL
    assert {"SC", "LU", "NR", "BC", "EC"} == shfe.INE_SYMBOLS
    assert ine.INE.exchange == "INE" and ine.INE.base_url == "https://www.ine.cn"


# ---------------------------------------------------------------------------------------------
# 与米筐导出对账(需要本地数据)
# ---------------------------------------------------------------------------------------------

RECONCILE_SYMBOLS = ["CU", "AL", "NI", "SN", "AU", "AG", "RB", "RU", "SC"]


def _same(a: pd.Series, b: pd.Series) -> pd.Series:
    """米筐导出为 float32,按相对误差 1e-6 比较;两边都 NaN 也算一致。"""
    x = a.astype(float)
    y = b.astype(float)
    return (x.isna() & y.isna()) | np.isclose(x, y, rtol=1e-6, atol=0)


def _reconcile_symbol(ex: pd.DataFrame, sym: str) -> dict[str, object]:
    rice = pd.read_parquet(RICE / f"{sym}.parquet")
    rice.index = rice.index.set_names(["contract", "date"])
    rice = rice.reset_index()
    rice["date"] = pd.to_datetime(rice["date"])
    mine = ex[ex["symbol"] == sym]
    m = mine.merge(rice, on=["contract", "date"], suffixes=("", "_rq"))
    if m.empty:
        return {"symbol": sym, "n": 0}
    traded = m["volume"].fillna(0) > 0
    ohlc = _same(m["open"], m["open_rq"]) & _same(m["high"], m["high_rq"])
    ohlc &= _same(m["low"], m["low_rq"]) & _same(m["close"], m["close_rq"])
    # 无成交日:交易所 OHLC 为空(本仓库 NaN),米筐用当日结算价填满四个价格
    rq_filled_with_settle = _same(m["close_rq"], m["settle"]) & _same(m["open_rq"], m["settle"])
    # 交易所 VOLUME 偶尔留空(无成交,极少)→ 本仓库 NaN;对账时视为 0
    vol = _same(m["volume"].fillna(0), m["volume_rq"])
    oi = _same(m["open_interest"], m["open_interest_rq"])
    pre = m["date"] < shfe.SINGLE_SIDED_FROM
    # 若米筐是"折算成单边"的口径,2020 年前要用 交易所/2 才对得上;算出来供文档判断
    vol_half = _same(m["volume"] / 2, m["volume_rq"])
    oi_half = _same(m["open_interest"] / 2, m["open_interest_rq"])
    bad = m[(traded & ~ohlc) | ~vol | ~oi]
    samples = [
        {
            "contract": str(r["contract"]),
            "date": str(pd.Timestamp(r["date"]).date()),
            "ex": [r["open"], r["high"], r["low"], r["close"], r["settle"], r["volume"], r["open_interest"]],
            "rq": [
                r["open_rq"],
                r["high_rq"],
                r["low_rq"],
                r["close_rq"],
                None,
                r["volume_rq"],
                r["open_interest_rq"],
            ],
        }
        for _, r in bad.head(8).iterrows()
    ]
    # 只在一边出现的 (合约, 日期):交易所有、米筐没有(米筐到期日之前),或反过来
    key = ["contract", "date"]
    lo, hi = max(mine["date"].min(), rice["date"].min()), min(mine["date"].max(), rice["date"].max())
    rice_in = rice[(rice["date"] >= lo) & (rice["date"] <= hi)]
    mine_in = mine[(mine["date"] >= lo) & (mine["date"] <= hi)]
    ex_only = mine_in.merge(rice_in[key], on=key, how="left", indicator=True)
    rq_only = rice_in.merge(mine_in[key], on=key, how="left", indicator=True)

    def share(x: pd.Series) -> float | None:
        return float(x.mean()) if len(x) else None

    bad_dates = bad.groupby(bad["date"].dt.date).size().sort_values(ascending=False)

    return {
        "symbol": sym,
        "n": int(len(m)),
        "n_traded": int(traded.sum()),
        "date_min": str(m["date"].min().date()),
        "date_max": str(m["date"].max().date()),
        "ohlc_match_all": share(ohlc),
        "ohlc_match_traded": share(ohlc[traded]),
        "untraded_rq_equals_settle": share(rq_filled_with_settle[~traded]),
        "volume_match": share(vol),
        "oi_match": share(oi),
        "volume_match_pre2020": share(vol[pre]),
        "volume_match_post2020": share(vol[~pre]),
        "oi_match_pre2020": share(oi[pre]),
        "oi_match_post2020": share(oi[~pre]),
        "volume_match_if_halved_pre2020": share(vol_half[pre]),
        "oi_match_if_halved_pre2020": share(oi_half[pre]),
        "n_exchange_only": int((ex_only["_merge"] == "left_only").sum()),
        "n_ricequant_only": int((rq_only["_merge"] == "left_only").sum()),
        "ricequant_only_samples": [
            f"{r['contract']}@{pd.Timestamp(r['date']).date()}"
            for _, r in rq_only[rq_only["_merge"] == "left_only"].head(5).iterrows()
        ],
        "n_mismatch": int(len(bad)),
        "mismatch_top_dates": {str(k): int(v) for k, v in bad_dates.head(5).items()},
        "mismatch_samples": samples,
    }


@pytest.mark.skipif(
    not (RICE / "CU.parquet").exists() or not (EXCH / "SHFE" / "quotes").exists(),
    reason="需要本地米筐导出与已回填的交易所行情",
)
def test_reconcile_quotes_with_ricequant() -> None:
    """重叠日期逐合约比较 OHLC / volume / OI;摘要写到 data/exchanges/SHFE/reconcile_ricequant.json 并打印。"""
    st = Store(EXCH)
    ex = pd.concat([st.read_days("SHFE", "quotes"), st.read_days("INE", "quotes")], ignore_index=True)
    ex["date"] = pd.to_datetime(ex["date"])
    results = [_reconcile_symbol(ex, s) for s in RECONCILE_SYMBOLS if (RICE / f"{s}.parquet").exists()]
    out = EXCH / "SHFE" / "reconcile_ricequant.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    cols = ["symbol", "n", "date_min", "date_max", "ohlc_match_traded", "volume_match", "oi_match"]
    print("\n" + pd.DataFrame(results)[cols].to_string(index=False))
    for r in results:
        assert r["n"] > 0, r["symbol"]
        # 2026-09 回填结果:有成交日 OHLC ≥ 99.96%,volume/OI ≥ 99.2%(RU 最低),差异孤立且无系统偏差(见文档)
        assert float(str(r["ohlc_match_traded"])) >= 0.995, r
        assert float(str(r["volume_match"])) >= 0.99, r
        assert float(str(r["oi_match"])) >= 0.99, r
