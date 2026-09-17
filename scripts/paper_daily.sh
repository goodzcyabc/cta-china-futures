#!/bin/bash
# 纸面交易每日入口:补跑到今天(北京时间当天;本机为多伦多时区,05:10 时北京已 17:10)。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p paper/log
TODAY=$(TZ=Asia/Shanghai date +%F)
echo "=== $(date '+%F %T') paper catchup to $TODAY"
PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY"
# 每日结果入库,形成不可篡改的时间戳(git 提交时间)
git add paper && git -c user.name=paper-bot -c user.email=paper@local commit -q -m "paper: $TODAY" || true
git push -q origin HEAD || true
