# Conservative Loss-Avoidance Counterfactual

Frozen shadow rule: block when component A OR component B is true. Component A is same-side delta-candidate percentile `<=50` over the source-of-truth 24h cutoff window. Component B is trusted `oi_change_60m < 0` AND direction-adjusted `buy_sell_delta_pct_240m < 0.06`. Unknown/untrusted values are kept, never blocked automatically. `oi_change_240m` is not used.

## Before / after

| Group | Cohort | Candidates | Filled | Resolved | Plain SL | TP1->SL | Protected | Gross PnL | Net PnL | Expectancy/fill | Blocked candidates/fills |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `GATE_REJECT` | `BASELINE_BEFORE_FILTER` | 30 | 29 | 29 | 16 | 5 | 8 | 71.68 | -73.34 | -2.53 | 3/3 |
| `GATE_REJECT` | `COUNTERFACTUAL_AFTER_FILTER` | 27 | 26 | 26 | 14 | 5 | 7 | 65.19 | -64.84 | -2.49 | 3/3 |
| `GATE_REJECT` | `BLOCKED_BY_FILTER` | 3 | 3 | 3 | 2 | 0 | 1 | 6.49 | -8.50 | -2.83 | 3/3 |
| `PEAK_EMIT_BASELINE` | `BASELINE_BEFORE_FILTER` | 50 | 46 | 46 | 26 | 6 | 14 | 254.27 | 24.31 | 0.53 | 18/18 |
| `PEAK_EMIT_BASELINE` | `COUNTERFACTUAL_AFTER_FILTER` | 32 | 28 | 28 | 12 | 6 | 10 | 371.17 | 232.03 | 8.29 | 18/18 |
| `PEAK_EMIT_BASELINE` | `BLOCKED_BY_FILTER` | 18 | 18 | 18 | 14 | 0 | 4 | -116.91 | -207.73 | -11.54 | 18/18 |

## Outcome protection guardrail

| Group | Component | Plain SL blocked | TP1->SL blocked | Protected blocked | Unknown among all candidates |
|---|---|---:|---:|---:|---:|
| `GATE_REJECT` | `component_a_weak_peak_le_50` | 0/16 (0.0%) | 0/5 (0.0%) | 1/8 (12.5%) | 0/30 |
| `GATE_REJECT` | `component_b_oi_down_60_and_weak_240m_flow` | 2/16 (12.5%) | 0/5 (0.0%) | 1/8 (12.5%) | 1/30 |
| `GATE_REJECT` | `conservative_union` | 2/16 (12.5%) | 0/5 (0.0%) | 1/8 (12.5%) | 1/30 |
| `PEAK_EMIT_BASELINE` | `component_a_weak_peak_le_50` | 6/26 (23.1%) | 0/6 (0.0%) | 0/14 (0.0%) | 0/50 |
| `PEAK_EMIT_BASELINE` | `component_b_oi_down_60_and_weak_240m_flow` | 11/26 (42.3%) | 0/6 (0.0%) | 4/14 (28.6%) | 3/50 |
| `PEAK_EMIT_BASELINE` | `conservative_union` | 14/26 (53.8%) | 0/6 (0.0%) | 4/14 (28.6%) | 3/50 |

## Unknown and untrusted coverage

| Group | Component B known | Component B unknown | OI untrusted | 240m directional flow unknown | Union unknown (kept) |
|---|---:|---:|---:|---:|---:|
| `GATE_REJECT` | 29/30 | 1/30 | 1/30 | 0/30 | 1/30 |
| `PEAK_EMIT_BASELINE` | 47/50 | 3/50 | 3/50 | 1/50 | 3/50 |

## PEAK component comparison on corrected replay

Unknown component values are kept. Net PnL and expectancy refer to the replay cohort left after applying that component alone.

| Component | Blocked fills | Blocked Plain/TP1->SL/Protected | Kept fills | Kept net PnL | Kept expectancy/fill |
|---|---:|---:|---:|---:|---:|
| `component_a_weak_peak_le_50` | 6 | 6/0/0 | 40 | 261.60 | 6.54 |
| `component_b_oi_down_60_and_weak_240m_flow` | 15 | 11/0/4 | 31 | 114.73 | 3.70 |
| `conservative_union` | 18 | 14/0/4 | 28 | 232.03 | 8.29 |

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
| `SCOUT_2220bb578141714c70b2` | `PEAK_EMIT_BASELINE` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_f3b43969d34fe0125a71` | `PEAK_EMIT_BASELINE` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_bf8fcdb7273d7e7333bf` | `PEAK_EMIT_BASELINE` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_bb2d62b91783ae15dad5` | `PEAK_EMIT_BASELINE` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_a45b41f23681ec0aa7d0` | `GATE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |

## Interpretation

- TP1->SL is treated as scratch-neutral; blocking it is not the main guardrail failure.
- Blocking a `TP1_TP2_TRAILING_STOP` is the critical false positive and must be reported explicitly.
- The rule was discovered on accepted PEAK lifecycle evidence. Applying it to ALMOST 2/3 is a domain-transfer test, not validation of the rule for that cohort.
- The earlier single-feed `v5` run used BTCUSDT Futures OHLC as an execution proxy and is superseded for lifecycle and expectancy conclusions by this dual-feed run.
- Targeted `2026-04-23` regression: filter=`BLOCKED`, replay lifecycle=`PLAIN_SL`, operational lifecycle=`None`.
- This is an independent-opportunity counterfactual. It does not re-sequence the one-position portfolio after removing signals.
- No live admission logic is changed by this report.
