# Focused DeltaScout Clarification Memo: Family B1 vs B2 Boundary

## 1. Purpose

- Fact: this memo exists only to clarify the B1 vs B2 boundary inside Family B.
- Fact: it does not re-summarize Family B as a whole and does not reopen the full batch review.
- Fact: the central question is whether B2 is a real subtype distinct from B1, or whether B2 is better treated as a weaker / thinner edge case of B1.

## 2. Operational definitions under review

- Fact: current working subtype definitions are:
  - B1 = continuation-pressure post-alignment failures
  - B2 = reversal-confirmation timing failures
- Fact: both B1 and B2 sit inside Family B, which already requires:
  - short-side reject
  - `price_vs_vwap_side=below`
  - deeper-funnel failure
  - priority reject reason `3of3_fail`
- Interpretation: this memo is testing whether the B1/B2 split is actually supported by the currently available local files.

## 3. Cases under review

| Timestamp UTC | Reject reason | Bucket | Rule | Isolated or cluster-like | Raw micro available | Sequence context available |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-03-24 14:09:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | cluster-like | yes | yes |
| 2026-03-24 14:45:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | cluster-like | no direct selected-case target | yes via 14:09 cluster |
| 2026-03-29 12:12:00 | `3of3_fail` | `possible_reversal_confirmation` | `IR_B1` | isolated in current bundle | no | no |
| 2026-03-29 12:30:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | isolated in current bundle | no | no |
| 2026-03-29 19:23:00 | accepted reference only | accepted short `PEAK_EMIT` | n/a | isolated in selected bundle | yes | yes |

- Fact: `2026-03-24 13:49:00` remains relevant same-session precursor context for the `2026-03-24` cluster because it is a short `vwap_side` reject immediately before the two below-VWAP `3of3_fail` rows.
- Unknown: the currently available selected-case bundle does not provide local sequence or raw micro coverage for the `2026-03-29 12:12` and `12:30` midday pair.

## 4. Evidence comparison: B1 candidates vs B2 candidate

### Direct metric comparison

| Case | price_vs_vwap_side | cum_delta_60m | cum_delta_180m | ret_15m | ret_60m | visible blocker |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-03-24 14:09:00 | below | -2169.326 | -1821.613 | 222.2 | -462.9 | `3of3_fail` |
| 2026-03-24 14:45:00 | below | -1334.064 | -2580.498 | -152.1 | -466.9 | `3of3_fail` |
| 2026-03-29 12:30:00 | below | -402.640 | -581.966 | 13.3 | -52.5 | `3of3_fail` |
| 2026-03-29 12:12:00 | below | -69.065 | -204.488 | -31.2 | 11.2 | `3of3_fail` |

- Fact: all four cases share the same visible blocker and the same aligned `below` VWAP-side placement.
- Fact: the `2026-03-24` B1 cluster has materially larger negative medium-horizon short pressure than `2026-03-29 12:12:00`:
  - `cum_delta_60m`: `-2169.326` and `-1334.064` vs `-69.065`
  - `cum_delta_180m`: `-1821.613` and `-2580.498` vs `-204.488`
- Fact: `2026-03-29 12:30:00` is closer to the B1 metric shape than `2026-03-29 12:12:00`:
  - `cum_delta_60m`: `-402.640` vs `-69.065`
  - `cum_delta_180m`: `-581.966` vs `-204.488`
  - bucket and rule also match B1 (`possible_continuation_pressure`, `IR_C2`).
- Fact: `2026-03-29 12:12:00` differs from the B1-labeled cases on bucket/rule only:
  - `possible_reversal_confirmation`
  - `IR_B1`
- Interpretation: the metric gap between `2026-03-29 12:12:00` and the B1 cluster is real, but the current files do not show that this metric gap corresponds to a different same-session process.

### Cluster behavior and persistence

- Fact: the `2026-03-24` B1 cases behave as a same-session deeper-failure cluster:
  - `13:49` short `vwap_side`, above VWAP
  - `14:09` short `3of3_fail`, below VWAP
  - `14:45` short `3of3_fail`, below VWAP
- Fact: the `2026-03-24` sequence therefore shows persistence after VWAP alignment is achieved.
- Fact: the current selected-case bundle does not show a same-session continuation chain around `2026-03-29 12:12` or `12:30`.
- Unknown: whether the `2026-03-29` midday pair is a real cluster, two isolated rows, or two timestamps inside one hidden same-session process.

### Post-event raw-feed behavior

- Fact: raw micro is available for `2026-03-24 14:09:00` and not available for either `2026-03-29` midday case.
- Fact: `2026-03-24 14:09:00` shows continued downside process after rejection:
  - event close `70305.00`
  - `+5m` close `69799.90`
  - `+30m` close `69899.90`
- Fact: accepted reference `2026-03-29 19:23:00` also shows a measured post-event downside sequence, but at much smaller amplitude:
  - event close `66422.20`
  - `+5m` close `66392.80`
  - `+15m` close `66355.00`
  - `+30m` close `66323.50`
- Interpretation: the current raw micro evidence supports B1 continuation persistence on `2026-03-24`, but it does not help validate B2 because the relevant midday micro rows are absent.

## 5. Sequence-context clarification

- Fact: the `2026-03-24` cases behave like a same-session deeper-failure continuation cluster.
- Fact: the selected-case sequence file explicitly shows:
  - precursor short conflict at `2026-03-24 13:49:00`
  - target short `3of3_fail` at `2026-03-24 14:09:00`
  - later short `3of3_fail` at `2026-03-24 14:45:00`
