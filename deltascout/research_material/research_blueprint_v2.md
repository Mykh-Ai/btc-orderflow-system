# DeltaScout Research Blueprint v2
## Setup Search Beyond Current PEAK

## Purpose

This document fixes the current research operating model for DeltaScout.

The project should not search for entries primarily through the lens of current `PEAK` accepts or rejected near-`PEAK` material.

The main search direction is:

**market state → transition → process phase → entry timing**

Current `PEAK` remains useful as:

- a reference class
- a diagnostics surface
- a contrast mechanism

But it is not the dominant center of setup discovery.

This aligns with the current research handoff and manifesto:
accepted `PEAK` flow remains reference-class diagnostics rather than the boundary of the program, while the deeper objective is broader market-behavior and future setup-family discovery.

---

## Core framing

The main research question is no longer:

- why did this rejected `PEAK` not pass?
- which reject looked stronger than accepted `PEAK`?

The main research question becomes:

- what state is the market in?
- what transition is underway?
- what phase of the process is currently visible?
- where inside that process does an entry become attractive?

This means DeltaScout research must move away from row-level reject fascination and toward process-level market understanding.

Rejected near-`PEAK` material still matters, but mainly because it can expose meaningful market behavior, not because every reject is a hidden missed trade.

---

## Primary research order

All future analysis should think in this order:

1. **regime**
2. **transition**
3. **process phase**
4. **entry timing**

Not:

1. single event
2. instant signal conclusion

This is the correct continuation of the broader DeltaScout mission framing:
market state first, then transition, then setup class, then timing.

---

## Role of PEAK

Current `PEAK` logic remains important, but only in bounded ways.

### PEAK is useful for:
- reference accepted-flow behavior
- diagnostics on what current grammar captures
- diagnostics on what current grammar rejects
- comparison against future setup classes

### PEAK is not:
- the full boundary of research
- the only valid source of trade ideas
- the final authority on market state
- the only path to future setup discovery

Accepted-flow remains too sparse and too narrow to define the center of setup discovery.
Current accepted cases are still best treated as reference-class diagnostics, not as a validated edge source.

Current `PEAK` remains one useful operational grammar, but future setup discovery must be allowed to outrun the current grammar when market-process evidence justifies it.

---

## Regime-first reading rule

Future analysis should read event context in this order:

- **regime** = `cum_delta_24h`
- **transition** = `cum_delta_180m`
- **setup pressure** = `cum_delta_60m`
- **entry timing** = `ret_15m` / `ret_60m`

This ordering should be preserved in future memos, summaries, and setup research.

### Important caution
`cum_delta_24h` is not a standalone signal or final definition of regime.
It is the first regime-context field in the current reading stack.

Later regime interpretation may need to become richer through additional fields such as:

- `price_change_24h`
- price relative to higher-horizon anchor
- session delta bias
- higher-horizon flow/price divergence

But the current ordering is still useful as the operating reading rule.

---

## Core layers of setup search

## Layer 1 — Regime

The first question is:

> what broader environment is the market in?

For short-side research, this includes at least:

- positive `cum_delta_24h`
- negative `cum_delta_24h`
- mixed / weakening 24h flow
- price agreement or disagreement with 24h flow

The sign of `cum_delta_24h` alone is not sufficient.

The important question is whether price still responds honestly to the higher-horizon flow.

---

## Layer 2 — Transition

The second question is:

> is the local structure already rotating away from the broader flow state?

This is read mainly through:

- `cum_delta_180m`
- `cum_delta_60m`
- local price returns
- flow/price agreement or divergence

Important cases include:

- positive 24h flow with negative 180m/60m
- negative 24h flow with strengthening downside continuation
- local reversal against still-positive higher-horizon flow
- local continuation after regime confirmation

---

## Layer 3 — Structure

The third question is:

> where is price located structurally?

This includes:

- `price_vs_vwap_side`
- distance from VWAP
- reclaim / failed reclaim
- sweep above local highs / below local lows
- return under anchor / return above anchor

Structure should be read as context, not as one hard filter in isolation.

This preserves the lesson from current reject-family work:
structural placement conflict and deeper aligned failure are not the same thing and should not be collapsed into one pool.

---

## Layer 4 — Participation

The fourth question is:

> who is actually participating in the move?

This includes:

- Open Interest
- `LiqBuyQty`
- `LiqSellQty`
- aggressive flow vs structural progress
- churn / unwind vs new positioning
- absorption-like behavior

This layer should help distinguish:

- honest continuation
- fake expansion
- squeeze
- absorption
- unwind

### Important caution
Participation must not be read mechanically.

OI growth alone is not enough.  
Liquidation bursts alone are not enough.

Participation should always be read together with:

- structural progress
- follow-through quality
- return behavior after burst
- absorption vs release behavior

