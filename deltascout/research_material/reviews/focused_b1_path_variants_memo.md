# Focused DeltaScout Memo: B1 Path Variants

## 1. Purpose

- Fact: this memo studies only possible path variants inside B1.
- Fact: it does not reopen Family B as a whole and does not summarize the full batch.
- Fact: the narrow question is whether B1 currently shows both a swept path and a cleaner continuation path, or whether that distinction is still too weak and subjective.

## 2. Working definition

- Fact: B1 is the confirmed operational Family B subtype.
- Fact: B1 is currently understood as continuation-pressure / post-alignment failure inside Family B.
- Interpretation: the path-variant question under review is:
  - does B1 currently show both a swept path and a cleaner continuation path?
  - or is that distinction still too weak / subjective on the current local files?

## 3. Cases under review

| Timestamp UTC | Reject reason | Bucket | Rule | selected_case_source | Sequence context available | Raw micro available | Blocker breakdown available |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-03-24 14:09:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | `2026-03-24.jsonl` | yes | yes | no dedicated selected-case blocker file found |
| 2026-03-24 14:45:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | `2026-03-24.jsonl` | yes, via `2026-03-24 14:09` sequence window | no direct selected-case target | no dedicated selected-case blocker file found |
| 2026-03-26 04:45:00 | `3of3_fail` | `possible_reversal_confirmation` | `IR_B1` | `2026-03-26.jsonl` | no | no | no dedicated selected-case blocker file found |
| 2026-03-29 12:30:00 | `3of3_fail` | `possible_continuation_pressure` | `IR_C2` | `2026-03-29.jsonl` | no | no | no dedicated selected-case blocker file found |

- Interpretation: `2026-03-26 04:45:00` is included because the task requires it and because the later B1/B2 clarification downgraded some IR_B1 continuation-like cases into the broader B1 lane unless stronger distinct-evidence appears.
- Unknown: no extra B1 case in the current local bundle has clearer path evidence than these four while staying inside the requested narrow scope.

## 4. Blocker signature comparison

- Fact: the requested blocker fields `price_check_pass`, `vol_check_pass`, `vwap_check_pass`, and `three_of_three_pass_count` are not present in the currently available local review files.
- Fact: no `selected_case_blocker_breakdown_<START>_to_<END>.csv` artifact is present in the local `reviews` tree.
- Fact: the available blocker-level evidence is limited to:
  - visible terminal reject reason `3of3_fail`
  - `reject_class=multi_condition` in daily `reject_dataset_*.csv`
- Fact: all four cases share that available blocker signature:
  - visible blocker `3of3_fail`
  - reject class `multi_condition`
- Interpretation: on the blocker fields currently visible, the proposed swept-vs-clean path variants do not separate.
- Unknown: whether hidden `three_of_three` sub-check differences exist cannot be tested from the current local files.

## 5. Sequence comparison

- Fact: sequence context is available only for the `2026-03-24 14:09:00` target window.
- Fact: that window shows a same-session continuation lane:
  - `2026-03-24 13:49:00` short `vwap_side`, above VWAP, precursor conflict
  - `2026-03-24 14:09:00` short `3of3_fail`, below VWAP
  - `2026-03-24 14:45:00` short `3of3_fail`, below VWAP
- Fact: `2026-03-24 14:09:00` therefore sits after an above-VWAP precursor and inside a same-session persistence cluster.
- Fact: `2026-03-24 14:45:00` sits later in that same continuation lane.
- Interpretation: the `2026-03-24` pair is the clearest current evidence for B1 as a persistent continuation lane rather than an isolated reject.

- Unknown: no selected-case sequence context is available for `2026-03-26 04:45:00`.
- Unknown: no selected-case sequence context is available for `2026-03-29 12:30:00`.
- Interpretation: because the non-`2026-03-24` cases lack local sequence windows, the current files do not show whether they represent:
  - a dirty continuation lane with precursor conflict,
  - a cleaner continuation lane,
  - or an isolated post-alignment failure without visible same-session persistence.

## 6. Raw micro path comparison

- Fact: raw micro is available only for `2026-03-24 14:09:00` among the required cases.
- Fact: the detailed pre-target path around `2026-03-24 14:09:00` is not cleanly one-directional:
  - `-8m` close `70212.90`, VWAP `70147.70`, `price_minus_vwap=65.20`
  - `-7m` close `70144.00`, VWAP `70195.94`, `price_minus_vwap=-51.94`
  - `-3m` close `70187.20`, VWAP `70256.76`, `price_minus_vwap=-69.56`
  - `-2m` close `70258.70`, VWAP `70226.57`, `price_minus_vwap=32.13`
  - `-1m` close `70339.50`, VWAP `70368.20`, `price_minus_vwap=-28.70`
  - `0m` close `70305.00`, VWAP `70286.55`, `price_minus_vwap=18.45`
