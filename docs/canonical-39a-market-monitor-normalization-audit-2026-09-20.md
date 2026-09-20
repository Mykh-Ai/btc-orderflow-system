# Canonical 39A Market Monitor normalization audit

Status: WIP / research branch. Full pytest still has one unmasked prompt-contract failure. This work is not ready to merge into `v2.0`.

Scope: `v2.0` at `7921d22`, isolated branch `codex/canonical-39a-monitor-normalization`. The original `v2.0` checkout was dirty before this work and was not edited. Audit preceded all code changes: status, 30-commit log, seven requested pickaxe searches, repository search, blame and numbered reads of the active runtime path.

Pickaxe provenance: `aad153a` introduced the v1 and 39A snapshot names, selection flags and the 39A `base_snapshot` dependency into the modular tree; `ae10ace` contains the 39A window/state implementation; `e7278f1` carried the selector values into parity evidence. `git blame` on the active Executor ENV, Judge builder call, feed adapter and entry-snapshot boundary confirmed those owners. `nl -ba` was used for the numbered runtime-path inspection.

## Before

`executor.py` ENV → `executor_mod.llm_trade_judge` chose v1 or v39A through monitor flags. The v1 builder consumed a cutoff-day feed and produced `market_monitor_snapshot_v1`; optional 39A consumed a broader feed but accepted the v1 result as `base_snapshot` for state, structure and zones. The locally uncommitted path had removed the choice but still called the v1 builder to construct that base. The default CSV loader dropped duplicate timestamps before the monitor could report them. The model-facing entry snapshot was therefore dependent on a legacy schema and could receive incomplete windows.

## Feature decisions

| Capability | Classification | Canonical source/decision |
| --- | --- | --- |
| Exact 5/15/30/60/240/1440 windows | ALREADY_CANONICAL | 39A timestamp-indexed windows, now mandatory for readiness |
| Missing timestamps, duplicate counts, completeness | ALREADY_CANONICAL | 39A window diagnostics; duplicate-preserving loader path and aggregate context check added |
| Recovered/degraded data and source files | ALREADY_CANONICAL | Feed adapter `DataQuality`/`SourceFile`, 39A quality and lineage |
| Persisted state, restart continuity | ALREADY_CANONICAL | 39A atomic state; invalid/future state now fails and same-cutoff write is idempotent |
| Market regime, price-relative structure, support/resistance, candidate bias | NEEDS_PORT_TO_CANONICAL | `outputs.build_market_state_timeline`, `market_structure_state` classifier and direct zone selection, all on continuous 1440 minutes |
| Liquidity and significant zones | NEEDS_PORT_TO_CANONICAL | `structure`, `liquidity_zones`, `zone_registry`, `accumulation_zones`, `significant_market_zones` algorithms directly composed in `canonical_features.py` |
| Broad 1d/3d/7d/30d context and conflicts | NEEDS_PORT_TO_CANONICAL | `context_windows` plus direction-aware conflict serialization |
| Delta, OI, range position and current close | ALREADY_CANONICAL | 39A local windows; exposed units made consistent |
| VWAP and POC | UNSAFE for exact values | OHLC-derived VWAP approximation labeled; POC unavailable without price-volume data |
| v1 snapshot builder and Executor duplicate 39A builder | LEGACY_DUPLICATE | Removed from production source; no retained algorithm selector |
| Cutoff-day-only local window and silent feed deduplication | OBSOLETE | Replaced by continuous feed and duplicate-preserving production load |
| `run_market_monitor.py`, `batch_runner.py`, `trader_snapshot_builder.py` | OBSOLETE as Executor inputs; retained historical research tooling | They write research outputs or render a selected-zone visualization and are not imported from `executor.py` or `executor_mod/`; no algorithm selector is exposed |

The direct feature algorithms may return no nearby zone when none qualifies. Empty typed zone buckets are explicit evidence, not a fallback to an older persisted snapshot.

## After

Feed CSV directory → duplicate-preserving `load_feed` → one `snapshot_builder_v39a` → direct canonical features and persisted state → validated `LLM_ENTRY_SNAPSHOT_V2` → advisory Judge journal. No monitor implementation flag, fallback import, or v1 schema is reachable from production runtime. Executor position lifecycle remains independent.

## Limits

The historical `LOG.md` and prior parity documents retain old strings as dated evidence; `docs/executor-runtime-parity-evidence.json` is a frozen parity input, not active configuration. No tracked compose, env example or deployment config exists in this repository. Prompt calibration is outside this task and its pre-existing regression test remains authoritative.

## Verification

- Canonical monitor regressions: 12 passed, including cross-midnight 240/1440 rows, missing previous day, default-loader duplicate retention, recovered data, direct features, canonical entry validation, source hashes at the Judge boundary and same-cutoff restart across a UTC day boundary.
- Focused canonical plus Judge suite: 58 passed with the unchanged prompt calibration test deselected for isolation only. The full suite below includes that test.
- Full pytest: 873 passed, 1 failed, 24 subtests passed. The failure is the existing V2 prompt calibration assertion; it now runs against a valid canonical snapshot and fails on absent historical prompt language. No assertion was removed or skipped.
- Compile checks: `python -m compileall -q executor.py executor_mod market_monitor test` passed.
- `git diff --check` passed. No deployment or restart was performed.
