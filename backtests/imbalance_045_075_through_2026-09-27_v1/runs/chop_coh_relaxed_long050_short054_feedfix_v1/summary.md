# PEAK replay with live A-or-B filter

This report covers the filtered `PEAK_EMIT_BASELINE` cohort under the resolved replay contract.

## Frozen chronology

- Discovery: signal timestamp before `2026-06-01T00:00:00Z`.
- Validation: signal timestamp on or after `2026-06-01T00:00:00Z`.
- The boundary was fixed before variant outcome aggregation.


## Independent deterministic replay

| Cohort | Candidates | Fills | Plain SL | TP1→SL | Protected | Net PnL | Expectancy/fill | PF | Avg R | Total R | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `PEAK_EMIT_BASELINE` | 50 | 46 | 26 | 6 | 14 | 24.31 | 0.53 | 1.03 | 0.09 | 4.21 | 327.87 |

## Conclusions

- Filtered PEAK full-history expectancy is positive: 0.53 USDC/fill.
- `ALMOST_2OF3_PRICE_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- `ALMOST_2OF3_VOLUME_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- `ALMOST_2OF3_VWAP_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- The union filter is not portable across variants: it blocks protected winners, and its net effect changes by failed-gate cohort and stop policy.
- LONG/SHORT and monthly slices are in `comparison_variant_metrics.csv` and `comparison_variant_monthly.csv`.
- Any subgroup with a small validation denominator remains exploratory and is not a live-readiness claim.
- This is the current filtered PEAK cohort; interpret it as an Executor-parity backtest, not as evidence for promoting a new signal rule.

## Data and execution constraints

- BTCUSDT Futures remains the signal/context contour; BTCUSDC Spot remains the entry/SL/TP/trailing execution contour.
- The recovered feed and its sidecars govern the documented 2026-04-23 to 2026-05-06 gap; synthetic originals are not treated as market evidence.
- One-minute same-bar ambiguity uses the conservative stop-first baseline.
- This is offline research only. No live filter or VPS runtime was changed.
