# 故障恢复演练证据(design_log 18.2 第 5 项)

验收程序 `scripts/paper_acceptance.py` 只认本目录下的结构化 JSON 证据;没有合格证据时报告显示 **PENDING**,不凭空判定通过。

每次演练一个文件 `YYYY-MM-DD_<简述>.json`,必需字段:

```json
{
  "date": "2026-10-08",
  "book": "paper_v03",
  "injected": "删除 data/exchanges/CZCE/quotes/2026/20261008.parquet 后运行 catchup",
  "detected": {"failed_json": true, "exit_code": 1, "notification": true, "stage": "settle"},
  "recovered": {"action": "恢复文件后 PYTHONPATH=src python3 -m cta.cli paper catchup --date 2026-10-08 --book paper_v03 --config configs/strategy_v03.yaml", "duration_s": 95},
  "outcome": "state.json 推进到 2026-10-08,equity.csv 无重复行,FAILED.json 自动清除,与未注入的重放逐字段一致",
  "operator": "s296he"
}
```

约束:演练只能在**账本副本**上做,或在真实账本上做后按手册恢复并留下 git 记录;证据里写明用的是哪一种。
