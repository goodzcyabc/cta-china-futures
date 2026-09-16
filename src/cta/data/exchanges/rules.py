"""各交易所合约最后交易日规则 → maturity_date(与米筐 maturity_date 同口径:最后交易日)。

规则来源:各交易所合约文本(上线前须逐品种核对,见 docs/data_exchanges.md)。未列出的品种按交易所默认规则。
"""

from __future__ import annotations

import pandas as pd

from cta.data.exchanges.base import symbol_of
from cta.data.exchanges.calendar import TradingCalendar

# 规则代码:
#   shfe15   交割月 15 日(遇假期顺延)                      —— 上期所大多数品种
#   nth10    交割月第 10 个交易日                           —— 大商所、郑商所大多数品种
#   last-4   交割月倒数第 4 个交易日                        —— 大商所鸡蛋
#   prev-last 交割月前一月的最后一个交易日                  —— 能源中心原油/低硫燃料油等
#   fri2     交割月第 2 个周五(遇假期顺延)                  —— 中金所国债
DEFAULT_RULE: dict[str, str] = {
    "SHFE": "shfe15",
    "INE": "prev-last",
    "DCE": "nth10",
    "CZCE": "nth10",
    "CFFEX": "fri2",
}
SYMBOL_RULE: dict[str, str] = {
    "JD": "last-4",
    "SC": "prev-last",
    "LU": "prev-last",
    "NR": "prev-last",
    "BC": "prev-last",
}


def maturity_date(contract: str, exchange: str, cal: TradingCalendar) -> pd.Timestamp:
    sym = symbol_of(contract)
    yy, mm = int(contract[len(sym) : len(sym) + 2]), int(contract[len(sym) + 2 :])
    year = 2000 + yy
    rule = SYMBOL_RULE.get(sym, DEFAULT_RULE[exchange])
    if rule == "shfe15":
        return cal.next_session_on_or_after(pd.Timestamp(year=year, month=mm, day=15))
    if rule == "nth10":
        return cal.nth_session_of_month(year, mm, 10)
    if rule == "last-4":
        return cal.nth_session_of_month(year, mm, -4)
    if rule == "prev-last":
        first = pd.Timestamp(year=year, month=mm, day=1)
        return cal.prev_session_on_or_before(first - pd.Timedelta(days=1))
    if rule == "fri2":
        first = pd.Timestamp(year=year, month=mm, day=1)
        fridays = pd.date_range(first, first + pd.offsets.MonthEnd(0), freq="W-FRI")
        return cal.next_session_on_or_after(fridays[1])
    raise ValueError(rule)
