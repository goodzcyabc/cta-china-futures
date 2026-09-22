#!/bin/bash
# 纸面交易每日入口:补跑到今天(北京时间当天;本机为多伦多时区,05:10 时北京已 17:10)。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p paper/log
TODAY=$(TZ=Asia/Shanghai date +%F)
echo "=== $(date '+%F %T') paper catchup to $TODAY"
PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY"
# 并行账本 v0.3(tsmom+carry+仓单水平;design_log 十):数据已由上一步拉好,不再拉
PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY" --no-ingest --config configs/strategy_v03.yaml --book paper_v03
# 并行账本 v0.1r(v0.1 + 监管事件覆盖层;design_log 13.6/13.7):事件由当日 params 机械推导
PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY" --no-ingest --config configs/strategy_v01r.yaml --book paper_v01r
# 并行账本 v0.3p(P1 剔除 5 品种;design_log 十四):作为"剔除亏钱品种"做法的前向检验
PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY" --no-ingest --config configs/strategy_v03p.yaml --book paper_v03p
# 每日结果入库,形成不可篡改的时间戳(git 提交时间)
git add paper paper_v03 paper_v03p paper_v01r && git -c user.name=paper-bot -c user.email=paper@local commit -q -m "paper: $TODAY" || true
git push -q origin HEAD || true
