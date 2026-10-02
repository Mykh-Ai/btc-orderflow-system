# Executor LLM Market Monitor single canonical path — evidence audit

Date: 2026-09-20
Target: `Mykh-Ai/btc-orderflow-system`, local `D:\Project_V\Executor`, branch `v2.0` at `7921d22427cde964d112175d874d43165db01d44` before task changes.
Decision: `ADR-LLM-Market-Monitor-Single-Canonical-Path.md`.
Status: `BLOCKED_BY_TEST_FAILURE`. No production change, merge, push, or LLM call was made.

## Phase 1: routing and provenance

The evidence audit ran `git status`, `git log --oneline -n 30`, all four requested `git log -p -S` queries, `git blame`, numbered source inspection, and `rg -n`. The local v2.0 checkout had pre-existing edits to `AGENTS.md` and `LOG.md`, plus untracked research files; these were not modified for this task. The other `btc-orderflow-system` checkout is on `codex/scout-replay-backtester-v0-1` with unrelated dirty work. This task edits only the v2.0 checkout.

- `71696ef` introduced `_resolve_market_monitor_current_feed_path` and the v1 route. `ae10ace`/`9825123` introduced the opt-in v39A builder; `aad153a` reconciled it into modular `v2.0`. `LOG.md` records the September 11 v39A deployment smoke, 58 targeted passes, and continuous state.
- Before: `executor.py` builds `ENV`, then calls `llm_trade_judge.configure(ENV)`. Its `ENV` contains `LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED`, current/context feed paths, and max zones, but **omits `LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED`**. `configure` replaces the module's own `ENV`, so the live `true` v39A container variable cannot reach the routing check. The snapshot flag can also suppress the monitor entirely. This is a code-confirmed route to v1; it does not prove when or why the September 11 to 14 production drift occurred.
- Before graph: enabled Judge -> snapshot/v39A flag check -> cutoff-day `current_feed` via `_resolve_market_monitor_current_feed_path` -> v1 builder -> optional v39A wrapper when the v39A flag survives configuration -> `build_entry_snapshot` -> `build_entry_prompt` -> model. v1's 15/60/240 local windows, market state, market structure state, local registry, and local inventory use cutoff-day `current`. Broad context and inventory use continuous `context_feed`.
- `executor_mod/entry_snapshot.py` accepted missing or error monitor input as a quality gap and copied any monitor schema into the model-facing V2 entry snapshot. It did not reject v1. `maybe_record_llm_pretrade_judge` could still make a real model call.
- Production Compose exists on the server, not in this v2.0 checkout. Its executor service uses `/root/volume-alert/.executor.env`; it mounts `/opt/aitrader_data/feed` at `/opt/aitrader/feed`, and bind mounts `market_monitor`, `executor.py`, and `executor_mod` into `/app`. Local `LOG.md` and immutable parity evidence contain historical switch/config references. No tracked local deployment script or example ENV file was found in this checkout.
- Existing tests explicitly expected flag-off monitor omission, cutoff-day feed resolution, and v1 error schema. They were updated to assert the canonical input contract. One old prompt-content test remains unchanged and failing, as detailed below.

## Phase 2: historical and current production evidence

The copied durable journal evidence under `D:\Project_V\Aitrader\tmp_llm_last_two_evidence\artifacts` contains the stored September 14 `LLM_ENTRY_SNAPSHOT_V2`; its lineage says `market_monitor_snapshot_v1`. The stored 240m window has `rows_used=133`, `expected_minutes=240`, and `start_timestamp=2026-09-14T00:00:00Z`. The read-only in-container replay reproduced its old 240m delta, delta percentage, OI change, market state, structure state, support/resistance, and conflict fields exactly. The August 31 durable evidence is an older v1 pack without a stored V2 entry snapshot or literal prompt; no V2 artifact was invented.

At audit time, production container `executor` was the only container matching executor, ID `55867f63b68b`, image `sha256:4b619faba1f496b8584b4535c7155b39fd2c11ade9cd8fb2bc66ad1491430589`, created `2026-09-19T18:23:07Z`, running. Selected container ENV was: Judge enabled `true`; context and current feed both `/opt/aitrader/feed`; snapshot and v39A flags both `true`; state path `/data/state/market_monitor_state_v39a.json`. These are current container facts, not proof that Python's replaced `ENV` retained the v39A flag.

Current in-container SHA-256 baselines: `executor.py` `ef2fc73486f16f18045391a51b60a90ed767cce8eef19a991ad42fba01881e18`; `executor_mod/llm_trade_judge.py` `15a4657fb5aedf67427698ebfb8697f9e609829a559e031a8a8f791f9ab70d1d`; `entry_snapshot.py` `9c0fed77884aef8e76917e76b540b929012cfc760c79cda993fcb37f83ea9682`; `market_monitor_snapshot_v39a.py` `f10cb65d3e4df0d8ae841cdbf641b50461904583a943bbc164d1e49c3caded0c`; `market_monitor/snapshot_builder.py` `5d62e1ac5479e3a4834e4c18aec7e0099abfa94c63b66b685fd2a44063bdd2b1`; `market_monitor/feed_adapter.py` `a5eed604faae856aa1a82bee0b3bdbce0023832f7e23e6359ed97555ab538dfd`. Compose hash: `c606cab260d1aa138ca1e3d20bc960655d09dd1eac90f04127ae26a5aed96beb`.