Otherwise participation becomes decorative instead of diagnostic.

---

## Layer 5 — Process phase

The fifth question is:

> what phase of the market process is currently visible?

This is the central research shift.

The project should increasingly think in terms of market-process phases rather than isolated event labels.

---

## Current working process model

This is a working hypothesis, not established truth.

A short-side process may unfold through phases such as:

1. **ground / precursor**
2. **manipulation / fake long picture / sweep**
3. **truth seed before full regime confirmation**
4. **post-regime-flip continuation**
5. **terminal continuation / late short attempt**

This model is useful because it organizes observed cases into a market-process ladder rather than a flat reject inventory.

It must remain hypothesis-driven, evidence-bound, and repeatability-tested.

---

## Setup classes to research

The following are current setup-search classes worth studying.

These are research classes, not live signals.

### A. Early Truth Seed

#### Characteristics
- `cum_delta_24h` still positive or mixed
- `cum_delta_180m` already negative
- `cum_delta_60m` already negative
- price no longer responds honestly to bullish flow
- path often still dirty / sweep-affected

#### Meaning
- often **phase marker first, entry second**
- may be the first honest sign that the downside process has started

### B. Post-Sweep Continuation

#### Characteristics
- a bullish burst / upper sweep happened first
- bullish continuation failed
- retest is weak
- price returns below anchor / below VWAP
- local flow supports renewed downside

#### Meaning
- **entry research class**
- one of the strongest candidate classes for continuation-entry research

### C. Post-Regime-Flip Continuation

#### Characteristics
- `cum_delta_24h < 0`
- `cum_delta_180m < 0`
- `cum_delta_60m < 0`
- structure already aligned for downside continuation

#### Meaning
- **entry research class**
- not the same as early truth seed
- continuation inside already confirmed bearish regime

### D. Terminal Continuation

#### Characteristics
- everything already looks bearish
- move is already stretched
- short looks obvious
- often late

#### Meaning
- **late-risk / no-edge class unless proven otherwise**
- should not be treated as high-quality continuation automatically

---

## Phase marker vs entry candidate vs late-risk

This distinction is mandatory.

Not every meaningful phase is an entry.  
Not every entry-looking moment has move potential.

Future analysis must explicitly separate:

### 1. Phase marker
Useful because it reveals state change, transition, manipulation, failed reclaim, or truth emergence.  
It may matter even when it is not directly tradable.

Typical example:
- Early Truth Seed

A phase marker may be highly important for process understanding even when it is not directly tradable.

### 2. Entry candidate
Useful because phase logic, structural location, and participation quality align enough to justify entry research.

Typical examples:
- Post-Sweep Continuation
- Post-Regime-Flip Continuation

### 3. Late-risk / no-edge state
Useful because it warns that the process may already be mature, stretched, crowded, or terminal.

Typical example:
- Terminal Continuation

This distinction protects the research program from the core mistake of confusing an important market event with a trade entry.

---

## Research gates for setup search

These are not live-trading gates.  
They are research gates.

### Gate 1 — Regime compatibility
Ask:
- does the setup sit with or against the visible 24h regime?

### Gate 2 — Flow vs price
Ask:
- does price still agree with higher-horizon flow?
- is there divergence?
- is bullish flow failing to produce bullish price progress?

### Gate 3 — Structural location
Ask:
- where is the setup relative to VWAP and structural anchors?
- is this a reclaim, failed reclaim, sweep, or stretched chase?

### Gate 4 — Participation quality
Ask:
- does OI suggest new participation, unwind, or churn?
- do liquidations dominate the burst or not?

### Gate 5 — Phase maturity
Ask:
- is this precursor, truth seed, clean continuation, or terminal continuation?

Only after these questions should entry timing be considered.

---

## What counts as a good entry candidate

A good entry candidate is not simply:

- a large delta
- a near-PEAK reject
- a below-VWAP event
- a strong-looking minute

A stronger entry candidate is one where:

- phase is mature enough
- regime does not strongly contradict the idea
- structure supports continuation
- participation does not look fake
- the move is not already terminal

---

## What counts as warning instead of entry

Some events are valuable not because they are entries, but because they mark the process.

Examples:

- strong burst against the prior move
- deceptive long picture
- liquidity sweep
- early truth seed
- failed reclaim

These may matter because they reveal market-state change, not because they should be traded directly.

---

## Why rejected material still matters

Rejected near-`PEAK` material remains useful for research.

But its role must be understood correctly.

Rejected material matters because it can reveal:

- pre-release structure
- post-alignment failure
- hidden continuation pressure
- early transition before current grammar accepts it
- deceptive opposing bursts that distort current comparison logic

The objective is **not** to rescue rejects as trades.  
The objective is to understand the market process they expose.

