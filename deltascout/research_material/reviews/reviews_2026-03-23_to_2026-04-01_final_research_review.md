# DeltaScout Final Research Review: 2026-03-23 to 2026-04-01

Source scope: synced local artifacts under `deltascout/research_material/reviews/2026-03-23` through `2026-04-01`.
Only the local review package was used.

## Part 1 — Compact Batch Summary

### Daily snapshot

| Date | Accepted | Reject | Interesting Reject | Close Outcome | Top Reject Reasons | Dominant Buckets |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 2026-03-23 | 0 | 17 | 16 | 0 | `vwap_side` 7, `direction_mismatch` 6, `3of3_fail` 3 | `unclear_but_constructive` 8, `possible_trap_or_false_break` 5 |
| 2026-03-24 | 0 | 25 | 25 | 0 | `direction_mismatch` 13, `vwap_side` 8, `3of3_fail` 4 | `unclear_but_constructive` 17, `possible_trap_or_false_break` 4, `possible_continuation_pressure` 3 |
| 2026-03-25 | 0 | 20 | 19 | 0 | `vwap_side` 8, `direction_mismatch` 7, `3of3_fail` 4 | `unclear_but_constructive` 13, `possible_trap_or_false_break` 5 |
| 2026-03-26 | 0 | 13 | 11 | 0 | `direction_mismatch` 7, `vwap_side` 2, `3of3_fail` 2 | `unclear_but_constructive` 9 |
| 2026-03-27 | 0 | 17 | 16 | 0 | `direction_mismatch` 9, `vwap_side` 6 | `unclear_but_constructive` 13 |
| 2026-03-28 | 0 | 15 | 14 | 0 | `direction_mismatch` 8, `vwap_side` 4, `3of3_fail` 2 | `unclear_but_constructive` 11 |
| 2026-03-29 | 1 | 23 | 18 | 1 | `direction_mismatch` 12, `vwap_side` 6, `3of3_fail` 4 | `unclear_but_constructive` 9, `possible_reversal_confirmation` 4, `possible_reversal_onset` 3 |
| 2026-03-30 | 0 | 22 | 18 | 0 | `direction_mismatch` 10, `vwap_side` 6, `vwap_distance` 3 | `unclear_but_constructive` 13 |
| 2026-03-31 | 0 | 21 | 18 | 0 | `direction_mismatch` 12, `vwap_side` 4, `imb_band` 2 | `unclear_but_constructive` 16 |
| 2026-04-01 | 0 | 13 | 11 | 0 | `direction_mismatch` 6, `vwap_side` 4, `3of3_fail` 2 | `unclear_but_constructive` 6, `possible_trap_or_false_break` 3 |

Window totals:
- Accepted: `1`
- Rejects: `186`
- Interesting rejects: `166`
- Joined close outcomes: `1`
- Dominant reject reasons: `direction_mismatch` 90, `vwap_side` 55, `3of3_fail` 26
- Dominant short-side reject reasons: `direction_mismatch` 45, `vwap_side` 32, `3of3_fail` 11
- Dominant interesting buckets: `unclear_but_constructive` 115, `possible_trap_or_false_break` 22, then `possible_reversal_confirmation`, `possible_reversal_onset`, `possible_continuation_pressure` at 9 each

### Accepted events

Only one accepted event appears in the window.

| Date/Time UTC | Kind | Price | cum_delta_60m | cum_delta_180m | ret_15m | ret_60m | price_vs_vwap_side | matched_open_interest | matched_funding_rate | matched_liq_buy_qty | matched_liq_sell_qty | Joined close outcome |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 2026-03-29 19:23:00 | short | 66232.738615 | 68.9850 | -802.8820 | 8.6 | 52.8 | below | 95888.14 | 4.451e-05 | 0.0 | 0.0 | `window_match`, `SHORT`, `entry=66187.66`, `close_reason=SL` |

### Key rejects

