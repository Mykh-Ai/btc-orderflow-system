# Delta Analyzer Phase 1 Spec

## Goal

Create a clean, minimal research foundation for `delta_analyzer` that can:

- ingest DeltaScout archive events
- ingest matching feed data
- match events to feed context
- build a base event dataset
- expose basic health checks

Phase 1 is a foundation layer, not a full analyzer.

## Scope

Phase 1 includes:

- archive JSONL reading
- feed CSV reading
- event normalization
- event-to-feed matching using nearest feed row where `feed_ts <= event_ts`
- building `events_base`
- integrity and health checks
- a minimal CLI that prints a summary

## Non-Goals

Phase 1 does not include:

- forward outcomes
- EMA, trend, or regime logic
- ML
- setup classification
- strategy ranking
- production signal logic

## Dataset Contract

`events_base` rows must contain:

- `ts`
- `event_type`
- `kind`
- `reject_reason`
- `delta`
- `vol`
- `imb`
- `price`
- `vwap`
- `poc`
- `matched_feed_ts`
- `source_file`
- `terminal_decision_present`

In Phase 1, `terminal_decision_present` is a heuristic flag based on same `(ts, kind)` presence of any non-raw event. It is not yet a strict lineage or terminal-pair guarantee.

## Ingestion Rules

Archive ingestion:

- read JSONL files line by line
- skip blank lines
- require `ts` and `event`
- normalize numeric fields when present
- retain source filename

Feed ingestion:

- use `/opt/aitrader/feed/*.csv` as the canonical default feed source unless `--feed-glob` is provided explicitly
- fail loudly when the selected feed glob matches no files
- read CSV files with `Timestamp`
- sort rows by timestamp
- use `ClosePrice` as preferred price, fallback to `AvgPrice`
- retain source filename

## Matching Rules

- each archive event must be matched to the nearest feed row with `feed_ts <= event_ts`
- if no such feed row exists, `matched_feed_ts` is `null`
- matching is global across the provided feed files after sorting

## Health Checks

Phase 1 health checks must return:

- `missing_feed_match_count`
- `multi_event_timestamps`
- `unmatched_events`
- `raw_delta_without_terminal_decision`

Definitions:

- `missing_feed_match_count`: events with no feed match
- `multi_event_timestamps`: count of timestamps that have more than one archive event row
- `unmatched_events`: compact human-readable identifiers for unmatched rows
- `raw_delta_without_terminal_decision`: `DELTA_MAX` or `DELTA_MIN` rows whose timestamp has no non-raw event partner

## CLI Contract

Command:

```bash
python -m deltascout.delta_analyzer.cli
```

CLI responsibilities:

- load archive files
- load feed files
- build `events_base`
- run integrity checks
- print a concise summary

## Acceptance Criteria

Phase 1 is acceptable if:

- the module can be imported cleanly
- the CLI runs against local research materials
- archive rows are normalized into a consistent internal shape
- feed rows are normalized into a consistent internal shape
- event rows receive nearest valid feed matches when possible
- `events_base` is built with the required columns
- integrity checks return the required metrics
- no production DeltaScout logic is modified
