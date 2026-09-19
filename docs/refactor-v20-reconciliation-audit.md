# Executor refactor reconciliation audit

Completed before runtime/test edits on 2026-09-17. Fresh fetch succeeded.

- v2.0: `71b4af9747f9ba62d09cf4dab9c1f055bce870a9`.
- Refactor/audit base: `46c77e5171995ad60739d4941b754f5377260983`.
- Merge base: `bca9ab9dee052fdba72136a965f3cb68142acc4d`.
- Both refs match supplied references; no newer commits. v2.0 checkout clean.
- Existing refactor worktree has user-owned AGENTS.md edit and transfer_out archive; preserve both, exclude from staging.

## Evidence and target mapping

Source numbers refer to fresh v2.0, target numbers to audit base. Checked git log -p -S, blame, rg and numbered reads. nl unavailable in PowerShell.

| Behavior | Evidence | Implementation target |
| --- | --- | --- |
| SC-01 | bec0aad, executor.py:2540-2583 persists exposure before hooks/exits and rejects unknown terminal quantity; pending_entry_flow.py:51-78 clears all terminal states | pending_entry_flow promotion, quote-key fallback and terminal event; existing OPEN_FILLED retry resumes after restart |
| SC-02 | 27a87bb, executor.py:2315-2429 durable identity, quantity/config validation and confirmed FILLED clear; open_filled_retry.py:48-51 suppresses POST errors then clears | open_filled_retry owns the single confirmation contract; reuse existing clear/finalization snapshot builders after confirmation |
| Ownership | 27a87bb executor.py:1210,1946,2445 guards manager/reconciliation/shutdown | live_position_manager, reconciliation, open_entry_flow, pending_entry_flow, exits_flow guards; thin orchestration and shutdown wiring |
| Reconciliation | executor.py:1965-2245 matches reconciliation.py:145-371 | Persist no-tagged last_emit mutations before early returns; terminal unknown quantity currently coerced to zero must retain ownership for SC-01 safety. No broad SC-03 redesign |
| Initial stop | ffb7dd9 executor.py:623-638,645-820,2842-2875; target open_entry_flow:86-99 falls back to last row and legacy swing | entry_math owns selection/dataclass/error; market_data exact-minute lookup; open_entry_flow calls structural selection. Preserve volume selection, timestamp tie-break, confirmed window, buffer/floor/cap and rounding |
| Quote sync | ffb7dd9 executor.py:1830-1929,2880-2935,1406-1745 | Shared quote_sync helper is justified by both entry and trailing callers. Inject mids/env/time. Existing trail owns source-level reference/audit adapters; manager catches sync errors before SL mutation and logs/alerts |
| OPEN | 9c93ebf trade_open_summary.py:39-104, executor.py:3048 | Reuse summary in open_entry_flow, remove human TP R suffixes only; preserve numeric tp1_r/tp2_r |
| SC-04 | f7279ab margin_policy.py:341-548 validates scoped pre/post evidence and v2 certificates | Reuse current margin_policy unchanged |
| SC-05 | 8b2a8fa margin_guard.py:304-318 clears flags before save including cleanup failure | Reuse current margin_guard unchanged; integration through refactor clear |
| New functionality | 71696ef,b366e19,d51f644,ae10ace and merge-base file diff | Preserve current non-lifecycle changed/additive files: API, margin modules, entry snapshot, LLM judge, monitor, tests/docs and ignore rules. Add newer LLM ENV keys. Preserve refactor-only files; do not copy monolithic executor or delete old guidance |

## Tests and expected changes

Reuse v2.0 test/sc01, test/sc02, SC-04/05, entry_math_current, margin_policy, LLM and summary suites. Adapt fixture configuration for extracted entry_math. Retain refactor purity/delegation, manager, reconciliation and close suites.

Obsolete assertions to update: clear after flatten POST/error; timestamp flatten IDs; latest-bar entry fallback; active legacy swing dependency; visible TP R suffixes. Direct module fixtures must provide new explicit dependencies. Add structural stop/quote safety, protective-SL preservation, durable throttle and uncertainty ownership coverage.

Expected runtime files: executor.py (wiring/config only), executor_mod/{pending_entry_flow,open_filled_retry,reconciliation,live_position_manager,open_entry_flow,entry_math,market_data,trail,exits_flow,quote_sync,trade_open_summary}.py, plus unchanged current non-lifecycle files identified above. Relevant tests and docs. No strategy/signal/borrow protocol/deployment/merge changes.

