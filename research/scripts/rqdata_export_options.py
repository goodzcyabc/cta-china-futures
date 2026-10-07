"""导出商品期权衍生指标与隐含波动率(米筐 RQData;需要持有 RQData 授权的人在自己的机器上运行)。

本仓库不保存、不输入任何米筐账号或密码。认证完全由运行者自己的环境提供(任选其一):
  - 已执行过 `rqdatac.init()` 可直接使用的环境(例如 license 已写入本机配置);
  - 环境变量 RQDATAC_CONF(rqdatac 支持的 URI 形式),或 RQDATA_USERNAME / RQDATA_PASSWORD(脚本只把它们原样传给 rqdatac.init)。

用法:
  pip install rqdatac
  python research/scripts/rqdata_export_options.py --out rqdata_options_export --start 2017-01-01 --end 2026-09-30
产物(每个标的一组 parquet,可直接打包发回):
  indicators_<SYM>.parquet   options.get_indicators:按到期月份逐日的 PCR(成交额/持仓/成交量)、±0.25 delta IV、skew
  contracts_<SYM>.parquet    options.get_contracts + instruments:合约代码、行权价、到期日、认购/认沽
  greeks_<SYM>.parquet       options.get_greeks(model='implied_forward', price_type='settlement'):逐合约逐日 iv 与 delta(可选,--greeks)
  manifest.json              每次调用的参数、行数、耗时、rqdatac 版本、配额用量(user.get_quota)
注意:米筐试用 license 有 1 GB 流量上限;--greeks 会显著增加流量,默认只导出指标与合约表。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

UNDERLYINGS = [
    "CU",
    "RU",
    "AU",
    "AL",
    "AG",
    "RB",
    "SC",
    "M",
    "C",
    "I",
    "V",
    "P",
    "Y",
    "SR",
    "CF",
    "MA",
    "TA",
    "SA",
    "NI",
    "SN",
]


def init_rqdatac() -> Any:
    try:
        import rqdatac  # type: ignore[import-not-found]
    except ImportError:
        sys.exit("需要先安装 rqdatac:pip install rqdatac")
    user, pwd = os.environ.get("RQDATA_USERNAME"), os.environ.get("RQDATA_PASSWORD")
    if user and pwd:
        rqdatac.init(user, pwd)
    else:
        rqdatac.init()  # 使用本机已有配置或 RQDATAC_CONF
    return rqdatac


def maturities_of(contracts: pd.DataFrame) -> list[str]:
    """到期月份 YYMM 取自标的期货合约代码(CU2503 → 2503);郑商所三位年月(SR505)按期权上市年份补十位。"""
    out: set[str] = set()
    for und, listed in zip(contracts["underlying"].astype(str), contracts["listed_date"]):
        digits = "".join(ch for ch in und if ch.isdigit())
        if len(digits) == 3:
            year = pd.Timestamp(listed).year if pd.notna(listed) else pd.Timestamp.today().year
            decade = (year // 10) % 10
            yy = decade * 10 + int(digits[0])
            if yy < year % 100 - 1:  # 跨十年(例如 2019 年上市的 SR001 → 2020)
                yy += 10
            digits = f"{yy % 100:02d}{digits[1:]}"
        if len(digits) == 4:
            out.add(digits)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="rqdata_options_export")
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    ap.add_argument("--symbols", default=",".join(UNDERLYINGS))
    ap.add_argument("--greeks", action="store_true", help="同时导出逐合约 iv/delta(流量大)")
    args = ap.parse_args()
    rq = init_rqdatac()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "rqdatac_version": getattr(rq, "__version__", "?"),
        "start": args.start,
        "end": args.end,
        "calls": [],
    }
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        t0 = time.time()
        try:
            ids = rq.options.get_contracts(underlying=sym)
        except Exception as e:  # noqa: BLE001
            manifest["calls"].append({"symbol": sym, "error": f"get_contracts: {e}"})
            continue
        if not ids:
            manifest["calls"].append({"symbol": sym, "error": "no option contracts"})
            continue
        inst = rq.instruments(ids)
        rows = [
            {
                "order_book_id": i.order_book_id,
                "underlying": getattr(i, "underlying_order_book_id", None),
                "strike": getattr(i, "strike_price", None),
                "option_type": getattr(i, "option_type", None),
                "listed_date": getattr(i, "listed_date", None),
                "maturity_date": getattr(i, "maturity_date", None),
                "exercise_type": getattr(i, "exercise_type", None),
            }
            for i in (inst if isinstance(inst, list) else [inst])
        ]
        con = pd.DataFrame(rows)
        con.to_parquet(out / f"contracts_{sym}.parquet", index=False)
        frames = []
        for mat in maturities_of(con):
            try:
                df = rq.options.get_indicators(sym, mat, start_date=args.start, end_date=args.end)
            except Exception as e:  # noqa: BLE001
                manifest["calls"].append({"symbol": sym, "maturity": mat, "error": f"get_indicators: {e}"})
                continue
            if df is not None and len(df):
                df = df.reset_index()
                df["maturity"] = mat
                frames.append(df)
        if frames:
            pd.concat(frames, ignore_index=True).to_parquet(out / f"indicators_{sym}.parquet", index=False)
        if args.greeks:
            g = rq.options.get_greeks(
                ids,
                start_date=args.start,
                end_date=args.end,
                fields=["iv", "delta"],
                model="implied_forward",
                price_type="settlement",
            )
            if g is not None and len(g):
                g.reset_index().to_parquet(out / f"greeks_{sym}.parquet", index=False)
        manifest["calls"].append(
            {
                "symbol": sym,
                "n_contracts": len(con),
                "n_indicator_rows": int(sum(len(f) for f in frames)),
                "seconds": round(time.time() - t0, 1),
            }
        )
        print(sym, manifest["calls"][-1], flush=True)
    with contextlib.suppress(Exception):
        manifest["quota"] = str(rq.user.get_quota())
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
