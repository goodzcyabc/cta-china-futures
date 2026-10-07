#!/bin/bash
# 从四家交易所官网回填公开日数据到 data/exchanges/(复现正式基线所需的全部行情与仓单;不需要米筐)。
# 用法:scripts/fetch_exchange_data.sh [开始日 2016-01-04] [结束日 最近一个已公布日] [类别 quotes,receipts]
# 结束日默认:北京时间 17:00 之后取北京今天,否则取北京昨天(交易所当天的结算数据下午才公布;郑商所、大商所的回填会把
# 抓不到的日子记入 missing.log,之后要加 --retry-missing 才会重试,所以不要回填尚未公布的日子)。
# 可断点续跑:已落盘的日期跳过;交易所确认无数据的日期记入各所 missing.log。全量四所两类合计约两万次逐日请求(各所请求间隔 ≥1 秒),估计几个小时。
# 上期所、上海国际能源中心、郑商所直连即可(郑商所逐日抓 .txt,不用有反爬的年度打包;2016、2019 抽查与年度打包解析结果逐行相同)。
# 大商所全站有反爬(412 + JS 挑战),需要本机 Chrome 开远程调试并运行 CDP 代理(http://localhost:3456,
# 见 docs/data/data_exchanges_dce.md 第 2 节);没有代理时只有大商所这一步失败,其余不受影响。
# 拉完后:python -m cta.cli research --config configs/strategy_v03.yaml --source exchange --dominant-rule oi_1.1x
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
if [ ! -x "$PY" ]; then echo "$PY not found -- run scripts/setup_env.sh first"; exit 1; fi
LAST=$("$PY" -c "
import datetime as d, zoneinfo as z
now = d.datetime.now(z.ZoneInfo('Asia/Shanghai'))
print(now.date() if now.hour >= 17 else now.date() - d.timedelta(days=1))")
START=${1:-2016-01-04}
END=${2:-$LAST}
KINDS=${3:-quotes,receipts}
INE_START=$START
if [[ "$INE_START" < "2018-03-26" ]]; then INE_START=2018-03-26; fi  # 原油期货上市日,之前没有数据
FAILED=""
run() {  # run <名称> <模块> <参数...>
  local name=$1 mod=$2; shift 2
  echo "=== $name $(date '+%T')"
  "$PY" -m "$mod" "$@" || FAILED="$FAILED $name"
}
run SHFE cta.data.exchanges.shfe backfill --start "$START" --end "$END" --kinds "$KINDS"
run INE  cta.data.exchanges.ine  backfill --start "$INE_START" --end "$END" --kinds "$KINDS"
run CZCE cta.data.exchanges.czce backfill --start "$START" --end "$END" --kinds "$KINDS" --no-annual
run DCE  cta.data.exchanges.dce  backfill --start "$START" --end "$END" --kinds "$KINDS"
# 各所命令行在个别日期抓取失败时仍返回 0:看上面每所的统计(error 计数)与 data/exchanges/<所>/missing.log
if [ -n "$FAILED" ]; then echo "=== FAILED:$FAILED (rerun to resume)"; exit 1; fi
echo "=== done (check per-exchange error counts above)"
