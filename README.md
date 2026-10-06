# cta-china-futures

中国商品期货 CTA 的合约级研究与纸面交易系统。研究回测、每日出单、纸面账本走**同一条代码路径**;每个假设先预注册、再看结果,所有试验与改动都记在设计日志里。

**完整报告:[`report/report_v0.5.md`](report/report_v0.5.md)(PDF 同名)。下一步计划:[`TODO.md`](TODO.md)。**

## 现状(2026-10)

| 完整引擎、300 万、含手续费与 1 跳滑点 | 年化 | 夏普(月频) | 最大回撤 | 样本内 2017–21 夏普 | 样本外 2022–26/6 夏普 |
|---|---|---|---|---|---|
| v0.1:时序动量 + 展期收益 | 9.3% | 0.87 | −12.6% | 1.25 | 0.37 |
| **v0.3(champion)**:+ 交易所仓单水平(非量价因子) | 12.7% | 1.08 | −14.4% | 1.62 | 0.35 |

2016-01 → 2026-09,统计自首个持仓日 2017-01-11;22 个品种,10% 目标波动。样本外明显弱于样本内,报告第 0 节如实解释了原因。

- **纸面交易**:五本账(champion v0.3 + 4 个对照版本)的账期都从 2026-09-16 起算,但开立时间不同(北京时间 v0.1 09-17、v0.3 09-19、其余三本 09-22),开立前的交易日用点时数据补算;开立后由定时任务每个交易日自动运行。验收指标自 2026-09-23 起算,2026-12-16 出工程验收报告,版本采用决定不早于 2027-09。
- **研究**:累计 60 次计数试验,包括价格因子、季度重训、全市场持仓、PMI、天气/新闻/库存/空气质量等另类数据、商品期权、多源合成因子;按预注册规则,样本外没有一个带来可采用的改善(详见报告第 6、6A 节)。

## 目录

```
configs/       策略配置(五本纸面账 + v0.6 演示)、合约参数 instruments.yaml、休市日历、纸面验收协议;experiments/ 研究用配置
src/cta/       data(米筐 + 交易所直连 + 另类数据)→ continuous(换月)→ signals → execution(手数与成交)
               → backtest / live / paper;analysis 与 factors 是研究工具
scripts/       paper_daily.sh(每日纸面入口)、paper_acceptance.py、portfolio_diagnostics.py 等运维脚本;research/ 研究脚本
paper/         五本纸面账:v01、v03(champion)、v03p、v01r、v05
docs/          design_log.md(预注册与全部试验)、architecture.md、deployment.md;research/、data/ 见 docs/README.md
report/        当前报告 v0.5;archive/ 历史版本
tests/         单测、前视截断测试、研究/纸面路径逐日一致性测试
data/、results/  本地数据与回测输出(不入库;data/benchmarks/ 的南华指数除外)
```

## 运行

在仓库根目录执行(或先 `pip install -e ".[dev]"`,之后可直接用 `cta`、`pytest`):

```bash
PYTHONPATH=src python3 -m cta.cli research --config configs/strategy_v03.yaml     # 回测 → results/<配置摘要>_<参数表摘要>_stitched/
PYTHONPATH=src python3 -m cta.cli live --asof 2026-09-30 --equity 3000000 --positions book.csv --config configs/strategy_v03.yaml
PYTHONPATH=src python3 -m cta.cli paper status --book paper/v03 --config configs/strategy_v03.yaml
PYTHONPATH=src python3 -m pytest
python3 -m ruff check src tests && python3 -m mypy src
```

数据不随仓库分发:米筐导出放在 `data/ricecta/data`;交易所直连数据在 `data/exchanges/`,历史部分(行情与仓单 2016 年起,能源中心 2018-03 上市起;会员持仓排名大商所 2020-07 起、能源中心 2019-11 起;大商所风控参数未接入)用各交易所模块的命令行回填(`PYTHONPATH=src python3 -m cta.data.exchanges.<shfe|ine|czce|dce|params> backfill …`),之后由每日纸面任务逐日追加,大商所需要本机 Chrome 的 CDP 代理;另类数据见 [`docs/data/altdata_sources.md`](docs/data/altdata_sources.md)。

## 文档

- [`docs/README.md`](docs/README.md):全部研究文档的索引(按设计日志轮次)
- [`docs/design_log.md`](docs/design_log.md):预注册、试验计数、事后改动(以追加为主,少数原地修改可在 git 历史中查到)
- [`docs/architecture.md`](docs/architecture.md)、[`docs/deployment.md`](docs/deployment.md):代码结构、纸面交易运行手册
- 非量价因子:[`docs/research/non_pv_factor_card.md`](docs/research/non_pv_factor_card.md)(仓单水平);多源合成因子演示 [`docs/research/msf_demo.md`](docs/research/msf_demo.md)
