"""交易所每日风控参数(保证金 / 手续费 / 平今手续费 / 涨跌停)接入,kind="params";并从逐日参数机械推导"上调"事件。

来源(交易所官网静态文件,桌面 UA 直接 curl 即可;字段映射、口径与已知坑见 docs/data_exchange_params.md):
  SHFE  https://www.shfe.com.cn/data/busiparamdata/future/Settlement{YYYYMMDD}.dat                 结算参数:保证金、手续费、平今折扣
        https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument{YYYYMMDD}.dat  每日交易参数:当日盘中生效的涨跌停
  INE   同上两个文件,域名 www.ine.cn(上期所文件里也含能源中心品种,按 INE_SYMBOLS 拆分,两者逐合约一致)
  CZCE  https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureDataClearParams.txt  结算参数表(2016-01-04 起)
        https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureTradeParam.txt      交易参数(2025-08-18 起)
  DCE   dcereport 全站反爬,参数文件需浏览器会话,本模块只留接口(fetch 抛 NotImplementedError)。

口径:margin_spec / fee_* 为文件日 D 结算起适用的值;limit_pct 为 D 盘中生效的涨跌停幅度(上期所 ContractDailyTradeArgument、
郑商所 FutureTradeParam 的口径;郑商所 2025-08-18 前用前一交易日结算参数表的"涨跌停板"列,两者相等)。

用法:
    PYTHONPATH=src python3 -m cta.data.exchanges.params backfill --start 2016-01-04 --exchanges SHFE,INE,CZCE [--local-dir DIR]
    PYTHONPATH=src python3 -m cta.data.exchanges.params day --date 2026-09-18
    PYTHONPATH=src python3 -m cta.data.exchanges.params derive --out data/external/exchange_events/events_derived.csv
    PYTHONPATH=src python3 -m cta.data.exchanges.params coverage
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from cta.data.exchanges import czce, shfe
from cta.data.exchanges.base import PARAM_COLS, Store, normalize_contract, symbol_of
from cta.data.exchanges.calendar import load_holidays
from cta.data.exchanges.ine import INE
from cta.data.exchanges.shfe import SHFE, FetchError, Site, http_get

log = logging.getLogger(__name__)

KIND = "params"
EXCHANGES: tuple[str, ...] = ("SHFE", "INE", "CZCE")  # 已实现直连的交易所;DCE 见 fetch_params
SITES: dict[str, Site] = {"SHFE": SHFE, "INE": INE}
# raw 文件名后缀(Store.raw_path 的 ext):每所每天两个文件
SHFE_EXT_SETTLEMENT = "settlement.json"
SHFE_EXT_TRADEARG = "tradearg.json"
CZCE_EXT_CLEAR = "clear.txt"
CZCE_EXT_TRADE = "trade.txt"
CZCE_BASE_URL = czce.BASE_URL
# 郑商所结算参数表的口径切换日(由 2016-01-04 起全部文件的表头确定)
# "平今仓手续费"数值列出现;此前只有 Y/N 的"平今手续费减半"→ fee_close_today 为 NaN
CZCE_CLOSE_TODAY_FROM = pd.Timestamp("2017-06-23")
# "涨跌停板(%)"列出现(同日 买/卖交易保证金率 两列合并为 交易保证金率)
CZCE_LIMIT_FROM = pd.Timestamp("2019-09-02")
# "手续费收取方式"列出现;首个"比例值"为 2023-07-20(甲醇),此前全部为元/手
CZCE_FEE_STYLE_FROM = pd.Timestamp("2022-11-07")
# FutureTradeParam.txt(交易参数,含当日涨跌停板幅度)首日
CZCE_TRADE_PARAM_FROM = pd.Timestamp("2025-08-18")
# 推导:相邻两个参数文件相距超过此天数(数据缺口而非假期)不比较;节假日判定窗口
MAX_GAP_DAYS = 12
HOLIDAY_BEFORE_SESSIONS = 3  # 上调生效日在休市日前 ≤3 个交易日
HOLIDAY_RESTORE_SESSIONS = 10  # 且随后 ≤10 个交易日内回落到不高于原值
EVENT_COLS = [
    "announce_date",
    "effective_date",
    "exchange",
    "symbol",
    "contract_scope",
    "param",
    "direction",
    "old_value",
    "new_value",
    "unit",
    "reason",
    "notice_id",
    "url",
    "notes",
]
DERIVED_NOTE = "DERIVED-daily"

_INST_RE = re.compile(r"^[a-z]{1,2}\d{4}$")
_CZCE_CODE_RE = re.compile(r"^[A-Z]{1,2}\d{3,4}$")


# ---------------------------------------------------------------------------------------------
# URL
# ---------------------------------------------------------------------------------------------


def settlement_url(site: Site, date: pd.Timestamp) -> str:
    return f"{site.base_url}/data/busiparamdata/future/Settlement{pd.Timestamp(date):%Y%m%d}.dat"


def trade_argument_url(site: Site, date: pd.Timestamp) -> str:
    return (
        f"{site.base_url}/data/busiparamdata/future/ContractDailyTradeArgument{pd.Timestamp(date):%Y%m%d}.dat"
    )


def czce_clear_url(date: pd.Timestamp) -> str:
    d = pd.Timestamp(date)
    return f"{CZCE_BASE_URL}/{d.year}/{d:%Y%m%d}/FutureDataClearParams.txt"


def czce_trade_url(date: pd.Timestamp) -> str:
    d = pd.Timestamp(date)
    return f"{CZCE_BASE_URL}/{d.year}/{d:%Y%m%d}/FutureTradeParam.txt"


def main_url(exchange: str, date: pd.Timestamp) -> str:
    """该所当日参数的主文件(保证金/手续费所在文件)URL,用于 missing.log 与事件的 url 列。"""
    if exchange == "CZCE":
        return czce_clear_url(date)
    return settlement_url(SITES[exchange], date)


# ---------------------------------------------------------------------------------------------
# 下载(存 raw)
# ---------------------------------------------------------------------------------------------


def _exts(exchange: str) -> tuple[str, str]:
    """(主文件 ext, 副文件 ext):主文件缺 = 当日无数据;副文件可缺(限价字段为 NaN)。"""
    if exchange == "CZCE":
        return CZCE_EXT_CLEAR, CZCE_EXT_TRADE
    return SHFE_EXT_SETTLEMENT, SHFE_EXT_TRADEARG


def _urls(exchange: str, date: pd.Timestamp) -> tuple[str, str]:
    if exchange == "CZCE":
        return czce_clear_url(date), czce_trade_url(date)
    return settlement_url(SITES[exchange], date), trade_argument_url(SITES[exchange], date)


def _json_or_none(raw: bytes | None, url: str) -> bytes | None:
    """200 但不是 JSON(WAF 挑战页)视为下载失败;404 或没有任何合约行(尚未发布)→ None,不落盘。"""
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FetchError(f"{url}: response is not JSON ({e})") from e
    if not isinstance(data, dict) or not any(isinstance(v, list) and v for v in data.values()):
        return None
    return raw


def _czce_txt_or_none(raw: bytes | None) -> bytes | None:
    """郑商所非交易日偶见 200 + '当日无数据' HTML;空文件或只有表头(无合约行)同样视为缺数据。"""
    if raw is None or not raw.strip() or b"<html" in raw[:300].lower():
        return None
    if sum(1 for ln in czce.decode_text(raw).splitlines() if "|" in ln) < 2:
        return None
    return raw


def read_raws(exchange: str, date: pd.Timestamp, store: Store) -> dict[str, bytes | None] | None:
    """已落盘的 raw:{'main': bytes, 'aux': bytes|None};主文件不存在返回 None。"""
    main_ext, aux_ext = _exts(exchange)
    main = store.read_raw(exchange, KIND, date, main_ext)
    if main is None:
        return None
    return {"main": main, "aux": store.read_raw(exchange, KIND, date, aux_ext)}


def write_raws(exchange: str, date: pd.Timestamp, raws: dict[str, bytes | None], store: Store) -> None:
    main_ext, aux_ext = _exts(exchange)
    main = raws.get("main")
    if main is not None:
        store.write_raw(exchange, KIND, date, main_ext, main)
    aux = raws.get("aux")
    if aux is not None:
        store.write_raw(exchange, KIND, date, aux_ext, aux)


def fetch_params(
    date: pd.Timestamp, exchange: str, store: Store | None = None, fetch_aux: bool = True
) -> dict[str, bytes | None] | None:
    """下载某日两个参数文件并存 raw,返回 {'main': 结算参数, 'aux': 交易参数|None};主文件 404 返回 None(节假日/未发布)。
    郑商所交易参数文件 2025-08-18 之前不存在,不请求。DCE 需浏览器会话:抛 NotImplementedError。"""
    if exchange == "DCE":
        raise NotImplementedError(
            "DCE daily parameters need a browser session (dcereport WAF); see docs/data_exchange_params.md"
        )
    if exchange not in EXCHANGES:
        raise ValueError(f"unknown exchange {exchange!r}; choose from {EXCHANGES}")
    st = store or Store()
    date = pd.Timestamp(date).normalize()
    cached = read_raws(exchange, date, st)
    if cached is not None and (cached["aux"] is not None or not fetch_aux):
        return cached
    main_url_, aux_url = _urls(exchange, date)
    if cached is not None:
        main: bytes | None = cached["main"]
    elif exchange == "CZCE":
        main = _czce_txt_or_none(http_get(main_url_))
    else:
        main = _json_or_none(http_get(main_url_), main_url_)
    if main is None:
        return None
    aux: bytes | None = None
    if fetch_aux and (exchange != "CZCE" or date >= CZCE_TRADE_PARAM_FROM):
        got = http_get(aux_url)
        aux = _czce_txt_or_none(got) if exchange == "CZCE" else _json_or_none(got, aux_url)
    raws: dict[str, bytes | None] = {"main": main, "aux": aux}
    write_raws(exchange, date, raws, st)
    return raws


# ---------------------------------------------------------------------------------------------
# 解析:raw → PARAM_COLS
# ---------------------------------------------------------------------------------------------


def _num(v: Any) -> float:
    if v is None:
        return float("nan")
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("±", "").replace("%", "")
    if s in {"", "-", "--"}:
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _json_rows(raw: bytes, key: str) -> list[dict[str, Any]]:
    """上期所/能源中心 .dat:{'Settlement': [...], 'report_date': ...};能源中心早期文件只有列表键。"""
    data = cast(dict[str, Any], json.loads(raw.decode("utf-8-sig")))
    rows = data.get(key)
    if rows is None:
        lists = [v for v in data.values() if isinstance(v, list)]
        rows = lists[0] if lists else []
    return cast(list[dict[str, Any]], rows)


def _row(
    date: pd.Timestamp,
    exchange: str,
    contract: str,
    margin: float,
    hedge: float,
    fee: float,
    fee_unit: str | None,
    close_today: float,
    limit: float,
) -> dict[str, Any]:
    return {
        "date": date,
        "exchange": exchange,
        "symbol": symbol_of(contract),
        "contract": contract,
        "margin_spec": margin,
        "margin_hedge": hedge,
        "fee_open": fee,
        "fee_open_unit": fee_unit if not np.isnan(fee) else None,
        "fee_close_today": close_today,
        "fee_close_today_unit": fee_unit if not np.isnan(close_today) else None,
        "limit_pct": limit,
    }


def parse_shfe_params(
    settlement: bytes, tradearg: bytes | None, date: pd.Timestamp, site: Site = SHFE
) -> pd.DataFrame:
    """Settlement + ContractDailyTradeArgument → PARAM_COLS(只保留本站点拥有的品种)。
    margin_spec = SPEC_LONGMARGINRATIO(投机;买卖两侧全程相等),margin_hedge = LONGMARGINRATIO(套保);
    手续费:TRADEFEERATION > 0 → 万分比(×1e4,单位 bp),否则 TRADEFEEUNIT 元/手;
    平今 = DISCOUNTRATE × 开仓费(折扣率是开仓费的倍数:0 免收、1 同开仓、2 双倍);limit_pct = 交易参数 UPPER_VALUE。
    保证金为 0 的行(集运指数 EC 最后交易日,合约现金交割)剔除。"""
    date = pd.Timestamp(date)
    limits: dict[str, float] = {}
    if tradearg is not None:
        for r in _json_rows(tradearg, "ContractDailyTradeArgument"):
            inst = str(r.get("INSTRUMENTID", "")).strip().lower()
            if _INST_RE.match(inst):
                limits[inst.upper()] = _num(r.get("UPPER_VALUE"))
    out: list[dict[str, Any]] = []
    for r in _json_rows(settlement, "Settlement"):
        inst = str(r.get("INSTRUMENTID", "")).strip().lower()
        if not _INST_RE.match(inst):
            continue  # 期权 / 期转现 / TAS 不在本文件,但防御性过滑
        contract = normalize_contract(inst, site.exchange, date)
        if not site.owns(symbol_of(contract)):
            continue
        margin = _num(r.get("SPEC_LONGMARGINRATIO"))
        if not margin > 0:
            log.debug(
                "%s %s %s: zero/empty margin (expiring cash-settled contract), dropped",
                site.exchange,
                date.date(),
                contract,
            )
            continue
        ratio, per_lot = _num(r.get("TRADEFEERATION")), _num(r.get("TRADEFEEUNIT"))
        if ratio > 0:
            fee, unit = round(ratio * 1e4, 6), "bp"
        else:
            fee, unit = (per_lot if not np.isnan(per_lot) else 0.0), "CNY_per_lot"
        disc = _num(r.get("DISCOUNTRATE"))
        close_today = round(disc * fee, 6) if not np.isnan(disc) else float("nan")
        out.append(
            _row(
                date,
                site.exchange,
                contract,
                margin,
                _num(r.get("LONGMARGINRATIO")),
                fee,
                unit,
                close_today,
                limits.get(contract, float("nan")),
            )
        )
    return pd.DataFrame(out, columns=PARAM_COLS)


def _czce_table(raw: bytes) -> tuple[list[str], list[list[str]]]:
    """竖线分隔文本 → (表头, 数据行)。首行为标题('郑州商品交易所期货结算参数表(2026-09-18)'),不含竖线。"""
    lines = [ln for ln in czce.decode_text(raw).splitlines() if "|" in ln]
    if not lines:
        return [], []
    header = [h.strip() for h in lines[0].split("|")]
    rows = [[c.strip() for c in ln.split("|")] for ln in lines[1:]]
    return header, rows


def _col(header: list[str], *names: str) -> int:
    for n in names:
        if n in header:
            return header.index(n)
    return -1


def _czce_limits(raw: bytes | None, column_names: tuple[str, ...], date: pd.Timestamp) -> dict[str, float]:
    """某个郑商所文件里 合约 → 涨跌停幅度(小数);文件为 None 或没有该列 → 空。"""
    if raw is None:
        return {}
    header, rows = _czce_table(raw)
    i = _col(header, *column_names)
    if i < 0:
        return {}
    out: dict[str, float] = {}
    for cells in rows:
        if cells and _CZCE_CODE_RE.match(cells[0]) and i < len(cells):
            out[normalize_contract(cells[0], "CZCE", date)] = _num(cells[i]) / 100.0
    return out


def parse_czce_params(
    clear: bytes, trade: bytes | None, date: pd.Timestamp, prev_clear: bytes | None = None
) -> pd.DataFrame:
    """FutureDataClearParams(+ FutureTradeParam)→ PARAM_COLS。
    margin_spec = 交易保证金率(%)/100(2019-09 前为 买交易保证金率,买卖全程相等);margin_hedge 文件无 → NaN;
    fee_open = 交易手续费,单位按"手续费收取方式"(比例值 → bp,绝对值 → 元/手;该列 2022-11-07 前不存在,全部按元/手);
    fee_close_today = 日内平今仓交易手续费 / 平今仓手续费(2017-06-23 起;此前只有 Y/N 的"平今手续费减半"→ NaN);
    limit_pct = 交易参数文件的 涨跌停板幅度(%)(当日盘中),没有交易参数文件时用前一交易日结算参数表的 涨跌停板(%)(相等)。"""
    date = pd.Timestamp(date)
    header, rows = _czce_table(clear)
    i_margin = _col(header, "交易保证金率(%)", "买交易保证金率(%)")
    i_fee = _col(header, "交易手续费")
    i_style = _col(header, "手续费收取方式")
    i_ct = _col(header, "日内平今仓交易手续费", "平今仓手续费")
    if i_margin < 0 or i_fee < 0:
        raise ValueError(f"CZCE params {date.date()}: unrecognised header {header}")
    limits = _czce_limits(trade, ("涨跌停板幅度(%)",), date) or _czce_limits(
        prev_clear, ("涨跌停板(%)",), date
    )
    out: list[dict[str, Any]] = []
    for cells in rows:
        if not cells or not _CZCE_CODE_RE.match(cells[0]) or len(cells) <= max(i_margin, i_fee):
            continue  # 期权、小计等
        contract = normalize_contract(cells[0], "CZCE", date)
        margin = _num(cells[i_margin]) / 100.0
        if not margin > 0:
            log.debug("CZCE %s %s: zero/empty margin, dropped", date.date(), contract)
            continue
        fee = _num(cells[i_fee])
        unit = "bp" if 0 <= i_style < len(cells) and cells[i_style] == "比例值" else "CNY_per_lot"
        close_today = _num(cells[i_ct]) if 0 <= i_ct < len(cells) else float("nan")
        out.append(
            _row(
                date,
                "CZCE",
                contract,
                margin,
                float("nan"),
                fee,
                unit,
                close_today,
                limits.get(contract, float("nan")),
            )
        )
    return pd.DataFrame(out, columns=PARAM_COLS)


def parse_params(
    raws: dict[str, bytes | None], date: pd.Timestamp, exchange: str, prev_main: bytes | None = None
) -> pd.DataFrame:
    """按交易所分派:raws = fetch_params 的返回;prev_main 只对郑商所有意义(前一交易日结算参数表,补 limit_pct)。"""
    main = raws.get("main")
    if main is None:
        raise ValueError(f"{exchange} {pd.Timestamp(date).date()}: main parameter file missing")
    if exchange == "CZCE":
        return parse_czce_params(main, raws.get("aux"), date, prev_clear=prev_main)
    if exchange in SITES:
        return parse_shfe_params(main, raws.get("aux"), date, SITES[exchange])
    raise NotImplementedError(f"no parser for {exchange}")


# ---------------------------------------------------------------------------------------------
# 落盘与回填
# ---------------------------------------------------------------------------------------------


def _prev_main_raw(exchange: str, date: pd.Timestamp, store: Store) -> bytes | None:
    """前一交易日的主文件 raw(最多回看 MAX_GAP_DAYS 天),郑商所无交易参数文件时用它补涨跌停。"""
    main_ext, _ = _exts(exchange)
    for back in range(1, MAX_GAP_DAYS + 1):
        raw = store.read_raw(exchange, KIND, date - pd.Timedelta(days=back), main_ext)
        if raw is not None:
            return raw
    return None


def _known_missing(exchange: str, store: Store) -> set[pd.Timestamp]:
    """各所 missing.log 里已记为缺失的 params 日期(复用各模块的日志格式)。"""
    if exchange == "CZCE":
        return {d for (d, k) in czce.load_missing(store) if k == KIND}
    return {pd.Timestamp(d) for (d, k) in shfe.load_missing(store, SITES[exchange]) if k == KIND}


def _log_missing(exchange: str, date: pd.Timestamp, store: Store, reason: str) -> None:
    if exchange == "CZCE":
        czce.log_missing(store, date, KIND, reason)
    else:
        shfe._log_missing(store, SITES[exchange], date, KIND, reason, main_url(exchange, date))


def _write(
    exchange: str, date: pd.Timestamp, raws: dict[str, bytes | None], store: Store, overwrite: bool
) -> str:
    prev = _prev_main_raw(exchange, date, store) if exchange == "CZCE" and raws.get("aux") is None else None
    df = parse_params(raws, date, exchange, prev_main=prev)
    if df.empty:
        return "empty"
    store.write_day(exchange, KIND, date, df, overwrite=overwrite)
    return "written"


def ingest_day(
    date: pd.Timestamp,
    exchanges: Iterable[str] = EXCHANGES,
    store: Store | None = None,
    overwrite: bool = False,
    record_missing: bool = True,
) -> dict[str, str]:
    """把某日各所参数落成 parquet。返回 {exchange: 'written'|'exists'|'missing'|'empty'|'error:...'}。
    已存在(且不 overwrite)跳过;主文件 404 记 missing(record_missing 且日期早于北京今天时写入该所 missing.log,
    当天的 404 可能只是尚未发布——文件约在北京 16:00–16:40 发布);单个交易所的下载/解析失败只记录不中断。"""
    st = store or Store()
    date = pd.Timestamp(date).normalize()
    beijing_today = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None).normalize()
    record_missing = record_missing and date < beijing_today
    status: dict[str, str] = {}
    for exch in exchanges:
        if st.has_day(exch, KIND, date) and not overwrite:
            status[exch] = "exists"
            continue
        try:
            raws = fetch_params(date, exch, st)
            if raws is None:
                status[exch] = "missing"
                if record_missing:
                    _log_missing(exch, date, st, "404")
                continue
            status[exch] = _write(exch, date, raws, st, overwrite)
            if status[exch] == "empty" and record_missing:
                _log_missing(exch, date, st, "empty")
        except NotImplementedError as e:
            status[exch] = f"error:{e}"
        except (FetchError, ValueError) as e:
            log.error("%s %s params: %s", exch, date.date(), e)
            status[exch] = f"error:{type(e).__name__}:{e}"
    return status


def local_raws(local: Path, exchange: str, date: pd.Timestamp) -> tuple[str, dict[str, bytes | None] | None]:
    """草稿区已下载文件 → ('found', raws) / ('missing', None)(有 .404 标记)/ ('none', None)(本地没有,需联网)。
    布局:SHFE/INE  {dir}/S{YYYYMMDD}.json + T{YYYYMMDD}.json(.404 后缀为 404 标记);CZCE  {dir}/{YYYYMMDD}.txt。"""
    ds = f"{pd.Timestamp(date):%Y%m%d}"
    if exchange == "CZCE":
        main_p, aux_p = local / f"{ds}.txt", None
    else:
        main_p, aux_p = local / f"S{ds}.json", local / f"T{ds}.json"
    if main_p.exists():
        aux = aux_p.read_bytes() if aux_p is not None and aux_p.exists() else None
        return "found", {"main": main_p.read_bytes(), "aux": aux}
    if main_p.with_name(main_p.name + ".404").exists():
        return "missing", None
    return "none", None


def backfill(
    start: pd.Timestamp,
    end: pd.Timestamp,
    exchanges: Iterable[str] = EXCHANGES,
    store: Store | None = None,
    local: Path | dict[str, Path] | None = None,
    retry_missing: bool = False,
    overwrite: bool = False,
    max_consecutive_errors: int = 10,
) -> dict[str, dict[str, int]]:
    """逐工作日回填 [start, end](可断点续跑):已有 parquet 跳过;missing.log 里的日期跳过(retry_missing 重试);
    local 目录里已下载的文件优先导入(写 raw + parquet,不联网),本地没有的再 curl;连续 max_consecutive_errors 次下载失败中止。
    local 可为单一目录(只回填一个所时)或 {exchange: dir}。返回 {exchange: 计数}。"""
    st = store or Store()
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    today = pd.Timestamp.today().normalize()
    result: dict[str, dict[str, int]] = {}
    for exch in exchanges:
        local_dir = local.get(exch) if isinstance(local, dict) else local
        known = set() if retry_missing else _known_missing(exch, st)
        counts: dict[str, int] = dict.fromkeys(
            ("written", "exists", "missing", "empty", "error", "skipped", "local"), 0
        )
        consecutive = 0
        days = pd.bdate_range(start, end)
        t0 = time.monotonic()
        for i, d in enumerate(days, 1):
            if st.has_day(exch, KIND, d) and not overwrite:
                counts["exists"] += 1
                continue
            if d in known:
                counts["skipped"] += 1
                continue
            try:
                raws: dict[str, bytes | None] | None = None
                where = "none"
                if local_dir is not None:
                    where, raws = local_raws(Path(local_dir), exch, d)
                if where == "missing":
                    counts["missing"] += 1
                    _log_missing(exch, d, st, "404")
                    continue
                if raws is not None:
                    counts["local"] += 1
                    write_raws(exch, d, raws, st)
                    raws = (
                        fetch_params(d, exch, st) if raws.get("aux") is None else raws
                    )  # 补抓副文件(已缓存主文件)
                else:
                    raws = fetch_params(d, exch, st)
                if raws is None:
                    counts["missing"] += 1
                    if d < today:
                        _log_missing(exch, d, st, "404")
                    continue
                status = _write(exch, d, raws, st, overwrite)
                counts[status] += 1
                if status == "empty" and d < today:
                    _log_missing(exch, d, st, "empty")
                consecutive = 0
            except FetchError as e:
                counts["error"] += 1
                consecutive += 1
                log.error("%s %s params: %s", exch, d.date(), e)
                if consecutive >= max_consecutive_errors:
                    raise RuntimeError(
                        f"{consecutive} consecutive fetch errors, aborting at {d.date()}"
                    ) from e
            except ValueError as e:  # 解析/校验失败:raw 已落盘,记错继续
                counts["error"] += 1
                log.error("%s %s params: parse/validate failed: %s", exch, d.date(), e)
            if i % 100 == 0 or i == len(days):
                log.info(
                    "%s params %s [%d/%d] %s  %.0fs",
                    exch,
                    d.date(),
                    i,
                    len(days),
                    counts,
                    time.monotonic() - t0,
                )
        result[exch] = counts
    return result


def coverage(store: Store | None = None, exchanges: Iterable[str] = EXCHANGES) -> pd.DataFrame:
    """每所每年的落盘天数。"""
    st = store or Store()
    rows = {}
    for exch in exchanges:
        days = st.days(exch, KIND)
        rows[exch] = (
            pd.Series([d.year for d in days]).value_counts().sort_index() if days else pd.Series(dtype=int)
        )
    out = pd.DataFrame(rows).fillna(0).astype(int)
    out.index.name = "year"
    return out


# ---------------------------------------------------------------------------------------------
# 事件推导:逐日比对品种"一般月份"档,上调 → 事件
# ---------------------------------------------------------------------------------------------


def _mode_small(df: pd.DataFrame, value_col: str, tag_col: str | None = None) -> pd.DataFrame:
    """每 (date, symbol) 的 value_col 众数(tag_col 为伴随的单位列,与值一起计数),平票取最小值;值为 NaN 的行不参与。"""
    cols = [value_col] + ([tag_col] if tag_col else [])
    sub = df.dropna(subset=[value_col])
    if tag_col:
        sub = sub.assign(**{tag_col: sub[tag_col].fillna("")})
    sizes = cast("pd.Series[int]", sub.groupby(["date", "symbol", *cols]).size())
    vc = sizes.rename("n").reset_index()
    vc = vc.sort_values(["date", "symbol", "n", *cols], ascending=[True, True, False] + [True] * len(cols))
    return vc.drop_duplicates(["date", "symbol"]).drop(columns="n")


def daily_levels(df: pd.DataFrame) -> pd.DataFrame:
    """PARAM_COLS 表 → 每日每品种的一般月份档:margin(margin_spec 众数,平票取小,自动忽略交割月加档)、
    fee / fee_unit((fee_open, 单位) 众数)、n_contracts。"""
    if df.empty:
        return pd.DataFrame(columns=["date", "symbol", "margin", "fee", "fee_unit", "n_contracts"])
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    n = cast("pd.Series[int]", d.groupby(["date", "symbol"]).size()).rename("n_contracts").reset_index()
    m = _mode_small(d, "margin_spec").rename(columns={"margin_spec": "margin"})
    f = _mode_small(d, "fee_open", "fee_open_unit").rename(
        columns={"fee_open": "fee", "fee_open_unit": "fee_unit"}
    )
    out = n.merge(m, on=["date", "symbol"], how="left").merge(f, on=["date", "symbol"], how="left")
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def _sessions_with_future(
    sessions: pd.DatetimeIndex, holidays: pd.DatetimeIndex, horizon_days: int = 40
) -> pd.DatetimeIndex:
    """已观察交易日 ∪ 未来工作日 − 已公告假期(configs/holidays.csv),供最后几个事件的节假日判定。"""
    if len(sessions) == 0:
        return sessions
    fut = pd.bdate_range(sessions[-1] + pd.Timedelta(days=1), sessions[-1] + pd.Timedelta(days=horizon_days))
    fut = fut[~fut.isin(holidays)]
    return pd.DatetimeIndex(sorted(set(sessions) | set(fut)))


def _closure_ahead(sessions: pd.DatetimeIndex, i: int, within: int = HOLIDAY_BEFORE_SESSIONS) -> bool:
    """sessions[i] 是否在某个休市日(周一至周五的非交易日)之前 ≤within 个交易日。"""
    for k in range(within):
        if i + k + 1 >= len(sessions):
            return False
        cur, nxt = sessions[i + k], sessions[i + k + 1]
        if len(pd.bdate_range(cur + pd.Timedelta(days=1), nxt - pd.Timedelta(days=1))) > 0:
            return True
    return False


def _changed_contracts(prev_rows: pd.DataFrame, cur_rows: pd.DataFrame, col: str) -> tuple[int, int]:
    """两日都在市的合约数,以及其中 col 真的变了的合约数(排除只是分档合约上市/到期让众数翻转的假事件)。"""
    a = prev_rows.set_index("contract")[col]
    b = cur_rows.set_index("contract")[col]
    common = a.index.intersection(b.index)
    if len(common) == 0:
        return 0, 0
    diff = (a.loc[common].to_numpy(dtype=float) - b.loc[common].to_numpy(dtype=float)) != 0
    return int(len(common)), int(np.nansum(diff))


def derive_events(
    store: Store | None,
    exchange: str,
    symbols: Iterable[str] | None = None,
    df: pd.DataFrame | None = None,
    holidays: pd.DatetimeIndex | None = None,
    require_restore: bool = True,
    up_only: bool = True,
) -> pd.DataFrame:
    """从 Store 的 params(或传入的 PARAM_COLS 表 df)推导品种级"上调"事件,输出与 events.csv 同 14 列。

    规则:每日每品种取一般月份档(众数,见 daily_levels);相邻两个参数文件日(相距 ≤MAX_GAP_DAYS 天)比较,
    margin 上升 → param=margin,fee 上升(单位相同)→ param=fee;两日都在市的合约中至少一个真的变了(否则是
    分档合约上市/到期让众数翻转),且不是"≥4 个共同合约里只有 1 个变"(单合约进入交割前月的阶梯)。
    event_date(=effective_date)= 新值首次出现的文件日 D(D 结算起适用,实盘 D 收盘后可见)。
    reason:上调日在休市日(周一至周五的非交易日,历史用交易日集合、未来用 configs/holidays.csv)前 ≤3 个交易日,
    且随后 ≤10 个交易日内一般档回落到不高于原值 → holiday(require_restore=False 时只看前一条件,当日即可判定);其余 derived。
    up_only=False 时下调也输出(direction=down,reason=derived)。"""
    st = store or Store()
    data = df if df is not None else st.read_days(exchange, KIND)
    data = data[data["exchange"] == exchange] if "exchange" in data.columns else data
    if data.empty:
        return pd.DataFrame(columns=EVENT_COLS)
    data = data.copy()
    data["date"] = pd.to_datetime(data["date"])
    sessions = pd.DatetimeIndex(sorted(data["date"].unique()))  # 交易所交易日(全部品种),用于休市日判定
    if symbols is not None:
        data = data[data["symbol"].isin(set(symbols))]
        if data.empty:
            return pd.DataFrame(columns=EVENT_COLS)
    levels = daily_levels(data)
    hol = holidays if holidays is not None else load_holidays()
    full = _sessions_with_future(sessions, hol)
    pos = {d: i for i, d in enumerate(full)}
    by_sym_rows = {s: g.set_index("date") for s, g in data.groupby("symbol")}
    events: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for sym, grp in levels.groupby("symbol"):
        lv = grp.set_index("date").sort_index()
        rows = by_sym_rows[sym]
        dates = lv.index
        for i in range(1, len(dates)):
            d0, d1 = dates[i - 1], dates[i]
            if (d1 - d0).days > MAX_GAP_DAYS:
                dropped["gap"] += 1
                continue
            for param, col, level_col in (("margin", "margin_spec", "margin"), ("fee", "fee_open", "fee")):
                a, b = float(lv.at[d0, level_col]), float(lv.at[d1, level_col])
                if np.isnan(a) or np.isnan(b) or a == b:
                    continue
                if param == "fee" and lv.at[d0, "fee_unit"] != lv.at[d1, "fee_unit"]:
                    dropped["fee_unit_changed"] += 1
                    continue
                if up_only and b < a:
                    continue
                n_common, n_changed = _changed_contracts(rows.loc[[d0]], rows.loc[[d1]], col)
                if n_common and not n_changed:
                    dropped["composition"] += 1
                    continue
                if n_changed == 1 and n_common >= 4:
                    dropped["single_contract"] += 1
                    continue
                reason = "derived"
                if b > a:
                    j = pos[d1]
                    if _closure_ahead(full, j):
                        restored = True
                        if require_restore:
                            window = full[j + 1 : j + 1 + HOLIDAY_RESTORE_SESSIONS]
                            after = lv[level_col].reindex(window).dropna()
                            restored = bool((after <= a + 1e-12).any())
                        if restored:
                            reason = "holiday"
                events.append(
                    {
                        "announce_date": pd.NaT,
                        "effective_date": d1,
                        "exchange": exchange,
                        "symbol": sym,
                        "contract_scope": "all",
                        "param": param,
                        "direction": "up" if b > a else "down",
                        "old_value": a,
                        "new_value": b,
                        "unit": "ratio" if param == "margin" else str(lv.at[d1, "fee_unit"]),
                        "reason": reason,
                        "notice_id": "",
                        "url": main_url(exchange, d1),
                        "notes": DERIVED_NOTE,
                    }
                )
    if dropped:
        log.info("%s derive_events: %d events, dropped %s", exchange, len(events), dict(dropped))
    out = pd.DataFrame(events, columns=EVENT_COLS)
    return out.sort_values(["effective_date", "symbol", "param"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------------------------


def _parse_exchanges(s: str) -> list[str]:
    out = [x.strip().upper() for x in s.split(",") if x.strip()]
    bad = [x for x in out if x not in EXCHANGES]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown exchanges {bad}; choose from {EXCHANGES} (DCE not implemented)"
        )
    return out


def _parse_local(s: str) -> dict[str, Path] | Path:
    """--local-dir 取值:单一目录,或 'SHFE=dir1,INE=dir2,CZCE=dir3'。"""
    if "=" not in s:
        return Path(s)
    out: dict[str, Path] = {}
    for item in s.split(","):
        k, v = item.split("=", 1)
        out[k.strip().upper()] = Path(v.strip())
    return out


def build_cli() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cta.data.exchanges.params", description=__doc__)
    ap.add_argument("--root", type=Path, default=None, help="数据根目录(默认 data/exchanges)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    bf = sub.add_parser("backfill", help="逐日回填(可断点续跑;--local-dir 优先导入已下载文件)")
    bf.add_argument("--start", required=True)
    bf.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    bf.add_argument("--exchanges", type=_parse_exchanges, default=list(EXCHANGES))
    bf.add_argument(
        "--local-dir", type=_parse_local, default=None, help="已下载文件目录,或 SHFE=dir,INE=dir,CZCE=dir"
    )
    bf.add_argument("--retry-missing", action="store_true", help="重试 missing.log 里的日期")
    bf.add_argument("--overwrite", action="store_true", help="从 raw 重新解析并覆盖已有 parquet")
    day = sub.add_parser("day", help="抓取/解析单日(每日增量)")
    day.add_argument("--date", required=True)
    day.add_argument("--exchanges", type=_parse_exchanges, default=list(EXCHANGES))
    day.add_argument("--overwrite", action="store_true")
    dv = sub.add_parser("derive", help="从已落盘 params 推导上调事件(events.csv 同 14 列)")
    dv.add_argument("--exchanges", type=_parse_exchanges, default=list(EXCHANGES))
    dv.add_argument("--symbols", default=None, help="逗号分隔;默认全部")
    dv.add_argument("--out", type=Path, default=Path("data/external/exchange_events/events_derived.csv"))
    dv.add_argument(
        "--no-restore-check", action="store_true", help="节假日判定只看休市日前 ≤3 个交易日(当日可判定)"
    )
    dv.add_argument("--all-directions", action="store_true", help="下调也输出")
    sub.add_parser("coverage", help="每所每年落盘天数")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_cli().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    st = Store(args.root) if args.root else Store()
    if args.cmd == "backfill":
        counts = backfill(
            pd.Timestamp(args.start),
            pd.Timestamp(args.end),
            args.exchanges,
            st,
            local=args.local_dir,
            retry_missing=args.retry_missing,
            overwrite=args.overwrite,
        )
        print(json.dumps(counts, ensure_ascii=False))
    elif args.cmd == "day":
        status = ingest_day(pd.Timestamp(args.date), args.exchanges, st, overwrite=args.overwrite)
        print(json.dumps({"date": args.date, **status}, ensure_ascii=False))
    elif args.cmd == "derive":
        syms = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
        parts = [
            derive_events(
                st, e, syms, require_restore=not args.no_restore_check, up_only=not args.all_directions
            )
            for e in args.exchanges
        ]
        ev = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENT_COLS)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        ev.to_csv(args.out, index=False, date_format="%Y-%m-%d")
        summary = ev.groupby(["exchange", "param", "reason"]).size().to_dict() if not ev.empty else {}
        print(
            json.dumps(
                {"rows": int(len(ev)), "out": str(args.out), "by": {str(k): v for k, v in summary.items()}},
                ensure_ascii=False,
            )
        )
    else:
        print(coverage(st).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "KIND",
    "EXCHANGES",
    "EVENT_COLS",
    "CZCE_CLOSE_TODAY_FROM",
    "CZCE_LIMIT_FROM",
    "CZCE_FEE_STYLE_FROM",
    "CZCE_TRADE_PARAM_FROM",
    "fetch_params",
    "parse_params",
    "parse_shfe_params",
    "parse_czce_params",
    "ingest_day",
    "backfill",
    "coverage",
    "daily_levels",
    "derive_events",
]
