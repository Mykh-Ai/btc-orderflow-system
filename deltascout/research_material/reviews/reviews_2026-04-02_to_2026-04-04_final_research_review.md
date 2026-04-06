# DeltaScout Final Research Review: 2026-04-02 to 2026-04-04

## Part 1 - Compact batch summary

### 1) Daily snapshot
- 2026-04-02: accepted 0, rejects 18, interesting rejects 12, close outcomes 0. Top reject reasons: direction_mismatch 11, vwap_distance 5, vwap_side 2. Dominant interesting bucket: unclear_but_constructive 10/12.
- 2026-04-03: accepted 1, rejects 20, interesting rejects 15, close outcomes 0. Top reject reasons: direction_mismatch 11, 3of3_fail 4, chop_coh 3, vwap_side 2. Dominant interesting bucket: unclear_but_constructive 10/15.
- 2026-04-04: accepted 1, rejects 14, interesting rejects 9, close outcomes 1 raw row with `join_status=missing`; no accepted-to-close join in accepted review rows. Top reject reasons: direction_mismatch 8, 3of3_fail 4, vwap_side 2. Dominant interesting bucket: unclear_but_constructive 6/9.

### 2) Accepted events
- 2026-04-03 16:20, `PEAK_EMIT`, long, price 66788.02, `cum_delta_24h=93.572`, `cum_delta_180m=11.203`, `cum_delta_60m=174.547`, `ret_15m=51.3`, `ret_60m=14.0`, `price_vs_vwap_side=above`, OI 90463.33, funding `1.01e-05`, liq buy 0.055, liq sell 0.0, no joined close outcome visible.
- 2026-04-04 23:56, `PEAK_EMIT`, long, price 67451.71, `cum_delta_24h=544.624`, `cum_delta_180m=320.475`, `cum_delta_60m=-26.656`, `ret_15m=24.9`, `ret_60m=-79.7`, `price_vs_vwap_side=above`, OI 91397.34, funding `2.415e-05`, liq buy 0.0, liq sell 0.0, no joined close outcome visible.

### 3) Key rejects
- 2026-04-02 06:06, long, `vwap_side`, bucket `possible_trap_or_false_break`: `cum_delta_24h=-1095.235`, `cum_delta_180m=-829.928`, `cum_delta_60m=183.524`, `ret_15m=89.0`, `ret_60m=179.6`, `price_vs_vwap_side=below`.
- 2026-04-03 01:00, short, `vwap_side`, bucket `possible_reversal_confirmation`: `cum_delta_24h=-8256.879`, `cum_delta_180m=-436.484`, `cum_delta_60m=-363.604`, `ret_15m=-11.2`, `ret_60m=-106.7`, `price_vs_vwap_side=above`.
- 2026-04-03 06:33, long, `direction_mismatch`, bucket `possible_reversal_onset`: `cum_delta_24h=-5051.371`, `cum_delta_180m=177.138`, `cum_delta_60m=12.968`, `ret_15m=-23.5`, `ret_60m=-110.4`, `price_vs_vwap_side=below`.
- 2026-04-04 06:55, long, `3of3_fail`, bucket `possible_reversal_confirmation`: `cum_delta_24h=1676.688`, `cum_delta_180m=417.548`, `cum_delta_60m=418.751`, `ret_15m=127.8`, `ret_60m=133.8`, `price_vs_vwap_side=above`.
- 2026-04-04 07:00, short, `direction_mismatch`, bucket `unclear_but_constructive`: `cum_delta_24h=1621.704`, `cum_delta_180m=388.649`, `cum_delta_60m=399.938`, `ret_15m=56.7`, `ret_60m=110.6`, `price_vs_vwap_side=above`.

### 4) Focused comparison
- Fact: the accepted long on 2026-04-03 16:20 sits slightly with the visible 24h regime (`cum_delta_24h=93.572`) and has cleaner local alignment than the earlier 2026-04-03 06:33 long reject because its `cum_delta_180m` and `cum_delta_60m` are both positive, while the reject has negative 24h regime and only shallow local positives.
- Fact: the 2026-04-04 accepted long has weaker local momentum than the 2026-04-04 06:55 long reject on `cum_delta_60m`, `ret_15m`, and `ret_60m`, but both sit with a positive 24h regime and both are above VWAP.
- Interpretation: on 2026-04-04 the visible blocker layer, not broad regime direction, is the main separator between the accepted reference case and at least one stronger-looking reject.
- Unknown: the files do not expose deeper decomposition for `3of3_fail`, so the exact blocked sub-condition remains opaque.

### 5) Batch-level conclusion
- Fact: the window is reject-heavy: 2 accepted vs 52 rejects, with 36 interesting rejects.
- Fact: enriched fields materially help regime-first reading because all highlighted accepted/reject cases expose `cum_delta_24h`, `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m`.
- Interpretation: `direction_mismatch` is the dominant blocker across the window, while `vwap_side` and `3of3_fail` appear as narrower but analytically sharper blocker lanes.
- Interpretation: `vwap_side` does appear to block otherwise structured cases, especially the 2026-04-02 06:06 long and 2026-04-03 01:00 short.
- Next research questions:
  - isolate `vwap_side` rejects that align with same-direction cumulative delta but fail on side placement;
  - compare accepted longs against 2026-04-04 `3of3_fail` long rejects to identify which hidden component is decisive;
  - inspect whether the large `unclear_but_constructive` cluster is one family or several separable subgroups.

