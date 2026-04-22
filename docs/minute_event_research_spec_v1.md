# DeltaScout Minute Event Research Spec v1

## Purpose

This document translates the research shift defined in the local DeltaScout research blueprint into an implementation-oriented analyzer roadmap.

Its purpose is to make **minute-level market data** a first-class research surface inside DeltaScout.

It does **not** replace the broader blueprint.
It operationalizes the next analyzer layers required to make that blueprint technically meaningful.

This is a **foundation-layer spec for minute-level research**.
It defines the analyzer foundation and near-term expansion needed before stronger event formation, setup discovery, and edge validation become credible.

It is **not**:

- a full edge-discovery layer
- a full setup-discovery implementation contract
- a full process-phase model

---

## Relationship to `research_blueprint_v2.md`

`research_blueprint_v2.md` defines the **research worldview**:

- market state
- transition
- process phase
- entry timing

This document defines the **next implementation path** for the analyzer.

Current market-data state note:

- the project has a local Aggregator archive contour at `/data/archive/feed/YYYY-MM-DD.csv`
- the current analyzer/offline workflow also reads a separate external contour at `/opt/aitrader/feed/YYYY-MM-DD.csv`
- runtime `PEAK` generation still comes from live `aggregated.csv`, not from either daily archive path directly

This spec treats that split as part of the current real system state. It describes the two feed contours as separate sources in current workflow.

Working relationship:

- `research_blueprint_v2.md` = strategic research frame
- `minute_event_research_spec_v1.md` = foundation and near-term implementation continuation

This document does not invalidate the existing `PEAK` / reject research layer.

Instead, it fixes the next expansion:

- `PEAK` / reject layer remains a **decision-layer diagnostics surface**
- the next analyzer expansion must elevate **minute-level rows** into a **first-class observation layer**

---

## Current problem statement

The current analyzer already builds useful archive-event and review outputs.

It already supports:

- archive event ingestion
- feed ingestion
- event-to-feed matching
- `events_base`
- `events_context`
- accepted/reject review outputs
- additive matched feed enrichment for:
  - Open Interest
  - Funding Rate
  - Liquidation fields

However, the current practical research front view remains too **decision-heavy**.

Current bias:

- focus on `PEAK`
- focus on rejects around `PEAK`
- focus on family decomposition inside the current grammar layer

What remains underdeveloped:

- minute-level market observations as primary research substrate
- systematic use of **every minute delta**
- integrated reading of:
  - price response
  - OI response
  - funding context
  - liquidation context

This means the project already collects and references rich minute-level data across more than one feed contour, but the analyzer still underuses that data as a research surface.

The immediate problem is **not** only data collection.

The immediate problem is **underexploitation of already collected minute-level feed data**, together with insufficiently explicit contour separation between the local Aggregator archive and the external research feed used by analyzer workflows.

The repository already contains partial minute-level usage in bundle workflows, but that usage is not yet promoted into a reusable analyzer foundation layer.

---

## Primary implementation shift

The primary analyzer object should expand from:

- archived decision events

Toward:

- **minute-level observation rows**

This does **not** mean removing or replacing existing archive-event layers.

It means adding a lower, more fundamental research layer beneath them.

Desired shift:

- from selected grammar outputs as the dominant front view
- toward minute-level market behavior as the foundational front view

In practical terms:

> the analyzer should stop treating minute feed mainly as background context for selected archive decisions

and start treating:

> each 1-minute row as a first-class observation row,
> with significant rows later promotable into stronger interpreted research objects

This preserves the strategic importance of minute-level rows without collapsing raw observation and later interpreted event logic into the same thing.

---

## Scope of this document

This document defines the next implementation-oriented analyzer phases.

It does **not** attempt to immediately implement:

- full process-phase modeling
- full setup taxonomy
- live DeltaScout logic changes
- ML
- profitability ranking
- signal generation
- final setup validation

This document is limited to the analyzer expansion required before those later layers become credible.

Immediate and near-term target scope:

- code-level audit of current minute-feed usage
- `minute_events_base`
- `minute_events_mechanics`
- `minute_events_outcomes`

Later layers such as:

- event taxonomy
- sequence analysis
- process-phase assignment

remain explicitly later phases.

---

## Core implementation principle

