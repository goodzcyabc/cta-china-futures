"""研究代码:候选因子的构造、筛选与评价(不参与出单;生产代码在 src/cta)。

factors    因子库、标准化、快速评估;多源合成因子 MSF(composite,经 cta.pipeline 的可选接口接入)
signals    基本面/另类数据/期权信号的点时构造
evaluation 三臂候选评价、walk-forward、季度自适应
altdata    另类数据抓取与标准观测表
legacy     冻结的旧引擎(只用于复现旧报告口径)
"""
