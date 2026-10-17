"""米筐 RQData 批量下载脚本的公共工具:初始化、配额守卫、断点续跑、原子写 parquet。

所有下载脚本共用本模块。数据写到 data/ricecta/data/<table>/...(与既有米筐导出口径一致,
data/ricecta/data 是 RicequantParquetSource 的默认根)。认证只来自运行者环境
(RQDATAC_CONF / RQDATA_USERNAME+RQDATA_PASSWORD),本仓库不保存任何账号信息。

配额:试用账户 1 GiB/天(服务端按传输流量计,字段越多越贵)。QuotaGuard 在用量超过
limit*fraction 时抛 QuotaExhausted,脚本据此干净退出;下次重跑时已写好的文件会被跳过。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "ricecta" / "data"
LOG_PATH = ROOT / "data" / "ricecta" / "download_log.jsonl"

DEFAULT_START = "2016-01-01"
COMMODITY_EXCHANGES = ("SHFE", "INE", "DCE", "CZCE", "GFEX")
# 生产品种池(configs/strategy_v03.yaml);5 分钟线按此顺序优先下载
PRODUCTION_SYMBOLS = [
    "AG",
    "AL",
    "AU",
    "C",
    "CF",
    "CU",
    "I",
    "J",
    "JD",
    "M",
    "MA",
    "NI",
    "P",
    "RB",
    "RU",
    "SA",
    "SC",
    "SN",
    "SR",
    "TA",
    "V",
    "Y",
]


class QuotaExhausted(RuntimeError):  # noqa: N818 - 名字沿用各脚本的 except 分支
    """当日流量配额接近上限或 license 快到期,留给下一天续跑。"""


def init() -> Any:
    """初始化 rqdatac(认证来自环境变量/RQDATAC_CONF),返回模块。"""
    try:
        import rqdatac
    except ImportError:
        raise SystemExit("需要先安装 rqdatac:uv pip install --python .venv/bin/python rqdatac") from None
    rqdatac.init()
    return rqdatac


class QuotaGuard:
    """每 n 次调用查一次配额;超过阈值抛 QuotaExhausted。"""

    def __init__(self, rqdatac: Any, fraction: float = 0.92, every: int = 20) -> None:
        self._rq = rqdatac
        self._fraction = fraction
        self._every = every
        self._n = 0

    def tick(self) -> None:
        self._n += 1
        if self._n % self._every == 0:
            self.check()

    def check(self) -> None:
        q = self._rq.user.get_quota()
        used, limit = float(q.get("bytes_used", 0)), float(q.get("bytes_limit", 0))
        if limit and used > limit * self._fraction:
            raise QuotaExhausted(f"流量已用 {used / 2**20:.0f} MiB / {limit / 2**20:.0f} MiB,停止下载")
        if int(q.get("remaining_days", 99)) <= 2:
            raise QuotaExhausted(f"license 剩余 {q.get('remaining_days')} 天,停止下载")

    def bytes_used(self) -> int:
        return int(self._rq.user.get_quota().get("bytes_used", 0))


def record(**fields: Any) -> None:
    """把一次下载的结果追加到 download_log.jsonl(审计用,失败不影响主流程)。"""
    row = {"ts": datetime.now().isoformat(timespec="seconds"), **fields}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def write_parquet(df: pd.DataFrame, path: Path, index: bool = True) -> None:
    """原子写 parquet:先写 .tmp 再 rename,避免半截文件被当成已完成。

    全表(含索引)只有浮点/时间列时用高压缩编码:zstd-18 + 浮点列 BYTE_STREAM_SPLIT +
    时间列 DELTA_BINARY_PACKED(等差时间戳每行 <0.5 B)。实测 5 分钟线体积 ~2.9x、
    读取耗时不变(AB 测试见 README「压缩格式」)。含字符串等其它类型的表保持默认字典编码。
    """
    if df is None or len(df) == 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    enc = column_encodings(df)
    if enc is None:
        df.to_parquet(tmp, index=index)
    else:
        import pyarrow as pa
        import pyarrow.parquet as pq

        pq.write_table(
            pa.Table.from_pandas(df, preserve_index=index),
            tmp,
            compression="zstd",
            compression_level=18,
            use_dictionary=False,
            column_encoding=enc,
        )
    os.replace(tmp, path)


def column_encodings(df: pd.DataFrame) -> dict[str, str] | None:
    """全表只有浮点/时间列时给出逐列编码;出现其它类型(含字符串索引)返回 None 走默认。"""
    enc: dict[str, str] = {}

    def add(name: str, dtype: Any) -> bool:
        if pd.api.types.is_float_dtype(dtype):
            enc[name] = "BYTE_STREAM_SPLIT"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            enc[name] = "DELTA_BINARY_PACKED"
        else:
            return False
        return True

    if isinstance(df.index, pd.DatetimeIndex):
        if not add(str(df.index.name or "__index_level_0__"), df.index.dtype):
            return None
    elif not isinstance(df.index, pd.RangeIndex):
        return None
    for name, dtype in df.dtypes.items():
        if not add(str(name), dtype):
            return None
    return enc or None


def retry[T](fn: Callable[[], T], attempts: int = 3, wait: float = 5.0) -> T:
    """对网络类错误重试;配额错误不重试。循环里按批调用时用 functools.partial 绑定当前批次,不要用带默认参数的 lambda。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except QuotaExhausted:
            raise
        except Exception as e:  # noqa: BLE001 - rqdatac 抛各种网络/服务端异常
            last = e
            if i < attempts - 1:
                time.sleep(wait * (i + 1))
    raise RuntimeError(f"重试 {attempts} 次仍失败: {last}") from last


def chunked(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def load_universe() -> pd.DataFrame:
    """全部期货合约基础信息(先运行 download_meta.py 生成)。"""
    path = DATA_ROOT / "universe" / "futures_instruments.parquet"
    if not path.exists():
        raise SystemExit(f"缺少 {path},先运行 download/download_meta.py")
    df = pd.read_parquet(path)
    df["listed_date"] = pd.to_datetime(df["listed_date"], errors="coerce")
    df["de_listed_date"] = pd.to_datetime(df["de_listed_date"], errors="coerce")
    return df


def commodity_symbols(universe: pd.DataFrame) -> list[str]:
    """商品期货品种(排除中金所金融期货),按生产池优先排序。"""
    syms = sorted(universe.loc[universe["exchange"].isin(COMMODITY_EXCHANGES), "underlying_symbol"].unique())
    pri = {s: i for i, s in enumerate(PRODUCTION_SYMBOLS)}
    return sorted(syms, key=lambda s: (pri.get(s, 10_000), s))


def contracts_since(universe: pd.DataFrame, symbol: str, start: str) -> list[str]:
    """start 以后还活着(退市日在 start 之后)的真实合约,按代码排序。

    合成连续合约(主力连续 88/888/889、指数连续 99、次主力 88A2)没有上市日,一律排除:
    它们价格经过复权平滑(可能出现负数),混入合约级数据会破坏 validate_contracts。
    """
    sub = universe[universe["underlying_symbol"] == symbol].copy()
    start_ts = pd.Timestamp(start)
    real = sub["listed_date"].notna()
    alive = real & (sub["de_listed_date"].isna() | (sub["de_listed_date"] >= start_ts))
    return sorted(sub.loc[alive, "order_book_id"].tolist())