DeltaScout should no longer treat minute feed primarily as support context for selected archive decisions.

Instead, it should begin from this principle:

> each minute should be retained first as a first-class observation row,
> and only later connected to sequence, process, setup, and `PEAK` diagnostics

This is the implementation consequence of the broader research shift already fixed in the blueprint.

---

## Implementation phases

## Phase M0 - Code Audit

### Goal

Establish the exact current analyzer state at code level before new implementation work begins.

This phase exists because current understanding is partly document-based and may not fully reflect the exact code path inventory.

### Required audit questions

The audit must answer:

1. Which analyzer datasets already exist in code?
2. Which feed columns are actually loaded today?
3. Are `OpenInterest`, `FundingRate`, `LiqBuyQty`, and `LiqSellQty` supported consistently across relevant code paths, or only partially?
4. Which derived fields already exist beyond current documentation?
5. Does any minute-granularity dataset already exist in code or in partial form?
6. Where is the minimal safe seam for introducing `minute_events_base`?
7. Which current documents and code paths are inconsistent today?

### Deliverables

Phase M0 should produce:

- a code-level audit memo
- an exact inventory of:
  - existing datasets
  - existing feed fields
  - existing derived fields
  - missing minute-event seams
- a recommendation for the narrowest safe implementation seam for M1

### Non-goals

Phase M0 must **not**:

- implement large new functionality
- redesign analyzer architecture broadly
- introduce taxonomy logic
- add speculative new abstractions without evidence

---

## Phase M1 - `minute_events_base`

### Goal

Create the first minute-level analyzer dataset where:

- one row = one minute-level observation
- the row is treated as a standalone feed-native record
- the dataset remains descriptive and foundational

This phase is intentionally narrow.

### Output dataset

- `minute_events_base`

### Minimum required fields

#### Identity
- `ts`
- `day`

#### Price
- `open`
- `high`
- `low`
- `close`

#### Volume / delta
- `buy_qty`
- `sell_qty`
- `vol_1m`
- `delta_1m`
- `imbalance_1m`

#### Structure anchor
- `vwap`

#### Participation
- `open_interest`
- `funding_rate`
- `liq_buy_qty`
- `liq_sell_qty`

#### Feed metadata
- `is_synthetic`
- `source_file`

### Required behavior

Phase M1 should define:

- sorting rules
- timestamp normalization rules
- null-handling rules
- output contract for missing optional fields
- dataset naming and storage conventions
- CLI or builder integration path

### Deliverables

Phase M1 should produce:

- `minute_events_base`
- schema / field contract
- CLI or equivalent build entry
- tests validating:
  - field presence
  - row count expectations
  - timestamp ordering
  - null handling for optional fields

### Non-goals

Phase M1 must **not** yet include:

- event taxonomy
- sequence logic
- process-phase assignment
- setup classification
- profitability or move-potential claims

---

## Phase M2 - `minute_events_mechanics`

### Goal

Add a mechanics layer on top of `minute_events_base`.

This layer should describe how the minute behaves, without yet assigning full event classes.

M2 should remain **descriptive**, not classificatory.

### Output dataset

- `minute_events_mechanics`

This may either:
- extend `minute_events_base`, or
- be materialized as a separate enriched dataset

The implementation choice should remain narrow and additive.

### Required mechanics groups

## 1. Delta mechanics

Required fields:

- `abs_delta_1m`
- `delta_sign`
- `delta_to_vol_ratio`
- `delta_pct_60m`
- `delta_pct_180m`
- `vol_pct_60m`
- `vol_pct_180m`

Purpose:

- distinguish ordinary minute from local delta extreme
- measure significance relative to recent background

---

## 2. Price-response mechanics

Required fields:

- `close_minus_open`
- `high_minus_low`
- `body_to_range_ratio`
- `close_location_in_range`
- `price_move_sign`
- `delta_price_alignment_1m`
- `delta_price_efficiency_1m`

Purpose:

- distinguish aggressive delta with real progress from aggressive delta with weak progress

---

## 3. VWAP / structure mechanics

Required fields:

- `dist_from_vwap`
- `abs_dist_from_vwap`
- `price_vs_vwap_side`
- `high_above_vwap_flag`
- `low_below_vwap_flag`

Purpose:

- preserve structural reading of the minute without collapsing structure into one hard gate

---

