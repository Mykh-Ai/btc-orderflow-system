# Delta Analyzer Implementation Plan v1.1

## 1. Primary mission

`delta_analyzer` is a research-layer component for DeltaScout.

Its purpose is **not** to do academic market commentary, **not** to produce beautiful hindsight explanations, and **not** to mechanically expand the existing `PEAK` logic.

Its real purpose is:

- to help discover **tradable market behavior**,
- to identify **entry contexts with asymmetric move potential**,
- to separate noise from repeatable opportunity,
- and to support the creation of future setup classes that can make money in live trading.

The final business objective is simple:

> **find market states and entry contexts that can help generate profitable trades.**

Everything else is secondary.

The research target is not “more events”.
The research target is not “better-looking charts”.
The research target is not “more elegant theory”.

The research target is:

> **trading edge with real profit potential.**

In practical terms, the analyzer should prioritize contexts that can produce **large directional movement**, with special interest in moves on the order of **$1000+**.

---

## 2. Strategic framing

Existing `PEAK` events are important, but they are only a **reference class**.

They should be used as:

- a baseline,
- a source of comparison,
- an already working market-facing logic.

They should **not** define the full boundary of research.

The research layer must study the market as a system of **states, transitions, and recurring formations**, not as a collection of isolated delta spikes.

The intended order of research is:

**market state → transition → setup class → entry timing**

not:

**single event → instant signal conclusion**

This ordering matters because the project is not trying to predict every fluctuation.
It is trying to identify the conditions under which a trade has meaningful move potential.

---

## 3. Core research principles

### 3.1 Profit-first discipline

All research should be evaluated against the practical objective:

- can this help identify better trades?
- can this help avoid low-quality trades?
- can this help detect conditions that precede meaningful movement?
- can this eventually support profitable execution?

If a research path is interesting but does not move the project toward tradeable edge, it is lower priority.

### 3.2 Context over isolated events

A strong delta event is not sufficient on its own.

Each event must be studied together with:

- what happened before it,
- what happened after it,
- cumulative delta context,
- price behavior,
- VWAP / EMA location,
- structural state,
- local and broad flow alignment or divergence.

### 3.3 Market state first

The analyzer must learn to describe the broader market condition before evaluating local candidates.

Important states include:

- trend intact,
- trend weakening,
- transition,
- break underway,
- break confirmed,
- continuation,
- exhaustion,
- trap / false break,
- absorption-like non-progression,
- honest directional flow.

### 3.4 Research discipline

The analyzer and all future research agents must avoid the following:

- assuming outcome without testing,
- calling a signal strong only because it looks good in hindsight,
- drawing conclusions from a single event,
- mixing different regimes into one class,
- treating all rejects as missed opportunities,
- using filter-loosening as the default research path.

### 3.5 Existing PEAK is not the destination

Current `PEAK` logic remains valuable as a reference, but the main research objective is broader:

> discover new repeatable behavior classes that may later become future `PEAK` families.

---

## 4. High-level objectives

`delta_analyzer` must eventually answer the following questions:

1. What market states precede meaningful directional movement?
2. What orderflow/price/structure combinations repeat before large moves?
3. Which reject classes are merely noise, and which are suspiciously strong?
4. Which events belong to reversal onset, reversal confirmation, continuation, exhaustion, or trap contexts?
5. Which classes are associated with potential for large directional movement such as $1000+?
6. Which families deserve formalization into future `PEAK_*` setup classes?
7. Which findings are most likely to improve live trade selection and future profitability?

---

## 5. Non-goals

The first versions of `delta_analyzer` should **not** attempt to do the following:

- replace DeltaScout live logic,
- generate production execution signals,
- optimize thresholds for the current `PEAK` blindly,
- use ML before a stable feature and dataset layer exists,
- infer profitability from visual hindsight alone,
- collapse all event types into one generic “good/bad” score,
- drift into abstract research that does not help the trading mission.

---

## 6. Inputs

The analyzer will work from research materials already available in the project.

### Primary inputs
- `raw_archive/*.jsonl`
- `raw_feed/*.csv`

### Reference materials
- initial research notes / findings
- DeltaScout README and current signal logic documentation

