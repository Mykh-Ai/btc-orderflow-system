# DeltaScout Minute Events M2.5 Planning Memo

## Purpose

This memo defines the next narrow planning layer after `minute_events_mechanics`.

M2.5 exists to add a **forward-outcome bridge layer** above mechanics and below taxonomy.
It should make later typed work evidence-oriented by measuring what actually happened after a minute-level observation row.

This is a planning memo only.
It does not implement M2.5.

## Current Starting Point

Current minute-event foundation layers already available or defined:

- `minute_events_base`
- `minute_events_mechanics`

Current state of the research stack:

Feed-source state note:

- `/data/archive/feed/YYYY-MM-DD.csv` and `/opt/aitrader/feed/YYYY-MM-DD.csv` are different market-data contours in current project documentation and workflow
- current evidence handling depends on declared contour provenance rather than treating the path as an incidental detail


- `minute_events_base` establishes one normalized observation row per minute
- `minute_events_mechanics` adds descriptive mechanics without event classes or setup claims
- the M0.1 outcome seam audit confirmed that the repository has only **partial** reusable outcome infrastructure

Main M0.1 outcome conclusion:

- reusable utility patterns exist
- a strong reusable minute-row forward-outcome builder does not already exist
- the safest seam is therefore a fresh additive `minute_events_outcomes` builder

## M2.5 Goal

M2.5 exists to measure **post-minute forward behavior** before minute-event classes are promoted into stronger research claims.

It solves the current gap between:

- descriptive mechanics
- later typed / taxonomy work

Without M2.5, M3 would risk turning minute mechanics into class claims without enough outcome-linked evidence.

M2.5 must therefore answer, deterministically:

- what happened after this minute over explicit forward horizons?
- how much upside and downside path followed?
- which thresholds were reached first, if any?
- did adverse path occur before favorable path, or vice versa?

## Recommended Dataset

Recommended dataset:

- `minute_events_outcomes`

Recommendation:

- materialize it as a **separate additive dataset** rather than mutating `minute_events_mechanics`

Why:

- keeps `minute_events_base` and `minute_events_mechanics` stable
- keeps outcome logic isolated from descriptive mechanics logic
- allows M2.5 to evolve independently without forcing M2 contract churn
- preserves a cleaner audit trail for later evidence review

Recommended row shape:

- one output row per input minute row
- carry identity fields forward
- carry a small reference subset of mechanics fields when needed for downstream joins and review
- append deterministic forward-outcome fields

## Recommended Implementation Seam

Recommended implementation location:

- `deltascout/delta_analyzer/modules/build_minute_events_outcomes.py`

Recommended row model:

- `MinuteEventOutcomesRow` in `deltascout/delta_analyzer/types.py`

### Input Layer Choice

Recommendation:

- M2.5 should consume `MinuteEventMechanicsRow`

Why:

- it preserves the additive layer order `base -> mechanics -> outcomes`
- it keeps downstream research able to study mechanics and outcomes in the same row contract
- it avoids recomputing already-defined direction and structure context later
- it still allows M2.5 to rely only on the subset it needs

Fallback principle:

- M2.5 should use mechanics rows as input, but its actual calculations should remain based on explicit price-path fields rather than mechanics heuristics wherever possible

### Utility Reuse Guidance

Recommended reusable patterns:

- analyzer-side timestamp-sorted minute timeline already used by `minute_events_base` and `minute_events_mechanics`
- deterministic timestamp normalization ideas from `scripts/offline/common.py`
- forward-window extraction discipline adapted from `deltascout/research_bundle/build_raw_micro.py`
- explicit matching discipline from `scripts/offline/build_close_outcomes.py::_join_peak()` as a pattern only

Recommended not to reuse directly:

- `scripts/offline/build_close_outcomes.py` as the main builder
- `executor/executor.py`
- `buyer/buyer.py`
- `deltascout/delta_analyzer/modules/build_review_tables.py`
- `deltascout/research_bundle/build_sequence_context.py`

These modules are either trade-close-centric, downstream reporting logic, or too entangled with non-minute objects.

## Price Basis Recommendation

Recommended price basis:

- `close`

Why:

- `minute_events_base` already promotes `close` as the canonical minute-end observation price
- `minute_events_mechanics` price-response fields already anchor on OHLC, especially `close`
- using `close` avoids ambiguity from the older backward-compatibility `price` field
- it keeps M2.5 aligned with the feed-native minute contract rather than legacy event-context compatibility behavior

If `close` is unknown on the current row, outcome metrics that require a start price should be `null`.

## Outcome Metrics In Scope

M2.5 should start narrow.

### 1. Forward returns at fixed horizons

Recommended fields:

- `ret_fwd_5m`
- `ret_fwd_15m`
- `ret_fwd_30m`
- `ret_fwd_60m`

Definition:

- `ret_fwd_X = future_close_at_or_before_horizon_end - current_close`

If no valid future close exists inside the horizon policy, output `null`.

### 2. Forward path extremes

Recommended fields:

- `upside_max_5m`
- `downside_max_5m`
- `upside_max_15m`
- `downside_max_15m`
- `upside_max_30m`
- `downside_max_30m`
- `upside_max_60m`
- `downside_max_60m`

Definitions relative to current `close`:

- `upside_max_X = max(future_high_or_close - current_close)` inside horizon
- `downside_max_X = max(current_close - future_low_or_close)` inside horizon

