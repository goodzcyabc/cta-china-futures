"""把已下载的 parquet 重写为优化编码(zstd-18 + 浮点 BYTE_STREAM_SPLIT + 时间列 delta)。

新下载的文件由 `rq_common.write_parquet` 自动使用优化编码;本脚本用于回头重写存量文件。
幂等:已是优化编码的文件跳过;`--dry-run` 只统计待重写数量与体积。

实测(5 分钟线 23 文件 / 39.8 万行样本):9.0 MiB -> 3.1 MiB(2.9x),读取耗时不变。
写前写后逐文件校验 `DataFrame.equals`(无损)。

用法:
  .venv/bin/python download/recompress.py --table futures_5minute [--dry-run] [--limit N]
  .venv/bin/python download/recompress.py --table futures_5minute,contracts_daily
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rq_common as rc  # noqa: E402


def is_optimized(path: Path) -> bool:
    """文件里已有 BYTE_STREAM_SPLIT 或 DELTA_BINARY_PACKED 编码即视为已优化。"""
    md = pq.ParquetFile(path).metadata
    for i in range(md.row_group(0).num_columns):
        encodings = md.row_group(0).column(i).encodings
        if "BYTE_STREAM_SPLIT" in encodings or "DELTA_BINARY_PACKED" in encodings:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True, help="表目录名(相对 data/ricecta/data),逗号分隔")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个文件(冒烟)")
    args = ap.parse_args()

    files: list[Path] = []
    for table in args.table.split(","):
        files += sorted((rc.DATA_ROOT / table.strip()).rglob("*.parquet"))
    if args.limit:
        files = files[: args.limit]

    pending = [p for p in files if not is_optimized(p)]
    if args.dry_run:
        sz = sum(p.stat().st_size for p in pending)
        print(f"{len(files)} 个文件:待重写 {len(pending)} 个({sz / 2**20:.1f} MiB),其余已是优化编码")
        return 0

    before = after = failed = skipped = 0
    t0 = time.time()
    for p in files:
        before += p.stat().st_size
        if p not in pending:
            skipped += 1
            after += p.stat().st_size
            continue
        try:
            df = pd.read_parquet(p)
            if rc.column_encodings(df) is None:  # 含字符串等类型,不适用逐列编码,保持原样
                skipped += 1
                after += p.stat().st_size
                continue
            rc.write_parquet(df, p)
            got = pd.read_parquet(p)
            assert got.equals(df), "重写后数据不一致"
        except Exception as e:  # noqa: BLE001 - 单文件失败不中断整批
            failed += 1
            print(f"失败 {p}: {e}")
            continue
        after += p.stat().st_size
    print(
        f"{len(files)} 个文件: {before / 2**20:.1f} -> {after / 2**20:.1f} MiB "
        f"({before / max(after, 1):.2f}x),跳过 {skipped},失败 {failed},"
        f"用时 {time.time() - t0:.0f}s"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