| Date/Time UTC | Event Type | Reject Reason | Bucket | Rule | Price | cum_delta_60m | cum_delta_180m | ret_15m | ret_60m | price_vs_vwap_side | Why it matters |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 2026-03-24 14:09:00 | `CANDIDATE_COMPARISON_REJECT` | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | 70816.640317 | -2169.3260 | -1821.6130 | 222.2 | -462.9 | below | Strong same-direction cumulative delta and aligned VWAP-side, but gate stack still failed |
| 2026-03-29 05:06:00 | `CANDIDATE_COMPARISON_REJECT` | `vwap_side` | `possible_reversal_confirmation` | `IR_B1` | 66796.084089 | -855.6300 | -177.8100 | -65.8 | -170.3 | above | Short candidate with negative delta context, blocked mainly on VWAP-side placement |
| 2026-03-29 08:50:00 | `CANDIDATE_COMPARISON_REJECT` | `vwap_side` | `possible_reversal_onset` | `IR_A2` | 66695.907621 | -448.4370 | -397.0130 | 18.0 | 60.0 | above | Same-session short reject with positive return horizons, filtered on `vwap_side` |
| 2026-03-31 01:46:00 | `CANDIDATE_COMPARISON_REJECT` | `3of3_fail` | `unclear_but_constructive` | `IR_F1` | 66753.855597 | 2578.4970 | 3236.1950 | 199.8 | 841.2 | below | Structurally extreme reject: strong return profile and aligned side, but still rejected by gate stack |
| 2026-04-01 06:25:00 | `CANDIDATE_COMPARISON_REJECT` | `vwap_side` | `unclear_but_constructive` | `IR_F1` | 68133.865799 | 1273.6770 | 2370.3330 | 229.1 | 318.8 | above | Clear example where `vwap_side` blocked a strong directional-looking short candidate |

### Focused comparison

Accepted reference case: `2026-03-29 19:23:00` short `PEAK_EMIT`.

Comparison set: same-side rejects on `2026-03-29`.

- Structural alignment:
  - Accepted case: `price_vs_vwap_side=below`
  - `2026-03-29 05:06` and `08:50`: both short rejects, both `price_vs_vwap_side=above`, both blocked by `vwap_side`
  - `2026-03-29 12:12` and `12:30`: short rejects with `price_vs_vwap_side=below`, but blocked by `3of3_fail`
- Return horizon profile:
  - Accepted `19:23`: `ret_15m=8.6`, `ret_60m=52.8`
  - Reject `08:50`: `ret_15m=18.0`, `ret_60m=60.0`
  - Reject `12:12`: `ret_15m=-31.2`, `ret_60m=11.2`
  - Reject `12:30`: `ret_15m=13.3`, `ret_60m=-52.5`
- Cumulative delta context:
  - Accepted `19:23`: `cum_delta_60m=68.985`, `cum_delta_180m=-802.882`
  - Reject `08:50`: `cum_delta_60m=-448.437`, `cum_delta_180m=-397.013`
  - Reject `05:06`: `cum_delta_60m=-855.630`, `cum_delta_180m=-177.810`
- Matched OI/funding/liquidations:
  - OI stays in a tight band across the comparison set: roughly `94.6k` to `95.9k`
  - Funding moves from slightly negative in the `vwap_side` rejects to positive in the accepted case
  - Liquidation fields are zero throughout, so they do not separate accepted from rejected cases here

Compact conclusion: the accepted reference case is structurally cleaner on VWAP-side placement, but it is not obviously stronger than all nearby rejects on return horizons alone. The strongest same-session tension is `2026-03-29 08:50`, a rejected short with both horizons positive that still fails on `vwap_side`.

### Batch-level conclusion

- The window is dominated by `direction_mismatch` and `vwap_side`; those two reasons account for most of the reject mass.
- Enriched fields changed interpretation materially by turning the reject pool into distinct research buckets instead of undifferentiated reject noise.
- `vwap_side` does appear to block otherwise strong cases, especially among short-side rejects with reversal-like or trap-like bucket labels.
- The accepted reference class is too sparse to define a stable edge boundary; it is better treated as a survival example through the current funnel.

Next research questions:
1. Among short-side `vwap_side` rejects, how often is `vwap_side` the only visible blocker versus one blocker among several hidden gate failures?
2. Within `unclear_but_constructive` rejects, can high-return cases be separated from low-information cases using `events_context` fields rather than bucket labels alone?
3. On sessions like `2026-03-29`, do later accepted shorts differ materially from earlier rejected shorts by VWAP-side placement alone, or by a broader structural combination?

