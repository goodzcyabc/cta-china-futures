# 独立信息两条的文献与证据清单(2026-09-26;供 `docs/fundamental_signal_prereg.md` 引用)

> 用途:给两条候选(全市场持仓兴趣、PMI 订单/库存)提供**原始定义**与**证据边界**;不是"每篇论文做一个回测"的许可。检索由一名子任务完成(NBER / Liverpool / UCD 的 PDF 本地抽取;ScienceDirect、SSRN、spglobal.com 全部 403,S&P 内容来自 Wayback 快照),原文引语不超过 15 词。无法核实处逐条标出。

## A. 本次必须读

### A1. Hong & Yogo (2012), "What Does Futures Market Interest Tell Us about the Macroeconomy and Asset Prices?", *JFE* 105(3), 473–490
来源:NBER WP 16712(2011-01 版与 rev1),https://www.nber.org/papers/w16712 ;期刊版 DOI https://doi.org/10.1016/j.jfineco.2012.04.005 (付费墙,数字取自 NBER 版,rev1 差 ≈0.01)。

| 项 | 论文原定义(可核实处) | 备注 |
|---|---|---|
| 持仓量 | CFTC 逐市场持仓量(所有到期月合计),CRB 价格;30 个商品、4 个板块(农产品 14、能源 5、畜产品 5、金属 6) | "所有到期月合计"是 COT 数据的构造,非原文明说 |
| 美元持仓 | 每个商品:现货价 × 未平仓合约数;板块内求和 | 不含合约乘数(COT 每市场一种合约) |
| 增长率 | 每个板块的**月**增长率;全市场 = 四个板块增长率**等权平均**;因月增长噪声大,再取 **12 个月几何平均**(表题:"12-month geometrically averaged growth rate of commodity market interest") | 不是全市场总量的 12 个月增长;顺序:板块增长 → 板块等权 → 12 个月平滑。脚注 4 给出无现货价的替代:合约数增长 → 板块内中位数 → 板块等权,"非常相似" |
| 样本统计 | 1965:12–2008:12 均值 1.47%/月、标准差 2.06%、月自相关 0.90 | 表 4 |
| 回归 | 月频,x_t 预测 t+1 月;因变量 = 完全抵押商品期货组合的月超额收益(每商品对 1–13 个月到期的合约等权 → 板块内等权 → 板块间等权),减一月国库券 | 不是 GSCI、不是 CRB 现货 |
| 控制变量 | 短端利率、期限利差(Aaa − 短端)、商品基差、12 个月商品收益(动量)、商品市场失衡(商业交易者净空头占比)、芝加哥联储 CFNAI | |
| 结果 | 表 6:加入市场兴趣后系数 +0.73(t 2.50),即预测变量每 1 个标准差 → 下月期望收益 +0.73%;R² 2.58% → 4.96%;与动量赛马 0.77(1.85),与失衡 0.69(2.42),与 CFNAI 0.68(1.88) | 符号为正;作者解释为对未来供需信息的反应不足 |
| 时点 | "All predictor variables are lagged one month." | 月内何时观测持仓量:原文未说(COT 周二数据,未核实) |
| 交易规则 | **无**;只有预测回归,无择时组合、无夏普 | |
| 板块内检验 | 可获取文本中没有 | |

**对本项目的含义**:设计日志 4.2 的 `oi_growth`(单品种全部合约持仓 21 日对数增长、品种级时序信号)不是论文检验对象;其 IS/OOS 为负不能推出"全市场市场兴趣已被否定"(设计日志 4.2 附第 212 行已记录该差异)。本轮 A 臂按原定义做:板块内名义持仓求和 → 板块月增长 → 板块等权 → 12 个月几何平均 → 预测下月篮子收益;交易映射另行冻结(论文没有)。

