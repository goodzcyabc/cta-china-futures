# 交易所每日风控参数(params)与上调事件推导

模块 `src/cta/data/exchanges/params.py`;统一字段 `PARAM_COLS`、`validate("params", …)` 在 `base.py`;测试与截断样例 `tests/test_exchanges_params.py`、`tests/fixtures/exchanges/params/`。
落盘布局与其他三类数据相同:`data/exchanges/<EXCH>/params/<YYYY>/<YYYYMMDD>.parquet`(一天一文件、永不覆盖),原始文件 gzip 存 `raw/params/<YYYY>/<YYYYMMDD>.{settlement.json|tradearg.json|clear.txt|trade.txt}.gz`。

用途:纸面/实盘每日拉取当日结算参数(保证金、手续费、平今手续费、涨跌停),并机械推导"品种一般月份档的保证金/手续费上调"事件,作为监管事件覆盖层(design_log 13.6 H-REG)的可复现事件源;历史表 `data/external/exchange_events/events.csv`(公告抽取 + 一次性推导)只能一次性生成,这里的推导口径与其中的 `DERIVED` 行同源。

```
PYTHONPATH=src python3 -m cta.data.exchanges.params backfill --start 2016-01-04 --exchanges SHFE,INE,CZCE   # 逐日回填,可断点续跑
PYTHONPATH=src python3 -m cta.data.exchanges.params day --date 2026-09-21                                    # 每日增量(纸面 ingest_all 已默认包含)
PYTHONPATH=src python3 -m cta.data.exchanges.params derive --out data/external/exchange_events/events_derived.csv
PYTHONPATH=src python3 -m cta.data.exchanges.params coverage
```

`backfill --local-dir DIR`(或 `SHFE=dir1,INE=dir2,CZCE=dir3`)优先导入已下载的原始文件(布局:上期所/能源中心 `S{YYYYMMDD}.json` + `T{YYYYMMDD}.json`,郑商所 `{YYYYMMDD}.txt`;`.404` 后缀为节假日标记),本地没有的再 curl。本次回填即用生成 events.csv 那次会话草稿区的下载件导入了 2016-01-04 … 2026-09-18 的上期所与郑商所文件、2018-03 … 2019-07 与 2022-01 … 2023-03 的能源中心文件,其余全部直连补齐(约 3 400 次请求,0 次失败)。

## 1. 数据源与 URL

| 交易所 | 文件 | URL | 起始 | 内容 |
|---|---|---|---|---|
| SHFE | 结算参数 | `https://www.shfe.com.cn/data/busiparamdata/future/Settlement{YYYYMMDD}.dat` | 2016-01-04(更早未探) | JSON `Settlement`:逐合约 投机/套保保证金、手续费(比例或按手)、平今折扣率、交割手续费 |
| SHFE | 每日交易参数 | `https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument{YYYYMMDD}.dat` | 同上 | JSON `ContractDailyTradeArgument`:逐合约 涨跌停 `UPPER_VALUE/LOWER_VALUE`、投机/套保保证金 |
| INE | 同上两个 | `https://www.ine.cn/data/busiparamdata/future/…` | 2018-03-26 | 结构相同。上期所文件里**也含能源中心品种**(sc/lu/nr/bc/ec),与能源中心自身文件逐合约一致;解析按 `shfe.INE_SYMBOLS` 拆分,SHFE 目录只留上期所品种、INE 目录只留能源中心品种 |
| CZCE | 结算参数表 | `https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureDataClearParams.txt` | 2016-01-04 | 竖线分隔:逐合约 结算价、是否单边市、交易保证金率、涨跌停板(2019-09-02 起)、交易手续费、手续费收取方式(2022-11-07 起)、平今手续费(2017-06-23 起)、日持仓限额/交易限额(2021/2022 起) |
| CZCE | 交易参数 | `https://www.czce.com.cn/cn/DFSStaticFiles/Future/{YYYY}/{YYYYMMDD}/FutureTradeParam.txt` | **2025-08-18**(之前 404) | 逐合约 上市日期、交易单位、最小变动价位、上日结算价、当日涨跌停板幅度、日持仓限额、交易限额、下单量限制 |
| DCE | — | dcereport 接口(需浏览器会话补签名) | — | **未接入**:`fetch_params(date, "DCE")` 抛 `NotImplementedError`,见 §7 |

