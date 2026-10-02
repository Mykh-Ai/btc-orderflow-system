# Conservative Loss-Avoidance Counterfactual

Frozen shadow rule: block when component A OR component B is true. Component A is same-side delta-candidate percentile `<=50` over the source-of-truth 24h cutoff window. Component B is trusted `oi_change_60m < 0` AND direction-adjusted `buy_sell_delta_pct_240m < 0.06`. Unknown/untrusted values are kept, never blocked automatically. `oi_change_240m` is not used.

## Before / after

| Group | Cohort | Candidates | Filled | Resolved | Plain SL | TP1->SL | Protected | Gross PnL | Net PnL | Expectancy/fill | Blocked candidates/fills |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `GATE_REJECT` | `BASELINE_BEFORE_FILTER` | 21 | 21 | 21 | 15 | 3 | 3 | -189.56 | -295.37 | -14.07 | 0/0 |
| `GATE_REJECT` | `COUNTERFACTUAL_AFTER_FILTER` | 21 | 21 | 21 | 15 | 3 | 3 | -189.56 | -295.37 | -14.07 | 0/0 |
| `GATE_REJECT` | `BLOCKED_BY_FILTER` | 0 | 0 | 0 | 0 | 0 | 0 | 0.00 | 0.00 | n/a | 0/0 |
| `PEAK_EMIT_BASELINE` | `BASELINE_BEFORE_FILTER` | 32 | 28 | 28 | 12 | 6 | 10 | 371.17 | 232.03 | 8.29 | 0/0 |
| `PEAK_EMIT_BASELINE` | `COUNTERFACTUAL_AFTER_FILTER` | 32 | 28 | 28 | 12 | 6 | 10 | 371.17 | 232.03 | 8.29 | 0/0 |
| `PEAK_EMIT_BASELINE` | `BLOCKED_BY_FILTER` | 0 | 0 | 0 | 0 | 0 | 0 | 0.00 | 0.00 | n/a | 0/0 |

## Outcome protection guardrail

| Group | Component | Plain SL blocked | TP1->SL blocked | Protected blocked | Unknown among all candidates |
|---|---|---:|---:|---:|---:|
| `GATE_REJECT` | `component_a_weak_peak_le_50` | 0/15 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 0/21 |
| `GATE_REJECT` | `component_b_oi_down_60_and_weak_240m_flow` | 0/15 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 3/21 |
| `GATE_REJECT` | `conservative_union` | 0/15 (0.0%) | 0/3 (0.0%) | 0/3 (0.0%) | 3/21 |
| `PEAK_EMIT_BASELINE` | `component_a_weak_peak_le_50` | 0/12 (0.0%) | 0/6 (0.0%) | 0/10 (0.0%) | 0/32 |
| `PEAK_EMIT_BASELINE` | `component_b_oi_down_60_and_weak_240m_flow` | 0/12 (0.0%) | 0/6 (0.0%) | 0/10 (0.0%) | 3/32 |
| `PEAK_EMIT_BASELINE` | `conservative_union` | 0/12 (0.0%) | 0/6 (0.0%) | 0/10 (0.0%) | 3/32 |

## Unknown and untrusted coverage

| Group | Component B known | Component B unknown | OI untrusted | 240m directional flow unknown | Union unknown (kept) |
|---|---:|---:|---:|---:|---:|
| `GATE_REJECT` | 18/21 | 3/21 | 3/21 | 0/21 | 3/21 |
| `PEAK_EMIT_BASELINE` | 29/32 | 3/32 | 3/32 | 1/32 | 3/32 |

## PEAK component comparison on corrected replay

Unknown component values are kept. Net PnL and expectancy refer to the replay cohort left after applying that component alone.

| Component | Blocked fills | Blocked Plain/TP1->SL/Protected | Kept fills | Kept net PnL | Kept expectancy/fill |
|---|---:|---:|---:|---:|---:|
| `component_a_weak_peak_le_50` | 0 | 0/0/0 | 28 | 232.03 | 8.29 |
| `component_b_oi_down_60_and_weak_240m_flow` | 0 | 0/0/0 | 28 | 232.03 | 8.29 |
| `conservative_union` | 0 | 0/0/0 | 28 | 232.03 | 8.29 |

## Operational PEAK guardrail

This table uses comparable, non-test operational outcomes and the same cutoff-safe candidate flags. Operational labels are not overwritten by replay labels.

| Component | Comparable operational trades | Plain SL blocked | TP1->SL blocked | Protected blocked |
|---|---:|---:|---:|---:|
| `component_a_weak_peak_le_50` | 0 | 0/0 | 0/0 | 0/0 |
| `component_b_oi_down_60_and_weak_240m_flow` | 0 | 0/0 | 0/0 | 0/0 |
| `conservative_union` | 0 | 0/0 | 0/0 | 0/0 |

Replay lifecycle mismatch against these operational outcomes: `PLAIN_SL` 0/0, `TP1_SL` 0/0, `TP1_TP2_TRAILING_STOP` 0/0.

## Every replay-protected blocked case and operational parity

Replay protected outcomes remain the conservative denominator above. A joined operational lifecycle is reported separately and does not rewrite replay results.

| Candidate | Group | Parity join | Join source | Replay lifecycle | Operational trade | Operational lifecycle | Entry match | SL/TP1/TP2 plan delta | Classification |
|---|---|---|---|---|---|---|---|---:|---|
| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | No replay-protected blocked cases |

## Interpretation

- TP1->SL is treated as scratch-neutral; blocking it is not the main guardrail failure.
- Blocking a `TP1_TP2_TRAILING_STOP` is the critical false positive and must be reported explicitly.
- The rule was discovered on accepted PEAK lifecycle evidence. Applying it to ALMOST 2/3 is a domain-transfer test, not validation of the rule for that cohort.
- The earlier single-feed `v5` run used BTCUSDT Futures OHLC as an execution proxy and is superseded for lifecycle and expectancy conclusions by this dual-feed run.
- Targeted `2026-04-23` candidate is absent from this cohort and requires audit.
- This is an independent-opportunity counterfactual. It does not re-sequence the one-position portfolio after removing signals.
- No live admission logic is changed by this report.
