# PEAK replay with live A-or-B filter

This report covers the filtered `PEAK_EMIT_BASELINE` cohort under the resolved replay contract.

## Frozen chronology

- Discovery: signal timestamp before `2026-06-01T00:00:00Z`.
- Validation: signal timestamp on or after `2026-06-01T00:00:00Z`.
- The boundary was fixed before variant outcome aggregation.


## Applied pre-replay loss filter

- Policy: `UNION_A_OR_B`.
- Candidates before / blocked / kept: 113 / 40 / 73.
- Unknown values kept fail-open: 10.
- Blocked identities are recorded in `candidate_loss_filter_exclusions.csv`.

## Independent deterministic replay

| Cohort | Candidates | Fills | Plain SL | TP1→SL | Protected | Net PnL | Expectancy/fill | PF | Avg R | Total R | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PEAK_EMIT_BASELINE` | 32 | 28 | 12 | 6 | 10 | 271.93 | 9.71 | 1.70 | 0.34 | 9.61 | 127.01 |

## Conclusions

- Filtered PEAK full-history expectancy is positive: 9.71 USDC/fill.
- `comparison_variant_loss_filter.csv` is a residual reapplication diagnostic on the already filtered candidate set; use the manifest and exclusion ledger for the pre-replay filter effect.
- LONG/SHORT and monthly slices are in `comparison_variant_metrics.csv` and `comparison_variant_monthly.csv`.
- Any subgroup with a small validation denominator remains exploratory and is not a live-readiness claim.
- This is the current filtered PEAK cohort; interpret it as an Executor-parity backtest, not as evidence for promoting a new signal rule.

## Data and execution constraints

- BTCUSDT Futures remains the signal/context contour; BTCUSDC Spot remains the entry/SL/TP/trailing execution contour.
- The recovered feed and its sidecars govern the documented 2026-04-23 to 2026-05-06 gap; synthetic originals are not treated as market evidence.
- One-minute same-bar ambiguity uses the conservative stop-first baseline.
- This is offline research only. No live filter or VPS runtime was changed.