## 4. OI mechanics

Required fields:

- `oi_change_1m`
- `abs_oi_change_1m`
- `oi_change_pct_60m`
- `oi_change_pct_180m`
- `delta_oi_alignment_flag`
- `price_oi_alignment_flag`

Initial interpretation targets:

- new participation
- unwind
- unclear / churn

Purpose:

- distinguish fresh positioning from weak participation or unwind-driven movement

---

## 5. Liquidation mechanics

Required fields:

- `liq_total_1m`
- `liq_imbalance_1m`
- `liq_dominant_side`
- `liq_burst_flag`
- `delta_vs_liq_relation_flag`

Purpose:

- distinguish forced liquidation bursts from more organic market bursts

---

## 6. Funding context

Required fields:

- `funding_sign`
- `funding_abs`
- `funding_pct_24h` or equivalent local percentile if feasible
- `crowded_side_flag`

Purpose:

- make funding usable as context rather than passive metadata

### Deliverables

M2 may be implemented in narrow staged slices, for example M2a and M2b, as long as the layer remains additive and descriptive.

Phase M2 should produce:

- enriched mechanics dataset
- field-level schema updates
- tests for:
  - rolling percentile behavior
  - null handling
  - optional field handling
  - consistency of derived mechanics

### Non-goals

Phase M2 must **not** yet include:

- `event_class_primary`
- sequence classification
- process-phase assignment
- setup-family modeling
- PEAK logic changes
- move-potential conclusions

---

## Phase M2.5 - `minute_events_outcomes`

### Goal

Add an explicit forward-outcome layer above mechanics and below taxonomy.

This phase exists to measure **post-minute forward behavior** before minute-event classes are promoted into stronger research claims.

M2.5 is the bridge between:

- descriptive mechanics
- later typed / taxonomy-style event formation

### Output dataset

- `minute_events_outcomes`

### Role of this layer

M2.5 should answer questions such as:

- what happened after this minute over fixed forward horizons?
- did later price path show favorable follow-through, adverse follow-through, or both?
- how often did a mechanically interesting minute lead to real move expansion versus weak or noisy continuation?

This layer is still deterministic and evidence-oriented.
It is **not** setup validation, but it is the correct next step before stronger event-class claims.

### Audit-based seam guidance

The M0.1 outcome seam audit established that the repository already contains some reusable outcome-adjacent infrastructure, including deterministic feed loading, timestamp normalization, selected-case path extraction patterns, and trade-close linkage utilities.

However, the repository does **not** already contain a strong reusable forward outcome builder for arbitrary minute rows.

Therefore the safest M2.5 seam is:

- a fresh additive `minute_events_outcomes` builder
- likely under `deltascout/delta_analyzer/modules/`
- reusing utility patterns where helpful, but not repurposing trade-close builders as the primary implementation path

### Candidate outcome metrics

Examples of the kinds of fields that belong in M2.5:

- forward returns at fixed horizons
- forward max favorable move
- forward max adverse move
- threshold-hit metrics
- time-to-threshold
- adverse-before-favorable style metrics

These are examples of the correct bridge layer after M2.
They are **not** presented here as already implemented.

### Deliverables

Phase M2.5 should produce:

- a deterministic outcome-linked dataset above `minute_events_base` or `minute_events_mechanics`
- explicit horizon / window definitions
- tests for forward-window behavior, null handling, and threshold semantics

### Non-goals

Phase M2.5 must **not** yet include:

- event taxonomy
- process-phase claims
- setup-family promotion as established truth
- profit claims
- full setup validation

What is valid here:

- basic deterministic event outcome metrics
- repeatable forward-path measurement
- evidence needed for later move-potential and asymmetry research

---

## Phase M3 - `minute_events_typed` (later phase)

### Goal

Introduce an initial transparent, rule-based taxonomy of minute events.

This phase is explicitly **later** than M2 and M2.5.

It should only begin after:

- M2 review is complete
- M2.5 outcome layer exists
- enough outcome-linked evidence has accumulated to justify stronger class formation
- base and mechanics layers are stable and trusted

### Possible future outputs

- `event_class_primary`
- `event_class_confidence`
- `event_class_note`
- optional `event_class_secondary`

### Candidate future classes

Examples only:

