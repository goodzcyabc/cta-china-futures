"""交易所直连数据层:每日从各交易所官网拉取行情、会员持仓排名、仓单,按"当天看到的样子"落盘,永不覆盖。

目录:data/exchanges/<EXCH>/{raw,quotes,positions,receipts}/<YYYY>/<YYYYMMDD>.*
统一字段见 base.py;各交易所的抓取与解析在 shfe.py / ine.py / czce.py / dce.py;
ExchangeSource 把落盘数据装配成 DataSource 协议,与米筐导出可互换或拼接(StitchedSource)。
"""
