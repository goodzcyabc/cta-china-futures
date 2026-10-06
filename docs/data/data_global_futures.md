# 外盘期货日线接入(供"外盘趋势溢出"因子研究)

落盘:`data/external/global_futures/daily.parquet`(不进 git;字段表与用法见同目录 `README.md`),原始抓取在 `data/external/global_futures/raw/`,
抓取与重建脚本 `data/external/global_futures/scripts/{fetch_sources.py,build_daily.py,yahoo_retry_loop.sh}`(curl 公开接口,请求间隔 ≥1.2 s,不登录、不付费)。
本文记录:映射与来源、覆盖、**时间戳语义与"中国 T 日可用的最新外盘收盘是哪一天"**、连续合约换月、缺失处理、与 `data/ricecta/data/global_crude/global_crude.parquet` 的交叉核对、拿不到的合约与已试来源。
建表日期 2026-09-21(数据至 2026-09-18,周五)。

## 1. 映射与来源

原计划主源是 Yahoo Finance 的 chart v8 接口(`query2.finance.yahoo.com/v8/finance/chart/GC%3DF?…&interval=1d`)。**本次会话 Yahoo 对本机 IP 全程返回 HTTP 429**(query1/query2、带完整浏览器请求头、带 finance.yahoo.com 下发的 cookie + crumb、IPv6、spark 接口、30/60/120 s 退避后每 5 分钟重试,18:16–18:50(美东)约 20 次全部 429;finance.yahoo.com 的 HTML 页面能打开但历史表格由前端再请求同一接口)。
因此 CME/CBOT/ICE 十个合约改用 **CNBC 图表接口**(`ts-api.cnbc.com/harmony/app/bars/@GC.1/1D/<start>/<end>/adjusted/EST5EDT.json`,公开、无需 key),它与 Yahoo 是同一口径的"前月连续"(第 6 节用仓库已有的 Yahoo 数据逐日核对:收盘 100% 一致)。Yahoo 的抓取脚本保留在 `fetch_sources.py yahoo`,429 解除后重跑即可,`build_daily.py` 会把 `GC=F` 等行并入同一张表(symbol_ext 不同,不会覆盖 CNBC 行)。

| 中国品种 | 外盘合约 | symbol_ext(exchange_ext) | 来源 | 字段 | 状态 |
|---|---|---|---|---|---|
| AU 沪金 | COMEX 黄金 GC | `@GC.1`(COMEX) | CNBC | OHLCV | 2016-01-04 … 2026-09-18,2,695 天 |
| AG 沪银 | COMEX 白银 SI | `@SI.1`(COMEX) | CNBC | OHLCV | 2,694 天 |
| CU 沪铜 | COMEX 铜 HG | `@HG.1`(COMEX) | CNBC | OHLCV | 2,694 天 |
| CU 沪铜 | LME 铜 官方价 | `LME_CU_CASH` / `LME_CU_3M`(LME) | westmetall | close | 2,708 天 |
| SC 原油 | NYMEX WTI CL | `@CL.1`(NYMEX) | CNBC | OHLCV | 2,689 天 |
| SC 原油 | ICE Brent(伦敦) | `@LCO.1`(ICE_EU) | CNBC | OHLCV | 2,760 天(ICE 欧洲在美国假日照常交易,故天数更多);其 close 与 Yahoo `BZ=F`(NYMEX Brent Last Day Financial,按 ICE Brent 结算价现金结算)逐日一致 |
| M 豆粕 | CBOT 豆粕 ZM | `@SM.1`(CBOT) | CNBC | OHLCV | 2,693 天 |
| Y 豆油 | CBOT 豆油 ZL | `@BO.1`(CBOT) | CNBC | OHLCV | 2,692 天 |
| C 玉米 | CBOT 玉米 ZC | `@C.1`(CBOT) | CNBC | OHLCV | 2,692 天 |
| CF 棉花 | ICE 美国 棉花 No.2 CT | `@CT.1`(ICE_US) | CNBC | OHLCV | 2,697 天(其中 6 天只有 close) |
| SR 白糖 | ICE 美国 原糖 No.11 SB | `@SB.1`(ICE_US) | CNBC | OHLCV | 2,694 天(其中 5 天只有 close) |
| AL 沪铝 | LME 铝 官方价 | `LME_AL_CASH` / `LME_AL_3M` | westmetall | close | 2,708 天 |
| NI 沪镍 | LME 镍 官方价 | `LME_NI_CASH` / `LME_NI_3M` | westmetall | close | 2,708 / 2,694 天(2022-03-08 … 03-25 无三月价,镍危机停牌期) |
| SN 沪锡 | LME 锡 官方价 | `LME_SN_CASH` / `LME_SN_3M` | westmetall | close | 2,708 天 |
| ZN / PB(附带) | LME 锌 / 铅 官方价 | `LME_ZN_*` / `LME_PB_*` | westmetall | close | 2,708 天 |
| RU 橡胶 | SGX SICOM TSR20(TF)主力连续 | `SGX_TF_DOM`(SGX) | api.sgx.com | settle, volume, OI, contract_ext | **2018-01-19** … 2026-09-18,2,161 天;2016 … 2018-01-18 缺(API 数据起点) |
| P 棕榈油 | BMD FCPO | — | — | — | **缺**(第 7 节) |
| RU 橡胶 | TOCOM/OSE RSS3 | — | — | — | **缺**,以 SGX TSR20 替代(第 7 节) |
| AL/NI/SN | LME 电子盘 OHLCV | — | — | — | 缺,只有官方价(第 7 节) |