三所文件桌面 UA 直接 GET 即可(与行情文件同一套静态目录),非交易日 404(郑商所偶见 200 + "当日无数据" HTML,按缺数据处理);上期所/能源中心文件在**北京时间约 16:00–16:40 发布**(`update_date` 字段),所以纸面 ingest 放在 16:30 之后、当天 404 不写 missing.log。下载复用 `shfe.http_get`(≥0.5 s 间隔、退避重试、404 → None),两所每天各两个请求。

## 2. 字段映射(`PARAM_COLS`)

一行一个期货合约(期权、期转现、TAS 不在这些文件里;上期所 `INSTRUMENTID` 只取 `^[a-z]{1,2}\d{4}$`,郑商所 `合约代码` 只取 `^[A-Z]{1,2}\d{3,4}$` 并按文件日期补十年位 `CF609 → CF2609`)。保证金、涨跌停为小数(0.09 = 9%);手续费按 `*_unit`:`bp` = 成交金额的万分之几,`CNY_per_lot` = 元/手。

| 列 | SHFE / INE 来源 | CZCE 来源 | 说明 |
|---|---|---|---|
| margin_spec | `Settlement.SPEC_LONGMARGINRATIO` | `交易保证金率(%)`/100(2019-09-02 前为 `买交易保证金率(%)`) | 投机保证金,**该日结算起适用**。两所买卖两侧全程相等(逐行核过 2016–2026)。保证金为 0 的行剔除(只见于集运指数 EC 最后交易日,合约现金交割,2024–2026 共 17 行) |
| margin_hedge | `Settlement.LONGMARGINRATIO` | 无 → NaN | 套保保证金 |
| fee_open / fee_open_unit | `TRADEFEERATION > 0` → ×1e4 记 `bp`;否则 `TRADEFEEUNIT` 记 `CNY_per_lot` | `交易手续费`;单位按 `手续费收取方式`(`比例值` → bp,值本身就是万分比;`绝对值` → 元/手);该列 2022-11-07 前不存在,全部为元/手(首个比例值 2023-07-20 甲醇) | 两所全程没有"比例与按手同时非零"的行 |
| fee_close_today / _unit | `DISCOUNTRATE × fee_open`,单位同 fee_open | `日内平今仓交易手续费`(2020-08 起)/`平今仓手续费`(2017-06-23 起);之前只有 Y/N 的 `平今手续费减半` → **NaN** | 上期所折扣率是开仓费的**倍数**(0 免收、1 同开仓、2 双倍;2026-09 铜 0.5 bp × 2 = 1.0 bp,与核验表一致)。郑商所旧列的 Y/N 无法还原数值:2017-06-23 切换当日 Y 的品种平今为 0、N 的品种为 3–24 元/手不等,故不猜 |
| limit_pct | `ContractDailyTradeArgument.UPPER_VALUE` | `FutureTradeParam.涨跌停板幅度(%)`/100;无该文件(2025-08-18 前)时用**前一交易日**结算参数表的 `涨跌停板(%)`(2019-09-02 起) | **该日盘中生效的涨跌停幅度**(见 §3)。合约在交易参数文件里没有(上期所 2018-08-31 线材、郑商所当日新上市合约)→ NaN;郑商所 2019-09-02 之前无来源 → NaN |

`validate("params")`:一文件一日期、合约代码规范且不重复、`margin_spec ∈ (0,1]`、`margin_hedge`/`limit_pct ∈ (0,1] 或 NaN`、手续费 ≥ 0 或 NaN、单位 ∈ {bp, CNY_per_lot} 或空。

## 3. 口径

