# TODO / 路线图(2026-10-06 更新)

接下来要做的事、为什么做、怎么判断有没有用。所有新研究沿用本项目的规则:

- 先写预注册(定义、方向、评价口径、采用规则)并提交,再算收益;
- 每个候选计 1 次试验(当前累计 60 次);
- 用同一个引擎和真实成本,对照 champion v0.3;
- 2016–2026 的数据已经被反复使用,不再算干净的样本外,真正的证据来自纸面期(2026-09-16 起)。

## 0. 正在进行

- [ ] **纸面期工程验收**:五本纸面账每日自动运行,2026-12-16 出验收报告。验收内容包括数据完整率、按腿成交率 ≥ 95%、滑点校准、每周对账,以及至少一次故障恢复演练。版本采用决定不早于 2027-09。
- [ ] **运维**:
  - 交易日历改为读取 `configs/holidays.csv`;
  - 补 2027 年休市日历(交易所通常 11–12 月公布);
  - 仓单抓取挪到夜盘前,避开 17:10 时少数日子还未公布的情况。
- [ ] **数据**:大商所数据抓取摆脱对本机浏览器的依赖。

## 1. 论文复现

按本项目的引擎、真实成本和点时规则复现,从计算最便宜的开始。论文里的数字是作者在海外期货上自报的,大多不含成本。

