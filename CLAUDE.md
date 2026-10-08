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
.venv/bin/ruff format --check src research tests scripts && .venv/bin/ruff check src research tests scripts && .venv/bin/mypy src research/cta_research
```

- No `pyproject.toml`; the project is not pip-installed (settings in `ruff.toml`, `mypy.ini`, `pytest.ini`). mypy is strict with `warn_unused_ignores`, so a stale `# type: ignore` fails CI.
- CI runs the same gates on Python 3.12. Only `data/benchmarks/` and `data/sample/` are tracked, so real-data tests skip in CI; `tests/test_sample_data.py` always runs on the public sample.
- Use `pytest -rs`: a run with skipped real-data tests proves nothing about data, signal or execution changes. In a new worktree, symlink `data/ricecta`, `data/exchanges`, `data/external` and `results` from the main checkout **one by one** (`ln -s <main>/data data` makes `data/data`), then run `scripts/setup_env.sh`.
- With local data, `research/tests/test_adaptive_quarterly.py` fails (not skips) without `results/quarterly_walkforward/equity_B_S3.csv`; reference checks in `research/tests/test_walkforward.py` and `test_fundamental_signals.py` skip without `results/settle_baseline/`.
- The suite is not side-effect free: it rebuilds `data/exchanges/<EX>/quotes_all.{parquet,stamp}` when stale and writes `data/exchanges/SHFE/reconcile_ricequant.json`; in a worktree these land in the main checkout's store through the symlink.
- No test runs `cta.cli` commands (`tests/test_boundaries.py` only imports it); smoke-check changes with `--help`.

## Layout

- Production = `src/cta/` plus `scripts/*.py` (everything the paper job, order generation and ops scripts use). Research = `research/`: `cta_research`, per-round `research/scripts/`, `research/tests/`.
- Production never imports or names `cta_research`, except `cta.pipeline._extra_factors_of` lazily loading `cta_research.factors.composite` when a config weights `msf` (only the demo `configs/strategy_v06_msf.yaml`). `tests/test_boundaries.py` fails on any other import, and on any mention of the name outside `cta/pipeline.py`.
- Flow: data source → `continuous/roll.py` panels → `signals/core.py` → `execution/` (shared by `backtest/engine.py`, `live/orders.py`, `paper/`). `tests/test_paths_agree.py` checks on 29 real days (2025-03-03 → 04-11) that the engine and an as-of loop (`generate_orders` → `ledger.execute_day` → `ledger.mark`) hold identical lots and equity; it does not run `PaperBook`/`paper/runner.py`.

## Data

- `--source stitched` (default): vendor export `data/ricecta/data` (proprietary, never commit) up to 2026-06-05, exchange store `data/exchanges/` after. Official settlement prices, receipts and regulatory events come only from the exchange store. With `data.settle: official` (default, every shipped config) a held contract-day without an official settle raises in `build_panels`; only the legacy `vendor_close` uses close. So `--source ricequant` fails for every shipped config.
- `--exchange-root` and `--dominant-rule` apply only to `--source exchange` (stitched ignores `--exchange-root`; other sources reject a non-default `--dominant-rule`). The default rule `max_oi` is what the paper books use after 2026-06-05; with it v0.3 has monthly Sharpe 0.89 against the 1.06 baseline (2017-01-11 → 2026-06-05); `oi_1.1x` approximates the vendor dominant table and gives 1.07 (`docs/research/source_check.md`). Do not change the paper books' rule during the acceptance window.
- The exchange store is append-only (`Store.write_day` refuses to overwrite). After a parser fix, re-parse from raw (`czce/dce reparse`, `backfill --overwrite` for shfe/ine/params). Local CZCE quotes for 2016–2025 came from annual zips without per-day raw files, so `czce reparse` skips them; re-ingest with `czce.ingest_annual(year, overwrite=True)`. Then delete `quotes_all.{parquet,stamp}` (its stamp does not notice a reparse).
- `scripts/fetch_exchange_data.sh` backfills quotes and receipts (enough for the v0.3 baseline). Params, which regulatory events and `paper/v01r` need, come from `python -m cta.data.exchanges.params backfill`; positions need the `kinds` argument.
- DCE is fetched through the local Chrome DevTools proxy (`localhost:3456`, from the web-access skill). Never try to defeat its anti-bot challenge another way.
- Only the paper runner refuses today's data before 16:30 Beijing (`settlement_published`); the per-exchange CLIs have no time guard, so never run them for today's Beijing date before 16:30. Raw downloads are cached in `data/exchanges/<EX>/raw/<kind>/<year>/<YYYYMMDD>.*.gz` and every later ingest re-parses the cache (`--overwrite` included): an early snapshot is fixed only by deleting that raw file (and any parquet written), then re-ingesting. Empty settlements: SHFE/INE quotes fill isolated gaps but raise `NotFinalError` (and delete their raw) above 5% of traded contracts; DCE quotes fail validation on any; CZCE drops those rows and writes the rest.

## Timing and execution rules