LME 官方价:`*_CASH` = LME Official Cash Settlement(现货卖价,T+2 交割),`*_3M` = LME Official 3-month;两者都是连续报价(滚动到期日),没有换月跳空。westmetall 表里还有 LME 库存列,未入表。
SGX:SGX 只有 SICOM TSR20 的**逐合约**日结算价/成交量/持仓量(无 OHLC),本表按"当日持仓量最大的合约、只向更晚到期切换、不加确认期"拼成主力连续,共用 88 个合约、换月 87 次(月度合约,持仓集中在 3–6 个月后,换月频繁),`contract_ext` 给出当日合约,换月日价差未调整。

## 2. 覆盖

| symbol_ext | 起 | 止 | 天数 | 有 OHLC | 有 volume | 剔除的占位 K 线 | 只有 close 的日子 |
|---|---|---|---|---|---|---|---|
| @GC.1 | 2016-01-04 | 2026-09-18 | 2,695 | 2,695 | 2,668 | 0 | 0 |
| @SI.1 | 2016-01-04 | 2026-09-18 | 2,694 | 2,694 | 2,663 | 0 | 0 |
| @HG.1 | 2016-01-04 | 2026-09-18 | 2,694 | 2,694 | 2,663 | 0 | 0 |
| @CL.1 | 2016-01-04 | 2026-09-18 | 2,689 | 2,689 | 2,650 | 1(2020-08-18) | 0 |
| @LCO.1 | 2016-01-04 | 2026-09-18 | 2,760 | 2,758 | 2,748 | 2(2017-01-02、2023-01-02 英国假日) | 2(2021-06-30、2026-09-18) |
| @SM.1 | 2016-01-04 | 2026-09-18 | 2,693 | 2,693 | 2,663 | 3(2021-04-02、2023-04-07 耶稣受难日,2026-04-21) | 0 |
| @BO.1 | 2016-01-04 | 2026-09-18 | 2,692 | 2,692 | 2,661 | 3(2017-10-17、两个受难日) | 0 |
| @C.1 | 2016-01-04 | 2026-09-18 | 2,692 | 2,692 | 2,666 | 2(两个受难日) | 0 |
| @CT.1 | 2016-01-04 | 2026-09-18 | 2,697 | 2,690 | 2,669 | 21(2017-09-04 及 2023 起 ICE 美国假日) | 6 |
| @SB.1 | 2016-01-04 | 2026-09-18 | 2,694 | 2,689 | 2,689 | 25(同上) | 5 |
| LME_*_CASH(6 金属) | 2016-01-04 | 2026-09-18 | 2,708 | — | — | 2016-12-27 一行为空 | — |
| LME_*_3M | 2016-01-04 | 2026-09-18 | 2,708(NI 2,694) | — | — | 同上;NI 另缺 2022-03-08…25 | — |
| SGX_TF_DOM | 2018-01-19 | 2026-09-18 | 2,161 | — | 2,161 | 新加坡假日占位行(settle=0)1,432 行已剔 | — |

