# 文档索引

2026-10-06 仓库整理过一次(经过见 [design_log.md](design_log.md) 第二十六节),**文件名都没改**。此前写成的文字(设计日志一至二十五、各预注册与结果、`report/archive/`)里的旧路径不改写,对照如下:

| 旧路径 | 现在 |
|---|---|
| `docs/<文件>` | `docs/research/<文件>` 或 `docs/data/<文件>`(design_log、architecture、deployment、drills 不变) |
| `scripts/<名>.py` | `scripts/research/<名>.py`(paper_daily.sh、paper_acceptance.py、portfolio_diagnostics.py、capital_scan.py、rqdata_export_options.py 不变) |
| `paper/`(当时指 v0.1 账本) | `paper/v01/`;现在的 `paper/` 是五本账的父目录 |
| `paper_v03/`、`paper_v03p/`、`paper_v01r/`、`paper_v05/` | `paper/v03/`、`paper/v03p/`、`paper/v01r/`、`paper/v05/` |
| `report/report_v0.1.2.md`、`report/report_v0.3.*`、`report/report_v0.4.*`、`report/yearly_v04.csv`、`report/paper_acceptance_record_2026-09-16_2026-09-22.md` 及旧图 | `report/archive/` 下同名 |
| `configs/exp_e1/e2/e3.yaml`、`strategy_v03r.yaml`、`strategy_v04_ew.yaml`、`strategy_v04_iv.yaml` | `configs/experiments/` 下同名 |

查改名前的历史用 `git log --follow -- <新路径>`。`configs/instruments.yaml` 的两行注释仍写旧路径 `docs/instruments_verification*.md`(现在在 `docs/data/`),纸面验收期(至 2026-12-15)内不改动这个文件。

| 文件 | 内容 |
|---|---|
| [design_log.md](design_log.md) | 设计日志:每一轮的预注册要点、全部试验(计数 60)、事后改动与更正;只追加,不改写 |
| [architecture.md](architecture.md) | 代码结构与关键约定 |
| [deployment.md](deployment.md) | 纸面交易运行手册:每日流程、失败语义与恢复 |
| [drills/](drills/) | 故障恢复演练证据(纸面验收程序读取) |

## research/ — 各轮研究(预注册 → 结果),按设计日志轮次

| 轮次(设计日志) | 主题 | 文件 |
|---|---|---|
| 四–六 | 11 个价格类因子:样本内筛选、组合、样本外、walk-forward | `factor_research_is.md`、`factor_research_oos_2026-06-05.md`、`factor_combo_is.md`、`factor_combo_oos_2026-06-05.md`、`factor_walkforward.md`、`factor_literature_check.json`(4.2 文献核对) |
| 七 | alphaXiv/arXiv 文献扫描;T1/T2 诊断(收益自相关、跳价) | `alphaxiv_survey_2026-09.md`、`diagnostics_acf_tick.md` |
| 九–十 | 新数据:会员持仓、仓单(选入仓单水平 → v0.3) | `factor_newdata_is.md`、`factor_newdata_oos_2026-06-05.md` |
| 十三 | 现货基差、外盘趋势溢出、监管事件覆盖层 | `factor_spotbasis_is.md`、`factor_global_is.md`、`factor_reg_is.md`、`factor_reg_oos_2026-06-05.md` |
| 十四 | 剔品种滚动检验;前视审计 | `prune_walkforward.md`、`lookahead_audit.md` |
| 十六 | 成交方式与调仓频率 | `exec_trials_is.md`、`exec_trials_oos_2026-06-03.md` |
| 十七 | 执行统一与官方结算价基线的逐级分解 | `settle_baseline.md` |
| 十八 | 纸面期组合诊断(只读工具输出) | `portfolio_diagnostics.md` |
| 十九 | 季度重选与 carry 开关(历史 walk-forward) | `walkforward_quarterly.md`、`quarterly_walkforward_prereg.md`、`quarterly_walkforward_diagnostic.md` |
| 二十 | 季度自适应 v1(真正的季度重训) | `adaptive_quarterly_v1_prereg.md`、`adaptive_quarterly_v1_report.md` |
| 二十一 | 全市场持仓兴趣、PMI 订单/库存 | `fundamental_signal_literature.md`、`fundamental_signal_prereg.md`、`fundamental_signal_diagnostic.md` |
| 二十二 | 另类数据五条:降雨、ENSO、新闻语调、上期所库存、钢城 PM2.5 | `altdata_prereg.md`、`altdata_diagnostic.md`(数据源目录见 `data/altdata_sources.md`) |
| 二十三 | 商品期权三条:偏度、方差风险溢价、去趋势 IV | `options_prereg.md`、`options_diagnostic.md` |
| 二十四 | 非量价因子说明书(仓单水平) | `non_pv_factor_card.md` |
| 二十五 | 多源基本面合成因子 MSF 演示 | `msf_prereg.md`、`msf_demo.md` |

## data/ — 数据源、合约参数核验、基线

| 文件 | 内容 |
|---|---|
| `data_notes.md` | 米筐导出的口径与坑 |
| `data_exchanges_shfe.md`、`data_exchanges_czce.md`、`data_exchanges_dce.md` | 各交易所直连抓取:URL、字段映射、口径切换、已知坑 |
| `data_exchange_params.md`、`data_exchange_events.md` | 交易所保证金/手续费/涨跌停参数与调参事件 |
| `data_global_futures.md` | 外盘期货数据与时间戳 |
| `altdata_sources.md` | 免费另类数据源侦察目录 |
| `instruments_verification*.md`、`instruments_verified*.json` | 合约参数逐项核验记录(`configs/instruments.yaml` 的出处) |
| `baselines.md`、`industry_baselines.md` | 南华商品指数、私募 CTA 产品与行业指数对照 |
