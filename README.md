# cta-china-futures

中国商品期货 CTA 的合约级研究与纸面交易系统。研究回测、每日出单、纸面账本走**同一条代码路径**;每个假设先预注册、再看结果,所有试验与改动都记在设计日志里。

**完整报告:[`report/report_v0.5.md`](report/report_v0.5.md)(PDF 同名)。下一步计划:[`TODO.md`](TODO.md)。**

## 现状(2026-10)

| 完整引擎、300 万、含手续费与 1 跳滑点 | 年化 | 夏普(月频) | 最大回撤 | 样本内 2017–21 夏普 | 样本外 2022–26/6 夏普 |
|---|---|---|---|---|---|
| v0.1:时序动量 + 展期收益 | 9.3% | 0.87 | −12.6% | 1.25 | 0.46¹ |
| **v0.3(champion)**:+ 交易所仓单水平(非量价因子) | 12.7% | 1.08 | −14.4% | 1.62 | 0.45¹ |

2016-01 → 2026-09,统计自首个持仓日 2017-01-11;22 个品种,10% 目标波动。样本外明显弱于样本内,报告第 0 节如实解释了原因。

¹ 报告 v0.5 里这一列是 0.37 / 0.35:那里的样本外切片从 2022-01-04 开始,按月统计时第一个月的收益被丢掉了,等于漏算 2022 年 1 月整月(v0.1 +4.8%、v0.3 +5.4%)。这里补上。报告中其他用同样切法算出的样本外月频夏普也少算了这个月;逐项复核列在 [`TODO.md`](TODO.md)。2026-10-07 发现,记在设计日志二十七。

**选合约规则与回测基线不一致(2026-10-07 发现)。** 回测基线的历史段(到 2026-06-05)用米筐主力表选合约,规则大致是:新合约前一日持仓量超过当前主力 1.1 倍才换。纸面账之后用交易所数据,规则是"前一日持仓量最大的合约",换得更早。同一策略全程按纸面规则回测,月频夏普是 0.89,基线是 1.06(同一窗口)。差距全部来自选合约规则:只用交易所公开数据加复刻的 1.1 倍规则,能复现基线(1.07)。详见 [`docs/research/source_check.md`](docs/research/source_check.md)。纸面验收期(到 2026-12-15)内不改规则,已列入 TODO。

- **纸面交易**:五本账(champion v0.3 + 4 个对照版本)的账期都从 2026-09-16 起算,但开立时间不同(北京时间 v0.1 09-17、v0.3 09-19、其余三本 09-22),开立前的交易日用点时数据补算;开立后由定时任务每个交易日自动运行。验收指标自 2026-09-23 起算,2026-12-16 出工程验收报告,版本采用决定不早于 2027-09。
- **研究**:累计 60 次计数试验,包括价格因子、季度重训、全市场持仓、PMI、天气/新闻/库存/空气质量等另类数据、商品期权、多源合成因子;按预注册规则,样本外没有一个带来可采用的改善(详见报告第 6、6A 节)。

## 原理

每个交易日收盘后,对 22 个品种各算一个数:该做多还是做空、仓位多大。第二天开盘按这个数调仓。

**三个信号**,每个都压到 −1(满仓空)到 +1(满仓多)之间:

1. **趋势(时序动量)**:看过去 1、3、6、12 个月这个品种涨了还是跌了,涨就偏多,跌就偏空。
   - 涨跌幅先除以该品种自己的波动率,所以"铜涨 5%"和"镍涨 5%"不算一样强(镍平时就波动大)。
   - 四个回看期平均。
   - 为什么可能有效:消息被价格慢慢消化,套保盘、库存周期这类力量会持续一段时间。
2. **展期收益(carry)**:比较当前持有的主力合约和"次主力"(到期更晚、持仓量最大的合约)的价格。
   - 例子:螺纹钢主力 3,500、三个月后到期的次主力 3,400。远月便宜,说明现货偏紧(这叫"贴水")。
   - 持有近的那个合约等它往现货靠,每年大约能多赚 (3500/3400 − 1) × 4 ≈ 12%,所以偏多。反过来远月贵就偏空。