- Signals at T close; fills at the T+1 open, which for night-session products is calendar-T 21:00. Any data published after 15:00 must be checked against that.
- Rolls: switch only after the dominant candidate holds 3 days, forward in maturity only; two legs fill together or not at all. Unfilled targets are not carried over.
- `adj_close` is ratio back-adjusted: every later roll rescales its whole history, so compare returns, never levels (including in truncation and cross-source checks). It feeds signals, vol estimates and vol targeting. Lots are sized from the T close of the contract held on T+1 (`sched_next`); fills, PnL, margin and limits use real contract prices.

## Paper trading

- Five books, each tied to one config: `paper/v01`→`strategy.yaml` (only book that ingests data; runs first), `paper/v03`→`strategy_v03.yaml` (champion), `paper/v03p`, `paper/v01r`, `paper/v05` → `strategy_v03p/v01r/v05.yaml`. The CLI does not check the pairing: always pass `--book` with its `--config`.
- Never hand-edit `state.json`; a settled day cannot be recomputed. A failed step writes `FAILED.json` and leaves state unchanged; rerunning `catchup` is idempotent. Side-effect-free check: `paper step --date <settled day> --no-ingest --book … --config …` → "already settled".
- A `--book` without `state.json` is refused unless `--init` (otherwise a fresh 3M book would be created). Never point `--book` at `paper/` or `paper/log/`.
- `scripts/paper_daily.sh` (launchd, `deploy/com.cta.paper.plist`, 05:10 local time) uses `.venv/bin/python`, commits **whatever is staged** and pushes `HEAD`. Keep that checkout on `main` with nothing staged, do branch work in a worktree, and never merge into it while the job runs.
- DCE fetch timeouts (2026-09-23, 10-08; on 10-08 the proxy was not attached to Chrome) fail every book holding DCE contracts at `settle`. Recover only in the launchd checkout, never from a worktree (the script would advance the worktree's copy of the books and push the branch): see `docs/deployment.md`, 失败语义与恢复.
- Trading days are Mon–Fri minus `configs/holidays.csv`; an unlisted holiday fails the step by design. Add each year's holidays when announced.

## Rules that must not be broken

- **Acceptance window (2026-09-23 → 2026-12-15).** Do not edit the five paper-book configs or `configs/instruments.yaml`, and make no config-schema or default changes: `StrategyConfig.digest()` / `InstrumentTable.digest()` hash `model_dump()` including defaults, and the pins in `configs/paper_protocol.yaml` would stop matching (nothing blocks the daily job; drift only shows in the acceptance report). After touching config, instruments or dependency pins, recompute the five config digests and `load_instruments().digest()` and compare with the pins. Unknown YAML keys are silently ignored; `execution.fill` has no effect but is part of the digest (leave it). Add features by reusing an existing field (MSF uses a `signals.weights` key) or outside the config (`dominant_rule` lives on the data source); default them off. Champion/challenger changes are the user's decision.
- **Pre-register first.** Commit `docs/research/<topic>_prereg.md` (`PREREG: …`) before computing any returns. Move preregs only with pure-rename commits (scripts find them via `git log --follow --diff-filter=A`). Results go only in the prereg's final "结果(运行后只追加)" section.
- **Record every trial** in `docs/design_log.md` (running count, currently 60) and log every post-hoc change there. Corrections are appended; never rewrite earlier text, preregs or `report/archive/`. Never pick windows, cuts or variants after seeing results; a factor whose sign comes out opposite to its preregistered direction is dropped, never flipped. Never call the reused 2022–2026 window clean out-of-sample.
- **Point-in-time.** Truncation tests (cut data at T; nothing ≤ T may change) are the real guard; include a Friday before a weekend release and a pre-holiday month end. New release-based factors must pass `target_rule="on_or_after"` explicitly to `cta_research.signals.fundamental_signals.releases_to_daily`: the default `"legacy"` books weekend releases on the previous Friday (night-session products then fill Friday 21:00, before publication) and only reproduces trials 50/51.
- **Out-of-sample monthly Sharpe:** start the slice at 2021-12-31, not 2022-01-04 (`perf_stats` drops the first month). Report v0.5 used the old slice (design log 二十七).
- **Research scripts.**
  - Only `factor_{screen,combo,newdata,reg,global,spotbasis}.py` and `exec_trials.py` gate the holdout behind `--confirm-holdout`; every other script, `factor_walkforward.py` included, runs into the 2022–2026 window, and full runs of the newer diagnostics count as trials.
  - `quarterly_walkforward_diagnostic.py` and `adaptive_quarterly_v1.py` default to `--mode smoke`, which writes the same default `results/` and `docs/research/` outputs as full (a bare run replaces `equity_B_S3.csv` with a 2022Q1–Q2 stub); `altdata/options/fundamental_signal_diagnostic.py` take `--smoke`. Pass scratch output paths for smoke runs.
  - Hand-written text survives a rerun only inside `<!-- narrative-top/bottom -->` (the altdata/fundamental_signal/options diagnostics, `adaptive_quarterly_v1.py`) or `<!-- human:start/end -->` (`msf_demo.py`); every other generator rewrites its whole doc.
  - `candidate_eval` stores the reference-equity match in `baseline_matches_reference` without raising: stop on False yourself, and treat None (reference CSV in `results/settle_baseline/` missing, so not checked) as a failed precondition.
