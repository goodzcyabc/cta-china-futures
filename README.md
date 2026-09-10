# cta-china-futures

中国商品期货 CTA(趋势 + 展期收益)的合约级研究与实盘系统。目标是**同一条代码路径**从研究回测走到每日出单,
先做成可审查的 prototype,再在实盘环境中迭代。

- 架构与约定:`docs/architecture.md`
- 预注册与设计日志(任何看过结果后的改动都在这里):`docs/design_log.md`
- 数据:`data/ricecta/data`(米筐导出的合约级日线、主力映射、合约元数据;不随仓库分发)

```bash
pip install -e ".[dev]"
cta research                       # 研究回测 -> results/<config_digest>/
cta report results/<digest>        # 报告与图
cta live --asof 2026-06-05 --equity 50000000 --positions book.csv   # 次日目标手数与订单
pytest && ruff check src tests && mypy src
```
