# DeltaScout Research Material: Initial Findings

## Scope

Source files copied from the VPS:

- `raw_archive/2026-03-16.jsonl`
- `raw_archive/2026-03-17.jsonl`
- `raw_archive/2026-03-18.jsonl`
- `raw_archive/2026-03-19.jsonl`
- `raw_feed/2026-03-16.csv`
- `raw_feed/2026-03-17.csv`
- `raw_feed/2026-03-18.csv`
- `raw_feed/2026-03-19.csv`

Source path on server:

```text
/root/volume-alert/data/archive/deltascout/
/root/volume-alert/data/archive/feed/
```

Collection date:

- `2026-03-19`

## Basic Archive Coverage

Daily event counts:

- `2026-03-16`: 15
- `2026-03-17`: 32
- `2026-03-18`: 32
- `2026-03-19`: 24

Total archive rows in the copied sample:

- `103`

## Event Composition

Observed event types:

- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`

Not observed in this sample:

- `PEAK_EMIT`

Per-day event mix observed during inspection:

- `2026-03-16`: `DELTA_MIN`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MAX`
- `2026-03-17`: `DELTA_MIN`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MAX`
- `2026-03-18`: `DELTA_MAX`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MIN`, `CANDIDATE_GATE_REJECT`
- `2026-03-19`: `DELTA_MAX`, `CANDIDATE_COMPARISON_REJECT`, `DELTA_MIN`

## Reject Reasons Seen

Aggregate reject reasons across the copied sample:

- `direction_mismatch`: 25
- `vwap_side`: 14
- `vwap_distance`: 4
- `3of3_fail`: 4
- `no_prev_peak`: 3
- `imb_band`: 1

Observed gate-reject coverage:

- only 1 `CANDIDATE_GATE_REJECT`
- reject reason seen there: `imb_band`

Observed comparison-reject coverage:

- dominant class in the sample
- especially concentrated in `direction_mismatch` and `vwap_side`

## First Research Conclusions

This sample is already useful for research, but its current value is concentrated in the reject funnel rather than in accepted-signal analysis.

What is already useful:

- analyze how often raw delta peaks become comparison rejects
- measure which comparison checks are the main bottlenecks
- inspect whether `direction_mismatch` is structurally too dominant
- inspect whether `vwap_side` is blocking too many otherwise interesting candidates
- compare raw `DELTA_MAX` and `DELTA_MIN` frequency against reject frequency
- join decision events with the same-day feed context from `raw_feed/`
- inspect local market structure around reject timestamps using minute-level feed rows

What is not yet represented in this sample:

- accepted-signal archive flow through `PEAK_EMIT`
- meaningful pass-vs-reject comparison
- close-outcome joins based on accepted PEAK events

## Implication for the Next Analysis Module

The first analysis module should focus on archive health and reject analytics, not on accepted-trade analytics.

Recommended v1 focus:

- event coverage by day
- event-type distribution
- reject-reason distribution
- comparison-reject vs gate-reject split
- dominant bottleneck metrics over time
- identification of candidate expansion directions for future `PEAK_EMIT` growth

## Working Hypothesis

The most promising near-term research direction is to study how `direction_mismatch` and `vwap_side` suppress candidate flow before gate evaluation.

If the goal is to increase future `PEAK_EMIT` count without obvious quality loss, this sample suggests that the first expansion work should likely happen before or around comparison-stage logic, not around gate-stage loosening.