## Part 2 - Analytical memo

### A. Batch verdict
- Fact: this batch is reject-heavy and evidence-rich on rejects, not on outcomes.
- Interpretation: the research center of gravity is the reject set, because accepted sample size is only two and both accepted rows have empty join fields.
- Interpretation: the main visible lanes split into two regimes: 2026-04-03 has many cases against a strongly negative 24h regime, while 2026-04-04 contains long-side material mostly with a positive 24h regime.
- Unknown: profitability or post-entry edge cannot be concluded honestly from this window because accepted-to-close linkage is absent in the accepted review rows.

### B. Strongest evidence clusters
- Fact: Cluster 1 is the 2026-04-02 `direction_mismatch` lane, with 11 rejects and 10 `unclear_but_constructive` cases. It repeats across both sides while price is mostly below VWAP.
  Interpretation: this looks more like unresolved transition or alignment conflict than random noise.
  Hypothesis: the lane may mix continuation and failed reversal attempts rather than one coherent setup class.
- Fact: Cluster 2 is the 2026-04-03 negative-regime short lane near 01:00-02:40, including a `vwap_side` short and a `direction_mismatch` short, all with strongly negative `cum_delta_24h` and `cum_delta_60m`.
  Interpretation: this cluster sits with the visible 24h regime and is stronger as research material than the single accepted long that appears much later in the session.
- Fact: Cluster 3 is the 2026-04-04 long-positive-regime lane, including the accepted long at 23:56 and several earlier long rejects, especially 06:55 `3of3_fail`.
  Interpretation: this cluster looks like continuation-pressure or reversal-confirmation research material inside a favorable regime, but filter selectivity remains narrow.
- Fact: Cluster 4 is the persistent `unclear_but_constructive` bucket across all three days: 10 on 2026-04-02, 10 on 2026-04-03, 6 on 2026-04-04.
  Interpretation: this bucket is not a validated setup class, but it is the dominant ambiguity reservoir in the batch.

### C. Structural paradoxes and tensions
- Fact: 2026-04-04 06:55 long reject vs 2026-04-04 23:56 accepted long.
  Fact: reject has stronger `cum_delta_24h` (1676.688 vs 544.624), stronger `cum_delta_180m` (417.548 vs 320.475), much stronger `cum_delta_60m` (418.751 vs -26.656), stronger `ret_15m` (127.8 vs 24.9), and stronger `ret_60m` (133.8 vs -79.7).
  Interpretation: the accepted case does not dominate the rejected case on visible regime or local momentum metrics.
  Unknown: the exact internal condition set inside `3of3_fail` is not visible, so the decisive blocker cannot be isolated from current files.
- Fact: 2026-04-03 01:00 short `vwap_side` reject sits with a strongly negative 24h regime and negative local deltas, yet is rejected on side placement while the accepted case later the same day is a long in a near-flat positive regime.
  Interpretation: the filter currently admits a narrower survival path than simple regime alignment would suggest.
  Unknown: without deeper sequence reconstruction, it is unclear whether the 01:00 short is an early-signal false positive or a structurally valid case blocked only by VWAP logic.
- Fact: 2026-04-02 contains no accepted cases, yet several rejects show non-trivial local structure, including one `vwap_side` long with positive `cum_delta_60m` and positive short-horizon returns.
  Interpretation: this day looks structurally thin on accepted flow but not structurally empty on research material.

### D. Expanded key case notes
- 2026-04-03 16:20 long accepted.
  Fact: `cum_delta_24h=93.572`, `cum_delta_180m=11.203`, `cum_delta_60m=174.547`, `ret_15m=51.3`, `ret_60m=14.0`, above VWAP.
  Interpretation: this is a modestly aligned long reference case in a nearly flat-to-slightly-positive regime rather than an emphatic momentum outlier.
  Unknown: no joined close outcome is present, so the accepted row proves survival through the funnel, not post-entry quality.
  **Blocker status**: only visible blocker not applicable because this is the accepted reference case.
  **Sequence note**: cluster-like; same-session same-side rejects appear earlier; no later same-side accepted case is visible that day; several earlier long rejects appear structurally comparable.
- 2026-04-04 06:55 long `3of3_fail` reject.
  Fact: positive regime and stronger local metrics than the later accepted 2026-04-04 long.
  Interpretation: this is one of the clearest paradox cases in the batch and should be treated as stronger research material than the accepted reference case, with the caveat that the blocker decomposition is hidden.
  Unknown: which exact sub-rule inside `3of3_fail` failed is not visible.
  **Blocker status**: visible blocker but other hidden blockers possible.
  **Sequence note**: cluster-like; nearby same-side rejects appear in the morning session; a later same-side accepted long appears at 23:56; a later same-side stronger reject is not clearly visible from the compact files.
