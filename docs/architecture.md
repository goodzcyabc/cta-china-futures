# 架构

目标:一个从研究到实盘**同一条代码路径**的商品期货 CTA 系统。研究回测、每日出单、纸面账本调用同一套数据层、信号层与执行层;区别只在"截至哪一天"。(2026-10-06 按当前代码重写,2026-10-07 研究代码移到 `research/`;此前版本见 git 历史。)

```
configs/                 strategy*.yaml(五本纸面账、样例 sample.yaml、v0.6 演示)、instruments.yaml(合约参数)、
                         holidays.csv、paper_protocol.yaml(纸面验收协议)、experiments/(研究用配置)
src/cta/                 生产代码(纸面每日任务与出单导入的全部代码)
  data/                  DataSource 协议与三个实现:RicequantParquetSource(米筐导出,2016 → 2026-06-05)、
                         exchanges/ExchangeSource(四家交易所直连,追加写入不覆盖;主力规则 max_oi 默认 / oi_1.1x 复刻米筐)、
                         StitchedSource(默认:米筐历史 + 交易所增量,结算价用交易所官方值);exchanges/ 下各交易所抓取与解析
  instruments/           合约参数模型:乘数、跳价、保证金、手续费、涨跌停,带核验标记
  continuous/            主力切换(3 日确认、只向更晚到期)、T+1 排程合约、回溯复权连续价
  signals/               纯函数:时序动量、展期收益、仓单水平、合成(√n 归一)、波动率目标、总暴露上限、交易缓冲
  pipeline.py            build_panels → compute_signals(研究与实盘共用);可选外部因子入口 extra_factors
  execution/             plan.py 手数规划(T 收盘定手数 → 保证金上限缩减 → 手数带);ledger.py 成交与盯市状态机
  backtest/              engine.py 日频引擎(调用 execution)
  live/                  按 as-of 日生成目标手数与订单差异,写输入快照与指纹
  paper/                 纸面账本与每日运行器(事务化落盘、失败写 FAILED.json、可幂等重跑)
  analysis/              只读诊断:纸面验收、逐品种归因、leave-one-out、配对差统计
  risk/                  绩效指标(日频/月频夏普、NW t、回撤)
  report/                由回测结果生成报告与图
  cli.py                 research | live | report | paper
research/                研究代码,不参与出单
  cta_research/
    factors/             候选因子库与评估(base / library / evaluate / newdata);composite.py 多源合成因子 MSF
    signals/             基本面(PMI 等)、另类数据、商品期权信号的点时构造
    evaluation/          三臂候选评价 candidate_eval、walk-forward、季度自适应
    altdata/             另类数据管道(天气、ENSO、新闻语调、库存周报、PM2.5、商品期权)
    legacy/              engine_legacy.py,冻结,只复现 2026-09-22 前的报告
  scripts/               各轮研究与诊断脚本(结果写到 results/ 与 docs/research/)
  tests/                 研究代码的测试
scripts/                 运维:paper_daily.sh(launchd 每日入口)、fetch_exchange_data.sh、setup_env.sh、make_sample_data.py、
                         paper_acceptance.py、portfolio_diagnostics.py、capital_scan.py
paper/                   五本纸面账 v01 / v03 / v03p / v01r / v05;log/cron.log 为 launchd 日志
tests/                   生产代码测试:单测、引擎机制、前视截断、研究/纸面路径逐日一致、样例数据端到端、代码边界
data/sample/             公开样例数据(交易所官网数据,4 个品种 2021–2024);data/benchmarks/ 南华指数;其余 data/ 不入库
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
6. **研究与生产分开。** 生产代码在 `src/cta`,研究代码在 `research/`。生产代码不导入研究代码;唯一例外是配置启用 `msf` 时,`cta.pipeline._extra_factors_of` 按需加载 `cta_research.factors.composite`(`tests/test_boundaries.py` 检查,并在导入路径里去掉 `research/` 后导入全部生产入口)。研究代码可以导入生产代码,用同一条数据、信号、引擎路径评价候选。研究脚本输出到 `results/`(不入库)与 `docs/research/`。
7. **先预注册,再看结果。** 每个新假设先在 `docs/research/<主题>_prereg.md` 写定义、方向、评价口径与采用规则并提交,再算收益;试验计数与事后改动记在 `docs/design_log.md`,以追加为主(少数原地修改可在 git 历史中查到)。

## 因子研究层
`cta_research.factors`:`base`(输入容器、规格、注册表、统一标准化)、`library`(候选因子,一个 id 一个定义,窗口写死)、`evaluate`(单因子波动率目标组合、成本、TS/XS-IC、逐年、Deflated Sharpe)。旧的因子脚本(`research/scripts/factor_{screen,combo,newdata,spotbasis,global,reg}.py`、`exec_trials.py`)默认只能跑样本内(≤2021-12-31),样本外要显式 `--confirm-holdout`;`factor_walkforward.py` 没有这个门槛,一跑就到 2026-06-05(含样本外);二十一起的新候选用三臂评价:二十一在 `research/scripts/fundamental_signal_diagnostic.py` 内实现,二十二起抽成 `cta_research.evaluation.candidate_eval` 统一使用(回放二十一的 PMI 候选逐位一致)。因子进入生产必须经过设计日志的选入规则与 version 递增。
