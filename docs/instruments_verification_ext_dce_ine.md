# 交易所参数复核终表 — 扩展品种(DCE 10 + INE 3) (instruments_verified_ext_dce_ine)

- 范围: `docs/instruments_verification.md` 未覆盖的 13 个品种(DCE: JM PP L A B CS EG EB PG LH; INE: NR LU BC)。SHFE/CZCE 扩展品种由另一任务核验, 不在本表。
- 参数快照: DCE 2026-09-18 结算参数 / 2026-09-21 日交易参数(自 09-18 结算起); INE 2026-09-18 业务参数汇总(结算参数 + 交易参数) / 2026-09-07 收费一览表; 生成日 2026-09-18
- 复核: 13 品种 × 6 字段 = 78 项; verified 78, corrected 0, unverified 0; 与当前 YAML(数据反推占位值) 差异 56 处; 乘数/跳价 13/13 与占位一致
- 口径同主表: margin_rate = 交易所一般持仓(投机)最低保证金(一般月份/主力档); limit_pct = 现行涨跌停(一般月份/主力档); fee 为交易所投机非日内开仓费(元/手 或 万分比, 二选一); fee_close_today 为平今费。

## 1. 最终参数表

| symbol | exchange | name | multiplier | tick | margin_rate | fee_per_lot | fee_notional_bp | limit_pct | fee_close_today | effective | source | status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|
| JM | DCE | 焦煤 | 60 | 0.5 | 0.12 | 0 | 1.0 | 0.08 | 1.0 bp | 保证金 12%: 2024-11-25 结算起(大商所发〔2024〕514号, 由 20%/15% 下调); 涨跌停 8% 与手续费 万分之1 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154号、2026-09-18〔2026〕347号 三份假期通知的"现行/节前标准"表均为 8%/12%); 2026-09-18 结算参数 / 2026-09-21 日交易参数确认现行 | http://www.dce.com.cn/dce/content/2024/ywggytz/8624615.html | verified |
| PP | DCE | 聚丙烯 | 5 | 1 | 0.07 | 1.0 | 0 | 0.06 | 1.0 元/手 | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154号、2026-09-18〔2026〕347号 表均为 6%/7%; 手续费由 2024-01-22〔2024〕34号 套保 0.5 元=投机一半反推); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| L | DCE | 塑料(线型低密度聚乙烯) | 5 | 1 | 0.07 | 1.0 | 0 | 0.06 | 1.0 元/手 | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.5 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| A | DCE | 豆一(黄大豆1号) | 10 | 1 | 0.07 | 2.0 | 0 | 0.06 | 2.0 元/手 | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| B | DCE | 豆二(黄大豆2号) | 10 | 1 | 0.07 | 1.0 | 0 | 0.06 | 1.0 元/手 | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.5 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| CS | DCE | 淀粉(玉米淀粉) | 10 | 1 | 0.06 | 1.5 | 0 | 0.05 | 1.5 元/手 | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 0.75 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| EG | DCE | 乙二醇 | 10 | 1 | 0.07 | 3.0 | 0 | 0.06 | 3.0 元/手 | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔2024〕34号 套保 1.5 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html | verified |
| EB | DCE | 苯乙烯 | 5 | 1 | 0.07 | 1.0 | 0 | 0.06 | 1.0 元/手 | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元); 7%/6% 为长期基准(三份假期通知表"其他合约" 6%/7%); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html | verified |
| PG | DCE | 液化石油气 | 20 | 1 | 0.11 | 6.0 | 0 | 0.09 | 6.0 元/手 | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%/6% 上调); 一般月份(PG2703 及以后) 仍为 7%/6%; 手续费 6 元/手 为长期基准(2024-01-22〔2024〕34号 套保 3 元); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html | verified |
| LH | DCE | 生猪 | 16 | 5 | 0.08 | 0 | 1.0 | 0.06 | 2.0 bp | 手续费 非日内 万分之1 / 日内 万分之2: 2023-05-24 交易起(大商所发〔2023〕201号, 由 万分之2/4 下调); 8%/6% 为长期基准(三份假期通知表 6%/8%); 2026-09-18 结算参数确认现行 | http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html | verified |
| NR | INE | 20号胶 | 10 | 5 | 0.09 | 0 | 0.2 | 0.07 | 0 bp | 涨跌停 7%/套保 8%/一般 9%: 2026-07-10 收盘结算起(上能发〔2026〕81号, NR2607~NR2703; 后续 nr2704~2709 同档); 手续费 万分之0.2、平今免收(折扣率 0): 2026-09-07 收费一览表 + 2026-09-18 结算参数 | https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html | verified |
| LU | INE | 低硫燃料油 | 10 | 1 | 0.16 | 0 | 0.1 | 0.14 | 0.1 bp | 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608~LU2706 及后续新合约); 手续费 万分之0.1、平今 万分之0.1: 2026-06-25 交易起(上能发〔2026〕79号); 2026-09-18 结算参数确认现行 | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html | verified |
| BC | INE | 国际铜 | 5 | 10 | 0.11 | 0 | 0.1 | 0.09 | 0 bp | 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2607~BC2702); bc2703 及以后 9%/8%/7%; 手续费 万分之0.1、平今免收(折扣率 0): 2026-09-07 收费一览表 + 2026-09-18 结算参数 | https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html | verified |

