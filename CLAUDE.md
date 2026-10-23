# CLAUDE.md

China commodity-futures CTA. Research backtest, daily orders and paper trading share **one code path**. Champion: v0.3 (time-series momentum + carry + exchange warehouse receipts). Docs and the design log are in Chinese; dates in them are Beijing time (`TZ=Asia/Shanghai date`). Start with `README.md` (method), `docs/README.md` (docs index), `docs/deployment.md` (operations), `TODO.md`.

## Commands

Run from the repo root: CLI defaults and many real-data test guards use cwd-relative `Path("data/...")` and silently skip elsewhere.

```bash
scripts/setup_env.sh                                   # once per checkout: .venv (Python 3.12, pinned requirements), src/ + research/ on path
.venv/bin/python -m cta.cli --help                     # research | live | report | paper
.venv/bin/python -m cta.cli research --config configs/strategy_v03.yaml
.venv/bin/python -m pytest                             # ~12 min with local data
.venv/bin/python -m pytest --ignore tests/test_paths_agree.py   # skip the ~9-min replay
.venv/bin/ruff format --check src research tests scripts download && .venv/bin/ruff check src research tests scripts download && .venv/bin/mypy src research/cta_research download
```

- No `pyproject.toml`; the project is not pip-installed (settings in `ruff.toml`, `mypy.ini`, `pytest.ini`). mypy is strict with `warn_unused_ignores`, so a stale `# type: ignore` fails CI.
- CI runs the same gates on Python 3.12. Only `data/benchmarks/` and `data/sample/` are tracked, so real-data tests skip in CI; `tests/test_sample_data.py` always runs on the public sample.
- Use `pytest -rs`: a run with skipped real-data tests proves nothing about data, signal or execution changes. In a new worktree, symlink `data/ricecta`, `data/exchanges`, `data/external` and `results` from the main checkout **one by one** (`ln -s <main>/data data` makes `data/data`), then run `scripts/setup_env.sh`.
- With local data, `research/tests/test_adaptive_quarterly.py` fails (not skips) without `results/quarterly_walkforward/equity_B_S3.csv`; reference checks in `research/tests/test_walkforward.py` and `test_fundamental_signals.py` skip without `results/settle_baseline/`.
- The suite is not side-effect free: it rebuilds `data/exchanges/<EX>/quotes_all.{parquet,stamp}` when stale and writes `data/exchanges/SHFE/reconcile_ricequant.json`; in a worktree these land in the main checkout's store through the symlink.
- No test runs `cta.cli` commands (tests only import it); smoke-check changes with `--help`.

## Layout (stage order; each folder has its own CLAUDE.md with the details)

| Stage | Folder |
|---|---|
| 1 data layer | `src/cta/data/` (sources, exchange store, `continuous/` roll) |
| 2 factor mining (research only) | `research/cta_research/factor_mining/` (candidates, research signals, evaluators); scripts in `research/scripts/` |
| 3 factor library (adopted factors) | `src/cta/factor_library/` |
| 4 factor combination | `src/cta/factor_combination/` |
| 5 execution | `src/cta/execution/` (`plan.py` sizing, `ledger.py` fills and marking, drivers `backtest/`, `live/`, `paper/`) |
| 6 analysis (read-only) | `src/cta/analysis/` |