- **时点**:结算参数文件是 D 日收盘结算时的参数,`margin_spec`/`fee_*` 自 D 结算起适用(公告"X 日收盘结算时起"的保证金调整在 X 日文件里首次出现)。**涨跌停两所文件口径不同**:上期所 `ContractDailyTradeArgument{D}` 是 D 日盘中已生效的参数(2026-07-02 铜保证金 12% → 11% 出现在 `Settlement20260702`,交易参数文件到 07-03 才变、涨跌停 10% → 9% 也在 07-03 文件),郑商所 `FutureDataClearParams{D}.涨跌停板` 则是 D 结算起、D+1 盘中适用的值,且逐合约等于 `FutureTradeParam{D+1}.涨跌停板幅度`(2026-04-29/30、05-06/07 核对)。本仓库统一取**"D 盘中生效"**:上期所用交易参数文件,郑商所用当日交易参数文件、没有时用前一交易日结算参数表,与 `paper/book.py` 用 `prev_settle × limit_pct` 判 D 日是否触板的用法一致。
- **一般月份档**(`daily_levels`):品种当日全部合约取**众数,平票取小**。上期所按临近交割逐月加档、郑商所交割月前加档,这些合约数量少,众数自然落在一般月份;手续费按 (值, 单位) 联合取众数。用主力合约代替众数会在换月时产生假事件,用中位数在合约数为偶数时会落在两档之间,故用众数。
- **成交量口径无关**:本类数据不涉及双边/单边。
- 上期所 2023-09-04 起文件多出套保手续费 `HTRADEFEERATIO/HTRADEFEEUNIT`,未入库。郑商所 `是否单边市`、`日持仓限额`、`交易限额` 未入库(推导用不到;需要时从 raw 重解析)。

## 4. 覆盖(每所每年落盘天数;回填 2016-01-04 → 2026-09-21,工作日逐日,404 记 `missing.log` 的 `params` 行)

| 年份 | SHFE | INE | CZCE |
|---|---|---|---|
| 2016 | 244 | 0 | 244 |
| 2017 | 244 | 0 | 244 |
| 2018 | 243 | 189 | 243 |
| 2019 | 244 | 244 | 244 |
| 2020 | 243 | 243 | 243 |
| 2021 | 243 | 243 | 243 |
| 2022 | 242 | 242 | 242 |
| 2023 | 242 | 242 | 242 |
| 2024 | 242 | 242 | 242 |
| 2025 | 243 | 243 | 243 |
| 2026 | 175 | 175 | 175 |
| 合计 | 2605 | 2063 | 2605 |

区间:SHFE 2016-01-04 … 2026-09-21(2605 个交易日);INE 2018-03-26 … 2026-09-21(2063 个交易日);CZCE 2016-01-04 … 2026-09-21(2605 个交易日)。上期所与郑商所文件日集合完全相同(同一套法定交易日);能源中心自 2018-03-26 原油上市起。工作日 404 全部为法定节假日(与行情文件的 missing.log 一致),区间内无缺口。

## 5. 事件推导(`derive_events`)

输入:某所全部 `params`(或传入的 PARAM_COLS 表);输出与 `events.csv` 相同的 14 列,`announce_date` 空、`effective_date` = 事件日、`contract_scope=all`、`notice_id` 空、`url` = 当日结算参数文件、`notes="DERIVED-daily"`。

规则(常量在模块顶部):
1. 每日每品种取一般月份档的 `margin_spec` 与 `(fee_open, unit)`;相邻两个**该品种有文件的交易日**(相距 ≤12 天,`MAX_GAP_DAYS`;超过视为数据缺口不比较)比较。
2. 上升 → 一条事件:`param=margin`(unit=ratio)或 `param=fee`(unit 为手续费单位;单位在两日间变化则不可比、不出事件);**事件日 = 新值首次出现的文件日 D**(D 结算起适用,实盘 D 日 16:40 后可见,覆盖层从 D+1 起作用)。默认只输出上调(`up_only=False` 也输出下调)。
3. 两道过滤,剔除不是"参数真变了"的众数翻转:(a) 两日都在市的合约中没有一个该字段真的变了(只是分档合约上市/到期让众数翻转;如 2026-07 有色 8 个近月合约 11%、远月 9%,随近月到期众数自己翻回 9%);(b) ≥4 个共同合约里只有 1 个变(单合约进入交割前月的阶梯恰好打破平票)。
4. `reason`:事件日在**休市日**(周一至周五的非交易日;历史用该所 params 交易日集合,最后一个文件之后用 `configs/holidays.csv` 的公告假期)之前 ≤3 个交易日(`HOLIDAY_BEFORE_SESSIONS`),**且**随后 ≤10 个交易日内(`HOLIDAY_RESTORE_SESSIONS`)一般档回落到不高于原值 → `holiday`;其余 `derived`。"回落到不高于原值"而非"恢复到原值"是为了让节前分两步上调(8→9→11,节后一步回到 8)的第二步也算节假日。`require_restore=False` 只看前一个条件(当日即可判定,供实盘用);`derive --no-restore-check`。

