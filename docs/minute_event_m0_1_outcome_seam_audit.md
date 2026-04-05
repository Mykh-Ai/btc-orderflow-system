# DeltaScout Minute Event M0.1 Outcome Seam Audit

## Purpose

This memo closes the gap left after M0 by auditing whether the repository already contains reusable outcome-related code that could support a future minute-event outcomes layer.

This is an audit only.
It does not implement M2.5.

Feed-source note:

- the repository currently exposes a local Aggregator archive contour at `/data/archive/feed/YYYY-MM-DD.csv`
- the current offline/analyzer workflow also uses a separate external contour at `/opt/aitrader/feed/YYYY-MM-DD.csv`
- this memo documents reusable seams without treating those contours as one identical source

## Files Reviewed

Primary outcome-adjacent code reviewed:

- `scripts/offline/build_close_outcomes.py`
- `scripts/offline/build_phase1_derived.py`
- `scripts/offline/common.py`
- `scripts/offline/run_post_close_watcher.py`
- `deltascout/delta_analyzer/modules/build_review_tables.py`
- `deltascout/research_bundle/build_index_summary.py`
- `deltascout/research_bundle/build_raw_micro.py`
- `deltascout/research_bundle/build_sequence_context.py`
- `executor/executor.py`
- `buyer/buyer.py`

Supporting tests and materialized contracts reviewed:

- `tests/offline/test_phase1_builders.py`
- `tests/offline/test_post_close_watcher.py`
- `deltascout/test/test_research_archive.py`
- sample `deltascout/research_material/reviews/2026-03-17/close_outcomes_2026-03-17.csv`

Repository scope note:

- there is no top-level `backtester/` directory in this repository

## Outcome-Related Code Found

### 1. `scripts/offline/build_close_outcomes.py`

What it computes:

- offline `close_outcomes_YYYY-MM-DD` dataset
- joins close evidence back to `PEAK_EMIT` rows
- exact or fallback time-window matching between close records and peak events
- close deduplication across `trade_outcomes.jsonl`, `executor.log`, and `executor_state.json`
- close-level fields such as:
  - `close_ts`
  - `close_reason`
  - `close_price`
  - `entry`
  - `sl`
  - `join_status`
  - `join_confidence`
  - `peak_ts`
  - `peak_kind`
  - `peak_price`
  - `peak_delta`
  - `peak_imb`
  - `peak_vol`

Granularity:

- trade close / accepted peak event linkage

Reuse assessment:

- reusable with adaptation

Why:

- it already solves timestamp normalization, date scoping, deduplication, and event-to-close linkage
- but it is built around accepted trade closes, not minute-level future path outcomes
- it does not compute forward returns, excursions, threshold hits, or minute-by-minute post-event paths

### 2. `scripts/offline/build_phase1_derived.py`

What it computes:

- `reject_dataset`
- `baseline_init`
- `window_owner_miss`
- `late_peak`

Outcome/path-relevant parts:

- `derive_late_peak()`
  - finds a prior local price extreme inside a lookback row window
  - computes `move_start_ts`
  - computes `latency_min`
  - computes `move_size`
- `derive_window_owner_miss()`
  - computes rolling ownership extremes over past rows
  - computes `threshold_abs_delta`
  - identifies strong delta rows missed by owner logic

Granularity:

- event-level retrospective diagnostics using minute feed

Reuse assessment:

- partially reusable with adaptation

Why:

- `derive_late_peak()` is the clearest existing path-style computation in the repo
- but it is backward-looking from a PEAK event, not forward-looking from arbitrary minute rows
- `derive_window_owner_miss()` has threshold logic and rolling windows, but again for retrospective diagnostics rather than post-event outcomes
- neither function computes future max/min path, future return horizons, or MFE/MAE-style outcomes

### 3. `scripts/offline/common.py`

What it computes:

- generic offline builder utilities:
  - JSONL loading
  - feed loading
  - time parsing
  - deterministic sorting and output writing

Outcome/path relevance:

- `load_feed()` creates a sorted minute feed with normalized `ts`, `price`, and `delta`
- it is generic over the input file path, so contour provenance has to be preserved by the caller and by surrounding documentation

Granularity:

- minute feed utility layer

Reuse assessment:

- directly reusable

Why:

- this is the narrowest reusable utility seam for future minute-event outcomes outside `delta_analyzer`
- it already provides deterministic sorted minute-level feed input suitable for future-window slicing

### 4. `scripts/offline/run_post_close_watcher.py`

What it computes:

- orchestration only
- triggers offline builders when a new close is observed in `trade_outcomes.jsonl`

Granularity:

- pipeline orchestration

Reuse assessment:

