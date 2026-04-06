# Delta Analyzer Phase 2 Validation

## Purpose

This document records the empirical validation status of Phase 2 as a research-layer component of `delta_analyzer`.

It does **not** redefine the Phase 2 contract.
It exists to answer a different question:

> Given the current copied local research corpus, is Phase 2 already useful as a real research layer, and what can it responsibly support next?

Phase 2 should be evaluated in the broader DeltaScout mission context:

- better trading edge, not more signals,
- market state -> transition -> setup class -> entry timing,
- no mechanical filter loosening,
- no treating all rejects as missed opportunities.

## Validation Verdict

Phase 2 is **validated** as a useful `event-context` research layer within its current scope.

On the current copied local research materials, `events_context` is no longer just a formal dataset-build artifact. It already provides usable backward-looking flow and price context around archive events and is strong enough to support:

- event-context reconstruction,
- reject-context interpretation,
- preliminary accepted-event linkage to downstream close outcomes through external research joins.

At the same time, Phase 2 should **not** be overstated.

It is **not** yet:

- an outcome layer,
- a market-state engine,
- a setup-classification layer,
- a sequence model,
- or a profitability analytics layer.

That boundary is consistent with the current Phase 2 scope.

## Phase 2 Contract Being Validated

Phase 2 extends the Phase 1 foundation with `events_context`, a research-only dataset that attaches backward-looking event context to archive rows.

In the current implementation scope, this context includes:

- rolling cumulative-delta fields,
- backward-looking price-return fields,
- VWAP-relative fields,
- and CLI-visible context coverage summaries.

The validated field families currently include:

- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`
- `dist_vwap`
- `abs_dist_vwap`
- `price_vs_vwap_side`

Phase 2 explicitly does **not** include:

- outcomes or forward returns,
- EMA, trend, or regime logic,
- setup classification,
- scoring or ranking,
- session segmentation,
- ML,
- production DeltaScout logic.

## Validation Corpus

Validation was performed against the current copied local DeltaScout research corpus stored under:

- `deltascout/research_material/raw_archive/`
- `deltascout/research_material/raw_feed/`

The current copied working sample used for validation covers five days and contains 117 archive rows.

Observed event families in the copied sample are:

- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`
- `PEAK_EMIT`

Initial research notes on the copied sample show that:

- comparison-stage rejects dominate the sample,
- gate rejects are extremely rare,
- accepted-flow coverage is still sparse,
- and the first copied `PEAK_EMIT` / close-outcome join appears in the current validation sample.

This means Phase 2 is being validated primarily as a context layer for reject-funnel and event-interpretation research, not yet as a broad accepted-flow or outcome analytics layer.

## What Phase 2 Already Provides

### 1. Backward-looking directional context

The cumulative-delta fields already make it possible to ask whether an event occurred:

- inside accumulated directional flow,
- against broader local flow,
- or in a mixed backdrop.

This is important because DeltaScout research should not interpret one delta in isolation.

### 2. Backward-looking price context

The return fields already help distinguish whether price had already moved before the event or whether the event occurred in a more delayed or conflicting price context.

These fields are simple backward-looking price differences, which is acceptable for the current research layer.

### 3. VWAP-relative context

`dist_vwap`, `abs_dist_vwap`, and `price_vs_vwap_side` already add practical interpretive value.

They are especially useful when reviewing:

- `vwap_side` rejects,
- obvious side-conflict cases,
- and structural misalignment between event direction and current VWAP-relative location.

### 4. Event-context reconstruction at dataset scale

Phase 2 is now strong enough to function as a usable event-context table for archive events rather than a thin technical artifact.

That matters because the current research direction is still centered on:

- archive coverage and archive health,
- reject-reason distribution,
- comparison-stage bottlenecks,
- joins between decision timestamps and same-day feed context.

### 5. External accepted-event to close-outcome linkage

Although outcomes are outside the Phase 2 contract, the current dataset is already sufficient for preliminary accepted-event linkage to downstream close outcomes through an external research join.

This linkage is currently an external research join, not an embedded outcome layer inside `events_context`.

## What Phase 2 Does Not Yet Provide

### 1. No embedded outcome path

Phase 2 does not contain close rows, SL rows, or forward reaction metrics inside `events_context`.

