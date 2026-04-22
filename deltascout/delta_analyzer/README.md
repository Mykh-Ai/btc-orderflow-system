# Delta Analyzer

`delta_analyzer` is a research-only foundation module for DeltaScout.

It exists to build a clean base layer for future analyzer work around:

- archive ingestion
- feed ingestion
- event-to-feed matching
- base event dataset creation
- archive and matching health checks
- backward-looking context reconstruction
- minute-level feed-native dataset creation

## Phase 1 Scope

Phase 1 implements only the foundation layer:

- read archive JSONL files
- read archived feed CSV files from the canonical `/opt/aitrader/feed/*.csv` default while preserving explicit CLI override support
- normalize rows into simple internal types, including additive support for optional `OpenInterest`, `FundingRate`, `LiqBuyQty`, and `LiqSellQty` columns when present
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

## Phase M1 Scope

Phase M1 adds `minute_events_base`, a feed-native analyzer dataset where one row equals one normalized feed minute.

Phase M1 currently adds:

- promoted normalized feed fields for `open`, `high`, `low`, `close`, `vol_1m`, `vwap`, and `is_synthetic`
- `minute_events_base` with deterministic `day`, `delta_1m`, and `imbalance_1m`
- CLI support for `--dataset minute_events_base`

This layer is intentionally foundational only. It does not classify events, assign phases, or alter the existing archive-event datasets.

## Phase M2a Scope

Phase M2a adds `minute_events_mechanics`, a descriptive dataset built above `minute_events_base`.

Phase M2a currently includes only:

- delta mechanics
- price-response mechanics
- VWAP / structure mechanics

## Phase M2b Scope

Phase M2b extends `minute_events_mechanics` with:

- OI mechanics
- liquidation mechanics

Funding mechanics, taxonomy, and process-phase logic are still not implemented.

## Phase M2.5 Scope

Phase M2.5 adds `minute_events_outcomes`, a deterministic forward-outcome dataset built above `minute_events_mechanics`.

Phase M2.5 currently includes:

- fixed-horizon forward returns
- symmetric upside / downside forward path extremes
- percentage threshold-hit flags and earliest time-to-hit fields
- threshold ordering fields
- derived `reference_direction` plus secondary favorable/adverse max fields

It remains feed-native and additive. It does not implement taxonomy, process-phase logic, setup validation, or trade-close logic.

## Phase M2.6 Scope

Phase M2.6 adds a research-only process-chain bridge above `minute_events_outcomes`.

Phase M2.6 currently includes deterministic derived outputs:

- `minute_event_chain_candidates`
- `minute_event_chain_reference_cases`
- `chain_cluster_summaries`

This layer remains provisional and hypothesis-driven. It is not final taxonomy or full process-engine truth.

## Not Implemented

`delta_analyzer` still does not implement:

- minute-event taxonomy
- process-phase labeling
- setup-family validation
- EMA or trend logic
- market-state classification
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
python -m deltascout.delta_analyzer.cli --archive-glob "<local-raw-archive>/*.jsonl" --feed-glob "<local-raw-feed>/*.csv"
python -m deltascout.delta_analyzer.cli --dataset events_base
python -m deltascout.delta_analyzer.cli --dataset events_context
python -m deltascout.delta_analyzer.cli --dataset minute_events_base
python -m deltascout.delta_analyzer.cli --dataset minute_events_base --date YYYY-MM-DD --output-root /data/archive/datasets
python -m deltascout.delta_analyzer.cli --dataset minute_events_mechanics
python -m deltascout.delta_analyzer.cli --dataset minute_events_mechanics --date YYYY-MM-DD --output-root /data/archive/datasets
python -m deltascout.delta_analyzer.cli --dataset minute_events_outcomes
python -m deltascout.delta_analyzer.cli --dataset minute_events_outcomes --date YYYY-MM-DD --output-root /data/archive/datasets
python -m deltascout.delta_analyzer.cli --build-review --date YYYY-MM-DD --input-root /data/archive/datasets --output-root /data/archive/datasets
python -m deltascout.delta_analyzer.cli --build-m2-6 --date YYYY-MM-DD --input-root /data/archive/datasets --output-root /data/archive/datasets
python -m deltascout.delta_analyzer.cli --build-m2-6 --date-from YYYY-MM-DD --date-to YYYY-MM-DD --input-root /data/archive/datasets --output-root /data/archive/datasets
```

The default archive glob still points to the local research-material archive sample. The default feed glob is now the canonical enriched archive path `/opt/aitrader/feed/*.csv`, and the analyzer fails loudly when that glob matches no files. Any explicit `--feed-glob` override still wins.

The review-builder mode is the Phase 2.5 review layer: it reads daily `events_context` plus optional `close_outcomes`, then writes accepted/reject review tables, `interesting_rejects_YYYY-MM-DD.csv`, `reject_reason_summary_YYYY-MM-DD.csv`, and a deterministic Markdown summary under `reviews/YYYY-MM-DD/`. `interesting_rejects_YYYY-MM-DD.csv` is the final planned Phase 2.5 review-layer extension; it does not introduce sequence-aware or transition-aware analysis, and true Phase 3 begins only when that later analysis layer is introduced. `event_sequence_review_YYYY-MM-DD.csv` remains an example of that later boundary and is not currently implemented.
