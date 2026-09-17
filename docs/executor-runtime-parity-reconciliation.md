# Executor running-runtime parity reconciliation

Evidence-Audit completed BEFORE implementation on 2026-09-17.
Starting branch HEAD: aad153a2b426d849973e00beab4af90518617e65.
Reference GitHub v2.0: 71b4af9747f9ba62d09cf4dab9c1f055bce870a9.
Target: codex/refactor-executor-finalization-v1, existing worktree.

## Runtime capture and limits

Read-only existing vps95 SSH connection, docker inspect selected metadata and
`docker exec -i executor python -` running an AST/hash inspector. It reads
/app/executor.py, recursively every /app/executor_mod/**/*.py, /proc/1/environ
(filtered non-secret Executor configuration) and file timestamps. It does NOT
import Executor modules, call Binance, write production files, restart or stop.

Full source-tree transfer in either direction was rejected by automatic approval
review. Audit completed with file/definition hashes, metadata and targeted
loader/API/margin/monolith fragments instead. No full production tree is copied.
Secrets, webhook credentials and authentication configuration are excluded from
the durable evidence. The evidence JSON lists every inspected path/SHA256,
non-secret config names/values, all mounts, capture UTC, process start time and
source mtimes. Python is 3.11 in production and 3.12 locally, so canonical AST
hashing omits empty version-specific fields; raw ast.dump hashes would falsely
report every function as changed. File hashes are raw bytes; older gate hashes
were newline-normalized text and must not be compared as raw-byte hashes.

Production executor.py has 2954 source lines and is a
monolith. Its installed extraction modules are NOT evidence of active ownership.
Top-level production imports/configuration retain monolithic pending, management,
entry, reconciliation, retry, initial-stop and quote logic. Source mtimes predate
container start; capture therefore found no source change after that start.
This audit inspects mounted source, not attached interpreter memory.

## Complete file inventory (production vs v2 and audited refactor working tree)

Every runtime Python file is accounted for below; identical rows have no
meaningful runtime-only behavior to port.

| Runtime relative path | v2 comparison | Refactor comparison | Classification | Interpretation |
| --- | --- | --- | --- | --- |
| executor.py | different | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Active monolith: initial-stop/quote/exit helpers match v2 semantically; differences are pre-SC-01/02 safety and extraction/wiring. See detailed inventory. |
| executor_mod/__init__.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/baseline_policy.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/binance_api.py | different | different | OBSOLETE_OR_NOT_RELEVANT | Production lacks SC-02 EX_FLAT MARKET no-replay exception and get_order_by_client_id. Preserve branch confirmation safety; no regression port. |
| executor_mod/close_reporting.py | production_only | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/entry_math.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/entry_snapshot.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/event_dedup.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/exit_orders.py | production_only | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/exits_flow.py | identical | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/invariants.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/live_position_manager.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/llm_trade_judge.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/margin_guard.py | different | different | OBSOLETE_OR_NOT_RELEVANT | Production saves before clearing hook flags; branch contains SC-05 after-clear save. Keep the verified fix. |
| executor_mod/margin_policy.py | different | different | OBSOLETE_OR_NOT_RELEVANT | Production uses version-1 unvalidated cleanup/dedup; branch contains SC-04 scoped validated version-2 certificates. Keep the verified fix. |
| executor_mod/market_data.py | different | different | REQUIRED_RUNTIME_BEHAVIOR / OBSOLETE_OR_NOT_RELEVANT | Active loader lacks production normalization in both baselines. Runtime locate_index_by_ts is legacy; production executor inline exact-minute helper supersedes it. |
| executor_mod/notifications.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/open_entry_flow.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/open_filled_retry.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/order_utils.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/pending_entry_flow.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/position_finalization.py | production_only | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/reconciliation.py | production_only | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/risk_math.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/state_store.py | identical | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/trade_close_summary.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/trade_execution_snapshot.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/trade_open_summary.py | identical | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |
| executor_mod/trade_outcome_archive.py | identical | identical | OBSOLETE_OR_NOT_RELEVANT | No refactor behavior delta (LF-normalized source identical). Production-only relative to v2 files are installed extraction artifacts. |
| executor_mod/trail.py | identical | different | OBSOLETE_OR_NOT_RELEVANT / CONFIG_OR_DEPLOYMENT_ONLY | Preserved extraction/current safety differs from installed stale module. Active production behavior resides in executor.py or unchanged owner. Detailed mapping below. |