| | 论文 | 核心做法 | 本项目怎么做 |
|---|---|---|---|
| A | Lim, Zohren & Roberts (2019). *Enhancing Time-Series Momentum Strategies Using Deep Neural Networks.* Journal of Financial Data Science 1(4). [arXiv:1904.04912](https://arxiv.org/abs/1904.04912) | LSTM 直接输出仓位 [−1, 1],以夏普比率作损失函数(Deep Momentum Network);原文在 88 个海外期货上检验 | 22 个品种合并训练,按年扩展窗口重训,损失函数扣除每个品种的真实手续费与滑点;输出接入现有波动率目标与执行层,对照 v0.3。中国期货上已有同类研究(Liu, Mirza, You & Zhan, *Annals of Operations Research*, 2024, [doi:10.1007/s10479-024-06277-x](https://doi.org/10.1007/s10479-024-06277-x)),这里是在更严格条件下复现,不算新发现。CPU 即可 |
| B | Wood, Roberts & Zohren (2022). *Slow Momentum with Fast Reversion: A Trading Strategy Using Deep Learning and Changepoint Detection.* Journal of Financial Data Science 4(1). [arXiv:2105.13727](https://arxiv.org/abs/2105.13727) | 用高斯过程在线检测趋势拐点,把拐点强度与位置作为特征 | 先把"拐点强度"单独当作一个因子,用现有三臂评价检验(1 次试验);过线再并入 A |
| C | Wood, Giegerich, Roberts & Zohren (2021). *Trading with the Momentum Transformer: An Intelligent and Interpretable Architecture.* [arXiv:2112.08534](https://arxiv.org/abs/2112.08534) | 用注意力机制处理一年的日频序列 | 论文 2015–2020 年的全资产组合夏普在单边成本 2.5–3 bp 时转负(只交易其中 25 个商品期货时,3 bp 下仍为 1.23);本项目 1 跳滑点折合 0.7–8.9 bp(另加手续费),所以成本建模决定成败。需要 GPU,见第 3 节 |

另有项目已登记、只能用 2026-06 之后新数据检验的候选,按同样规则排队:设计日志 6.1 的 C1 趋势 sleeve(样本内已按 5.1 规则被否,只差新数据)、C2、C4;七 的 C9、C11–C13;13.4 的 C14、C15;15.6 的 C16。已检验并关闭的不再排队(C3、C10 成本版、仓单 21 日变化 H-REC)。仓单变化率的其他窗口、同比、分板块变体与 H-REC 同族,要测须先写预注册、按新增试验计数、只用新数据。

## 2. 大规模特征搜索

**目标**:把已有数据用一套预先写定的算子语法批量生成候选特征,代替逐个手工设计。数据包括价格/成交/持仓、仓单、天气、ENSO、新闻语调、空气质量、期权隐含波动率和宏观指标。

**生成方法**:
- 算子写法参考 Kakushadze (2016) *101 Formulaic Alphas*(Wilmott 2016(84),[arXiv:1601.00991](https://arxiv.org/abs/1601.00991));
- 生成器参考 AlphaGen:Yu 等 (2023) *Generating Synergistic Formulaic Alpha Collections via Reinforcement Learning*(KDD '23,[arXiv:2306.12964](https://arxiv.org/abs/2306.12964))。它用强化学习生成公式,奖励是对已有因子组合的增量,不是单个因子好不好看。

**防止自欺**。批量搜索一定能找到"好看"的假因子,所以下列规则先写死:
1. 搜索空间提交后才运行,候选总数 N 全部计入试验数,不只算留下来的。
2. 单因子 t 值门槛 3.0,不用 2.0(Harvey, Liu & Zhu 2016, *…and the Cross-Section of Expected Returns*, Review of Financial Studies 29(1))。
3. 嵌套 walk-forward:每个训练窗口内用固定的选择规则,只记录外层样本外的结果。
4. 对整个候选家族做检验:
   - 相对 champion 的 SPA 检验(Hansen 2005, Journal of Business & Economic Statistics 23(4));
   - 按全部 N 计算的 Deflated Sharpe(Bailey & López de Prado 2014, Journal of Portfolio Management 40(5),项目里已实现);
   - 回测过拟合概率 PBO(Bailey, Borwein, López de Prado & Zhu 2017, Journal of Computational Finance 20(4))。
5. 通过的候选进入注册日之后的纸面期检验;没通过的也计入试验数并留档。

**预期**:免费数据上已有 10 条信号全部是 Noise,所以批量搜索大概率只会留下很少的候选。它的价值在于同时做到"搜得多"和"不自欺"。CPU 即可。

## 3. GPU 实验项目

- **模型对照**:在 22 个中国商品期货上跑 Momentum Transformer(上面 C)和其他深度模型。用多随机种子集成、按年滚动重训、真实成本。比较协议参考同一组作者的大规模基准 Saly-Kaufmann, Wood, Calliess & Zohren (2026), *Deep Learning for Financial Time Series: A Large-Scale Benchmark of Risk-Adjusted Performance*([arXiv:2603.01820](https://arxiv.org/abs/2603.01820),预印本)。该文中 LSTM 版本的毛夏普从 2010–15 年的 1.83 降到 2020–25 年的 1.07,衰减是否同样发生在中国数据上,正是要检验的。
- **迁移学习**:参考 Wood, Kessler, Roberts & Zohren (2024) *Few-Shot Learning Patterns in Financial Time Series for Trend-Following Strategies*(Journal of Financial Data Science 6(2),[arXiv:2310.10500](https://arxiv.org/abs/2310.10500))。先在海外长历史期货上预训练,再对中国品种做少样本或零样本交易,需要外部长历史期货数据。
- **中文文本**:如果拿到带历史时间戳的新闻全文,用大语言模型抽取品种层面的供需事件与情绪。免费的 GDELT 新闻语调已检验过,结果是 Noise;瓶颈在数据,不在模型。
- 判据同上:预注册、计入试验数、对照 champion、用纸面期验证。

## 4. 数据(决定上限的部分)

- **付费产业链数据**(开工率、社会库存、表观需求):本项目的结论是免费数据已经挖尽,下一步有效信息主要来自这里,需要先解决来源与成本。
- **带时间戳的中文新闻全文库**。
- **大商所期权 2025–2026**:目前只能经浏览器或米筐导出。

## 已完成

见 [`report/report_v0.5.md`](report/report_v0.5.md) 与 [`docs/README.md`](docs/README.md):
- 数据到出单同一条代码路径、交易所直连数据、合约级引擎、五本纸面账;
- 60 次预注册试验,包括价格因子、重训、另类数据、商品期权、多源合成因子;
- 非量价因子(交易所仓单水平)已在 champion 里运行。
