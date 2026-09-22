#!/bin/bash
# 纸面交易每日入口:补跑到今天(北京时间当天;本机为多伦多时区,05:10 时北京已 17:10)。
# 每本账独立运行:一本失败不影响其余账本;任一失败 → 仍写入 git(含 FAILED.json)、发桌面通知、非零退出。
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p paper/log
TODAY=$(TZ=Asia/Shanghai date +%F)
echo "=== $(date '+%F %T') paper catchup to $TODAY"
FAILED=""
run_book() {  # run_book <账本目录> [其余参数...]
  local book=$1; shift
  if ! PYTHONPATH=src python3 -m cta.cli paper catchup --date "$TODAY" --book "$book" "$@"; then
    FAILED="$FAILED $book"
    echo "!!! $book FAILED (see $book/FAILED.json)"
  fi
}
run_book paper                                                       # v0.1 主账本(拉当日交易所数据)
run_book paper_v03  --no-ingest --config configs/strategy_v03.yaml   # v0.3:+仓单水平(design_log 十)
run_book paper_v01r --no-ingest --config configs/strategy_v01r.yaml  # v0.1 + 监管事件覆盖层(13.6/13.7)
run_book paper_v05  --no-ingest --config configs/strategy_v05.yaml   # 工业品 12 品种(十五;事后假设)
run_book paper_v03p --no-ingest --config configs/strategy_v03p.yaml  # P1 剔除 5 品种(十四)
# 每日结果入库(含 FAILED.json),形成不可篡改的时间戳(git 提交时间)
MSG="paper: $TODAY"; [ -n "$FAILED" ] && MSG="$MSG (FAILED:$FAILED)"
git add paper paper_v03 paper_v03p paper_v01r paper_v05 || FAILED="$FAILED git-add"
if ! git diff --cached --quiet; then  # 有改动才提交;提交失败与推送失败都进告警链
  git -c user.name=paper-bot -c user.email=paper@local commit -q -m "$MSG" || FAILED="$FAILED git-commit"
fi
git push -q origin HEAD || FAILED="$FAILED git-push"
if [ -n "$FAILED" ]; then
  osascript -e "display notification \"$FAILED\" with title \"CTA 纸面账失败 $TODAY\"" 2>/dev/null || true
  echo "=== FAILED:$FAILED"
  exit 1
fi
echo "=== ok"