- honest directional burst
- aggressive but weak progress
- absorption-like event
- squeeze / liquidation burst
- unwind-like move
- continuation impulse
- opposing trap burst
- exhaustion spike
- neutral churn

These are future research classes, not current implementation requirements.

---

## Phase M4 - Sequence / Process Extensions (later phase)

### Goal

Use minute-event classes and mechanics to build:

- sequence logic
- process-phase interpretation
- phase-marker vs entry-candidate distinctions

This phase is explicitly out of current implementation scope.

### Working process-chain hypothesis for later research

Future minute-event discovery should not be constrained by the current `PEAK` gate logic.

Minute rows remain first-class observation rows even when they do not map cleanly onto current `PEAK` / reject boundaries.

In this later research frame, `PEAK` / reject remains a diagnostics layer, not the boundary of discovery.

One working hypothesis to test is that strong minute-event families may appear as linked process stages rather than isolated standalone classes.

That means future sequence / process extensions may need to model both:

- family-level hints
- chain-role hints

Candidate chain-role hints for later-phase research:

- `seed`
- `release`
- `continuation`
- `late/exhaustion`

This is a working research/process-chain hypothesis only.

It is not validated truth, and it is not already-implemented runtime logic.

Current family findings should therefore be treated as an initial discovery surface only: evidence-bearing early families, not the final boundary of future `AI_Emit` or minute-event discovery.

Future research must remain open to additional families, subfamilies, and chain roles beyond the currently observed examples. The current process-chain lens is a working extension, not a closed taxonomy.

It should only begin after:

- M0 audit is complete
- M1 base layer exists
- M2 mechanics layer exists
- M2.5 outcome layer exists
- M3 classification is credible enough to sequence

---

## Explicit non-goals for current implementation scope

The current implementation scope must **not** be allowed to expand into:

- live DeltaScout signal logic changes
- broad refactors unrelated to minute-event layer
- PEAK-family redesign
- process-phase labeling as established truth
- setup ranking
- full setup validation
- profit claims
- ML
- hidden heuristic layers not documented transparently

This spec is for analyzer foundation expansion, not for premature setup conclusions.

It does **not** prohibit deterministic outcome measurement as a next bridge layer.
What remains out of scope is promoting those measurements into validated setup truth too early.

---

## Expected implementation outputs

At the end of the immediate implementation scope, the analyzer should support:

1. a narrow code-level audit output
2. `minute_events_base`
3. `minute_events_mechanics`
4. `minute_events_outcomes`
5. schema documentation updates
6. tests
7. a concise build or CLI path for generating minute-event datasets

Optional but desirable as a small operational enhancement:

- concise summary output showing
  - row counts
  - field coverage
  - missing optional-field rates
  - basic mechanics or outcomes coverage sanity checks

---

## Codex workflow guidance

This section exists to keep implementation disciplined.

### Required task order

1. **M0 audit first**
2. manual review of audit findings
3. define and stabilize M1
4. define and review M2
5. define and review M2.5
6. only then define M3 / taxonomy work

### Important rule

Do **not** combine:

- M0
- M1
- M2
- M2.5
- taxonomy
- sequence logic

into one large implementation task.

### Reason

The analyzer is being shifted at a foundational level.
Large combined tasks increase the risk of:

- scope leakage
- premature abstractions
- confusion between implemented vs aspirational layers
- weak foundation with overly ambitious top-layer logic

### Working rule

Implementation tasks should remain:

- narrow
- additive
- testable
- auditable

Merge / no-merge decisions remain manual after each step.

---

## Success criteria

This minute-event layer is successful not only if:

- schema exists
- datasets build
- tests pass

It is successful if it also becomes:

- a credible substrate for repeatable move-potential and asymmetry research
- a clean base for later outcome-linked setup discovery
- a faithful implementation bridge aligned with `research_blueprint_v2.md`

This is the real reason the minute-event foundation matters.

---

## Final operating rule

DeltaScout should stop treating minute feed mainly as background context for selected archive decisions.

The next analyzer expansion must elevate minute-level rows into first-class observation rows.

The immediate next implementation target is therefore:

- not broader PEAK interpretation
- not richer reject commentary
- not process-phase storytelling

but:

- **a real minute-event foundation and evidence bridge**

This is the required bridge between the current research blueprint and the next credible analyzer architecture.

