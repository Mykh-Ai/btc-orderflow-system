# Focused DeltaScout Memo: Short-Side Reject Families

Source scope: existing local review materials under `deltascout/research_material/reviews`, plus the already available batch review, index summary, selected-case sequence context CSV, and selected-case raw-feed micro CSV.

## 1. Memo purpose

- Fact: this memo isolates only two short-side reject families from the currently available local package.
- Fact: it is not a full-batch summary and does not attempt to restate all batch-level findings.
- Interpretation: the practical question is whether the two families represent different transition types, different timing failures, different structural failure modes, or different setup-discovery candidates.

## 2. Family definitions

### Family A
- Fact: Family A consists of short-side rejects with `price_vs_vwap_side=above`, especially visible `vwap_side` rejects.
- Fact: same-session related short-side `direction_mismatch` rows are included when they appear in the same transition cluster.
- Interpretation: this is a research family, not a validated setup class.

### Family B
- Fact: Family B consists of short-side rejects with `price_vs_vwap_side=below` that still fail deeper in the funnel, especially visible `3of3_fail` rejects.
- Fact: same-session related short-side `direction_mismatch` rows are included when they belong to the same cluster.
- Interpretation: this is also a research family, not a validated setup class.

## 3. Family A - evidence review

- Fact: the strongest Family A clusters in the current local materials are:
  - `2026-03-21 09:10` to `09:40`
  - `2026-03-29 05:01` to `08:50`
  - `2026-04-01 06:25`
  - with an additional trap-like example at `2026-03-23 12:25`.
- Fact: `2026-03-21 09:15` is a short `vwap_side` reject with bucket `possible_reversal_onset`, `cum_delta_60m=-736.905`, `cum_delta_180m=-909.203`, `ret_15m=128.4`, `ret_60m=30.9`, and `price_vs_vwap_side=above`.
- Fact: the same cluster contains short `direction_mismatch` rows at `09:10` and `09:40`, both also `above` VWAP.
- Interpretation: this cluster behaves like an unfinished same-session short transition rather than an isolated reject.
- Fact: `2026-03-29 08:50` is a short `vwap_side` reject with bucket `possible_reversal_onset`, `cum_delta_60m=-448.437`, `cum_delta_180m=-397.013`, `ret_15m=18.0`, `ret_60m=60.0`, and `price_vs_vwap_side=above`.
- Fact: nearby same-side rows include `08:15` short `direction_mismatch` and `08:20` short `vwap_side` `possible_reversal_confirmation`, all still `above` VWAP.
- Interpretation: the `2026-03-29` morning cluster looks more like repeated short attempts under unresolved placement conflict than like a one-off false signal.
- Fact: `2026-04-01 06:25` is a short `vwap_side` reject with bucket `unclear_but_constructive`, `cum_delta_60m=1273.677`, `cum_delta_180m=2370.333`, `ret_15m=229.1`, `ret_60m=318.8`, and `price_vs_vwap_side=above`.
- Interpretation: this case widens Family A beyond reversal-labeled buckets; above-VWAP placement can block a case even when the visible metrics look highly constructive.
- Fact: the visible blocker that dominates Family A is `vwap_side`, with nearby short `direction_mismatch` often appearing as same-cluster friction rather than a separate family.
- Fact: raw-feed micro context for `2026-03-21 09:15` shows the event minute close `70691.80` versus VWAP `70691.30`, then the next 5 to 15 minutes trade back below VWAP (`70625.20` vs `70633.25`, then `70550.10` vs `70551.36`).
- Interpretation: this suggests Family A often forms near an above-VWAP edge where short pressure is visible but not yet structurally resolved at the event timestamp.
- Fact: raw-feed micro for `2026-03-29 08:50` shows the target minute close `66694.90` versus VWAP `66693.10`, then price softens by +15 and +30 minutes while staying near or below later VWAP snapshots.
- Interpretation: this reads more like reversal onset or unresolved transition than clean failed continuation.
- Fact: raw-feed micro for `2026-04-01 06:25` shows strong buy-dominant minute flow into the event (`BuyQty 270.792` vs `SellQty 99.207`, `LiqBuyQty 2.541`) while price still prints below contemporaneous VWAP in the micro extract (`68812.30` vs `68826.46`).
- Unknown: the family definition depends on review-level `price_vs_vwap_side`, while the micro extract uses raw `Close-VWAP`; the files do not explain the reconciliation rule between those two layers.
- Interpretation: Family A currently looks most like a mix of reversal onset, trap / false break, and unresolved transition. It does not read as one uniform structural family.

