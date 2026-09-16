"""交易日历:已观察到的交易日(有行情文件的日期)∪ 未来工作日 − 已公告假期(configs/holidays.csv)。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cta.data.exchanges.base import Store


def load_holidays(path: Path | None = None) -> pd.DatetimeIndex:
    p = path or (Path(__file__).resolve().parents[4] / "configs" / "holidays.csv")
    if not p.exists():
        return pd.DatetimeIndex([])
    df = pd.read_csv(p, comment="#")
    out: pd.DatetimeIndex = pd.DatetimeIndex(pd.to_datetime(df["date"])).sort_values()
    return out


class TradingCalendar:
    """observed:所有交易所行情文件的日期并集;未来日期用工作日减假期。"""

    def __init__(self, store: Store | None = None, holidays: pd.DatetimeIndex | None = None):
        st = store or Store()
        observed: set[pd.Timestamp] = set()
        for e in ("SHFE", "INE", "DCE", "CZCE"):
            observed.update(st.days(e, "quotes"))
        self.observed = pd.DatetimeIndex(sorted(observed))
        self.holidays = (
            holidays if holidays is not None else load_holidays(st.root / "calendar" / "holidays.csv")
        )

    def sessions(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
        start, end = pd.Timestamp(start), pd.Timestamp(end)
        last_obs = self.observed.max() if len(self.observed) else pd.Timestamp("1900-01-01")
        obs = self.observed[(self.observed >= start) & (self.observed <= end)]
        fut_start = max(start, last_obs + pd.Timedelta(days=1))
        fut = pd.bdate_range(fut_start, end) if fut_start <= end else pd.DatetimeIndex([])
        fut = fut[~fut.isin(self.holidays)]
        return pd.DatetimeIndex(sorted(set(obs) | set(fut)))

    def is_session(self, d: pd.Timestamp) -> bool:
        d = pd.Timestamp(d)
        if len(self.observed) and d <= self.observed.max():
            return d in self.observed
        return d.weekday() < 5 and d not in self.holidays

    def nth_session_of_month(self, year: int, month: int, n: int) -> pd.Timestamp:
        s = self.sessions(
            pd.Timestamp(year=year, month=month, day=1),
            pd.Timestamp(year=year, month=month, day=28) + pd.offsets.MonthEnd(0),
        )
        if len(s) < abs(n):
            raise ValueError(f"month {year}-{month} has only {len(s)} sessions")
        return s[n - 1] if n > 0 else s[n]

    def next_session_on_or_after(self, d: pd.Timestamp) -> pd.Timestamp:
        d = pd.Timestamp(d)
        s = self.sessions(d, d + pd.Timedelta(days=20))
        return s[0]

    def prev_session_on_or_before(self, d: pd.Timestamp) -> pd.Timestamp:
        d = pd.Timestamp(d)
        s = self.sessions(d - pd.Timedelta(days=20), d)
        return s[-1]
