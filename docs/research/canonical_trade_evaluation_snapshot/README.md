# Canonical trade evaluation snapshot V1 — research contract

This is a **WIP research input** on `codex/canonical-39a-monitor-normalization`. The new trade-evaluation builder is not connected to the production model call. No trade logic, deployment, Executor restart, or historical verdict was changed. The `LLM_ENTRY_SNAPSHOT_V2` prompt instructions and model setting remain as they were, including the known failing calibration test. The branch adds a pre-call `judge_invocation_started_at_utc` field to future verdict evidence packs; it does not enter the current V2 model input. The added monitor horizon fields **would** pass through the existing V2 snapshot serializer if this branch were deployed, so model-input impact still needs architecture review before deployment.

## Timing and actual runtime flow

`DeltaScout PEAK → Executor candidate/open → Binance fill observed by Executor → initial SL/TP orders placed → position saved OPEN → EXITS_PLACED_V15 Judge hook → evidence pack → current V2 prompt → GPT-5.5`. The Judge sees an actual position. `open_entry_flow.py` carries PEAK `ts` and USDT `price`; `pending_entry_flow.py` records `entry_actual`, `executedQty`/position quantity, and `filled_at` when it observes a fill. `exits_flow.py` invokes the Judge only after exits are placed. `llm_trade_judge.py` then copies `entry_actual`, `filled_at`, quantity and initial `prices` to the durable evidence pack. The current V2 `analysis_cutoff_ts` still points to PEAK, even though the call occurs after fill; this research contract does not silently reuse that cutoff.

The old verdict journal's `created_at` is written **after** the model call. It cannot establish the exact invocation or assessment time. Historical model inputs therefore have `assessment_cutoff_utc: null`, `exact_assessment_cutoff: false`, and market cutoff at the last closed minute at or before the Executor-observed fill. This is deliberately conservative and may omit later pre-call market data. The documented initial SL/TP are durable in the Judge-hook pack, so they were known when the old call was made. The `filled_at` field is Executor observation time, not the Binance transaction timestamp.

## Schema and provenance

`executor_mod/trade_evaluation_snapshot.py` builds `CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1` from an allowlist. A future caller must provide the actual assessment cutoff before sending it to a model; the builder checks signal ≤ fill ≤ assessment and every market horizon end ≤ market cutoff ≤ assessment. A missing historical assessment cutoff remains explicit and makes quality `PARTIAL`.

| Field group | Source and meaning |
| --- | --- |
| `signal.signal_time_utc`, `signal_price`, `side` | DeltaScout PEAK `src_evt.ts`, `price_usdt`, `kind`; prices are USDT per BTC. No signal price is substituted for actual entry. |
| `signal.measurements` | `delta`, `vol`/`volume`, `imb`/`imbalance`, `vwap`, `poc`, `strength` from the durable PEAK event, supplemented by the prior frozen signal seed only when absent. Signal VWAP/POC are upstream facts with their own source semantics; they are not the monitor's VWAP/POC. |
| `signal.raw_signal_plan_usdt` | DeltaScout's planned `entry_usdt`, `sl_usdt`, `tp1_usdt`, `tp2_usdt`, kept separate from Executor's actual initial geometry. `upstream_source` and `upstream_action` preserve source identity. Filter A/B interpretation is omitted; no admission conclusion is converted into model advice. |
| `execution.actual_entry_price`, `filled_qty`, `actual_fill_timestamp_utc` | Judge-hook `evidence_pack.entry_actual`, `executedQty` when present (otherwise position `qty`), and `filled_at`. The fill timestamp is when Executor observed the fill. |
| `execution.initial_stop_price`, `tp1_price`, `tp2_price` | Judge-hook `evidence_pack.prices`, after initial exits have been placed. No later amended, trailed or closed values are read. |
| `execution` distances and R | Computed from **actual** entry and initial stop/targets in BTCUSDC quote currency. Risk is positive in trade direction; reward is signed in trade direction, so adverse target geometry remains visible. `R = reward / risk`. |
| `entry_minus_signal_*_approx`, zone execution-quote geometry | Raw DeltaScout and feed prices are USDT; Executor entry/targets are USDC. Durable `k_entry` is the entry-time USDT→USDC quote ratio. Conversion and all cross-quote distances are approximate; no exact assessment-time conversion is claimed. |
| `market.horizons` | One 39A feed-based rolling contract for `5m`, `15m`, `30m`, `60m`, `240m`, `1440m`, `3d`, `7d`, `30d`. `1d` is an alias to `1440m`, not a second numerical fact. Every horizon is clipped to a closed UTC-minute market cutoff. |
| `market.zones` | Canonical significant/liquidity registry and qualified nearest support/resistance, deduplicated by category and zone ID. Bounds stay in feed quote currency and are also converted approximately for entry/TP geometry. Status and confidence remain descriptive. |
| `market.classifiers` | Named derived interpretations with separate roles; raw horizon observations remain the common factual base. |
| `quality` | Monitor readiness, incomplete horizon names, recovered data, reconstruction flag, missing evidence, units, and exactness. `READY_WITH_PARTIAL_CONTEXT` prevents incomplete 3d/7d/30d from being hidden by complete local windows. |

