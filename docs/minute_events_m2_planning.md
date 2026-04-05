# DeltaScout Minute Events M2 Planning Memo

## Purpose

This memo defines the next narrow implementation step after M1.

M1 established `minute_events_base` as a feed-native foundation dataset.
M2 should add a mechanics layer on top of that foundation without drifting into taxonomy, sequence logic, or process-phase labeling.

This is a planning memo only.
It does not implement M2.

## Current Starting Point

M1 now provides a canonical minute dataset with one row per normalized feed minute.

Current `minute_events_base` fields:

- `ts`
- `day`
- `open`
- `high`
- `low`
- `close`
- `buy_qty`
- `sell_qty`
- `vol_1m`
- `delta_1m`
- `imbalance_1m`
- `vwap`
- `open_interest`
- `funding_rate`
- `liq_buy_qty`
- `liq_sell_qty`
- `is_synthetic`
- `source_file`

This is sufficient to support a narrow mechanics layer without changing archive-event datasets.

## M2 Goal

Add `minute_events_mechanics` as a descriptive layer above `minute_events_base`.

M2 should answer:

- how unusual was this minute relative to nearby history?
- did delta produce real price progress or weak progress?
- where was the minute relative to VWAP?
- did OI behavior look like fresh participation, unwind, or unclear churn?
- was the move driven by liquidation burst behavior?
- what funding-side crowding context was visible?

M2 must remain descriptive.
It must not classify minute events into setup families or process phases.

## Recommended Output Shape

Recommended dataset:

- `minute_events_mechanics`

Recommendation:

- materialize as a separate dataset rather than mutating `minute_events_base`

Why:

- keeps M1 contract stable
- keeps M2 additive
- allows independent testing of mechanics behavior
- avoids inflating the base dataset before mechanics rules are trusted

Recommended row model:

- one output row per `minute_events_base` row
- base fields carried through unchanged
- mechanics fields appended

## Recommended Implementation Seam

Add:

- `MinuteEventMechanicsRow` dataclass in `deltascout/delta_analyzer/types.py`
- `build_minute_events_mechanics.py` in `deltascout/delta_analyzer/modules/`
- CLI dataset option `minute_events_mechanics`

Builder input:

- `minute_events_base` rows or equivalent in-memory `FeedRow`-derived foundation rows

Builder should not:

- read archive events
- join review outputs
- depend on `events_base` or `events_context`

## Recommended Mechanics Groups

### 1. Delta mechanics

Required fields:

- `abs_delta_1m`
- `delta_sign`
- `delta_to_vol_ratio`
- `delta_pct_60m`
- `delta_pct_180m`
- `vol_pct_60m`
- `vol_pct_180m`

Definitions:

- `abs_delta_1m = abs(delta_1m)` when known else `null`
- `delta_sign`:
  - `positive`
  - `negative`
  - `flat_or_unknown`
- `delta_to_vol_ratio = abs_delta_1m / vol_1m` when both known and `vol_1m != 0`, else `null`

Percentile policy recommendation:

- use rolling empirical percentile rank over prior-and-current known rows inside the lookback window
- compute on absolute values for `delta_pct_*` and `vol_pct_*`
- return `null` when the current value is unknown
- return `null` when there are fewer than `min_history_rows` valid observations

Recommended `min_history_rows`:

- `20`

### 2. Price-response mechanics

Required fields:

- `close_minus_open`
- `high_minus_low`
- `body_to_range_ratio`
- `close_location_in_range`
- `price_move_sign`
- `delta_price_alignment_1m`
- `delta_price_efficiency_1m`

Definitions:

- `close_minus_open = close - open` when both known else `null`
- `high_minus_low = high - low` when both known else `null`
- `body_to_range_ratio = abs(close - open) / (high - low)` when all known and range > 0 else `null`
- `close_location_in_range = (close - low) / (high - low)` when all known and range > 0 else `null`
- `price_move_sign`:
  - `up`
  - `down`
  - `flat_or_unknown`
- `delta_price_alignment_1m`:
  - `aligned`
  - `opposed`
  - `flat_or_unknown`
- `delta_price_efficiency_1m = abs(close - open) / abs(delta_1m)` when both known and `delta_1m != 0`, else `null`

Interpretation rule:

- M2 should expose these mechanically only
- no labels such as absorption, exhaustion, or squeeze in M2 output

### 3. VWAP / structure mechanics

Required fields:

- `dist_from_vwap`
- `abs_dist_from_vwap`
- `price_vs_vwap_side`
- `close_vs_vwap_side`
- `high_above_vwap_flag`
- `low_below_vwap_flag`

Definitions:

- `dist_from_vwap = close - vwap` when known else `null`
- `abs_dist_from_vwap = abs(dist_from_vwap)` when known else `null`
- `price_vs_vwap_side` should remain aligned with the existing side naming used elsewhere:
  - `above`
  - `below`
  - `at_or_unknown`
- `close_vs_vwap_side` may duplicate `price_vs_vwap_side`; if both fields survive, document the intentional duplication clearly
- `high_above_vwap_flag = true` when `high > vwap`, false when both known and not true, else `null`
- `low_below_vwap_flag = true` when `low < vwap`, false when both known and not true, else `null`

Recommendation:

- prefer keeping both `dist_from_vwap` and `abs_dist_from_vwap`
- keep naming close to the current event-context contract for continuity

### 4. OI mechanics

Required fields:

- `oi_change_1m`
- `abs_oi_change_1m`
- `oi_change_pct_60m`
- `oi_change_pct_180m`
- `delta_oi_alignment_flag`
- `price_oi_alignment_flag`

