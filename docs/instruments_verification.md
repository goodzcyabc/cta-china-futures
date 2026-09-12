# 交易所参数复核终表 (instruments_verified)

- 参数快照: 2026-09-11 结算参数 / 2026-09-14 交易参数; 生成日 2026-09-11
- 复核: 23 品种 × 6 字段 = 138 项; verified 138, corrected 0, unverified 0; 与当前 YAML 差异 42 处

## 1. 最终参数表 (与 configs/instruments.yaml 同结构 + fee_close_today/status)

| sym | 交易所 | 名称 | multiplier | tick | margin_rate | fee_per_lot | fee_notional_bp | limit_pct | fee_close_today | status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| C | DCE | 玉米 | 10 | 1 | 0.07 | 1.2 | 0 | 0.06 | 1.2 元/手 | verified |
| M | DCE | 豆粕 | 10 | 1 | 0.07 | 1.5 | 0 | 0.06 | 1.5 元/手 | verified |
| Y | DCE | 豆油 | 10 | 1 | 0.07 | 2.5 | 0 | 0.06 | 2.5 元/手 | verified |
| P | DCE | 棕榈油 | 10 | 1 | 0.08 | 2.5 | 0 | 0.07 | 2.5 元/手 | verified |
| JD | DCE | 鸡蛋 | 10 | 1 | 0.07 | 0 | 1.5 | 0.06 | 1.5 bp | verified |
| CF | CZCE | 棉花 | 5 | 5 | 0.07 | 4.3 | 0 | 0.06 | 0 元/手 | verified |
| SR | CZCE | 白糖 | 10 | 1 | 0.06 | 2.0 | 0 | 0.05 | 0 元/手 | verified |
| V | DCE | PVC | 5 | 1 | 0.07 | 1.0 | 0 | 0.06 | 1.0 元/手 | verified |
| TA | CZCE | PTA | 5 | 2 | 0.07 | 3.0 | 0 | 0.06 | 0 元/手 | verified |
| MA | CZCE | 甲醇 | 10 | 1 | 0.07 | 0 | 1.0 | 0.06 | 1.0 bp | verified |
| SA | CZCE | 纯碱 | 20 | 1 | 0.08 | 0 | 1.0 | 0.07 | 1.0 bp | verified |
| RU | SHFE | 天然橡胶 | 10 | 5 | 0.09 | 3.0 | 0 | 0.07 | 0 元/手 | verified |
| SC | INE | 原油 | 1000 | 0.1 | 0.16 | 20.0 | 0 | 0.14 | 0 元/手 | verified |
| J | DCE | 焦炭 | 100 | 0.5 | 0.12 | 0 | 1.0 | 0.08 | 1.4 bp | verified |
| I | DCE | 铁矿石 | 100 | 0.5 | 0.08 | 0 | 1.0 | 0.06 | 1.0 bp | verified |
| RB | SHFE | 螺纹钢 | 10 | 1 | 0.07 | 0 | 1.0 | 0.05 | 1.0 bp | verified |
| CU | SHFE | 铜 | 5 | 10 | 0.11 | 0 | 0.5 | 0.09 | 1.0 bp | verified |
| AL | SHFE | 铝 | 5 | 5 | 0.11 | 3.0 | 0 | 0.09 | 3.0 元/手 | verified |
| NI | SHFE | 镍 | 1 | 10 | 0.12 | 3.0 | 0 | 0.1 | 3.0 元/手 | verified |
| SN | SHFE | 锡 | 1 | 10 | 0.14 | 3.0 | 0 | 0.12 | 3.0 元/手 | verified |
| AU | SHFE | 黄金 | 1000 | 0.02 | 0.16 | 20.0 | 0 | 0.14 | 0 元/手 | verified |
| AG | SHFE | 白银 | 15 | 1 | 0.22 | 0 | 0.5 | 0.2 | 0.5 bp | verified |
| TF | CFFEX | 5年期国债 | 10000 | 0.005 | 0.012 | 3.0 | 0 | 0.012 | 0 元/手 | verified |

YAML 片段(可直接替换 symbols 段; fee_close_today 单位: 元/手品种同 fee_per_lot, 比例品种为 bp):