3. **仓单水平**(非量价因子,交易所每天公布):注册仓单是交易所仓库里随时可以拿去交割的货。
   - 一个品种的仓单处在自己过去一年里的低位,说明可交割的现货少、容易被逼仓,偏多;处在高位就偏空。
   - 再和当天其他品种比较,只看相对高低。
   - 说明书:[`docs/research/non_pv_factor_card.md`](docs/research/non_pv_factor_card.md)。

三个信号等权平均,得到每个品种的方向和强度。

**仓位怎么定**:
- 每个品种按自己的波动率分配风险:波动小的(如黄金)同样的信号可以持更多名义金额,波动大的(如镍)少持。
- 再用最近 40 个交易日各品种之间的相关性估算整个组合的波动,整体缩放到年化 10%。
- 上限三条:单品种名义金额不超过权益的 1 倍,所有品种合计不超过 3 倍,保证金占用不超过 40%。
- 两道"小变化不动"的缓冲,省手续费:
  - 新目标与当前暴露相差不到新目标的 30%,不调;
  - 换算成整手后,差额不到当前手数的 30% 也不调。

**怎么成交**:
- T 日收盘后,用 T+1 要持有的合约在 T 日的收盘价,把目标换成整手。
- T+1 开盘成交。有夜盘的品种就是 T 日晚上 21:00 开盘那一刻。
- 成交价按开盘价往不利方向多算 1 跳(滑点),另收交易所手续费。
- 当天没能成交(停牌、涨跌停、缺行情)的不顺延,第二天按最新信号重算。
- **换月**:主力合约(按持仓量判定,两种规则见上文"选合约规则"一段)换了,而且连续 3 天都是同一个新合约,才平掉旧合约、开新合约;只往更晚到期的合约换,不回切。

**记账**:按交易所官方结算价每日盯市。回测、每日出单、纸面账本调用同一套规划与记账函数。用 2025-03-03 → 04-11 共 29 个真实交易日逐日重放核对过:回测与"逐日出单 → 次日成交 → 盯市"两条路径每日持仓手数完全相等。

**研究纪律**:
- 新想法先写预注册(定义、方向、评价口径、采用规则)并提交,再算收益。
- 每个候选都计入试验数(当前 60),包括失败的。
- 2016–2021 是样本内,2022 年起是样本外;但 2022–2026 已被反复看过,真正干净的证据只来自纸面期。
- 生产信号有"把未来数据截掉,结果不变"的自动测试(前视截断测试)。

## 目录

```
src/cta/         生产代码:每天真正用来算目标仓位、出单、记账的部分
  data/          米筐导出读取;四家交易所官网数据的抓取、解析、交易日历
  continuous/    换月:决定每天持有哪个合约,拼回溯复权连续价
  signals/       三个生产信号与仓位计算(趋势、展期收益、仓单水平;波动率目标)
  execution/     目标暴露 → 整手 → 成交与记账(回测、出单、纸面三方共用)
  backtest/ live/ paper/   回测引擎、每日出单、纸面账本
  analysis/      只读诊断:纸面验收、归因、配对比较统计
research/        研究代码,不参与出单
  cta_research/  factors(候选因子库、多源合成因子 MSF)、signals(基本面/另类数据/期权信号)、
                 evaluation(三臂候选评价、walk-forward)、altdata(另类数据抓取)、legacy(冻结的旧引擎)
  scripts/       每轮研究的脚本(结果写到 docs/research/)
  tests/         研究代码的测试
configs/         策略配置(五本纸面账、样例、v0.6 演示)、合约参数、休市日历、纸面验收协议;experiments/ 研究用配置
scripts/         运维:paper_daily.sh(每日纸面入口)、fetch_exchange_data.sh(回填交易所数据)、setup_env.sh、
                 make_sample_data.py、paper_acceptance.py、portfolio_diagnostics.py、capital_scan.py
paper/           五本纸面账:v01、v03(champion)、v03p、v01r、v05
docs/            design_log.md(预注册与全部试验)、architecture.md、deployment.md;research/、data/ 见 docs/README.md
report/          当前报告 v0.5;archive/ 历史版本
tests/           生产代码的测试:单测、前视截断、研究/纸面路径逐日一致、样例数据端到端
data/sample/     公开样例数据(见下);data/benchmarks/ 是南华指数;其余 data/ 与 results/ 不入库
```

生产代码不导入研究代码。唯一例外是可选的多源合成因子:配置里启用 `msf` 时,`cta.pipeline` 才去加载 `cta_research`。`tests/test_boundaries.py` 检查这一点。

