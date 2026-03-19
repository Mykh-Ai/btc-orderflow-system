# Delta Analyzer

`delta_analyzer` is a research-only foundation module for DeltaScout.

It exists to build a clean base layer for future analyzer work around:

- archive ingestion
- feed ingestion
- event-to-feed matching
- base event dataset creation
- archive and matching health checks

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

## Not Implemented

Phase 1 does not implement:

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
python -m deltascout.delta_analyzer.cli --archive-glob "deltascout/дослідницький матеріал/raw_archive/*.jsonl" --feed-glob "deltascout/дослідницький матеріал/raw_feed/*.csv"
```

The default globs already point to the local research-material folder copied for DeltaScout research.
