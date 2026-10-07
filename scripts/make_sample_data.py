"""从本地交易所直连数据(data/exchanges/)抽一份小样例,打包成 data/sample/exchanges_sample.tar.gz。

样例只含交易所官网公开发布的数据(行情含官方结算价、仓单),不含米筐导出。
内容:上期所 CU、RB,大商所 M,郑商所 SR;2021-01-04 → 2024-12-31;布局与 data/exchanges/ 相同,
解压后可直接给 ExchangeSource 用(见 configs/sample.yaml 与 tests/test_sample_data.py)。

用法:python scripts/make_sample_data.py [--src data/exchanges] [--out data/sample/exchanges_sample.tar.gz]
"""

from __future__ import annotations

import argparse
import gzip
import tarfile
import tempfile
from pathlib import Path

import pandas as pd

SYMBOLS = {"SHFE": ["CU", "RB"], "DCE": ["M"], "CZCE": ["SR"]}
KINDS = ("quotes", "receipts")
START, END = "20210104", "20241231"


def _normalize(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0, 0, 0, "", ""
    return ti


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/exchanges")
    ap.add_argument("--out", default="data/sample/exchanges_sample.tar.gz")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_files = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "exchanges"
        for ex, syms in SYMBOLS.items():
            for kind in KINDS:
                for f in sorted((src / ex / kind).glob("*/*.parquet")):
                    if not (START <= f.stem <= END):
                        continue
                    d = pd.read_parquet(f)
                    d = d[d["symbol"].isin(syms)]
                    if d.empty:
                        continue
                    dst = root / ex / kind / f.parent.name / f.name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    d.to_parquet(dst, index=False)
                    n_files += 1
        # 固定时间戳与属主,同样输入重跑得到逐字节相同的压缩包(不产生无意义的 git 差异)
        with gzip.GzipFile(out, "wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
            tar.add(root, arcname="exchanges", filter=_normalize)
    print(f"{n_files} files -> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
