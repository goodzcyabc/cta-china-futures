"""另类数据管道(预注册 docs/altdata_prereg.md):每个来源一个模块,提供
fetch(dest, start, end) -> None(幂等、可续传,原始文件与 HTTP Last-Modified 一起落盘)与
load(dest) -> pd.DataFrame(标准观测表:obs_date, available_day, key, value, 以及来源特有的 meta 列)。
可得日 available_day 按预注册各节的规则计算;信号构造在 cta.analysis.altdata_signals。"""
