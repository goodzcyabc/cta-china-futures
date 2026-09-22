# cta-china-futures

中国商品期货 CTA(趋势 + 展期收益)的合约级研究与实盘系统。目标是**同一条代码路径**从研究回测走到每日出单,
先做成可审查的 prototype,再在实盘环境中迭代。

- 架构与约定:`docs/architecture.md`
- 预注册与设计日志(任何看过结果后的改动都在这里):`docs/design_log.md`
- 数据:`data/ricecta/data`(米筐导出的合约级日线、主力映射、合约元数据;不随仓库分发)
- **完整报告(v0.3 主线,2026-09-22):`report/report_v0.3.md`**(系统、数据、策略、五个版本回测、44 次试验、板块与执行层诊断、前视审计、五本纸面账、诚实结论)
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