## 4. Family B - evidence review

- Fact: the strongest Family B cases in the current local materials are:
  - `2026-03-24 14:09` and `14:45`
  - `2026-03-31 01:46`
  - with accepted-reference adjacency at `2026-03-29 19:22` to `19:23`.
- Fact: `2026-03-24 14:09` is a short `3of3_fail` reject with bucket `possible_continuation_pressure`, `cum_delta_60m=-2169.326`, `cum_delta_180m=-1821.613`, `ret_15m=222.2`, `ret_60m=-462.9`, and `price_vs_vwap_side=below`.
- Fact: the same session also contains `13:49` short `vwap_side` `possible_reversal_confirmation` above VWAP and `14:45` another short `3of3_fail` below VWAP.
- Interpretation: this session shows a transition from an above-VWAP Family A state into a below-VWAP Family B state, but the deeper funnel still terminates the short idea.
- Fact: `2026-03-31 01:46` is a short `3of3_fail` reject with bucket `unclear_but_constructive`, `cum_delta_60m=2578.497`, `cum_delta_180m=3236.195`, `ret_15m=199.8`, `ret_60m=841.2`, and `price_vs_vwap_side=below`.
- Interpretation: this is the strongest Family B paradox case because visible structural alignment and forward-return profile are both strong, yet the deeper funnel still rejects it.
- Fact: the local sequence window around `2026-03-31 01:46` contains a prior short `direction_mismatch` at `01:09`, also below VWAP.
- Interpretation: Family B can include same-side conflict even after below-VWAP alignment is present.
- Fact: the visible blocker that dominates Family B is `3of3_fail`, not `vwap_side`.
- Fact: raw-feed micro for `2026-03-24 14:09` shows the target minute close `70305.00` versus VWAP `70286.55`, then a sharp drop by +5 minutes to `69799.90` with VWAP `69766.38`, while sell quantity dominates that minute (`783.637` vs `530.466`).
- Interpretation: this looks more like continuation pressure or late-stage directional follow-through than a simple false break.
- Fact: raw-feed micro for `2026-03-31 01:46` shows the target minute close `67940.50` versus VWAP `67929.79`, then price softens by +5 and +15 minutes before rebounding by +30, while OI climbs from `89952.82` to `90177.81`.
- Interpretation: this family appears later in the structural process: VWAP-side alignment is already present, but the deeper gate stack still finds something unresolved or mistimed.
- Interpretation: Family B currently looks like a mix of continuation pressure, reversal confirmation, and unresolved transition. It reads later-stage than Family A, but not mechanically cleaner.
- Unknown: the files do not decompose `3of3_fail`, so the decisive hidden blocker remains opaque.

## 5. Side-by-side comparison