For each horizon the model gets start/end, expected/used rows, complete/valid flags, missing count and first ten missing timestamp examples, duplicate count, quality counts, open/close/high/low, price change and percent, `current_price_position_in_range`, delta and fractional `delta_pct`, total quantity, OI change in feed-contract units, OHLC typical-price quantity-weighted `vwap_approx`, and price-minus-approx-VWAP in quote units and percent. This approximation is not trade-level VWAP. Exact POC remains `null` with `UNAVAILABLE_PRICE_VOLUME_DISTRIBUTION_MISSING`. Partial horizons keep measured values but `metrics_valid: false`; they cannot masquerade as complete evidence.

## Classifier roles and overlap

| Model field | Horizon and algorithm | Role / overlap |
| --- | --- | --- |
| `rolling_market_state` | Rolling 1440 closed minutes, `market_state_timeline` | Derived regime interpretation. It can disagree with structure because its inputs and labels differ. |
| `rolling_structure_state` | Rolling 1440 closed minutes plus canonical zones, `market_structure_state_classifier` | Derived structure interpretation, not a second raw market fact. |
| `candidate_bias` | Subfield of the structure classifier | Candidate-direction interpretation. It is not an independent DeltaScout signal or a recommendation. |
| `context_conflicts` | Local 60m delta versus broad 3d/7d regime labels | Derived, limited conflict observations. An empty list does not establish agreement across all horizons. |
| `structure.levels` | Observed 240m/1440m extrema | Kept in the monitor's internal state continuity, omitted from model input because their numeric facts already appear in horizons and observed extrema are not automatically qualified structure. |

The model input does not include the old parallel `broad_context.1d` numbers or legacy `market_context.aggregated`, which could duplicate the single `1440m` fact. It does not include monitor state memory or diagnostics. The monitor still uses broad-context regime internally for classifiers; the model-facing numeric horizon values come from the one exact rolling-window algorithm.

## Real example

`EX_EN_1781221266` in `frozen_trade_evaluation_snapshots.jsonl`: DeltaScout long PEAK at `2026-06-11T23:41:00Z`, signal `63667.092603 USDT/BTC`, delta `42.63 BTC`; Executor observed fill at `23:42:06.493872Z`, actual entry `63619.03 USDC/BTC`, qty `0.04715 BTC`, initial SL `63221.74`, TP1 `64016.31`, TP2 `64413.59`. Risk from actual entry is `397.29 USDC/BTC`; TP1 and TP2 are `0.9999748295 R` and `1.9999496589 R`. The 240m market horizon ending `23:42:00Z` has `240/240` rows, high `63776.6`, low `63235.8`, `current_price_position_in_range` `0.74297337`, and `COMPLETE_DEGRADED` provenance. The 30d horizon is incomplete. Its `assessment_cutoff_utc` is null because the exact historic Judge-call time was not persisted. This case is an **example of partially reconstructed input**, not an eligible GPT-5.6 evaluation input.

