## Where you are

You are working inside:

`deltascout/delta_analyzer`

This is a research-layer module inside the broader DeltaScout project.

It is not production execution logic.
It is not the live DeltaScout signal engine.
It is not the Executor.

Its purpose is to help build a research engine that reconstructs market context, studies market behavior, and supports discovery of future trading setup classes.

---

## Project mission

The final goal of this project is:

> improve trading decisions and help discover profitable trade setups.

This module does not exist for abstract research.
It does not exist to generate pretty explanations.
It does not exist to expand signal count mechanically.

It exists to help identify:

- market states
- state transitions
- repeatable orderflow/price/structure formations
- local entry contexts with real move potential

Priority is:

> better trading edge, not more signals.

---

## How to think

Always think in this order:

**market state -> transition -> setup class -> entry timing**

Do not think in this order:

**single event -> instant signal conclusion**

Do not analyze one delta in isolation.
Always include context:

- cumulative delta on multiple horizons
- price action before and after
- VWAP / EMA / structure
- transition vs continuation
- divergence between flow and price
- strong delta zones and return-to-zone behavior

---

## Current scope

`delta_analyzer` currently has a Phase 1 foundation.

Phase 1 includes:

- archive ingestion
- feed ingestion
- event normalization
- event-to-feed matching
- `events_base` dataset
- basic integrity / health checks
- minimal CLI

Phase 1 does not include:

- outcomes
- EMA/trend regime logic
- setup classification
- ML
- live signal generation

Do not silently expand scope unless explicitly asked.

---

## Required reading before design changes

Read these documents before proposing analyzer design changes:

- `deltascout/research_material/research_manifesto.md`
- `deltascout/research_material/delta_analyzer_implementation_plan_v1_1.md`
- `deltascout/delta_analyzer/Delta_Analyzer_Phase1_Spec.md`
- `deltascout/delta_analyzer/README.md`

If your proposal conflicts with these documents, explain why explicitly.

---

## What counts as a good contribution

Good contributions are those that improve one or more of these:

- archive/feed reliability
- event normalization
- dataset quality
- context reconstruction
- market-state description
- outcome measurement
- setup discovery
- research clarity
- future tradable edge discovery

---

## What to avoid

Do not:

- modify production DeltaScout logic unless explicitly requested
- add live signal logic here
- jump into ML before datasets/features are mature
- treat all rejects as missed opportunities
- loosen filters mechanically just to increase event count
- confuse hindsight with edge
- mix multiple market regimes into one bucket

---

## Working style

Prefer:

- small scoped patches
- explicit contracts
- minimal abstractions
- readable datasets
- clear CLI behavior
- honest limitations
- implementation aligned with current phase

When unsure, preserve simplicity and keep the module research-first.
