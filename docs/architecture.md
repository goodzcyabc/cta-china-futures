# 架构

目标:一个从研究到实盘**同一条代码路径**的商品期货 CTA 系统。研究回测、每日出单、纸面账本调用同一套数据层、信号层与执行层;区别只在"截至哪一天"。(2026-10-06 按当前代码重写;此前版本见 git 历史。)

```
configs/                 strategy*.yaml(五本纸面账 + v0.6 演示)、instruments.yaml(合约参数)、holidays.csv、
                         paper_protocol.yaml(纸面验收协议)、experiments/(研究用配置)
src/cta/
  data/                  DataSource 协议与三个实现:RicequantParquetSource(米筐导出,2016 → 2026-06-05)、
                         exchanges/ExchangeSource(四家交易所直连,追加写入不覆盖)、StitchedSource(默认:
                         米筐历史 + 交易所增量,结算价用交易所官方值);exchanges/ 下各交易所抓取与解析;
                         alt/ 另类数据管道(天气、ENSO、新闻语调、库存周报、PM2.5、商品期权)
  instruments/           合约参数模型:乘数、跳价、保证金、手续费、涨跌停,带核验标记
  continuous/            主力切换(3 日确认、只向更晚到期)、T+1 排程合约、回溯复权连续价
  signals/               纯函数:时序动量、展期收益、仓单水平、合成(√n 归一)、波动率目标、总暴露上限、交易缓冲
  pipeline.py            build_panels → compute_signals(研究与实盘共用);可选外部因子入口 extra_factors
  execution/             plan.py 手数规划(T 收盘定手数 → 保证金上限缩减 → 手数带);ledger.py 成交与盯市状态机
  backtest/              engine.py 日频引擎(调用 execution);engine_legacy.py 冻结,只复现 2026-09-22 前的报告
  live/                  按 as-of 日生成目标手数与订单差异,写输入快照与指纹
  paper/                 纸面账本与每日运行器(事务化落盘、失败写 FAILED.json、可幂等重跑)
  analysis/              只读研究工具:三臂候选评价、配对差统计、walk-forward、纸面验收、各轮信号构造
  factors/               研究用因子库与评估;composite.py 为多源合成因子 MSF(配置启用时进入生产路径)
  risk/                  绩效指标(日频/月频夏普、NW t、回撤)
  report/                由回测结果生成报告与图
  cli.py                 research | live | report | paper
scripts/                 paper_daily.sh(launchd 每日入口)、paper_acceptance.py、portfolio_diagnostics.py、
                         capital_scan.py、rqdata_export_options.py;research/ 一次性研究与诊断脚本
paper/                   五本纸面账 v01 / v03 / v03p / v01r / v05;log/cron.log 为 launchd 日志
tests/                   单测、引擎机制测试、前视截断测试、研究/纸面路径逐日一致性测试
docs/                    design_log.md(预注册与全部试验)、本文件、deployment.md(运行手册);
                         research/(各轮预注册与结果)、data/(数据源与参数核验)、drills/(故障演练证据)
report/                  当前报告 report_v0.5;archive/ 为历史版本
```

## 关键约定

1. **价格类信号(时序动量、波动率)用回溯复权连续价;展期收益用持有合约与次主力的真实收盘价,仓单水平用交易所注册仓单;成交与盯市只看真实合约价。** 连续价的历史水平会随每次换月重新缩放;定手数用 T+1 将持有合约在 T 日的收盘价,名义金额、保证金、手续费、滑点按实际成交或持有的合约计算。
2. **T 日收盘算信号,T+1 开盘成交。** 有夜盘的品种,T+1 的开盘即 T 日 21:00 夜盘开盘;任何 15:00 之后公布的数据都要按这个时点判断能否使用。
3. **换月由数据决定,不由日历决定。** 主力按持仓量切换并需连续 3 日确认;换月两腿要么同时成交,要么都不动。
4. **没有写死的成本。** 跳价、保证金、手续费、涨跌停来自 `configs/instruments.yaml`(带 verified 标记);米筐历史段合约的乘数来自米筐元数据,与参数表一致。
5. **每次运行有指纹。** 结果目录名由配置摘要与参数表摘要构成(`results/<配置摘要>_<参数表摘要>[_<数据源>]/`);配置摘要、参数表摘要、数据清单摘要、git SHA 都写入 `run.json` 与订单快照 `snapshot.json`。
6. **研究与生产分开。** 生产信号在 `cta.signals`(外部因子只能经 `pipeline` 的 extra_factors 入口、由配置显式启用);可复用、带测试的研究工具在 `cta.analysis` / `cta.factors`;一次性分析在 `scripts/research/`,输出到 `results/`(不入库)与 `docs/research/`。
7. **先预注册,再看结果。** 每个新假设先在 `docs/research/<主题>_prereg.md` 写定义、方向、评价口径与采用规则并提交,再算收益;试验计数与事后改动记在 `docs/design_log.md`,以追加为主(少数原地修改可在 git 历史中查到)。

## 因子研究层
`cta.factors`:`base`(输入容器、规格、注册表、统一标准化)、`library`(候选因子,一个 id 一个定义,窗口写死)、`evaluate`(单因子波动率目标组合、成本、TS/XS-IC、逐年、Deflated Sharpe)。旧的因子脚本(`scripts/research/factor_{screen,combo,newdata,spotbasis,global,reg}.py`、`exec_trials.py`)默认只能跑样本内(≤2021-12-31),样本外要显式 `--confirm-holdout`;`factor_walkforward.py` 没有这个门槛,一跑就到 2026-06-05(含样本外);二十一起的新候选用三臂评价:二十一在 `scripts/research/fundamental_signal_diagnostic.py` 内实现,二十二起抽成 `cta.analysis.candidate_eval` 统一使用(回放二十一的 PMI 候选逐位一致)。因子进入生产必须经过设计日志的选入规则与 version 递增。
