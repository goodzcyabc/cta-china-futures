"""郑商所期权日行情(cta_research.altdata.czce_options):嵌入真实文件摘录测解析、双边折半、代码规范化(含跨十年)、
可得日、幂等下载;本地有 options_daily.parquet 时检查整表合规与预注册品种覆盖。"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from cta.data.exchanges.base import normalize_contract
from cta_research.altdata import czce_options as co

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "external" / "alt" / "czce_options"
TABLE = DEST / "options_daily.parquet"

# ---------------------------------------------------------------------------------------------
# 嵌入样例(真实文件逐行摘录;汇总行的数值按摘录行重算,以便检查 XX合计 核对)
# ---------------------------------------------------------------------------------------------

HDR_OLD = (
    "品种代码   |昨结算    |今开盘    |最高价    |最低价    |今收盘    |今结算    |涨跌1     |涨跌2     |"
    "成交量(手)|空盘量    |增减量    |成交额(万元)|DELTA     |隐含波动率|行权量"
)
HDR_NEW = (
    "合约代码   |昨结算    |今开盘    |最高价    |最低价    |今收盘    |今结算    |涨跌1     |涨跌2     |"
    "成交量(手)|持仓量    |增减量    |成交额(万元)|DELTA     |隐含波动率|行权量"
)

# OptionDataDaily 2017-04-19(GBK 编码,表头 品种代码/空盘量,双边计数)
SAMPLE_20170419 = "\n".join(
    [
        "\t\t\t\t\t郑州商品交易所期权每日行情表(2017-04-19)",
        HDR_OLD,
        "SR707C6500|242.00    |190.50    |219.50    |190.50    |215.50    |228.00    |-26.50    |-14.00    |190       |170       |170       |39.12       |0.8039    |11.91     |0",
        "SR707P6500|25.50     |17.00     |38.50     |17.00     |22.50     |26.50     |-3.00     |1.00      |202       |80        |80        |5.76        |-0.1938   |11.91     |0",
        "小计       |          |          |          |          |          |          |          |          |392       |250       |250       |44.88       |          |          |0",
        "SR709C6600|267.50    |288.00    |299.50    |250.50    |273.00    |266.00    |5.50      |-1.50     |630       |286       |286       |166.51      |0.6649    |12.31     |0",
        "SR709P6600|91.00     |101.50    |112.00    |81.50     |82.00     |95.50     |-9.00     |4.50      |1,990     |1,034     |1,034     |192.03      |-0.3274   |12.31     |0",
        "小计       |          |          |          |          |          |          |          |          |2,620     |1,320     |1320      |358.54      |          |          |0",
        "SR合计     |          |          |          |          |          |          |          |          |3,012     |1,570     |1570      |403.42      |          |          |0",
        "总计       |          |          |          |          |          |          |          |          |3,012     |1,570     |1570      |403.42      |          |          |0",
        "",
    ]
)

# OptionDataDaily 2019-06-14(UTF-8;CF001 → CF2001 与 CF909 → CF1909 跨十年;双边计数)
SAMPLE_20190614 = "\n".join(
    [
        "\t\t\t\t\t郑州商品交易所期权每日行情表(2019-06-14)",
        HDR_OLD,
        "CF001C12200|1,974.00  |0.00      |0.00      |0.00      |0.00      |1,986.00  |12.00     |12.00     |0         |24        |0         |0.00        |0.8422    |21.42     |0",
        "CF001P12200|182.00    |0.00      |0.00      |0.00      |0.00      |173.00    |-9.00     |-9.00     |0         |326       |0         |0.00        |-0.1500   |21.42     |0",
        "CF909C14000|259.00    |265.00    |308.00    |238.00    |241.00    |268.00    |-18.00    |9.00      |1,058     |2,306     |-190      |138.65      |0.3499    |23.41     |0",
        "CF909P14000|782.00    |765.00    |845.00    |765.00    |815.00    |781.00    |33.00     |-1.00     |294       |818       |-54       |117.51      |-0.6459   |23.41     |0",
        "CF合计     |          |          |          |          |          |          |          |          |1,352     |3,474     |-244      |256.16      |          |          |0",
        "SR001C5000|295.50    |322.00    |326.50    |307.00    |314.50    |313.50    |19.00     |18.00     |314       |4,334     |22        |99.14       |0.6180    |16.71     |0",
        "SR001P5000|170.00    |159.50    |167.00    |159.00    |167.00    |161.50    |-3.00     |-8.50     |92        |1,574     |-68       |14.95       |-0.3683   |16.71     |0",
        "SR合计     |          |          |          |          |          |          |          |          |406       |5,908     |-46       |114.09      |          |          |0",
        "总计       |          |          |          |          |          |          |          |          |1,758     |9,382     |-290      |370.25      |          |          |0",
        "",
    ]
)

# OptionDataDaily 2019-12-16(MA/TA 期权上市首日;MA005 → MA2005)
SAMPLE_20191216 = "\n".join(
    [
        "\t\t\t\t\t郑州商品交易所期权每日行情表(2019-12-16)",
        HDR_OLD,
        "MA005C2100|106.50    |116.00    |116.00    |94.50     |99.50     |102.50    |-7.00     |-4.00     |538       |316       |316       |54.84       |0.5622    |19.49     |0",
        "TA005P4800|91.50     |90.00     |99.50     |76.50     |79.00     |90.50     |-12.50    |-1.00     |1,348     |478       |478       |57.31       |-0.3330   |14.55     |0",
        "",
    ]
)

# OptionDataDaily 2026-09-30(UTF-8,表头 合约代码/持仓量,单边;含序列期权 MS 与 3 位执行价;行尾填充空格)
SAMPLE_20260930 = "\n".join(
    [
        "\t\t\t\t\t郑州商品交易所期权每日行情表(2026-09-30)",
        HDR_NEW,
        "SR611C5500|6.50      |2.50      |3.50      |1.50      |2.00      |4.00      |-4.50     |-2.50     |5,347     |26,106    |567       |11.23       |0.0513    |18.81     |0             ",
        "小计      |          |          |          |          |          |          |          |          |5,347     |26,106    |567       |11.23       |          |          |0             ",
        "SR701C4900|448.50    |436.00    |461.50    |426.50    |452.00    |467.00    |3.50      |18.50     |1,022     |1,423     |66        |449.01      |0.8570    |18.60     |0             ",
        "SR701P4900|5.50      |6.50      |7.50      |5.00      |5.00      |33.00     |-0.50     |27.50     |1,033     |3,081     |305       |7.23        |-0.1403   |18.60     |0             ",
        "SR701MSC4900|445.00    |433.00    |459.00    |421.00    |446.50    |437.50    |1.50      |-7.50     |269       |172       |73        |117.22      |0.9779    |12.80     |0             ",
        "SR701MSP4900|1.50      |1.50      |1.50      |1.50      |1.50      |2.00      |0.00      |0.50      |176       |570       |-45       |0.28        |-0.0230   |12.80     |0             ",
        "小计      |          |          |          |          |          |          |          |          |2,500     |5,246     |399       |573.74      |          |          |0             ",
        "SR合计    |          |          |          |          |          |          |          |          |7,847     |31,352    |966       |584.97      |          |          |0             ",
        "ZC612P990 |198.50    |0.00      |0.00      |0.00      |0.00      |198.10    |-0.40     |-0.40     |0         |0         |0         |0.00        |-0.8559   |53.93     |0             ",
        "小计      |          |          |          |          |          |          |          |          |0         |0         |0         |0.00        |          |          |0             ",
        "ZC合计    |          |          |          |          |          |          |          |          |0         |0         |0         |0.00        |          |          |0             ",
        "总计      |          |          |          |          |          |          |          |          |7,847     |31,352    |966       |584.97      |          |          |0             ",
    ]
)

# 期权上市前的占位文件(2017-04-18,GBK):标题 + 表头 + 无交易记录
SAMPLE_20170418 = "\t\t\t\t\t郑州商品交易所期权每日行情表(2017-04-18)\n" + HDR_OLD + "\n无交易记录！\n"

# 年度文件 SROPTIONS2023(首列 交易日期)
SAMPLE_ANNUAL_2023 = "\n".join(
    [
        "交易日期  |" + HDR_NEW,
        "2023-06-15|SR309C5100|1,842.00  |1,892.00  |1,899.50  |1,877.50  |1,886.00  |1,885.50  |44.00     |43.50     |34        |141       |0         |64.07       |0.9956    |36.77     |0                              ",
        "2023-06-15|SR309C5200|1,742.50  |1,786.00  |1,787.00  |1,784.50  |1,784.50  |1,786.00  |42.00     |43.50     |15        |101       |3         |26.79       |0.9933    |35.64     |0                              ",
        "",
    ]
)


def _day(text: str, d: str, encoding: str = "utf-8") -> co.DayFile:
    return co.parse_daily_bytes(
        text.encode(encoding), pd.Timestamp(d), "raw/x.txt.gz", "2025-06-30T08:10:37Z"
    )


# ---------------------------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------------------------


def test_parse_2017_gbk_old_header() -> None:
    day = _day(SAMPLE_20170419, "2017-04-19", "gb18030")
    t = day.table
    assert day.info["encoding"] == "gb18030"
    assert day.info["title_date"] == "2017-04-19"
    assert day.info["header_fields"].split("|")[:1] == ["option_code"]
    assert "oi" in day.info["header_fields"].split("|")  # 空盘量 → oi
    assert list(t.columns) == co.OUT_COLUMNS
    assert len(t) == 4 and day.info["n_aggregate_rows"] == 4  # 两个小计 + SR合计 + 总计 剔除
    assert day.info["total_check_mismatch"] == ""
    r = t.set_index("option_code").loc["SR709P6600"]
    assert r["product"] == "SR" and r["underlying"] == "SR1709" and r["cp"] == "P"
    assert r["strike"] == 6600.0 and r["settle"] == 95.5 and r["close"] == 82.0
    assert r["delta"] == pytest.approx(-0.3274)
    assert r["iv_exchange"] == pytest.approx(0.1231)
    assert r["volume_raw"] == 1990.0 and r["oi_raw"] == 1034.0
    assert r["turnover_raw"] == pytest.approx(1_920_300.0)
    assert not bool(r["is_serial"])
    assert r["exchange"] == "CZCE" and pd.isna(r["expire_date"])
    assert r["source_file"] == "raw/x.txt.gz" and r["last_modified_utc"] == "2025-06-30T08:10:37Z"
    assert r["update_date"] == ""


def test_parse_2026_new_header_serial_and_series_sums() -> None:
    day = _day(SAMPLE_20260930, "2026-09-30")
    t = day.table.set_index("option_code")
    assert day.info["encoding"] == "utf-8"
    assert len(t) == 6 and day.info["n_serial_rows"] == 2
    assert day.info["total_check_mismatch"] == ""
    assert bool(t.at["SR701MSC4900", "is_serial"]) and not bool(t.at["SR701C4900", "is_serial"])
    assert t.at["SR701MSC4900", "underlying"] == "SR2701" and t.at["SR701MSC4900", "cp"] == "C"
    assert t.at["SR701MSP4900", "strike"] == 4900.0
    assert t.at["ZC612P990", "strike"] == 990.0 and t.at["ZC612P990", "underlying"] == "ZC2612"
    # 2026 单边:不折半
    assert t.at["SR701C4900", "volume"] == 1022.0 == t.at["SR701C4900", "volume_raw"]
    assert t.at["SR701C4900", "turnover"] == pytest.approx(4_490_100.0)
    # 系列合计只计常规期权,同一 (date, underlying) 的行(含序列期权)取同一值
    reg_vol, reg_oi = 1022.0 + 1033.0, 1423.0 + 3081.0
    for code in ("SR701C4900", "SR701P4900", "SR701MSC4900", "SR701MSP4900"):
        assert t.at[code, "series_volume"] == reg_vol and t.at[code, "series_oi"] == reg_oi
    assert t.at["SR611C5500", "series_volume"] == 5347.0 and t.at["SR611C5500", "series_oi"] == 26106.0
    assert t.at["ZC612P990", "series_volume"] == 0.0
    # 未成交合约 close 按原样(0)保留
    assert t.at["ZC612P990", "close"] == 0.0 and t.at["ZC612P990", "volume"] == 0.0


def test_parse_placeholder_and_title_mismatch() -> None:
    empty = _day(SAMPLE_20170418, "2017-04-18", "gb18030")
    assert len(empty.table) == 0 and empty.info["n_option_rows"] == 0
    with pytest.raises(co.ParseError):
        _day(SAMPLE_20260930, "2026-09-29")  # 标题日期与文件日期不符


def test_parse_rejects_unknown_code_and_header() -> None:
    bad_code = SAMPLE_20260930.replace("SR611C5500", "SR611X5500")
    with pytest.raises(co.ParseError):
        _day(bad_code, "2026-09-30")
    bad_hdr = SAMPLE_20260930.replace("隐含波动率", "神秘列")
    with pytest.raises(co.ParseError):
        _day(bad_hdr, "2026-09-30")


def test_option_code_regex_variants() -> None:
    for code, want in [
        ("SR707C6200", ("SR", "707", None, "C", "6200")),
        ("SR701MSC4900", ("SR", "701", "MS", "C", "4900")),
        ("SR701-C-5000", ("SR", "701", None, "C", "5000")),
        ("ZC612P990", ("ZC", "612", None, "P", "990")),
    ]:
        m = co.OPT_RE.match(code)
        assert m is not None and m.groups() == want


def test_parse_annual_format() -> None:
    pt = co.parse_table(SAMPLE_ANNUAL_2023)
    assert list(pt.rows["trade_date"]) == ["2023-06-15", "2023-06-15"]
    std = co.standardize(pt.rows, pd.to_datetime(pt.rows["trade_date"]))
    assert list(std["underlying"]) == ["SR2309", "SR2309"]
    assert list(std["settle"]) == [1885.5, 1786.0]
    assert std["iv_exchange"].tolist() == pytest.approx([0.3677, 0.3564])


# ---------------------------------------------------------------------------------------------
# 双边折半
# ---------------------------------------------------------------------------------------------


def test_double_sided_halving_before_2020() -> None:
    old = _day(SAMPLE_20190614, "2019-06-14").table.set_index("option_code")
    r = old.loc["CF909C14000"]
    assert r["volume_raw"] == 1058.0 and r["volume"] == 529.0
    assert r["oi_raw"] == 2306.0 and r["oi"] == 1153.0
    assert r["turnover_raw"] == pytest.approx(1_386_500.0) and r["turnover"] == pytest.approx(693_250.0)
    # 系列合计用折半后的单边值
    assert r["series_volume"] == (1058.0 + 294.0) / 2 and r["series_oi"] == (2306.0 + 818.0) / 2
    assert co.is_double_sided(pd.Timestamp("2019-12-31"))
    assert not co.is_double_sided(pd.Timestamp("2020-01-01"))
    new = _day(SAMPLE_20260930, "2026-09-30").table
    assert (new["volume"] == new["volume_raw"]).all() and (new["oi"] == new["oi_raw"]).all()


# ---------------------------------------------------------------------------------------------
# 合约代码规范化(郑商所 3 位年月 → 4 位,含跨十年)
# ---------------------------------------------------------------------------------------------


def test_contract_normalization_decade() -> None:
    t = _day(SAMPLE_20190614, "2019-06-14").table.set_index("option_code")
    assert t.at["CF001C12200", "underlying"] == "CF2001"  # 2019 年文件里的 0 → 2020
    assert t.at["CF909C14000", "underlying"] == "CF1909"
    assert t.at["SR001P5000", "underlying"] == "SR2001"
    t2 = _day(SAMPLE_20191216, "2019-12-16").table.set_index("option_code")
    assert t2.at["MA005C2100", "underlying"] == "MA2005" and t2.at["TA005P4800", "underlying"] == "TA2005"
    t3 = _day(SAMPLE_20170419, "2017-04-19", "gb18030").table
    assert set(t3["underlying"]) == {"SR1707", "SR1709"}
    # 下一个十年边界:2029-11 的文件里 SR001 → SR3001,SR911 → SR2911
    assert normalize_contract("SR001", "CZCE", pd.Timestamp("2029-11-15")) == "SR3001"
    assert normalize_contract("SR911", "CZCE", pd.Timestamp("2029-11-15")) == "SR2911"
    assert normalize_contract("SR001", "CZCE", pd.Timestamp("2030-01-02")) == "SR3001"


def test_underlying_month_sanity_guard() -> None:
    pt = co.parse_table(SAMPLE_ANNUAL_2023)
    with pytest.raises(co.ParseError):  # 标的月份早于交易日(SR309 在 2023-10 的行)→ 视为解析错误
        co.standardize(pt.rows, pd.Timestamp("2023-10-09"))


# ---------------------------------------------------------------------------------------------
# 可得日
# ---------------------------------------------------------------------------------------------


def test_available_day_rule() -> None:
    cal = pd.DatetimeIndex(
        ["2024-09-26", "2024-09-27", "2024-10-08", "2026-09-28", "2026-09-29", "2026-09-30"]
    )
    hol = {pd.Timestamp(x) for x in ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]}
    dates = [pd.Timestamp(x) for x in ["2024-09-26", "2024-09-27", "2026-09-29", "2026-09-30"]]
    m = co.available_day_map(dates, cal, hol)
    assert m[pd.Timestamp("2024-09-26")] == pd.Timestamp("2024-09-27")
    assert m[pd.Timestamp("2024-09-27")] == pd.Timestamp("2024-10-08")  # 跨国庆长假
    assert m[pd.Timestamp("2026-09-29")] == pd.Timestamp("2026-09-30")
    assert m[pd.Timestamp("2026-09-30")] == pd.Timestamp("2026-10-08")  # 超出日历末端:工作日 − 公告假期
    assert all(v > k for k, v in m.items())


def _write_raw(dest: Path, d: str, text: str, encoding: str = "utf-8") -> None:
    body = text.encode(encoding)
    ts = pd.Timestamp(d)
    f, m = co.raw_file(dest, ts), co.meta_file(dest, ts)
    f.parent.mkdir(parents=True, exist_ok=True)
    gz = gzip.compress(body, mtime=0)
    f.write_bytes(gz)
    meta = {
        "url": co.daily_url(ts),
        "http_status": 200,
        "size": len(body),
        "stored_size": len(gz),
        "sha256": hashlib.sha256(body).hexdigest(),
        "last_modified_utc": "2025-06-30T08:10:37Z",
        "encoding": encoding,
    }
    m.write_text(json.dumps(meta), encoding="utf-8")


def test_build_uses_futures_calendar_union_option_dates(tmp_path: Path) -> None:
    dest = tmp_path / "czce_options"
    _write_raw(dest, "2019-06-14", SAMPLE_20190614)
    _write_raw(dest, "2019-12-16", SAMPLE_20191216)
    _write_raw(dest, "2026-09-30", SAMPLE_20260930)
    quotes = tmp_path / "exchanges"
    (quotes / "CZCE").mkdir(parents=True)
    # 期货日历故意缺 2019-12-16(期权文件日期补进日历),并在 2019-06-14 后跳到 2019-06-17(周末)
    pd.DataFrame(
        {"date": pd.to_datetime(["2019-06-14", "2019-06-17", "2019-12-13", "2019-12-17", "2026-09-30"])}
    ).to_parquet(quotes / "CZCE" / "quotes_all.parquet")
    hol = tmp_path / "holidays.csv"
    hol.write_text("date,name\n2026-10-01,a\n2026-10-02,a\n2026-10-05,a\n2026-10-06,a\n2026-10-07,a\n")
    df = co.build(dest, quotes_root=quotes, holidays_path=hol)
    got = df.groupby("date")["available_day"].first()
    assert got[pd.Timestamp("2019-06-14")] == pd.Timestamp("2019-06-17")
    assert got[pd.Timestamp("2019-12-16")] == pd.Timestamp("2019-12-17")
    assert got[pd.Timestamp("2026-09-30")] == pd.Timestamp("2026-10-08")
    assert list(df.columns) == co.OUT_COLUMNS
    assert (dest / "options_daily.parquet").exists() and (dest / "files.csv").exists()
    files = pd.read_csv(dest / "files.csv")
    assert set(files["status"]) == {"ok"} and files["n_option_rows"].sum() == len(df)


# ---------------------------------------------------------------------------------------------
# 下载幂等(假客户端,不联网)
# ---------------------------------------------------------------------------------------------


class _FakeClient:
    calls: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.bytes_on_wire = 0

    def get(self, path: str, valid: Any, extra_headers: Any = None) -> co.Response:
        _FakeClient.calls.append(path)
        if "20260925" in path:
            return co.Response(404, b"", {})
        day = pd.Timestamp(path.split("/")[-2]).strftime("%Y-%m-%d")
        body = SAMPLE_20260930.replace("2026-09-30", day).encode()
        return co.Response(200, body, {"last-modified": "Wed, 30 Sep 2026 08:05:38 GMT"})

    def close(self) -> None:
        pass


def test_fetch_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(co, "Client", _FakeClient)
    monkeypatch.setattr(co, "futures_calendar", lambda *a, **k: pd.DatetimeIndex([]))
    _FakeClient.calls = []
    co.fetch(tmp_path, "2026-09-24", "2026-09-30")
    assert len(_FakeClient.calls) == 5  # 周四、周五(404)、周一至周三;周末不请求
    meta = json.loads(co.meta_file(tmp_path, pd.Timestamp("2026-09-30")).read_text())
    assert meta["last_modified_utc"] == "2026-09-30T08:05:38Z" and meta["http_status"] == 200
    assert co.file_present(tmp_path, pd.Timestamp("2026-09-28"))
    _FakeClient.calls = []
    co.fetch(tmp_path, "2026-09-24", "2026-09-30")
    assert _FakeClient.calls == []  # 已有文件与已确认的 404 都不再请求


# ---------------------------------------------------------------------------------------------
# 真实数据(本地有整表时)
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real() -> pd.DataFrame:
    if not TABLE.exists():
        pytest.skip(f"需要 {TABLE}")
    return pd.read_parquet(TABLE)


def test_real_table_contract(real: pd.DataFrame) -> None:
    df = real
    assert list(df.columns) == co.OUT_COLUMNS
    assert str(df["date"].dtype).startswith("datetime64") and str(df["available_day"].dtype).startswith(
        "datetime64"
    )
    assert not df.duplicated(["date", "option_code"]).any()
    assert (df["available_day"] > df["date"]).all()
    puts = df[df["cp"] == "P"]
    assert (puts["delta"].dropna() <= 0).all()
    calls = df[df["cp"] == "C"]
    assert (calls["delta"].dropna() >= 0).all()
    iv = df["iv_exchange"]
    assert (iv.dropna() > 0).all()
    assert df["iv_exchange"].isna().mean() < 0.001
    # 预注册品种全部在 (0, 3);全表唯一例外是 2021-10-11 动力煤 ZC111 深度虚值(煤价暴涨期,交易所公布 3.0–3.18),按原样保留
    pre = df["product"].isin(list(co.LISTING))
    assert ((iv[pre] > 0) & (iv[pre] < 3)).all()
    over = df[iv >= 3]
    assert set(over["product"]) <= {"ZC"} and set(over["date"]) <= {pd.Timestamp("2021-10-11")}
    assert (iv < 3.2).all()
    assert set(df["cp"]) == {"C", "P"} and (df["exchange"] == "CZCE").all()
    assert df["expire_date"].isna().all()
    pre = df["date"] < pd.Timestamp("2020-01-01")
    assert np.allclose(df.loc[pre, "volume"] * 2, df.loc[pre, "volume_raw"])
    assert np.allclose(df.loc[~pre, "oi"], df.loc[~pre, "oi_raw"])
    # 同一 (date, underlying) 的系列合计唯一
    assert (df.groupby(["date", "underlying"])["series_oi"].nunique(dropna=False) == 1).all()


def test_real_coverage_from_listing(real: pd.DataFrame) -> None:
    q = pd.read_parquet(
        ROOT / "data" / "exchanges" / "CZCE" / "quotes_all.parquet", columns=["date", "contract"]
    )
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(q["date"]).unique()))
    last = real["date"].max()
    for sym, listing in co.LISTING.items():
        g = real[real["product"] == sym]
        days = pd.DatetimeIndex(sorted(g["date"].unique()))
        assert days[0] == pd.Timestamp(listing), sym
        expected = cal[(cal >= pd.Timestamp(listing)) & (cal <= last)]
        assert len(expected.difference(days)) == 0, (sym, list(expected.difference(days))[:5])
    # 预注册品种的标的都能在项目期货行情里找到(同日同合约)
    pre = real[real["product"].isin(list(co.LISTING))][["date", "underlying"]].drop_duplicates()
    have = set(zip(pd.to_datetime(q["date"]), q["contract"]))
    found = [(d, u) in have for d, u in zip(pre["date"], pre["underlying"])]
    assert np.mean(found) == 1.0