- 2026-04-03 01:00 short `vwap_side` reject.
  Fact: `cum_delta_24h=-8256.879`, `cum_delta_180m=-436.484`, `cum_delta_60m=-363.604`, `ret_15m=-11.2`, `ret_60m=-106.7`, but `price_vs_vwap_side=above`.
  Interpretation: this looks like a regime-aligned short blocked by side placement rather than by weak directional context.
  Unknown: whether this is a true false-negative or a necessary anti-chase filter cannot be resolved from current files.
  **Blocker status**: only visible blocker.
  **Sequence note**: cluster-like; nearby same-side short rejects appear around 02:40 and 03:37; no later same-side accepted short appears that day; later same-side stronger reject evidence remains partial.
- 2026-04-02 06:06 long `vwap_side` reject.
  Fact: `cum_delta_24h=-1095.235`, `cum_delta_180m=-829.928`, `cum_delta_60m=183.524`, `ret_15m=89.0`, `ret_60m=179.6`, below VWAP.
  Interpretation: local setup pressure improved while higher-frame regime remained negative, producing a plausible trap-or-false-break candidate rather than a clean long continuation.
  Unknown: without accepted comparators on the same day, it remains unclear whether this is a meaningful missed long or a properly blocked counter-regime attempt.
  **Blocker status**: only visible blocker.
  **Sequence note**: cluster-like; several same-day same-side long rejects are nearby in the session; no later same-side accepted case appears; later same-side stronger reject evidence is mixed.
- 2026-04-03 06:33 long `direction_mismatch` reject.
  Fact: `cum_delta_24h=-5051.371`, `cum_delta_180m=177.138`, `cum_delta_60m=12.968`, `ret_15m=-23.5`, `ret_60m=-110.4`, below VWAP.
  Interpretation: this is a good example of local rebound structure that still sits against the dominant 24h regime.
  Unknown: whether the mismatch rule is the sole blocker or just the first visible one is unclear.
  **Blocker status**: visible blocker but other hidden blockers possible.
  **Sequence note**: cluster-like; other long rejects appear the same day; a later same-side accepted long appears at 16:20; a later same-side stronger reject is not obvious from the compact package.

### D2. Case-comparison discipline
- 2026-04-04 06:55 long reject vs 2026-04-04 23:56 accepted long.
  Fact: `cum_delta_24h` favors the reject (1676.688 vs 544.624).
  Fact: `cum_delta_180m` favors the reject (417.548 vs 320.475).
  Fact: `cum_delta_60m` favors the reject strongly (418.751 vs -26.656).
  Fact: `ret_15m` and `ret_60m` both favor the reject (127.8 vs 24.9, 133.8 vs -79.7).
  Interpretation: structural alignment on visible metrics is stronger for the reject, not for the accepted reference case.
  Interpretation: visible blocker status is `3of3_fail`, but the blocked sub-component is hidden.
  Unknown: outcome quality remains unknown for both because accepted join data is absent and reject counterfactual execution is not observable.
- 2026-04-03 01:00 short reject vs 2026-04-03 16:20 accepted long.
  Fact: the short reject has a far stronger absolute 24h regime signal in the short direction, while the accepted long has near-flat positive 24h context.
  Fact: the short reject also has negative `cum_delta_180m` and `cum_delta_60m`, while the accepted long has small positive values.
  Interpretation: the two cases do not share the same structural lane; this is a paradox of regime alignment versus filter admission, not a same-class comparison.
  Unknown: whether the short reject should outrank the accepted long cannot be concluded without deeper same-side comparator data.

### E. Accepted vs rejected reference-class judgment
- Fact: the accepted cases show that the funnel can emit long PEAK events in near-flat or positive 24h regimes with above-VWAP placement.
- Fact: the accepted cases do not prove robust post-entry edge, because joined close outcomes are absent in the accepted review rows.
- Interpretation: at least one reject, 2026-04-04 06:55 long `3of3_fail`, appears structurally stronger than the accepted reference class on visible regime and local momentum metrics.
- Unknown: current accepted flow may represent either better structure or merely narrower rule survival; current files do not separate those explanations cleanly.

### F. What remains unknown
- Unknown: accepted sample is sparse: only two rows in the full window.
- Unknown: accepted-to-close joins are absent in accepted review rows.
- Unknown: `3of3_fail` decomposition is opaque from the current files.
- Unknown: `unclear_but_constructive` likely contains multiple subgroups, but the compact package does not separate them.
- Unknown: same-session sequence ambiguity remains unresolved for several cases without deeper event-window reconstruction.

### G. Next best research direction
- isolate 2026-04-04 long `3of3_fail` cases and reconstruct the hidden failing components versus the accepted 23:56 long.
- inspect `vwap_side` rejects that are regime-aligned on `cum_delta_24h`, `cum_delta_180m`, and `cum_delta_60m`, starting with 2026-04-03 01:00 short.
- split the `unclear_but_constructive` bucket by regime sign and VWAP side to test whether it hides separable families.
- compare earlier same-session long rejects against later accepted longs on 2026-04-03 and 2026-04-04 using sequence-context artifacts rather than standalone rows.