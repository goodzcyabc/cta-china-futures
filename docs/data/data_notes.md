# 数据说明与已踩的坑

来源:米筐(Ricequant)导出,存于 `data/ricecta/data`,**随仓库分发**(由 `download/` 脚本生成,见文末「自建导出」;按体积仅排除未下载的 `futures_tick/` 抽样、`dominant_contracts/_pieces/` 中间分片与下载日志)。覆盖全部商品品种,2016-01-01 起(替换原 23 品种、2016-01-04 至 2026-06-05 的本地导出口径,表结构兼容)。

基准:`data/benchmarks/nhci_daily.csv` 为南华商品指数(NHCI,收益率指数)日收盘,2004-06-01 至 2026-09-11,取自南华期货官网行情网关(webhq.nanhua.net,WebSocket/protobuf,无 HTTP 接口;旧 akshare 接口已失效),2024-12-24 与 2025-12-19 两个点位已对照南华官方日报核验;随仓库分发(公开数据,125 KB)。

| 表 | 用途 | 注意 |
|---|---|---|
| `contracts_daily/<SYM>.parquet` | 合约级 OHLCV + 持仓量,(contract, date) 双索引 | 无结算价;结算以收盘价近似 |
| `contracts_daily/metadata.parquet` | 合约到期日、上市/退市日、乘数、保证金率 | **margin_rate 是临近交割抬高后的值**(CU 0.20 vs 常规 0.10),不能当日常保证金;`symbol` 列是中文简称,与品种代码列冲突 |
| `dominant_contracts/dominant.parquet` | 数据商每日主力合约 | 直接切换会产生回滚;本项目加 3 日确认且只向更晚到期切换 |
| `dominant_daily/<SYM>.parquet` | 主力连续日线(含结算价、涨跌停) | **是复权后的连续价**(与原始合约收盘比值 0.93–1.02),不能与原始合约价混用;本项目不使用 |
| `spot_basis/*.parquet` | 现货与基差 | 未用于 v0.1 |
| `shibor/shibor.parquet` | 利率 | 闲置资金收益的可选项(默认 0) |

品种覆盖:SA 自 2019-12、SC 自 2018-03,其余自 2016-01。TF(国债)为金融期货,不在商品 CTA 品种池。

展期收益的"次主力"到期间隔:金属(CU/AL/NI/SN)约 31 天、贵金属约 62 天、多数农产品与化工约 120 天(1/5/9 月合约)。
间隔越长,年化 carry 越受季节性影响;鸡蛋(JD)尤其明显(见设计日志二c)。

上线替换数据源时必须核对:合约乘数与跳价、涨跌幅与保证金的当日值、主力切换规则、夜盘日切与交易日历。

## 5 分钟线(`futures_5minute/`)

全库 7,430 个合约文件、约 560 MiB,**随仓库分发**(克隆仓库前留意体积)。

- 布局:`futures_5minute/<品种>/<合约>.parquet`(目录=米筐 `underlying_symbol`,文件=`order_book_id`);含大商所 2025-10 起的月均价品种 `L_F`/`PP_F`/`V_F`(如 `L2602F.parquet`,以月均价交割);合成连续合约(88/888/889/99/88A2)不在库内。
- 字段:8 列 `open/high/low/close/volume/total_turnover/open_interest/trading_date`,均为 float32;索引 `datetime` 是 **bar 结束时间**(夜盘 21:00–02:30 的 bar 归属下一交易日,`trading_date` 即该交易日)。合约乘数在 `contracts_daily/metadata.parquet`。
- 覆盖 2016-01 起全部商品品种的真实合约,读法 `pd.read_parquet('data/ricecta/data/futures_5minute/CU/CU2610.parquet')`;文件为 zstd-18 + `BYTE_STREAM_SPLIT` + 时间列 delta 编码(见 `download/README.md`「压缩格式」),标准 pandas/pyarrow 直接可读。
- 数据质量(交付前已全量检查;工具 `download/check_5m.py --fix`,可随时复跑):
  - 命名/schema/索引单调唯一/5 分钟整点网格/无 NaN/无负值/OHLC 包含关系:全量通过。
  - **约一半 bar 零成交**(`volume=0`,OHLC 为上一成交价填充;冷门与交割月合约尤其多)——任何执行价、滑点、VWAP 计算必须先按 `volume>0` 过滤(设计日志 23.2 的"交割月假价差"即此类陷阱)。
  - **郑商所(CZCE)的 `total_turnover` 不能反推价格**:约 67% 的 bar 反推均价 `total_turnover/(volume×乘数)` 落在 [low, high] 之外(上期所/大商所/能源 ≤0.7%),并有跨 bar 同值重复;与现拉米筐数据逐值一致,属供应商口径问题,不是本仓库处理引入。要么不用该字段,要么均价直接用 OHLC 构造。
  - 极少数 bar `volume>0` 而 `total_turnover=0`(或反之):全库约 880 行 / 5300 万行,供应商边界情况,原样保留。
  - 两处交割月单笔成交 bar 的供应商 OHLC 越界已做最小修复(仅把 high/low 放宽到包含 open/close,未改动任何价格字段本身):`C/C2209` 2022-09-05 09:20 high 2717→2725;`JM/JM2307` 2023-06-09 22:05 high 1320→1341.5。除此之外与米筐原始数据逐值一致(已抽查比对)。

## 自建导出(`download/`,2026-10-15 起)

`download/` 下的脚本用 rqdatac 自建同口径导出(试用账号 1 GiB/天;幂等、断点续跑,配额不足时退出码 3,第二天重跑续)。完整清单和运行方式见 `download/README.md`。

- 兼容既有接口:`contracts_daily/<SYM>.parquet`(多一列 `total_turnover`)、`contracts_daily/metadata.parquet`、`dominant_contracts/dominant.parquet`、`dominant_daily/<SYM>.parquet`(前复权)、`shibor/shibor.parquet`、`futures_5minute/<SYM>/<CONTRACT>.parquet`(8 字段,trading_date 有夜盘日切语义;**已入库**,见上文「5 分钟线」)。
- 新增表:`universe/futures_instruments.parquet`(全合约基础信息)、`dominant2/dominant3/dominant_rule1`、`indices/commodity_indices.parquet`(中证 CFCI/CFI 等 35 个商品期货指数,2010 起)、`exchange_daily/<SYM>.parquet`(官方结算价),`continuous/`(近月/次月)、`roll_yield/`(米筐 carry)、`warehouse_stocks/`(补大商所)、`member_rank/`、`trading_parameters/`(保证金/手续费/限仓:SHFE 2013-10、DCE 2018-12、CZCE 2021-04 起)、`options/`(合约/主力月份/PCR/IV/skew,补 DCE 期权缺口)、`econ/`(全部 4006 个宏观因子,带发布时点 `info_date`)、`spot/`(上金所现货与早午盘基准价)。
- 覆盖范围:交易所口径的全部商品品种(中金所除外,90 个品种,含 2016 年后退市的合约),不再限于原导出的 23 个。`futures_tick/` 为可选抽样脚本,默认不跑(流量大)。
- 只含真实合约:合成连续合约(88/888/889/99/88A2,价格经平滑可为负)不进 `contracts_daily`/`futures_5minute`;连续价用 `dominant_daily/`、`continuous/` 或 `indices/`。