CNBC 美国合约每年约 250–253 天(如 @GC.1:2016 252、2017 251、2018 252、2019 252、2020 253、2021 252、2022 251、2023 250、2024 252、2025 251、2026 至 9-18 为 179),与 CME 交易日历一致。完整的剔除/只有 close 日期清单在 `build_summary.json`。

## 3. 时间戳语义(决定信号能否在中国 T 日 15:00 / T+1 09:00 前使用)

**所有来源的 `date` 都是外盘交易所本地日历上的"交易日"(trade date),不是交易时段开始的那个日历日**;每行另给 `close_ts_utc` = 该 close 最终确定的时刻。

### 3.1 CME(COMEX 金银铜、NYMEX WTI)——CNBC `@GC.1` 等与 Yahoo `GC=F` 等同口径

- Globex 交易时段:美东 **18:00(D−1)→ 17:00(D)**(每日 17:00–18:00 休市),交易所把这一段记为交易日 **D**。日线 `date = D`。CNBC 的 `tradeTime` 就是 `D 00:00 EST5EDT`(2,695 根全部为 00:00);Yahoo 的日线日期同为 D(yfinance 导出的 `global_crude.parquet` 索引为 `D 00:00 America/New_York`,与 CNBC 同日收盘 100% 相等,见第 6 节)。
- 日线 close = **交易所结算价**,不是 17:00 的最后一笔:COMEX 金属结算窗口 13:29:30–13:30 ET,NYMEX 原油 14:28–14:30 ET。证据:NYMEX `BZ=F`(Brent Last Day Financial)按 ICE Brent 结算价现金结算,Yahoo `BZ=F` close 与 CNBC ICE Brent `@LCO.1` close 在 1,360 个交易日上 99.9% 精确相等,而两者 open 只有 11.6% 相等、成交量完全不同——两个不同场所的"最后一笔"不可能逐日到美分一致,只有结算价会。
- 换算北京时间(夏令时 3 月中–11 月初 ET=UTC−4,冬令时 UTC−5):结算 13:30 ET = 北京 **D+1 01:30(夏)/ 02:30(冬)**;原油结算 14:30 ET = D+1 02:30 / 03:30;时段收盘 17:00 ET = D+1 **05:00 / 06:00**。`close_ts_utc` 取保守的 17:00 ET。
- 对中国交易日 T(日盘 09:00–15:00,夜盘 T−1 日 21:00–02:30):美国交易日 D 的 K 线在北京 D+1 早 05:00–06:00 完成,**在 T 日 09:00 之前、T 日 15:00 之前可用的最新美国日线都是 date ≤ T−1(日历)的那根**——通常就是 T−1;T 为周一时是上周五;美国假日则再往前。美国交易日 D=T 的 K 线在中国 T 日 15:00(= T 日 02:00/03:00 ET,Globex 时段进行中)**没有完成**,不可用。

### 3.2 CBOT 农产品(豆粕、豆油、玉米)

- Globex:19:00 CT(D−1)– 07:45 CT,日盘 08:30–13:20 CT(D);结算 13:15 CT。`date = D`(芝加哥交易日)。
- 13:20 CT = 北京 **D+1 02:20(夏)/ 03:20(冬)**;`close_ts_utc` 取 13:20 CT。可用性结论同 3.1:中国 T 日可用的最新一根是 date ≤ T−1。

### 3.3 ICE 美国软商品(棉花、原糖)

- 棉花 No.2:21:00 ET(D−1)– 14:20 ET(D),结算 14:14–14:15 ET;14:20 ET = 北京 D+1 02:20/03:20。
- 原糖 No.11:03:30–13:00 ET(D),结算 12:55–13:00 ET;13:00 ET = 北京 D+1 01:00/02:00。
- `date = D`(纽约交易日)。可用性同 3.1。

### 3.4 ICE Brent(`@LCO.1`,伦敦)

- 01:00–23:00 伦敦时间,结算 19:28–19:30 伦敦;`date` = 伦敦交易日 D。结算 19:30 伦敦 = 北京 **D+1 02:30(英夏令时)/ 03:30(GMT)**;时段收盘 23:00 伦敦 = 北京 D+1 06:00/07:00。`close_ts_utc` 取 19:30 伦敦(close 是结算价)。可用性同 3.1(最新可用 = date ≤ T−1)。

