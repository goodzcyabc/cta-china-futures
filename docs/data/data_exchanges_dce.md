# 大商所(DCE)数据接入

模块:`src/cta/data/exchanges/dce.py`;测试:`tests/test_exchanges_dce.py`(离线样例在 `tests/fixtures/exchanges/dce/`);
数据:`data/exchanges/DCE/{raw,quotes,positions,receipts}/<YYYY>/<YYYYMMDD>.*`,缺失记录 `data/exchanges/DCE/missing.log`。

```
PYTHONPATH=src python3 -m cta.data.exchanges.dce backfill --start 2016-01-04 --end 2026-09-16 --kinds quotes,positions,receipts
PYTHONPATH=src python3 -m cta.data.exchanges.dce ingest --date 2026-09-16          # 每日增量(三类)
PYTHONPATH=src python3 -m cta.data.exchanges.dce reparse --start ... --end ...      # 解析逻辑改了之后用 raw 重建
PYTHONPATH=src python3 -m cta.data.exchanges.dce reconcile --symbols C,M,Y,P,JD,V,J,I
PYTHONPATH=src python3 -m cta.data.exchanges.dce coverage
```

## 1. 数据源与 URL 模式

大商所 2025 年换了新站(`/dce/`),行情/持仓/仓单查询都是 Vue SPA `http://www.dce.com.cn/frontend/dcereport/#/zh/<route>`,
数据来自同域后端 `http://www.dce.com.cn/dcereport/publicweb/...`(JSON POST)。

| 类别 | 页面(新站频道 → SPA 路由) | 后端接口(本模块用) | 请求体 |
|---|---|---|---|
| 日行情 | `/dce/channel/list/168.html` → `dayFuturesQuotation` | `POST /dcereport/publicweb/dailystat/dayQuotes` | `{"varietyId":"all","tradeDate":"YYYYMMDD","tradeType":"1","contractId":"","lang":"zh","optionSeries":"","statisticsType":0}` |
| 会员持仓排名 | `/dce/channel/list/176.html` → `memberDealPosiQuotes` | `POST /dcereport/publicweb/dailystat/memberDealPosi/batchDownload`(整日 zip) | `{"tradeDate":"YYYYMMDD","varietyId":"c","contractId":"all","tradeType":"1","lang":"zh"}` |
| 仓单日报 | `/dce/channel/list/187.html` → `wbillWeeklyQuotes` | `POST /dcereport/publicweb/dailystat/wbillWeeklyQuotes` | `{"varietyId":"all","tradeDate":"YYYYMMDD"}` |
| 交易日判断 | — | `POST /dcereport/publicweb/tradeDateNum` | `{"date":"YYYYMMDD"}`,非交易日 `data` 为 null |
| 历史数据打包 | `/dce/channel/list/164.html` → `datadownload` | `GET /dcereport/quote/history/download?type=1&year=YYYY&variety=all&lang=zh` | 每品种一个 xlsx 的 zip,2006–当年 |

`tradeType` 1=期货、2=期权。会员排名的单合约接口 `.../dailystat/memberDealPosi`(需 `contractId`,合约列表来自 `.../dailystat/posiContract`)
一天要 200+ 次请求,所以用批量下载:请求体里的 varietyId/contractId 只是页面状态,服务端返回整日全部合约(`YYYYMMDD_DPL.zip`,每合约一个 utf-8 tab 分隔 txt)。

已核实不可用/不采用的入口:
- 老版 `http://www.dce.com.cn/publicweb/quotesdata/dayQuotesCh.html`、`exportDayQuotesChData.html`、`memberDealPosiQuotes.html`、`wbillWeeklyQuotes.html`:
  curl 412;浏览器里打开返回 500(旧站 publicweb 参数接口已全部下线)。
- 旧站历史数据 `http://www.dce.com.cn/dalianshangpin/xqsj/lssj/index.html`:静态镜像,只到 2024 年;年度文件 `/dalianshangpin/resource/cms/...`
  可以 curl 直接下(200),但 2016 zip(csv)/2017 csv/2018–2023 xlsx/2024 xls 格式逐年不同,且为双边口径,只用作交叉核对。

## 2. 反爬与抓取方式

全站是瑞数类反爬:curl/requests 请求任何 HTML 或接口都返回 412 + JS 挑战页;接口带页面 JS 生成的签名参数,不能手工构造。
做法:通过 web-access skill 的 CDP Proxy(`http://localhost:3456`)在用户 Chrome 里新建一个后台 tab 打开任一 dcereport 页面,
在页面上下文里 `fetch(path, {method:"POST", credentials:"include", ...})`,页面自己的脚本会补签名。
`CdpSession` 封装了开/关 tab、`/eval`、JSON 与二进制(base64 分片,一次 eval 返回 >2MB 会超时)取回,站点请求间隔 ≥1 秒(`MIN_INTERVAL`)。
请求失败按 2^n 秒退避重试 4 次,连续失败重开 tab;仍失败写 `error:` 到 missing.log,下次 backfill 自动重试。

## 3. 字段映射