## Historical rebuild and cohort

`rebuild_cases.py` verifies all **155 full-day source SHA-256 hashes** from the prior research manifest against read-only local archives, then clips loaded feed rows to each case's conservative fill-minute cutoff. It recomputes each file's synthetic/recovered quality from rows already available by that cutoff, runs the current self-contained 39A monitor without state writes, and freezes the new model input. Full-day hashes and later outcome records remain outside model input. `case_ledger.csv` joins lifecycle/outcome **after** freezing each input; never hand the ledger to the model.

The 26 durable Judge-hook records yield **24 partial snapshots**: 20 of the prior 21 frozen cases and four additional `ERROR_NOT_SCORED` cases. One prior case (`EX_EN_1778813539`) has signal time later than its observed fill/verdict and is rejected for impossible chronology. One supplemental case (`EX_EN_1789841876`) lacks a SHA-matched post-September-14 source-feed segment. Across the 24 snapshots, monitor readiness is 1 `READY`, 14 `READY_WITH_DEGRADED_DATA`, and 9 `READY_WITH_PARTIAL_CONTEXT`; all remain snapshot `PARTIAL` because exact assessment time is unknown. One case additionally lacks durable raw signal measurements. Fifteen have complete 30d history; seven lack 30d, and two lack 7d and 30d.

Of the 24 snapshots, 23 have a joined final `SL` reason and one has no outcome in the available journal. Eleven of those 23 show no TP1 completion; twelve show TP1 completion, including six with TP2 completion before later stop/management. These are **favorable lifecycle stages**, not proven net-winning trades. The separate execution-snapshot journal has 15 rows but no net realized PnL for this cohort; one row reports positive approximate gross PnL, which cannot establish net profitability. Thus there are **zero verified net-winning evaluation cases**, and zero fully usable losing/winning cases for controlled GPT-5.6 A/B/C due to the missing exact assessment cutoff. The 24 partial inputs are useful for schema inspection and sensitivity research, with their limitations visible.

## Remaining blockers before GPT-5.6 research

1. After architectural review, deploy and verify the branch's new pre-call `judge_invocation_started_at_utc` journal field, then build the monitor from closed observations available at that time. It is not present in old journals. The current production cutoff remains PEAK; the branch does not yet route the new trade snapshot into the model call.
2. Obtain trusted source feed hashes after September 14 for the missing supplemental case; resolve the one timestamp anomaly from source evidence rather than timezone guessing.
3. Obtain complete realized fill/fee records and verified **net** PnL for a balanced cohort, including wins. A TP1/TP2 flag or final `SL` alone is not a net outcome.
4. Review the existing V2 prompt-contract regression separately. No assertion was deleted, skipped or xfailed here. Do not launch an A/B/C evaluation from this incomplete cohort.

Rebuild command: run `python -m docs.research.canonical_trade_evaluation_snapshot.rebuild_cases --help` from the repository root, then pass the durable local verdict/outcome/optional execution journals, the three `docs/research/llm_judge_calibration/source_*` research files, every local feed root needed to satisfy all 155 hashes, and this directory as `--output`. It makes no model call and writes no Executor state.

## Verification

- Focused trade-snapshot and canonical-monitor tests: **19 passed**.
- Full `python -m pytest -q --tb=no`: **880 passed, 1 failed, 24 subtests passed**. The one failure is the unchanged `test_prompt_mentions_market_context_and_no_hindsight` V2 prompt-contract regression. It was not edited, skipped, xfailed, or masked.
- `python -m compileall -q executor_mod market_monitor docs/research/canonical_trade_evaluation_snapshot test/test_trade_evaluation_snapshot.py` and staged `git diff --cached --check` passed.
- Frozen-input integrity test checks all 24 SHA-256 ledger digests, conservative market cutoff ≤ observed fill, explicit partial status, and absence of outcome/PnL/trailing/verdict keys.

**Research status: `BLOCKED_BY_MISSING_PREASSESSMENT_EVIDENCE`.** The known V2 prompt test also blocks any merge decision until resolved in a separate prompt-contract task.
