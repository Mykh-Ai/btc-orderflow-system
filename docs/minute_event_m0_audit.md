# DeltaScout Minute Event M0 Audit

## Purpose

This memo records the code-level M0 audit for the minute-event analyzer expansion described in the minute-event research spec.

The goal of M0 is not to redesign the analyzer. The goal is to confirm the exact current code seams, dataset inventory, field contracts, and documentation drift before M1 begins.

## Scope Reviewed

Reviewed code and artifacts:

- `deltascout/delta_analyzer/cli.py`
- `deltascout/delta_analyzer/config.py`
- `deltascout/delta_analyzer/types.py`
- `deltascout/delta_analyzer/modules/archive_reader.py`
- `deltascout/delta_analyzer/modules/feed_reader.py`
- `deltascout/delta_analyzer/modules/matcher.py`
- `deltascout/delta_analyzer/modules/build_events_base.py`
- `deltascout/delta_analyzer/modules/context_features.py`
- `deltascout/delta_analyzer/modules/build_events_context.py`
- `deltascout/delta_analyzer/modules/build_review_tables.py`
- `deltascout/research_bundle/build_raw_micro.py`
- `deltascout/research_bundle/build_sequence_context.py`
- `deltascout/test/test_delta_analyzer_phase2_contracts.py`
- sample feed file `deltascout/research_material/raw_feed/2026-03-17.csv`
- sample review output `deltascout/research_material/reviews/2026-03-17/events_context_2026-03-17.csv`

## Current Analyzer Inventory

The analyzer is currently event-centric.

Implemented analyzer datasets:

- `events_base`
- `events_context`

Implemented review-layer outputs built from `events_context`:

- `accepted_event_context_YYYY-MM-DD.csv`
- `reject_event_context_YYYY-MM-DD.csv`
- `interesting_rejects_YYYY-MM-DD.csv`
- `reject_reason_summary_YYYY-MM-DD.csv`
- `daily_review_summary_YYYY-MM-DD.md`

Implemented bundle-side outputs that already reuse minute feed, but not as a first-class dataset:

- `selected_case_raw_feed_micro_*.csv`
- `selected_case_sequence_context_*.csv`

Important audit result:

- there is no standalone minute-granularity analyzer dataset in `delta_analyzer`
- minute feed is currently used either as:
  - matched context for archive events, or
  - selected-case bundle extraction

This confirms the main spec claim: minute-level rows are collected and reused, but not yet elevated into a foundational analyzer object.

## Current Feed Contract in Code

The real feed contract is defined by `feed_reader.py` plus the archived CSV headers.

### Loaded feed columns today

Directly loaded into `FeedRow`:

- `Timestamp`
- `Close`, fallback `ClosePrice`, fallback `AvgPrice`
- `BuyQty`
- `SellQty`
- `OpenInterest`
- `FundingRate`
- `LiqBuyQty`
- `LiqSellQty`

Present in archived research feed sample but not normalized into `FeedRow`:

- `Open`
- `High`
- `Low`
- `Volume`
- `AggTrades`
- `VWAP`
- `IsSynthetic`

### Current `FeedRow` shape

`FeedRow` currently contains:

- `ts`
- `price`
- `buy_qty`
- `sell_qty`
- `open_interest`
- `funding_rate`
- `liq_buy_qty`
- `liq_sell_qty`
- `row`
- `source_file`

Important implication:

- the code already preserves the raw CSV row in `FeedRow.row`
- this is the narrowest existing seam for M1 because missing normalized fields can be promoted from `row` without changing archive-event behavior first

## Current Archive / Event Contract

`archive_reader.py` normalizes archive JSONL into `NormalizedEvent` with:

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
- `source_file`
- `raw`

This layer is independent from minute-event modeling and does not need architectural change for M1.

## Current Derived Fields in Code

### `events_base`

`events_base` is built by matching each archive event to the latest feed row with `feed_ts <= event_ts`.

Fields:

- core event fields from archive
- `matched_feed_ts`
- `matched_open_interest`
- `matched_funding_rate`
- `matched_liq_buy_qty`
- `matched_liq_sell_qty`
- `terminal_decision_present`

