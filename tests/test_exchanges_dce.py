"""大商所模块:解析器(离线截断样例)、missing.log/断点续跑、CLI 参数、与米筐对账(有数据才跑)。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges import dce
from cta.data.exchanges.base import POSITION_COLS, QUOTE_COLS, RECEIPT_COLS, Store, validate

FIX = Path(__file__).parent / "fixtures" / "exchanges" / "dce"


def test_parse_quotes_fixture() -> None:
    raw = (FIX / "quotes_20260916.json").read_bytes()
    df = dce.parse_quotes(raw, pd.Timestamp("2026-09-16"))
    assert list(df.columns) == QUOTE_COLS
    # 小计/总计 行和月均价期货(l2610F)剔除;合约代码大写
    assert "l2610F" not in set(df["contract"]) and not any("小计" in str(c) for c in df["contract"])
    assert {"C2701", "JD2609", "BB2707"} <= set(df["contract"])
    assert set(df["symbol"]) == {"C", "JD", "BB"}
    jd = df.set_index("contract").loc["JD2609"]
    assert jd["open"] == 4197 and jd["settle"] == 4146 and jd["prev_settle"] == 4134
    assert jd["volume"] == 35 and jd["open_interest"] == 507
    assert jd["turnover"] == pytest.approx(145.12 * 1e4)  # 万元 → 元
    out = validate("quotes", df)  # 无成交合约 OHLC → NaN,settle 仍 > 0
    bb = out.set_index("contract").loc["BB2707"]
    assert np.isnan(bb["open"]) and bb["settle"] > 0
    assert (out["settle"] > 0).all()


def test_parse_positions_fixture() -> None:
    raw = (FIX / "positions_20260915.zip").read_bytes()
    df = dce.parse_positions(raw, pd.Timestamp("2026-09-15"))
    assert list(df.columns) == POSITION_COLS
    assert set(df["contract"]) == {"C2701"}  # b2705 是空表 → 整体略去
    ranked = df[~df["is_total"]]
    assert list(ranked["rank"]) == list(range(1, 21))
    r1 = ranked.set_index("rank").loc[1]
    assert r1["member_vol"] == "东证期货（代客）" and r1["vol"] == 79492 and r1["vol_chg"] == -477
    assert r1["member_long"] == "中粮期货（代客）" and r1["long_oi"] == 91993 and r1["long_chg"] == 2417
    assert r1["member_short"] == "新湖期货（代客）" and r1["short_oi"] == 89616 and r1["short_chg"] == 2705
    tot = df[df["is_total"]]
    assert len(tot) == 1 and int(tot["rank"].iloc[0]) == 0
    assert (
        tot["vol"].iloc[0] == 345570
        and tot["long_oi"].iloc[0] == 475536
        and tot["short_oi"].iloc[0] == 487548
    )
    assert tot["vol_chg"].iloc[0] == -23985
    validate("positions", df)


def test_parse_receipts_fixture() -> None:
    raw = (FIX / "receipts_20260915.json").read_bytes()
    df = dce.parse_receipts(raw, pd.Timestamp("2026-09-15"))
    assert list(df.columns) == RECEIPT_COLS
    # 分库(variety 为空)、品种小计行(whAbbr 为空)、交易所总计行(varietyOrder 为空)均略去
    assert "中粮五大连池" not in set(df["warehouse"]) and "北良港主库区" not in set(df["warehouse"])
    a = df[(df["symbol"] == "A") & ~df["is_total"]]
    assert list(a["warehouse"]) == ["中粮贸易"] and a["receipts"].iloc[0] == 4855  # 仓库组行含分库数量
    jm = df[df["symbol"] == "JM"]
    assert set(jm.loc[~jm["is_total"], "warehouse"]) == {"中铝国贸", "博金煤业", "海南浩通"}
    assert jm.loc[jm["is_total"], "receipts"].iloc[0] == 100 + 38 + 1336  # 与交易所自己的小计行 1474 一致
    assert jm.loc[jm["is_total"], "warehouse"].iloc[0] == "合计"
    m = df[(df["symbol"] == "M") & ~df["is_total"]]
    assert len(m) == 2 and m["receipts"].sum() == 3300 + 2800
    validate("receipts", df)


def test_missing_log_roundtrip_and_resume(tmp_path: Path) -> None:
    st = Store(tmp_path)
    d = pd.Timestamp("2026-01-01")
    dce.record_missing(st, d, "*", "holiday")
    dce.record_missing(st, pd.Timestamp("2016-01-04"), "positions", "empty:before-history-start-2020-07-20")
    dce.record_missing(st, pd.Timestamp("2026-09-15"), "receipts", "error:DceError:timeout")
    known = dce.load_missing(st)
    assert dce._is_final_missing(known, d, "quotes") and dce._is_final_missing(known, d, "receipts")
    assert dce._is_final_missing(known, pd.Timestamp("2016-01-04"), "positions")
    assert not dce._is_final_missing(known, pd.Timestamp("2026-09-15"), "receipts")  # error 条目下次重试
    assert not dce._is_final_missing(known, pd.Timestamp("2026-09-16"), "quotes")


def test_ingest_day_uses_stored_raw_without_network(tmp_path: Path) -> None:
    st = Store(tmp_path)
    d = pd.Timestamp("2026-09-16")
    st.write_raw("DCE", "quotes", d, "json", (FIX / "quotes_20260916.json").read_bytes())
    sess = dce.CdpSession()  # 未 open,任何联网都会抛错 → 证明走的是 raw
    assert dce.ingest_day(d, "quotes", sess, st) == "written"
    assert dce.ingest_day(d, "quotes", sess, st) == "exists"
    back = st.read_days("DCE", "quotes")
    assert len(back) == len(dce.parse_quotes((FIX / "quotes_20260916.json").read_bytes(), d))
    assert dce.reparse_day(d, "quotes", st) == "written"


def test_volume_factor_vs_ricecta() -> None:
    dates = pd.Series(pd.to_datetime(["2019-12-31", "2020-01-02", "2025-01-02"]))
    assert list(dce.volume_factor_vs_ricecta(dates)) == [2.0, 1.0, 1.0]
    assert pd.Timestamp("2020-01-02") == dce.SINGLE_SIDED_SINCE
    assert dce.JD_MULTIPLIER == 10


def test_cli_parser() -> None:
    p = dce.build_parser()
    a = p.parse_args(
        ["backfill", "--start", "2016-01-04", "--end", "2026-09-16", "--kinds", "quotes,positions,receipts"]
    )
    assert a.cmd == "backfill" and a.kinds == ["quotes", "positions", "receipts"]
    with pytest.raises(SystemExit):
        p.parse_args(["backfill", "--start", "2016-01-04", "--kinds", "quotes,foo"])


_STORE = Store()
_RQ = _STORE.root.parent / "ricecta" / "data" / "contracts_daily"
_HAVE_DATA = bool(_STORE.days("DCE", "quotes")) and (_RQ / "C.parquet").exists()


@pytest.mark.skipif(not _HAVE_DATA, reason="需要已回填的 DCE 行情和米筐导出")
def test_reconcile_with_ricecta() -> None:
    symbols = ["C", "M", "Y", "P", "JD", "V", "J", "I"]
    summary, samples = dce.reconcile_with_ricecta(symbols, _STORE, _RQ)
    assert set(summary["symbol"]) == set(symbols)
    got = summary[summary["n"] > 0]
    assert not got.empty
    # 价格逐合约逐日一致;成交量/持仓量按口径折算(2020-01-02 前 ×2)后一致。
    # 剩余 <1% 的不一致集中在交割月(交易所重述后最后交易日 OI=0 等)和米筐个别日期数值偏小(与交易所年度包核对为米筐侧),见 docs。
    assert (got["ohlc_match"] >= 0.999).all(), summary.to_string()
    assert (got["volume_match"] >= 0.99).all(), summary.to_string()
    assert (got["oi_match"] >= 0.99).all(), summary.to_string()


_PKG = _STORE.root / "DCE" / dce.YEARLY_PACKAGE_DIR


@pytest.mark.skipif(not (_HAVE_DATA and _PKG.exists()), reason="需要已回填的 DCE 行情和年度打包")
def test_crosscheck_yearly_packages_double_sided() -> None:
    """交易所年度打包(双边)= 接口(单边)× 2,价格完全一致;只抽最早、最晚两年以控制耗时。"""
    years = sorted(int(p.name.split("_")[0]) for p in _PKG.glob("*_allVarietyFtr.zip"))
    res = dce.crosscheck_yearly_packages(_STORE, years=[years[0], years[-1]])
    assert len(res) == 2, res.to_string()
    # 年度包是下载时刻的快照;store 之后每天增量追加,所以只要求"包里的每一行都在 store 里且一致"
    assert (res["n_both"] == res["n_package"]).all(), res.to_string()
    for c in ("ohlc_match", "settle_match", "volume_x2_match", "oi_x2_match", "turnover_x2_match"):
        assert (res[c] >= 0.9999).all(), res.to_string()
