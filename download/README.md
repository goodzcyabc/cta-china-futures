# download/: 米筐 RQData 批量下载

把 alpha 研究所需要的米筐数据全部落到 `data/ricecta/data/`(**随仓库分发**;按体积仅排除未下载的 `futures_tick/` 抽样、`dominant_contracts/_pieces/` 中间分片与下载日志),输出 parquet,
与既有米筐导出口径(`RicequantParquetSource`、`research/scripts/exec_fills.py`)兼容。
脚本幂等、断点续跑;试用账号每天 1 GiB 流量,`run_all.sh` 被配额截断后**第二天原样重跑**即可续。

## 环境

```bash
uv pip install --python .venv/bin/python rqdatac          # 认证走环境变量,不写进仓库
export RQDATAC_CONF='...'                                  # 或 RQDATA_USERNAME/RQDATA_PASSWORD
```

## 运行

```bash
download/run_all.sh                 # 全量:meta → 指数 → daily → 非量价 → 宏观 → 5 分钟 → 期权 → 校验
download/run_all.sh --no-5m         # 跳过 5 分钟线(轻量数据,几分钟跑完)
nohup download/continue_daily.sh >> download/run.log 2>&1 &   # 配额自动续跑(多日无人值守)
.venv/bin/python download/download_5minute.py --check    # 查看 5 分钟线进度
.venv/bin/python download/validate.py                    # 校验产物 schema / 不变量
.venv/bin/python download/check_5m.py --fix              # 5 分钟线全量清洁性检查(仅修 OHLC 越界)
```

逐表细节见各脚本 docstring;`--symbols CU,RB`、`--limit N`(冒烟)、`--force`(重下)通用。

## 数据清单

| 目录(data/ricecta/data/) | 内容 | 脚本 | 用途 |
|---|---|---|---|
| `universe/futures_instruments.parquet` | 全部期货合约基础信息(上市/退市、乘数、保证金) | download_meta.py | 合约宇宙 |
| `dominant_contracts/dominant*.parquet` | 主力/次主力/次次主力 + rule=1 主力 | download_meta.py | 主力选择、规则敏感性 |
| `indices/commodity_indices.parquet` | 中证 CFCI/CFI 等 35 个商品期货相关指数 | download_indices.py | 板块 regime、中性化参考 |
| `contracts_daily/<SYM>.parquet` | 合约级日线 OHLCV+成交额+持仓量 | download_daily.py | 数据层基座 |
| `contracts_daily/metadata.parquet` | 合约元数据 | download_daily.py | 数据层 |
| `dominant_daily/<SYM>.parquet` | 主力连续日线(前复权,含结算/涨跌停) | download_daily.py | 与既有导出口径一致 |
| `exchange_daily/<SYM>.parquet` | 交易所日线(官方结算价/成交额) | download_daily.py | 结算价核对、官方口径 |
| `continuous/<SYM>.parquet` | 近月/次月连续合约 | download_daily.py | 期限结构/日历价差 |
| `roll_yield/<SYM>.parquet` | 米筐展期收益率(main_sub / near_main) | download_daily.py | carry 因子对照 |
| `futures_5minute/<SYM>/<CONTRACT>.parquet` | 5 分钟线(全合约,2016 起;**入库**,7,430 个合约 / 约 560 MiB) | download_5minute.py | 执行研究、日内特征 |
| `warehouse_stocks/<SYM>.parquet` | 注册仓单(含有效预报/可交割量) | download_nonprice.py | 仓单因子、补大商所 |
| `member_rank/<SYM>.parquet` | 会员持仓排名(volume/long/short) | download_nonprice.py | 持仓因子、补历史缺口 |
| `trading_parameters/<SYM>.parquet` | 逐合约逐日保证金/手续费/限仓 | download_nonprice.py | 成本模型、监管事件层(补 DCE/CZCE) |
| `options/contracts*.parquet` | 商品期权合约表 | download_options.py | 期权数据层 |
| `options/dominant_month/<SYM>.parquet` | 期权主力/次主力月份 | download_options.py | 期权链组织 |
| `options/indicators/<SYM>.parquet` | 逐到期月 PCR/IV/skew | download_options.py | 期权情绪/波动因子,补 DCE 缺口 |
| `options/greeks/<SYM>.parquet` | 逐合约 iv/Delta(可选 `--greeks`) | download_options.py | 期权定价 |
| `shibor/shibor.parquet` | SHIBOR 全期限 | download_macro.py | 资金面/无风险利率 |
| `econ/macro_factors.parquet` | 米筐全量宏观因子(4006 个,带发布时点) | download_macro.py | 宏观状态/regime |
| `econ/money_supply.parquet`, `econ/reserve_ratio.parquet` | 货币供应、准备金率 | download_macro.py | 货币环境 |
| `spot/sge_daily/*.parquet`, `spot/sge_benchmark.parquet` | 上金所现货日线、早午盘基准价 | download_macro.py | 贵金属现期基差 |
| `futures_tick/...`(默认不跑) | tick 抽样 | download_tick.py | 微观结构校准 |

