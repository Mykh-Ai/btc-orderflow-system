# Executor v2.0 reconciliation verification

Result: READY_FOR_ARCHITECT_REVIEW. This is not a merge or deployment approval.

Starting remote refs after fetch: refactor 46c77e5171995ad60739d4941b754f5377260983; v2.0 71b4af9747f9ba62d09cf4dab9c1f055bce870a9. Merge base bca9ab9dee052fdba72136a965f3cb68142acc4d. See the pre-implementation audit for unique commits, behavior evidence, obsolete test expectations and risks.

## Final behavior ownership

- pending_entry_flow promotes CANCELED/EXPIRED/REJECTED executed exposure into durable OPEN_FILLED before hooks/exits. order_utils provides reliable terminal executedQty parsing shared by the pending poll, timeout/post-cancel and reconciliation paths. Unknown, malformed, nonfinite, boolean and quantities that cannot be represented without losing exposure are retained for review.
- open_filled_retry owns durable failsafe intent creation and read-only confirmation. The client identity/config and exact original/executed quantity must match a MARKET FILLED order before the existing clear path runs. Intent is saved before POST; next_check_s and last_notice are durable. Uncertain POST/GET does not cause a second MARKET request or slot clear. Existing v2.0 API lookup and single-attempt failsafe transport are reused.
- reconciliation, live_position_manager, pending_entry_flow and exits_flow return before generic management when an intent exists. open_entry_flow explicitly rejects new signals. state_store.has_open_position and main's legacy abort-clear guard also respect intent even with a legacy saved status. Confirmation still runs when failsafe/config flags or status change; config mismatch stays owned. Reconciliation alert throttles are saved before early returns.
- entry_math owns the current highest-volume confirmed historical swing policy, including latest-timestamp tie-break, original window/schema rules, percentage floor, buffer/cap and outward rounding. market_data owns exact-minute lookup with -1 for missing/invalid context. The old swing_stop_far is retained for characterization/debug and is not used by entry planning.
- quote_sync owns same-cycle BTCUSDT/BTCUSDC mids, positive finite quote validation, ratio sanity band, outward conversion and execution-mid stop validation. Both entry and trail use it. trail owns USDT confirmation references, synchronization adapter and persisted conversion audit; manager validates before any SL cancel/replace. Quote errors log and notify while keeping existing protective orders. Invalid sanity-band configuration and malformed persisted confirmation throttle also fail loud.
- trade_open_summary is reused for OPEN text; symbol/side/volume, Entry, SL, absolute R, risk percent and TP prices remain. Human TP R suffixes are removed in telegram_text/message/text; numeric tp1_r/tp2_r remain.
- Current margin_policy (SC-04) and margin_guard (SC-05) are reused without logic changes. Tests reload real state after refactored close and verify error debt evidence plus cleared after-close flags persist.
- Current LLM entry snapshot/judge and Market Monitor files/config/docs/tests are preserved from v2.0. Market Monitor config has only its redundant final blank line removed to satisfy git diff --check.

## Validation