This stays fully aligned with the current family-level handoff:
rejects remain the primary research surface, but should be interpreted as structured evidence rather than one generic reject mass.

---

## What invalidates a process-phase hypothesis

This block is mandatory.

Without explicit invalidation logic, any phase model can drift into narrative or belief.

A process-phase hypothesis should be degraded when evidence breaks the claim.

### Examples of invalidation
- if a supposed truth seed gives no structural follow-through and quickly breaks back, downgrade it to noise / failed precursor
- if a supposed continuation survives only on liquidation burst without OI support, weaken the continuation claim
- if a supposed post-flip continuation is already stretched and behaves like terminal chase, downgrade it to late-risk
- if a supposed phase reading does not repeat across new windows, treat it as narrative, not as a working class
- if structure, participation, and follow-through disagree materially, phase confidence should be reduced

### Core principle
**Repeatability outranks elegance.**

A beautiful explanation without recurrence is weaker than a simpler class that repeats.

---

## Move-potential test remains mandatory

This block is also mandatory.

Even if a phase or setup class looks meaningful, it does not yet have real research value for the trading system unless it is associated with meaningful move potential.

The final questions must remain:

- does it produce movement?
- does it produce asymmetry?
- does it produce move-capable context?
- or is it only an interesting picture?

DeltaScout Research is not here merely to explain the market.  
It is here to discover entry locations with real directional potential, especially in the spirit of the broader `$1000+` move objective already stated in project research doctrine.

Meaningful move potential should be tested repeatedly across windows, not inferred from one strong historical example.

---

## Practical workflow for future analysis

For each new market window:

### Step 1 — describe regime
- `cum_delta_24h`
- visible higher-horizon flow condition
- whether price agrees or diverges

### Step 2 — describe transition
- `cum_delta_180m`
- `cum_delta_60m`
- local rotation vs higher-horizon context

### Step 3 — describe structure
- VWAP-side
- anchor distance
- reclaim / failed reclaim
- sweep / retest

### Step 4 — describe participation
- OI
- liquidations
- possible absorption / unwind / squeeze

### Step 5 — assign process phase
- precursor
- manipulation
- truth seed
- clean continuation
- terminal continuation

### Step 6 — classify role
- phase marker?
- entry candidate?
- late-risk / no-edge?

### Step 7 — test validity
- structural follow-through?
- participation quality?
- repeated on other windows?
- invalidation signs present?

### Step 8 — only then assess entry quality
- informative phase marker?
- potential entry?
- likely too early?
- likely too late?
- move-capable or only descriptive?

---

## Relationship to current family work

Current family-level findings should not be discarded inside this broader process model.

They remain useful as operational evidence buckets:

- **Family A** = earlier short-side transition / placement-conflict lane
- **Family B** = later aligned-failure lane
- **B1** = strongest operational subtype
- **B3** = strongest setup-discovery anomaly

These should be preserved as evidence-bearing families while process-phase research grows around them.

The phase model is a higher-order interpretation layer, not a replacement for already accumulated family evidence.

---

## Important caution

The research program should not collapse into:

- “find the good rejects”
- “prove PEAK is wrong”
- “loosen gates to get more signals”

That would be too narrow and too mechanical.

The correct objective is:

> discover recurring market behavior and process-state structure that can later support profitable setup classes

---

## Current strongest research direction

The strongest current direction is no longer simply:

- inspect rejected PEAKs

It is now:

- reconstruct market process
- detect state transitions
- separate early precursor from true continuation
- distinguish pre-flip from post-flip behavior
- understand how current PEAK logic sits inside the broader market process

---

## Future research priorities

### Priority 1
Market-state-first reading of new windows.

### Priority 2
Continuation ladders across phases:
- precursor
- manipulation
- truth seed
- post-flip continuation
- terminal continuation

### Priority 3
B1 / B3 and other family-level contrasts as part of process understanding, not as isolated label games.

### Priority 4
PEAK-side diagnostics as supporting evidence, not final truth.

### Priority 5
Later addition of stronger regime context fields beyond `cum_delta_24h`, such as:
- `price_change_24h`
- `distance_from_24h_vwap` or `price_vs_regime_anchor`
- `rolling session delta bias`

These should be layered only after the current regime-first reading becomes stable and useful.

---

## Final operating verdict

Current DeltaScout research should now be understood as moving:

- from row-level reject interpretation
- toward market-state and process-phase interpretation

`PEAK` remains useful as a diagnostics surface.

But the deeper search is for:

- recurring market behavior
- regime transition
- process phase
- entry contexts that can later produce real trading edge

The goal is not “rejected PEAKs”.  
The goal is to understand the market process they sometimes reveal.

### Final rule
A setup class matters only when phase logic, structural validity, and move potential remain aligned.