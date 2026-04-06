Task: build a standard DeltaScout research bundle from the currently available local review folders

Input root:
`deltascout/research_material/reviews`

Use only the review folders and files that are currently present locally under this root.
Do not assume any fixed date range in advance.
Discover the available daily review folders automatically from the local filesystem.

Do NOT:
- change code
- rebuild anything
- create or modify analyzer outputs
- speculate beyond the files
- require a predefined date list from the operator

Goal:
From the currently available synced review folders, build one standard research bundle for LLM analysis.

The bundle must contain exactly 4 output artifacts:

1. one batch-level research review markdown
2. one batch-level index summary CSV
3. one selected-case sequence context CSV
4. one selected-case raw-feed micro extract CSV

Use only data already present in the local review materials and any directly associated local raw/review files that are already synced.

## Regime-first reading rule

Future research outputs built from this bundle must read event context in this order:
- regime = `cum_delta_24h`
- transition = `cum_delta_180m`
- setup pressure = `cum_delta_60m`
- entry timing = `ret_15m` / `ret_60m`

Whenever event metrics are listed in the batch review, any focused family memo, any focused comparison memo, or any accepted-flow / postmortem style memo derived from this bundle, keep this exact order:
- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`

Do not treat `cum_delta_24h` as optional or implicit. If it is missing for any case, say so explicitly and state that regime framing is incomplete for that case.

---

## Step 1 - Discover scope

Automatically detect all daily review folders directly under:

`deltascout/research_material/reviews`

Treat folders matching a date-like day structure as daily review units.

Sort them ascending by date.

Use all valid discovered daily folders as the batch scope.

Also determine:
- earliest discovered date
- latest discovered date

Use those two dates in output filenames.

If no valid daily folders are found:
- do not invent output
- return a short failure note instead of fake artifacts

---

## Step 2 - Build the 4 standard bundle artifacts

### Artifact 1 - batch-level research review markdown

Create one markdown file:

`reviews_<START>_to_<END>_final_research_review.md`

This file must contain:
- compact batch summary
- analytical memo

#### Part 1 - Compact batch summary
Include:
1. daily snapshot
2. accepted events
3. key rejects
4. focused comparison when justified
5. batch-level conclusion

For any accepted-event table, comparison block, compact case note, or other event-context list inside this markdown, the event context fields must appear in this order:
- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`

If a key case or lane is discussed, state explicitly whether the local short/long setup sits with or against the visible 24h cumulative-delta regime. If `cum_delta_24h` is missing, say so explicitly rather than silently skipping regime framing.

#### Part 2 - Analytical memo
Include:
A. Batch verdict  
B. Strongest evidence clusters  
C. Structural paradoxes and tensions  
D. Expanded key case notes  
D2. Case-comparison discipline  
E. Accepted vs rejected reference-class judgment  
F. What remains unknown  
G. Next best research direction  
H. Missing-evidence escalation  
I. Minimal additional data request

#### Claim discipline
For every major analytical claim, mark it explicitly as one of:
- Fact
- Interpretation
- Hypothesis
- Unknown

Do not present interpretations as facts.
Do not present hypotheses as validated setup classes.

#### Expanded key case rules
For each expanded key case include:
- timestamp
- event type / reject reason / bucket
- why the case matters
- whether the case sits with or against the visible 24h cumulative-delta regime
- what is structurally strong
- what blocked it or limits confidence
- whether it should be watched for future setup research

Also include:

**Blocker status**
Label as one of:
- only visible blocker
- visible blocker but other hidden blockers possible
- deeper failure opaque from current files

**Sequence note**
Using only evidence visible from the package, state:
- isolated or cluster-like
- whether same-side rejects appear nearby
- whether a later same-side accepted appears
- whether a later same-side stronger reject appears

#### Comparison discipline
Do not call a rejected case stronger than the accepted reference class unless you state explicitly:
- on which metrics it looks stronger
- on which metrics it remains weaker or ambiguous
- what still cannot be known from the files
- whether the compared cases sit with or against the visible 24h cumulative-delta regime

Accepted-flow and PEAK-side diagnostics must include `cum_delta_24h` in any comparison table or case note. Use it as regime context only, not as a standalone signal.

---

### Artifact 2 - batch-level index summary CSV

Create one CSV file:

`reviews_<START>_to_<END>_index_summary.csv`

Each row must represent one discovered daily folder.

Required columns:

- `date`
- `accepted_count`
- `reject_count`
- `interesting_reject_count`
- `close_outcome_count`
- `top_reject_reason_1`
- `top_reject_reason_1_count`
- `top_reject_reason_2`
- `top_reject_reason_2_count`
- `top_reject_reason_3`
- `top_reject_reason_3_count`
- `dominant_bucket_1`
- `dominant_bucket_1_count`
- `dominant_bucket_2`
- `dominant_bucket_2_count`
- `has_accepted`
- `has_close_outcome`
- `accepted_case_ts`
- `accepted_case_kind`
- `accepted_case_close_reason`
- `dominant_side_reject_bias`
- `contains_vwap_side_rejects`
- `contains_direction_mismatch_rejects`
- `contains_3of3_fail_rejects`
- `contains_possible_reversal_onset`
- `contains_possible_reversal_confirmation`
- `contains_possible_continuation_pressure`
- `contains_possible_trap_or_false_break`
- `notes_flag`