- Fact: Family A is defined by `price_vs_vwap_side=above`; Family B is defined by `price_vs_vwap_side=below` plus deeper failure such as `3of3_fail`.
- Interpretation: the most visible structural difference is placement stage. Family A fails before alignment is complete; Family B fails after alignment appears to have been achieved.
- Fact: Family A often carries mixed-to-negative same-direction cumulative delta support, such as `2026-03-21 09:15` (`-736.905`, `-909.203`) and `2026-03-29 08:50` (`-448.437`, `-397.013`), but it can also include highly positive contexts like `2026-04-01 06:25` (`1273.677`, `2370.333`).
- Fact: Family B includes strongly negative same-direction delta support at `2026-03-24 14:09` and strongly positive support at `2026-03-31 01:46`.
- Interpretation: cumulative delta sign alone does not separate the families; timing and gate location separate them more clearly than directional magnitude does.
- Fact: Family A frequently shows positive `ret_15m` and sometimes positive `ret_60m` even while failing early on `vwap_side`; examples are `2026-03-21 09:15`, `2026-03-21 11:30`, `2026-03-29 08:50`, and `2026-04-01 06:25`.
- Fact: Family B can show either mixed or very strong return-horizon behavior: `2026-03-24 14:09` has `ret_15m=222.2` but `ret_60m=-462.9`, while `2026-03-31 01:46` has `199.8` and `841.2`.
- Interpretation: Family A looks earlier and more placement-sensitive; Family B looks later and more gate-stack-sensitive.
- Fact: same-session evolution differs. `2026-03-24` shows a Family A case at `13:49` followed by Family B cases at `14:09` and `14:45`; `2026-03-29` shows repeated Family A shorts in the morning, then a below-VWAP accepted short much later at `19:23`.
- Interpretation: the available files support a timing gradient where Family A can precede Family B or accepted states, but the progression is not deterministic.
- Unknown: the current materials do not prove whether Family B is always later than Family A, because the sequence windows are local rather than full-session causal traces.

## 6. Relationship to accepted short reference cases

- Fact: the accepted short references in the local package are `2026-03-20 00:40` and `2026-03-29 19:23`, both `PEAK_EMIT`, both `price_vs_vwap_side=below`, both with `join_status=window_match`, and both with `close_reason=SL`.
- Fact: the accepted cases show that below-VWAP short placement can survive the funnel and join to a close outcome record.
- Fact: they do not prove that accepted short flow is profitable or that accepted shorts are always structurally superior to rejected shorts.
- Fact: Family A contains cases that are stronger than accepted references on some metrics. `2026-04-01 06:25` is stronger than accepted `2026-03-29 19:23` on `cum_delta_60m`, `cum_delta_180m`, `ret_15m`, and `ret_60m`, but weaker on placement because it is still `above` VWAP.
- Fact: Family B also contains cases that are stronger than accepted references on some metrics. `2026-03-31 01:46` is stronger than accepted `2026-03-29 19:23` on both cumulative delta measures and both forward-return horizons while sharing `price_vs_vwap_side=below`.
- Interpretation: accepted references help show what survived, but they do not define the outer limit of structurally interesting short-side material.
- Unknown: the files do not reveal whether the accepted cases passed because they are genuinely better structures or because the funnel is selecting a narrower slice of a broader short-side transition field.

## 7. Strongest paradoxes

- Fact: comparing Family B case `2026-03-31 01:46` with accepted short `2026-03-29 19:23`, the reject is stronger on `cum_delta_60m` (`2578.497` vs `68.985`), `cum_delta_180m` (`3236.195` vs `-802.882`), `ret_15m` (`199.8` vs `8.6`), and `ret_60m` (`841.2` vs `52.8`), while both are `below` VWAP.
- Interpretation: this is the strongest below-VWAP paradox in the current package.
- Unknown: the hidden sub-failures behind `3of3_fail` remain unobserved.

- Fact: comparing Family A case `2026-03-29 08:50` with accepted short `2026-03-29 19:23`, the reject is stronger on `ret_15m` (`18.0` vs `8.6`) and `ret_60m` (`60.0` vs `52.8`), more negative on `cum_delta_60m` (`-448.437` vs `68.985`), but weaker on placement (`above` vs `below` VWAP).
- Interpretation: this is the clearest same-session above-VWAP paradox.
- Unknown: the files do not show whether VWAP-side was the only true blocker.

