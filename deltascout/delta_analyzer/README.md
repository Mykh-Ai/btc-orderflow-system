# Delta Analyzer

`delta_analyzer` is a research-only foundation module for DeltaScout.

It exists to build a clean base layer for future analyzer work around:

- archive ingestion
- feed ingestion
- event-to-feed matching
- base event dataset creation
- archive and matching health checks
- backward-looking context reconstruction

## Phase 1 Scope

Phase 1 implements only the foundation layer:

- read archive JSONL files
- read feed CSV files
- normalize rows into simple internal types
- match event timestamps to nearest feed row with `feed_ts <= event_ts`
- build `events_base`
- run basic integrity checks
- provide a minimal CLI summary

In Phase 1, `terminal_decision_present` is a heuristic flag based on same `(ts, kind)` presence of any non-raw event. It is not yet a strict lineage or terminal-pair guarantee.

## Phase 2 Scope

Phase 2 adds `events_context`, a research-only extension of `events_base` that reconstructs backward-looking flow and price context around each event.

Phase 2 currently adds:

- rolling cumulative delta over `24h`, `180m`, and `60m` using the full merged feed history across all discovered CSV files
- backward-looking price deltas over `15m` and `60m`
- event-price distance from VWAP

Important naming rule:

- `cum_delta_24h` means rolling cumulative delta over the last 24 hours ending at the event timestamp
- `cum_delta_24h`, `cum_delta_180m`, and `cum_delta_60m` are computed from one continuous, globally sorted feed stream across all discovered CSV files; early rows can therefore reuse prior-file / prior-day tail history when it exists
- if any feed row inside the requested cumulative-delta window has missing `BuyQty` or `SellQty`, the cumulative delta field is `null` rather than silently zero-filling unknown flow
- these fields must remain distinct and are not interchangeable

The `ret_15m` and `ret_60m` fields are simple backward-looking price differences, not percentage returns.

## Not Implemented

`delta_analyzer` still does not implement:

- outcomes
- EMA or trend logic
- market-state classification
- setup taxonomy
- ML
- live trading logic
- signal generation

## CLI

Run:

```bash
python -m deltascout.delta_analyzer.cli
```

Optional overrides:

```bash
python -m deltascout.delta_analyzer.cli --archive-glob "deltascout/research_material/raw_archive/*.jsonl" --feed-glob "deltascout/research_material/raw_feed/*.csv"
python -m deltascout.delta_analyzer.cli --dataset events_base
python -m deltascout.delta_analyzer.cli --dataset events_context
python -m deltascout.delta_analyzer.cli --build-review --date YYYY-MM-DD --input-root /data/archive/datasets --output-root /data/archive/datasets
```

The default globs already point to the local research-material folder copied for DeltaScout research.

The review-builder mode is the Phase 2.5 skeleton only: it reads daily `events_context` plus optional `close_outcomes`, then writes accepted/reject review tables and a deterministic Markdown summary under `reviews/YYYY-MM-DD/`.
