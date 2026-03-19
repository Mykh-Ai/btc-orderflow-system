# Delta Analyzer Phase 2 Spec

## Goal

Extend the Phase 1 foundation with `events_context`, a research-only dataset that attaches multi-horizon flow context, backward-looking price context, and VWAP location to each archive event.

This layer should help answer:

- what local delta context preceded the event?
- what broader flow context preceded the event?
- how far was price from VWAP at the event?
- was the event aligned with local flow or sitting inside a conflicting broader backdrop?

## Scope

Phase 2 includes:

- all Phase 1 ingestion, matching, and integrity behavior
- a new `events_context` dataset builder
- rolling cumulative-delta context fields
- backward-looking price-delta context fields
- VWAP distance fields
- a CLI mode that can build `events_context` and summarize context coverage

## Non-Goals

Phase 2 does not include:

- outcomes or forward returns
- EMA, trend, or regime logic
- setup classification
- scoring or ranking
- session segmentation
- ML
- production DeltaScout logic

## events_context Field Contract

Each `events_context` row contains all `events_base` fields plus:

- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `cum_delta_utc_day`
- `ret_15m`
- `ret_60m`
- `dist_vwap`
- `abs_dist_vwap`
- `price_vs_vwap_side`

## Definitions

### Feed price source

Use `ClosePrice` from the feed when present. If `ClosePrice` is missing, fall back to `AvgPrice`.

### Feed delta per row

Per-row feed delta is:

- `BuyQty - SellQty`

### Rolling cumulative delta windows

For each event timestamp `event_ts`, rolling windows include all feed rows where:

- `feed_ts <= event_ts`
- `feed_ts` is inside the requested lookback duration

Fields:

- `cum_delta_24h`: rolling cumulative delta over the last 24 hours ending at `event_ts`
- `cum_delta_180m`: rolling cumulative delta over the last 180 minutes ending at `event_ts`
- `cum_delta_60m`: rolling cumulative delta over the last 60 minutes ending at `event_ts`

If full history is not available, compute with whatever feed rows exist in the window. Do not pad or extrapolate.

### UTC day cumulative delta reference

- `cum_delta_utc_day`: cumulative delta from `00:00 UTC` on the event date through `event_ts`

This field is a reference frame and must remain distinct from `cum_delta_24h`.

### Return fields

`ret_15m` and `ret_60m` are simple backward-looking price differences, not percentages:

- `ret_15m = matched_price_at_event - matched_price_at_or_before(event_ts - 15m)`
- `ret_60m = matched_price_at_event - matched_price_at_or_before(event_ts - 60m)`

If no earlier feed row exists at or before the lookback boundary, the return field must be `null`.

### VWAP fields

- `dist_vwap = event_price - event_vwap`
- `abs_dist_vwap = abs(dist_vwap)`
- `price_vs_vwap_side` is an explicit categorical field:
  - `above`
  - `below`
  - `at_or_unknown`

If event price or VWAP is missing, VWAP-derived fields stay null and `price_vs_vwap_side` becomes `at_or_unknown`.

## CLI Contract

Command:

```bash
python -m deltascout.delta_analyzer.cli
```

CLI responsibilities in Phase 2:

- load archive and feed files
- always build `events_base`
- optionally build `events_context` via `--dataset events_context` (default)
- run integrity checks on `events_base`
- print a concise summary including dataset row counts and context coverage

## Acceptance Criteria

Phase 2 is acceptable if:

1. `events_context` builds from local research materials
2. required context fields are attached when underlying data exists
3. `cum_delta_24h` is clearly distinct from `cum_delta_utc_day`
4. `cum_delta_60m` and `cum_delta_180m` are rolling windows ending at the event timestamp
5. VWAP distance fields are present
6. backward-looking price context fields are present
7. the CLI runs successfully and prints a concise summary
8. no production DeltaScout logic is modified
