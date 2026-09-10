import numpy as np
import pandas as pd

from cta.continuous.roll import build_symbol_panel, confirmed_dominant


def _fixture():
    dates = pd.bdate_range("2021-01-04", periods=12)
    # 两个合约:A(近月)与 B(次月),A 价 100 平,B 价 90 平;第 7 天起数据商主力切到 B
    rows = []
    for d in dates:
        rows.append(("X2103", d, 100.0, 101, 99, 100.0, 10, 1000 if d < dates[6] else 200))
        rows.append(("X2105", d, 90.0, 91, 89, 90.0, 10, 500 if d < dates[6] else 1500))
        rows.append(("X2107", d, 85.0, 86, 84, 85.0, 5, 100))
    c = pd.DataFrame(
        rows, columns=["contract", "date", "open", "high", "low", "close", "volume", "open_interest"]
    ).set_index(["contract", "date"])
    dm = pd.DataFrame({"date": dates, "symbol": "X", "contract": ["X2103"] * 6 + ["X2105"] * 6})
    meta = pd.DataFrame(
        {
            "symbol": "X",
            "exchange": "DCE",
            "listed_date": pd.Timestamp("2020-01-01"),
            "de_listed_date": pd.to_datetime(["2021-03-15", "2021-05-14", "2021-07-15"]),
            "maturity_date": pd.to_datetime(["2021-03-15", "2021-05-14", "2021-07-15"]),
            "margin_rate": 0.1,
            "multiplier": 10.0,
        },
        index=pd.Index(["X2103", "X2105", "X2107"], name="contract"),
    )
    dd = pd.DataFrame(
        {
            "date": dates,
            "contract": dm["contract"].values,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 0.0,
            "settlement": np.where(np.arange(12) < 6, 100.0, 90.0),
            "prev_settlement": 0.0,
            "limit_up": 108.0,
            "limit_down": 92.0,
            "volume": 0.0,
            "open_interest": 0.0,
        }
    ).set_index("date")
    return dates, c, dm, meta, dd


def test_confirmed_dominant_requires_persistence_and_monotone_maturity() -> None:
    idx = pd.bdate_range("2021-01-01", periods=8)
    cands = pd.Series(["A", "A", "B", "A", "B", "B", "B", "A"], index=idx)
    mat = pd.Series({"A": pd.Timestamp("2021-03-01"), "B": pd.Timestamp("2021-05-01")})
    held = confirmed_dominant(cands, mat, confirm_days=3)
    assert held.tolist() == ["A", "A", "A", "A", "A", "A", "B", "B"]  # 第 3 次连续 B 才切;之后不回滚到 A


def test_build_panel_roll_and_adjustment() -> None:
    dates, c, dm, meta, dd = _fixture()
    p = build_symbol_panel("X", c, dm, meta, dd, confirm_days=3).frame
    roll_days = p.index[p["roll"]]
    assert len(roll_days) == 1 and roll_days[0] == dates[8]  # 第 7 天开始候选为 B,第 9 天(连续 3 天)切换
    assert p.at[roll_days[0], "roll_from"] == "X2103" and p.at[roll_days[0], "roll_from_open"] == 100.0
    # 回溯复权:切换前的历史乘以 90/100,切换后不变 -> 连续价无跳空
    assert abs(p["adj_close"].iloc[0] - 90.0) < 1e-9 and abs(p["adj_close"].iloc[-1] - 90.0) < 1e-9
    # 次主力与到期间隔:持有 X2103 时次主力应为 X2105(OI 更大),间隔 60 天;持有 X2105 时为 X2107
    assert p["next_contract"].iloc[0] == "X2105" and p["days_to_next"].iloc[0] == 60
    assert p["next_contract"].iloc[-1] == "X2107"
    assert p["multiplier"].iloc[0] == 10.0 and p["margin_rate"].iloc[0] == 0.1
    # 结算价:与数据商主力一致时取结算价;切换滞后的两天(第 7、8 天)持有 A 而数据商主力为 B -> 回退为收盘
    assert p["settle"].iloc[0] == 100.0 and p["settle"].iloc[6] == 100.0 and p["settle"].iloc[-1] == 90.0