### `events_context`

`events_context` extends `events_base` with:

- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`
- `dist_vwap`
- `abs_dist_vwap`
- `price_vs_vwap_side`

### Review-layer derived outputs

`build_review_tables.py` adds:

- accepted/reject table filtering
- close-outcome joins for accepted rows
- reject-reason grouped summaries
- rule-based `interesting_reject_*` fields

These are research review outputs, not foundational analyzer minute datasets.

## Minute-Granularity Support Already Present

There is partial minute-level support in the repository, but it lives outside the analyzer foundation.

### `research_bundle/build_raw_micro.py`

This already materializes minute rows around selected cases with fields such as:

- `Timestamp`
- `Close`
- `VWAP`
- `BuyQty`
- `SellQty`
- `OpenInterest`
- `FundingRate`
- `LiqBuyQty`
- `LiqSellQty`
- `IsSynthetic`
- derived `delta_1m`
- derived `vol_1m`
- derived `price_minus_vwap`

This is useful evidence that:

- the project already treats minute feed as analyzable research data in some workflows
- there is already precedent for computing minute-level descriptive mechanics

But this is still scoped to selected-case bundle generation, not a general analyzer dataset.

### `research_bundle/build_sequence_context.py`

This builds sequence context from review outputs, not raw minute feed.

It sits above the current event-centric layer and is not a candidate seam for M1.

## Matching and Windowing Rules Already Implemented

These rules matter because M1 should stay consistent where possible.

### Timestamp parsing

Current parsers normalize timestamps by:

- replacing `Z` with `+00:00`
- converting `" "` to `"T"` in analyzer ingestion

Raw micro bundle code separately parses feed timestamps with `%Y-%m-%d %H:%M:%S`.

### Matching rule

Event-to-feed matching is:

- latest feed row at or before event timestamp

### Rolling window rule

`events_context` uses one globally merged, timestamp-sorted feed history across all discovered CSV files.

Windows:

- do not reset at file or day boundaries
- do not pad missing history
- return `None` for cumulative delta if any row in the lookback has unknown `BuyQty` or `SellQty`

### Return rule

`ret_15m` and `ret_60m` are absolute price differences, not percentage returns.

## Audit Answers to the Required M0 Questions

### 1. Which analyzer datasets already exist in code?

Inside `delta_analyzer`:

- `events_base`
- `events_context`

Adjacent but not foundational analyzer datasets:

- daily review tables
- selected-case raw micro bundle
- selected-case sequence context bundle

### 2. Which feed columns are actually loaded today?

Normalized and loaded:

- timestamp
- close-like price
- buy/sell quantities
- open interest
- funding rate
- liquidation quantities

Present in source CSV but not normalized:

- OHLC except `Close`
- `Volume`
- `VWAP`
- `AggTrades`
- `IsSynthetic`

### 3. Are `OpenInterest`, `FundingRate`, `LiqBuyQty`, and `LiqSellQty` supported consistently across relevant code paths, or only partially?

They are supported consistently in the current event-centric analyzer path:

- loaded in `feed_reader.py`
- carried in `FeedRow`
- attached in `events_base`
- propagated through `events_context`
- written into review outputs

They are not yet used for foundational minute-level mechanics in `delta_analyzer`.

### 4. Which derived fields already exist beyond current documentation?

Already implemented:

- `terminal_decision_present`
- `abs_dist_vwap`
- `price_vs_vwap_side`
- review-layer `interesting_reject_*`
- grouped reject summary stats
- bundle-side `delta_1m`
- bundle-side `vol_1m`
- bundle-side `price_minus_vwap`

### 5. Does any minute-granularity dataset already exist in code or in partial form?

Yes, in partial form only:

- `selected_case_raw_feed_micro_*.csv`

No general-purpose minute-event analyzer dataset currently exists.

### 6. Where is the minimal safe seam for introducing `minute_events_base`?

The narrowest safe seam is:

- add a new minute dataset builder in `deltascout/delta_analyzer/modules/`
- extend `FeedRow` to normalize the additional minute fields required for M1
- add a new CLI dataset option for minute-event materialization

Why this is the safest seam:

- it is additive
- it does not require changing archive ingestion
- it does not require changing `events_base` / `events_context`
- it reuses the already canonical feed ingestion path
- it keeps minute-event foundation below the current event-centric layer instead of entangling them

### 7. Which current documents and code paths are inconsistent today?

Confirmed inconsistencies:

- [data-contracts.md](D:\Project_V\btc-orderflow-system\docs\data-contracts.md) describes an older aggregator schema centered on `Trades`, `TotalQty`, `AvgSize`, `AvgPrice`, `ClosePrice`, `HiPrice`, `LowPrice`
- the actual research feed used by the analyzer currently has enriched columns:
  - `Open`
  - `High`
  - `Low`
  - `Close`
  - `Volume`
  - `VWAP`
  - `OpenInterest`
  - `FundingRate`
  - `LiqBuyQty`
  - `LiqSellQty`
  - `IsSynthetic`

Additional mismatch:

- the spec language says minute feed is underused as a research surface
- the repository already has `build_raw_micro.py`, so the better phrasing is:
  minute feed is partially exploited in bundle workflows but not yet promoted into a reusable analyzer foundation layer

## Recommended M1 Implementation Seam

M1 should stay narrow and additive.

### Recommended code shape

Add:

- `MinuteEventRow` dataclass in `deltascout/delta_analyzer/types.py`
- `build_minute_events_base.py` in `deltascout/delta_analyzer/modules/`
- CLI dataset option `minute_events_base`

Extend `FeedRow` normalization to include:

- `open`
- `high`
- `low`
- `close`
- `vol_1m` from `Volume`
- `vwap`
- `is_synthetic`

Prefer keeping:

- existing `price` field for backward compatibility with current event-context logic
- `price` mapped to the current close-like value

### Recommended `minute_events_base` source

Use only feed CSV input.

Do not join archive events in M1.

One row should equal one normalized feed minute.

### Recommended M1 fields

Directly from feed:

- `ts`
- `day`
- `open`
- `high`
- `low`
- `close`
- `buy_qty`
- `sell_qty`
- `vol_1m`
- `vwap`
- `open_interest`
- `funding_rate`
- `liq_buy_qty`
- `liq_sell_qty`
- `is_synthetic`
- `source_file`

Derived in M1 only where trivial and fully deterministic:

- `delta_1m = buy_qty - sell_qty`
- `imbalance_1m = delta_1m / vol_1m` when both values are present and `vol_1m != 0`

### Recommended M1 storage and CLI behavior

The least disruptive pattern is to mirror the existing analyzer CLI behavior:

- `--dataset minute_events_base`
- optional `--date`
- optional CSV write when `--date` and `--output-root` are supplied

Recommended filename:

- `minute_events_base_YYYY-MM-DD.csv`

This keeps the output contract parallel to `events_context_YYYY-MM-DD.csv`.

## M1 Guardrails

M1 should not:

- infer taxonomy
- classify phase
- compute rolling percentile mechanics
- join to archive events
- alter review-table behavior
- alter `events_base` or `events_context` semantics

M1 should only establish:

- canonical normalized minute row contract
- deterministic null handling
- deterministic ordering
- deterministic materialization path

## Recommended M1 Tests

Minimum required tests:

- feed row normalization includes newly promoted fields
- `minute_events_base` row count equals normalized feed row count
- rows are timestamp-sorted
- `day` is derived correctly from `ts`
- `delta_1m` and `imbalance_1m` behave correctly
- optional fields remain null when source columns are missing or blank
- `is_synthetic` is preserved deterministically

## Final M0 Verdict

The current repository is ready for M1.

Reason:

- the feed ingestion seam already exists
- the repository already contains enriched minute-level source data
- there is already partial minute-level research usage in bundle workflows
- the missing piece is not data access but a canonical minute-event foundation dataset inside `delta_analyzer`

The narrowest safe next step is therefore:

- add `minute_events_base` as a feed-native analyzer dataset
- keep it fully additive
- defer all mechanics and taxonomy work until after M1 is stable
