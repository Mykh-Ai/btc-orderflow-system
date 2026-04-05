# DeltaScout Final Research Review: 2026-03-17 to 2026-04-04

Source scope: automatically discovered local daily review folders under `deltascout/research_material/reviews`.
Only existing local review and raw-feed materials were used.

## Part 1 - Compact batch summary

### 1) Daily snapshot
- Fact: discovered scope contains 19 daily review folders from `2026-03-17` through `2026-04-04`.
- Fact: batch totals are 4 accepted events, 338 rejects, 283 interesting rejects, and 3 close-outcome rows visible in daily review packages, with only 2 accepted rows showing joined close outcomes.
- Fact: dominant reject reasons across the full scope remain `direction_mismatch`, `vwap_side`, and `3of3_fail`.
- Fact: dominant interesting bucket across the full scope is `unclear_but_constructive`; the late extension `2026-04-02` .. `2026-04-04` preserves that same pattern.
- Fact: accepted days are `2026-03-20`, `2026-03-29`, `2026-04-03`, and `2026-04-04`.
- Interpretation: the scope remains reject-heavy even after the added rebuild window, and the added dates do not overturn the earlier center of gravity in the reject set.

### 2) Accepted events
- 2026-03-20 00:40, `PEAK_EMIT`, short, price 69822.44, `cum_delta_24h` not explicitly surfaced in the older memo, `cum_delta_180m=-243.928`, `cum_delta_60m=526.417`, `ret_15m=240.6`, `ret_60m=509.6`, `price_vs_vwap_side=below`, joined close outcome `window_match`, side `SHORT`, close reason `SL`.
- 2026-03-29 19:23, `PEAK_EMIT`, short, price 66232.74, `cum_delta_24h` not explicitly surfaced in the older memo, `cum_delta_180m=-802.882`, `cum_delta_60m=68.985`, `ret_15m=8.6`, `ret_60m=52.8`, `price_vs_vwap_side=below`, joined close outcome `window_match`, side `SHORT`, close reason `SL`.
- 2026-04-03 16:20, `PEAK_EMIT`, long, price 66788.02, `cum_delta_24h=93.572`, `cum_delta_180m=11.203`, `cum_delta_60m=174.547`, `ret_15m=51.3`, `ret_60m=14.0`, `price_vs_vwap_side=above`, no joined close outcome visible.
- 2026-04-04 23:56, `PEAK_EMIT`, long, price 67451.71, `cum_delta_24h=544.624`, `cum_delta_180m=320.475`, `cum_delta_60m=-26.656`, `ret_15m=24.9`, `ret_60m=-79.7`, `price_vs_vwap_side=above`, no joined close outcome visible.

### 3) Key rejects
- 2026-03-21 09:15, short, `vwap_side`, bucket `possible_reversal_onset`, rule `IR_A2`: `cum_delta_24h` unavailable in the compact source used here, `cum_delta_180m=-909.203`, `cum_delta_60m=-736.905`, `ret_15m=128.4`, `ret_60m=30.9`, `price_vs_vwap_side=above`.
- 2026-03-24 14:09, short, `3of3_fail`, bucket `possible_continuation_pressure`, rule `IR_C2`: `cum_delta_24h` unavailable in the compact source used here, `cum_delta_180m=-1821.613`, `cum_delta_60m=-2169.326`, `ret_15m=222.2`, `ret_60m=-462.9`, `price_vs_vwap_side=below`.
- 2026-03-31 01:46, short, `3of3_fail`, bucket `unclear_but_constructive`, rule `IR_F1`: `cum_delta_24h` unavailable in the compact source used here, `cum_delta_180m=3236.195`, `cum_delta_60m=2578.497`, `ret_15m=199.8`, `ret_60m=841.2`, `price_vs_vwap_side=below`.
- 2026-04-03 01:00, short, `vwap_side`, bucket `possible_reversal_confirmation`, rule `IR_B1`: `cum_delta_24h=-8256.879`, `cum_delta_180m=-436.484`, `cum_delta_60m=-363.604`, `ret_15m=-11.2`, `ret_60m=-106.7`, `price_vs_vwap_side=above`.
- 2026-04-04 06:55, long, `3of3_fail`, bucket `possible_reversal_confirmation`, rule `IR_B1`: `cum_delta_24h=1676.688`, `cum_delta_180m=417.548`, `cum_delta_60m=418.751`, `ret_15m=127.8`, `ret_60m=133.8`, `price_vs_vwap_side=above`.