## Before and proposed after

After the local edit: enabled Judge -> continuous context feed (required) -> six exact window preflight -> v1 internal state/zone helper on a complete continuous 1440-minute slice -> v39A builder -> strict V2 entry/prompt validation -> model. Both old enable flags and the current-feed key are parsed for compatibility but ignored for routing. Missing/duplicate required minutes or builder errors yield `market_monitor_snapshot_error_v39a`, a durable `monitor_input_error` verdict, log event, and existing webhook; no model call. The hook remains after exit orders are saved and placed, with an exception boundary in `exits_flow`. No order, margin, finalization, reconciliation, DeltaScout, or signal code was changed. The local implementation adds explicit `market_state` and `market_structure_state` provenance, and no longer copies v1 local windows to the model-facing snapshot.

Retained v1 components: broad context and context inventory were already based on continuous context feed; local state, structure, registry, inventory and zones are recomputed from the complete continuous base slice. v1 remains an internal helper, not a final schema. The full unified 39A level lifecycle remains unimplemented. The new base slice changes state interpretation and may increase synchronous advisory computation time; this requires architect review and production validation before deployment.

## Read-only midnight replay

The replay ran inside the existing container against historical `/opt/aitrader/feed` files. It did not call the LLM, write state, alter historical verdicts, or use later trade outcomes. Its proposed canonical state fields were derived from a continuous 1440-minute base using the deployed v1 helper; the local new wrapper has not been installed in the container.

| Cutoff and field | Historical v1 model evidence | Proposed continuous canonical computation |
| --- | --- | --- |
| 2026-09-14 240m rows/start | 133 / `00:00Z` | 240 / `2026-09-13T22:13:00Z` |
| 2026-09-14 240m delta / delta_pct / OI change | `-124.579` / `-0.00873658` / `25.64` | `-774.819` / `-0.032165767` / `324.39` |
| 2026-09-14 market state | `ACCUMULATION` from 133 local rows | `ACCUMULATION` from continuous 1440 rows; evidence delta `-2381.912` versus old `-124.579` |
| 2026-09-14 structure state / bias | `COMPRESSION_ABOVE_SUPPORT` / `UP` | `MARKET_STRUCTURE_CONTEXT` / `NONE` |
| 2026-09-14 support / resistance | `73869.6–75969.1` / `78766.0–81377.7` | same price bands and zone ids in this replay |
| 2026-09-14 conflict | local buy flow versus broad 3d/7d distribution, MEDIUM | same conflict |
| 2026-08-31 240m rows/start/delta/OI | 240 / `04:59Z` / `1001.131` / `-216.76` | same, with delta_pct `0.0519556835` (rounding versus v1 `0.05195568`) |
| 2026-08-31 state / structure / bias | `EXPANSION_UP` / `COMPRESSION_ABOVE_SUPPORT` / `UP` | `ACCUMULATION` / `MARKET_STRUCTURE_CONTEXT` / `NONE` |
| 2026-08-31 support / resistance | `77053.5–78099.0` / `78958.0–81500.0`, resistance score 95 | same bands, resistance score 100 |
| 2026-08-31 conflict | local buy flow versus broad 3d/7d distribution, MEDIUM | same conflict |

## Verification and deployment gate

- New canonical regression file: 8 passed. Covers 00:04, 02:12 and 133-row shape, missing previous day, duplicate rows, ignored false flags, restart continuity, fail-loud no-model-call journal/log/webhook, and noncanonical entry rejection.
- Focused Judge plus canonical regressions: 55 passed, 2 subtests passed, 1 failed.
- Full local `python -m pytest -q`: 869 passed, 24 subtests passed, 1 failed. All execution lifecycle suites included in that run passed.
- The remaining failure is `test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`. It calls the prompt builder with no monitor; the canonical gate now rejects that input. Its older literal text assertions also fail against the already committed V2 prompt (`build_entry_prompt`) before this task. The test was not skipped, weakened, or silently rewritten.
- Compile checks and `git diff --check` passed for the edited code; final checks should be rerun after any review fix.
- Deployment gate not met. No backup, upload, restart, in-container postchange hash verification, or postchange runtime smoke was performed.

## Rollback boundary

There is nothing to roll back in production. The exact unchanged production target is the `executor` container/image and bind-mounted source hashes recorded above, with Compose at `/root/volume-alert/docker-compose.yml` and selected config in `/root/volume-alert/.executor.env`. Before any later rollout, back up those source/config files and record the backup path; restore those backups and recreate **only** executor if rollback is required. A command pointing to a backup path cannot honestly be supplied before that backup exists.

Final status: `BLOCKED_BY_TEST_FAILURE`.
