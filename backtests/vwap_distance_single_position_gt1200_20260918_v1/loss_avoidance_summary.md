# Conservative Loss-Avoidance Counterfactual

Frozen shadow rule: block when component A OR component B is true. Component A is same-side delta-candidate percentile `<=50` over the source-of-truth 24h cutoff window. Component B is trusted `oi_change_60m < 0` AND direction-adjusted `buy_sell_delta_pct_240m < 0.06`. Unknown/untrusted values are kept, never blocked automatically. `oi_change_240m` is not used.

## Before / after

| Group | Cohort | Candidates | Filled | Resolved | Plain SL | TP1->SL | Protected | Gross PnL | Net PnL | Expectancy/fill | Blocked candidates/fills |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `VWAP_DISTANCE_REJECT` | `BASELINE_BEFORE_FILTER` | 96 | 78 | 77 | 37 | 17 | 23 | -76.11 | -463.78 | -5.95 | 26/24 |
| `VWAP_DISTANCE_REJECT` | `COUNTERFACTUAL_AFTER_FILTER` | 70 | 54 | 53 | 29 | 13 | 11 | -264.48 | -533.55 | -9.88 | 26/24 |
| `VWAP_DISTANCE_REJECT` | `BLOCKED_BY_FILTER` | 26 | 24 | 24 | 8 | 4 | 12 | 188.37 | 69.77 | 2.91 | 26/24 |

## Outcome protection guardrail

| Group | Component | Plain SL blocked | TP1->SL blocked | Protected blocked | Unknown among all candidates |
|---|---|---:|---:|---:|---:|
| `VWAP_DISTANCE_REJECT` | `component_a_weak_peak_le_50` | 8/37 (21.6%) | 4/17 (23.5%) | 12/23 (52.2%) | 0/96 |
| `VWAP_DISTANCE_REJECT` | `component_b_oi_down_60_and_weak_240m_flow` | 0/37 (0.0%) | 0/17 (0.0%) | 0/23 (0.0%) | 96/96 |
| `VWAP_DISTANCE_REJECT` | `conservative_union` | 8/37 (21.6%) | 4/17 (23.5%) | 12/23 (52.2%) | 70/96 |

## Unknown and untrusted coverage

| Group | Component B known | Component B unknown | OI untrusted | 240m directional flow unknown | Union unknown (kept) |
|---|---:|---:|---:|---:|---:|
| `VWAP_DISTANCE_REJECT` | 0/96 | 96/96 | 2/96 | 0/96 | 70/96 |

## PEAK component comparison on corrected replay

Unknown component values are kept. Net PnL and expectancy refer to the replay cohort left after applying that component alone.

| Component | Blocked fills | Blocked Plain/TP1->SL/Protected | Kept fills | Kept net PnL | Kept expectancy/fill |
|---|---:|---:|---:|---:|---:|
| `component_a_weak_peak_le_50` | 0 | 0/0/0 | 0 | 0.00 | n/a |
| `component_b_oi_down_60_and_weak_240m_flow` | 0 | 0/0/0 | 0 | 0.00 | n/a |
| `conservative_union` | 0 | 0/0/0 | 0 | 0.00 | n/a |

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
| `SCOUT_3d4fdbc05ffa89fcdfdb` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_d41d37701211b4402e57` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_12452d6155a7d7e3ca23` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_f21de443a7d3fc4ff0fb` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_83c6f0aa22ffeb23961f` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_b899749c4a2dc021c7c5` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_266eb209172c2055f434` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_dbcf63129100aa6e9e9c` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_2dfba1ce15e83ce1436a` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_ad40e39ceb229498c54a` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_c352721e39dd31baf511` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |
| `SCOUT_0766c7c3c4842fe23e8b` | `VWAP_DISTANCE_REJECT` | `UNMATCHED` | `` | `TP1_TP2_TRAILING_STOP` | `None` | `None` | `None` | n/a/n/a/n/a | `None` |

## Interpretation

- TP1->SL is treated as scratch-neutral; blocking it is not the main guardrail failure.
- Blocking a `TP1_TP2_TRAILING_STOP` is the critical false positive and must be reported explicitly.
- The rule was discovered on accepted PEAK lifecycle evidence. Applying it to ALMOST 2/3 is a domain-transfer test, not validation of the rule for that cohort.
- The earlier single-feed `v5` run used BTCUSDT Futures OHLC as an execution proxy and is superseded for lifecycle and expectancy conclusions by this dual-feed run.
- Targeted `2026-04-23` candidate is absent from this cohort and requires audit.
- This is an independent-opportunity counterfactual. It does not re-sequence the one-position portfolio after removing signals.
- No live admission logic is changed by this report.