### 4) Focused comparison
- Fact: early-window accepted shorts (`2026-03-20`, `2026-03-29`) pass with `price_vs_vwap_side=below`, while several strong-looking short rejects fail on `vwap_side` with `price_vs_vwap_side=above`.
- Fact: late-window accepted longs (`2026-04-03`, `2026-04-04`) arrive in near-flat-to-positive 24h regimes, but at least one `3of3_fail` long reject on `2026-04-04 06:55` is stronger on visible regime and local momentum metrics than the later accepted long.
- Interpretation: the full discovered scope shows two different paradox families, not one: short-side `vwap_side` blockage in the earlier window and long-side deeper gate blockage in the rebuilt late window.
- Unknown: the files remain insufficient to convert these paradoxes into validated setup classes because hidden gate decomposition is absent.

### 5) Batch-level conclusion
- Fact: the discovered scope stays reject-dominant after extension to `2026-04-04`.
- Interpretation: enriched fields changed interpretation materially by making regime and timing tensions legible, but they do not by themselves resolve why some stronger-looking rejects fail.
- Interpretation: `vwap_side` appears to block otherwise strong short cases repeatedly, while `3of3_fail` appears to block both aligned shorts and aligned longs at deeper, opaque layers.
- Hypothesis: accepted PEAK flow still looks like a narrow survival path through the funnel, not a broad edge-bearing class.
- Next questions:
  1. compare short `vwap_side` rejects against accepted shorts session-by-session;
  2. decompose `3of3_fail` rejects, especially `2026-03-31 01:46` and `2026-04-04 06:55`;
  3. split `unclear_but_constructive` by regime sign and VWAP side to test for separable families.

## Part 2 - Analytical memo

### A. Batch verdict
- Fact: the full scope contains 19 discovered daily folders, 4 accepted events, and 338 rejects.
- Interpretation: this is an evidence-rich but acceptance-thin batch. The main research center of gravity remains the reject pool.
- Interpretation: the strongest material is not evenly distributed; it concentrates in two lanes: short-side structural paradoxes before `2026-04-02` and mixed long/short blocker paradoxes in `2026-04-02` .. `2026-04-04`.
- Unknown: accepted outcomes remain too sparse and too weakly joined to support a profitability claim.

### B. Strongest evidence clusters
- Fact: Cluster 1 is early-window short `vwap_side` rejection, with repeated same-side rejects on `2026-03-21`, `2026-03-23`, `2026-03-29`, and `2026-04-01`.
  Interpretation: these cases often retain constructive forward horizons or directional pressure but fail on placement.
- Fact: Cluster 2 is early-window short `3of3_fail` paradox structure, especially `2026-03-24 14:09` and `2026-03-31 01:46`.
  Interpretation: these cases show that visible directional alignment is insufficient when deeper gate logic rejects the setup.
- Fact: Cluster 3 is 2026-04-03 negative-regime reject structure, especially the short `vwap_side` reject at 01:00 and long `direction_mismatch` reject at 06:33.
  Interpretation: this cluster sits mostly against or across a strongly negative 24h regime and is stronger as research material than the lone accepted long later that day.
- Fact: Cluster 4 is 2026-04-04 positive-regime long structure, including the accepted long at 23:56 and the stronger-looking `3of3_fail` long reject at 06:55.
  Interpretation: this is the clearest late-window accepted-vs-rejected paradox.
- Fact: Cluster 5 is the persistent `unclear_but_constructive` reservoir across the whole scope.
  Hypothesis: this bucket likely mixes multiple latent subgroups and should not be treated as one setup family.

### C. Structural paradoxes and tensions
- Fact: `2026-03-31 01:46` short reject looks stronger than accepted short `2026-03-29 19:23` on visible `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m`, while both are below VWAP.
  Interpretation: accepted status is not explained by visible directional strength alone.
  Unknown: `3of3_fail` sub-components are hidden.
- Fact: `2026-03-21 09:15` and `2026-03-29 08:50` are short rejects with constructive horizons that fail on `vwap_side`, while accepted shorts pass with below-VWAP placement.
  Interpretation: a single visible structural rule can dominate otherwise promising same-side context.
  Unknown: whether `vwap_side` is the true blocker or only the first visible blocker remains unresolved.
- Fact: `2026-04-04 06:55` long reject is stronger than accepted long `2026-04-04 23:56` on `cum_delta_24h`, `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m`.
  Interpretation: the late window reproduces the same paradox in the opposite side direction: stronger visible metrics do not guarantee acceptance.
  Unknown: hidden gate-stack composition remains opaque.
- Fact: `2026-04-03 01:00` short `vwap_side` reject sits with a strongly negative 24h regime, yet the day’s accepted case is a later long in a near-flat positive regime.
  Interpretation: regime alignment and funnel survival can diverge sharply within the same session.

### D. Expanded key case notes
- Case 1: `2026-03-20 00:40:00`, accepted short.
  Fact: accepted, below VWAP, joined close outcome `window_match`, close reason `SL`, strong `ret_15m` and `ret_60m`; `cum_delta_24h` unavailable in the compact source used here, so regime framing is incomplete for this synthesized bundle review.
  Interpretation: useful short-side reference case, but not proof of post-entry edge.
  Unknown: `cum_delta_24h` is not explicitly surfaced in the older memo, so regime framing for this case is incomplete in this synthesized bundle review.
  **Blocker status**: only visible blocker not applicable because this row was accepted.
  **Sequence note**: cluster-like; later same-side short rejects appear in adjacent sessions.