- `src/cta/pipeline.py` wires 1 → 3 → 4 → 5. `src/cta/cli.py` is the entry point for research | live | report | paper and the only one the daily job uses (`-m cta.cli`); the exchange modules have their own `python -m` CLIs for backfill and reparse. `config.py` and `instruments/` (strategy config, contract specs) also stay at the top of `src/cta`.
- Production = `src/cta/` plus `scripts/*.py`. It never imports or names the research package, except `pipeline._extra_factors_of`, which lazily loads the MSF composite when a config weights `msf` (only the demo `configs/strategy_v06_msf.yaml`). `tests/test_boundaries.py` and `tests/test_stage_layout.py` enforce the boundary, the stage direction, every import path and the file-relative default paths.
- `research/cta_research/altdata/` holds the alternative-data pipelines; `research/cta_research/legacy/` the pre-2026-09-22 engine.
- Top-level `data/` is the gitignored data store (code is in `src/cta/data/`); top-level `paper/` holds the five books (code is in `src/cta/execution/paper/`).
- `download/` holds the rqdatac fetch scripts for the vendor export (idempotent, quota-guarded, resume by re-running; data lands in top-level `data/ricecta/data/`). Full table list and usage: `download/README.md`; source caveats: `docs/data/data_notes.md`. Running them needs a RiceQuant account in the runner's environment; nothing in the repo holds credentials. The export is committed to this repo, **including the 5-minute bars** (7,430 contracts, ~560 MiB); its caveats (zero-volume bars, CZCE `total_turnover`, repaired rows) plus the cleanliness tool `download/check_5m.py` are documented in `docs/data/data_notes.md`「5 分钟线」. The scripts are under the same ruff/mypy gates as `src`; `tests/test_download_scripts.py` covers the pure helpers.
- Paths before 2026-10-12 (e.g. `cta.signals.core`, `cta.backtest`, `cta_research.factors`) are mapped in `docs/README.md`.

## Rules that must not be broken

- **Acceptance window (2026-09-23 → 2026-12-15).** Do not edit the five paper-book configs or `configs/instruments.yaml`, and make no config-schema or default changes: `StrategyConfig.digest()` / `InstrumentTable.digest()` hash `model_dump()` including defaults, and the pins in `configs/paper_protocol.yaml` would stop matching (nothing blocks the daily job; drift only shows in the acceptance report). After touching config, instruments or dependency pins, recompute the five config digests and `load_instruments().digest()` and compare with the pins. Unknown YAML keys are silently ignored; `execution.fill` has no effect but is part of the digest (leave it). Add features by reusing an existing field (MSF uses a `signals.weights` key) or outside the config (`dominant_rule` lives on the data source); default them off. Also leave `configs/holidays.csv` alone until 2026-12-16: it is not pinned, yet adding 2027 holidays moves future maturities and roll signals (design log 30.3). Champion/challenger changes are the user's decision.
- **Pre-register first.** Commit `docs/research/<topic>_prereg.md` (`PREREG: …`) before computing any returns. Move preregs only with pure-rename commits (scripts find them via `git log --follow --diff-filter=A`). Results go only in the prereg's final "结果(运行后只追加)" section.
- **Record every trial** in `docs/design_log.md` (running count, currently 61) and log every post-hoc change there. Corrections are appended; never rewrite earlier text, preregs or `report/archive/`. Never pick windows, cuts or variants after seeing results; a factor whose sign comes out opposite to its preregistered direction is dropped, never flipped. Never call the reused 2022–2026 window clean out-of-sample.
- **Point-in-time.** Truncation tests (cut data at T; nothing ≤ T may change) are the real guard; include a Friday before a weekend release and a pre-holiday month end. New release-based factors must pass `target_rule="on_or_after"` explicitly to `cta_research.factor_mining.signals.fundamental_signals.releases_to_daily`: the default `"legacy"` books weekend releases on the previous Friday (night-session products then fill Friday 21:00, before publication) and only reproduces trials 50/51.
- **Out-of-sample monthly Sharpe:** start the slice at 2021-12-31, not 2022-01-04 (`perf_stats` drops the first month). Report v0.5 used the old slice (design log 二十七).
- **Timing.** Signals at T close; fills at the T+1 open, which for night-session products is calendar-T 21:00. Any data published after 15:00 must be checked against that.
- **Paper books and the daily job.** `scripts/paper_daily.sh` (launchd, 05:10 local time) commits whatever is staged and pushes `HEAD`: keep that checkout on `main` with nothing staged, do branch work in a worktree, never merge into it while the job runs, and recover failed days only there. Details in `src/cta/execution/paper/CLAUDE.md` and `docs/deployment.md`.
- **Research scripts and frozen evaluations.** See `research/cta_research/CLAUDE.md` (smoke modes that overwrite real outputs, hand-written text that reruns erase, frozen replays such as trial 61 at commit 5626548) and `research/cta_research/factor_mining/CLAUDE.md` (holdout gates, candidate_eval preconditions).