## 流量与配额(试用 1 GiB/天)

- 服务端按**传输量**计费:同一份数据 `fields` 全字段约 250 B/行,只取所需 8 字段约 12 B/行
  —— 5 分钟线必须传 `fields`(脚本已内置)。
- `QuotaGuard` 在用量 > 92% 或 license 剩余 ≤ 2 天时抛 `QuotaExhausted`,脚本退出码 3,
  `run_all.sh` 随即停止,避免硬撞配额。
- 各表体量参考:日频 ~250 MiB、非量价 ~300 MiB、宏观 ~40 MiB、期权 ~50 MiB、
  **5 分钟线 ~1–1.5 GiB**(最大头,按品种顺序跑,生产 22 品种优先)。
- 每次运行的进度与耗时追加到 `data/ricecta/download_log.jsonl`。

## 压缩格式(2026-10-17 起)

- 写盘统一走 `rq_common.write_parquet`:全表只有浮点/时间列时用
  zstd-18 + 浮点列 `BYTE_STREAM_SPLIT` + 时间列 `DELTA_BINARY_PACKED`;
  含字符串等其它类型的表保持默认字典编码(两套逐列编码不能混用)。
- AB 测试(23 文件 / 39.8 万行):9.0 MiB → 3.1 MiB(2.9x),读取耗时与 snappy 持平。
  收益大头是时间列:snappy 下 datetime 索引约 7.6 B/行(全表 23.8 B/行),delta 后约 0.3 B/行;
  其次是把浮点字典编码让位给 BYTE_STREAM_SPLIT。
- 存量重写实测:1,714 个文件 570 → 179 MiB(**3.19x**,0 失败,193s);其余文件下载时即按新编码写盘,
  5 分钟线全量(7,430 文件)约 557 MiB。
- 存量文件重写:`download/recompress.py --table futures_5minute`(幂等:已优化的跳过、
  不可优化的表跳过;逐文件 `DataFrame.equals` 校验无损)。

## 口径与注意事项

- 只下载**真实合约**:米筐的人工合成连续合约(命名含"连续",代码以 88/888/889/99/88A2 结尾,
  价格经复权平滑、可能为负)一律排除,否则 `validate_contracts` 会因非正价格报错。
  需要连续价请用 `dominant_daily/` 或 `continuous/`。

- 5 分钟线 index 为 bar 结束时间(夜盘归属下一交易日),列
  `open/high/low/close/volume/total_turnover/open_interest/trading_date`,字段集与既有导出一致;
  约一半 bar 零成交、郑商所 `total_turnover` 不能反推价格等已知特性见 `docs/data/data_notes.md`「5 分钟线」,
  清洁性检查/修复用 `download/check_5m.py --fix`。
- `dominant_daily` 使用前复权(`adjust_type='pre'`, `prev_close_spread`),与既有导出口径一致;
  原始价请用 `contracts_daily` / `exchange_daily`。
- `metadata.parquet` 的 `margin_rate` 是米筐的"临近交割抬高后"值,细节见 `docs/data/data_notes.md`。
- 入库口径:`data/ricecta/data/` 全部随仓库分发(含 5 分钟线);仅 `futures_tick/`(默认不跑)、`dominant_contracts/_pieces/`、`download_log.jsonl` 与 `*.tmp`(原子写临时文件)不入库。