- Untouched v2.0 baseline: python -m pytest -q => 1 failed, 431 passed, 2 subtests passed.
- Untouched refactor repository suite: python -m pytest -q test/ => 423 passed, 24 subtests passed.
- Final focused lifecycle/stop/quote/margin suites => 494 passed, 22 subtests passed. The command selects test/sc01, test/sc02, test/v20 and all extracted entry/pending/retry/manager/reconciliation suites, close snapshots, entry math/current entry math, market_data, margin policy/isolated/guard, SC-04/05 and trade-open summary.
- Final full tracked-tree run in temporary clean export: python -m pytest -q => 1 failed, 694 passed, 24 subtests passed. Export uses git archive of the staged tree with all tracked tests included; no tests are skipped or disabled.
- Only full-suite failure is the pre-existing test/test_llm_trade_judge.py:432, TestMarketContextUntilCutoff.test_prompt_mentions_market_context_and_no_hindsight, expecting the old market_context.deltascout prompt literal. It is preserved unchanged from v2.0.
- Unqualified python -m pytest -q in the existing worktree still has 39 pre-existing collection errors because the user-owned transfer_out archive contains duplicate test module names. Archive remains unchanged; the clean tracked-tree run above proves this is not a source-tree collection regression.
- Compilation of executor.py and every executor_mod/*.py passed (Python glob expansion for PowerShell).
- git diff --check and git diff --cached --check passed after removing the redundant imported config EOF blank line.
- Static AST/import/ownership checks passed: public executor adapters call existing lifecycle modules; no adapter directly places entry/exit/flatten orders; no executor_mod imports executor; only one failsafe MARKET submission call and one confirmed-clear call exist in open_filled_retry. executor.py is 855 lines, versus current v2.0's monolith; orchestration, config and injected adapters remain there.

## Practical limits and remaining gaps

No requested behavioral port remains outstanding. The source v2.0 market_data loader does not create structural columns low_usdt/high_usdt/volume_1m/swing_row_real; the CSV must already supply them. Missing schema follows the current safe SKIP_OPEN contract. No production CSV or deployed runtime was inspected and nothing was deployed. SC-03 work beyond ownership/quantity guards and SC-06 durable borrow intent remain deliberately out of scope. Unrelated LLM prompt test repair requires a separate task.

User-owned AGENTS.md modifications and transfer_out are excluded from the commit. Legacy guidance files are retained; there are no deletions, history rewrites, v2.0 merges, server operations or new endpoints beyond current v2.0.

## Exact changed files

- `.gitignore`
- `LOG.md`
- `docs/entry-math-characterization.md`
- `docs/refactor-v20-reconciliation-audit.md`
- `docs/sc01-terminal-partial-fill.md`
- `docs/sc02-failsafe-flatten-confirmation.md`
- `docs/sc04-margin-debt-evidence.md`
- `docs/sc05-close-state-save-order.md`
- `executor.py`
- `executor_mod/binance_api.py`
- `executor_mod/entry_math.py`
- `executor_mod/entry_snapshot.py`
- `executor_mod/exits_flow.py`
- `executor_mod/live_position_manager.py`
- `executor_mod/llm_trade_judge.py`
- `executor_mod/margin_guard.py`
- `executor_mod/margin_policy.py`
- `executor_mod/market_data.py`
- `executor_mod/market_monitor_snapshot_v39a.py`
- `executor_mod/open_entry_flow.py`
- `executor_mod/open_filled_retry.py`
- `executor_mod/order_utils.py`
- `executor_mod/pending_entry_flow.py`
- `executor_mod/quote_sync.py`
- `executor_mod/reconciliation.py`
- `executor_mod/state_store.py`
- `executor_mod/trade_open_summary.py`
- `executor_mod/trail.py`
- `market_monitor/__init__.py`
- `market_monitor/accumulation_zones.py`
- `market_monitor/batch_runner.py`
- `market_monitor/config.py`
- `market_monitor/context_windows.py`
- `market_monitor/events.py`
- `market_monitor/feed_adapter.py`
- `market_monitor/hidden_flow_research.py`
- `market_monitor/label_quality.py`
- `market_monitor/label_taxonomy.py`
- `market_monitor/liquidity_zones.py`
- `market_monitor/market_structure_state.py`
- `market_monitor/outputs.py`
- `market_monitor/pattern_structures.py`
- `market_monitor/post_sweep_observation.py`
- `market_monitor/research_summary.py`
- `market_monitor/run_batch_research.py`
- `market_monitor/run_hidden_flow_research.py`
- `market_monitor/run_label_quality.py`
- `market_monitor/run_market_monitor.py`
- `market_monitor/run_research_summary.py`
- `market_monitor/run_significant_zone_selector.py`
- `market_monitor/run_trader_snapshot.py`
- `market_monitor/run_visual_overlay.py`
- `market_monitor/score_instrumentation.py`
- `market_monitor/significant_market_zones.py`
- `market_monitor/significant_zone_selector.py`
- `market_monitor/snapshot_builder.py`
- `market_monitor/snapshot_builder_v39a.py`
- `market_monitor/structure.py`
- `market_monitor/summary.py`
- `market_monitor/trader_snapshot_builder.py`
- `market_monitor/visual_overlay.py`
- `market_monitor/zone_registry.py`
- `test/sc01/conftest.py`
- `test/sc01/test_terminal_partial_fill.py`
- `test/sc02/conftest.py`
- `test/sc02/test_flatten_confirmation.py`
- `test/test_entry_math_current.py`
- `test/test_llm_trade_judge.py`
- `test/test_margin_policy.py`
- `test/test_open_entry_flow.py`
- `test/test_open_entry_flow_module.py`
- `test/test_open_filled_retry.py`
- `test/test_open_filled_retry_module.py`
- `test/test_reconciliation_module.py`
- `test/test_reconciliation_sync.py`
- `test/test_sc04_margin_debt_evidence.py`
- `test/test_sc05_close_state_persistence.py`
- `test/test_trade_open_summary.py`
- `test/v20/test_refactor_safety.py`
- `docs/refactor-v20-reconciliation-verification.md`

## Numbered final implementation evidence

- `executor_mod/pending_entry_flow.py:11`: `handle_pending_position` (ends at line 261).
- `executor_mod/open_filled_retry.py:13`: `handle_open_filled_exits_retry` (ends at line 94).
- `executor_mod/open_filled_retry.py:97`: `confirm_failsafe_flatten` (ends at line 178).
- `executor_mod/reconciliation.py:117`: `sync_from_binance` (ends at line 459).
- `executor_mod/entry_math.py:211`: `select_volume_confirmed_initial_stop` (ends at line 325).
- `executor_mod/market_data.py:72`: `locate_index_by_ts` (ends at line 85).
- `executor_mod/quote_sync.py:31`: `get_usdt_usdc_quote_snapshot` (ends at line 58).
- `executor_mod/quote_sync.py:61`: `convert_stop_usdt_to_usdc` (ends at line 78).
- `executor_mod/quote_sync.py:81`: `validate_stop_against_usdc_mid` (ends at line 94).
- `executor_mod/trail.py:330`: `set_confirmation_reference_from_agg` (ends at line 346).
- `executor_mod/trail.py:348`: `store_quote_audit` (ends at line 353).
- `executor_mod/trail.py:356`: `stop_quote_from_agg` (ends at line 366).
- `executor_mod/live_position_manager.py:11`: `manage_v15_position` (ends at line 604).
- `executor_mod/trade_open_summary.py:35`: `build_trade_open_payload` (ends at line 102).
- `executor_mod/margin_policy.py:341`: `_validated_cleanup_snapshot` (ends at line 396).
- `executor_mod/margin_guard.py:230`: `on_after_position_closed` (ends at line 319).