Baseline-only paths:
- executor_mod/market_monitor_snapshot_v39a.py exists in v2 and refactor but is
  absent from the mounted production tree: CONFIG_OR_DEPLOYMENT_ONLY. Keep it;
  missing deployment artifact is not a strategy or Executor-owner change.
- executor_mod/quote_sync.py exists only in refactor: CONFIG_OR_DEPLOYMENT_ONLY
  (modular ownership). Production keeps equivalent quote functions in executor.py.

## Complete meaningful production-v2 behavior delta inventory

1. REQUIRED_RUNTIME_BEHAVIOR: market_data.load_df_sorted derives structural
   inputs from the existing ten-column raw schema, preserves invalid interior
   close rows with forward-filled legacy price, and leaves untouched invalid
   raw inputs in structural columns. Port exact function to market_data owner.
2. OBSOLETE_OR_NOT_RELEVANT: production main clears terminal entries without
   checking fills; v2 SC-01 handles terminal partial fills. Refactor includes
   strict parser and explicitly required preserved critical webhook/throttle.
   Never restore the production exposure-loss behavior.
3. OBSOLETE_OR_NOT_RELEVANT: production retry suppresses flatten POST errors then
   clears immediately with timestamp client ID. v2 SC-02 has durable UUID intent,
   GET confirmation, quantity/config validation and ownership guards in main
   shutdown, manager and sync. Keep SC-02; task explicitly requires its tests.
4. OBSOLETE_OR_NOT_RELEVANT: binance_api._do_request in production lacks the
   EX_FLAT MARKET no-replay restriction; get_order_by_client_id is absent.
   These are the API side of historical SC-02, not new required behavior.
5. OBSOLETE_OR_NOT_RELEVANT: margin_policy cleanup is version 1, dedups unvalidated
   clean results regardless of scope, uses permissive asset snapshots and omits
   pre/post validation. v2 SC-04 fixed it. Preserve existing v2 safety semantics.
6. OBSOLETE_OR_NOT_RELEVANT: margin_guard saves cleanup before clearing lifecycle
   flags. v2 SC-05 moves the save after flag clearing, including failure paths.
   Preserve existing v2 safety semantics.
7. OBSOLETE_OR_NOT_RELEVANT: ten extraction files installed in production but
   absent from v2 are stale/inactive owners. No copy of stale pending/retry/
   manager/reconciliation/entry code. File content does not establish reachability.
8. CONFIG_OR_DEPLOYMENT_ONLY: missing market_monitor_snapshot_v39a.py deployment
   artifact; source/mount locations, actual environment overrides and CRLF/LF
   representation. Do not change defaults, thresholds or deployment.

Other production-v2 top-level definition ASTs match. Indexed statement differences
in executor.py are mostly insertion-index shifts from UUID import/new confirmation
function; compared leaf/control hashes identify only SC-01/02 semantics above.
Initial-stop selector/classes, quote helpers, SL/TP math, exits and trailing policy
match v2; no new strategy delta is found. No UNCERTAIN runtime behavior is ported.

## Production-refactor ownership/difference inventory

- entry_math: production monolith selector/dataclasses/error/structural buffer,
  floor/cap/volume/timestamp tie-break -> current entry_math. Installed runtime
  entry_math lacks V8 additions and is not the active selector. No selector fix.
- market_data: loader gap REQUIRED_RUNTIME_BEHAVIOR; production exact-minute
  inline resolver -> current market_data.locate_index_by_ts, already fail-closed.
  Ignore the unused runtime module's legacy latest-row fallback.
- quote_sync and trail adapters: production quote classes/functions -> existing
  quote_sync; confirmation reference/audit helpers -> trail adapters. Module
  placement differs, policy/thresholds do not. No re-monolithization.
- open_entry_flow: production main admission/entry/V8 stop/USDT-USDC conversion/
  initial-mid validation/open payload -> existing owner. Installed stale owner
  uses legacy stop; do not regress it.
