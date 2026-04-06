# DeltaScout Minute Event Process-Chain Spec v1
## Phase M2.6 — Process-Chain Research Bridge

## Purpose

This document defines the next research-layer bridge after `minute_events_outcomes` and before formal typed taxonomy or full sequence/process engines.

It exists to capture a practical discovery problem that became explicit after the first minute-event family work:

- some minute-event families do **not** behave as isolated standalone classes
- instead, they appear as **linked stages inside one market process**
- stronger future `AI_Emit` research may therefore require modeling **chain role**, not only family identity

This phase is intentionally positioned **between** M2.5 and M3/M4.

It is **not**:

- a full event taxonomy
- a full process engine
- a live DeltaScout signal layer
- a final setup-validation contract
- a profitability proof layer

---

## Relationship to existing documents

This document should be read together with:

- `deltascout/research_material/research_blueprint_v2.md`
- `deltascout/research_material/minute_event_research_spec_v1.md`
- current family-level findings and handoff materials under `deltascout/research_material/`

Working relationship:

- `research_blueprint_v2.md` = strategic market-state / process-phase worldview
- `minute_event_research_spec_v1.md` = minute-event foundation, mechanics, and outcomes bridge
- `minute_events_m2_6_process_chain_spec_v1.md` = pre-typing bridge for linked minute-event process roles

This phase does **not** replace M2.5.
It uses M2.5-style evidence to decide whether family-level minute-event candidates behave like:

- origin / truth-seed events
- cleaner release events
- continuation events
- late / exhaustion events

---

## Why M2.6 is needed

The first minute-event family exploration suggests that family-level grouping alone is too flat.

Observed problem:

- one family may behave as an **early violent seed / flush**
- another family may behave as a **cleaner continuation or release after that seed**
- some rows that look mechanically similar still differ sharply depending on where they appear inside the chain

This means the next useful bridge is not yet full typing.
The next useful bridge is a **process-chain research layer**.

---

## Working research observations motivating M2.6

These observations are current evidence-bound working findings, not validated truths.

### Observation 1 — minute-first reading is already justified

Minute-event work should no longer be treated only as support context around `PEAK` / reject review.
Minute rows are already useful as a first-class research surface.

### Observation 2 — family-level pockets are visible, but not sufficient

Initial minute-event family work produced at least:

- a cleaner release-style family (`F1`)
- an opposed flush / reversal-seed family (`F2`)
- a late / no-edge style anti-family

However, these broad family labels remain too coarse.

### Observation 3 — `F2` may behave as an origin / truth-seed family

Representative examples discussed in current research work suggest that `F2` can sometimes precede large directional movement and should not be treated only as a passive phase marker.

Working read:

- `F2` may sometimes function as an **early violent truth-seed / flush origin**
- but not every `F2` row is necessarily a direct entry candidate

### Observation 4 — `F1` may often behave as a cleaner follow-through class

Representative examples suggest that `F1` may often appear as:

- a cleaner release after a prior seed / flush
- a continuation-style entry after earlier process emergence

Working read:

- `F1` may often function as a **release / continuation class**
- but some `F1` rows may still be late, mixed, or already fading

### Observation 5 — family identity and chain role are not the same

A useful future research layer must therefore distinguish:

- **family hint**
- **chain role**

The same family hint may appear in more than one chain role.

---

## Core M2.6 principle

The next bridge layer should ask not only:

- what family does this minute resemble?

but also:

- what **role** does this minute appear to play inside the visible process?

M2.6 therefore introduces a working distinction between:

- **family-level pattern hint**
- **process-chain role**

---

## Proposed working chain roles

These roles are a **working hypothesis**, not established truth.

### 1. `seed`

A minute that appears to reveal early truth, flush behavior, sweep resolution, or initial release before the move is structurally clean.

Typical use:

- important process signal
- sometimes tradable
- often rough / early / higher-risk

### 2. `release`

A minute where the move becomes cleaner, structure aligns better, and directional progress becomes more usable.

Typical use:

- stronger entry-research candidate
- often cleaner than the original seed

### 3. `continuation`

A minute that extends an already-established move without being purely terminal.

Typical use:

- entry candidate only when not already stretched
- must be distinguished from late chase

### 4. `late_exhaustion`

A minute that appears directionally aligned but occurs too late, too stretched, or too terminal to support attractive entry quality.

Typical use:

- warning / no-edge role
- anti-family or invalidation role

---

## Scope of M2.6

M2.6 should stay narrow.

### In scope

- process-chain research hypotheses above minute outcomes and below final typing
- manual and semi-structured linking of minute-family candidates into chain roles
- reference-case curation for future AI_Emit discovery
- sequence-aware candidate review for selected minute-event rows
- distinguishing origin-like rows from continuation-like rows

### Out of scope

- final taxonomy for all minute rows
- automatic global process-role assignment across the whole dataset
- live DeltaScout gating changes
- formal AI_Emit deployment
- full setup validation
- profitability claims as established truth