### 3.5 LME 官方价(westmetall)

- 官方价在第二轮圈内交易(Ring 2,12:30–13:15 伦敦)中形成,约 13:30 伦敦公布(westmetall 当天下午更新)。`date` = 伦敦营业日 D。
- 13:30 伦敦 = 北京 **D 日 20:30(英夏令时)/ 21:30(GMT)**,即当天中国日盘收盘之后、夜盘开盘(21:00)前后。中国 T 日 15:00 信号可用的最新 LME 官方价是 **T−1**(伦敦营业日);T 日夜盘只在英国夏令时月份能赶上 D=T 的官方价(20:30),冬令时 21:30 才公布,统一按 `close_ts_utc` 判断或保守用 T−1。
- 对齐检验:LME 三月价 D 日收益率与上期所 CU/AL/NI/SN 主力**同一交易日 D**收盘收益率相关 0.72/0.57/0.66/0.64,而与 D+1 只有 0.14/0.09/0.15/0.07——上期所 T 日(含 T−1 夜盘)已经吸收了 LME D 日官方价之前的信息,LME D 日官方价对中国 T+1 的增量信息很小,做"溢出"因子时要注意这点。

### 3.6 SGX TSR20(api.sgx.com)

- 交易时段 07:55–18:00 新加坡时间(与北京同为 UTC+8),日结算价于收盘后确定;`date` 取 API 的 `base-date` 字段 = 新加坡交易日 D(API 另有 `record-date` = D−1、`record-last-time` = D−1 16:00,是系统快照时间,不是交易日;用上期所 RU 收益率核对:与 `base-date` 同日相关 0.81–0.91,错一天则 ≈0)。新加坡假日 API 仍给 settle=0、volume=0 的占位行,已剔除。
- 18:00 北京 = `close_ts_utc`。中国 T 日 15:00 信号可用的最新一根是 **T−1**;T 日 21:00 夜盘和 T+1 09:00 可用 D=T。

### 3.7 汇总:各序列"中国 T 日 15:00 信号可用的最新 close"

| 序列 | close 确定时刻(北京) | T 日 09:00 前可用的最新 date | T 日 15:00 前可用的最新 date | T 日 21:00 夜盘可用 |
|---|---|---|---|---|
| CME / CBOT / ICE 美国 / ICE Brent(CNBC、Yahoo) | D+1 01:00–07:00 | ≤ T−1 | ≤ T−1(同上,T 日无新增) | ≤ T−1 |
| LME 官方价 | D 日 20:30/21:30 | ≤ T−1 | ≤ T−1 | T(仅夏令时可靠) |
| SGX TSR20 | D 日 18:00 | ≤ T−1 | ≤ T−1 | T |

注意:09:00 与 15:00 的可用集合完全相同——没有任何一个外盘序列在北京 09:00–15:00 之间出新的日线收盘。因子里用 `merge_asof(cutoff = T 日 09:00 北京, on close_ts_utc)` 即可,不必分开处理。反过来,中国 T 日的行情(日盘 15:00 收盘)先于同日美国 D=T 的结算出现,若研究"中国→外盘"方向或用 T 日外盘收益解释 T 日中国收益,会引入前视,须避免。

## 4. 连续合约与换月