```yaml
meta: {verified: true, verified_date: 2026-09-11, slippage_ticks_per_side: 1}
symbols:
  C:  {exchange: DCE,   name: 玉米,       multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.2,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 1.2}
  M:  {exchange: DCE,   name: 豆粕,       multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.5,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 1.5}
  Y:  {exchange: DCE,   name: 豆油,       multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 2.5,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 2.5}
  P:  {exchange: DCE,   name: 棕榈油,      multiplier: 10,    tick: 1,     margin_rate: 0.08,  fee_per_lot: 2.5,  fee_notional_bp: 0,   limit_pct: 0.07,  fee_close_today: 2.5}
  JD: {exchange: DCE,   name: 鸡蛋,       multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 0,    fee_notional_bp: 1.5, limit_pct: 0.06,  fee_close_today: 1.5}
  CF: {exchange: CZCE,  name: 棉花,       multiplier: 5,     tick: 5,     margin_rate: 0.07,  fee_per_lot: 4.3,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 0}
  SR: {exchange: CZCE,  name: 白糖,       multiplier: 10,    tick: 1,     margin_rate: 0.06,  fee_per_lot: 2.0,  fee_notional_bp: 0,   limit_pct: 0.05,  fee_close_today: 0}
  V:  {exchange: DCE,   name: PVC,      multiplier: 5,     tick: 1,     margin_rate: 0.07,  fee_per_lot: 1.0,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 1.0}
  TA: {exchange: CZCE,  name: PTA,      multiplier: 5,     tick: 2,     margin_rate: 0.07,  fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.06,  fee_close_today: 0}
  MA: {exchange: CZCE,  name: 甲醇,       multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 0,    fee_notional_bp: 1.0, limit_pct: 0.06,  fee_close_today: 1.0}
  SA: {exchange: CZCE,  name: 纯碱,       multiplier: 20,    tick: 1,     margin_rate: 0.08,  fee_per_lot: 0,    fee_notional_bp: 1.0, limit_pct: 0.07,  fee_close_today: 1.0}
  RU: {exchange: SHFE,  name: 天然橡胶,     multiplier: 10,    tick: 5,     margin_rate: 0.09,  fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.07,  fee_close_today: 0}
  SC: {exchange: INE,   name: 原油,       multiplier: 1000,  tick: 0.1,   margin_rate: 0.16,  fee_per_lot: 20.0, fee_notional_bp: 0,   limit_pct: 0.14,  fee_close_today: 0}
  J:  {exchange: DCE,   name: 焦炭,       multiplier: 100,   tick: 0.5,   margin_rate: 0.12,  fee_per_lot: 0,    fee_notional_bp: 1.0, limit_pct: 0.08,  fee_close_today: 1.4}
  I:  {exchange: DCE,   name: 铁矿石,      multiplier: 100,   tick: 0.5,   margin_rate: 0.08,  fee_per_lot: 0,    fee_notional_bp: 1.0, limit_pct: 0.06,  fee_close_today: 1.0}
  RB: {exchange: SHFE,  name: 螺纹钢,      multiplier: 10,    tick: 1,     margin_rate: 0.07,  fee_per_lot: 0,    fee_notional_bp: 1.0, limit_pct: 0.05,  fee_close_today: 1.0}
  CU: {exchange: SHFE,  name: 铜,        multiplier: 5,     tick: 10,    margin_rate: 0.11,  fee_per_lot: 0,    fee_notional_bp: 0.5, limit_pct: 0.09,  fee_close_today: 1.0}
  AL: {exchange: SHFE,  name: 铝,        multiplier: 5,     tick: 5,     margin_rate: 0.11,  fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.09,  fee_close_today: 3.0}
  NI: {exchange: SHFE,  name: 镍,        multiplier: 1,     tick: 10,    margin_rate: 0.12,  fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.1,   fee_close_today: 3.0}
  SN: {exchange: SHFE,  name: 锡,        multiplier: 1,     tick: 10,    margin_rate: 0.14,  fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.12,  fee_close_today: 3.0}
  AU: {exchange: SHFE,  name: 黄金,       multiplier: 1000,  tick: 0.02,  margin_rate: 0.16,  fee_per_lot: 20.0, fee_notional_bp: 0,   limit_pct: 0.14,  fee_close_today: 0}
  AG: {exchange: SHFE,  name: 白银,       multiplier: 15,    tick: 1,     margin_rate: 0.22,  fee_per_lot: 0,    fee_notional_bp: 0.5, limit_pct: 0.2,   fee_close_today: 0.5}
  TF: {exchange: CFFEX, name: 5年期国债,    multiplier: 10000, tick: 0.005, margin_rate: 0.012, fee_per_lot: 3.0,  fee_notional_bp: 0,   limit_pct: 0.012, fee_close_today: 0}
```

