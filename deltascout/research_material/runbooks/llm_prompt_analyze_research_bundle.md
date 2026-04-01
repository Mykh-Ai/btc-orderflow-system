Task: create final DeltaScout research review package for the requested date window using the latest rebuilt artifacts

Input location:
`deltascout/research_material/reviews`

Use only the synced local review artifacts for the target dates.

Important:
Use only the latest rebuilt artifacts generated after:
1. enriched feed cutover
2. `Close` price-column fix
3. previous-day feed horizon fix for `ret_15m` / `ret_60m`

Do NOT:
- change code
- rebuild anything
- create new datasets
- speculate beyond the files
- silently infer profitability from sparse accepted/outcome evidence

Goal:
Produce an analyst-facing review package that is useful for DeltaScout research, not just a compact digest.

The output must contain **two sections in one markdown file**:
1. a **compact batch summary**
2. an **analytical memo**

The compact summary should preserve fast readability.
The analytical memo should restore research depth and make the strongest evidence-based tensions explicit.

The document must stay evidence-first and must treat current accepted PEAK events as a reference class, not as the boundary of thinking.

---

## Part 1 — Compact batch summary

### 1) Daily snapshot
For each date:
- accepted count
- reject count
- interesting reject count
- close outcome count
- top reject reasons
- dominant interesting_reject buckets

### 2) Accepted events
List all accepted events across the window with:
- date/time
- kind
- price
- cum_delta_60m
- cum_delta_180m
- ret_15m
- ret_60m
- price_vs_vwap_side
- matched_open_interest
- matched_funding_rate
- matched_liq_buy_qty
- matched_liq_sell_qty
- joined close outcome summary if present

### 3) Key rejects
Select the most relevant rejects across the window.
Prioritize:
- short-side rejects
- `vwap_side`
- `direction_mismatch`
- `3of3_fail`
- `possible_reversal_confirmation`
- `possible_reversal_onset`
- `possible_continuation_pressure`
- `possible_trap_or_false_break`

Keep the list selective, but include enough detail for real comparison.

### 4) Focused comparison
If the window contains an accepted event and nearby same-side rejects, include one compact comparison block using only evidence from the files:
- structural alignment
- ret_15m / ret_60m
- cumulative delta context
- matched OI/funding/liquidation fields
- no unsupported claims

### 5) Batch-level conclusion
End the compact section with:
- dominant reject patterns in the window
- whether enriched fields changed interpretation materially
- whether `vwap_side` appears to block otherwise strong cases
- 2–3 concrete next research questions

---

## Part 2 — Analytical memo

This second section is mandatory.
Do not just repeat the compact section.

### A. Batch verdict
Give a hard research verdict for the full window:
- what kind of batch this is
- where the main research center of gravity is
- whether the batch is accepted-heavy, reject-heavy, structurally thin, or evidence-rich
- whether the strongest material is in accepted cases or in rejects

### B. Strongest evidence clusters
Identify 3–5 strongest evidence clusters across the batch.
For each cluster, state:
- why it matters
- what repeats
- whether it looks more like reversal onset, reversal confirmation, continuation pressure, trap / false break, exhaustion, or unresolved structure
- whether it is stronger as research material than the accepted reference case

### C. Structural paradoxes and tensions
This section is mandatory.

Explicitly surface the strongest tensions such as:
- accepted cases that look weaker than rejected cases
- rejects blocked by a single rule despite stronger directional context
- cases where structural alignment passed but deeper comparison failed
- days where reject distribution suggests transition behavior rather than noise

For each paradox or tension, state it in forensic form:
- what exactly is being compared
- which metrics make the tension visible
- what remains ambiguous from the files

Do not rely only on descriptive language such as:
- stronger-looking
- cleaner
- more convincing

Instead, state explicitly:
- which metrics are stronger
- which metrics are weaker
- which metrics are aligned
- which metrics are conflicting
- which parts remain opaque

### D. Expanded key case notes
Pick 3–5 key cases across the batch and write mini-case notes.
For each case include:
- timestamp
- event type / reject reason / bucket
- why this case is analytically important
- what is structurally strong about it
- what blocked it or limited confidence
- whether it should be watched as possible future setup-class research material

At least one case note should compare a rejected case directly against the accepted reference case when justified by the files.

For each expanded key case, add two explicit sub-lines:

**Blocker status**
Label as one of:
- only visible blocker
- visible blocker but other hidden blockers possible
- deeper failure opaque from current files