- Case 2: `2026-03-31 01:46:00`, short reject `3of3_fail`.
  Fact: visible metrics are stronger than at least one accepted short reference case.
  Interpretation: strongest early-window paradox case.
  Unknown: deeper failure opaque from current files.
  **Blocker status**: deeper failure opaque from current files.
  **Sequence note**: relatively isolated in the local window; no later same-side accepted is visible nearby.
- Case 3: `2026-04-03 01:00:00`, short reject `vwap_side`.
  Fact: strongly negative 24h regime, negative local deltas, above VWAP.
  Interpretation: regime-aligned short blocked by side placement.
  Unknown: whether it is a true false-negative remains unresolved.
  **Blocker status**: only visible blocker.
  **Sequence note**: cluster-like; nearby same-side short rejects appear; no later same-side accepted short that day.
- Case 4: `2026-04-04 06:55:00`, long reject `3of3_fail`.
  Fact: stronger than the later accepted long on all main visible metrics.
  Interpretation: strongest late-window paradox case.
  Unknown: hidden failing component remains unobserved.
  **Blocker status**: visible blocker but other hidden blockers possible.
  **Sequence note**: cluster-like; later same-side accepted long appears at 23:56.
- Case 5: `2026-04-04 23:56:00`, accepted long.
  Fact: accepted in a positive 24h regime with above-VWAP placement, but weaker than the earlier reject on local momentum metrics and with no joined close outcome.
  Interpretation: accepted status here shows funnel passage, not dominance on visible structure.
  Unknown: no post-entry quality evidence is available in the accepted row.
  **Blocker status**: only visible blocker not applicable because this row was accepted.
  **Sequence note**: cluster-like; earlier same-side long rejects appear in the same session.

### D2. Case-comparison discipline
- `2026-03-31 01:46` short reject vs `2026-03-29 19:23` accepted short.
  Fact: reject is stronger on `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m`.
  Fact: both are below VWAP, so visible side placement does not explain the difference.
  Interpretation: structural alignment alone does not separate the cases.
  Unknown: exact blocked sub-checks are missing.
- `2026-04-04 06:55` long reject vs `2026-04-04 23:56` accepted long.
  Fact: reject is stronger on `cum_delta_24h`, `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m`.
  Fact: both are above VWAP.
  Interpretation: visible metrics again favor the reject over the accepted reference case.
  Unknown: only hidden gate logic can explain the acceptance split, and that logic is not exposed in the files.

### E. Accepted vs rejected reference-class judgment
- Fact: accepted cases now span both short and long sides across the discovered scope.
- Fact: accepted shorts have joined close outcomes, both `SL`; accepted longs in the rebuilt late window do not show joined close outcomes in the review rows.
- Interpretation: some rejects still appear structurally stronger than accepted reference cases on explicit metrics.
- Interpretation: accepted flow still looks like a narrow survival path through the funnel rather than a clearly superior structural class.
- Unknown: the current package cannot cleanly distinguish “better structure” from “stricter survival conditions.”

### F. What remains unknown
- Unknown: accepted sample is still sparse at 4 cases across 19 days.
- Unknown: accepted-to-close evidence is incomplete and uneven across the scope.
- Unknown: `3of3_fail` decomposition is missing.
- Unknown: `cum_delta_24h` is incomplete in this synthesized full-scope memo for some earlier accepted comparisons because the older local memo did not surface it explicitly.
- Unknown: `unclear_but_constructive` is still too broad to treat as a validated class.

### G. Next best research direction
- reconstruct `3of3_fail` sub-checks for `2026-03-31 01:46` and `2026-04-04 06:55`.
- isolate short `vwap_side` rejects with positive or constructive horizon patterns and compare them against accepted shorts on the same or adjacent sessions.
- split `unclear_but_constructive` by regime sign, VWAP side, and return-horizon shape.
- use the newly rebuilt sequence-context and raw-micro bundle artifacts to study transition behavior around `2026-04-03 01:00` and `2026-04-04 06:55`.

### H. Missing-evidence escalation
- Fact: stronger causal claims require narrower missing artifacts, not broader speculation.
- Interpretation: the highest-value missing evidence is gate-stack transparency for `3of3_fail` and consistent accepted-to-close linkage for the late-window long accepts.

### I. Minimal additional data request
- one per-case decomposition artifact for `3of3_fail` sub-failures on selected paradox rejects;
- one accepted-flow join/export for `2026-04-03` and `2026-04-04` accepted longs with explicit outcome linkage if available;
- one session-local comparison extract for the strongest same-side reject and accepted pairs already identified in the bundle.