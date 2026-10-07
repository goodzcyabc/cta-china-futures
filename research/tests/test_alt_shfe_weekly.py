"""上期所库存周报(cta_research.altdata.shfe_weekly):嵌入样例测 JSON/HTML 解析、可得规则、幂等下载;有本地数据时测整表合规。"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from cta_research.altdata import shfe_weekly as sw

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "external" / "alt" / "shfe_weekly"
OBS = DEST / "observations.csv"

# ---------------------------------------------------------------------------------------------
# 嵌入样例
# ---------------------------------------------------------------------------------------------


def _row(
    varname: str, wh: str, spot: Any, wrt: Any, cap: Any, pspot: Any, pwrt: Any, pcap: Any, **extra: Any
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "VARNAME": varname,
        "WHABBRNAME": wh,
        "SPOTWGHTS": spot,
        "WRTWGHTS": wrt,
        "WHSTOCKS": cap,
        "PRESPOTWGHTS": pspot,
        "PREWRTWGHTS": pwrt,
        "PREWHSTOCKS": pcap,
        "WGHTUNIT": "2",
        "REGNAME": "",
    }
    d.update(extra)
    return d


def _json_sample(with_varid: bool = True, drop_cu_total: bool = False) -> bytes:
    """仿 2025 年格式:铜有 保税/完税/总计 三行,天然橡胶只有 总计,螺纹钢小计为空,铜(BC)/氧化铝 不应命中。"""

    def vid(s: str) -> dict[str, Any]:
        return {"VARID": s} if with_varid else {}

    rows = [
        _row("铜$$COPPER", "中储吴淞$$Zhongchu Wusong", 20602, 25, 144575, 18626, 25, 144575, **vid("cu")),
        _row("铜$$COPPER", "合计$$Subtotal", 20602, 25, 144575, 18626, 25, 144575, **vid("cu")),
        _row("铜$$COPPER", "保税商品总计$$Total (Bonded)", 18, 0, 30000, 18, 0, 30000, **vid("cu")),
        _row(
            "铜$$COPPER",
            "完税商品总计$$Total (Tax included)",
            94036,
            25560,
            943040,
            81833,
            18927,
            949673,
            **vid("cu"),
        ),
        _row("铜$$COPPER", "总计$$Total", 94054, 25560, 973040, 81851, 18927, 979673, **vid("cu")),
        _row(
            "氧化铝(仓库)$$Aluminium Oxide Warehouse",
            "总计$$Total",
            165272,
            138692,
            691308,
            130104,
            112306,
            717694,
            **vid("ao"),
        ),
        _row("铜(BC)$$Copper (BC)", "总计$$Total", 999, 1, 2, 3, 4, 5, **vid("bc")),
        _row(
            "天然橡胶$$NATURAL RUBBER",
            "总计$$Total",
            "191,948",
            "151740",
            506260,
            205360,
            162230,
            495770,
            **vid("ru"),
        ),
        _row(
            "螺纹钢(仓库)$$Rebar Warehouse",
            "总计$$Total",
            "",
            251649,
            580536,
            "",
            230131,
            602054,
            **vid("rb"),
        ),
        _row("锡$$TIN", "总计$$Total", 7897, 7326, 27674, 7773, 7397, 27603, **vid("sn")),
    ]
    if drop_cu_total:
        rows = [
            r for r in rows if not (r["VARNAME"].startswith("铜$$") and r["WHABBRNAME"].startswith("总计"))
        ]
    doc = {
        "o_cursor": rows,
        "o_code": "0000",
        "o_msg": "查询成功",
        "report_date": "20250912",
        "o_tradingday": "20250912",
        "update_date": "20250912 16:31:03",
    }
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def _url_date(url: str) -> str:
    m = re.search(r"(\d{8})weeklystock", url)
    return m.group(1) if m else ""


def _html_table(name: str, total_rows: list[tuple[str, list[str]]]) -> str:
    head = (
        '<table class="el-table_table"><thead class="is-group has-gutter"><tr>'
        '<th class="is-center is-leaf el-table__cell"><div class="cell">地区</div></th></tr></thead>'
        '<tr class="el-table__row special_row_type"><td colspan="10" style="text-align: left;">'
        f'<div class="cell">{name}</div></td><td><div class="cell">单位：吨</div></td></tr>'
        '<tr class="el-table__row tdBorder"><td>上海</td><td class="is-center el-table__cell">某库</td>'
        "<td>1</td><td>2</td><td>3</td><td>4</td><td>5</td><td>6</td><td>7</td><td>8</td><td>9</td></tr>"
    )
    body = ""
    for label, nums in total_rows:
        cells = "".join(f"<td>{x}</td>" for x in nums)
        body += f'<tr class="el-table__row isTotal tdBorder"><td colspan="2">{label}</td>{cells}</tr>'
    return head + body + "</table>"


def _html_sample(report_date: str = "2025-10-31") -> bytes:
    intro = (
        '<html lang="zh-CN"><body><div class="comtent_table" id="stock"><table class="content_intro">'
        f"<tr><td>{report_date} 2025年 第(44)期,总第1358期</td></tr></table>"
    )
    cu = _html_table(
        "铜",
        [
            ("合计", ["1", "1", "1", "1", "0", "0", "1", "1", "0"]),
            ("保税商品总计", ["18", "0", "18", "0", "0", "0", "30000", "30000", "0"]),
            (
                "完税商品总计",
                ["104774", "35071", "116122", "39710", "11348", "4639", "923529", "918890", "-4639"],
            ),
            ("总计", ["104792", "35071", "116140", "39710", "11348", "4639", "953529", "948890", "-4639"]),
        ],
    )
    bc = _html_table("铜(BC)", [("总计", ["9", "9", "9", "9", "0", "0", "9", "9", "0"])])
    ru = _html_table(
        "天然橡胶",
        [("总计", ["163450", "124020", "162,025", "120900", "-1425", "-3120", "528980", "537100", "8120"])],
    )
    rb = _html_table("螺纹钢(仓库)", [("总计", ["", "1", "", "2", "", "1", "3", "4", "1"])])
    return (intro + cu + bc + ru + rb + "</div></body></html>").encode("utf-8")


# ---------------------------------------------------------------------------------------------
# (a) 解析
# ---------------------------------------------------------------------------------------------


def test_parse_json_totals_and_products() -> None:
    recs = {r.symbol: r for r in sw.parse_json(_json_sample(), date(2025, 9, 12))}
    assert set(recs) == {"CU", "RU", "SN"}  # 氧化铝/铜(BC)/螺纹钢 不命中,铝/镍 缺席
    cu = recs["CU"]
    assert (cu.total, cu.warrant, cu.capacity) == (94054.0, 25560.0, 973040.0)
    assert cu.off_warrant == 94054.0 - 25560.0
    assert (cu.prev_total, cu.prev_warrant, cu.prev_capacity) == (81851.0, 18927.0, 979673.0)
    assert (cu.bonded_total, cu.bonded_warrant) == (18.0, 0.0)
    assert (cu.dutypaid_total, cu.dutypaid_warrant) == (94036.0, 25560.0)
    assert cu.source_format == "json" and cu.update_date == "20250912 16:31:03"
    ru = recs["RU"]
    assert (ru.total, ru.warrant) == (191948.0, 151740.0)  # 字符串/千分位
    assert ru.bonded_total is None and ru.dutypaid_total is None
    assert recs["SN"].off_warrant == 571.0


def test_parse_json_without_varid_uses_varname() -> None:
    """2014–2015 的文件没有 VARID,只能靠 VARNAME 中文部分精确匹配。"""
    recs = {r.symbol: r for r in sw.parse_json(_json_sample(with_varid=False), date(2025, 9, 12))}
    assert set(recs) == {"CU", "RU", "SN"}
    assert recs["CU"].total == 94054.0


def test_parse_json_sums_bonded_and_dutypaid_when_no_total_row() -> None:
    recs = {r.symbol: r for r in sw.parse_json(_json_sample(drop_cu_total=True), date(2025, 9, 12))}
    cu = recs["CU"]
    assert cu.total == 18.0 + 94036.0
    assert cu.warrant == 0.0 + 25560.0
    assert cu.capacity == 30000.0 + 943040.0
    assert cu.prev_total == 18.0 + 81833.0
    assert (cu.bonded_total, cu.dutypaid_total) == (18.0, 94036.0)


def test_parse_json_rejects_wrong_date_and_bad_body() -> None:
    with pytest.raises(sw.ParseError):
        sw.parse_json(_json_sample(), date(2025, 9, 19))  # 嵌入 report_date 与文件名不符
    with pytest.raises(sw.ParseError):
        sw.parse_json(b"<html>challenge</html>", date(2025, 9, 12))
    with pytest.raises(sw.ParseError):
        sw.parse_json(b'{"o_code": "0"}', date(2025, 9, 12))


def test_parse_json_varid_mismatch_raises() -> None:
    doc = json.loads(_json_sample().decode("utf-8"))
    for r in doc["o_cursor"]:
        if r["VARNAME"].startswith("锡"):
            r["VARID"] = "ni"
    with pytest.raises(sw.ParseError):
        sw.parse_json(json.dumps(doc, ensure_ascii=False).encode("utf-8"), date(2025, 9, 12))


def test_parse_html_totals_and_products() -> None:
    recs = {r.symbol: r for r in sw.parse_html(_html_sample(), date(2025, 10, 31))}
    assert set(recs) == {"CU", "RU"}  # 铜(BC)/螺纹钢 不命中
    cu = recs["CU"]
    assert (cu.total, cu.warrant, cu.capacity) == (116140.0, 39710.0, 948890.0)
    assert (cu.prev_total, cu.prev_warrant, cu.prev_capacity) == (104792.0, 35071.0, 953529.0)
    assert (cu.bonded_total, cu.bonded_warrant) == (18.0, 0.0)
    assert (cu.dutypaid_total, cu.dutypaid_warrant) == (116122.0, 39710.0)
    assert cu.off_warrant == 116140.0 - 39710.0
    assert cu.source_format == "html" and cu.update_date == ""
    ru = recs["RU"]
    assert (ru.total, ru.warrant, ru.capacity) == (162025.0, 120900.0, 537100.0)
    assert (ru.prev_total, ru.prev_warrant) == (163450.0, 124020.0)


def test_parse_html_rejects_wrong_date_and_non_report() -> None:
    with pytest.raises(sw.ParseError):
        sw.parse_html(_html_sample("2025-11-07"), date(2025, 10, 31))
    with pytest.raises(sw.ParseError):
        sw.parse_html(b"<html><body>404</body></html>", date(2025, 10, 31))


def test_num_cells() -> None:
    assert sw._num("") is None and sw._num("-") is None and sw._num(None) is None
    assert sw._num("1,234") == 1234.0 and sw._num(7) == 7.0 and sw._num(" 5.5 ") == 5.5
    with pytest.raises(sw.ParseError):
        sw._num("abc")


def test_records_to_frame_drops_missing_and_sorts() -> None:
    recs = [
        sw.Record("RU", date(2025, 9, 12), total=10.0, warrant=4.0, capacity=1.0, source_format="json"),
        sw.Record("CU", date(2025, 9, 12), total=20.0, warrant=5.0, capacity=2.0, source_format="json"),
        sw.Record(
            "CU", date(2025, 9, 5), total=None, warrant=5.0, capacity=2.0, source_format="json"
        ),  # 小计空 → 无行
        sw.Record("CU", date(2025, 8, 29), total=7.0, warrant=1.0, capacity=None, source_format="json"),
    ]
    df = sw.records_to_frame(recs, holidays=set())
    assert list(df.columns)[:4] == ["obs_date", "available_day", "key", "value"]
    assert list(zip(df["key"], df["obs_date"])) == [
        ("S-CU", "2025-08-29"),
        ("S-CU", "2025-09-12"),
        ("S-RU", "2025-09-12"),
    ]
    assert list(df["value"]) == [6.0, 15.0, 6.0]
    assert pd.isna(df.loc[0, "capacity"])


def test_records_to_frame_rejects_duplicates() -> None:
    recs = [
        sw.Record("CU", date(2025, 9, 12), total=20.0, warrant=5.0, source_format="json"),
        sw.Record("CU", date(2025, 9, 12), total=21.0, warrant=5.0, source_format="html"),
    ]
    with pytest.raises(sw.ParseError):
        sw.records_to_frame(recs, holidays=set())


def test_consistency_check_flags_mismatch() -> None:
    df = pd.DataFrame(
        {
            "key": ["S-CU", "S-CU", "S-CU"],
            "obs_date": ["2025-08-29", "2025-09-05", "2025-09-12"],
            "total": [7.0, 8.0, 9.0],
            "warrant": [1.0, 2.0, 3.0],
            "capacity": [None, 5.0, 6.0],
            "prev_total": [6.0, 7.0, 8.0],
            "prev_warrant": [0.0, 1.0, 2.5],  # 第三份报告的"上周期货"与第二份不符
            "prev_capacity": [None, None, 5.0],
        }
    )
    m = sw.consistency_check(df)
    assert len(m) == 1
    assert (m.loc[0, "obs_date"], m.loc[0, "field"], m.loc[0, "reported_prev"], m.loc[0, "actual_prev"]) == (
        "2025-09-12",
        "warrant",
        2.5,
        2.0,
    )


# ---------------------------------------------------------------------------------------------
# (b) 可得规则:A = 报告日之后第一个交易日(周一至周五 − configs/holidays.csv)
# ---------------------------------------------------------------------------------------------


def test_available_day_friday_to_monday() -> None:
    assert sw.available_day(date(2025, 9, 12), set()) == date(2025, 9, 15)  # 周五 → 周一
    assert sw.available_day(date(2025, 9, 30), set()) == date(2025, 10, 1)  # 周二 → 周三(无假日登记时)
    assert sw.available_day(date(2025, 9, 11), set()) == date(2025, 9, 12)  # 周四 → 周五


def test_available_day_skips_registered_holidays() -> None:
    hol = {date(2026, 9, 25), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)}
    assert sw.available_day(date(2026, 9, 24), hol) == date(2026, 9, 28)  # 周四报告,周五假 → 下周一
    assert sw.available_day(date(2026, 9, 30), hol) == date(2026, 10, 6)  # 国庆:10/1、10/2、10/5 假 → 10/6
    assert sw.available_day(date(2026, 9, 18), hol) == date(2026, 9, 21)


def test_available_day_always_strictly_after_and_weekday() -> None:
    hol = {date(2024, 1, 1), date(2024, 2, 12), date(2024, 2, 13)}
    d = date(2023, 12, 1)
    while d <= date(2024, 3, 31):
        a = sw.available_day(d, hol)
        assert a > d, (d, a)
        assert a - d >= timedelta(days=1)
        assert a.weekday() < 5 and a not in hol
        # 严格:R 与 A 之间没有任何交易日
        x = d + timedelta(days=1)
        while x < a:
            assert not sw.is_trading_day(x, hol)
            x += timedelta(days=1)
        d += timedelta(days=1)


def test_available_day_ignores_file_timestamps() -> None:
    """规则只依赖报告日;文件被晚些重写(Last-Modified 更晚)不改变可得日,也绝不会更早。"""
    early = sw.Record(
        "CU", date(2025, 9, 12), total=2.0, warrant=1.0, last_modified_utc="2025-09-12T07:13:00Z"
    )
    late = sw.Record(
        "AL", date(2025, 9, 12), total=2.0, warrant=1.0, last_modified_utc="2026-03-20T09:19:29Z"
    )
    df = sw.records_to_frame([early, late], holidays=set())
    assert set(df["available_day"]) == {"2025-09-15"}
    assert set(df["last_modified_utc"]) == {"2025-09-12T07:13:00Z", "2026-03-20T09:19:29Z"}


def test_load_holidays_parses_repo_format(tmp_path: Path) -> None:
    p = tmp_path / "holidays.csv"
    p.write_text("# comment\ndate,name\n2026-01-01,元旦\n2026-02-16,春节\n", encoding="utf-8")
    assert sw.load_holidays(p) == {date(2026, 1, 1), date(2026, 2, 16)}
    assert sw.load_holidays(tmp_path / "missing.csv") == set()


# ---------------------------------------------------------------------------------------------
# 下载:幂等/续传(打桩 HTTP,不联网)
# ---------------------------------------------------------------------------------------------


def test_ensure_file_idempotent_and_404_memo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get(url: str, valid: Any) -> tuple[int, bytes, str | None]:
        calls.append(url)
        if "20250912" in url:
            return 200, _json_sample(), "Fri, 12 Sep 2025 08:31:03 GMT"
        return 404, b"", None

    monkeypatch.setattr(sw, "http_get", fake_get)
    monkeypatch.setattr(sw, "MIN_INTERVAL", 0.0)
    raw = tmp_path / "raw"
    nf: dict[tuple[str, str], str] = {}
    assert sw.ensure_file(raw, date(2025, 9, 12), "json", nf) is True
    assert sw.ensure_file(raw, date(2025, 9, 12), "json", nf) is True  # 已在本地:不再请求
    assert len(calls) == 1
    f, m = sw.raw_paths(raw, date(2025, 9, 12), "json")
    meta = json.loads(m.read_text(encoding="utf-8"))
    assert meta["size"] == f.stat().st_size == len(_json_sample())
    assert meta["last_modified_utc"] == "2025-09-12T08:31:03Z"
    assert meta["update_date"] == "20250912 16:31:03"
    # 404:记录到 not_found.csv;报告日已过 7 天 → 之后不再重探
    assert sw.ensure_file(raw, date(2025, 10, 3), "json", nf) is False
    assert sw.ensure_file(raw, date(2025, 10, 3), "json", nf) is False
    assert len(calls) == 2
    assert sw._load_not_found(raw) == nf and ("2025-10-03", "json") in nf
    # 文件大小与 meta 不符(截断)→ 重新下载
    f.write_bytes(b"{}")
    assert sw.ensure_file(raw, date(2025, 9, 12), "json", nf) is True
    assert len(calls) == 3 and f.stat().st_size == len(_json_sample())


def test_fetch_walks_back_from_friday(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """周五 404 → 周四 … 周一;找到即停;整周 404 则无报告。"""
    calls: list[str] = []

    def fake_get(url: str, valid: Any) -> tuple[int, bytes, str | None]:
        calls.append(url)
        if "20250930" in url:  # 2025-10-03 周五国庆休市,报告日为周二 9/30
            doc = json.loads(_json_sample().decode("utf-8"))
            doc["report_date"] = doc["o_tradingday"] = "20250930"
            return 200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), None
        return 404, b"", None

    monkeypatch.setattr(sw, "http_get", fake_get)
    monkeypatch.setattr(sw, "MIN_INTERVAL", 0.0)
    sw.fetch(tmp_path, start="2025-09-29", end="2025-10-05")
    assert [_url_date(u) for u in calls] == ["20251003", "20251002", "20251001", "20250930"]
    df = sw.load(tmp_path, holidays_path=tmp_path / "none.csv")
    assert set(df["obs_date"]) == {"2025-09-30"} and set(df["key"]) == {"S-CU", "S-RU", "S-SN"}
    assert set(df["available_day"]) == {"2025-10-01"}  # 未登记假日时按工作日历


def test_fetch_treats_empty_cursor_as_no_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2014–2015 的服务器对无报告日返回 200 + 空 o_cursor(实测 20150106):不能当作报告存下并停止向前退。"""
    calls: list[str] = []

    def fake_get(url: str, valid: Any) -> tuple[int, bytes, str | None]:
        calls.append(url)
        d = _url_date(url)
        if d == "20150220":  # 周五(春节休市)→ 空报告
            empty = {"o_tradingday": d, "o_cursor": [], "o_code": "0", "o_msg": "库存周报查询成功"}
            return 200, json.dumps(empty, ensure_ascii=False).encode("utf-8"), None
        if d == "20150219":
            return 404, b"", None
        if d == "20150218":
            doc = json.loads(_json_sample(with_varid=False).decode("utf-8"))
            doc.pop("report_date"), doc.pop("o_tradingday"), doc.pop("update_date")
            return 200, json.dumps(doc, ensure_ascii=False).encode("utf-8"), None
        return 404, b"", None

    monkeypatch.setattr(sw, "http_get", fake_get)
    monkeypatch.setattr(sw, "MIN_INTERVAL", 0.0)
    sw.fetch(tmp_path, start="2015-02-16", end="2015-02-22")
    assert [_url_date(u) for u in calls] == ["20150220", "20150219", "20150218"]
    raw = tmp_path / "raw"
    assert not sw.raw_paths(raw, date(2015, 2, 20), "json")[0].exists()  # 空报告不落盘
    assert ("2015-02-20", "json") in sw._load_not_found(raw)
    df = sw.load(tmp_path, holidays_path=tmp_path / "none.csv")
    assert set(df["obs_date"]) == {"2015-02-18"} and set(df["available_day"]) == {"2015-02-19"}