---

## Expected inputs

M2.6 should primarily consume:

- `minute_events_base`
- `minute_events_mechanics`
- `minute_events_outcomes`
- selected review-package context where useful
- raw archive / raw feed for sequence drill-down
- manual case notes from representative windows

M2.6 should remain minute-first rather than PEAK-gate-first.
Current `PEAK` remains a reference / diagnostics layer, not the boundary of discovery.

---

## Proposed M2.6 outputs

M2.6 does **not** require one final canonical dataset immediately.
The first useful outputs can be narrower and additive.

### Output A — `minute_event_chain_candidates`

A focused candidate table for rows that pass family-level discovery filters and are worth chain-role review.

Minimum useful fields:

- `ts`
- `day`
- `direction`
- `family_hint`
- `chain_role_hypothesis`
- `price_vs_vwap_side`
- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`
- selected mechanics / outcome fields
- `reference_window_id`
- `notes`

### Output B — `minute_event_chain_reference_cases`

A manually reviewed or semi-manually reviewed catalog of representative cases.

Purpose:

- preserve strongest examples
- preserve counterexamples
- preserve ambiguous cases
- create future typing foundation for M3/M4

Minimum useful fields:

- `ts`
- `family_hint`
- `chain_role_label`
- `role_confidence`
- `phase_marker_vs_entry_candidate`
- `pre_window_summary`
- `post_window_summary`
- `invalidating_notes`
- `move_followthrough_notes`

### Output C — `chain_cluster_summaries`

Grouped sequence views for clusters where more than one related minute candidate appears in one process window.

Purpose:

- detect whether `seed -> release -> continuation` actually recurs
- prevent over-reading isolated minutes

---

## Initial working hypotheses for M2.6

These hypotheses are explicitly provisional.

### Hypothesis A

Some `F2` rows behave as `seed` or `origin` events rather than as non-tradable markers only.

### Hypothesis B

Some `F1` rows behave as `release` or cleaner `continuation` after a prior `F2`-like seed.

### Hypothesis C

Family-level discovery improves materially when the same row is evaluated with both:

- `family_hint`
- `chain_role_hypothesis`

### Hypothesis D

The strongest future AI_Emit candidates may emerge not from one broad family label, but from a narrower subset such as:

- `F2 as seed`
- `F1 as release`

### Hypothesis E

A meaningful part of current false positives can be re-read as:

- `late_exhaustion`
- `mixed continuation`
- `phase marker but not entry`

---

## Required M2.6 workflow

### Step 1 — candidate extraction

Use minute-event mechanics + outcomes to extract narrow candidate rows from promising families and anti-families.

### Step 2 — cluster and window assembly

For each candidate, build a local window:

- pre-window
- trigger minute
- post-window

### Step 3 — family hint assignment

Assign provisional family membership such as `F1`, `F2`, or later families.

### Step 4 — chain-role hypothesis assignment

Assign a provisional role:

- `seed`
- `release`
- `continuation`
- `late_exhaustion`

### Step 5 — manual review of top cases

Manually review representative top cases to avoid premature automation.

### Step 6 — reference-case preservation

Keep a stable catalog of the strongest and most informative cases.

### Step 7 — recurrence check

Check whether the same family-role combinations recur across multiple windows.

Only after recurrence and invalidation review should the work move toward stronger M3/M4 style formalization.

---

## Relationship to later phases

### M2.6 vs M3

M2.6 is **not** full typed taxonomy.
It does not attempt to assign stable final event classes across the full minute universe.

M2.6 is a **pre-typing bridge**.

### M2.6 vs M4

M2.6 is also **not** the full sequence/process engine.
It is the narrowest useful bridge toward sequence reasoning.

M4 would later be responsible for broader, more systematic process/sequence extensions.
M2.6 only prepares the ground.

---

## What must not happen in M2.6

M2.6 must **not**:

- pretend chain-role hypotheses are already validated setup truth
- promote future AI_Emit families directly into live logic
- collapse manual examples into premature broad taxonomy
- confuse one strong historical example with repeatable edge
- overwrite the importance of invalidation and late-risk labeling

---

## Success criteria

M2.6 is successful if it produces:

1. a usable chain-role research vocabulary
2. a repeatable way to review minute-event families as linked process stages
3. a stable set of reference cases for future AI_Emit discovery
4. a clearer separation between:
   - origin-like minute events
   - cleaner release / continuation events
   - late / terminal events
5. a stronger bridge from M2.5 evidence to later M3/M4 work

---

## Final operating verdict

M2.6 should be understood as a narrow process-chain research bridge.

It exists because family-level minute-event discovery has become informative enough to justify the next question:

> not only what family this minute resembles,
> but what role it appears to play inside the move.

This phase is the correct place to begin testing:

- `seed`
- `release`
- `continuation`
- `late/exhaustion`

as a future AI_Emit discovery bridge, without pretending that full sequence logic or final setup typing already exists.