- live_position_manager: active monolithic manager -> existing injected owner
  with quote callbacks and failsafe ownership guard. Installed stale manager is
  not evidence to undo production quote conversion or preserved SC-02.
- pending_entry_flow/order_utils: active main poll/timeout/post-cancel -> current
  owner; keep strict unknown-qty protection, partial-fill repair and exact SC-01
  files. Production's old clearing/parser is intentionally not copied.
- open_filled_retry/binance_api/state_store: retain SC-02 confirmed-close contract,
  no ambiguous MARKET replay and durable ownership; runtime's old code superseded.
- reconciliation/exits_flow: active production monolith reconciliation and retry
  -> existing owners. Keep persisted no-tag alert timestamp, strict terminal
  unknown-quantity retention and failsafe ownership guards from prior safety work.
  No broad SC-03 implementation or finalization redesign.
- margin_guard/margin_policy: retain SC-04/05 (historical runtime regressions above).
- trade_open_summary: production builder retains numeric tp1_r/tp2_r; refactor
  omits display-only R suffixes per prior task. Existing explicit presentation
  decision preserved; no trading semantics changed.
- close_reporting/exit_orders/position_finalization: runtime installed files match
  refactor, active production monolith adapters map to these owners; no policy gap.
- unchanged baseline/API support/dedup/invariants/LLM/snapshot/archive/risk/
  notifications/close-summary owners: normalized source matches as recorded.
- ENV and configure sequence: extra additive refactor LLM defaults and DI wiring
  are configuration/orchestration only; keep actual environment overrides outside
  strategy code. Do not bake production thresholds into defaults.

Intentional residual differences are the explicitly retained safety fixes,
modular DI placement, OPEN display decision and deployment artifact/configuration
facts. They must be visible to architect review; literal reproduction of known
production bugs is not claimed. The historical premerge safety report remains
byte-for-byte unchanged and is superseded only by this task's later validation.

## Exact loader semantics to port

- Strip BOM/whitespace from headers; missing file/Timestamp/price-column or failed
  timestamp/conversion handling returns empty as in captured function.
- Convert Timestamp with pd.to_datetime(utc=True), then remove timezone; sort
  ascending and reset index exactly as production.
- Choose ClosePrice, else AvgPrice, else Close. Numeric conversions use
  pd.to_numeric(errors="coerce"); absent high/low/volume/trades -> all-NaN Series.
- Preserve close_usdt/high_usdt/low_usdt/volume_1m untouched; derive price from close.
- swing_row_real: close/high/low/volume/trades are non-NaN and strictly positive,
  and high >= low. No added integer trade count, finite-number or close-in-range
  check. Positive infinity can pass these production comparisons; preserve and
  document it rather than inventing filtering.
- Legacy HiPrice/LowPrice fall back to price for absent/NaN values; this does NOT
  make the structural raw values or swing_row_real valid.
- Drop invalid Timestamp rows, sort/reset, forward-fill legacy price and drop
  remaining leading invalid price rows. Interior invalid close remains in minute
  sequence with false structural validity.

## Implementation and verification

Implemented only market_data.load_df_sorted, byte-for-byte equal to the captured
LF-normalized production function. No other REQUIRED_RUNTIME_BEHAVIOR gap found.
Existing exact-minute resolution and all strategy/SL/TP/trailing thresholds stay
unchanged. All three previous SC-01 files remain at captured baseline SHA256.
The raw ten-column feed contract is PRODUCTION_FEED_COMPATIBLE after this port.
Valid fixtures no longer fail with INITIAL_SWING_SCHEMA_MISSING.

New test/test_production_feed_contract.py contains 53 cases: raw CSV -> real
loader -> normalized columns -> exact minute -> V8 structural stop, LONG/SHORT,
1440-bar lookback/25-25 confirmation, invalid neighborhood rejection, malformed
source fields/timestamps, leading/interior invalid close behavior and exact-minute
miss without latest-row lookahead. It compares against the captured source
function in test/fixtures/production_market_data_loader.py.txt (SHA256 in evidence).