def test_formats_for_eras() -> None:
    assert sw.formats_for(date(2020, 1, 3)) == ["json"]
    assert sw.formats_for(date(2025, 11, 7)) == ["json", "html"]
    assert sw.formats_for(date(2026, 9, 18)) == ["html"]


# ---------------------------------------------------------------------------------------------
# (c) 真实数据
# ---------------------------------------------------------------------------------------------


@pytest.mark.skipif(not OBS.exists(), reason="observations.csv not fetched")
def test_real_observations_obey_contract_and_rule() -> None:
    df = pd.read_csv(OBS, dtype={"obs_date": str, "available_day": str, "key": str, "update_date": str})
    assert list(df.columns)[:4] == ["obs_date", "available_day", "key", "value"]
    assert set(df["key"]) == {"S-CU", "S-AL", "S-NI", "S-SN", "S-RU"}
    assert not df.duplicated(["key", "obs_date"]).any()
    assert df.equals(df.sort_values(["key", "obs_date"], kind="mergesort").reset_index(drop=True))
    assert df["value"].notna().all()
    obs = pd.to_datetime(df["obs_date"])
    avail = pd.to_datetime(df["available_day"])
    hol = sw.load_holidays()
    assert (avail > obs).all()
    assert (avail - obs >= pd.Timedelta(days=1)).all()
    assert (avail.dt.weekday < 5).all()
    assert not avail.dt.date.isin(hol).any()
    # 逐行重算规则
    recomputed = [sw.available_day(d.date(), hol).isoformat() for d in obs]
    assert recomputed == list(df["available_day"])
    # value = 小计 − 期货;报告日都是工作日
    assert ((df["total"] - df["warrant"] - df["value"]).abs() < 1e-6).all()
    assert (obs.dt.weekday < 5).all()
    assert df["source_format"].isin(["json", "html"]).all()
    # 与 raw 重新加载一致(available_day 重算)
    df2 = sw.load(DEST)
    assert len(df2) == len(df)
    assert list(df2["available_day"]) == list(df["available_day"])
    assert list(df2["value"]) == list(df["value"])
