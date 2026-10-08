# 上线路径(8 个月)与验收

## 阶段
1. **原型(已完成)**:研究=生产同一路径;`cta live` 可按 as-of 日输出目标手数与订单差异、输入快照与指纹(按需手动运行;每日出单现由纸面任务 `cta paper catchup` 完成)。
2. **纸面交易(第 1–3 个月;2026-09-16 起,当前阶段)**:每日收盘后运行,订单记入只追加日志;次日以实际开盘/TWAP 价复核成交假设;跟踪实现滑点 vs 假设(1 跳)。
3. **小规模实盘(第 4–6 个月)**:资金按需求方给定的 100–500 万起步(默认 300 万;100 万时黄金/原油/铜/锡一手即占权益 33–78%,见 `results/capital_scan/summary.md`),单品种手数上限;每周核对持仓与经纪商对账单;任一核对差异即停机。
4. **放量(第 7–8 个月)**:按容量与实现滑点决定规模上限。

## 通过纸面交易的条件(2026-09-09 原写法;已被 design_log 17.5 / 十八 替代,不再适用)
- 原写法:3 个月实现月频夏普 > 0;实现滑点均值 ≤ 1.5 跳;订单/持仓对账 100% 一致;无一次数据或时区事故。现行规则见下文"三个月验收与配对差":3 个月只做工程验收,不以夏普判定;滑点只报告;FAILED 日经后续重放修复算完整。

## 中止条件(2026-09-09 原写法;纸面期未按此执行)
- 原写法:从峰值回撤超过 15%;或连续 3 个月实现滑点 > 2 跳;或数据源缺失导致任一交易日无法在开盘前出单。纸面期实际按 design_log 18.2/18.3 执行:2026-09-23 大商所抓取超时、五本账当日失败,09-24 定时运行补跑成功,纸面交易未中止;纸面期内唯一预注册的动作是 18.3 的 challenger 停账。

## 上线前必做
1. 数据源:接入持牌实时/日终行情与合约参数(乘数、跳价、涨跌幅、保证金按日更新);与本仓库在 2023–2026 做因子与目标手数一致性校验。
2. 合约参数表 `instruments.yaml` 已按交易所官网核验(`docs/data/instruments_verification.md`,含来源与未能核实项);上线前仍需换成经纪商实际费率(交易所费率 + 经纪商加收)并按日刷新保证金。
3. 执行:开盘后 TWAP 或限价分批;涨跌停/停牌当日不成交、次日按最新目标重出(引擎、出单、纸面账本共用 `cta.execution`,未成交不顺延、次日按最新信号重算,design_log 17.7);换月两腿预检后同进退。
4. 风控硬约束:总名义 ≤ 3 倍、单品种 ≤ 1 倍(或 0.25,见试验)、保证金占用 ≤ 40%、单日亏损与回撤停机线;所有约束在出单前检查并留痕。
5. 运维:日切调度、失败告警、快照与指纹留存(已有)、持仓对账脚本、月度报告自动生成。
6. 监控:实现 vs 假设滑点、换手、各信号分量的滚动夏普、暴露漂移、因涨跌停/停牌当日未成交的订单腿(未成交不顺延,次日按最新目标重出)。

## 治理
- `configs/strategy.yaml` 参数冻结;任何改动进 `docs/design_log.md`。version 自 2026-09-12 的 0.1.2 起未再递增:2026-09-19 显式固定 `universe.symbols`(design_log 11.2)、2026-09-23 `trade_buffer` 拆为 `exposure_buffer`/`lot_band`(design_log 17.7)两次改动只记入设计日志,配置指纹随之改变。
- 回测结果目录以 `<配置指纹>_<参数表指纹>[_<数据源>]` 命名,不同配置或参数表的结果互不覆盖;同一配置、参数表与数据源重跑会写入同一目录并覆盖其中文件(`results/` 不进 git)。

