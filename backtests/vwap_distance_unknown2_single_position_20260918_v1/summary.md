# ALMOST PEAK 2/3 failed-gate variants

The candidate identity and original `candidate_group` are preserved. `comparison_setup_variant` is an additive research dimension.

## Frozen chronology

- Discovery: signal timestamp before `2026-06-01T00:00:00Z`.
- Validation: signal timestamp on or after `2026-06-01T00:00:00Z`.
- The boundary was fixed before variant outcome aggregation.

## Classification control

- Current replay price failed: 0.
- Current replay volume failed: 0.
- Current replay VWAP failed: 0.
- Frozen v3 control through `2026-08-18`: `66 price / 74 volume / 107 vwap`; enforced by a separate regression test.
- Invalid/ambiguous comparison rows: 0.

## Independent deterministic replay

| Cohort | Candidates | Fills | Plain SL | TP1→SL | Protected | Net PnL | Expectancy/fill | PF | Avg R | Total R | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|

## Conclusions

- Positive full-history expectancy: none.
- `ALMOST_2OF3_PRICE_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- `ALMOST_2OF3_VOLUME_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- `ALMOST_2OF3_VWAP_FAIL` union filter: blocks 0 candidates/0 fills, including 0 protected; net 0.00 → 0.00 USDC.
- The union filter is not portable across variants: it blocks protected winners, and its net effect changes by failed-gate cohort and stop policy.
- LONG/SHORT and monthly slices are in `comparison_variant_metrics.csv` and `comparison_variant_monthly.csv`.
- Any subgroup with a small validation denominator remains exploratory and is not a live-readiness claim.
- No failed-gate subgroup has positive full-history expectancy under this run; do not promote a subgroup from this stop-policy replay.

## Data and execution constraints

- BTCUSDT Futures remains the signal/context contour; BTCUSDC Spot remains the entry/SL/TP/trailing execution contour.
- The recovered feed and its sidecars govern the documented 2026-04-23 to 2026-05-06 gap; synthetic originals are not treated as market evidence.
- One-minute same-bar ambiguity uses the conservative stop-first baseline.
- This is offline research only. No live filter or VPS runtime was changed.