### A2. Hollstein, Prokopczuk, Tharann & Wese Simen (2021), "Predictability in Commodity Markets: Evidence from More Than a Century", *J. Commodity Markets* 24, 100171
DOI https://doi.org/10.1016/j.jcomm.2021.100171 ;开放版 https://livrepository.liverpool.ac.uk/id/eprint/3166384 (作者接受稿 2021-01)。
- 30 个商品**现货**月末价 1871–2015,目标 = 单商品 1 个月超额收益(季节哑变量去季节);16 个预测变量 = Goyal–Welch 集合 + Δindpro、ΔM1、通胀、失业率;Δindpro/infl/unrate 滞后 1 个月处理公布延迟。
- 样本内:工业生产增长与通胀最强(Δindpro 对农产品几乎全部显著,能源仅 WTI,金属 6/9);平均 R² 0.2–1.9%。**符号在在线附录,可获取文本没有**(经济讨论暗示为正,只作推断)。
- 样本外(10 年滚动、Campbell–Thompson R²、Clark–West):单变量多数 R²_OOS 为负;均值组合 "comb" 在三个板块都为正(0.12/0.41/0.22),对 12 个商品显著;厨房水槽回归样本外很差。
- 含义:商业周期变量有信息,但**没有证明任何中国 PMI 交易规则**;它支持"用一个先验定义的变量、不做单变量筛选"。

### A3. Cotter, Eyiah-Donkor & Potì (2023), "Commodity Futures Return Predictability and Intertemporal Asset Pricing", *J. Commodity Markets* 31, 100289
DOI https://doi.org/10.1016/j.jcomm.2022.100289 ;读的是 UCD Geary WP2020/11(2020-11)。
- 目标 S&P GSCI 总收益超额,1976–2016,样本外 1990 起递推;28 个预测变量(基差、原油产量/库存、商品货币、股债、宏观、OECD 领先指标)。
- **方法意义**:16 种预测组合(简单均值/截尾/中位/Bates–Granger;DMSFE、ABMA、完整子集回归;主成分)。单个预测模型多数 R²_OOS 为负且 Giacomini–Rossi 检验在 1% 全部拒绝稳定;每个组合都为正(0.30%–4.96%)。作者把单模型的失败归于参数不稳定;预测力逆周期。
- 含义:**不要按单品种挑历史最优宏观变量**;单变量的样本外表现不稳定是常态。本轮每臂只允许一个预注册变量。

### A4. Ye 等(中国商品与宏观预期)
- Ye, Guo, Jiang, Liu, Deschamps (2019), *Finance Research Letters* 28, DOI https://doi.org/10.1016/j.frl.2018.04.011 :中国商品期货指数与中美宏观专业预测之间的非线性 Granger 因果;中国期货价格 Granger 导致对中国宏观的预测,而被对美国宏观的预测所导致。用的指数与调查来源:摘要未给(全文付费)。
- Ye, Guo, Deschamps, Jiang, Liu (2021), *Economic Modelling* 94, DOI https://doi.org/10.1016/j.econmod.2020.02.038 :15 个中国商品合约,GARCH-MIDAS 把月频宏观预测与日频波动结合;波动对宏观**预期**的反应强于对同期状况;改善波动预测并带来投资者经济收益;效应随经济状态变化。
- 含义:支持"中国商品期货与宏观预期有关",**没有证明** PMI 订单/库存比有可交易收益。