## 2. 与当前 YAML 的差异清单 (42 处)

| # | symbol | field | old | new | 依据/生效 | source |
|---:|---|---|---:|---:|---|---|
| 1 | C | limit_pct | 0.04 | 0.06 | 保证金/涨跌停:2026-09-14 日交易参数(至少自2026-04-27); 手续费:2026-09-11 结算参数 | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 2 | M | limit_pct | 0.04 | 0.06 | 同 C | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 3 | Y | tick | 2 | 1 | tick 1元/吨: 2026-04-10 起(大商所公告〔2026〕32号); 其余同 C | http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html |
| 4 | Y | limit_pct | 0.05 | 0.06 | tick 1元/吨: 2026-04-10 起(大商所公告〔2026〕32号); 其余同 C | http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html |
| 5 | P | tick | 2 | 1 | tick 1元/吨: 2026-04-10 起(〔2026〕32号); 保证金/涨跌停 2026-09-14 日交易参数 | http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html |
| 6 | P | limit_pct | 0.06 | 0.07 | tick 1元/吨: 2026-04-10 起(〔2026〕32号); 保证金/涨跌停 2026-09-14 日交易参数 | http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html |
| 7 | JD | margin_rate | 0.08 | 0.07 | 2026-09-14 日交易参数 / 2026-09-11 结算参数 | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 8 | JD | limit_pct | 0.04 | 0.06 | 2026-09-14 日交易参数 / 2026-09-11 结算参数 | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 9 | CF | limit_pct | 0.05 | 0.06 | 4.3元/手 为长期基准(原始公告日 unknown); 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 10 | SR | margin_rate | 0.07 | 0.06 | 手续费 2元/手: 2026-06-23 夜盘起(郑商所公告〔2026〕91号, 由 3 元下调); 保证金 6%/涨跌停 5% 2026-09-11 结算参数 | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 11 | SR | fee_per_lot | 3.0 | 2.0 | 手续费 2元/手: 2026-06-23 夜盘起(郑商所公告〔2026〕91号, 由 3 元下调); 保证金 6%/涨跌停 5% 2026-09-11 结算参数 | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm |
| 12 | V | tick | 5 | 1 | 2026-09-14 日交易参数 / 2026-09-11 结算参数 | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 13 | V | limit_pct | 0.04 | 0.06 | 2026-09-14 日交易参数 / 2026-09-11 结算参数 | http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 |
| 14 | TA | limit_pct | 0.05 | 0.06 | 3元/手 为长期基准; 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 15 | MA | margin_rate | 0.08 | 0.07 | 万分之一: 2023-07-19 夜盘起(郑商函〔2023〕526号, 经红塔期货转发件; 交易所官网未定位原件); 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 16 | MA | fee_per_lot | 2.0 | 0 | 万分之一: 2023-07-19 夜盘起(郑商函〔2023〕526号, 经红塔期货转发件; 交易所官网未定位原件); 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 17 | MA | fee_notional_bp | 0 | 1.0 | 万分之一: 2023-07-19 夜盘起(郑商函〔2023〕526号, 经红塔期货转发件; 交易所官网未定位原件); 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 18 | MA | limit_pct | 0.05 | 0.06 | 万分之一: 2023-07-19 夜盘起(郑商函〔2023〕526号, 经红塔期货转发件; 交易所官网未定位原件); 2026-09-11 结算参数确认现行 | https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm |
| 19 | SA | margin_rate | 0.09 | 0.08 | 2026-06-05(郑商函〔2026〕476号: 保证金 8%/涨跌停 7% 自当日结算起; 手续费与平今均万分之一 自当晚夜盘起) | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 20 | SA | fee_per_lot | 3.5 | 0 | 2026-06-05(郑商函〔2026〕476号: 保证金 8%/涨跌停 7% 自当日结算起; 手续费与平今均万分之一 自当晚夜盘起) | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 21 | SA | fee_notional_bp | 0 | 1.0 | 2026-06-05(郑商函〔2026〕476号: 保证金 8%/涨跌停 7% 自当日结算起; 手续费与平今均万分之一 自当晚夜盘起) | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 22 | SA | limit_pct | 0.05 | 0.07 | 2026-06-05(郑商函〔2026〕476号: 保证金 8%/涨跌停 7% 自当日结算起; 手续费与平今均万分之一 自当晚夜盘起) | https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm |
| 23 | RU | margin_rate | 0.1 | 0.09 | 2026-07-10 收盘结算起(上期发〔2026〕260号: 涨跌停 7%/套保 8%/一般 9%) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 24 | RU | limit_pct | 0.06 | 0.07 | 2026-07-10 收盘结算起(上期发〔2026〕260号: 涨跌停 7%/套保 8%/一般 9%) | https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html |
| 25 | SC | margin_rate | 0.15 | 0.16 | 2026-06-25(上能发〔2026〕78号: 收盘结算起 涨跌停 14%/套保 15%/一般 16%; 上能发〔2026〕79号: 交易起 20元/手、免收平今) | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 26 | SC | limit_pct | 0.08 | 0.14 | 2026-06-25(上能发〔2026〕78号: 收盘结算起 涨跌停 14%/套保 15%/一般 16%; 上能发〔2026〕79号: 交易起 20元/手、免收平今) | https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html |
| 27 | J | margin_rate | 0.2 | 0.12 | 保证金 12%: 2026-06-12 结算起(大商所发〔2026〕210号, 由 20%/15% 下调); 手续费 2026-09-11 结算参数 | http://www.dce.com.cn/dce/content/2026/ywggytz/18630879.html |
| 28 | I | margin_rate | 0.12 | 0.08 | 涨跌停 6%/保证金 8%: 2026-09-09 结算起(大商所发〔2026〕333号, 由 9%/11% 下调; 9%/11% 自 2024-12-06 起) | http://www.dce.com.cn/dce/content/2026/ywggytz/18633751.html |
| 29 | RB | margin_rate | 0.08 | 0.07 | 2026-05-19 收盘结算起(上期发〔2026〕191号: 涨跌停 5%/套保 6%/一般 7%) | https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html |
| 30 | RB | limit_pct | 0.06 | 0.05 | 2026-05-19 收盘结算起(上期发〔2026〕191号: 涨跌停 5%/套保 6%/一般 7%) | https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html |
| 31 | CU | margin_rate | 0.1 | 0.11 | 2026-07-02 收盘结算起(上期发〔2026〕253号: CU2607~2702 涨跌停 9%/套保 10%/一般 11%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 32 | CU | limit_pct | 0.06 | 0.09 | 2026-07-02 收盘结算起(上期发〔2026〕253号: CU2607~2702 涨跌停 9%/套保 10%/一般 11%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 33 | AL | margin_rate | 0.1 | 0.11 | 2026-07-02 收盘结算起(上期发〔2026〕253号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 34 | AL | limit_pct | 0.06 | 0.09 | 2026-07-02 收盘结算起(上期发〔2026〕253号) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 35 | NI | limit_pct | 0.08 | 0.1 | 2026-07-02 收盘结算起(上期发〔2026〕253号: NI2607~2703 涨跌停 10%/套保 11%/一般 12%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 36 | SN | margin_rate | 0.12 | 0.14 | 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 12%/13%/14%); 2026 年 6-7 月未随铜铝镍下调 | https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html |
| 37 | SN | limit_pct | 0.08 | 0.12 | 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 12%/13%/14%); 2026 年 6-7 月未随铜铝镍下调 | https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html |
| 38 | AU | margin_rate | 0.1 | 0.16 | 2026-07-02 收盘结算起(上期发〔2026〕253号: AU 涨跌停 14%/套保 15%/一般 16%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 39 | AU | fee_per_lot | 10.0 | 20.0 | 2026-07-02 收盘结算起(上期发〔2026〕253号: AU 涨跌停 14%/套保 15%/一般 16%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 40 | AU | limit_pct | 0.06 | 0.14 | 2026-07-02 收盘结算起(上期发〔2026〕253号: AU 涨跌停 14%/套保 15%/一般 16%) | https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html |
| 41 | AG | margin_rate | 0.12 | 0.22 | 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 20%/21%/22%); 2026 年 2 月以来未下调 | https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html |
| 42 | AG | limit_pct | 0.06 | 0.2 | 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 20%/21%/22%); 2026 年 2 月以来未下调 | https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html |

差异归因: limit_pct 偏低(YAML 取合约文本下限) 19 处; margin_rate 过时 14 处; 手续费单位/水平过时 6 处(SR、MA×2、SA×2、AU); tick 3 处(Y、P 2026-04-10 起 1 元/吨; V 合约文本即 1 元/吨, YAML 的 5 有误)。仅 TF 与 YAML 完全一致。

## 3. 平今手续费备注 (日频调仓可能触发平今)

| 情形 | 品种 | 说明 |
|---|---|---|
| 平今 > 开仓 | **J** 焦炭 (1.4bp vs 1.0bp), **CU** 铜 (1.0bp vs 0.5bp, 2 倍) | J 的日内开仓腿也按 1.4bp 计, 日内往返实收 2.8bp; 若按 1.0+1.4 计会低估 0.4bp |
| 平今免收 (0) | CF, SR, TA, RU, **AU**, **SC**, TF | 日内往返仅付一次开仓费。SC/AU 当前免收并非高收; SC 在 2026-05-19~06-24 曾临时收平今 60 元/手(开仓 20), 回测该区间需按 60 元 |
| 平今 = 开仓 | C, M, Y, P, JD, V, I, MA, SA, RB, AL, NI, SN, AG | MA/SA 比例值平今不免收(万分之一) |

## 4. 逐品种来源与备注

### C 玉米 (DCE) — verified
- 生效/依据: 保证金/涨跌停:2026-09-14 日交易参数(至少自2026-04-27); 手续费:2026-09-11 结算参数
- 一手来源: http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/272.html
- 次级印证: https://www.bocifco.com/info.aspx?cid=3&id=124 ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 交割月 c2609 保证金 20%; 合约文本 4%/5% 仅为下限; 套保手续费 2026 全年减半(0.6元/手)。

### M 豆粕 (DCE) — verified
- 生效/依据: 同 C
- 一手来源: http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/2220.html
- 次级印证: https://www.bocifco.com/info.aspx?cid=3&id=124 ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 交割月 m2609 20%。

### Y 豆油 (DCE) — verified
- 生效/依据: tick 1元/吨: 2026-04-10 起(大商所公告〔2026〕32号); 其余同 C
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1
- 次级印证: https://www.cfc108.com/zxjtqh/2026-03/31/article_2026033117405111078.shtml ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 备注: tick 由 2 改 1 元/吨(2026-04-10 起); 2026-04-10 前历史数据 tick=2。交割月 y2609 20%。

### P 棕榈油 (DCE) — verified
- 生效/依据: tick 1元/吨: 2026-04-10 起(〔2026〕32号); 保证金/涨跌停 2026-09-14 日交易参数
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18628268.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1
- 次级印证: https://www.cfc108.com/zxjtqh/2026-03/31/article_2026033117405111078.shtml ; https://www.bocifco.com/info.aspx?cid=3&id=124
- 备注: tick 由 2 改 1 元/吨(2026-04-10 起)。交割月 p2609 20%。

### JD 鸡蛋 (DCE) — verified
- 生效/依据: 2026-09-14 日交易参数 / 2026-09-11 结算参数
- 一手来源: http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/2263.html
- 次级印证: https://www.shinnytech.com/articles/business-rules/products/dce.jd ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 交易单位 5吨/手, 报价 元/500kg → 每手 10 个报价单位, 合约价值=价格×10。无夜盘。交割月 jd2609 20%。

### CF 棉花 (CZCE) — verified
- 生效/依据: 4.3元/手 为长期基准(原始公告日 unknown); 2026-09-11 结算参数确认现行
- 一手来源: https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260914/FutureTradeParam.htm ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm
- 次级印证: https://www.iweiai.com/qihuo/mianhua ; https://futures.pingan.com/fuwuzhongxin/qihuobaozhengjintiaozheng/1789118795091.shtml
- 备注: 平今免收。CF609 交割月 20%。

### SR 白糖 (CZCE) — verified
- 生效/依据: 手续费 2元/手: 2026-06-23 夜盘起(郑商所公告〔2026〕91号, 由 3 元下调); 保证金 6%/涨跌停 5% 2026-09-11 结算参数
- 一手来源: https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/9c4c45f4d3594b28934613798bfccb4a.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm
- 次级印证: https://www.yntw.com/2026/06/38290.html ; https://www.iweiai.com/qihuo/baitang
- 备注: 平今免收。2026-06-23 前手续费 3 元/手。SR609 交割月 20%。

### V PVC (DCE) — verified
- 生效/依据: 2026-09-14 日交易参数 / 2026-09-11 结算参数
- 一手来源: http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1 ; http://www.dce.com.cn/dce/channel/list/2160.html
- 次级印证: https://www.bocifco.com/info.aspx?cid=3&id=124 ; https://www.9qihuo.com/qihuoshouxufei
- 备注: tick 为 1 元/吨(合约信息表), 原 YAML 的 5 有误。v2609 交割月 20%/涨跌停 9%。

### TA PTA (CZCE) — verified
- 生效/依据: 3元/手 为长期基准; 2026-09-11 结算参数确认现行
- 一手来源: https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260914/FutureTradeParam.htm ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm
- 次级印证: https://www.iweiai.com/qihuo/pta ; https://futures.pingan.com/fuwuzhongxin/qihuobaozhengjintiaozheng/1789118795091.shtml
- 备注: 平今免收。TA609 交割月 20%/涨跌停 9%(〔2026〕91号临时上调仅涉 2608/2609)。

### MA 甲醇 (CZCE) — verified
- 生效/依据: 万分之一: 2023-07-19 夜盘起(郑商函〔2023〕526号, 经红塔期货转发件; 交易所官网未定位原件); 2026-09-11 结算参数确认现行
- 一手来源: https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260914/FutureTradeParam.htm
- 次级印证: https://www.hongtaqh.com/wsyyt/sxftz/202307/20230719_2482.html ; https://www.iweiai.com/qihuo/jiachun
- 备注: 原 YAML 的 2元/手 是错误单位: 甲醇按成交金额万分之一(比例值), 平今同样万分之一(不免收)。MA609 交割月 20%/涨跌停 9%。

### SA 纯碱 (CZCE) — verified
- 生效/依据: 2026-06-05(郑商函〔2026〕476号: 保证金 8%/涨跌停 7% 自当日结算起; 手续费与平今均万分之一 自当晚夜盘起)
- 一手来源: https://www.czce.com.cn/cn/gyjys/jysdt/ggytz/webinfo/2026/6/b4badd9ad3654d43a79ed8577f247ace.htm ; https://www.czce.com.cn/cn/DFSStaticFiles/Future/2026/20260911/FutureDataClearParams.htm ; https://www.czce.com.cn/cn/jysfw/hyfw/sfbz/H077004002017index_1.htm
- 次级印证: https://www.ccbfutures.com/main/a/20260602/78085.shtml ; https://www.iweiai.com/qihuo/chunjian
- 备注: 原 YAML 的 3.5元/手 已过时: 现按成交金额万分之一(比例值), 平今同样万分之一。历史上多次对特定合约临时上调至万分之四。SA609 交割月 20%。

### RU 天然橡胶 (SHFE) — verified
- 生效/依据: 2026-07-10 收盘结算起(上期发〔2026〕260号: 涨跌停 7%/套保 8%/一般 9%)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202607/t20260708_832506.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 平今免收(平今折扣率 0)。ru2610(交割前一月) 10%, ru2609 交割月 20%。

### SC 原油 (INE) — verified
- 生效/依据: 2026-06-25(上能发〔2026〕78号: 收盘结算起 涨跌停 14%/套保 15%/一般 16%; 上能发〔2026〕79号: 交易起 20元/手、免收平今)
- 一手来源: https://www.ine.cn/publicnotice/notice/202606/t20260623_832248.html ; https://www.ine.cn/publicnotice/notice/202606/t20260623_832254.html ; https://www.ine.cn/reports/businessdata/prmsummary/ ; https://www.ine.cn/publicnotice/notice/202609/t20260911_833372.html
- 次级印证: https://www.wkjyqh.com/main/a/20260624/83191.shtml ; https://www.cifutures.com.cn/contents/2026/6/24-aa8fa13f03304a8ba5ca829c579e075a.html
- 备注: 平今当前免收, 但 2026-05-19~06-24 曾临时收 60元/手(上能发〔2026〕61号), 回测该区间需注意。上能发〔2026〕103号(9/11 发布): 自 2026-09-14 收盘结算起仅 SC2610/SC2611 升至涨跌停 16%/一般 18%, 其他月份维持 14%/16%(该通知仅一手复核员核到, 期货公司尚未转发)。2026 年 3/5/6/9 月频繁按合约月份调整, 回测应逐日取参数表。

### J 焦炭 (DCE) — verified
- 生效/依据: 保证金 12%: 2026-06-12 结算起(大商所发〔2026〕210号, 由 20%/15% 下调); 手续费 2026-09-11 结算参数
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18630879.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1
- 次级印证: https://www.huajinqh.com/ServiceCenter/CompanyNotice/26742.html ; https://www.huajinqh.com/UserFiles/upload/file/20260518/%E6%89%8B%E7%BB%AD%E8%B4%B9%E6%A0%87%E5%87%86%E8%A1%A820260519.pdf
- 备注: 平今 1.4bp 高于非日内 1.0bp; 且当日开仓若当日平掉, 开仓腿也按 1.4bp 计(日内往返实收 2.8bp, 用 1.0+1.4 会低估 0.4bp)。2026-06-12 前保证金 20%。

### I 铁矿石 (DCE) — verified
- 生效/依据: 涨跌停 6%/保证金 8%: 2026-09-09 结算起(大商所发〔2026〕333号, 由 9%/11% 下调; 9%/11% 自 2024-12-06 起)
- 一手来源: http://www.dce.com.cn/dce/content/2026/ywggytz/18633751.html ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryDayTradPara?variety=all&tradeType=1 ; http://www.dce.com.cn/frontend/dcereport/#/zh/queryFutAndOptSettle?variety=all&tradeType=1
- 次级印证: https://www.jiemian.com/article/15064021.html ; https://futures.pingan.com/fuwuzhongxin/qihuobaozhengjintiaozheng/1788953956098.shtml
- 备注: 刚于 2026-09-09 下调; 回测 2024-12-06~2026-09-08 区间应用 margin 0.11 / limit 0.09。

### RB 螺纹钢 (SHFE) — verified
- 生效/依据: 2026-05-19 收盘结算起(上期发〔2026〕191号: 涨跌停 5%/套保 6%/一般 7%)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202605/t20260515_831713.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.huajinqh.com/UserFiles/upload/file/20260518/%E6%89%8B%E7%BB%AD%E8%B4%B9%E6%A0%87%E5%87%86%E8%A1%A820260519.pdf ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 手续费按月份分档: 1/5/10 月合约(主力)及进入交割月前第二月起的合约 万分之1; 其余月份 万分之0.2。表中取主力月标准。平今与开仓同价。

### CU 铜 (SHFE) — verified
- 生效/依据: 2026-07-02 收盘结算起(上期发〔2026〕253号: CU2607~2702 涨跌停 9%/套保 10%/一般 11%)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.huajinqh.com/UserFiles/upload/file/20260518/%E6%89%8B%E7%BB%AD%E8%B4%B9%E6%A0%87%E5%87%86%E8%A1%A820260519.pdf ; https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml
- 备注: 平今为开仓 2 倍(万分之1 vs 万分之0.5, 平今折扣率 200%)。保证金/涨跌停按月份分档: cu2610~2702 为 11%/9%(主力档), cu2703+ 为 9%/7%, cu2609 交割月 20%。

### AL 铝 (SHFE) — verified
- 生效/依据: 2026-07-02 收盘结算起(上期发〔2026〕253号)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 分档: al2610~2702 为 11%/9%(主力档), al2703+ 为 9%/7%, al2609 20%。

### NI 镍 (SHFE) — verified
- 生效/依据: 2026-07-02 收盘结算起(上期发〔2026〕253号: NI2607~2703 涨跌停 10%/套保 11%/一般 12%)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 分档: ni2610~2703 为 12%/10%(主力档), ni2704+ 为 10%/8%, ni2609 20%。

### SN 锡 (SHFE) — verified
- 生效/依据: 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 12%/13%/14%); 2026 年 6-7 月未随铜铝镍下调
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 分档: sn2610~2703 为 14%/12%(主力档), sn2704+ 为 13%/11%, sn2609 20%。

### AU 黄金 (SHFE) — verified
- 生效/依据: 2026-07-02 收盘结算起(上期发〔2026〕253号: AU 涨跌停 14%/套保 15%/一般 16%)
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202606/t20260630_832357.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.huajinqh.com/UserFiles/upload/file/20260518/%E6%89%8B%E7%BB%AD%E8%B4%B9%E6%A0%87%E5%87%86%E8%A1%A820260519.pdf ; https://www.9qihuo.com/qihuoshouxufei
- 备注: 平今免收(折扣率 0)。手续费按月份分档: 6/12 月合约(主力)及进入交割月前第二月起的合约 20元/手, 其他月份 10元/手; 原 YAML 10 元是非主力月价。au2609 20%。2026 年 2 月起保证金处于历史高位(曾 17-22%)。

### AG 白银 (SHFE) — verified
- 生效/依据: 2026-02-09 收盘结算起(上期发〔2026〕56号: 已上市合约 20%/21%/22%); 2026 年 2 月以来未下调
- 一手来源: https://www.shfe.com.cn/publicnotice/notice/202602/t20260205_830383.html ; https://www.shfe.com.cn/data/busiparamdata/future/Settlement20260911.dat ; https://www.shfe.com.cn/reports/businessdata/feeandcharges/202609/W020260907546306371101.xlsx
- 次级印证: https://www.huajinqh.com/UserFiles/upload/file/20260518/%E6%89%8B%E7%BB%AD%E8%B4%B9%E6%A0%87%E5%87%86%E8%A1%A820260519.pdf ; https://www.gjqh.com.cn/ws-2003417-c0002_3-cn/news_94896.shtml
- 备注: 上期所当前保证金最高品种。分三档: ag2609~2704 22%/20%(主力档), ag2705~2706 19%/17%, ag2707+ 16%/14%。手续费分档: 6/12 月合约 万分之0.5, 其他月份 万分之0.1。平今与开仓同价。

### TF 5年期国债 (CFFEX) — verified
- 生效/依据: 2026-08-28 结算业务参数表(为 /cn/jscs.html 最新一期); 收费一览表 2026-06-01
- 一手来源: http://www.cffex.com.cn/sj/jscs/202608/28/20260828_1.csv ; http://www.cffex.com.cn/sj/jycs/202609/11/20260911_1.csv ; http://www.cffex.com.cn/cn/5tf.html ; http://www.cffex.com.cn/u/cms/www/202606/01175123xpr3.pdf
- 次级印证: https://www.7chabao.com/future/TF ; https://futures.pingan.com/fuwuzhongxin/qihuobaozhengjintiaozheng/1776339887211.shtml
- 备注: 与原 YAML 完全一致。平今免收。交割月合约(TF2609) 2%; 一般月份 1.2%; 合约文本最低 1% 仅为下限。乘数 10000 由面值 100 万/百元净价报价推导。

## 5. 未能核实项

无。138 项均由两名独立复核员 confirmed。仅两处次级证据提示(不影响取值): MA 万分之一的起始日 2023-07-19 来自红塔期货转发件(交易所官网未定位原件, 当前值已由官网结算参数确认); SC 2026-09-14 起 SC2610/2611 升档的上能发〔2026〕103号 仅一手复核员在 ine.cn 核到, 期货公司尚未转发。

## 6. 回测使用注意

(1) 交易所在假期前临时上调保证金/涨跌停, 节后恢复; (2) SHFE 有色/贵金属按合约月份分 2~3 档(表中取主力档), RB/AU/AG 手续费按主力月/非主力月分档(表中取主力月标准); (3) 交割月合约保证金一律 20%(CFFEX TF 2%), 表中取一般月份; (4) 所有手续费为交易所投机标准, 期货公司会加收; 套保手续费减半(DCE 2026 全年); (5) 表中值为 2026-09-11 交易所参数, 历史回测需分段(I 2026-09-09 前 11%/9%, J 2026-06-12 前 20%, SR 2026-06-23 前 3 元, SA 2026-06-05 前 3.5 元/9%/5%, Y/P 2026-04-10 前 tick=2, SHFE 各品种见 effective_date); (6) SC 自 2026-09-14 结算起 SC2610/SC2611 升至 16%/18%(上能发〔2026〕103号)。

建议 meta: `{verified: true, verified_date: 2026-09-11, slippage_ticks_per_side: 1}`。