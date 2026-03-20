# DeltaScout Research Material: Initial Findings

## Scope

Source files copied from the VPS:

- `raw_archive/2026-03-16.jsonl`
- `raw_archive/2026-03-17.jsonl`
- `raw_archive/2026-03-18.jsonl`
- `raw_archive/2026-03-19.jsonl`
- `raw_archive/2026-03-20.jsonl`
- `raw_feed/2026-03-16.csv`
- `raw_feed/2026-03-17.csv`
- `raw_feed/2026-03-18.csv`
- `raw_feed/2026-03-19.csv`
- `raw_feed/2026-03-20.csv`

Source path on server:

```text
/root/volume-alert/data/archive/deltascout/
/root/volume-alert/data/archive/feed/
```

Collection date:

- `2026-03-20`

## Basic Archive Coverage

Daily event counts:

- `2026-03-16`: 15
- `2026-03-17`: 32
- `2026-03-18`: 32
- `2026-03-19`: 24
- `2026-03-20`: 14

Total archive rows in the copied sample:

- `117`

## Event Composition

Observed event types:

- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`
- `PEAK_EMIT`

Per-day event mix observed during inspection:

- `2026-03-16`: `DELTA_MIN`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MAX`
- `2026-03-17`: `DELTA_MIN`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MAX`
- `2026-03-18`: `DELTA_MAX`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MIN`, `CANDIDATE_GATE_REJECT`
- `2026-03-19`: `DELTA_MAX`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MIN`
- `2026-03-20`: `DELTA_MIN`, `PEAK_EMIT`, `DELTA_MAX`, `CANDIDATE_COMPARISON_REJECT`

Observed accepted-flow coverage:

- `2026-03-20` contains the first copied `PEAK_EMIT` in the local research sample
- the emitted event is a `short` peak at `2026-03-20 00:40:00`
- same-day offline rebuild produced `close_outcomes_2026-03-20.csv` with `rows=1`
- the close-outcome join status for that row is `window_match`

## Reject Reasons Seen

Aggregate reject reasons across the copied sample:

- `direction_mismatch`: 29
- `vwap_side`: 15
- `vwap_distance`: 4
- `3of3_fail`: 5
- `no_prev_peak`: 3
- `imb_band`: 1

Observed gate-reject coverage:

- only 1 `CANDIDATE_GATE_REJECT`
- reject reason seen there: `imb_band`

Observed comparison-reject coverage:

- dominant class in the sample
- especially concentrated in `direction_mismatch` and `vwap_side`
- `2026-03-20` continues the same pattern: 6 comparison rejects, of which 4 are `direction_mismatch`

## First Research Conclusions

This sample is still most useful for reject-funnel research, but it no longer represents a pure reject-only slice.

What is already useful:

- analyze how often raw delta peaks become comparison rejects
- measure which comparison checks are the main bottlenecks
- inspect whether `direction_mismatch` is structurally too dominant
- inspect whether `vwap_side` is blocking too many otherwise interesting candidates
- compare raw `DELTA_MAX` and `DELTA_MIN` frequency against reject frequency
- join decision events with the same-day feed context from `raw_feed/`
- inspect local market structure around reject timestamps using minute-level feed rows
- inspect the first copied `PEAK_EMIT` path and compare it against same-day rejects around it
- use the `2026-03-20` close-outcome row as the first accepted-flow anchor for join validation

What is not yet represented in this sample:

- broad accepted-signal coverage across multiple days
- meaningful pass-vs-reject comparison at sample scale
- robust close-outcome analysis across multiple emitted signals

## Implication for the Next Analysis Module

The first analysis module should still focus on archive health and reject analytics, but it should no longer ignore accepted-flow handling completely.

Recommended v1 focus:

- event coverage by day
- event-type distribution
- reject-reason distribution
- comparison-reject vs gate-reject split
- dominant bottleneck metrics over time
- explicit handling of sparse `PEAK_EMIT` coverage when it appears
- verification that emitted peaks can be joined to downstream close outcomes
- identification of candidate expansion directions for future `PEAK_EMIT` growth

## Working Hypothesis

The most promising near-term research direction is still to study how `direction_mismatch` and `vwap_side` suppress candidate flow before gate evaluation.

The `2026-03-20` material strengthens that view rather than weakening it:

- one real `PEAK_EMIT` now exists in the copied sample
- gate rejects are still extremely rare
- comparison rejects remain the dominant suppression layer

If the goal is to increase future `PEAK_EMIT` count without obvious quality loss, the evidence still points first to comparison-stage logic, while also confirming that accepted-flow joins should now be kept in the analysis loop.