原始文件 gzip 原样落 `raw/`(quotes/receipts 为 JSON,positions 为 zip)。规范化列见 `base.py`。

日行情 `dayQuotes` → QUOTE_COLS

| 接口字段 | 列 | 说明 |
|---|---|---|
| contractId | contract | `normalize_contract` 大写,如 c2701 → C2701;为空的行是 "xx小计"/"总计",剔除;月均价期货 `l2610F` 等不符合合约代码规则,剔除 |
| open/high/low/close | open/high/low/close | 交易所用 0 表示无成交价 → NaN(`validate` 对成交量为 0 的合约也置 NaN)。注意 **成交量>0 但 OHL 为 0** 的情况存在(只有期转现/交割配对成交,如 eb2609 2026-09-15 成交 115 手),此时 close=settle,OHL 记 NaN |
| clearPrice / lastClear | settle / prev_settle | |
| volumn / openInterest | volume / open_interest | 单边口径(见 §4),原值不折算 |
| turnover | turnover | 接口单位万元,×1e4 转元 |

会员持仓排名 zip → POSITION_COLS:每合约 txt 三段(成交量 / 持买单量 / 持卖单量),每段 名次、会员简称、数量、增减,末行 合计。
同一 rank 的三段并排成一行;合计行 rank=0、is_total=True、member_* = "合计"。整个 txt 没有任何名次行的合约(交易所返回空表)略去。

仓单日报 `wbillWeeklyQuotes` → RECEIPT_COLS:`entityList` 每行 varietyOrder(品种代码)、variety、whType、whAbbr、wbillQty、diff。
- `variety` 非空的行是主行:whType 1 是"仓库组"(其数量已含下面的分库),whType 2 是独立仓库;
- `variety` 为空的行是上一主行的分库/子库(whType 2/3),或品种小计(whAbbr 也为空)→ 都略去,避免重复计数;
- `varietyOrder` 为空的是交易所总计行 → 略去;
- 每品种追加 warehouse="合计"、is_total=True 的合计行(主行求和;2026-09-15 各品种合计之和 417,589 = 交易所总计行)。

symbol 用 `varietyOrder` 大写(a→A、jd→JD…),与米筐 underlying_symbol 一致。

## 4. 成交量/持仓量口径(单边/双边)

- 交易所规则:大商所 2019-10-29 通知修改《交易管理办法》中成交量/持仓量定义,**2020-01-01 起由双边改单边**
  (`http://www.dce.com.cn/dce/content/2019/wm/6193854.html`),首个单边交易日 2020-01-02。→ `SINGLE_SIDED_SINCE = 2020-01-02`。
- 但当前 dcereport 接口(本模块数据源)**把 2020 年前的历史也按单边重述了**:2016-01-04 c1601 接口 volume 1147 / OI 2005,
  当年公布(旧站年度包、米筐)是 2294 / 4010;成交额同样减半。→ `API_RESTATED_SINGLE_SIDED = True`。
- 新站/旧站"历史数据"年度打包**全程双边**(页面注明"成交量、持仓量:手(按双边计算)"):2020-01-02 c2005 年度包 342,718 手,接口/米筐 171,359 手。
- 米筐导出沿用交易所当时公布口径:2020-01-02 之前双边,之后单边。
- **本仓库落盘接口原值(全程单边)**,不做折算;与米筐对账时 2020-01-02 前 米筐 = 本仓库 × 2(`volume_factor_vs_ricecta`)。
- 会员排名的成交量/持仓量、仓单数量按接口原值存;排名历史只从 2020-07-20 起(接口和批量下载对更早日期都只返回空表,
  2020-07-17 及更早均验证为空),`POSITIONS_HISTORY_START = 2020-07-20`,更早的工作日直接记 `empty:before-history-start` 不再请求
  (`--probe-positions-history` 可强制逐日请求)。

鸡蛋 JD:交易单位 5 吨/手,报价单位 元/500kg,合约乘数 10(米筐 metadata contract_multiplier 也是 10)。
成交额校验:jd2502 2025-01-02 接口 turnover 223,533.23 万元 = 66,177 手 × 3,377 元 × 10;年度包(双边)4,470,664,600 元 = 2 倍。

## 5. 覆盖率(每类每年交易日文件数,2026-09-16 回填)

回填 2016-01-04 → 2026-09-16,共 2793 个工作日:2602 个交易日全部有行情;191 个工作日为节假日(行情接口返回空表,记入 missing.log),
每年 13–20 天,与法定假期一致;无任何 `error:` 条目(4288+ 次站点请求零失败)。

| 年 | quotes | positions | receipts |
|---|---|---|---|
| 2016 | 244 | 0(交易所无数据) | 244 |
| 2017 | 244 | 0(交易所无数据) | 244 |
| 2018 | 243 | 0(交易所无数据) | 243 |
| 2019 | 244 | 0(交易所无数据) | 244 |
| 2020 | 243 | 113(2020-07-20 起) | 243 |
| 2021 | 243 | 243 | 243 |
| 2022 | 242 | 242 | 242 |
| 2023 | 242 | 242 | 242 |
| 2024 | 242 | 242 | 242 |
| 2025 | 243 | 243 | 243 |
| 2026 | 172(至 09-16) | 172 | 172 |