Rules:
- use only `yes` / `no` for boolean-like fields
- leave unavailable accepted fields blank
- preserve date order ascending
- no prose in this file

---

### Artifact 3 - selected-case sequence context CSV

Create one CSV file:

`selected_case_sequence_context_<START>_to_<END>.csv`

Purpose:
give sequence-aware context around the most important cases in the discovered batch.

#### Case selection
Select approximately 8-12 key cases across the full discovered scope.

Prioritize:
- accepted events when present
- short-side rejects
- `vwap_side`
- `direction_mismatch`
- `3of3_fail`
- `possible_reversal_onset`
- `possible_reversal_confirmation`
- `possible_continuation_pressure`
- `possible_trap_or_false_break`
- paradox cases where rejected rows look structurally strong

#### For each selected case
Extract all nearby DeltaScout review events in a local window around the case.

Preferred window:
- +/-90 minutes

Required columns:
- `target_ts`
- `session_date`
- `ts`
- `minutes_from_target`
- `is_target_case`
- `event_type`
- `kind`
- `reject_reason`
- `interesting_reject_bucket`
- `rule_id`
- `price`
- `price_vs_vwap_side`
- `cum_delta_24h`
- `cum_delta_180m`
- `cum_delta_60m`
- `ret_15m`
- `ret_60m`
- `same_side_as_target`
- `later_same_side_event_in_window`
- `later_same_side_accepted_in_window`
- `later_same_side_stronger_reject_in_window`

Rules:
- use only evidence visible from the currently available local materials
- do not invent sequence relations that cannot be derived
- leave fields blank when unavailable
- if `cum_delta_24h` is blank for a row, preserve the blank and do not infer regime compatibility

---

### Artifact 4 - selected-case raw-feed micro extract CSV

Create one CSV file:

`selected_case_raw_feed_micro_<START>_to_<END>.csv`

Purpose:
give microstructure context around the same selected cases used in Artifact 3.

#### Scope
For the same selected case timestamps used in the sequence-context artifact, extract local raw-feed rows around each case.

Preferred window:
- -30 minutes to +30 minutes around target timestamp

Required columns:
- `target_ts`
- `Timestamp`
- `minutes_from_target`
- `Close`
- `VWAP`
- `BuyQty`
- `SellQty`
- `OpenInterest`
- `FundingRate`
- `LiqBuyQty`
- `LiqSellQty`
- `IsSynthetic`
- `delta_1m`
- `vol_1m`
- `price_minus_vwap`

Rules:
- use only already available local raw/feed material if present locally
- do not rebuild or derive new analyzer datasets
- helper fields such as `delta_1m`, `vol_1m`, `price_minus_vwap` may be computed directly from extracted raw rows
- if raw-feed material is not available locally for some selected cases, keep the missing coverage honest and do not fabricate rows

---

## Output discipline

Produce exactly these 4 artifacts and nothing else:
1. `reviews_<START>_to_<END>_final_research_review.md`
2. `reviews_<START>_to_<END>_index_summary.csv`
3. `selected_case_sequence_context_<START>_to_<END>.csv`
4. `selected_case_raw_feed_micro_<START>_to_<END>.csv`

Do not create extra markdown notes.
Do not create code patches.
Do not create rebuild instructions.
Do not create vague summaries outside these files.

---

## Evidence discipline

- Accepted PEAK events are a reference class, not the boundary of thinking.
- Rejects are research material, not automatically weak cases.
- Do not imply profitability from sparse accepted or sparse outcome evidence.
- Do not turn bucket labels into validated setup classes.
- Treat `cum_delta_24h` as regime context, not as a standalone signal.
- If evidence is insufficient, say so explicitly inside the markdown review.
- When stronger analysis would require additional data, request only narrow, concrete, operationally realistic missing artifacts.

---

## Quality gate before finishing

Before finalizing, check:

- Were daily folders discovered automatically from the currently available local review root?
- Were the output filenames based on the discovered earliest and latest dates?
- Does the markdown review clearly separate Fact / Interpretation / Hypothesis / Unknown?
- Does each expanded key case include blocker status?
- Does each expanded key case include a sequence note?
- Do accepted-vs-rejected comparisons name explicit metric contrasts?
- Did batch, focused, comparison, and accepted-flow style readouts keep `cum_delta_24h` explicit and first in the context order?
- If `cum_delta_24h` was missing for any case, did the markdown review say so explicitly?
- Does the package include both navigation-level and sequence-level artifacts?
- If evidence was insufficient, did the markdown review request narrow additional artifacts instead of speculating?