Definitions:

- `oi_change_1m = current_open_interest - previous_open_interest` when both known else `null`
- `abs_oi_change_1m = abs(oi_change_1m)` when known else `null`
- percentile fields should use the same rolling percentile policy as delta/volume, on absolute OI change
- alignment flags:
  - `aligned`
  - `opposed`
  - `flat_or_unknown`

Recommended alignment logic:

- `delta_oi_alignment_flag` compares the sign of `delta_1m` and `oi_change_1m`
- `price_oi_alignment_flag` compares the sign of `close_minus_open` and `oi_change_1m`

M2 should not yet emit interpreted labels like `new_participation`, `unwind`, or `churn` as final class fields.
If desired, that can be a later transparent rule layer above the raw mechanics.

### 5. Liquidation mechanics

Required fields:

- `liq_total_1m`
- `liq_imbalance_1m`
- `liq_dominant_side`
- `liq_burst_flag`
- `delta_vs_liq_relation_flag`

Definitions:

- `liq_total_1m = liq_buy_qty + liq_sell_qty` when both known, else use the known side if one side is known, else `null`
- `liq_imbalance_1m = liq_buy_qty - liq_sell_qty` when both known else `null`
- `liq_dominant_side`:
  - `buy`
  - `sell`
  - `balanced_or_unknown`
- `liq_burst_flag` recommendation:
  - compute on rolling percentile of `liq_total_1m`
  - `true` when percentile >= configured threshold
  - `false` when percentile is known and below threshold
  - `null` when percentile is not computable

Recommended default burst threshold:

- `0.95`

`delta_vs_liq_relation_flag` recommendation:

- `aligned`
- `opposed`
- `flat_or_unknown`

based on the sign of `delta_1m` versus the sign of `liq_imbalance_1m`

### 6. Funding context

Required fields:

- `funding_sign`
- `funding_abs`
- `funding_pct_24h`
- `crowded_side_flag`

Definitions:

- `funding_sign`:
  - `positive`
  - `negative`
  - `flat_or_unknown`
- `funding_abs = abs(funding_rate)` when known else `null`
- `funding_pct_24h` should use rolling empirical percentile rank on absolute funding magnitude over the last 24 hours of known minute rows
- `crowded_side_flag`:
  - `long_crowded`
  - `short_crowded`
  - `neutral_or_unknown`

Rule recommendation:

- positive funding implies `long_crowded`
- negative funding implies `short_crowded`
- zero or unknown implies `neutral_or_unknown`

## Shared Window Policy

All rolling percentile fields should use one explicit shared policy.

Recommended policy:

- windows are backward-looking and inclusive of the current row
- windows are based on actual timestamps, not row counts
- use globally merged, timestamp-sorted minute rows across all discovered feed files
- do not reset at day boundaries
- do not forward-fill missing values
- if the target metric is unknown on the current row, output `null`
- if fewer than `min_history_rows` valid rows exist in the lookback, output `null`

Recommended windows:

- `60m`
- `180m`
- `24h`

## Shared Null Policy

M2 should stay strict about nulls.

Recommended rule:

- unknown input should usually produce `null`, not silent zero-fill

Examples:

- unknown `open` or `close` means `close_minus_open = null`
- zero range means `body_to_range_ratio = null`
- zero `vol_1m` means `delta_to_vol_ratio = null`
- missing prior OI means `oi_change_1m = null`
- insufficient history means percentile fields = `null`

This keeps M2 descriptive instead of pretending to know more than the feed provides.

## Recommended CLI Behavior

Add:

- `--dataset minute_events_mechanics`

Behavior recommendation:

- build `minute_events_base` in memory first
- then build `minute_events_mechanics`
- when `--date` and `--output-root` are supplied, write:
  - `minute_events_mechanics_YYYY-MM-DD.csv`

Summary output recommendation:

- `feed_files`
- `minute_events_base_rows`
- `minute_events_mechanics_rows`
- coverage counts for major mechanics groups

## Recommended Test Scope for M2

Minimum tests:

- rolling percentile fields respect lookback windows and `min_history_rows`
- rows remain timestamp-sorted
- null handling stays strict for missing OHLC/OI/liquidation/funding inputs
- alignment flags behave deterministically for positive, negative, flat, and unknown cases
- `liq_burst_flag` only turns non-null when percentile is computable
- existing M1 tests continue to pass unchanged

Recommended separation:

- keep M2 tests in a separate test module rather than inflating the M1/M2 contract file too aggressively

Suggested file:

- `deltascout/test/test_minute_events_mechanics.py`

## Explicit Non-Goals for M2

M2 should still not do any of the following:

- event taxonomy
- event-class labels
- process-phase labels
- setup-family labels
- sequence logic
- move-potential scoring
- PEAK/reject reinterpretation
- profitability or trade claims

## Recommended M2 Task Slicing

Do not implement all M2 mechanics in one oversized patch.

Recommended narrow order:

1. add row type and builder scaffold
2. implement delta and price-response mechanics only
3. add VWAP / structure mechanics
4. add OI, liquidation, and funding mechanics
5. wire CLI and output contract
6. add focused tests and docs

This sequencing is safer than one large mechanics patch because it separates purely arithmetic fields from rolling-window and optional-field behavior.

## Final Planning Verdict

M2 is now well-scoped enough for a separate implementation task.

The recommended M2 implementation should:

- stay additive above `minute_events_base`
- materialize a separate `minute_events_mechanics` dataset
- prefer explicit deterministic contracts over heuristic interpretation
- keep taxonomy and phase logic strictly out of scope
