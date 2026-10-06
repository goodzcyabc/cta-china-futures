# 交易所参数复核补充表 (SHFE 9 + CZCE 13 品种)

- 参数快照: 2026-09-18 交易所结算参数/交易参数; 生成日 2026-09-18; 口径同 docs/instruments_verification.md(一般月份/主力档, 交易所投机标准)
- 复核: 22 品种 × 6 字段 = 132 项; verified 132, corrected 0, unverified 0; 与当前 YAML 差异 88 处(乘数/跳价 0 处差异)
- 范围: 上期所 FU/BU/ZN/HC/PB/SP/SS/BR/AO, 郑商所 FG/OI/SF/RM/SM/AP/UR/CJ/PF/PK/SH/PX/PR; 大商所/能源中心由另一任务核验

## 1. 最终参数表

| symbol | exchange | name | multiplier | tick | margin_rate | fee_per_lot | fee_notional_bp | limit_pct | fee_close_today | effective | source | status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| FU | SHFE | 燃料油 | 10 | 1 | 0.16 | 0 | 0.5 | 0.14 | 0 bp | 2026-06-25 结算起 16%/14%(上期发〔2026〕249号); 手续费 2026-06-25 交易起(250号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html | verified |
| BU | SHFE | 石油沥青 | 10 | 1 | 0.12 | 0 | 0.5 | 0.1 | 0 bp | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 手续费 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html | verified |
| ZN | SHFE | 锌 | 5 | 5 | 0.11 | 3.0 | 0 | 0.09 | 0 元/手 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html | verified |
| HC | SHFE | 热轧卷板 | 10 | 1 | 0.07 | 0 | 1.0 | 0.05 | 1.0 bp | 2026-05-19 结算起 7%/5%(上期发〔2026〕191号); 主力月 万分之1(2016-04-25 起), 非主力月 0.2(2024-05-31 起) | https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html | verified |
| PB | SHFE | 铅 | 5 | 5 | 0.11 | 0 | 0.4 | 0.09 | 0 bp | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之0.4 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html | verified |
| SP | SHFE | 纸浆 | 10 | 2 | 0.07 | 0 | 0.2 | 0.05 | 0 bp | 2026-07-10 结算起 7%/5%(上期发〔2026〕260号); 手续费 万分之0.2 2026-07-10 交易起(261号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html | verified |
| SS | SHFE | 不锈钢 | 5 | 5 | 0.07 | 2.0 | 0 | 0.05 | 0 元/手 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html | verified |
| BR | SHFE | 丁二烯橡胶 | 5 | 5 | 0.12 | 0 | 0.2 | 0.1 | 0.2 bp | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 万分之0.2 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html | verified |
| AO | SHFE | 氧化铝 | 20 | 1 | 0.11 | 0 | 1.0 | 0.09 | 1.0 bp | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之1 2025-04-08 起(〔2025〕92号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html | verified |
| FG | CZCE | 玻璃 | 20 | 1 | 0.09 | 2.0 | 0 | 0.08 | 2.0 元/手 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm | verified |
| OI | CZCE | 菜籽油 | 10 | 1 | 0.07 | 2.0 | 0 | 0.06 | 2.0 元/手 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf | verified |
| SF | CZCE | 硅铁 | 5 | 2 | 0.07 | 2.0 | 0 | 0.06 | 0 元/手 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm | verified |
| RM | CZCE | 菜籽粕 | 10 | 1 | 0.07 | 1.5 | 0 | 0.06 | 0 元/手 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm | verified |
| SM | CZCE | 锰硅 | 5 | 2 | 0.07 | 2.0 | 0 | 0.06 | 0 元/手 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm | verified |
| AP | CZCE | 苹果 | 10 | 1 | 0.09 | 5.0 | 0 | 0.08 | 10.0 元/手 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm | verified |
| UR | CZCE | 尿素 | 20 | 1 | 0.08 | 0 | 1.0 | 0.07 | 1.0 bp | 万分之1/平今万分之1 2023-08-03 起(郑商函〔2023〕559号); 8%/7% 品种级基准(2024-12 起未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/07/1689460847817820.htm | verified |
| CJ | CZCE | 红枣 | 5 | 5 | 0.08 | 3.0 | 0 | 0.07 | 3.0 元/手 | 8%/7% 2026-05-06 起(郑商函〔2026〕402号); 3元/手 长期基准(结算参数确认) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm | verified |
| PF | CZCE | 短纤 | 5 | 2 | 0.07 | 2.0 | 0 | 0.06 | 0 元/手 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm | verified |
| PK | CZCE | 花生 | 5 | 2 | 0.07 | 2.0 | 0 | 0.06 | 2.0 元/手 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm | verified |
| SH | CZCE | 烧碱 | 30 | 1 | 0.08 | 0 | 1.0 | 0.07 | 0 bp | 万分之1 上市起(郑商函〔2023〕692号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 8%/7% 品种级基准(2024-12 起未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464652925099.htm | verified |
| PX | CZCE | 对二甲苯 | 5 | 2 | 0.07 | 0 | 1.0 | 0.06 | 0 bp | 万分之1 上市起(郑商函〔2023〕693号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 7%/6% 2025-10-09 起(〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464653277405.htm | verified |
| PR | CZCE | 瓶片 | 15 | 2 | 0.07 | 0 | 0.5 | 0.06 | 0 bp | 万分之0.5、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm | verified |

YAML 片段(可直接替换对应 symbols 行; fee_close_today 单位: 元/手品种同 fee_per_lot, 比例品种为 bp):

```yaml
  FU: {exchange: SHFE, name: 燃料油, multiplier: 10, tick: 1, margin_rate: 0.16, fee_per_lot: 0, fee_notional_bp: 0.5, limit_pct: 0.14, fee_close_today: 0}
  BU: {exchange: SHFE, name: 石油沥青, multiplier: 10, tick: 1, margin_rate: 0.12, fee_per_lot: 0, fee_notional_bp: 0.5, limit_pct: 0.1, fee_close_today: 0}
  ZN: {exchange: SHFE, name: 锌, multiplier: 5, tick: 5, margin_rate: 0.11, fee_per_lot: 3.0, fee_notional_bp: 0, limit_pct: 0.09, fee_close_today: 0}
  HC: {exchange: SHFE, name: 热轧卷板, multiplier: 10, tick: 1, margin_rate: 0.07, fee_per_lot: 0, fee_notional_bp: 1.0, limit_pct: 0.05, fee_close_today: 1.0}
  PB: {exchange: SHFE, name: 铅, multiplier: 5, tick: 5, margin_rate: 0.11, fee_per_lot: 0, fee_notional_bp: 0.4, limit_pct: 0.09, fee_close_today: 0}
  SP: {exchange: SHFE, name: 纸浆, multiplier: 10, tick: 2, margin_rate: 0.07, fee_per_lot: 0, fee_notional_bp: 0.2, limit_pct: 0.05, fee_close_today: 0}
  SS: {exchange: SHFE, name: 不锈钢, multiplier: 5, tick: 5, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.05, fee_close_today: 0}
  BR: {exchange: SHFE, name: 丁二烯橡胶, multiplier: 5, tick: 5, margin_rate: 0.12, fee_per_lot: 0, fee_notional_bp: 0.2, limit_pct: 0.1, fee_close_today: 0.2}
  AO: {exchange: SHFE, name: 氧化铝, multiplier: 20, tick: 1, margin_rate: 0.11, fee_per_lot: 0, fee_notional_bp: 1.0, limit_pct: 0.09, fee_close_today: 1.0}
  FG: {exchange: CZCE, name: 玻璃, multiplier: 20, tick: 1, margin_rate: 0.09, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.08, fee_close_today: 2.0}
  OI: {exchange: CZCE, name: 菜籽油, multiplier: 10, tick: 1, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 2.0}
  SF: {exchange: CZCE, name: 硅铁, multiplier: 5, tick: 2, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 0}
  RM: {exchange: CZCE, name: 菜籽粕, multiplier: 10, tick: 1, margin_rate: 0.07, fee_per_lot: 1.5, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 0}
  SM: {exchange: CZCE, name: 锰硅, multiplier: 5, tick: 2, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 0}
  AP: {exchange: CZCE, name: 苹果, multiplier: 10, tick: 1, margin_rate: 0.09, fee_per_lot: 5.0, fee_notional_bp: 0, limit_pct: 0.08, fee_close_today: 10.0}
  UR: {exchange: CZCE, name: 尿素, multiplier: 20, tick: 1, margin_rate: 0.08, fee_per_lot: 0, fee_notional_bp: 1.0, limit_pct: 0.07, fee_close_today: 1.0}
  CJ: {exchange: CZCE, name: 红枣, multiplier: 5, tick: 5, margin_rate: 0.08, fee_per_lot: 3.0, fee_notional_bp: 0, limit_pct: 0.07, fee_close_today: 3.0}
  PF: {exchange: CZCE, name: 短纤, multiplier: 5, tick: 2, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 0}
  PK: {exchange: CZCE, name: 花生, multiplier: 5, tick: 2, margin_rate: 0.07, fee_per_lot: 2.0, fee_notional_bp: 0, limit_pct: 0.06, fee_close_today: 2.0}
  SH: {exchange: CZCE, name: 烧碱, multiplier: 30, tick: 1, margin_rate: 0.08, fee_per_lot: 0, fee_notional_bp: 1.0, limit_pct: 0.07, fee_close_today: 0}
  PX: {exchange: CZCE, name: 对二甲苯, multiplier: 5, tick: 2, margin_rate: 0.07, fee_per_lot: 0, fee_notional_bp: 1.0, limit_pct: 0.06, fee_close_today: 0}
  PR: {exchange: CZCE, name: 瓶片, multiplier: 15, tick: 2, margin_rate: 0.07, fee_per_lot: 0, fee_notional_bp: 0.5, limit_pct: 0.06, fee_close_today: 0}
```

## 2. 与当前 YAML 的差异清单 (88 处)

| # | symbol | field | old | new | 依据/生效 | source |
|---:|---|---|---:|---:|---|---|
| 1 | FU | margin_rate | 0.1 | 0.16 | 2026-06-25 结算起 16%/14%(上期发〔2026〕249号); 手续费 2026-06-25 交易起(250号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html |
| 2 | FU | fee_notional_bp | 1.0 | 0.5 | 2026-06-25 结算起 16%/14%(上期发〔2026〕249号); 手续费 2026-06-25 交易起(250号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html |
| 3 | FU | limit_pct | 0.07 | 0.14 | 2026-06-25 结算起 16%/14%(上期发〔2026〕249号); 手续费 2026-06-25 交易起(250号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html |
| 4 | FU | fee_close_today | 1.0 | 0 | 2026-06-25 结算起 16%/14%(上期发〔2026〕249号); 手续费 2026-06-25 交易起(250号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html |
| 5 | BU | margin_rate | 0.1 | 0.12 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 手续费 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 6 | BU | fee_notional_bp | 1.0 | 0.5 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 手续费 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 7 | BU | limit_pct | 0.07 | 0.1 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 手续费 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 8 | BU | fee_close_today | 1.0 | 0 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 手续费 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 9 | ZN | margin_rate | 0.1 | 0.11 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 10 | ZN | fee_per_lot | 0 | 3.0 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 11 | ZN | fee_notional_bp | 1.0 | 0 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 12 | ZN | limit_pct | 0.07 | 0.09 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 13 | ZN | fee_close_today | 1.0 | 0 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 3元/手 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 14 | HC | margin_rate | 0.1 | 0.07 | 2026-05-19 结算起 7%/5%(上期发〔2026〕191号); 主力月 万分之1(2016-04-25 起), 非主力月 0.2(2024-05-31 起) | https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html |
| 15 | HC | limit_pct | 0.07 | 0.05 | 2026-05-19 结算起 7%/5%(上期发〔2026〕191号); 主力月 万分之1(2016-04-25 起), 非主力月 0.2(2024-05-31 起) | https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html |
| 16 | PB | margin_rate | 0.1 | 0.11 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之0.4 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 17 | PB | fee_notional_bp | 1.0 | 0.4 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之0.4 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 18 | PB | limit_pct | 0.07 | 0.09 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之0.4 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 19 | PB | fee_close_today | 1.0 | 0 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之0.4 2012-09-01 起; 平今免 2014-04-01 起 | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 20 | SP | margin_rate | 0.1 | 0.07 | 2026-07-10 结算起 7%/5%(上期发〔2026〕260号); 手续费 万分之0.2 2026-07-10 交易起(261号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 21 | SP | fee_notional_bp | 1.0 | 0.2 | 2026-07-10 结算起 7%/5%(上期发〔2026〕260号); 手续费 万分之0.2 2026-07-10 交易起(261号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 22 | SP | limit_pct | 0.07 | 0.05 | 2026-07-10 结算起 7%/5%(上期发〔2026〕260号); 手续费 万分之0.2 2026-07-10 交易起(261号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 23 | SP | fee_close_today | 1.0 | 0 | 2026-07-10 结算起 7%/5%(上期发〔2026〕260号); 手续费 万分之0.2 2026-07-10 交易起(261号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 24 | SS | margin_rate | 0.1 | 0.07 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 25 | SS | fee_per_lot | 0 | 2.0 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 26 | SS | fee_notional_bp | 1.0 | 0 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 27 | SS | limit_pct | 0.07 | 0.05 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 28 | SS | fee_close_today | 1.0 | 0 | 2026-07-02 结算起 7%/5%(上期发〔2026〕253号); 2元/手、平今免 2020-07-07 起(〔2020〕236号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 29 | BR | margin_rate | 0.1 | 0.12 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 万分之0.2 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 30 | BR | fee_notional_bp | 1.0 | 0.2 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 万分之0.2 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 31 | BR | limit_pct | 0.07 | 0.1 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 万分之0.2 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 32 | BR | fee_close_today | 1.0 | 0.2 | 2026-07-10 结算起 12%/10%(上期发〔2026〕260号); 万分之0.2 2024-04-26 起(〔2024〕126号) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 33 | AO | margin_rate | 0.1 | 0.11 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之1 2025-04-08 起(〔2025〕92号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 34 | AO | limit_pct | 0.07 | 0.09 | 2026-07-02 结算起 11%/9%(上期发〔2026〕253号); 万分之1 2025-04-08 起(〔2025〕92号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 35 | FG | margin_rate | 0.1 | 0.09 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 36 | FG | fee_per_lot | 0 | 2.0 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 37 | FG | fee_notional_bp | 1.0 | 0 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 38 | FG | limit_pct | 0.07 | 0.08 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 39 | FG | fee_close_today | 1.0 | 2.0 | 2026-06-05 结算起 9%/8%, 夜盘起 2元/手(郑商函〔2026〕476号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 40 | OI | margin_rate | 0.1 | 0.07 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf |
| 41 | OI | fee_per_lot | 0 | 2.0 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf |
| 42 | OI | fee_notional_bp | 1.0 | 0 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf |
| 43 | OI | limit_pct | 0.07 | 0.06 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf |
| 44 | OI | fee_close_today | 1.0 | 2.0 | 2元/手 2018-01-02 夜盘起(郑商发〔2017〕302号); 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf |
| 45 | SF | margin_rate | 0.1 | 0.07 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 46 | SF | fee_per_lot | 0 | 2.0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 47 | SF | fee_notional_bp | 1.0 | 0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 48 | SF | limit_pct | 0.07 | 0.06 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 49 | SF | fee_close_today | 1.0 | 0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 50 | RM | margin_rate | 0.1 | 0.07 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 51 | RM | fee_per_lot | 0 | 1.5 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 52 | RM | fee_notional_bp | 1.0 | 0 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 53 | RM | limit_pct | 0.07 | 0.06 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 54 | RM | fee_close_today | 1.0 | 0 | 平今免 2026-06-23 夜盘起(公告〔2026〕91号); 1.5元/手 长期基准; 7%/6% 品种级基准(2024-12 起, 2025-05-20 恢复后未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 55 | SM | margin_rate | 0.1 | 0.07 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 56 | SM | fee_per_lot | 0 | 2.0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 57 | SM | fee_notional_bp | 1.0 | 0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 58 | SM | limit_pct | 0.07 | 0.06 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 59 | SM | fee_close_today | 1.0 | 0 | 2026-06-24 结算起 7%/6%, 2元/手(郑商所公告〔2026〕91号); 平今免 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 60 | AP | margin_rate | 0.1 | 0.09 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 61 | AP | fee_per_lot | 0 | 5.0 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 62 | AP | fee_notional_bp | 1.0 | 0 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 63 | AP | limit_pct | 0.07 | 0.08 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 64 | AP | fee_close_today | 1.0 | 10.0 | 9%/8% 2026-05-06 起(郑商函〔2026〕402号); 平今10元 2026-06-08 起(477号); 5元/手 长期基准 | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 65 | UR | margin_rate | 0.1 | 0.08 | 万分之1/平今万分之1 2023-08-03 起(郑商函〔2023〕559号); 8%/7% 品种级基准(2024-12 起未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/07/1689460847817820.htm |
| 66 | CJ | margin_rate | 0.1 | 0.08 | 8%/7% 2026-05-06 起(郑商函〔2026〕402号); 3元/手 长期基准(结算参数确认) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 67 | CJ | fee_per_lot | 0 | 3.0 | 8%/7% 2026-05-06 起(郑商函〔2026〕402号); 3元/手 长期基准(结算参数确认) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 68 | CJ | fee_notional_bp | 1.0 | 0 | 8%/7% 2026-05-06 起(郑商函〔2026〕402号); 3元/手 长期基准(结算参数确认) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 69 | CJ | fee_close_today | 1.0 | 3.0 | 8%/7% 2026-05-06 起(郑商函〔2026〕402号); 3元/手 长期基准(结算参数确认) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm |
| 70 | PF | margin_rate | 0.1 | 0.07 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 71 | PF | fee_per_lot | 0 | 2.0 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 72 | PF | fee_notional_bp | 1.0 | 0 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 73 | PF | limit_pct | 0.07 | 0.06 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 74 | PF | fee_close_today | 1.0 | 0 | 2元/手、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 75 | PK | margin_rate | 0.1 | 0.07 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 76 | PK | fee_per_lot | 0 | 2.0 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 77 | PK | fee_notional_bp | 1.0 | 0 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 78 | PK | limit_pct | 0.07 | 0.06 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 79 | PK | fee_close_today | 1.0 | 2.0 | 2元/手 2026-06-24 起(公告〔2026〕91号); 7%/6% 2025-10-09 起(郑商函〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 80 | SH | margin_rate | 0.1 | 0.08 | 万分之1 上市起(郑商函〔2023〕692号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 8%/7% 品种级基准(2024-12 起未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464652925099.htm |
| 81 | SH | fee_close_today | 1.0 | 0 | 万分之1 上市起(郑商函〔2023〕692号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 8%/7% 品种级基准(2024-12 起未变) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464652925099.htm |
| 82 | PX | margin_rate | 0.1 | 0.07 | 万分之1 上市起(郑商函〔2023〕693号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 7%/6% 2025-10-09 起(〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464653277405.htm |
| 83 | PX | limit_pct | 0.07 | 0.06 | 万分之1 上市起(郑商函〔2023〕693号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 7%/6% 2025-10-09 起(〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464653277405.htm |
| 84 | PX | fee_close_today | 1.0 | 0 | 万分之1 上市起(郑商函〔2023〕693号); 平今免 2024-05-29 夜盘起(〔2024〕323号); 7%/6% 2025-10-09 起(〔2025〕735号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464653277405.htm |
| 85 | PR | margin_rate | 0.1 | 0.07 | 万分之0.5、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 86 | PR | fee_notional_bp | 1.0 | 0.5 | 万分之0.5、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 87 | PR | limit_pct | 0.07 | 0.06 | 万分之0.5、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |
| 88 | PR | fee_close_today | 1.0 | 0 | 万分之0.5、平今免 2025-03-14 夜盘起(郑商函〔2025〕204号); 7%/6% 2025-02-05 起(〔2025〕71号) | http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm |

差异归因: YAML 中这 21 个品种的 margin_rate(0.10)/limit_pct(0.07)/fee_notional_bp(1.0)/fee_close_today(1.0 bp) 均为数据反推占位值, 乘数与跳价全部正确; 元/手计费品种(ZN/SS/FG/OI/SF/RM/SM/AP/CJ/PF/PK)需把 fee_notional_bp 归零并改用 fee_per_lot。

## 3. 平今手续费备注

| 情形 | 品种 | 说明 |
|---|---|---|
| 平今 > 开仓 | **AP** 苹果 (10 元 vs 5 元, 2 倍) | 日内往返实收 15 元/手 |
| 平今免收 (0) | FU, BU, ZN, PB, SP, SS, SF, SM, RM, PF, SH, PX, PR | 日内往返仅付一次开仓费; RM 自 2026-06-23 夜盘起免收; FU 2026-06-25 起恢复免收(2026-03-11~06-24 曾收 万分之3); BU 2024-04-26 起免收 |
| 平今 = 开仓 | HC, BR, AO, FG, OI, UR, CJ, PK | 同开仓价; HC/BR/AO/UR 为比例值, 其余元/手 |

## 4. 逐品种来源与备注

### FU 燃料油 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-06-25 收盘结算起(上期发〔2026〕249号: 14%/套保15%/一般16%, 全部合约); FU2610/FU2611 自 2026-09-14 收盘结算起升为 16%/17%/18%(上期发〔2026〕316号). 手续费: 2026-06-25 交易起(上期发〔2026〕250号: 1/5/9 月合约 万分之0.5, 其他月 万分之0.1, 进入交割月前第二月起恢复 0.5, 平今免收)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832251.html ; https://www.shfe.com.cn/publicnotice/notice/202609/t20260911_833382.html ; https://www.shfe.com.cn/publicnotice/notice/202606/t20260623_832256.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/energyandchemical/fu_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: FU2610~2611: 18%/16%; FU2612+: 16%/14%
- 备注: 主力档取 FU2701/2705/2709 等 1/5/9 月合约: 16%/14%, 万分之0.5; 非 1/5/9 月合约 万分之0.1(FU2612/2702/2703/2704/2706/2707/2708). FU2610/2611 现为 18%/16%(近月加档). 2026 年 3-6 月中东局势下多次调整: 2026-03-10 起 22%/20%(99号), 2026-06-02 起 19%/17%(213号), 2026-03-11~06-24 手续费临时为 万分之1、平今 万分之3(95号); 回测该区间需分段. 合约文本 8%/5% 仅为下限.

### BU 石油沥青 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-10 收盘结算起(上期发〔2026〕260号: 10%/套保11%/一般12%, 全部合约). 手续费: 2024-04-26 交易起(上期发〔2024〕126号: 万分之0.5, 免收平今)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html ; https://www.shfe.com.cn/publicnotice/notice/202404/t20240423_801626.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/energyandchemical/bu_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: 全部合约 12%/10%
- 备注: 所有上市合约同档(bu2809 为 2026-09-16 新挂牌合约, 涨跌停 20% 系新合约上市初期 2 倍幅度, 有成交后恢复). 2026-03-10~07-09 曾为 14%/12%(99号/93号), 2026-02-05 起曾 11%/9%(54号), 2025-12-09 起曾 9%/7%(上期发〔2025〕352号). 合约文本 4%/3% 仅为下限.

### ZN 锌 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-02 收盘结算起(上期发〔2026〕253号: ZN2607~ZN2702 9%/套保10%/一般11%); 手续费 3 元/手: 2012-09-01 起(上期办发〔2012〕105号, 由 4 元下调); 平今免收: 2014-04-01 起(上期办发〔2014〕32号)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/publicnotice/notice/201208/t20120802_789152.html ; https://www.shfe.com.cn/publicnotice/notice/201403/t20140320_790284.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/metal/nonferrousmetal/zn_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: zn2610~2702: 11%/9%; zn2703+: 9%/7%
- 备注: 分档: zn2610~2702 11%/9%(主力档, 表中取此档), zn2703 及以后 9%/7%(2026-09-18 结算参数). 2026-02-09~07-01 曾为 12%/10%(上期发〔2026〕56号). 平今折扣率 0(结算参数 DISCOUNTRATE=0). 合约文本 5%/4% 仅为下限.

### HC 热轧卷板 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-05-19 收盘结算起(上期发〔2026〕191号: hc2606~hc2702 5%/套保6%/一般7%). 手续费: 1/5/10 月合约 万分之1(2016-04-25 起, 上期发〔2016〕65号); 其他月合约 万分之0.2, 进入交割月前第二月起恢复 万分之1(2024-05-31 交易起, 上期发〔2024〕186号); 平今与开仓同价
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html ; https://www.shfe.com.cn/publicnotice/notice/202405/t20240529_801782.html ; https://www.shfe.com.cn/publicnotice/notice/201604/t20160421_791523.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/hc_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: hc2611+: 7%/5%; hc2610: 10%/5%
- 备注: 手续费按月份分档(同 RB): 1/5/10 月合约(主力)及进入交割月前第二月起的合约 万分之1(hc2610/2611/2701/2705); 其余月份 万分之0.2. 表中取主力月标准. hc2610(交割月前一月) 保证金 10%. hc2703 及以后新上市合约同为 7%/5%. 合约文本 4%/3% 仅为下限.

### PB 铅 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-02 收盘结算起(上期发〔2026〕253号: PB2607~PB2702 9%/套保10%/一般11%); 手续费 万分之0.4: 2012-09-01 起(上期办发〔2012〕105号, 由 0.5 下调); 平今免收: 2014-04-01 起(上期办发〔2014〕32号)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/publicnotice/notice/201208/t20120802_789152.html ; https://www.shfe.com.cn/publicnotice/notice/201403/t20140320_790284.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/metal/nonferrousmetal/pb_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: pb2610~2702: 11%/9%; pb2703+: 9%/7%
- 备注: 分档: pb2610~2702 11%/9%(主力档), pb2703 及以后 9%/7%. 2026-02-09~07-01 曾为 12%/10%(56号). 平今折扣率 0. 合约文本 5%/4% 仅为下限.

### SP 纸浆 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-10 收盘结算起(上期发〔2026〕260号: SP2607~SP2703 5%/套保6%/一般7%). 手续费: 2026-07-10 交易起(上期发〔2026〕261号: 万分之0.2, 附件一览表平今 0)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html ; https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832508.html ; https://www.shfe.com.cn/publicnotice/notice/202607/W020260708666030903356.doc ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/energyandchemical/sp_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: sp2611+: 7%/5%; sp2610: 10%/5%
- 备注: 2026-07-10 前手续费 万分之0.5(结算参数 2026-06-01~07-09), 涨跌停/保证金 7%/9%(2026-02-05 起, 54号); 2025-10-14~2026-02-04 为 5%/7%(上期发〔2025〕287号). sp2610(交割月前一月) 10%; sp2704 及以后新上市合约同为 7%/5%. 平今免收(折扣率 0). 合约文本 4%/3% 仅为下限.

### SS 不锈钢 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-02 收盘结算起(上期发〔2026〕253号: SS2607~SS2702 5%/套保6%/一般7%; 此前 2026-05-19 起为 6%/7%/8%, 191号). 手续费 2 元/手、平今免收: 2020-07-07 交易起(上期发〔2020〕236号, 由 万分之1 改为 2 元/手)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html ; https://www.shfe.com.cn/publicnotice/notice/202007/t20200702_796124.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/metal/ferrousandpreciousmetal/ss_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: ss2611+: 7%/5%; ss2610: 10%/5%
- 备注: ss2610(交割月前一月) 10%; ss2611 及以后 7%/5%. 2026-02-09~05-18 曾为 10%/8%(56号). 平今折扣率 0. 合约文本 5%/4% 仅为下限.

### BR 丁二烯橡胶 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-10 收盘结算起(上期发〔2026〕260号: 10%/套保11%/一般12%, 全部合约). 手续费: 2024-04-26 交易起(上期发〔2024〕126号: 万分之0.2, 平今 万分之0.2)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html ; https://www.shfe.com.cn/publicnotice/notice/202404/t20240423_801626.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/energyandchemical/br_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: 全部合约 12%/10%
- 备注: 所有上市合约同档 12%/10%. 2026-03-10~07-09 曾为 14%/12%(93号/99号); 2025-10-14 起曾 9%/7%(上期发〔2025〕288号). 平今与开仓同价(折扣率 1); 2024-2025 年曾多次对特定合约临时上调平今至 万分之0.6~1. 合约文本 7%/5% 仅为下限. 上市初(2023-07-28)为 万分之1(2023-09-08 起 万分之1/平今万分之1, 上期发〔2023〕295号).

### AO 氧化铝 (SHFE) — verified
- 生效/依据: 涨跌停/保证金: 2026-07-02 收盘结算起(上期发〔2026〕253号: AO2607~AO2702 9%/套保10%/一般11%). 手续费: 2025-04-08 交易起(上期发〔2025〕92号: 万分之1, 平今 万分之1; 2025-03-11~04-07 曾 万分之1.5)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/publicnotice/notice/202504/t20250401_824937.html ; https://www.shfe.com.cn/publicnotice/notice/202503/t20250307_824724.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260918.dat ; https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument20260918.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx ; https://www.shfe.com.cn/products/futures/metal/nonferrousmetal/ao_f/
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: ao2610~2702: 11%/9%; ao2703+: 9%/7%
- 备注: 分档: ao2610~2702 11%/9%(主力档), ao2703 及以后 9%/7%. 2026-02-09~07-01 曾为 12%/10%(56号); 2025-11-07 起曾 9%/7%(上期发〔2025〕319号). 平今与开仓同价(折扣率 1); 2024-10~2025-05 曾对特定合约临时上调至 万分之3. 合约文本 5%/4% 仅为下限.

### FG 玻璃 (CZCE) — verified
- 生效/依据: 保证金 9%/涨跌停 8%: 2026-06-05 结算起; 手续费 2 元/手、平今 2 元/手: 2026-06-05 夜盘起(郑商函〔2026〕476号, 由 6 元/手下调)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/bl/bzhy/qhhy/H077002009001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: FG611+: 9%/8%; FG610: 10%/8%
- 备注: 2026-06-05 前: 手续费 6 元/手(平今 6 元), 保证金 10%/涨跌停 9%(2026-05-06 起; 2026-02-12~02-23、04-29~05-05 假期临时 12%/10%). FG610(近月) 保证金 10%. 2026-09-29 结算起国庆临时 10%/9%(郑商函〔2026〕860号), 10-08 后恢复. 合约文本 5% 仅为下限.

### OI 菜籽油 (CZCE) — verified
- 生效/依据: 手续费 2 元/手: 2018-01-02 夜盘起(郑商发〔2017〕302号, 由 2.5 元下调), 平今同价; 保证金 7%/涨跌停 6%: 品种级长期基准(结算参数回溯: 2024-12-13 起即为 7%/6%, 仅 2025-04-02~05-19 因清明/劳动节通知(郑商函〔2025〕241号/313号)临时 9%/8%, 2025-05-20 起恢复; 其后各假期临时上调均恢复)
- 一手来源: https://www.czce.com.cn/cn/rootfiles/2018/05/07/1526089634085979-1526089634138361.pdf ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/czy/bzhy/qhhy/H077002006001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: 全部合约 7%/6%
- 备注: 平今不免收(2 元/手). 2026-09-29 结算起国庆临时 9%/8%(郑商函〔2026〕860号), 10-08 后恢复. 合约文本 5% 仅为下限.

### SF 硅铁 (CZCE) — verified
- 生效/依据: 保证金 7%/涨跌停 6%: 2026-06-24 结算起; 手续费 2 元/手: 2026-06-24 起(郑商所公告〔2026〕91号, 由 3 元/手下调); 平今免收: 长期基准(2026-09-18 结算参数平今 0)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/gt/bzhy/qhhy/H077002017001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: SF611+: 7%/6%; SF610: 10%/6%
- 备注: 2026-06-24 前: 3 元/手、8%/7%(2025-05-06 起, 郑商函〔2025〕313号). SF610(近月) 10%. 2026-09-29 结算起国庆临时 9%/8%(860号). 平今免收的原始公告未定位, 以结算参数(平今 0.00)为准. 合约文本 5% 仅为下限.

### RM 菜籽粕 (CZCE) — verified
- 生效/依据: 平今免收: 2026-06-23 夜盘起(郑商所公告〔2026〕91号); 手续费 1.5 元/手: 长期基准(收费一览表+结算参数确认, 原始公告未定位); 保证金 7%/涨跌停 6%: 品种级长期基准(结算参数回溯: 2024-12-13 起即为 7%/6%, 2025-03-10~03-16、04-02~05-19 临时上调(郑商函〔2025〕241号/313号等), 2025-05-20 起恢复)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/czp/bzhy/qhhy/H077002011001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: 全部合约 7%/6%
- 备注: 2026-06-23 前平今 1.5 元/手. 2026-09-29 结算起国庆临时 9%/8%(860号). 合约文本 5% 仅为下限.

### SM 锰硅 (CZCE) — verified
- 生效/依据: 保证金 7%/涨跌停 6%: 2026-06-24 结算起; 手续费 2 元/手: 2026-06-24 起(郑商所公告〔2026〕91号, 由 3 元/手下调); 平今免收: 长期基准(结算参数平今 0)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/meng/bzhy/qhhy/H077002020001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: SM611+: 7%/6%; SM610: 10%/6%
- 备注: 2026-06-24 前: 3 元/手、8%/7%(2026-02-24 春节后恢复时定为 8%/7%, 郑商函〔2026〕182号; 此前 9%/8%). SM610(近月) 10%. 2026-09-29 结算起国庆临时 9%/8%(860号). 合约文本 5% 仅为下限.

### AP 苹果 (CZCE) — verified
- 生效/依据: 保证金 9%/涨跌停 8%: 2026-05-06 恢复交易后首个非单边市交易日结算起(郑商函〔2026〕402号第二条); 平今 10 元/手: 2026-06-08 起(郑商函〔2026〕477号, 由 20 元下调); 开仓 5 元/手: 长期基准(收费一览表+结算参数确认)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/92b969f5573e42c695757733c5df0134.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/pg/bzhy/qhhy/H077002021001001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: AP611+: 9%/8%; AP610: 10%/8%
- 备注: 平今 10 元 = 开仓 2 倍, 日内往返 15 元. 2026-05-06 前 10%/9%. AP610(近月) 10%. 2026-09-29 结算起国庆临时 10%/9%(860号). 合约文本 7% 仅为下限.

### UR 尿素 (CZCE) — verified
- 生效/依据: 手续费 万分之1、平今 万分之1: 2023-08-03 起(郑商函〔2023〕559号); 保证金 8%/涨跌停 7%: 品种级长期基准(结算参数回溯: 2024-12-13 起即为 8%/7%, 各假期临时上调后均恢复)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/07/1689460847817820.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/nsqh/bzhy/qhhy/H077002023002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: UR611+: 8%/7%; UR610: 10%/7%
- 备注: 按成交金额比例收取, 平今不免收. UR610(近月) 10%. 2026-09-29 结算起国庆临时 9%/8%(860号). 合约文本 5% 仅为下限.

### CJ 红枣 (CZCE) — verified
- 生效/依据: 保证金 8%/涨跌停 7%: 2026-05-06 恢复交易后首个非单边市交易日结算起(郑商函〔2026〕402号第二条, 由 9%/8% 下调; 9%/8% 自 2025-06-20 起, 郑商函〔2025〕460号); 手续费 3 元/手、平今 3 元/手: 长期基准(收费一览表+结算参数确认)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/4/b60b22ff38fc4ade848e06d1cffaed64.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/06/1750858509158684.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/hzqh/bzhy/qhhy/H077002022002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: 全部合约 8%/7%
- 备注: 2023-11-08 曾对 2312~2409 合约临时 10 元/手. 2026-09-29 结算起国庆临时 9%/8%(860号). 合约文本 7% 仅为下限.

### PF 短纤 (CZCE) — verified
- 生效/依据: 手续费 2 元/手、平今免收: 2025-03-14 夜盘起(郑商函〔2025〕204号); 保证金 7%/涨跌停 6%: 2025-02-05 恢复交易后结算起(郑商函〔2025〕71号第二条); 2026-03-10 起 2604~2609 合约临时升至 13%/11%(郑商函〔2026〕244号), 已随合约到期/恢复
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/01/1738062898261399.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/3/4a462c266e2f4e19a0759ad9d5911921.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/dxqh/bzhy/qhhy/H077002025002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: PF611+: 7%/6%; PF610: 10%/6%
- 备注: 2025-03-14 前手续费 3 元/手、平今 3 元/手(结算参数回溯); 2025-02-05 前 8%/7%. PF610(近月) 10%. 2026-09-29 结算起国庆临时 10%/9%(860号). 合约文本 5% 仅为下限.

### PK 花生 (CZCE) — verified
- 生效/依据: 手续费 2 元/手、平今 2 元/手: 2026-06-24 起(郑商所公告〔2026〕91号, 由 4 元/手下调); 保证金 7%/涨跌停 6%: 2025-10-09 恢复交易后首个非单边市交易日结算起(郑商函〔2025〕735号第二条)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/9/52ba804f458649eab0e8d23fcb193842.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/hsqh/bzhy/qhhy/H077002026002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: PK611+: 7%/6%; PK610: 10%/6%
- 备注: 2026-06-24 前 4 元/手(平今 4 元); 2025-10-09 前 8%/7%. PK610(近月) 10%. 2026-09-29 结算起国庆临时 9%/8%(860号). 合约文本 5% 仅为下限.

### SH 烧碱 (CZCE) — verified
- 生效/依据: 手续费 万分之1: 2023-09-15 上市起(郑商函〔2023〕692号); 平今免收: 2024-05-29 夜盘起(郑商函〔2024〕323号); 保证金 8%/涨跌停 7%: 品种级长期基准(结算参数回溯: 2024-12-13 起即为 8%/7%, 各假期临时上调后均恢复; 2026-03-09 起 2604~2607 合约临时上调, 郑商函〔2026〕239号, 已随合约到期恢复)
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464652925099.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2024/05/1715232667290475.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/3/c28d417b1a7543b2aa131bb516d44329.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/sjqhqq/bzhy/qhhy/H077002028002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: SH611+: 8%/7%; SH610: 10%/7%
- 备注: 交易单位 30 吨/手(干吨). 2025 年曾多次对 2509 等合约临时上调手续费至 万分之2. SH610(近月) 10%. 2026-09-29 结算起国庆临时 10%/9%(860号). 合约文本 5% 仅为下限.

### PX 对二甲苯 (CZCE) — verified
- 生效/依据: 手续费 万分之1: 2023-09-15 上市起(郑商函〔2023〕693号); 平今免收: 2024-05-29 夜盘起(郑商函〔2024〕323号); 保证金 7%/涨跌停 6%: 2025-10-09 恢复交易后首个非单边市交易日结算起(郑商函〔2025〕735号第二条); 2026-03-10 起 2604~2609 临时升至 13%/11%(244号), 已恢复
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2023/09/1689464653277405.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2024/05/1715232667290475.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/9/52ba804f458649eab0e8d23fcb193842.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/dejbqhqq/bzhy/qhhy/H077002027002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: PX611+: 7%/6%; PX610: 15%/6%
- 备注: 2025-10-09 前 8%/7%. PX610(近月) 15%. 2026-09-21 结算起 PX2610 涨跌停 9%、PX2611 保证金 9%/涨跌停 8%; 2026-09-29 结算起全品种临时 10%/9%(860号). 合约文本 5% 仅为下限.

### PR 瓶片 (CZCE) — verified
- 生效/依据: 手续费 万分之0.5、平今免收: 2025-03-14 夜盘起(郑商函〔2025〕204号; 上市时 万分之1/平今万分之1, 郑商函〔2024〕558号); 保证金 7%/涨跌停 6%: 2025-02-05 恢复交易后结算起(郑商函〔2025〕71号第二条); 2026-03-10 起 2604~2609 临时升至 13%/11%(244号), 已恢复
- 一手来源: http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/03/1738067227057437.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2024/08/1715239665634128.htm ; http://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2025/01/1738062898261399.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureDataClearParams.txt ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260918/FutureTradeParam.txt ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/sspz/ppqh/bzhy/qhhy/H077002029002001index_1.htm
- 次级印证: https://www.9qihuo.com/qihuoshouxufei
- 分档: PR611+: 7%/6%; PR610: 10%/6%
- 备注: 交易单位 15 吨/手. 2025-03-14 前手续费 万分之1、平今 万分之1(结算参数回溯); 2025-02-05 前 8%/7%. PR610(近月) 10%. 2026-09-29 结算起国庆临时 10%/9%(860号). 合约文本 5% 仅为下限.

## 5. 未能核实项

无(132 项全部由交易所一手来源两处互证: 结算/交易参数文件 + 公告或收费一览表/合约文本; 次级印证 9qihuo 2026-09-18 22:55 更新表全部一致)。以下为"原始公告未定位、但现行值已由交易所参数文件+收费一览表确认"的长期基准: RM 1.5 元/手、AP 5 元/手、CJ 3 元/手、SF/SM 平今免收、OI/RM/UR/SH 的品种级保证金基准(逐日结算参数回溯至 2024-12-13 均为现行值或假期临时值)。

## 6. 方法与回测使用注意

(1) 上期所: `Settlement{YYYYMMDD}.dat`(保证金/手续费/平今折扣率) + `ContractDailyTradeArgument{YYYYMMDD}.dat`(涨跌停) 可直接 curl; 公告经站内搜索 API `POST /api/search/` 定位(公告列表页缺 2023-11~2025-10 区段). 郑商所: `FutureDataClearParams.txt`/`FutureTradeParam.txt` 可直接 curl; 公告正文需 CDP(app.czce.com.cn/cmsapp/notice 支持标题+日期筛选). 
(2) 上期所有色(ZN/PB/AO)按合约月份分 2 档(2610~2702 主力档 11%/9%, 2703+ 9%/7%); FU 近月 2610/2611 为 18%/16%; HC/SS/SP 交割月前一月 10%. 表中取主力档. 
(3) 手续费按月份分档: FU 1/5/9 月 万分之0.5、其他 0.1; HC 1/5/10 月 万分之1、其他 0.2(表中取主力月). 
(4) 历史分段(回测需要): SHFE 2026-07-02 前 ZN/PB/AO 12%/10%, SS 8%/6%; 2026-07-10 前 BU/BR 14%/12%, SP 9%/7% 且 SP 手续费 万分之0.5; 2026-06-25 前 FU 19%/17%(06-02 起)/22%/20%(03-10 起) 且 03-11~06-24 手续费 万分之1、平今 万分之3; 2026-05-19 前 HC 与 RB 同步(见主表 RB). CZCE 2026-06-05 前 FG 6 元/手、10%/9%; 2026-06-24 前 SF/SM 3 元/手、8%/7%, PK 4 元/手; 2026-06-23 前 RM 平今 1.5 元; 2026-06-08 前 AP 平今 20 元; 2026-05-06 前 AP 10%/9%、CJ 9%/8%; 2025-03-14 前 PF 3 元/平今 3 元、PR 万分之1/平今万分之1; 2025-10-09 前 PK/PX 8%/7%; 2025-02-05 前 PF/PR 8%/7%、CJ 12%/10%、FG 12%/10%; 2025-05-20 前(自 04-02) OI 9%/8%、RM 10%/8%; 2025-06-20 前 CJ 10%/9%. 郑商所 2024-12-13~2026-09-18 逐日结算参数已回溯核对(FutureDataClearParams.txt), 上期所 2026-06-01~09-18 逐日已回溯. 
(5) 郑商所 2026-09-29 结算起国庆临时上调(郑商函〔2026〕860号), 10-08 后恢复; 上期所国庆调整公告尚未发布(截至 09-18). 
(6) 所有手续费为交易所投机标准, 期货公司会加收; 郑商所套保开仓手续费 2026 年免收(郑商函 2025-12-22 通知).

建议 meta: `{verified: true, verified_date: 2026-09-18, slippage_ticks_per_side: 1}`(与主表合并后统一).