- Fact: the immediate post-target path then releases sharply down:
  - `+1m` close `70282.10`
  - `+2m` close `70171.50`
  - `+3m` close `70000.30`
  - `+4m` close `69822.10`
  - `+5m` close `69799.90`
- Interpretation: `2026-03-24 14:09:00` is the strongest current swept-B1 example because the path before release is visibly mixed / sweep-affected, then resolves into a sharper downside continuation.

- Fact: no raw micro is available for `2026-03-24 14:45:00`, `2026-03-26 04:45:00`, or `2026-03-29 12:30:00` in the current selected-case bundle.
- Interpretation: the current files therefore cannot directly show whether any of those three cases had:
  - a cleaner immediate downside continuation,
  - a smaller upper-liquidity sweep before release,
  - or a similarly dirty pre-release path.

- Fact: two weak proxy fields exist in daily reject datasets:
  - `prev_price`
  - `prev_vwap`
- Fact: those proxies suggest the later required cases are already well below VWAP at the event minute:
  - `2026-03-24 14:45`: current `70305.69` vs VWAP `70836.0`
  - `2026-03-26 04:45`: current `70860.75` vs VWAP `71202.0`
  - `2026-03-29 12:30`: current `66480.24` vs VWAP `66726.0`
- Interpretation: these event-level proxies are compatible with cleaner already-released downside states, but they do not prove a clean path after the signal zone because the minute-by-minute micro path is missing.
- Unknown: no direct raw-micro evidence currently identifies a strongest clean-B1 example with the same confidence as the swept `2026-03-24 14:09:00` example.

## 7. Hard variant verdict

- Interpretation: **B1 may show path variation, but current evidence is too thin**.

Why:

- Fact: a useful swept-B1 reading is supported by one strong case: `2026-03-24 14:09:00`.
- Fact: that case has all three evidence layers needed for a path reading:
  - shared B1-style blocker signature at the visible level (`3of3_fail`, `multi_condition`)
  - same-session continuation cluster with precursor conflict
  - raw micro showing mixed / sweep-affected pre-release movement before a stronger downside release
- Fact: the proposed clean-B1 side does not have equivalent evidence depth in the current bundle.
- Fact: `2026-03-24 14:45:00`, `2026-03-26 04:45:00`, and `2026-03-29 12:30:00` lack selected-case raw micro, and two of them also lack selected-case sequence windows.
- Interpretation: this means the current files support path variation as a plausible research reading, but not yet as a repeatable or well-resolved split.
- Interpretation: the strongest current swept-B1 example is `2026-03-24 14:09:00`.
- Interpretation: the strongest current clean-B1 candidate is `2026-03-29 12:30:00`, but only as a weak candidate because it has B1 labeling and a milder already-below-VWAP event state without matching raw-micro confirmation.
- Unknown: what remains unresolved is whether the apparent clean variant repeats, whether `2026-03-29 12:30:00` truly had a cleaner release path, and whether `2026-03-26 04:45:00` belongs in the same lane after direct path evidence is exposed.

## 8. Minimal next request

- Fact: artifact 1 wanted: `selected_case_raw_feed_micro_<START>_to_<END>.csv` coverage that includes `2026-03-24 14:45:00`, `2026-03-26 04:45:00`, and `2026-03-29 12:30:00`.
- Fact: why it matters: it would show whether upper-liquidity sweep before release is actually present in some B1 cases and absent in others.
- Fact: ambiguity resolved: whether the path distinction repeats or is only anecdotal from `2026-03-24 14:09:00`.

- Fact: artifact 2 wanted: selected-case sequence context centered on `2026-03-26 04:45:00` and `2026-03-29 12:30:00`.
- Fact: why it matters: path cleanliness is more convincing when tied to same-session continuation-lane behavior rather than isolated event metrics.
- Fact: ambiguity resolved: whether those cases sit in a dirty continuation lane with precursors or in a cleaner already-released lane.

- Fact: artifact 3 wanted: `selected_case_blocker_breakdown_<START>_to_<END>.csv` for the required B1 cases.
- Fact: why it matters: it would show whether swept-vs-clean path candidates share the same hidden blocker signature or differ at the `three_of_three` component level.
- Fact: ambiguity resolved: whether the proposed path distinction is only path-shape variation or also a different internal blocker profile.