## Part 2 — Analytical Memo

### A. Batch verdict

This is a reject-heavy, evidence-rich research batch rather than an accepted-heavy validation batch. The center of gravity is not in the single accepted `PEAK_EMIT`; it is in the reject field, especially the repeated short-side conflicts between directional context and terminal gating. The batch is structurally thin on accepted evidence, but structurally rich in rejected cases that recur with interpretable patterns. The strongest research material is therefore in the rejects, not in the accepted reference class.

### B. Strongest evidence clusters

1. `vwap_side` short rejects with reversal-like labels
- Why it matters: this is the clearest recurring tension between directional context and rule enforcement.
- What repeats: short candidates with negative or mixed cumulative delta, sometimes positive forward-return horizons, still fail on VWAP-side placement.
- Shape: mostly `possible_reversal_confirmation`, `possible_reversal_onset`, or `possible_trap_or_false_break`.
- Strength versus accepted reference: as research material, this cluster is stronger than the accepted case because it repeats across dates and sessions.

2. `direction_mismatch` as the dominant batch-level reject mass
- Why it matters: it is the single largest terminal reject reason in the window.
- What repeats: same-side candidates appear in both weak and seemingly constructive contexts, but the mismatch rule keeps terminating them.
- Shape: often unresolved structure rather than clear continuation or reversal.
- Strength versus accepted reference: stronger as a research problem than the accepted case because of scale, not because every member is individually stronger.

3. `3of3_fail` rejects with aligned short-side structure
- Why it matters: these cases show that passing VWAP-side alignment does not guarantee survival.
- What repeats: short candidates with `price_vs_vwap_side=below` and often meaningful delta context still fail the gate stack.
- Shape: mixed between continuation pressure and unresolved structure.
- Strength versus accepted reference: some of these cases are individually stronger than the accepted reference on raw return profile, especially `2026-03-31 01:46`.

4. `unclear_but_constructive` as a large unresolved reservoir
- Why it matters: `IR_F1` dominates the batch, which suggests the current taxonomy still compresses many potentially different structures into one bucket.
- What repeats: rejects that are not obviously noise, but also do not cleanly resolve into trap/reversal/continuation labels.
- Shape: unresolved structure.
- Strength versus accepted reference: stronger as a future research target because of its size and heterogeneity.

### C. Structural paradoxes and tensions

- The accepted reference case is not the strongest-looking case in the window on forward-return profile. `2026-03-31 01:46` short `3of3_fail` posts `ret_15m=199.8` and `ret_60m=841.2` with `price_vs_vwap_side=below`, while the accepted `2026-03-29 19:23` has only `ret_15m=8.6` and `ret_60m=52.8`.
- Several rejected shorts look directionally stronger than the accepted reference but are blocked by a single visible rule. `2026-03-29 08:50` and `2026-04-01 06:25` both show positive horizons, but both fail on `vwap_side` because they sit `above` VWAP.
- Structural alignment can pass while deeper gating still fails. `2026-03-24 14:09` is a short with `price_vs_vwap_side=below` and very negative cumulative delta, yet it still fails on `3of3_fail`.
- The reject distribution on `2026-03-29`, `2026-03-31`, and `2026-04-01` looks more like transition behavior than simple noise: same-side rejects occupy different failure modes within the same session, suggesting a funnel that is discriminating among related structures rather than rejecting uniformly weak material.
- Auxiliary enriched fields do not obviously rescue the current acceptance logic. OI and funding vary, but the accepted case does not stand out sharply enough to say these fields currently create a clean accepted/rejected boundary.

### D. Expanded key case notes

1. `2026-03-29 19:23:00`
- Event: accepted short `PEAK_EMIT`
- Why important: this is the only accepted case and the only joined close outcome in the window.
- Structural strength: `price_vs_vwap_side=below`, positive `ret_15m` and `ret_60m`, matched close record.
- What limits confidence: close outcome is `SL`, accepted sample size is one, and auxiliary fields do not isolate it sharply from nearby rejects.
- Research status: reference case only, not proof of a strong setup class.