### Event families currently present in archive
- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`
- `PEAK_EMIT`

---

## 7. Conceptual architecture

The analyzer should be built as a stack of research layers.

### Layer A — Ingestion and normalization
Responsibilities:
- read archive files,
- read matching feed files,
- normalize timestamps,
- standardize event rows,
- join event rows to feed rows,
- run archive/feed integrity checks.

Output:
- normalized event stream,
- normalized feed stream,
- event-to-feed linkage.

### Layer B — Feature extraction
Responsibilities:
- compute event-level features,
- compute rolling feed-context features,
- compute sequence-level features,
- compute regime and trend-state features.

Output:
- enriched research dataset.

### Layer C — Event framing
Responsibilities:
- classify each event into research context,
- distinguish reference PEAK behavior from reject behavior,
- separate reversal, transition, continuation, trap, and exhaustion-like contexts.

Output:
- framed event dataset with research labels.

### Layer D — Outcome layer
Responsibilities:
- compute forward movement and reaction metrics,
- attach MFE / MAE style outcome features,
- measure move potential after candidate events.

Output:
- event outcome dataset.

### Layer E — Discovery and reporting
Responsibilities:
- summarize funnels,
- compare candidate classes,
- report suspicious subgroups,
- prepare future setup-family candidates.

Output:
- research summaries,
- candidate setup reports,
- future PEAK-family research backlog.

---

## 8. Research datasets

The analyzer should produce at least four core datasets.

### 8.1 `events_base`
One row per archive event.

Suggested fields:
- `ts`
- `day`
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
- `terminal_decision_present`
- `source_file`

### 8.2 `events_context`
One row per event with local context.

Current validated Phase 2 fields:
- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`
- `dist_vwap`
- `abs_dist_vwap`
- `price_vs_vwap_side`

Future candidate context features:
- `cum_delta_day`
- `ret_5m`
- `ret_180m`
- `range_5m`
- `range_15m`
- `range_60m`
- `vol_pct_180`
- `imb_pct_180`
- `delta_pct_180`
- `delta_price_alignment_1m`
- `delta_price_alignment_60m`
- `cumdelta_price_divergence_flag`

These candidate fields should be treated as future context wishlist items, not as part of the currently validated Phase 2 contract.

### 8.3 `events_market_state`
One row per event with broader state description.

Suggested fields:
- `price_vs_ema21`
- `price_vs_ema50`
- `ema21_slope`
- `ema50_slope`
- `distance_to_ema21`
- `distance_to_ema50`
- `trend_state`
- `structure_state`
- `flow_state`
- `transition_state`
- `extension_state`

### 8.4 `events_outcomes`
One row per event with forward reaction metrics.

Suggested fields:
- `fwd_ret_5m`
- `fwd_ret_15m`
- `fwd_ret_30m`
- `fwd_ret_60m`
- `mfe_15m`
- `mae_15m`
- `mfe_60m`
- `mae_60m`
- `did_move_500`
- `did_move_1000`
- `did_move_1500`
- `time_to_500`
- `time_to_1000`
- `adverse_before_1000`

---

## 9. Feature groups

### 9.1 Event-level features
These describe the event itself.

Examples:
- raw delta metrics,
- absolute delta,
- volume,
- imbalance,
- price,
- close,
- high / low,
- VWAP,
- POC,
- distance from VWAP,
- price-vs-VWAP side.

### 9.2 Sequence-level features
These describe the event within the stream of nearby events.

Examples:
- previous peak kind,
- previous delta event kind,
- minutes since previous peak,
- minutes since previous delta event,
- same-direction flag,
- alternation count,
- streak length,
- event density in 30m / 60m windows,
- comparison fail decomposition for `3of3` style rejects.

### 9.3 Feed-context features
These describe local flow and price behavior.

Examples:
- cumulative delta on multiple horizons,
- cumulative buy and sell,
- rolling returns,
- local ranges,
- rolling percentiles,
- alignment between delta and price,
- divergence flags,
- proximity to strong delta zones,
- distance to strong delta zones,
- return-to-delta-zone behavior,
- reaction after revisit of strong delta zones.

### 9.4 Regime/context features
These describe the broader market condition.