## 纸面交易运行手册(2026-09-16 起)
- 数据:每个工作日多伦多 05:10(北京 17:10;2026-11-01 多伦多结束夏令时后为北京 18:10)由 `cta paper catchup`(主账本 v0.1)调各交易所模块 `ingest_day` 拉当日行情/持仓排名/仓单,落盘到 `data/exchanges/`(永不覆盖)。
- 信号路径与研究完全相同:`build_panels → compute_signals → generate_orders`,数据源为 `StitchedSource`(米筐历史到 2026-06-05,之后交易所直连)。
- 成交模拟:上一交易日生成的订单在当日**开盘价 + 1 跳滑点**成交,手续费按核验参数表;开盘触及涨跌停或开盘价为空(停牌/零成交)则该单当日不成交、次日按最新目标重出;换月两腿先预检、任一腿不可成交则两腿都不动;每日按官方结算价盯市。2026-09-22/23 起回测引擎、实盘出单与纸面账本共用 `cta.execution`(手数规划 + 成交/盯市状态机),口径已统一(design_log 17.7);`tests/test_paths_agree.py` 在 2025-03-03 → 04-11 共 29 个真实交易日(首日空仓,其后 28 日有成交)逐日核对两条路径:持仓手数完全相等,权益差 < 1e-6 元。
- 状态与留痕(每本账一个目录 `paper/<账本>/`,2026-10-06 起;之前五本账分别在仓库根目录 `paper/`、`paper_v03/` 等):`state.json`(权益、持仓)、`orders/<日期>/`(订单 + 输入快照与指纹)、`fills/<日期>.csv`、`equity.csv`、`log/<日期>.json`;launchd 日志在 `paper/log/cron.log`;每日 git 提交一次,提交时间即时间戳。
- 调度:`deploy/com.cta.paper.plist`(launchd,工作日 05:10 多伦多);漏跑由 `cta paper catchup` 按账本最后盯市日补齐。
- 运行环境:`scripts/paper_daily.sh` 用仓库内的 `.venv/bin/python`(Python 3.12,版本固定在 `requirements.txt`);新机器或新检出先运行一次 `scripts/setup_env.sh`。`.venv` 不存在时脚本报警(`no-venv`)且不运行任何账本,不会退回系统 Python(2026-10-07 起;此前用系统 Python 3.9,切换前已验证五本账目标暴露逐位相同,见设计日志二十七)。
- 通过/中止标准:纸面 3 个月只做**工程验收**——数据完整率(无 FAILED 日)、成交率 ≥95%、实现滑点、盯市对账无差异、故障恢复演练;**不据此比较或选择版本**(3 个月夏普差的标准误 ±1.3,design_log 17.5)。净夏普与回测同期差在 ±0.5 内仅作"系统没坏"的粗检;盯市口径已统一(纸面与回测都用官方结算价,design_log 18.4)。

### 运行中发现并修复的坑(2026-09-17)
- **交易所网站白天就有"当日"行情文件,是盘中快照(结算价为空)。** 首次试跑在北京 11:21 抓到快照、按空结算价盯市并出单,全部作废(已回滚,留痕见 git 历史 c9c4a10 / 32ed30b)。现在两道闸门:`runner.settlement_published` 北京 16:30 前不抓当天;`shfe.parse_quotes` 若 >5% 成交合约无结算价抛 `NotFinalError`,`shfe.ingest_day`(上期所与能源中心共用)随即删除已缓存的 raw,下次运行重抓。
- 大商所抓取依赖本机 Chrome 的 CDP 代理(web-access 的 proxy);Chrome 未开时 DCE 当日缺数据 → **持有 DCE 合约的账本当日失败**(FAILED.json,非零退出,桌面通知),次日 catchup 重试同一日;不再"静默零盈亏"。上线前需要换成不依赖浏览器的抓取(例如带完整 cookie 的请求或经纪商行情)。
- 每日脚本在账本无变化时不提交(先检查 `git diff --cached`);提交或推送失败会进入告警链(通知 + 退出码 1)。注意脚本提交的是**整个暂存区**并 `git push origin HEAD`:05:10 前不要在本工作副本留下已暂存但未准备提交的改动。

### 并行账本(2026-09-18 起)
- 角色(design_log 十八):**champion = `paper/v03/`(v0.3)**;其余四本为 challenger,只做配对差报告,不选赢家;不再新增账本。验收报告与 `configs/paper_protocol.yaml` 里沿用原标签(paper、paper_v03…),目录由 `dir` 字段给出。
- `paper/v01/`:v0.1(tsmom + carry),主账本(拉数据),配置 `configs/strategy.yaml`;`paper/v03/`:v0.3(+ 仓单水平),`strategy_v03.yaml`;`paper/v03p/`:v0.3 剔除 5 个 IS 亏钱品种(design_log 十四),`strategy_v03p.yaml`;`paper/v01r/`:v0.1 + 监管事件覆盖层(design_log 13.6/13.7,事件由每日 params 推导,大商所缺),`strategy_v01r.yaml`;`paper/v05/`:v0.3 信号、只做 12 个工业品(design_log 十五,事后假设的前向检验),`strategy_v05.yaml`。同一数据、同一成交规则;每日脚本先跑主账本(拉数据),再跑其余四本(不拉)。手动操作时 `--book` 必须和对应的 `--config` 配对,命令行不检查配对;账本目录没有 `state.json` 时命令行拒绝运行(新建账本须显式加 `--init`),每日脚本也会先检查并报警。
- 比较标准:3 个月后报告各 challenger 相对 champion(v0.3)的配对 PnL 差及其区间,**不做采用决定**(design_log 17.5/17.6);v0.3 换手高约 20%,成交率与滑点是重点。