- not reusable for minute-event outcomes directly

Why:

- useful only as evidence of current build order and current output dependencies
- it confirms that close outcomes are treated as a post-close research layer, not as a minute-event path layer

### 5. `deltascout/delta_analyzer/modules/build_review_tables.py`

What it computes:

- accepted/reject review tables from `events_context`
- joins accepted rows to `close_outcomes`
- exposes `join_status`, `join_confidence`, `close_ts`, `close_reason`, `entry`, `side`

Granularity:

- event review layer using accepted PEAK events

Reuse assessment:

- not directly reusable for minute-event outcomes

Why:

- it consumes close outcomes as input rather than computing path metrics
- it is a downstream reporting layer, not an outcome-calculation seam

### 6. `deltascout/research_bundle/build_index_summary.py`

What it computes:

- bundle-level review summary
- `close_outcome_count`
- accepted/reject review aggregation

Granularity:

- review bundle summary

Reuse assessment:

- not reusable for minute-event outcomes directly

Why:

- this is summary/reporting logic only

### 7. `deltascout/research_bundle/build_raw_micro.py`

What it computes:

- raw minute windows around selected cases
- per-minute values around a target timestamp
- derived per-minute `delta_1m`, `vol_1m`, `price_minus_vwap`

Granularity:

- selected-case minute path extraction

Reuse assessment:

- reusable with adaptation

Why:

- it already performs timestamp-based window extraction around target events
- however it extracts symmetric windows for selected cases only
- it does not compute future outcome metrics, excursions, or threshold-hit summaries
- still, it is the clearest existing path-extraction seam adjacent to future M2.5 work

### 8. `deltascout/research_bundle/build_sequence_context.py`

What it computes:

- event windows around selected cases using review tables
- later same-side event / accepted / stronger-reject flags

Granularity:

- event sequence context

Reuse assessment:

- not reusable for minute-event outcomes directly

Why:

- sequence logic is event-centric and label-centric
- it does not operate on future price path metrics

### 9. `executor/executor.py`

What it computes:

- live/paper trade lifecycle management
- stop/target handling
- trade close emission into `trade_outcomes.jsonl`
- fields inside `last_closed` snapshots such as:
  - `entry`
  - `sl`
  - `close_price`
  - `reason`
  - `trade_key`
  - execution/trailing-state metadata

Granularity:

- trade execution / position lifecycle

Reuse assessment:

- not reusable for minute-event outcomes directly

Why:

- this is trade-state and execution logic, not research path analytics
- it does create the canonical close/outcome journal used by offline builders
- but it is too entangled with trading semantics to be a clean seam for minute-event outcomes

### 10. `buyer/buyer.py`

What it computes:

- notify-only entry/SL/TP derivation
- no forward path analytics

Granularity:

- signal notification / trade plan

Reuse assessment:

- not reusable

## Current Contracts Relevant to Future Minute Outcomes

### Existing dataset contracts found

#### `close_outcomes_YYYY-MM-DD`

Observed contract from builder code and sample file:

- `close_key`
- `source_date`
- `close_ts`
- `mode`
- `close_reason`
- `close_price`
- `side`
- `entry`
- `sl`
- `join_status`
- `join_confidence`
- `peak_ts`
- `peak_kind`
- `peak_price`
- `peak_delta`
- `peak_imb`
- `peak_vol`
- flattened `lc_*` fields from `trade_outcomes.jsonl`

Assessment:

- this is a close-linkage contract, not a minute-event forward outcome contract
- it supports accepted event postmortem and close attribution
- it does not encode forward return horizons, excursions, or threshold-hit metrics for arbitrary minute rows

#### `late_peak_YYYY-MM-DD`

Observed contract from `derive_late_peak()`:

- `event_ts`
- `move_start_ts`
- `latency_min`
- `move_size`
- `reference_price`
- `peak_price`
- `lookback_rows`

Assessment:

- this is the nearest existing path-style metric contract
- but it is backward-looking and PEAK-specific
- useful as a conceptual template, not as direct minute-event outcome logic

#### `window_owner_miss_YYYY-MM-DD`

Observed contract:

- `ts`
- `delta`
- `abs_delta`
- `rolling_max`
- `rolling_min`
- `threshold_abs_delta`

Assessment:

- gives evidence of threshold logic and rolling path diagnostics
- not an outcome contract in the forward-return sense

## Existing Path / Sequence Utilities

### Utilities already present

#### `scripts/offline/common.py::load_feed`

Reusable seam:

- sorted minute feed with canonical `ts`, `price`, `delta`

Assessment:

- directly reusable utility for any future window/path builder

#### `deltascout/research_bundle/build_raw_micro.py`