- **CNBC `@XX.1` / Yahoo `=F`**:数据商的"前月连续",由相继的前月合约**直接拼接、未做价差复权**,换月日有跳空;换月规则由数据商决定、不公开,跟随交易所的活跃/领先月而不一定是最近到期月(2026-09-21:CNBC `@GC.1` = Gold Dec'26、Yahoo 页面标题 "Gold Dec 26 (GC=F)",跳过了 10 月合约;`@CL.1` = Oct'26、`@LCO.1` = Nov'26、`@SM.1/@BO.1/@C.1/@CT.1` = Dec'26、`@SB.1` = Oct'26)。`volume` 是该前月合约的成交量,临近换月会萎缩。做趋势/溢出因子请用收益率并对换月日做处理(例如剔除 |ret| 异常大的换月日或用 LME/SGX 对照),不要直接用价格水平。
- 同一日期上 CNBC 与 Yahoo 的前月连续就是同一序列(第 6 节),因此换月日也一致。
- **LME 官方价**:现货与三月价都是滚动期限的连续报价,无换月。
- **SGX 主力连续**:按持仓量最大、只向后切换,`contract_ext` 标出合约;换月 87 次(2018-02 … 2026-09),跳空未调整,需要时可用 `raw/sgx/*.json` 自行做复权。

## 5. 缺失与停牌处理

- 外盘节假日**无行**(不前向填充)。美国合约在美国假日无 K 线;ICE Brent 在美国假日照常有行、在英国假日(2017-01-02、2023-01-02 等)无行。
- CNBC 用 0 或 −9999401/−999401 哨兵值表示缺失的 open/high/low,并在假日给"沿用前一日 close、无成交量"的占位行。`build_daily.py` 的规则:OHL 全缺且 close 等于前一日 → 剔除(假日占位);O=H=L=C 且等于前一日 → 剔除;close 等于前一日且成交量为 0 或低于近 20 日中位数 10% → 剔除(ICE 棉花 2023 年起在美国假日出现的带少量成交的碎片 K 线);**OHL 缺但 close 有变化 → 保留为只有 close 的行**(OHL 为 NaN,如 @LCO.1 2026-09-18、@CT.1 6 天、@SB.1 5 天);成交量为 0 记为 NaN(未知),不是零成交(每个 CME/CBOT 合约约 26–39 天,多在 2016–2017 与 2020)。
- 2020-04-20(WTI 5 月合约收于 −37.63 的那天)在 CNBC 源里**没有 K 线**;2020-04-21 有(前月 open −14.00、low −16.74、close 10.01),负价按真实数据保留。
- LME:2016-12-27(英国替代假日)六个金属均为空行,未入表;镍三月价 2022-03-08 … 03-25 缺(LME 3 月 8 日暂停镍交易、16 日恢复,期间不公布三月官方价),现货结算价齐全。
- SGX:27,364 行合约日数据中 1,432 行为新加坡假日占位(settle=0),已剔;2016-01 … 2018-01-18 不可得。
- 尚未做的处理(留给因子研究):中国与外盘假日不重叠时的对齐(建议 `merge_asof` 按 `close_ts_utc`),换月日收益的处理(第 4 节)。

## 6. 与 `data/ricecta/data/global_crude/global_crude.parquet` 的交叉核对

该文件是 yfinance 导出的 `CL=F`、`BZ=F` 日线(2021-01-04 … 2026-06-04,索引 `Date` 为 America/New_York 00:00,列 Open/High/Low/Close/Volume,float32)。逐日对照:

| 对照 | 重叠天数 | close 精确相等 | open / high / low 相等 | volume 相等 | 日期错 ±1 天时 close 相等 |
|---|---|---|---|---|---|
| Yahoo `CL=F` vs CNBC `@CL.1` | 1,359 | **100%** | 97.9% / 97.9% / 98.0% | 92.1% | 0.8% / 0.9% |
| Yahoo `BZ=F`(NYMEX Brent 现金结算)vs CNBC `@LCO.1`(ICE Brent) | 1,360 | **99.9%** | 11.6% / 59.9% / 61.1% | 0%(不同场所) | 0.9% / 0.9% |

抽样(CNBC O/H/L/C/V 与 Yahoo `CL=F` 完全相同):2021-01-04 48.40/49.83/47.18/47.62/528,525;2022-03-08 120.67/129.44/117.07/123.70/583,106;2023-06-15 68.70/70.96/67.97/70.62/115,613;2024-06-14 77.96/79.15/77.73/78.45/245,827;2025-04-07 61.12/63.90/58.95/60.70/597,617;2026-06-04 95.75/95.91/91.91/93.04,成交量 219,500 vs Yahoo 260,613(唯一差异,应为其中一方事后修订)。
日期集合的差异只有几天:Yahoo `CL=F` 多出 2023-10-23、2025-07-04(美国假日,疑为错误 K 线)、2026-04-21、2026-05-19;CNBC `@CL.1` 多出 2021-04-02(耶稣受难日,CNBC 有成交 577,986)。`BZ=F` 多出 2021-12-01、2023-08-31、2024-11-01、2025-12-01(Brent 前月到期后的第一天,CNBC 的连续序列在这里断一天);`@LCO.1` 多出全部美国假日。
结论:(1) 两个来源的 `date` 都是美国交易日,口径相同;(2) close 是结算价;(3) 研究中用 CNBC 序列等价于用 Yahoo 序列,Yahoo 恢复后两者可互为备份。

## 7. 拿不到的合约与已试来源

| 目标 | 结果 | 已试 |
|---|---|---|
| Yahoo `GC=F SI=F HG=F CL=F BZ=F ZM=F ZL=F ZC=F CT=F SB=F` | 本次未取到(IP 级 429),已用 CNBC 同口径替代;脚本保留 | query1/query2 v8 chart(裸请求、完整浏览器头、cookie+crumb、IPv6)、v7 spark、finance.yahoo.com 历史页(能开,表格为前端请求)、30/60/120 s 退避 + 每 5 分钟重试(约 35 分钟、约 20 次);之后留有 `scripts/yahoo_retry_loop.sh` 每 10 分钟探测一次、最多 3 小时,成功即抓取到 `raw/yahoo/` |
| P 棕榈油 BMD FCPO | **缺** | Yahoo `CPO=F`/`FCPO=F`/`KO=F` 均 404;CNBC `@FCPO.1` 有符号无数据,`@CPO.1` 有 2,813 根但**质量不可用**(全部零成交量、2022 年起每年 28–50 根落在周日、27–43% 的 K 线 O=H=L=C、与大商所 P 主力同日收益相关仅 0.5–0.68、2016–2021 更低)已否决,原文件留在 `raw/cnbc/CPO_1.json`;MPOC 官网 `mpoc.org.my/market-insight/daily-palm-oil-prices/` 只展示最近 10 个交易日的 BMD 三月结算价(可作日增量源,无历史);Bursa Malaysia 网站 403;MPOB BEPI 需付费;stooq 见下 |
| RU 的 TOCOM/OSE RSS3 | **缺**,用 SGX TSR20 替代(2018-01-19 起) | JPX 官网只有当日结算价页;SGX API 只从 2018-01-18 起有数据(`TFF16`、`TFZ17`、`TFF18` 为空,`TFM18` 从 2018-01-18 开始) |
| LME 铝/镍/锡 OHLCV | 只有官方价(现货结算、三月),无 OHLC/成交量 | westmetall 年表(成功);CNBC `MAL3/MCU3/MNI3/MSN3` 无此符号;CME 铝 `@ALI.1` 仅 18 根 |
| stooq CSV(`stooq.com/q/d/l/?s=gc.f&i=d`) | 未用 | 返回 JavaScript 工作量证明(SHA-256 前缀零)验证页,属于机器人检测,**未绕过** |
| Nasdaq.com 商品历史 API | 未用 | `assetclass=commodities/futures/…` 全部报参数错误,商品页已 301 |
| WSJ / MarketWatch 历史 CSV | 未用 | DataDome 401 |
| FRED(WTI/Brent 现货) | 未用 | TLS 握手后无响应 |
| EIA `RCLC1d.xls`(NYMEX WTI 近月结算) | 未用 | 可下载,但系列止于 2024-04-05 |
| CME 结算价 API | 未用 | 403,无法直接核对结算价(改用第 3.1 节的 BZ=F/ICE Brent 证据) |

## 8. 刷新

```
python3 data/external/global_futures/scripts/fetch_sources.py cnbc lme sgx   # 各 10 / 6 / ≤24 次请求(过去年份与已到期合约跳过)
python3 data/external/global_futures/scripts/fetch_sources.py yahoo          # 429 时自动 30/60/120 s 退避
python3 data/external/global_futures/scripts/build_daily.py                   # 重建 daily.parquet 与 build_summary.json
```

`build_daily.py` 对 Yahoo 原始时间戳做了两种情况的判别(日线戳在 00:00 UTC 时取 UTC 日期,否则取交易所时区日期)并把判别结果写入 `build_summary.json` 的 `date_rule`;Yahoo 取到后请先看该字段并用第 6 节的方法与 CNBC 对照一次。