**注意**:恢复条件用到事件后 10 个交易日的数据,最近 10 个交易日内的事件 `reason` 是暂定的(重跑会从 `derived` 变成 `holiday`);实盘覆盖层若要当日决定,用 `require_restore=False`,代价是"节前上调后不再恢复"的真收紧会被当成节假日(SHFE 公告行里有 42 例,见 §6)。

本次回填后的推导结果(`derive`,只输出上调;写到 `data/external/exchange_events/events_derived.csv`,1629 行):

| 生效年份 | SHFE derived | SHFE holiday | INE derived | INE holiday | CZCE derived | CZCE holiday | 合计 |
|---|---|---|---|---|---|---|---|
| 2016 | 32 | 29 | 0 | 0 | 28 | 75 | 164 |
| 2017 | 3 | 27 | 0 | 0 | 4 | 58 | 92 |
| 2018 | 1 | 26 | 1 | 6 | 16 | 46 | 96 |
| 2019 | 7 | 45 | 1 | 4 | 11 | 42 | 110 |
| 2020 | 41 | 65 | 7 | 8 | 34 | 72 | 227 |
| 2021 | 33 | 57 | 2 | 17 | 73 | 60 | 242 |
| 2022 | 27 | 22 | 3 | 12 | 26 | 43 | 133 |
| 2023 | 5 | 34 | 5 | 12 | 9 | 36 | 101 |
| 2024 | 15 | 54 | 8 | 18 | 6 | 47 | 148 |
| 2025 | 16 | 57 | 9 | 15 | 10 | 62 | 169 |
| 2026 | 54 | 20 | 17 | 5 | 16 | 35 | 147 |
| 合计 | 234 | 436 | 53 | 97 | 233 | 576 | 1629 |

按参数:SHFE:margin 658 / fee 12;INE:margin 146 / fee 4;CZCE:margin 785 / fee 24。品种数:CZCE 28;INE 5;SHFE 20。

## 6. 质量核验

**与已核验现行值对照**(`tests/test_exchanges_params.py::test_params_match_verified_2026_values`,有本地数据才跑):`docs/instruments_verification.md`(2026-09-11 结算参数 / 2026-09-14 交易参数)与 `docs/instruments_verification_ext_shfe_czce.md`(2026-09-18)中 22 个品种的主力/一般月份合约,每项比 `margin_spec`、`fee_open`+单位、`fee_close_today`、`limit_pct` 五个字段:**22/22 品种 110/110 字段一致**(2026-09-21 回填后运行)。

**推导事件 vs 公告事件**(`scripts/params_events_eval.py`;公告事件 = `events.csv` 中 `notice_id` 非空、`param ∈ {margin, fee}`、`direction=up` 的行按 (品种, 参数, 生效交易日) 去重;生效日不是交易日的取其后第一个交易日;生效日晚于最后一个参数文件的不计;匹配 = 同所同品种同参数、事件日与生效日相差 ≤1 个交易日):

| 交易所 | 公告事件数(scope=all / 非节假日) | 容差(交易日) | 召回率 全部 | 召回率 scope=all | 召回率 非节假日 | 命中者新值一致 | 推导事件数(非 holiday) | 精确率 全部 | 精确率 非 holiday |
|---|---|---|---|---|---|---|---|---|---|
| SHFE | 672(597 / 180) | ±0 | 90.2% | 99.3% | 72.2% | 99.2% | 670(234) | 90.4% | 73.5% |
| SHFE | 672(597 / 180) | ±1 | 90.9% | 99.5% | 75.0% | 98.7% | 670(234) | 91.3% | 75.2% |
| SHFE | 672(597 / 180) | ±2 | 92.0% | 99.7% | 78.3% | 98.7% | 670(234) | 92.7% | 79.1% |
| INE | 163(121 / 59) | ±0 | 81.6% | 99.2% | 54.2% | 98.5% | 150(53) | 88.7% | 67.9% |
| INE | 163(121 / 59) | ±1 | 84.7% | 99.2% | 61.0% | 97.1% | 150(53) | 89.3% | 69.8% |
| INE | 163(121 / 59) | ±2 | 88.3% | 99.2% | 71.2% | 95.8% | 150(53) | 90.7% | 73.6% |