Production pandas is 3.0.3; local pandas is 2.3.0. A separate isolated `python -B`
child inside the container evaluated ONLY the captured AST loader function on a
small synthetic raw CSV via in-memory pandas/os proxies. No Executor imports,
feed read/write, bytecode write or exchange call. Exact normalized numeric values,
flags and sort order match local output, including malformed, zero/negative,
fractional trade-count, out-of-range close and infinite values. The 30 output
rows are durably captured in
`test/fixtures/production_market_data_normalization_reference.json`; an additional
regression test compares the local path to these actual production values.

Updated test/v20/test_refactor_safety.py integration CSV fixtures to native raw
columns. Its old missing-derived-column integration assertion is superseded by
invalid source TotalQty -> NO_CONFIRMED_VOLUME_SWING; direct selector schema
rejection coverage remains. No test disabled, skipped or trading logic changed.

Final pre-commit verification:
- Focused owner/raw-feed/safety command:
  python -m pytest -q test/test_production_feed_contract.py test/test_market_data.py
  test/test_executor_market_data_wrappers.py test/test_wiring_market_data.py
  test/test_entry_math.py test/test_entry_math_current.py test/test_open_entry_flow.py
  test/test_open_entry_flow_module.py test/sc01/ test/sc02/ test/v20/
  Result: 392 passed, 8 subtests passed (exit 0).
- Full tracked-tree pytest: temporary git archive HEAD plus the ten owned task
  files, excluding user AGENTS.md edit and untracked transfer_out/. No test skip
  or disabling. Result: 1 failed, 861 passed, 24 subtests passed (exit 1).
- Only failure: test/test_llm_trade_judge.py:432,
  TestMarketContextUntilCutoff.test_prompt_mentions_market_context_and_no_hindsight
  expects the old market_context.deltascout prompt literal. Known/allowed,
  unrelated and unchanged. No other failures.
- Compile: executor.py and executor_mod/*.py passed.
- Import-boundary AST check: no executor_mod Python file imports executor.py.
- executor.py remains exactly 855 lines, unchanged in this task.
- git diff --check exit 0; no-index new-file checks also show no whitespace errors.
- All 30 raw-byte production source SHA256 values unchanged at final recheck.
- All three SC-01 files plus user AGENTS.md remain at initial captured byte hashes.
- Raw ten-column loader accepts valid feed and exposes real structural inputs;
  V8 no longer raises INITIAL_SWING_SCHEMA_MISSING for a valid production schema.
- Focused real entry, quote/SL/trailing and SC-02 finalization tests remain reachable
  and pass; no re-monolithization or duplicate state machine.

Intentionally not ported: pre-SC-01/02/04/05 production bugs, stale unused owners,
legacy module latest-row lookup (active production helper already fail-closed),
missing deployment artifact/configuration differences and previously chosen OPEN
presentation. No additional active required-runtime behavior gap was found.
No UNCERTAIN behavior ported; no SC-03, SC-06, strategy, threshold, feed/aggregator,
production/server write, merge, deployment or restart.

Task files (ten; excluding user AGENTS.md and transfer_out/):
- executor_mod/pending_entry_flow.py (preserved SC-01)
- test/sc01/test_unknown_exposure_alert.py (preserved SC-01)
- docs/refactor-premerge-safety-gate.md (preserved historical SC-01 audit)
- executor_mod/market_data.py
- test/test_production_feed_contract.py
- test/v20/test_refactor_safety.py
- test/fixtures/production_market_data_loader.py.txt
- test/fixtures/production_market_data_normalization_reference.json
- docs/executor-runtime-parity-evidence.json
- docs/executor-runtime-parity-reconciliation.md

Final status: READY_FOR_FINAL_ARCHITECT_REVIEW.
This status does not claim literal parity with historical unsafe production
behaviors. Intentional retained safety differences and deployment facts above
are explicitly presented for architect review. No active required loader parity
gap remains. Commit/push metadata is recorded after validation.


SC-01 commit: 0597dd1f6ea3e4bc1adcef777d77e9529bf9aacc.
Runtime-parity commit SHA is the commit containing this report and is supplied
in the final task response; push target is exclusively
codex/refactor-executor-finalization-v1.