- Interpretation: this is direct support for B1 as an operational subtype rather than a label-only grouping.

- Unknown: the current selected-case sequence materials do not cover `2026-03-29 12:12` and `2026-03-29 12:30`.
- Unknown: therefore the files do not show whether `2026-03-29 12:12` and `12:30` behave like the same subtype or different ones.
- Interpretation: the current bundle does not provide sequence evidence that `2026-03-29 12:12` is a genuinely distinct reversal-confirmation timing case.
- Interpretation: on current files alone, `2026-03-29 12:12` reads as a weaker, less-supported Family B member with a different bucket label, not as a sequence-validated distinct subtype.

## 6. Raw micro clarification

- Fact: the strongest B1 case with available raw micro is `2026-03-24 14:09:00`.
- Fact: its micro path shows continued short-side process after rejection rather than immediate invalidation:
  - `-5m`: close `70201.70`, VWAP `70233.33`
  - `0m`: close `70305.00`, VWAP `70286.55`
  - `+5m`: close `69799.90`, VWAP `69766.38`
  - `+15m`: close `69883.90`, VWAP `69873.97`
  - `+30m`: close `69899.90`, VWAP `69915.98`
- Interpretation: this looks more like continuation persistence or late-entry risk than immediate invalidation.

- Unknown: no raw micro is available in the current selected-case bundle for `2026-03-29 12:12` or `2026-03-29 12:30`.
- Interpretation: the files therefore cannot show whether the midday `2026-03-29` cases behaved like:
  - immediate invalidation
  - weaker continuation persistence
  - late-entry continuation
  - or a genuinely different reversal-confirmation timing path.
- Fact: because the decisive micro comparison is missing, raw micro evidence currently supports B1 more than B2.

## 7. Accepted reference comparison

- Fact: accepted short references help show that below-VWAP short cases can survive the funnel.
- Fact: accepted short references do not prove that accepted flow defines the correct subtype structure inside Family B.
- Interpretation: the B1/B2 boundary can be clarified mostly independently of accepted-flow sparsity, because the real issue is whether there is direct structural and sequence evidence for two different post-alignment failure processes.
- Fact: accepted references do not materially help separate B1 from B2 in the current bundle.
- Fact: they help only with perspective:
  - aligned `below` VWAP-side is survivable;
  - `3of3_fail` still hides the decisive missing discriminator.
- Unknown: accepted references do not reveal whether the midday `2026-03-29` pair splits into separate subtypes or one thinly evidenced lane.

## 8. Hard clarification verdict

- Interpretation: **B2 is not yet supported and is better treated as an edge case of B1**.

Why:

- Fact: structural differences currently supporting B2 are thin:
  - different bucket label (`possible_reversal_confirmation`)
  - different rule label (`IR_B1`)
  - weaker medium-horizon short pressure than the B1 cluster.
- Fact: metric differences currently supporting B2 are limited to one weaker case:
  - `2026-03-29 12:12` has `cum_delta_60m=-69.065`, `cum_delta_180m=-204.488`, `ret_15m=-31.2`, `ret_60m=11.2`
  - but `2026-03-29 12:30` sits nearby with B1 labels and a more continuation-compatible metric shape.
- Fact: sequence differences supporting B2 failed to materialize in the current files because there is no selected-case sequence context for the midday `2026-03-29` pair.
- Fact: raw-micro differences supporting B2 also failed to materialize because there is no selected-case raw micro for the midday `2026-03-29` pair.
- Interpretation: on current evidence, B2 is label-distinct but not process-distinct.
- Interpretation: the most defensible current treatment is that `2026-03-29 12:12` is a weaker / thinner edge case inside the broader B1-style post-alignment failure lane, not a sequence-validated standalone subtype.

- Interpretation: strongest operational subtype after clarification remains **B1**.
- Interpretation: strongest ambiguous case after clarification is **2026-03-29 12:12:00**.
- Unknown: what remains unresolved is whether `2026-03-29 12:12` becomes distinct once its same-session sequence and raw micro are exposed, and whether `3of3_fail` hides a genuinely different sub-check pattern for IR_B1 vs IR_C2 cases.

## 9. Minimal next request

- Fact: artifact 1 wanted: selected-case sequence context centered on `2026-03-29 12:12:00` and `2026-03-29 12:30:00`.
- Fact: why it matters: it would show whether the midday pair is one same-session deeper-failure cluster or two separate structures.
- Fact: ambiguity resolved: whether `2026-03-29 12:12` has sequence behavior distinct enough to justify B2.

- Fact: artifact 2 wanted: selected-case raw-feed micro extract for `2026-03-29 12:12:00` and `2026-03-29 12:30:00`.
- Fact: why it matters: the current B1/B2 boundary cannot be tested on post-event process without midday micro coverage.
- Fact: ambiguity resolved: whether `2026-03-29 12:12` shows immediate invalidation, weaker continuation, or the same continuation persistence already seen in B1.

- Fact: artifact 3 wanted: per-case `3of3_fail` sub-check breakdown for `2026-03-24 14:09:00`, `2026-03-24 14:45:00`, `2026-03-29 12:12:00`, and `2026-03-29 12:30:00`.
- Fact: why it matters: bucket and rule labels alone are currently doing too much work.
- Fact: ambiguity resolved: whether IR_B1 and IR_C2 are failing on genuinely different hidden gate components or collapsing into the same deeper-failure mechanism.