- quotes:2602 天,每天 178–277 个期货合约行(剔除小计/总计/月均价期货后),全部通过 `validate`。
  与交易所"历史数据"年度打包(2016–2026,存于 `raw/quotes_yearly/`,`crosscheck` 子命令)逐合约逐日比较:
  521,799 行两边完全对齐(无一方多出的合约日),OHLC/结算价 100% 一致,打包成交量/持仓量/成交额 = 本仓库 × 2 的比例 100%——
  证实接口全程单边、打包全程双边,且两者是同一套数据。
- positions:1497 天 = 2020-07-20 起每个交易日,每天 40–101 个合约(有排名的),每合约名次 6–20;三榜名次行求和 = 交易所合计行 100%。
  2016-01-04 → 2020-07-17 的 1105 个工作日交易所接口和批量下载都只返回空表(已逐日验证 2016-01-04、2020-01-02、2020-03-02、2020-06-01、2020-07-01、07-15、07-16、07-17 为空,07-20 起有数据),记 `empty:before-history-start-2020-07-20`。
- receipts:见下方回填结果(每个交易日一份,仓单接口 2016-01-04 起可查)。

## 6. 与米筐导出对账(C、M、Y、P、JD、V、J、I,重叠期 2016-01-04 → 2026-06-05)

`reconcile` 子命令;成交量/持仓量按 §4 折算(2020-01-02 前 米筐 = 本仓库 × 2)。

| symbol | 重叠行数 | OHLC 一致 | volume 一致 | OI 一致 | 有成交但无撮合价(不比 OHLC) |
|---|---|---|---|---|---|
| C | 15,180 | 100.00% | 99.49% | 99.23% | 12 |
| M | 20,240 | 99.98% | 99.47% | 99.34% | 27 |
| Y | 20,240 | 100.00% | 99.93% | 99.83% | 37 |
| P | 30,360 | 99.99% | 99.90% | 99.92% | 52 |
| JD | 30,089 | 99.98% | 99.95% | 99.65% | 5 |
| V | 30,360 | 99.99% | 99.82% | 99.81% | 39 |
| J | 30,360 | 99.98% | 99.96% | 99.95% | 118 |
| I | 30,360 | 99.97% | 99.66% | 99.68% | 47 |

共 207,189 行,665 行不一致(0.32%),两类原因,**都不在本仓库侧**(这些行本仓库与交易所年度打包完全一致):
1. 交割月内(221 行):交割月最后几个交易日交易所公布的持仓量已扣除交割配对(最后交易日常为 0,如 P2005 2020-05-19 交易所 0、米筐 4,161;
   C2005 2020-05-06 交易所 29,347、米筐 70,101),米筐保留配对前口径;成交量差异同理(交割配对成交)。
2. 非交割月(444 行,170 个日期):米筐个别日期数值偏小(96.6% 的行米筐成交量 < 交易所,持仓量 55%),集中在每月 6–7 日附近和 2020-03~04
   (如 2021-11-08 33 行、2020-04-07 13 行、C1905 2019-04-08 米筐 163,308 vs 交易所 190,034),看起来是米筐侧当日快照不完整;
   其中 23 行 OHLC 也差 1–3 个最小变动价位(同一批日期)。
米筐无成交日 OHLC 填收盘价、本仓库为 NaN,不计入比较。

口径结论:**用交易所接口数据替换/拼接米筐时,2020-01-02 之前成交量、持仓量、成交额要 ×2 才与米筐同口径;之后直接可拼**;
若要全程单边,反过来把米筐 2020-01-02 前的值 ÷2。

## 7. 已知坑

- 一次 `/eval` 返回超过 ~2MB 的字符串会 "CDP 命令超时",二进制响应必须存到 window 变量再分片取回。
- ant-design 日期框直接改 value 不触发查询;要模拟 mousedown 打开面板再点 `td[title="YYYY-MM-DD"]`。本模块直接调接口,不碰 UI。
- 交易所把无成交价记为 0,不是 null;成交量>0 且 OHL=0 的行确实存在(期转现/交割配对),`base.validate` 会拒绝 0,所以解析时先转 NaN。
- 行情接口在非交易日只返回一行 "总计" 全 0,不报错;仓单接口在非交易日返回空 entityList;用 `tradeDateNum` 或行情空表判定节假日。
- 月均价期货(聚乙烯/聚氯乙烯/聚丙烯月均价,代码 `l2610F`)混在期货行情里,已剔除。
- 会员排名 txt 里名次可能不足 20(小合约),三段长度可不同;个别合约整段为空。
- 米筐无成交日 OHLC 填收盘价,本仓库为 NaN,对账时只比较有成交且有撮合价的行。
- 老 `publicweb` 页面 500、`m.dce.com.cn` 域名已无;旧站静态镜像 2025-05 后不更新。
