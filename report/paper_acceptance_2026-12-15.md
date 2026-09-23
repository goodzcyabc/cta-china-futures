# 纸面交易验收报告(PRELIMINARY,截至 2026-09-22)

**PRELIMINARY —— 验收期 2026-09-23 → 2026-12-15 尚未结束,本报告截至 2026-09-22,只是阶段性结果。**

预注册规则:`docs/design_log.md` 十八;协议清单:`configs/paper_protocol.yaml`;champion = `paper_v03`,challenger = `paper`, `paper_v03p`, `paper_v01r`, `paper_v05`。**不选赢家,不采用、不淘汰任何版本。**

## 0. 摘要

| 账本 | 角色 | 有数据/预期交易日 | 成交率 | 逐日对账 | 失败记录 | 未声明漂移 |
|---|---|---|---|---|---|---|
| paper_v03 | champion | 0/0 | n/a | 一致 | 0 | 0 |
| paper | challenger | 0/0 | n/a | 一致 | 0 | 0 |
| paper_v03p | challenger | 0/0 | n/a | 一致 | 0 | 0 |
| paper_v01r | challenger | 0/0 | n/a | 一致 | 0 | 0 |
| paper_v05 | challenger | 0/0 | n/a | 一致 | 0 | 0 |

> 验收期从 2026-09-23 起算,账本最新日期为 2026-09-22:**验收期尚未产生任何数据**,下面各节为空是正常的;09-16 → 09-22 的记录期数据不计入验收(设计日志 18.2 第 6 条)。

预期交易日 = 周一至周五且不在 `configs/holidays.csv`,2026-09-23 → 2026-09-22 共 0 天。五本账共同有效日期:2026-09-16 → 2026-09-22(5 天)。

## 1. 数据完整率

| 账本 | 预期 | 有数据 | 完整率 | 缺失日期 |
|---|---|---|---|---|
| paper_v03 | 0 | 0 | nan% | — |
| paper | 0 | 0 | nan% | — |
| paper_v03p | 0 | 0 | nan% | — |
| paper_v01r | 0 | 0 | nan% | — |
| paper_v05 | 0 | 0 | nan% | — |

预注册阈值:验收期内每个交易日五本账都有权益行(FAILED 日在后续运行中修复重放算完整;最终仍缺失 → 不通过)。

## 2. 成交率(按腿)

| 账本 | filled | blocked | filled/(filled+blocked) |
|---|---|---|---|
| paper_v03 | 0 | 0 | n/a |
| paper | 0 | 0 | n/a |
| paper_v03p | 0 | 0 | n/a |
| paper_v01r | 0 | 0 | n/a |
| paper_v05 | 0 | 0 | n/a |

阈值 ≥ 95%。blocked 逐条:

(无)

## 3. 权益对账(账本语义:Δ权益 = Δ已实现 + 当日盯市 − Δ手续费;滑点已在成交价内,不再扣)

(验收期内无权益行)

## 4. 失败记录(FAILED.json 与日志)

(无)

## 5. 配置 / 参数表 / 代码 / 数据漂移(基于订单快照 config_digest、instruments_digest、git_sha、data_manifest)

(验收期内无快照变化)

默认只检测和报告,不阻止每日作业。协议清单声明的切换视为合法;未声明的策略配置/参数表/代码/数据版本变化需要解释。

## 6. 故障恢复演练证据

状态:**PENDING**(证据目录 `docs/drills/*.json`,必需字段 date, book, injected, detected, recovered, outcome;没有合格证据即 PENDING,不凭空判定通过)。


## 7. champion / challenger 配对差(预注册 18.3;只报告,不选择)

(验收期内尚无配对日期,无法计算)

## 8. 方法与参数

- 输出目录:`results/paper_acceptance`;协议清单:`configs/paper_protocol.yaml`;随机种子 20260923;bootstrap 2000 次、块长 10;NW lag 5;对账容差 1e-4 元。
- 本报告只读取 paper*/ 目录,不修改任何账本文件;不新增账本;不据结果采用或淘汰版本。
- 与回测的比较(18.4)留到验收期结束再做;本阶段共同日期 5 天。