**Sequence note**
Using only evidence visible from the review package, state briefly:
- whether the case looks isolated or cluster-like
- whether same-side rejects appear nearby in the same session
- whether a later same-side accepted case appears
- whether a later same-side stronger reject appears

### D2. Case-comparison discipline
When a rejected case is compared directly against an accepted reference case, include:
- 2–5 metric-level contrasts
- one sentence on structural alignment
- one sentence on visible blocker status
- one sentence on what remains unknown

Keep this compact, but explicit.

### E. Accepted vs rejected reference-class judgment
State clearly:
- what the accepted case(s) show
- what they do **not** prove
- whether any rejects appear structurally stronger than the accepted reference class
- whether current accepted flow looks like a strong edge source or only a narrow survival path through the funnel

Do not call a rejected case stronger than the accepted reference class unless you state explicitly:
- on which metrics it looks stronger
- on which metrics it remains weaker or ambiguous
- what still cannot be known from the files

If the comparison is only partial, say so directly.

### F. What remains unknown
List what cannot be concluded honestly from the files.
Be specific:
- sparse accepted sample
- sparse outcomes
- no clear enriched-field separation
- unresolved sequence/transition ambiguity
- anything else supported by the window

### G. Next best research direction
Give 2–4 concrete next research directions.
These must be narrow and evidence-driven.
Do not recommend mechanical filter loosening.

Examples of acceptable next directions:
- isolate `vwap_side` rejects with strong same-direction cumulative delta
- study `direction_mismatch` rejects that also carry reversal-like buckets
- compare accepted cases against later same-session rejects
- inspect whether `unclear_but_constructive` contains separable subgroups

Prefer next steps that reduce ambiguity in the current evidence.
Good next steps are those that clarify:
- whether a visible blocker is truly the main blocker
- whether unresolved rejects are cluster-like or isolated
- whether accepted flow is selecting better structure or only narrower structure

### H. Missing-evidence escalation
If the current review package is not sufficient for a strong conclusion, do not compensate with speculation.

Instead, explicitly do all of the following:
1. state that the evidence is insufficient
2. name the exact missing artifact or data slice that would help
3. explain why that artifact is needed
4. state which hypothesis, comparison, or ambiguity it would resolve
5. prefer narrow, existing, operationally realistic requests over broad generic requests

Good requests are specific, for example:
- selected same-session event sequence around one key case
- compact raw-feed extract for ±30m or ±60m around a timestamp
- accepted vs rejected comparison slice for one session
- blocker decomposition for a `3of3_fail` or `vwap_side` case if available
- same-side later-event relation within the session

Bad requests are vague, for example:
- more data
- all raw files
- full history without a stated reason

When asking for more material, keep the request minimal and evidence-driven.
The goal is not to expand the bundle mechanically, but to remove the single most important ambiguity.

### I. Minimal additional data request
If stronger analysis would require additional material, end with this subsection:

**Minimal additional data request**

List up to 3 concrete additional artifacts.
For each one, state:
- exact artifact wanted
- why it matters
- what it would help confirm or reject

---

## Writing discipline

- Be compact but not shallow.
- Prefer evidence over commentary.
- Do not turn bucket labels into validated setup classes.
- Do not imply profitability from one accepted case.
- Do not collapse everything into PEAK-centric thinking.
- Rejects are research material, not automatically weak cases.
- When evidence supports it, say explicitly if a rejected case appears structurally stronger than the accepted reference case.

### Claim discipline
For every major analytical claim, mark it explicitly as one of:
- Fact
- Interpretation
- Hypothesis
- Unknown

Do not present interpretations as facts.
Do not present hypotheses as validated setup classes.
Do not hide uncertainty when the files do not support a stronger conclusion.

---

## Output

Create one markdown file only.

Preferred filename pattern:
`reviews_YYYY-MM-DD_to_YYYY-MM-DD_final_research_review.md`

---

## Quality gate before finishing

Before writing the final document, check:

- Did the memo clearly separate Fact / Interpretation / Hypothesis / Unknown?
- Did each expanded key case include blocker status?
- Did each expanded key case include a sequence note?
- Did accepted-vs-rejected comparisons name explicit metric contrasts?
- Did the memo avoid turning bucket labels into validated setup classes?
- Did the memo avoid implying profitability from sparse accepted/outcome evidence?
- If evidence was insufficient, did the memo request narrow additional artifacts instead of speculating?