This keeps the first layer symmetric and avoids premature directional interpretation.

### 3. Threshold-hit metrics

Recommended first threshold family:

- percentage move thresholds on current close

Recommended initial threshold set:

- `0.10%`
- `0.25%`
- `0.50%`

Recommended fields by threshold `T` and horizon `H`:

- `up_hit_T_H_flag`
- `down_hit_T_H_flag`
- `up_time_to_hit_T_H_min`
- `down_time_to_hit_T_H_min`

Why percentage thresholds are the safest first layer:

- deterministic and easy to audit
- do not require external volatility models
- avoid introducing ATR-like or regime-normalized assumptions too early
- work directly from the `close` basis already present in the minute contract

### 4. Path-quality ordering metrics

Recommended fields:

- `up_before_down_T_H_flag`
- `down_before_up_T_H_flag`
- `both_hit_T_H_flag`

These should answer whether, within a given horizon and threshold, upside threshold or downside threshold was reached first.

This is the narrowest deterministic equivalent of an adverse-before-favorable style metric at this layer.

## Horizon / Threshold Policy

### Horizon Examples

Recommended initial horizon set:

- `5m`
- `15m`
- `30m`
- `60m`

Why:

- `5m` captures immediate follow-through
- `15m` and `30m` bridge short reaction and local continuation behavior
- `60m` is already aligned with existing analyzer context habits
- this set is narrow enough to test and reason about without over-expanding contract width

### Window Policy

Recommended policy:

- horizons are **time-based**, not row-based
- windows are **forward-looking** and **exclude** the current row from future-path calculations
- current row provides the anchor price only
- future rows must satisfy `current_ts < future_ts <= current_ts + horizon`
- use globally merged, timestamp-sorted minute rows across discovered feed files from one declared contour at a time
- do not reset at day boundaries

### Threshold Style

Recommended first-layer threshold style:

- percentage move from current `close`

Not recommended for first implementation:

- ATR-like thresholds
- volatility-relative thresholds
- mechanics-conditioned thresholds

Those may become useful later, but they would add interpretation and normalization assumptions too early.

## Favorable / Adverse Direction Semantics

This must be explicit because M2.5 exists before setup classes.

Recommendation:

- the **core** M2.5 contract should stay symmetric and report **upside** and **downside** outcomes separately
- if a derived favorable/adverse view is needed for research joins, use a deterministic `reference_direction` field

Recommended `reference_direction` logic:

- `up` when `price_move_sign == up`
- `down` when `price_move_sign == down`
- fallback to `delta_sign` when `price_move_sign == flat_or_unknown` and `delta_sign` is directional
- otherwise `unknown`

Then:

- `favorable_max_H` maps to upside for `reference_direction == up`
- `favorable_max_H` maps to downside for `reference_direction == down`
- `adverse_max_H` maps to the opposite side
- favorable/adverse derived fields should be `null` when `reference_direction == unknown`

Why this is the safest first approach:

- it avoids pretending every minute already has setup direction
- it preserves symmetric raw path evidence as the primary contract
- it still gives later research a deterministic first-pass directional lens without taxonomy

## Shared Null / Missing-Data Policy

M2.5 should remain strict about nulls.

Recommended rules:

- unknown current `close` => all outcome fields that depend on anchor price are `null`
- incomplete future horizon => fixed-horizon return fields are `null`
- future window with some valid rows but no exact horizon-end close => use the latest valid future row within the horizon only if this fallback is documented explicitly; otherwise keep `null`
- threshold not reached within horizon => hit flag = `false`, time-to-hit = `null`
- no valid future rows in horizon => hit flags and time-to-hit fields = `null`
- missing future high/low/close fields should not be silently zero-filled
- if current row itself is materially incomplete, symmetric path metrics should remain `null`

Recommended strictness:

- no forward-fill
- no inferred synthetic path completion
- no row-count substitution for missing clock-time coverage

## Explicit Non-Goals

M2.5 should still not do any of the following:

- setup-family validation
- profit claims
- edge ranking
- event taxonomy
- process-phase labeling
- live signal logic
- PEAK/reject reinterpretation
- trade-entry or trade-exit simulation

M2.5 is for deterministic forward-path measurement only.

## Test Scope Recommendation

Minimum future implementation tests:

- fixed-horizon forward return correctness for each horizon
- forward window selection respects `current_ts < future_ts <= horizon_end`
- threshold-hit flags turn true only when threshold is actually reached
- time-to-threshold is the earliest valid hit time in minutes
- `up_before_down` / `down_before_up` ordering behaves deterministically
- rows remain timestamp-sorted
- incomplete-horizon behavior stays strict and documented
- null handling is correct when current `close` or future path values are missing
- symmetric upside/downside metrics match the raw future path
- derived favorable/adverse mapping behaves deterministically when `reference_direction` is known and remains `null` when unknown

Recommended test file:

- `deltascout/test/test_minute_events_outcomes.py`

## Final Planning Verdict

The safest next M2.5 seam is:

- a fresh additive `minute_events_outcomes` dataset
- built in `delta_analyzer`
- consuming `MinuteEventMechanicsRow`
- anchored on current-row `close`
- using timestamp-based forward horizons
- exposing symmetric upside/downside path metrics first
- adding deterministic threshold and ordering fields before any typed event logic

This is the correct bridge between mechanics and later taxonomy work because it lets future M3 claims be tested against explicit forward evidence rather than promoted from mechanics alone.