## 失败语义与恢复(2026-09-22 起)
- 日步"全有或全无":成交、盯市、出单全部成功才写 `fills/<日>.csv`、`equity.csv`(按日去重)、`state.json`(原子)。任一步失败 → 命令行在 stderr 输出 `PAPER STEP FAILED: <账本目录名,如 v03> <日> failed at stage '<quotes|fill|settle|orders|save|commit>': <错误>`,写 `<book>/FAILED.json`(日期、阶段、原因、traceback),`state.json` 不变,`log/<日>.json` 带 `failed`,CLI 非零退出。
- 会触发失败的情况:交易日但磁盘无该日行情(数据迟到、抓取失败、或休市未登记在 `configs/holidays.csv`);持仓合约当日缺行情或结算价为空;账本任何数值非有限;`generate_orders` 抛错(as-of 非交易日、未核验品种等)。
- 恢复:修好原因(补数据 / 补日历 / 修代码)后重跑 `paper catchup --date <今天>` 即可,从失败日起幂等重放;成功后 FAILED.json 自动删除。不需要手工改 state.json。
- 最常见的失败是大商所抓取超时(2026-09-23、10-08 两次):`paper/v01/log/<日>.json`(只有主账本记录 ingest)里 DCE 是超时错误(10-08 在系统 Python 3.9 下写作 `error: timeout: timed out`,现在 .venv 的 Python 3.12 下会写作 `error: TimeoutError: timed out`;补跑成功会覆盖这个日志,原始记录在当天的 `paper: <日> (FAILED: …)` 提交里),持有大商所合约的账本在 `settle` 失败。09-23 那次第二天的定时任务自动补上了;10-08 那次原因是 CDP 代理在跑、但没连上 Chrome(`curl -s localhost:3456/health` 显示 `connected: null`、`chromePort: null`;注意代理空闲时也这样显示,有请求进来才连,所以光看它不能确诊)。恢复步骤(10-08 即按此处理;当时该检出还没有 `.venv`,第 2 步用的是 `PYTHONPATH=src python3`,现在用 `.venv/bin/python`):
  1. 用户确认 Chrome 开着、远程调试可用;
  2. 在 launchd 用的那个检出(`deploy/com.cta.paper.plist` 里的路径,`main`、暂存区为空)的仓库根目录运行 `.venv/bin/python -m cta.data.exchanges.dce ingest --date <失败日>`,确认 `data/exchanges/DCE/{quotes,receipts}/<年>/<YYYYMMDD>.parquet`(如 `2026/20261008.parquet`)已落盘、health 变成 `connected: true`;
  3. 在同一检出运行 `scripts/paper_daily.sh >> paper/log/cron.log 2>&1`(重放失败日、提交并推送;已结算的日子跳过),之前先在 cron.log 写一行说明这是手动补跑。不要在 worktree 里跑:脚本会推进 worktree 里那份账本副本并推送分支,真正的账本仍是失败状态。
- `scripts/paper_daily.sh`:五本账各自运行,一本失败不影响其余;结束时把结果(含 FAILED.json)提交 git,任一失败则 macOS 通知 + 退出码 1(见 `paper/log/cron.log`)。
- 日历:`configs/holidays.csv` 只登记到 2026-10-07,**2027 年休市安排公告后必须补**,否则元旦当天会失败报警(这是设计:宁可报警也不静默跳日)。

## 三个月验收与配对差(2026-09-22 预注册,design_log 十八)
- 验收指标(2026-09-23 起算,2026-12-16 出报告):数据完整率 100%、成交率 ≥95%(按腿)、滑点校准只报告、每周对账差异为 0、至少一次故障恢复演练。
- 配对差:各 challenger 相对 champion(v0.3)的日收益差,报告年化均值、Newey–West SE、t、块 bootstrap 95% 区间;**不采用、不淘汰**;t < −3 且回撤差 > 10pp 连续两月可停账止损。
- 版本采用决定不早于 2027-09(配对差 SE 降到 ±0.65 需要 12 个月)。
- 语义断点:2026-09-22(含)之前的订单为旧口径,09-23 起为统一口径(手数带、T 收盘定手数、保证金真缩减、目标合约 = T+1 排程)。

## 验收与诊断命令(只读)
- 纸面验收(设计日志十八):`.venv/bin/python scripts/paper_acceptance.py --start 2026-09-23 --end 2026-12-15 [--strict]` → `results/paper_acceptance/*.csv`、`report/paper_acceptance_2026-12-15.md`(期末前为 PRELIMINARY)。故障演练证据放 `docs/drills/*.json`(格式见 `docs/drills/README.md`),否则报告显示 PENDING。协议清单 `configs/paper_protocol.yaml` 记录 champion/challenger、预期摘要与已声明的切换。
- 组合诊断:`.venv/bin/python scripts/portfolio_diagnostics.py [--skip-loo]` → `results/portfolio_diagnostics/*.csv`、`docs/research/portfolio_diagnostics.md`(逐品种净归因对账不过即失败)。