- Fact: on `2026-03-24`, the sequence moves from a Family A short at `13:49` (`vwap_side`, above VWAP) to Family B shorts at `14:09` and `14:45` (`3of3_fail`, below VWAP).
- Interpretation: this suggests that below-VWAP alignment can appear later without resolving the underlying funnel conflict.
- Unknown: whether this is timing failure, regime transition, or hidden multi-rule conflict cannot be settled from the current files.

## 8. Working hypotheses

- Hypothesis: Family A often represents earlier short-side transition attempts where directional pressure is visible but VWAP-side placement is not yet structurally aligned.
- Why it may matter: if true, Family A is useful for timing research rather than direct setup replication.
- Which family it belongs to: Family A.
- What would need to be checked next: longer same-session sequence exports around repeated above-VWAP short attempts.

- Hypothesis: Family B often represents later-stage short structures where visible placement has aligned, but deeper gate conditions still reject the case.
- Why it may matter: this family may be closer to future setup-class discovery because it has already passed the most obvious placement barrier.
- Which family it belongs to: Family B.
- What would need to be checked next: per-case decomposition of `3of3_fail` sub-checks.

- Hypothesis: Family A and Family B are related in some sessions as different timing stages of the same transition process, but not in all sessions.
- Why it may matter: this would explain why `2026-03-24` shows a visible A-to-B sequence while `2026-03-31` is dominated by Family B without a clear Family A precursor in the local window.
- Which family it belongs to: both.
- What would need to be checked next: wider session-local event traces extending beyond the current +-90 minute sequence windows.

- Hypothesis: Family B is the stronger current research target for future setup-class discovery, while Family A is the stronger target for timing and pre-alignment transition study.
- Why it may matter: the two families may deserve different research objectives instead of one combined filter-loosening strategy.
- Which family it belongs to: both.
- What would need to be checked next: direct paired comparisons between later accepted shorts and earlier same-side A/B family rejects in the same or adjacent sessions.

## 9. Research verdict

- Interpretation: Family A and Family B do not look like fully separate worlds, but they also do not look like the same phenomenon in a trivial sense.
- Interpretation: the current files support treating Family A as an earlier, placement-conflicted short-side transition family and Family B as a later, deeper-failure short-side transition family.
- Interpretation: Family B is the stronger current research target because it already contains below-VWAP alignment and, in the best cases, stronger metric profiles than accepted references.
- Interpretation: Family A is more promising for studying timing failure and transition onset, especially around repeated above-VWAP short attempts that later resolve or fail.
- Unknown: Family A remains more ambiguous because raw micro and review placement do not reconcile perfectly, and because visible `vwap_side` may or may not be the only real blocker.
- Interpretation: the strongest current setup-discovery lead is Family B, but the strongest transition-timing lead is Family A.

## 10. Minimal additional data request

- Fact: request 1: per-case `3of3_fail` sub-check breakdown for selected Family B rejects.
- Fact: why it matters: it would show which deeper gate actually terminates below-VWAP short structures.
- Fact: ambiguity resolved: whether Family B failures are timing failures, hidden structure failures, or another opaque gate component.

- Fact: request 2: wider same-session event sequence export for the short clusters around `2026-03-21 09:15`, `2026-03-24 14:09`, `2026-03-29 08:50`, and `2026-03-31 01:46`.
- Fact: why it matters: it would clarify whether Family A tends to evolve into Family B or accepted states later in the same session.
- Fact: ambiguity resolved: whether the two families are sequential timing stages or only loosely related families.

- Fact: request 3: one reconciled mapping note between review-level `price_vs_vwap_side` and raw-feed `Close-VWAP` snapshots for selected cases.
- Fact: why it matters: current micro extracts sometimes show raw `Close < VWAP` while the review layer labels the case `above` VWAP.
- Fact: ambiguity resolved: whether the apparent discrepancy is due to event-time alignment, averaging logic, or review-layer derivation rules.
