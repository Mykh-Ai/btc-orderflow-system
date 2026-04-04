# DeltaScout Research Mission

## Purpose

DeltaScout Research exists to discover **market behavior patterns** that can later become new trading setup classes.

The goal is **not** to blindly expand the current `PEAK` logic and **not** to loosen filters just to produce more signals.

The goal is to understand:

- what market states precede meaningful moves,
- what orderflow/price/structure combinations repeat,
- which local entry zones can lead to **large directional movement**,
- and which of those patterns deserve to become future `PEAK` families.

In practical terms, the research target is:

> identify entry locations with potential for **$1000+ directional move**.

---

## Existing PEAK is a reference class, not the final destination

Current `PEAK` events matter because they already represent a working market-facing logic.

They should be treated as:

- a **reference class**,
- a baseline for comparison,
- a source of insight into what the system already captures well.

They should **not** define the full research boundary.

DeltaScout Research must remain open to discovering **new formation classes** beyond current `PEAK`.

---

## Research worldview

The market should be studied as a system of **states and transitions**, not as isolated delta spikes.

A single strong delta event is **not enough** on its own.

Each event must be analyzed in context:

- what happened **before** it,
- what happened **after** it,
- what the broader market state was,
- whether the event appeared during:
  - trend continuation,
  - trend weakening,
  - trend break,
  - post-break continuation,
  - exhaustion,
  - trap,
  - absorption,
  - honest directional flow.

Core principle:

> do not study one delta in isolation; study the market state around it.

---

## Context first

Research must include broader context, not just local event metrics.

Important context dimensions include:

- cumulative delta on multiple horizons,
- price behavior around strong delta zones,
- VWAP / EMA / structural location,
- whether price and delta are aligned or diverging,
- whether market reaction is immediate or delayed.

Special attention should be given to situations where:

- cumulative delta rises but price does not advance,
- cumulative delta falls but price holds,
- price starts moving only after deep cumulative imbalance has already built up.

This means the analyzer must detect not just delta sign, but the **relationship between flow and price**.

---

## Primary research objective

The research process should follow this order:

**market state → transition → setup class → entry timing**

Not:

**single event → instant signal conclusion**

The main task is to identify:

1. **market states**
2. **market transitions**
3. **repeatable setup classes**
4. **local entry timing opportunities**

---

## Research directions

DeltaScout Research should operate across three layers:

### 1. Reference layer
Study current `PEAK` behavior to understand what already works.

### 2. Behavior discovery layer
Study raw market behavior to discover recurring states such as:

- reversal onset
- reversal confirmation
- continuation pressure
- exhaustion
- trap / false break
- absorption / non-progression
- honest directional flow

### 3. Future setup layer
Convert validated behavior classes into future setup families such as:

- `PEAK_TB1` — trend-break onset
- `PEAK_TB2` — trend-break confirmation
- `PEAK_CONT` — continuation pressure
- `PEAK_TRAP` — false-break reversal
- `PEAK_ABS` — absorption / non-progression
- `PEAK_ALIGN` — clean delta-price alignment

These labels are research placeholders, not trading signals by default.

---

## What the analyzer must learn to see

The analyzer should learn to describe the market through four lenses.

### Market state
- trend
- transition
- compression
- expansion
- extension
- exhaustion

### Flow state
- honest directional flow
- delta/price divergence
- delayed reaction after cumulative buildup
- absorption-like behavior
- continuation pressure

### Structural state
- trend intact
- trend weakening
- break underway
- break confirmed
- post-break continuation

### Opportunity state
- early reversal candidate
- confirmed reversal candidate
- continuation candidate
- late continuation
- trap risk
- no-edge noise

---

## Research discipline

The research layer must remain disciplined.

Do not:

- assume outcome without testing,
- call a signal strong only because it looks good in hindsight,
- draw broad conclusions from one event,
- mix different market regimes into one bucket,
- treat all rejects as missed opportunities.

Always separate:

- reversal onset
- reversal confirmation
- continuation
- exhaustion
- trap

---

## Current operating research state

DeltaScout research has moved beyond broad reject-funnel counting alone.

Current short-side reject work is now being treated through a family-level decomposition:

- **Family A** = short-side rejects above VWAP; earlier transition / placement-conflict lane
- **Family B** = short-side rejects below VWAP that still fail deeper in the funnel; later aligned-failure lane

This should be treated as the current working research split, not as a finalized setup taxonomy.

Current operating read:

- Family A is the stronger current transition-timing lead
- Family B is the broader current setup-discovery lane
- later focused work shows Family B has internal subtype structure and should not be treated as internally uniform

---

## Current context documents

Current research context should be carried forward with these documents:

- `2026-03-16_to_2026-03-20_initial_findings.md`
- `2026-03-23_to_2026-04-01_family_findings.md`
- `focused_family_b_deep_dive.md`

---
## Current operating blueprint reference

The full operating blueprint now lives in `deltascout/research_material/research_blueprint_v2.md`.

It formalizes the current shift from row-level reject / PEAK-centered reading toward market-state / process-phase setup search.

PEAK remains useful as a reference/diagnostics surface, but the blueprint should be treated as the current doctrine for setup-search framing.

This manifesto remains the higher-level research-orientation document, while the blueprint contains the fuller operating model.

---
## Guiding principle

Every future model, analyzer, and research agent in DeltaScout should follow this principle:

> DeltaScout Research is not here to worship the current PEAK logic.  
> It is here to map market behavior, discover new repeatable formations, and turn them into future trading setup classes with real profit potential.