## Risks and baseline

- v2.0 full pytest: 1 failed, 431 passed, 2 subtests passed. Existing failure: TestMarketContextUntilCutoff.test_prompt_mentions_market_context_and_no_hindsight (old prompt literal). Preserve/report, do not rewrite unrelated test.
- Refactor unqualified full pytest: 39 duplicate collection errors from user transfer_out archive. Repository-only test/: 423 passed, 24 subtests passed. Preserve archive and report separately.
- Current market_data loader does not synthesize structural columns low_usdt/high_usdt/volume_1m/swing_row_real. Source must contain them; missing schema safely skips. Preserve this behavior without inventing synthetic bars.
- Intent is additive inside existing position mapping, generic JSON save/load already retains it. Absent intent follows ordinary old-state lifecycle; no destructive migration.
- Reuse v2.0 exact client-ID lookup and no-replay transport. No new endpoint beyond v2.0.
- No production state inspection needed; no server commands, deployment, v2.0 merge or SC-06 work.

## Audit commands

git status; git log --oneline -n 30; git log --graph --decorate --oneline --all -n 80; git merge-base; git log --left-right --cherry-pick; three-dot diff --stat/--name-status; git diff bca9ab9..origin/v2.0 -- executor.py and affected modules; git log -p -S for failsafe_flatten, ENTRY_TERMINAL_PARTIAL_FILLED, INITIAL_STOP_POLICY, TRAIL_USDC_SYNC_ERROR, tp1_r, debt_snapshot and save-order marker; git blame source and target ranges; rg all requested patterns and call graph. Unique commits recorded below directly from fresh refs.
> 71b4af9 Merge PR #169: characterize current executor entry math
> 34d9c57 test: characterize current executor entry math before extraction
> ac5d86e Merge PR #168: SC-05 persist cleared after-close flags
> 8b2a8fa fix(margin): persist after-close flags after clearing (SC-05)
> 22f9e10 Merge PR #167: SC-04 validated margin debt evidence
> f7279ab fix(margin): require validated debt evidence before clean cleanup (SC-04)
> 1b8defa Merge PR #166: confirm failsafe flatten before releasing position
> 27a87bb fix: confirm failsafe flatten fills before releasing position
> 005097c Merge PR #165: retain exposure after terminal partial entry fill
> bec0aad fix: retain executed exposure after terminal entry status
> 0c4f5cc test: cover terminal partial entry exposure and restart recovery
> 11acef1 Merge production executor sync
> ffb7dd9 Sync production executor stop and trail logic
> ff3caa7 Merge open alert risk levels
> 9c93ebf Add trade levels to open alerts
> 6288f1e Ignore downloaded server journals
> ae10ace Add entry-only LLM judge snapshot v2 and v39a monitor
> 7ba19e9 Document entry prompt v2 and v39a deployment
> d51f644 Fix LLM judge truncated JSON verdicts
> b366e19 Add repaired market structure evidence to LLM judge
> 71696ef Add Market Monitor snapshot evidence
< 46c77e5 refactor executor open entry flow
< 293f78e test open entry flow before extraction
< d922cfe refactor executor pending entry flow
< a934c16 test pending entry flow before extraction
< 4771fcf refactor executor live position manager
< 3be4e39 test live position manager behavior before extraction
< 17d69fa refactor executor open filled retry helpers
< 0fd8d22 test open filled exit retry lifecycle before extraction
< 3a37f0d refactor executor reconciliation helpers
< 97eefc9 test reconciliation sync behavior before extraction
< 9a2ab99 refactor executor exit order helpers
< 92143b5 refactor executor close reporting helpers
> 82882fb Add agent permission guidance
< 2726fe7 refactor executor finalization and entry math helpers


## Supplemental ownership evidence

Detailed implementation review confirms order_utils is the existing pure order-payload module shared by executor adapters. Pending poll/timeout/post-cancel and reconciliation duplicated quantity parsing, so its shared validated_executed_qty helper prevents the same unreliable-zero cleanup across these paths. state_store.has_open_position originally relied on status alone; main's legacy abort branch also cleared by status alone. Both now explicitly honor durable failsafe intent, as tested using a saved legacy ENTRY_CANCELED status. These are ownership guards, not a second finalization state machine.