### A5. PMI 定义与公布时点
- S&P Global PMI FAQ(https://www.spglobal.com/market-intelligence/en/solutions/products/resources/pmi-faq ;Wayback 2026-01-29 快照):制造业 PMI = 五个扩散指数加权(新订单 30%、产出 25%、就业 20%、供应商交货 15% 逆向、采购库存 10%);扩散指数 = 上升% + 0.5 × 持平%,50 = 无变化。**FAQ 本身没有 orders-to-inventories 内容**。
- S&P Global 评论(Dennison,2024-12-11,"How to interpret and use the PMI Orders to Inventories ratio";Wayback 2025-07-26 快照):比率 = 季调新订单指数 **÷** 产成品库存指数(除法,不是差),中性值 1;>1 订单快于库存 → 未来产出偏强,<1 库存快于销售 → 减产/降价;作为产出与价格的前瞻指标(图示领先工业生产、GDP、PPI,无数值提前量)。
- 国家统计局制造业 PMI(https://www.stats.gov.cn/sj/zxfb/202608/t20260831_1965154.html 附注 4):13 个分类指数含 **新订单、产成品库存、原材料库存**(英文版 new order / finished goods inventory / raw materials inventory);权重 新订单 30%、生产 25%、从业人员 20%、供应商配送时间 15%(逆)、原材料库存 10%;季调;50% 为荣枯线。
- **公布时点**(页面时间戳与发布日程核实):当月**最后一个日历日**(含周末)09:00(至 2021-12-31)/ 09:30(2022-01-30 起);例外:2 月数据在 3 月初(2025-03-01;2026-03-04 因春节),2022-01 数据在 1 月 30 日。英文页时间戳晚一天,以中文页为准。中国商品日盘 09:00 开盘 → 月末交易日 **09:30 公布的值不能用于当日开盘**,只能用于下一交易日开盘(本项目按公布日之后第一个交易日开盘建仓)。米筐 `info_date` 与上述惯例一致(2016 年为次月 1 日,2018 年起为当月末日;2023-05 之前为回填记录,逐条不可独立核验)。

## B. 用于理解现有趋势因子为什么衰退(已在设计日志 七/7.1 精读;此处只列结论)
- Sepp & Lucic (2026) "The Science and Practice of Trend-Following Systems", arXiv:2607.19497:趋势收益 = 标准化收益自相关的加权和 + 漂移²;短记忆 alpha 扣成本是刀锋,长记忆撑净夏普;回看期与成本须一起分析。本项目 T1 诊断:2022 后 64–250 阶自相关转负(−0.27),趋势收益来自少数品种的漂移。
- Kurth, Eisler, Rej & Bouchaud (2026) "Is Trend Still Your Friend?", arXiv:2607.01550:波动率标准化 tick size 小的合约 2009 后快趋势失效。只作机制诊断;E2 跳价过滤(十一)已测不采用,不再授权门控策略。

## C. 次级候选与长期方向(本轮不测)
- Bianchi, Fan, Miffre & Zhang (2023) "Exploiting the Dynamics of Commodity Futures Curves", arXiv:2308.00383:C12 已登记;需要 ≥3–4 个活跃期限,中国多数品种不足;论文后期净收益弱;优先级低于 A/B。
- Dai 等 (2026) arXiv:2603.11408(WTI 多维 LLM 情绪)、Paredes Amorin 等 (2026) arXiv:2603.09085(铝价主题/事件条件情绪):文本信息可能有用(相关性、强度、不确定性、事实事件 vs 预测、新闻源差异),但本项目没有带历史时间戳、无幸存者偏差的新闻库;属于下一阶段数据工程,不能用价格数据伪造。

## D. 负面证据或只可借用方法(本轮关闭)
- Kosch & Forsberg (2026) "Seasonal Trading in Commodity Futures", arXiv:2609.12227:2016–2024 样本外含成本、18 个 Holm 校正检验无一显著优于等权做多 → 季节性因子及变体关闭。
- Cheng, Zhou & Liu (2025) "Large Language Models and Futures Price Factors in China", arXiv:2509.23609:单因子日频年化 749%–2213%、夏普 8–13,精读判断为时间对齐/同期相关问题;只借定义,不引数字。
- Li & Ferreira (2025) "Follow the Leader: Network Momentum", arXiv:2501.07135:证据弱、图参数与样本外选择有自由度;若测必须与板块/全市场平均动量对照;本轮不做。
- Zhai (2026) "Public Trader Identity", arXiv:2608.04373:市场不同,不可迁移;只借两种验证思想(评分跨窗口持续性、规模匹配安慰剂),已用于九/十的会员持仓因子(判死)。

## E. 无法核实清单
1. Hong–Yogo 期刊版数字(付费墙);持仓量是否跨到期月合计、月内观测时点。
2. Hollstein 等的 Δindpro/infl 系数符号(在线附录)。
3. Cotter 等读的是 2020 工作论文,非 2023 期刊版。
4. Ye 等 2019 用的指数与调查来源。
5. S&P 页面全部为 Wayback 快照;FAQ 无 orders-to-inventories 文本。
6. 统计局 09:00 → 09:30 的切换只由页面时间戳推断(最后一次 09:00 为 2021-12-31,首次 09:30 为 2022-01-30)。