YAML 片段(可直接替换 symbols 段中对应行; fee_close_today 单位: 元/手品种同 fee_per_lot, 比例品种为 bp; asset_class 沿用现有 YAML):

```yaml
  JM: {exchange: DCE,   name: 焦煤,      multiplier: 60,    tick: 0.5,   margin_rate: 0.12,  fee_per_lot: 0,     fee_notional_bp: 1.0,   limit_pct: 0.08,  fee_close_today: 1.0,   asset_class: ferrous,  effective: "2024-11-25", source: "http://www.dce.com.cn/dce/content/2024/ywggytz/8624615.html", verified: true}
  PP: {exchange: DCE,   name: 聚丙烯,     multiplier: 5,     tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 1.0,   asset_class: chem,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  L:  {exchange: DCE,   name: 塑料,      multiplier: 5,     tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 1.0,   asset_class: chem,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  A:  {exchange: DCE,   name: 豆一,      multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 2.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 2.0,   asset_class: agri,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  B:  {exchange: DCE,   name: 豆二,      multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 1.0,   asset_class: agri,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  CS: {exchange: DCE,   name: 淀粉,      multiplier: 10,    tick: 1,     margin_rate: 0.06,  fee_per_lot: 1.5,   fee_notional_bp: 0,     limit_pct: 0.05,  fee_close_today: 1.5,   asset_class: agri,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  EG: {exchange: DCE,   name: 乙二醇,     multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 3.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 3.0,   asset_class: chem,     effective: "2026-09-18", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html", verified: true}
  EB: {exchange: DCE,   name: 苯乙烯,     multiplier: 5,     tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.0,   fee_notional_bp: 0,     limit_pct: 0.06,  fee_close_today: 1.0,   asset_class: chem,     effective: "2026-07-10", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html", verified: true}
  PG: {exchange: DCE,   name: 液化石油气,   multiplier: 20,    tick: 1,     margin_rate: 0.11,  fee_per_lot: 6.0,   fee_notional_bp: 0,     limit_pct: 0.09,  fee_close_today: 6.0,   asset_class: energy,   effective: "2026-03-24", source: "http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html", verified: true}
  LH: {exchange: DCE,   name: 生猪,      multiplier: 16,    tick: 5,     margin_rate: 0.08,  fee_per_lot: 0,     fee_notional_bp: 1.0,   limit_pct: 0.06,  fee_close_today: 2.0,   asset_class: agri,     effective: "2023-05-24", source: "http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html", verified: true}
  NR: {exchange: INE,   name: 20号胶,    multiplier: 10,    tick: 5,     margin_rate: 0.09,  fee_per_lot: 0,     fee_notional_bp: 0.2,   limit_pct: 0.07,  fee_close_today: 0,     asset_class: chem,     effective: "2026-07-10", source: "https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html", verified: true}
  LU: {exchange: INE,   name: 低硫燃料油,   multiplier: 10,    tick: 1,     margin_rate: 0.16,  fee_per_lot: 0,     fee_notional_bp: 0.1,   limit_pct: 0.14,  fee_close_today: 0.1,   asset_class: energy,   effective: "2026-06-25", source: "https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html", verified: true}
  BC: {exchange: INE,   name: 国际铜,     multiplier: 5,     tick: 10,    margin_rate: 0.11,  fee_per_lot: 0,     fee_notional_bp: 0.1,   limit_pct: 0.09,  fee_close_today: 0,     asset_class: metal,    effective: "2026-07-02", source: "https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html", verified: true}
```