Examples:
- price vs EMA21 / EMA50,
- EMA slopes,
- trend state,
- structure break state,
- extension / exhaustion state,
- honest flow vs divergence,
- transition state,
- broad vs local context disagreement.

---

## 10. Research taxonomy

The analyzer should not force every event into a single binary good/bad frame.

It should support a research taxonomy such as:

### A. Reversal onset
The first serious sign that the previous phase is breaking.

### B. Reversal confirmation
The break is no longer only a possibility; structure is visibly shifting.

### C. Continuation pressure
The break already happened and the market continues in the same direction.

### D. First opposing burst
The first strong opposing delta after a strong directional burst.

### E. Honest flow alignment
Delta and price move together in a clean directional manner.

### F. Divergence / delayed release
Cumulative flow builds while price holds, then releases later.

### G. Exhaustion / late extension
The move is already stretched and may be losing quality.

### H. Trap / false break
The event appears directional but quickly reverses or fails.

### I. Strong delta zone interaction
Price later returns to a strong delta area and either launches, rejects, absorbs, or fails there.

These are research labels, not live signals.

---

## 11. Implementation phases

## Phase 1 — Foundation
Goal:
- build normalized archive/feed ingestion,
- create event-to-feed matching,
- produce archive health checks,
- generate the first base event dataset.

Deliverables:
- normalized readers,
- matching layer,
- integrity report,
- `events_base` dataset.

Success criteria:
- each archive event can be traced to feed context,
- missing or unmatched cases are explicitly flagged,
- raw delta events without terminal decision can be detected.

---

## Phase 2 — Feature layer v1
Goal:
- enrich events with immediate feed context.

Deliverables:
- `events_context` dataset,
- cumulative delta features,
- local return/range features,
- delta-price alignment features,
- VWAP distance features.

Success criteria:
- each event can be described not only by its own row but also by its 60m/180m/day context.

## Phase 2.5 — Review Builder Layer

### Purpose

Phase 2.5 introduces a deterministic research-review build layer on top of the already validated Phase 2 `events_context` dataset.

Its purpose is **not** to expand signal logic or redesign PEAK.
Its purpose is to convert archived daily materials into a research-operable review package that helps accumulate evidence for:

- market state,
- transition behavior,
- candidate setup classes,
- and later entry-timing research.

This layer exists because Phase 2 already provides useful backward-looking event context, but that context still needs to be transformed into daily review artifacts that can support ongoing research.

### Position in the roadmap

Phase 2.5 sits between:

- **Phase 2** — backward-looking event context reconstruction
- and later phases that may introduce:
  - sequence analysis,
  - market-state classification,
  - setup taxonomy,
  - or richer outcome-aware research layers

Phase 2.5 is intentionally narrow.
It should be treated as a **review-package builder**, not as a new prediction layer.

### Why this layer is needed

At this point, DeltaScout already preserves:

- archive events,
- feed data,
- `events_context`,
- accepted `PEAK_EMIT` rows when present,
- and close outcomes as a separate research-side source

However, these materials still remain too fragmented for disciplined daily research unless they are assembled into deterministic review outputs.

Without this layer:

- accepted events remain isolated,
- rejects remain difficult to triage systematically,
- reject reasons are hard to review against real context,
- and transition-like sequences remain hidden inside raw rows.

Phase 2.5 solves that by producing daily review artifacts that can be accumulated over time.

### Non-goals

Phase 2.5 does **not** include:

- market-state classification as established truth
- setup classification as established truth
- outcome prediction
- profitability ranking
- signal scoring
- live-trading logic changes
- mechanical filter loosening
- backtester logic
- broad feature-family expansion without evidence

### Inputs

For a target UTC date `YYYY-MM-DD`, Phase 2.5 consumes:

- raw archive for that date
- raw feed for that date
- `events_context` for that date
- `close_outcomes` for that date, when present

The close-outcome source remains an **external research-side join input**, not part of the Phase 2 `events_context` contract itself.

### Outputs

For each processed date, the builder should write a daily review package under a deterministic output path.

Recommended output directory:

- `data/archive/datasets/reviews/YYYY-MM-DD/`

Required outputs:

- `accepted_event_context_YYYY-MM-DD.csv`
- `reject_event_context_YYYY-MM-DD.csv`
- `interesting_rejects_YYYY-MM-DD.csv`
- `reject_reason_summary_YYYY-MM-DD.csv`
- `event_sequence_review_YYYY-MM-DD.csv`
- `daily_review_summary_YYYY-MM-DD.md`

CSV tables are the **primary outputs**.
The Markdown file is a **derived human-readable summary** and must be generated from the tables rather than written manually.

### Output contracts

#### 1. accepted_event_context

One row per accepted archive event (`PEAK_EMIT`).

Purpose:

- anchor accepted events in backward-looking context
- connect accepted events to downstream close outcomes through external research joins
- accumulate accepted reference cases

Expected fields include:

- accepted event identity fields
- base archive fields already available for the row
- current Phase 2 context block:
  - `cum_delta_24h`
  - `cum_delta_180m`
  - `cum_delta_60m`
  - `ret_15m`
  - `ret_60m`
  - `dist_vwap`
  - `abs_dist_vwap`
  - `price_vs_vwap_side`
- close-outcome join fields when available:
  - `join_status`
  - `join_confidence`
  - `close_ts`
  - `close_reason`
  - `entry`
  - `side`

#### 2. reject_event_context

One row per reject event, including both:

- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`

Purpose:

- preserve rejected candidates as research objects
- support reject-funnel analysis
- allow reject reasoning to be checked against real context

Expected fields include:

- reject timestamp
- reject event type
- candidate kind
- reject reason
- current Phase 2 context block
- selected raw archive fields already present on the row

#### 3. interesting_rejects

A research triage subset of `reject_event_context`.

Purpose:

- identify rejects that do **not** look trivially weak
- surface transition-like, continuation-like, or ambiguity-rich rejects for later review
- create a repeatable watchlist for behavior-class discovery

This output must remain deterministic and auditable.

Initial helper fields may include:

- `interesting_reject_flag`
- `interesting_reject_bucket`
- `interesting_reject_note`

Initial buckets should be treated as **research buckets**, not established setup classes.
Examples:

- `possible_reversal_onset`
- `possible_reversal_confirmation`
- `possible_continuation_pressure`
- `possible_exhaustion_probe`
- `possible_trap_or_false_break`
- `unclear_but_constructive`

#### 4. reject_reason_summary

Daily aggregate by reject reason.

Purpose:

- quantify how reasons distribute within the day
- test whether dominant reasons align with real context rather than merely dominating by count
- support later reason-quality review

Expected fields may include:

- `date`
- `reject_reason`
- `count`
- `kind`
- summary statistics for:
  - `cum_delta_60m`
  - `cum_delta_180m`
  - `ret_15m`
  - `dist_vwap`

#### 5. event_sequence_review

One row per archive event with sequence helper fields.

Purpose:

- begin structured sequence analysis without yet introducing a full market-state engine
- surface transition behavior
- detect local event chains such as terminal push, opposite response, continuation burst, or exhaustion-like response

Expected helper fields may include:

- `prev_event_ts`
- `prev_event_type`
- `prev_kind`
- `prev_reject_reason`
- `minutes_since_prev_event`
- `minutes_since_prev_same_kind`
- `minutes_since_prev_opposite_kind`
- `prev_peak_emit_within_15m`
- `prev_peak_emit_within_30m`
- `opposite_reject_within_15m`
- `same_kind_reject_within_15m`
- `same_kind_extreme_count_30m`
- `opposite_kind_extreme_count_30m`

These are sequence-support fields only.
They are **not** yet market-state labels.

#### 6. daily_review_summary

A deterministic Markdown summary built from the daily CSV outputs.

Purpose:

- provide a human-readable daily research snapshot
- summarize event counts, reject distribution, accepted coverage, close-outcome linkage, and interesting rejects
- help maintain a growing archive of reviewed research days

It should include:

- event counts by type
- reject counts by reason
- accepted count
- accepted-to-close linkage count
- interesting-reject count
- short sequence notes derived from tables
- short research implications

### Design principles

Phase 2.5 must follow these rules:

- tables first, prose second
- deterministic outputs only
- no LLM-authored hidden logic inside the builder
- no hindsight-labeled “winners”
- no treating all rejects as missed trades
- no broad setup claims from one day
- no phase-scope leakage into live trading logic

### Implementation shape

Recommended new modules:

- `modules/build_review_tables.py`
- `modules/sequence_features.py`
- `modules/review_triage.py`
- `modules/review_outputs.py`

Recommended responsibilities:

#### build_review_tables.py
- orchestrate daily review-package build
- load `events_context`
- load `close_outcomes`
- build accepted and reject review tables
- call sequence and triage helpers
- save outputs

#### sequence_features.py
- build deterministic sequence helper fields
- remain low-level and descriptive
- avoid market-state claims

#### review_triage.py
- apply transparent triage rules
- assign `interesting_reject_flag`
- assign initial `interesting_reject_bucket`

#### review_outputs.py
- write CSV artifacts
- build deterministic Markdown summary from output tables

### CLI integration

A new CLI mode should be added for review-package generation.

Recommended pattern:

- `python -m deltascout.delta_analyzer.cli --build-review --date YYYY-MM-DD --input-root ... --output-root ...`

### Incremental build discipline for Phase 2.5+

This is a **forward design rule** for Phase 2.5 and later review/output layers.
It describes the intended long-term operating model.
It does **not** claim that incremental manifests or rebuild-skipping logic already exist today unless later implementation explicitly adds them.

The current research archive is still small, so occasional full-history rebuilds remain acceptable during active phase development, schema churn, and research iteration.
However, as the archive grows across multiple months, routine analyzer and review runs should become **incremental by default**.
A full rebuild should remain available, but only as an **explicit operator action**.

#### Operating modes

Future Phase 2.5+ builders should distinguish between two operating modes:

1. **Incremental update**
   - the routine default mode
   - process only dates that are new, missing, incomplete, outdated, explicitly marked dirty, or otherwise eligible for rebuild
2. **Full rebuild**
   - an intentional operator-triggered mode
   - recompute all targeted dates after builder/schema/version changes, migration work, or deliberate historical regeneration

#### Date-scoped outputs

Review and output artifacts should remain **date-scoped**.
They should be built by:

- a single date, or
- an explicit date range

Future routine operation should **not** blindly recompute the entire archived research base on every run.

#### Lightweight processed-days manifest

To support future incremental behavior, each review or output family may maintain a lightweight manifest or registry.
This should stay simple and file-based unless a stronger need appears later.

A per-date manifest row or entry may include:

- `date`
- `output_family`
- `build_status`
- `built_at`
- `builder_version` or `schema_version`
- optional `dirty` / `needs_rebuild`

This is intentionally minimal.
It does **not** require database infrastructure, queue orchestration, content hashes, or DAG scheduling as part of the Phase 2.5 design rule.

#### Minimal rebuild criteria

In future incremental mode, a date should be eligible for rebuild if any of the following are true:

- expected outputs are missing
- prior build status is not successful
- builder/schema version changed
- source inputs changed materially
- operator requests a force rebuild
- the date is explicitly marked dirty

Otherwise, a date with already-built successful outputs should normally be skipped during routine runs.

#### Watcher relationship

The future post-close watcher should remain naturally incremental.
For ordinary daily operation, it should process only the date implied by the newly detected close event.
It should **not** trigger full-history analyzer or review rebuilds as part of the normal daily path.

This mode should:

1. locate the required daily inputs
2. fail clearly if required inputs are missing
3. build the review package deterministically
4. report created files and key counts

### Runbook integration

After the close-outcome rebuild runbook completes, the next automated server step should run the review builder.

Expected order:

1. rebuild Phase 1 derived datasets
2. rebuild close outcomes
3. build review package
4. report created review artifacts

This keeps the research workflow deterministic and repeatable.

### Success criteria

Phase 2.5 should be considered successful when:

- daily review-package outputs are produced deterministically
- accepted events are context-linked and externally joinable to close outcomes
- rejects are preserved as research objects rather than discarded noise
- interesting rejects can be surfaced reproducibly
- reject reasons can be reviewed against real context
- basic event-sequence helpers become available for later research phases

### Strategic value

Phase 2.5 does not claim to solve setup discovery directly.

Its value is that it begins turning raw archived behavior into structured research evidence for later discovery of:

- continuation pressure
- failed continuation
- reversal onset
- reversal confirmation
- exhaustion
- trap / false break
- other repeatable behavior classes that may later support profitable entries

That is why this layer is justified now.
It improves the research stack without pretending that setup classes are already known.

---

## Phase 3 — Sequence layer
Goal:
- represent each event as part of a sequence, not an isolated point.

Status note:
- Phase 3 remains a future layer.
- It is not the immediate next step after Phase 2.
- The immediate next step is the Phase 2.5 review loop built on top of validated `events_context`.
- Phase 3 planning should begin only after enough evidence accumulates from repeated Phase 2.5 review outputs.

Deliverables:
- sequence features,
- previous-event linkage,
- streak / alternation metrics,
- reject decomposition for comparison-stage events.

Success criteria:
- analyzer can distinguish first opposing burst, repeated continuation burst, and isolated event.

---

## Phase 4 — Market-state layer
Goal:
- detect broader market condition and transition state.

Deliverables:
- `events_market_state` dataset,
- EMA context,
- trend-state labels,
- structure-state labels,
- flow-state labels.

Success criteria:
- analyzer can describe whether an event belongs to trend continuation, trend break onset, trend break confirmation, exhaustion, or trap context.

---

## Phase 5 — Outcome layer
Goal:
- attach forward reaction metrics to events.

Deliverables:
- `events_outcomes` dataset,
- forward return windows,
- MFE/MAE metrics,
- move-threshold metrics such as $500 / $1000 / $1500.

Success criteria:
- suspicious-looking classes can be tested against real forward movement rather than visual hindsight.

---

## Phase 6 — Setup discovery
Goal:
- identify recurring event families that deserve focused study.

Deliverables:
- subgroup comparison reports,
- setup candidate summaries,
- early research ranking of candidate classes.

Success criteria:
- analyzer can point to repeated behavior classes rather than only individual examples.

---

## Phase 7 — Future PEAK-family research
Goal:
- transform validated behavior classes into formal candidate setup families.

Possible future research families:
- `PEAK_TB1`
- `PEAK_TB2`
- `PEAK_CONT`
- `PEAK_TRAP`
- `PEAK_ABS`
- `PEAK_ALIGN`

Success criteria:
- the project has an evidence-backed path from raw market behavior to future signal families.

---

## 12. Priority roadmap

### Current status
- Phase 1: closed
- Phase 2: closed and validated
- Immediate next step: Phase 2.5 review loop

### Next
Should focus on:
- accepted-event to close-outcome research linkage
- interesting reject triage
- reject reason / context sanity review
- repeated daily review outputs built on top of validated `events_context`

### After Phase 2.5 evidence accumulates
Should focus on:
- evidence-based Phase 3 planning
- evidence-based state-layer review
- evidence-based outcome-layer expansion

---

## 13. Key risks and blind spots

The analyzer design must acknowledge the following risks:

1. **Hindsight bias**
Visual post-hoc interpretation can be misleading without formal outcome measurement.

2. **Small-sample overfitting**
A few strong examples may not represent a stable class.

3. **Regime mixing**
Events from different market regimes can look similar locally but behave very differently.

4. **Single-metric overreliance**
No single metric — not delta, not cumulative delta, not VWAP distance — should dominate interpretation alone.

5. **Archive completeness issues**
Research conclusions may be distorted if event streams or feed links are incomplete.

6. **Premature signalization**
The analyzer must not be pushed into live logic before the research layer is mature.

---

## 14. Guiding principle

Every future model, analyzer, and research agent in DeltaScout should follow this principle:

> DeltaScout Research does not exist to worship the current PEAK logic. It exists to map market behavior, discover repeatable formations, reconstruct market state, and turn validated behavior classes into future trading setup families with real profit potential.

And one more rule:

> If a research direction does not improve the ability to find profitable trades, it is not a core priority.

---

## 15. Final implementation stance

`delta_analyzer` should be built as a **market behavior research engine**.

It is not merely:
- a reject analyzer,
- a PEAK expander,
- or a delta event summarizer.

It is a structured way to answer:

- what state the market is in,
- what transition may be underway,
- what class of event is happening,
- and whether that class has the potential to produce meaningful movement.

That is the correct foundation for discovering future DeltaScout setup families and, ultimately, improving trading results.