Reusable seam:

- timestamp-based minute window extraction around a target event

Assessment:

- reusable with adaptation
- strongest existing example of path extraction logic in repository research code

#### `scripts/offline/build_close_outcomes.py::_join_peak`

Reusable seam:

- event-to-other-record timestamp linkage with explicit fallback window semantics

Assessment:

- reusable pattern for matching, but not a future-path calculator itself

### Utilities not found

No explicit reusable utility was found for:

- forward window slicing from arbitrary minute rows
- future max/min path computation over minute windows
- forward return horizon table generation
- MFE / MAE style excursion metrics
- threshold-hit and time-to-threshold metrics for minute events
- adverse-before-favorable path summaries

## Inconsistencies or Blockers

### 1. Existing outcome logic is trade-close-centric

The strongest existing outcome layer is `close_outcomes`, which is centered on accepted PEAKs and actual close evidence.

Blocker implication:

- minute-event outcomes will need a different object model
- one minute row may never become a trade, so trade-close logic cannot simply be reused as-is

### 2. Existing path metric is backward-looking, not forward-looking

`derive_late_peak()` computes retrospective move origin and latency into a PEAK.

Blocker implication:

- future minute-event outcomes need the opposite orientation: forward path from minute row to later prices

### 3. Path extraction logic is hidden in research bundle code, not analyzer foundation

`build_raw_micro.py` already slices minute windows, but it lives in selected-case bundle tooling.

Blocker implication:

- M2.5 should not directly depend on selected-case bundle code
- if reused, its logic should be adapted into a cleaner analyzer-side builder

### 4. Time-window semantics are inconsistent across modules

Examples:

- `build_close_outcomes.py` uses date scoping plus fallback join windows in minutes
- `derive_late_peak()` uses `lookback_rows`, not clock-time windows
- `delta_analyzer` context and mechanics layers use timestamp-based windows

Blocker implication:

- M2.5 should standardize on timestamp-based forward windows, not row-count windows

### 5. Documentation and file-placement drift exists

The current task references files under `deltascout/research_material/` for minute-event audit docs, while earlier local audit/planning notes were also being written under `docs/` in some steps.

Blocker implication:

- future M2.5 work should keep runbook/spec/audit location consistent to avoid split contracts

### 6. Feed-contour drift exists

The project currently has two distinct daily feed contours in active documentation and workflows: local `/data/archive/feed` and external `/opt/aitrader/feed`.

Blocker implication:

- minute-event outcome work must record which contour its input rows came from
- evidence from one contour should not be silently generalized as if it came from the other

## Recommended M2.5 Seam

Recommendation:

- build `minute_events_outcomes` as a fresh additive builder
- adapt a small amount of existing logic rather than trying to reuse close/trade builders directly

### Narrowest safe seam

Recommended implementation location:

- `deltascout/delta_analyzer/modules/build_minute_events_outcomes.py`

Recommended input:

- `MinuteEventRow` or `MinuteEventMechanicsRow`
- normalized feed rows already used by the analyzer

Recommended reusable pieces:

- reuse the analyzer-side sorted minute timeline concept already present in `minute_events_base` / `minute_events_mechanics`
- borrow timestamp/date normalization ideas from `scripts/offline/common.py`
- borrow window-extraction thinking from `deltascout/research_bundle/build_raw_micro.py`
- borrow matching discipline from `_join_peak()` only as a pattern, not as direct code

Recommended not to reuse directly:

- `build_close_outcomes.py` as the main builder
- `executor.py` or `buyer.py`
- `build_review_tables.py`
- `build_sequence_context.py`

### Why fresh additive builder is safer

Because future minute-event outcomes will need:

- arbitrary minute-row input, not only accepted PEAKs
- forward-looking windows, not retrospective close matching
- per-minute horizon metrics, not trade-close attribution
- likely metrics such as:
  - forward returns at fixed horizons
  - forward max favorable move
  - forward max adverse move
  - threshold-hit and time-to-threshold

The current repository does not already carry that exact builder shape.

## Final Verdict

The repository does carry some reusable outcome-adjacent infrastructure, but not a direct minute-event outcomes implementation.

Most reusable pieces are:

- deterministic feed loading and sorting
- date scoping and timestamp normalization
- selected-case minute window extraction
- close-event dedup and matching patterns

The repository does **not** already carry reusable minute-event forward outcome logic in the strong sense.

Final verdict:

- reusable outcome infrastructure exists only partially
- the safest future M2.5 seam is a fresh additive `minute_events_outcomes` builder that adapts utility patterns from existing offline and bundle code, rather than trying to repurpose trade-close builders directly