That is acceptable and consistent with the current scope, but it means outcome analysis still requires an external join and cannot yet be done from `events_context` alone.

### 2. No market-state or transition classification

Phase 2 helps reconstruct context, but it does not yet classify:

- continuation,
- reversal onset,
- transition,
- exhaustion,
- trap / false break,
- or broader regime state.

That belongs to later analyzer phases, not to Phase 2.

### 3. No setup taxonomy

Phase 2 can help surface interesting accepted events and interesting rejects, but it does not yet assign them to formal setup classes.

### 4. No sequence logic

Phase 2 treats each row as an event with backward-looking context.
It does not yet model:

- previous-event linkage,
- streaks,
- alternation,
- repeated continuation bursts,
- first opposing burst behavior,
- or reject decomposition across event sequences.

That belongs to a later sequence layer, not to Phase 2 itself.

### 5. Context is shared by same-timestamp terminal pairs

When multiple archive rows share the same timestamp, the matched backward-looking context is naturally the same for those rows.

This is useful for comparing different timestamps, but it does not explain decision logic inside one exact timestamp by itself.

## Evidence-Backed Practical Usefulness

The copied sample already supports several research tasks responsibly.

### A. Reject-funnel interpretation

The current research context says the near-term focus remains the reject funnel, especially comparison-stage rejects, archive health, reject-reason distribution, and feed-context joins.
Phase 2 directly supports that work.

### B. Reason sanity checks

Phase 2 already allows basic sanity review of whether reject reasons such as `direction_mismatch` or `vwap_side` align with the observed backward-looking flow and VWAP context.

### C. Accepted-event anchoring when sparse

The copied sample now includes the first local `PEAK_EMIT`, and accepted-flow handling can no longer be ignored completely.
Phase 2 is already sufficient to contextualize such accepted rows even though accepted-flow coverage is still sparse.

### D. Research triage

Phase 2 is already good enough to separate:

- obviously weak-looking rejects,
- structurally explainable rejects,
- and at least some ambiguous or interesting rejects that deserve later review.

That is a real research contribution even before any outcome layer exists.

## Known Limitations and Discipline Notes

The current validation does **not** justify the following:

- broad outcome claims,
- profitability conclusions from sparse accepted-flow evidence,
- broad redesign of DeltaScout signal logic,
- full market-state inference from current fields alone,
- mechanical filter loosening to increase event count,
- or treating all rejects as hidden winners.

The same discipline also requires avoiding:

- hindsight bias,
- small-sample overfitting,
- regime mixing,
- single-metric overreliance,
- archive completeness distortion,
- and premature signalization.

## Evidence-Based Near-Term Priorities

The next work should remain narrow and evidence-based.

### Priority 1 — accepted-event to close-outcome research linkage

Phase 2 is already strong enough to support a stable research join between accepted events and downstream close outcomes through an external table.

### Priority 2 — interesting reject review

Phase 2 should now be used to identify rejects whose context does **not** look trivially weak.

This is not a call to loosen filters.
It is a call to create a disciplined review bucket for potentially interesting rejects.

### Priority 3 — reason/context sanity checks

The copied sample should be used to test whether dominant reject reasons, especially `direction_mismatch` and `vwap_side`, consistently align with backward-looking cumulative-delta and VWAP context rather than merely dominating by count.

## What Is Not Yet Justified

The current evidence does **not** yet justify:

- designing a broad market-state engine from scratch,
- adding large new feature families before current fields have been used fully,
- drawing conclusions about accepted-event quality from one close outcome,
- or jumping directly into broad next-phase design without first using Phase 2 in real research review loops.

## Final Conclusion

Phase 2 should now be considered **validated within its intended scope**.

Its current role is not to decide trade quality or profitability.
Its role is to provide a clean, usable event-context layer that can:

- reconstruct backward-looking event context,
- help explain reject behavior,
- support preliminary accepted-event review,
- and prepare the research stack for later sequence, market-state, and outcome layers.

That is already meaningful progress.

The correct next step is therefore not to overstate Phase 2, but to **use it**:

- as the base layer for accepted-event context review,
- as the base layer for interesting-reject triage,
- and as the base layer for later evidence-backed analyzer phases.