## 安装与运行

需要 Python 3.12:

```bash
scripts/setup_env.sh
```

它会建 `.venv`,装 [`requirements-dev.txt`](requirements-dev.txt)(版本全部固定),并把 `src/`、`research/` 加入环境的导入路径。之后在仓库根目录:

```bash
.venv/bin/python -m pytest
```

没有本地完整数据时,依赖真实数据的测试会跳过,样例数据测试照常运行。

### 不需要任何私有数据:样例数据

`data/sample/exchanges_sample.tar.gz`(2.4 MB)是交易所官网公开数据的一小份:
- 4 个品种:铜 CU、螺纹钢 RB、豆粕 M、白糖 SR;
- 2021-01-04 → 2024-12-31 的逐合约行情(含官方结算价)和仓单。

```bash
mkdir -p /tmp/cta-sample && tar -xzf data/sample/exchanges_sample.tar.gz -C /tmp/cta-sample
.venv/bin/python -m cta.cli research --config configs/sample.yaml --source exchange --exchange-root /tmp/cta-sample/exchanges
```

`configs/sample.yaml` 与 champion v0.3 参数相同,只缩小了品种和区间。4 个品种的结果只说明流程能跑通,不代表策略表现。样例由 `scripts/make_sample_data.py` 从完整数据生成;同样输入、同样的包版本重跑,输出逐字节相同。

### 用公开数据复现正式基线

```bash
scripts/fetch_exchange_data.sh
.venv/bin/python -m cta.cli research --config configs/strategy_v03.yaml --source exchange --dominant-rule oi_1.1x
```

- 第一条从四家交易所官网回填 2016 年以来的行情与仓单。四所两类数据合计约两万次逐日请求(每所请求间隔 ≥1 秒),估计要几个小时;可断点续跑。
  - 上期所、能源中心、郑商所直连即可。
  - 大商所全站有反爬,需要本机 Chrome 开远程调试并运行 CDP 代理,见 [`docs/data/data_exchanges_dce.md`](docs/data/data_exchanges_dce.md)。
- 第二条在 2017-01-11 → 2026-06-05 上与正式基线一致:月频夏普 1.07 对 1.06,配对差 +0.11%/年,t = 0.52。
  - 这个数字是在本机已有的交易所数据上算的,没有从零重新抓一遍再跑。
  - 本机郑商所 2016–2025 年的行情来自年度打包;脚本改用逐日文件,每年抽查一天(共 10 天),解析结果逐行相同。
- 不加 `--dominant-rule` 时用纸面在用的"前一日持仓最大"规则,结果是 0.89。原因见上文"选合约规则"一段。

### 有米筐导出时

正式基线需要两份数据:米筐导出放在 `data/ricecta/data`;交易所数据在 `data/exchanges`(官方结算价与仓单只来自交易所,用上面的脚本回填)。然后在仓库根目录运行:

```bash
.venv/bin/python -m cta.cli research --config configs/strategy_v03.yaml
.venv/bin/python -m cta.cli live --asof 2026-09-30 --equity 3000000 --positions book.csv --config configs/strategy_v03.yaml
.venv/bin/python -m cta.cli paper status --book paper/v03 --config configs/strategy_v03.yaml
```

- `research`:正式基线,米筐历史 + 交易所增量,输出到 `results/`。
- `live`:生成次日订单。
- `paper status`:查看纸面账本。

另类数据见 [`docs/data/altdata_sources.md`](docs/data/altdata_sources.md)。

## 文档

- [`docs/README.md`](docs/README.md):全部研究文档的索引(按设计日志轮次)
- [`docs/design_log.md`](docs/design_log.md):预注册、试验计数、事后改动(以追加为主,少数原地修改可在 git 历史中查到)
- [`docs/architecture.md`](docs/architecture.md)、[`docs/deployment.md`](docs/deployment.md):代码结构、纸面交易运行手册
- 非量价因子:[`docs/research/non_pv_factor_card.md`](docs/research/non_pv_factor_card.md)(仓单水平);多源合成因子演示 [`docs/research/msf_demo.md`](docs/research/msf_demo.md)
- 数据路径校验:[`docs/research/source_check.md`](docs/research/source_check.md)