解读:
- 公告范围为全部合约(`contract_scope=all`)的公告事件几乎全部被推导命中(SHFE 597 个中 594、INE 121 个中 120,±1 交易日)。未命中的三个:AO 2025-03-11(公告表 direction 标错:参数文件 12% → 10%、3 bp → 1.5 bp 实为下调)、WR 2021-06-15(线材合约极少,众数被交割月档拉走)、NR 2021-04-16 手续费 3 元/手 → 万分之 0.2(单位改变,本模块判为不可比不出事件;公告表自己也标 `direction uncertain`)。
- 未命中的其余公告事件是**只针对个别合约**的调整(如 FU2610/FU2611、SC2610/SC2611、RB2401),不改变品种一般档,按定义不是推导事件——这是口径差异,不是漏抓;能源中心此类公告占比高(原油按合约月份分档调整多),所以 INE 的"全部"召回率更低。
- 推导有而公告没有的事件(SHFE 58 条、INE 16 条 `derived`):2016 螺纹钢/白银/橡胶、2020-03 原油系与白银、2021 有色、2023–2026 集运欧线 EC 等,与 `docs/data_exchange_events.md` §4 "无公告解释的推导事件"一致——多为单边市后的规则自动加档或公告正文未抓到的调整,它们是真实的参数变动。
- 节假日标记:与公告行匹配的对上,公告写 `holiday` 且推导标 `holiday` SHFE 436 / INE 98 对;公告 `holiday` 但推导标 `derived` SHFE 42 / INE 4 对(节前上调后 10 个交易日内**没有**回落,如 2021-06-10 上期发〔2021〕156 号有色、2016-03-31 螺纹钢——交易所节后没有恢复,推导把它当作真收紧);公告非节假日而推导标 `holiday` 两所均为 0 对。
- 郑商所无公告正文可比,与 `events.csv` 里上一版一次性推导的 CZCE `DERIVED` 上调行比较:809 条中 809 条完全相同(日期、品种、参数、新值),上一版多出的 1 条(PL 2026-06-08 fee)是手续费由元/手改为比例值,本版判为单位不可比、不出事件。

## 7. 已知缺口与待办

1. **大商所(DCE)未接入**。dcereport 报表系统整站瑞数反爬,参数接口需要浏览器会话补签名(与 `dce.py` 的行情/排名同一机制),本次会话无浏览器;`fetch_params(date, "DCE")` 抛 `NotImplementedError`,纸面 `ingest_all` 对 DCE 记 `params:skipped_needs_browser`。接入时可沿用 `dce.CdpSession`,大商所"交易参数"页(`/dcereport/publicweb/…/tradingParameters` 一类接口)按合约给出保证金/涨跌停/手续费;推导规则不需改。
2. 郑商所 2016-01-04 … 2017-06-22 的 `fee_close_today` 为 NaN(文件只有 Y/N 标志);2016-01-04 … 2019-09-01 的 `limit_pct` 为 NaN(文件无涨跌停列);2019-09-02 当天 `limit_pct` 也为 NaN(无前一日结算参数表)。
3. 郑商所手续费单位在 2022-11-07 前按元/手记,若某品种当时已是比例值需以当年公告为准(上一版事件表同样假设,首个比例值出现在 2023-07-20)。
4. `limit_pct` 是"当日盘中生效"口径,要拿 D+1 的涨跌停请用 D+1 的文件(上期所)或 D 日 raw 里的 `涨跌停板(%)` 列(郑商所)。
5. 事件推导只覆盖 `margin` 与 `fee`(一般月份档)。平今手续费、涨跌停、持仓限额的变动没有推导;单合约档位(临近交割月的阶梯)不在其中。
6. 最近 10 个交易日内事件的 `reason` 暂定(§5 注意)。
7. 参数文件更早的年份未探(上期所 `busiparamdata` 目录 2016 之前是否存在未测)。