2. `2026-03-29 08:50:00`
- Event: short reject, `vwap_side`, bucket `possible_reversal_onset`, rule `IR_A2`
- Why important: this is the cleanest nearby rejected comparison against the accepted short.
- Structural strength: negative cumulative delta on both 60m and 180m, positive `ret_15m` and `ret_60m`.
- What blocked it: `price_vs_vwap_side=above`, so the visible terminal blocker is VWAP-side placement.
- Research status: should be watched as possible future setup-class material because it looks stronger than the accepted reference on forward-return profile while failing on one interpretable structural rule.

3. `2026-03-31 01:46:00`
- Event: short reject, `3of3_fail`, bucket `unclear_but_constructive`, rule `IR_F1`
- Why important: this is the strongest paradox case in the whole batch.
- Structural strength: `price_vs_vwap_side=below`, extremely strong `cum_delta_60m`, `cum_delta_180m`, `ret_15m`, and `ret_60m`.
- What blocked it: the files only expose terminal `3of3_fail`; they do not explain which deeper sub-checks failed.
- Research status: high-priority future setup-class research material. It appears structurally stronger than the accepted reference case.

4. `2026-04-01 06:25:00`
- Event: short reject, `vwap_side`, bucket `unclear_but_constructive`, rule `IR_F1`
- Why important: it extends the `vwap_side` paradox beyond a single date.
- Structural strength: very strong positive 60m/180m cumulative delta, `ret_15m=229.1`, `ret_60m=318.8`, non-zero buy liquidation quantity.
- What blocked it: `price_vs_vwap_side=above`.
- Research status: important cross-day evidence that `vwap_side` can block strong-looking cases even outside reversal-labeled buckets.

5. `2026-03-24 14:09:00`
- Event: short reject, `3of3_fail`, bucket `possible_continuation_pressure`, rule `IR_C2`
- Why important: it shows that aligned side placement is not enough.
- Structural strength: `price_vs_vwap_side=below`, deeply negative 60m and 180m cumulative delta.
- What blocked it: `3of3_fail`, despite the structural picture looking continuation-compatible.
- Research status: useful for understanding what the gate stack rejects after VWAP-side alignment is already satisfied.

### E. Accepted vs rejected reference-class judgment

The accepted case shows that a short can pass the current funnel with aligned VWAP-side placement and modestly positive return horizons, and that such a case can still close as `SL`. It does not prove that the accepted flow is a strong edge source. It also does not prove that accepted cases are structurally superior to rejected cases.

Yes, some rejects appear structurally stronger than the accepted reference class. The clearest example is `2026-03-31 01:46`, and the most direct same-session example is `2026-03-29 08:50`. Current accepted flow therefore looks less like a broad edge source and more like a narrow survival path through the funnel.

### F. What remains unknown

- Accepted sample is sparse: one accepted case is not enough to define a stable accepted reference class.
- Outcome sample is sparse: one joined close outcome, and it is `SL`.
- The files do not expose the internal decomposition behind `3of3_fail`, so some of the strongest rejects remain opaque at the decisive layer.
- OI, funding, and liquidation fields do not show a clear separating pattern in this window.
- Sequence ambiguity remains unresolved: several dates look transitional, but the files alone do not prove whether the rejected cases were early, late, or structurally mistimed relatives of future acceptable setups.
- Large `unclear_but_constructive` mass means the current bucket taxonomy is still under-resolving the reject population.

### G. Next best research direction

1. Isolate short-side `vwap_side` rejects that also have positive `ret_15m` and `ret_60m`, then compare them directly against accepted shorts on the same session or adjacent sessions.
2. Split `unclear_but_constructive` short rejects into subgroups using `price_vs_vwap_side`, cumulative delta sign pattern, and return-horizon shape, instead of treating `IR_F1` as one class.
3. Inspect `3of3_fail` short rejects with `price_vs_vwap_side=below` to identify whether they are failing on a hidden timing/sequence constraint rather than on weak directional structure.
4. Build session-local comparisons where one accepted case and several same-side rejects coexist, to test whether the funnel is selecting cleaner structure or merely a narrower subset of otherwise similar cases.
