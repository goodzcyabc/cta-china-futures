"""5 分钟线清洁性全量检查与最小修复。

检查(逐文件全量):
- 目录/文件命名合规,无合成连续合约(88/888/889/99/88A2)
- 恰为 8 列、数值列 float32、索引为无时区 DatetimeIndex('datetime')
- 索引单调、唯一、落在 5 分钟整点网格
- OHLC 无 NaN/非正;low <= open/close <= high(容差 0.05,float32 精度)
- volume/total_turnover/open_interest >= 0
- trading_date:不早于自然日、滞回 <= 7 天、单调

`--fix` 只做一种修复:把越界的 high/low 放宽到包含 open/close。依据:open/close 都是
成交价,high/low 必须包含它们;此类越界是米筐在交割月单笔成交 bar 上的偶发瑕疵
(2022-09 C2209、2023-06 JM2307 各 1 行)。放宽方向由该行自身可证,不改任何价格字段本身。
其余异常只报告不修改。

用法:
  .venv/bin/python download/check_5m.py          # 只检查
  .venv/bin/python download/check_5m.py --fix    # 检查并修复 OHLC 越界
退出码:0 = 干净(或修复后干净);1 = 有问题。
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rq_common as rc  # noqa: E402

ROOT = rc.DATA_ROOT / "futures_5minute"
# 合约代码:基础字母 + 4 位 YYMM + 可选后缀字母(大商所月均价品种 L2602F/PP2602F/V2602F);
# 合成连续(88/888/889/99/88A2)是 2-3 位数字,匹配不上 4 位模式,自然被排除。
NAME = re.compile(r"^([A-Z]{1,3})(\d{4})([A-Z]{1,2})?$")
SYM = re.compile(r"^[A-Z]{1,3}(_[A-Z]{1,2})?$")
SYNTH_SUFFIX = ("88", "888", "889", "99", "88A2")
COLS = ["open", "high", "low", "close", "volume", "total_turnover", "open_interest", "trading_date"]
FLOATS = COLS[:-1]
TOL = 0.05  # float32 在 1e5 量级的 ulp ~0.008


def check_file(p: Path, problems: list[str], fix: bool) -> list[str]:
    fixes: list[str] = []
    sym, stem = p.parent.name, p.stem

    def bad(msg: str) -> None:
        problems.append(f"{p}: {msg}")

    if not SYM.fullmatch(sym):
        bad(f"目录名异常 {sym!r}")
    m = NAME.match(stem)
    if m is None:
        bad("文件名不合规")
    else:
        expect_dir = f"{m.group(1)}_{m.group(3)}" if m.group(3) else m.group(1)
        if expect_dir != sym:
            bad(f"合约前缀与目录不符 ({expect_dir} vs {sym})")
        if stem.endswith(SYNTH_SUFFIX):
            bad("疑似合成/连续合约")
    df = pd.read_parquet(p)
    if list(df.columns) != COLS:
        bad(f"列异常 {list(df.columns)}")
        return fixes
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.name != "datetime":
        bad("索引非 DatetimeIndex('datetime')")
    elif df.index.tz is not None:
        bad("索引带时区")
    else:
        if not df.index.is_monotonic_increasing:
            bad("索引非单调")
        if not df.index.is_unique:
            bad("索引有重复")
        if (df.index.second != 0).any() or (df.index.minute % 5 != 0).any():
            bad("时间戳不在 5 分钟整点网格上")
    for c in FLOATS:
        if df[c].dtype != "float32":
            bad(f"{c} dtype={df[c].dtype}")
    if not pd.api.types.is_datetime64_any_dtype(df["trading_date"]):
        bad(f"trading_date dtype={df['trading_date'].dtype}")
    if df[COLS].isna().any().any():
        bad("存在 NaN")
    else:
        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            bad("存在非正价格")
        if (df[["volume", "total_turnover", "open_interest"]] < 0).any().any():
            bad("存在负值(volume/turnover/oi)")
        bad_hl = (
            (df["low"] > df["high"] + TOL)
            | (df["open"] > df["high"] + TOL)
            | (df["open"] < df["low"] - TOL)
            | (df["close"] > df["high"] + TOL)
            | (df["close"] < df["low"] - TOL)
        )
        if bad_hl.any():
            if not fix:
                bad("OHLC 越界")
            else:
                for ts in df.index[bad_hl]:
                    old_hi, old_lo = df.at[ts, "high"], df.at[ts, "low"]
                    df.at[ts, "high"] = max(old_hi, df.at[ts, "open"], df.at[ts, "close"])
                    df.at[ts, "low"] = min(old_lo, df.at[ts, "open"], df.at[ts, "close"])
                    fixes.append(
                        f"{p} {ts}: high {old_hi}->{df.at[ts, 'high']}, low {old_lo}->{df.at[ts, 'low']}"
                    )
                still = (
                    (df["low"] > df["high"] + TOL)
                    | (df["open"] > df["high"] + TOL)
                    | (df["open"] < df["low"] - TOL)
                    | (df["close"] > df["high"] + TOL)
                    | (df["close"] < df["low"] - TOL)
                )
                if still.any():
                    bad("OHLC 越界(修复后仍有)")
    if isinstance(df.index, pd.DatetimeIndex) and pd.api.types.is_datetime64_any_dtype(df["trading_date"]):
        d = df.index.normalize()
        if (df["trading_date"] < d).any():
            bad("trading_date 早于自然日")
        if (df["trading_date"] > d + pd.Timedelta(days=7)).any():
            bad("trading_date 滞后超 7 天")
        if not df["trading_date"].is_monotonic_increasing:
            bad("trading_date 非单调")
    if fixes:
        rc.write_parquet(df, p)
        assert pd.read_parquet(p).equals(df), f"{p}: 修复写回校验失败"
    return fixes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="修复 OHLC 越界(high/low 放宽到包含 open/close)")
    args = ap.parse_args()

    files = sorted(ROOT.rglob("*.parquet"))
    problems: list[str] = []
    fixes: list[str] = []
    t0 = time.time()
    for i, p in enumerate(files, 1):
        fixes += check_file(p, problems, args.fix)
        if i % 1000 == 0:
            print(f"  ... {i}/{len(files)}", flush=True)
    for f in fixes:
        print("修复:", f)
    print(f"\n{len(files)} 个文件,{time.time() - t0:.0f}s:问题 {len(problems)} 条,修复 {len(fixes)} 处")
    for q in problems[:40]:
        print("  ", q)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
