# cta-china-futures

中国商品期货 CTA(趋势 + 展期收益)的合约级研究与实盘系统。目标是**同一条代码路径**从研究回测走到每日出单,
先做成可审查的 prototype,再在实盘环境中迭代。

- 架构与约定:`docs/architecture.md`
- 预注册与设计日志(任何看过结果后的改动都在这里):`docs/design_log.md`
- 数据:`data/ricecta/data`(米筐导出的合约级日线、主力映射、合约元数据;不随仓库分发)
- **完整报告(v0.5,2026-10-06):`report/report_v0.5.md`**(PDF 同名):在 v0.4 基础上新增**非量价因子**一节(仓单水平说明书 + 多源基本面合成因子 MSF 演示)与二十至二十五轮研究(试验 47–60);基线数字、champion、纸面账不变。`report/report_v0.4.md`(2026-09-23)、`report/report_v0.3.md`(legacy)原样保留
- **非量价因子**:生产中的仓单水平 `docs/non_pv_factor_card.md`;多源合成因子(12 个非量价来源等权,默认关闭)`src/cta/factors/composite.py`、配置 `configs/strategy_v06_msf.yaml`、预注册 `docs/msf_prereg.md`、结果 `docs/msf_demo.md`;试跑 `cta research --config configs/strategy_v06_msf.yaml`(需要 `data/external/alt/` 下的另类数据,见 `docs/altdata_sources.md`)
- 另类数据与期权管道(点时、带原始文件与时间戳):`src/cta/data/alt/`;结果 `docs/altdata_diagnostic.md`、`docs/options_diagnostic.md`、`docs/fundamental_signal_diagnostic.md`
- 早期回测报告(v0.1.2):`report/report_v0.1.2.md`
- 资金规模扫描(100–500 万):`scripts/capital_scan.py` → `report/capital_scan.md`
- 行业基线对照(洛书拾壹号、南华商品指数):`docs/baselines.md`
- 合约参数核验记录:`docs/instruments_verification.md`
- 文献扫描(alphaXiv/arXiv,2026-09):`docs/alphaxiv_survey_2026-09.md`(7 篇精读、C9–C13 登记、两项诊断 T1/T2)
- 因子研究(v0.2):因子库 `src/cta/factors/`(11 个预注册候选 + 统一评估/IC/Deflated Sharpe),脚本 `scripts/factor_screen.py`(样本内默认,样本外需显式确认)、`factor_combo.py`、`factor_walkforward.py`;结果 `docs/factor_research_is.md`、`docs/factor_research_oos_2026-06-05.md`、`docs/factor_combo_*.md`、`docs/factor_walkforward.md`;规则与结论在 `docs/design_log.md` 四–六

```bash
pip install -e ".[dev]"
cta research                       # 研究回测 -> results/<config_digest>_<instruments_digest>/
cta report results/<config_digest>_<instruments_digest>        # 报告与图
cta live --asof 2026-06-05 --equity 3000000 --positions book.csv   # 次日目标手数与订单
pytest && ruff check src tests && mypy src
```