## 2. 与当前 YAML 占位值的差异清单 (56 处)

当前 YAML 中这 13 个品种全部标 `verified: false`, 保证金 0.10 / 万分之1 / 涨跌停 0.07 / 平今 1.0 为占位; 乘数与跳价为数据反推值。

| # | symbol | field | old | new | 依据/生效 | source |
|---:|---|---|---:|---:|---|---|
| 1 | JM | margin_rate | 0.1 | 0.12 | 保证金 12%: 2024-11-25 结算起(大商所发〔2024〕514号, 由 20%/15% 下调); 涨跌停 8… | http://www.dce.com.cn/dce/content/2024/ywggytz/8624615.html |
| 2 | JM | limit_pct | 0.07 | 0.08 | 保证金 12%: 2024-11-25 结算起(大商所发〔2024〕514号, 由 20%/15% 下调); 涨跌停 8… | http://www.dce.com.cn/dce/content/2024/ywggytz/8624615.html |
| 3 | PP | margin_rate | 0.1 | 0.07 | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 4 | PP | fee_per_lot | 0 | 1.0 | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 5 | PP | fee_notional_bp | 1.0 | 0 | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 6 | PP | limit_pct | 0.07 | 0.06 | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 7 | PP | fee_close_today | 1.0 (bp) | 1.0 (cny_per_lot) | 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 8 | L | margin_rate | 0.1 | 0.07 | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 9 | L | fee_per_lot | 0 | 1.0 | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 10 | L | fee_notional_bp | 1.0 | 0 | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 11 | L | limit_pct | 0.07 | 0.06 | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 12 | L | fee_close_today | 1.0 (bp) | 1.0 (cny_per_lot) | 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 13 | A | margin_rate | 0.1 | 0.07 | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 14 | A | fee_per_lot | 0 | 2.0 | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 15 | A | fee_notional_bp | 1.0 | 0 | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 16 | A | limit_pct | 0.07 | 0.06 | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 17 | A | fee_close_today | 1.0 (bp) | 2.0 (cny_per_lot) | 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 18 | B | margin_rate | 0.1 | 0.07 | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 19 | B | fee_per_lot | 0 | 1.0 | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 20 | B | fee_notional_bp | 1.0 | 0 | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 21 | B | limit_pct | 0.07 | 0.06 | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 22 | B | fee_close_today | 1.0 (bp) | 1.0 (cny_per_lot) | 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 23 | CS | margin_rate | 0.1 | 0.06 | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 24 | CS | fee_per_lot | 0 | 1.5 | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 25 | CS | fee_notional_bp | 1.0 | 0 | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 26 | CS | limit_pct | 0.07 | 0.05 | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 27 | CS | fee_close_today | 1.0 (bp) | 1.5 (cny_per_lot) | 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 … | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 28 | EG | margin_rate | 0.1 | 0.07 | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔202… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 29 | EG | fee_per_lot | 0 | 3.0 | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔202… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 30 | EG | fee_notional_bp | 1.0 | 0 | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔202… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 31 | EG | limit_pct | 0.07 | 0.06 | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔202… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 32 | EG | fee_close_today | 1.0 (bp) | 3.0 (cny_per_lot) | 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔202… | http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html |
| 33 | EB | margin_rate | 0.1 | 0.07 | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元)… | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html |
| 34 | EB | fee_per_lot | 0 | 1.0 | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元)… | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html |
| 35 | EB | fee_notional_bp | 1.0 | 0 | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元)… | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html |
| 36 | EB | limit_pct | 0.07 | 0.06 | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元)… | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html |
| 37 | EB | fee_close_today | 1.0 (bp) | 1.0 (cny_per_lot) | 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元)… | http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html |
| 38 | PG | margin_rate | 0.1 | 0.11 | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%… | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html |
| 39 | PG | fee_per_lot | 0 | 6.0 | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%… | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html |
| 40 | PG | fee_notional_bp | 1.0 | 0 | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%… | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html |
| 41 | PG | limit_pct | 0.07 | 0.09 | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%… | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html |
| 42 | PG | fee_close_today | 1.0 (bp) | 6.0 (cny_per_lot) | 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%… | http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html |
| 43 | LH | margin_rate | 0.1 | 0.08 | 手续费 非日内 万分之1 / 日内 万分之2: 2023-05-24 交易起(大商所发〔2023〕201号, 由 万分之… | http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html |
| 44 | LH | limit_pct | 0.07 | 0.06 | 手续费 非日内 万分之1 / 日内 万分之2: 2023-05-24 交易起(大商所发〔2023〕201号, 由 万分之… | http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html |
| 45 | LH | fee_close_today | 1.0 (bp) | 2.0 (bp) | 手续费 非日内 万分之1 / 日内 万分之2: 2023-05-24 交易起(大商所发〔2023〕201号, 由 万分之… | http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html |
| 46 | NR | margin_rate | 0.1 | 0.09 | 涨跌停 7%/套保 8%/一般 9%: 2026-07-10 收盘结算起(上能发〔2026〕81号, NR2607~NR… | https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html |
| 47 | NR | fee_notional_bp | 1.0 | 0.2 | 涨跌停 7%/套保 8%/一般 9%: 2026-07-10 收盘结算起(上能发〔2026〕81号, NR2607~NR… | https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html |
| 48 | NR | fee_close_today | 1.0 (bp) | 0 (bp) | 涨跌停 7%/套保 8%/一般 9%: 2026-07-10 收盘结算起(上能发〔2026〕81号, NR2607~NR… | https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html |
| 49 | LU | margin_rate | 0.1 | 0.16 | 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608… | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 50 | LU | fee_notional_bp | 1.0 | 0.1 | 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608… | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 51 | LU | limit_pct | 0.07 | 0.14 | 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608… | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 52 | LU | fee_close_today | 1.0 (bp) | 0.1 (bp) | 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608… | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 53 | BC | margin_rate | 0.1 | 0.11 | 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2… | https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html |
| 54 | BC | fee_notional_bp | 1.0 | 0.1 | 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2… | https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html |
| 55 | BC | limit_pct | 0.07 | 0.09 | 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2… | https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html |
| 56 | BC | fee_close_today | 1.0 (bp) | 0 (bp) | 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2… | https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html |

差异归因: 乘数/跳价 0 处(占位值全部正确); 保证金 13 处(占位 10% 无一命中); 涨跌停 12 处(仅 NR 的 7% 与占位相同; JM 为 8%); 手续费 19 行/11 品种(仅 JM、LH 恰为 万分之1; 其余 8 个 DCE 品种是 元/手 绝对值品种, INE 三品种为 万分之0.1~0.2); 平今 12 处(数值或单位, 仅 JM 相同)。

## 3. 平今手续费备注 (日频调仓可能触发平今)

| 情形 | 品种 | 说明 |
|---|---|---|
| 平今 > 开仓 | **LH** 生猪 (日内 2bp vs 非日内 1bp) | 结算参数 shortOpenFee/shortOffsetFee 均为 万分之2: 当日开仓当日平掉时开仓腿也按 2bp 计, 日内往返实收 4bp(同 J 焦炭结构) |
| 平今免收 (0) | **NR**, **BC** | 结算参数表 平今折扣率 0%; 日内往返只付一次开仓费 |
| 平今 = 开仓 | JM(1bp), PP/L/B/EB(1 元), CS(1.5 元), A(2 元), EG(3 元), PG(6 元), LU(0.1bp, 折扣率 100%) | LU 在 2026-03-10~06-24 曾 0.3bp/3bp/0.3bp 三次临时上调(见 LU 备注) |

## 4. 逐品种来源与备注

### JM 焦煤 (DCE) — verified
- 生效/依据: 保证金 12%: 2024-11-25 结算起(大商所发〔2024〕514号, 由 20%/15% 下调); 涨跌停 8% 与手续费 万分之1 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154号、2026-09-18〔2026〕347号 三份假期通知的"现行/节前标准"表均为 8%/12%); 2026-09-18 结算参数 / 2026-09-21 日交易参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2024/ywggytz/8624615.html ; http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/2000159.html ; http://www.dce.com.cn/dce/content/2025/ywggytz/18620456.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124 ; https://www.ccbfutures.com/main/a/20241122/70246.shtml
- 乘数/跳价: 合约文本 60 吨/手, 0.5 元/吨 — 与 YAML 占位一致
- 备注: 主力 jm2701 12%/8%。jm2610/jm2611/jm2612 自 2026-09-18 结算起为 13%/11%: 三合约 9/18 收于跌停(结算价 1617/1582.5/1534 → 收盘 1488/1456/1411.5, 恰为 -8%), 触发《风险管理办法》涨跌停板后自动扩板加保证金, 无单独通知(9/17 前所有合约均 12%/8%); 属临时状态。手续费 投机开/平/平今 均 万分之1(2025-08-18 起 JM2601 日内曾临时 万分之2, 已到期)。套保 万分之0.5。2024-11-25 前保证金 20%。合约文本 4%/5% 仅为下限。

### PP 聚丙烯 (DCE) — verified
- 生效/依据: 7%/6% 与 1 元/手 为长期基准(2025-09-24〔2025〕348号、2026-04-27〔2026〕154号、2026-09-18〔2026〕347号 表均为 6%/7%; 手续费由 2024-01-22〔2024〕34号 套保 0.5 元=投机一半反推); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2137.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 5 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 主力 pp2701。平今=开仓 1 元/手。2026-03-10~05 月间 PP2604~2609 曾临时 11%/9%(〔2026〕73号), 已到期。〔2026〕347号: 2026-09-29 结算起(国庆前)全品种升至 8%/10%, 10-08 后恢复。

### L 塑料(线型低密度聚乙烯) (DCE) — verified
- 生效/依据: 同 PP: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.5 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2175.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 5 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 主力 l2701。平今=开仓 1 元/手。交易品种全称"线型低密度聚乙烯", 代码 L。2026-03-10~05 月 L2604~2609 曾临时 11%/9%(〔2026〕73号), 已到期。国庆前 2026-09-29 结算起 8%/10%。

### A 豆一(黄大豆1号) (DCE) — verified
- 生效/依据: 7%/6% 与 2 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 1 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/290.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 主力 a2611。平今=开仓 2 元/手。合约月份 1/3/5/7/9/11。国庆前 2026-09-29 结算起 8%/10%。

### B 豆二(黄大豆2号) (DCE) — verified
- 生效/依据: 7%/6% 与 1 元/手 为长期基准(三份假期通知表 6%/7%; 2024-01-22〔2024〕34号 套保 0.5 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2092.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 主力 b2611。平今=开仓 1 元/手。b2610 已进入交割月前一月档 10%。国庆前 2026-09-29 结算起 8%/10%。

### CS 淀粉(玉米淀粉) (DCE) — verified
- 生效/依据: 6%/5% 与 1.5 元/手 为长期基准(三份假期通知表 5%/6%; 2024-01-22〔2024〕34号 套保 0.75 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/306.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 主力 cs2611。平今=开仓 1.5 元/手。合约月份 1/3/5/7/9/11。国庆期间维持不变(〔2026〕347号)。

### EG 乙二醇 (DCE) — verified
- 生效/依据: 一般月份 7%/6% 与 3 元/手 为长期基准(三份假期通知表"其他合约" 6%/7%; 2024-01-22〔2024〕34号 套保 1.5 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2123.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 取一般月份档(eg2612 及以后 7%/6%)。当前主力 eg2610 已进入交割前月档 10%/6%; 〔2026〕347号: 2026-09-23 结算起 EG2610 8%/10%、EG2611 8%/9%, 09-29 结算起全品种 9%/11%, 10-08 后恢复。平今=开仓 3 元/手。2026-03~05 月 EG2604~2609 曾临时 11%/13%(〔2026〕73号), 已到期。

### EB 苯乙烯 (DCE) — verified
- 生效/依据: 手续费 1 元/手: 2026-07-10 交易起(大商所发〔2026〕264号, 由 3 元下调, 平今同为 1 元); 7%/6% 为长期基准(三份假期通知表"其他合约" 6%/7%); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18631364.html ; http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/2329.html
- 次级印证: https://www.ghlsqh.com.cn/news/show-28473.html ; https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 5 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 2026-07-10 前手续费 3 元/手(平今 3 元), 回测需分段。当前主力 eb2610 已进入交割前月档 10%; 一般月份 eb2611+ 7%/6%。2026-03~05 月 EB2604~2609 曾临时 11%/13%(〔2026〕73号), 已到期。国庆前 2026-09-29 结算起 9%/11%。

### PG 液化石油气 (DCE) — verified
- 生效/依据: 主力档 11%/9%: 2026-03-24 结算起(大商所发〔2026〕87号, PG2610~PG2702 由 7%/6% 上调); 一般月份(PG2703 及以后) 仍为 7%/6%; 手续费 6 元/手 为长期基准(2024-01-22〔2024〕34号 套保 3 元); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18628151.html ; http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2090.html
- 次级印证: https://finance.sina.com.cn/wm/2026-03-23/doc-inhrysxs2330096.shtml ; https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 20 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 与 CU/BC 同口径取主力档: 主力 pg2610 及 2611/2612/2701/2702 为 11%/9%(〔2026〕87号, 〔2026〕347号表亦单列此档); pg2703 及以后 7%/6%, 2702 到期后若无新通知主力将回落到 7%/6%, 回测常数建议按主力档但需知其为 2026-03-24 起的阶段性水平。平今=开仓 6 元/手(〔2026〕88号 PG2604~2606 日内 12 元 已到期)。国庆前 2026-09-29 结算起其他合约 9%/11%。

### LH 生猪 (DCE) — verified
- 生效/依据: 手续费 非日内 万分之1 / 日内 万分之2: 2023-05-24 交易起(大商所发〔2023〕201号, 由 万分之2/4 下调); 8%/6% 为长期基准(三份假期通知表 6%/8%); 2026-09-18 结算参数确认现行
- 一手来源: http://www.dce.com.cn/dce/content/2023/ywggytz/8544536.html ; http://www.dce.com.cn/dce/content/2026/ywggytz/19622733.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/content/2024/ywggytz/8591482.html ; http://www.dce.com.cn/dce/channel/list/2279.html
- 次级印证: https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 16 吨/手, 5 元/吨 — 与 YAML 占位一致
- 备注: 主力 lh2611。日内交易(当日开当日平)开仓腿与平今腿均按 万分之2 计(结算参数 shortOpenFee/shortOffsetFee=2), 非日内开/平 万分之1; 同 J 焦炭的结构, 日内往返实收 4bp 而非 1+2。无夜盘。合约月份 1/3/5/7/9/11。lh2609 交割月 20%。国庆前 2026-09-29 结算起 8%/10%。

### NR 20号胶 (INE) — verified
- 生效/依据: 涨跌停 7%/套保 8%/一般 9%: 2026-07-10 收盘结算起(上能发〔2026〕81号, NR2607~NR2703; 后续 nr2704~2709 同档); 手续费 万分之0.2、平今免收(折扣率 0): 2026-09-07 收费一览表 + 2026-09-18 结算参数
- 一手来源: https://www.ine.cn/publicnotice/notice/202607/t20260708_832502.html ; https://www.ine.cn/reports/businessdata/prmsummary/ ; https://www.ine.cn/reports/businessdata/feeandcharges/202609/W020260907547252881829.xlsx ; https://www.ine.cn/products/futures/energyandchemical/nr_f/
- 次级印证: https://www.guoyuanqh.com/notice/details_616_30889.html ; https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 5 元/吨 — 与 YAML 占位一致
- 备注: 主力 nr2611 9%/7%。nr2610 10%(交割前月档)。2026-03-12〔2026〕33号 NR2703 上市时曾为 11%/9%, 7/10 起统一下调至 9%/7%。平今免收的起始公告未在 ine.cn 定位, 现行由结算参数表(平今折扣率 0%)与收费一览表确认。套保手续费 万分之0.1(2026 年减半)。

### LU 低硫燃料油 (INE) — verified
- 生效/依据: 涨跌停 14%/套保 15%/一般 16%: 2026-06-25 收盘结算起(上能发〔2026〕78号, LU2608~LU2706 及后续新合约); 手续费 万分之0.1、平今 万分之0.1: 2026-06-25 交易起(上能发〔2026〕79号); 2026-09-18 结算参数确认现行
- 一手来源: https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html ; https://www.ine.cn/publicnotice/notice/202606/t20260623_832254.html ; https://www.ine.cn/publicnotice/notice/202609/t20260911_833372.html ; https://www.ine.cn/reports/businessdata/prmsummary/ ; https://www.ine.cn/reports/businessdata/feeandcharges/202609/W020260907547252881829.xlsx ; https://www.ine.cn/products/futures/energyandchemical/lu_f/
- 次级印证: https://finance.sina.com.cn/wm/2026-06-23/doc-iniemfsm6335197.shtml ; https://news.qq.com/rain/a/20260911A0EH5F00 ; https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 10 吨/手, 1 元/吨 — 与 YAML 占位一致
- 备注: 与 SC 同口径取〔2026〕78号 一般档 16%/14%; 但 上能发〔2026〕103号 自 2026-09-14 收盘结算起 LU2610、LU2611(含当前主力 lu2611) 升至 18%/17%/16%, lu2612 及以后仍 16%/14%。平今不免收(折扣率 100%)。2026 年手续费多次临时调整: 03-10 起平今 万分之0.3(〔2026〕24号), 03-11 起开仓 万分之1/平今 万分之3(〔2026〕29号), 05-19 起 万分之0.1/平今 万分之0.3(〔2026〕61号), 06-25 起 万分之0.1/平今 万分之0.1(〔2026〕79号); 回测该区间需分段。

### BC 国际铜 (INE) — verified
- 生效/依据: 主力档 涨跌停 9%/套保 10%/一般 11%: 2026-07-02 收盘结算起(上能发〔2026〕80号, BC2607~BC2702); bc2703 及以后 9%/8%/7%; 手续费 万分之0.1、平今免收(折扣率 0): 2026-09-07 收费一览表 + 2026-09-18 结算参数
- 一手来源: https://www.ine.cn/publicnotice/notice/202606/t20260630_832355.html ; https://www.ine.cn/reports/businessdata/prmsummary/ ; https://www.ine.cn/reports/businessdata/feeandcharges/202609/W020260907547252881829.xlsx ; https://www.ine.cn/products/futures/metal/nonferrousmetal/bc_f/
- 次级印证: https://www.ghlsqh.com.cn/news/show-28415.html ; https://www.9qihuo.com/qihuoshouxufei ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 乘数/跳价: 合约文本 5 吨/手, 10 元/吨 — 与 YAML 占位一致
- 备注: 与 SHFE CU 同口径取主力档(主力 bc2610, 2610~2702 均 11%/9%); bc2703+ 为 9%/7%。2026-01-28〔2026〕5号 起 11%/9%, 02-09〔2026〕10号 升至 12%/10%, 07-02〔2026〕80号 回到 11%/9%(仅 2607~2702)。平今免收的起始公告未定位, 现行由结算参数表(折扣率 0%)确认。合约文本 涨跌停 ±3%/保证金 5% 仅为下限。

## 5. 未能核实项

无(78/78 verified)。两处仅有"现行状态"而未定位到起始公告, 不影响取值: NR、BC 平今免收 — 由 INE 结算参数表(平今折扣率 0%)与收费一览表确认现行, 起始通知未在 ine.cn 公告列表(2026-01 至今)中找到; 另 DCE A/B/CS/L/PP/EG/PG 的元/手手续费为多年基准, 起始公告未逐一追溯, 以 2024-01-22 大商所发〔2024〕34号(套保=投机一半的全品种表)与 2026-09-18 结算参数互证。

## 6. 数据获取方法(可复现)

- DCE: 在 `http://www.dce.com.cn/frontend/dcereport/` 任一页面上下文内 `fetch` 后端: `POST /dcereport/publicweb/tradepara/dayTradPara` body `{varietyId:'all',tradeDate:'20260921',tradeType:'1',lang:'zh'}`(specBuyRate/riseLimitRate 逐合约) 与 `POST /dcereport/publicweb/tradepara/futAndOptSettle` body `{varietyId:'all',tradeDate:'20260918',tradeType:'1',lang:'zh'}`(openFee/offsetFee/shortOpenFee/shortOffsetFee, style 绝对值=元/手 比例值=万分之X); curl 直连 412。合约文本在品种页 `/dce/channel/list/<id>.html`(JM 2000159, PP 2137, L 2175, A 290, B 2092, CS 306, EG 2123, EB 2329, PG 2090, LH 2279)。公告全文检索 `/dce/search.thtml?keyword=…`(公告列表页 239.html 有 CDN 缓存, 9/18 当日公告只能靠检索找到)。
- INE: `https://www.ine.cn/reports/businessdata/prmsummary/` 点 `结算参数`/`交易参数` tab(SPAN.tabs_item), 表列为 合约|结算价|一般手续费率(‰)|套保手续费率|一般手续费额|套保手续费额|交割手续费|一般买/卖保证金率|套保买/卖|平今折扣率(%); 0.010‰ = 万分之0.1。收费一览表 xlsx 需带 CDP tab 的 `TrsAccessMonitor` cookie 下载。全站 WAF, 公告正文只能走真实 Chrome。
- 次级: 九期网 `https://www.9qihuo.com/qihuoshouxufei`(curl 可取 HTML, 逐合约 保证金/涨跌停/开仓/平昨/平今/主力标记, 2026-09-18 22:55 更新); 中银国际期货 `https://www.bocifco.com/info.aspx?cid=3&id=124`(公司保证金 = 交易所 + 5~8pp, 停板与特殊合约列表可用于印证结构)。
