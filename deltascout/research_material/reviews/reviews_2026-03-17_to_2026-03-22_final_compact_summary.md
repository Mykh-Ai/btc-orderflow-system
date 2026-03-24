# DeltaScout Review Summary: 2026-03-17 to 2026-03-22

Rebuilt with enriched feed (`/opt/aitrader/feed`), `Close` price-column fix, and previous-day feed horizon for `ret_15m`/`ret_60m`.
All context fields (`ret_15m`, `ret_60m`, `matched_open_interest`, `matched_funding_rate`, `matched_liq_buy_qty`, `matched_liq_sell_qty`) are now populated.

---

## 1. Daily Snapshot

| Date | Accepted | Rejects | Interesting | Close outcomes | Top reject reasons |
|------|----------|---------|-------------|----------------|-------------------|
| 03-17 | 0 | 16 | 16 | 0 | direction_mismatch(7), vwap_side(7), 3of3_fail(2) |
| 03-18 | 0 | 16 | 13 | 0 | direction_mismatch(9), vwap_side(4), 3of3_fail(1), imb_band(1), no_prev_peak(1) |
| 03-19 | 0 | 20 | 16 | 0 | direction_mismatch(14), vwap_distance(4), vwap_side(1), 3of3_fail(1) |
| 03-20 | 1 | 13 | 11 | 1 | direction_mismatch(8), 3of3_fail(2), imb_band(1), no_prev_peak(1), vwap_side(1) |
| 03-21 | 0 | 20 | 16 | 0 | direction_mismatch(13), vwap_side(4), chop_coh(1), 3of3_fail(1), imb_band(1) |
| 03-22 | 0 | 15 | 9 | 0 | direction_mismatch(4), vwap_side(4), chop_coh(3), vwap_distance(2), 3of3_fail(1), imb_band(1) |
| **Total** | **1** | **100** | **81** | **1** | |

Batch reject totals: direction_mismatch(55), vwap_side(21), 3of3_fail(8), vwap_distance(6), imb_band(5), chop_coh(4), no_prev_peak(2).

Interesting reject bucket distribution across 81 rows:

| Bucket | Count | Rule IDs |
|--------|-------|----------|
| unclear_but_constructive | 51 | IR_F1 |
| possible_reversal_onset | 11 | IR_A1, IR_A2 |
| possible_reversal_confirmation | 4 | IR_B1 |
| possible_trap_or_false_break | 5 | IR_E1, IR_E2 |
| possible_continuation_pressure | 4 | IR_C1, IR_C2 |
| possible_exhaustion_probe | 1 | IR_D1 |

---

## 2. Accepted Events

Only one accepted event in the entire 6-day window.

### 2026-03-20 00:40 UTC — PEAK_EMIT SHORT

| Field | Value |
|-------|-------|
| kind | short |
| price | 69,822.44 |
| vwap | 70,092.00 |
| poc | 69,270.00 |
| imb | 0.591 |
| delta | -26.7 |
| vol | 45.19 |
| cum_delta_60m | +526.42 |
| cum_delta_180m | -243.93 |
| cum_delta_24h | -8,341.59 |
| ret_15m | +240.60 |
| ret_60m | +509.60 |
| dist_vwap | -269.56 (below) |
| matched_open_interest | 86,751.63 |
| matched_funding_rate | 1.094e-05 |
| matched_liq_buy_qty | 1.13 |
| matched_liq_sell_qty | 0.0 |

**Close outcome:**

| Field | Value |
|-------|-------|
| join_status | window_match (confidence 0.6) |
| close_reason | SL |
| entry | 69,828.18 |
| side | SHORT |
| close_ts | 2026-03-20 03:30 UTC |
| duration | ~2h50m |

Context: short entry at price below VWAP in a session with negative 24h cumulative delta (-8,341). The positive ret_15m (+240.6) and ret_60m (+509.6) indicate that price had been rising in the 15–60 minutes before entry — the short was entered into a short-term upward move. Closed via SL.

---

## 3. Key Short-Side Rejects

### 3a. vwap_side rejects — short candidates blocked for being above VWAP

**2026-03-21 09:15** — vwap_side, short (interesting: `possible_reversal_onset`, IR_A2)

| Field | Value |
|-------|-------|
| price | 70,692.50 |
| vwap | 70,350.00 |
| dist_vwap | +342.50 (above) |
| delta | -95.27 |
| vol | 110.86 |
| imb | 0.859 |
| cum_delta_60m | -736.90 |
| cum_delta_180m | -909.20 |
| ret_15m | +128.40 |
| ret_60m | +30.90 |
| matched_open_interest | 87,479.15 |
| matched_funding_rate | 4.48e-06 |

Strong negative cumulative delta on both 60m and 180m horizons. Meaningful negative delta (-95.27) with high volume. Rejected solely because price was 342.50 above VWAP.

**2026-03-21 11:30** — vwap_side, short (interesting: `possible_reversal_onset`, IR_A2)

| Field | Value |
|-------|-------|
| price | 70,574.14 |
| vwap | 70,293.00 |
| dist_vwap | +281.14 (above) |
| delta | -169.51 |
| vol | 190.01 |
| imb | 0.892 |
| cum_delta_60m | -121.47 |
| cum_delta_180m | -134.38 |
| ret_15m | +45.00 |
| ret_60m | +32.10 |
| matched_open_interest | 87,388.18 |
| matched_funding_rate | 1.78e-05 |
| matched_liq_buy_qty | 0.002 |
| matched_liq_sell_qty | 0.008 |

Largest delta magnitude in the 03-21 session (-169.51). Highest volume (190.01). Rejected for being 281 above VWAP — narrower margin than the 09:15 candidate.

**2026-03-17 04:23** — vwap_side, short (interesting: `possible_continuation_pressure`, IR_C1)

| Field | Value |
|-------|-------|
| price | 74,815.11 |
| vwap | 74,106.00 |
| dist_vwap | +709.11 (above) |
| cum_delta_60m | -756.08 |
| cum_delta_180m | -1,759.06 |
| ret_15m | -263.80 |
| ret_60m | -480.80 |
| matched_open_interest | 88,763.58 |
| matched_funding_rate | 2.445e-05 |

Strongly negative cumulative delta with negative returns confirming a downward move already in progress. Blocked at 709 above VWAP — wider margin, but the flow context was highly supportive for short.

### 3b. direction_mismatch — short candidates with contrary cum_delta

**2026-03-21 09:40** — direction_mismatch, short (interesting: `possible_reversal_onset`, IR_A1)

| Field | Value |
|-------|-------|
| delta | -150.81 |
| vol | 161.90 |
| imb | 0.932 |
| cum_delta_60m | -279.34 |
| cum_delta_180m | -1,048.17 |
| ret_15m | +41.70 |
| ret_60m | +74.10 |
| dist_vwap | +254.22 (above) |

Third short-side candidate in the 09:10–09:40 cluster on 03-21. Rejected as direction_mismatch despite strongly negative 180m cumulative delta.

### 3c. possible_reversal_confirmation — short-side 3of3_fail

**2026-03-17 05:45** — 3of3_fail, short (interesting: `possible_reversal_confirmation`, IR_B1)

| Field | Value |
|-------|-------|
| delta | -119.33 |
| vol | 149.48 |
| imb | 0.798 |
| cum_delta_60m | -812.46 |
| cum_delta_180m | -1,726.81 |
| ret_15m | -470.80 |
| ret_60m | -125.40 |
| dist_vwap | -87.61 (below) |

This candidate was actually below VWAP. Failed 3of3 comparison, but had the strongest combination of supportive returns (price already falling on both horizons) and negative cumulative delta in the 03-17 session.

---

## 4. Focused Comparison

### Accepted short 2026-03-20 00:40 vs. rejected shorts 2026-03-21 09:15 and 2026-03-21 11:30

| Metric | 03-20 00:40 (accepted, SL) | 03-21 09:15 (vwap_side) | 03-21 11:30 (vwap_side) |
|--------|---------------------------|-------------------------|-------------------------|
| delta | -26.7 | -95.27 | -169.51 |
| vol | 45.19 | 110.86 | 190.01 |
| imb | 0.591 | 0.859 | 0.892 |
| cum_delta_60m | +526.42 | -736.90 | -121.47 |
| cum_delta_180m | -243.93 | -909.20 | -134.38 |
| ret_15m | +240.60 | +128.40 | +45.00 |
| ret_60m | +509.60 | +30.90 | +32.10 |
| dist_vwap | -269.56 (below) | +342.50 (above) | +281.14 (above) |
| OI | 86,751.63 | 87,479.15 | 87,388.18 |
| funding_rate | 1.094e-05 | 4.48e-06 | 1.78e-05 |
| liq_buy | 1.13 | 0.0 | 0.002 |
| liq_sell | 0.0 | 0.0 | 0.008 |
| outcome | SL after 2h50m | rejected | rejected |

Observations from the data:

1. **Structural maturity**: The accepted short had cum_delta_60m of +526 (positive — flow was against the short direction on a 60m horizon). The 03-21 rejects had cum_delta_60m of -737 and -121 respectively — both directionally supportive for short. The 180m picture was similar: the accepted entry had a weaker directional basis (-244) than either reject (-909, -134).

2. **ret_15m / ret_60m**: The accepted entry occurred after a +240/+509 price rise, meaning it entered against recent price momentum. The 03-21 09:15 reject had more modest opposing momentum (+128/+31), and the 11:30 reject had the least (+45/+32). By return context, both rejects had lower counter-trend exposure than the accepted entry.

3. **Enriched fields**: OI was similar across all three (~86.7k–87.5k). Funding rates were in the same order of magnitude (1e-05 to 5e-06). Liquidation quantities were near-zero for all three. In this sample, the enriched fields do not materially differentiate accepted from rejected.

4. **The blocking factor**: The 03-21 rejects were 281–343 above VWAP. The accepted entry was 270 below VWAP. The `vwap_side` gate is the sole reason these candidates did not reach PEAK. Their flow context was arguably stronger for short than the accepted entry that was eventually stopped out.

---

## 5. Batch-Level Conclusion

### Dominant reject patterns (03-17 to 03-22)

- **direction_mismatch** is the dominant filter at 55% of all rejects (55/100). It fires whenever cumulative delta polarity does not align with the candidate direction at the comparison stage.
- **vwap_side** is the second-largest at 21% (21/100). It blocks candidates that are on the "wrong" side of VWAP relative to their direction.
- Together, these two reasons account for 76% of all rejects. The remaining 24% are split among 3of3_fail, vwap_distance, imb_band, chop_coh, and no_prev_peak.

### Did enriched fields change interpretation?

In this 6-day sample, `matched_open_interest`, `matched_funding_rate`, `matched_liq_buy_qty`, and `matched_liq_sell_qty` are now populated but **do not yet differentiate accepted from rejected events**. OI stayed in a narrow band (85.9k–93.5k). Funding rates were small and mostly positive. Liquidation quantities were near-zero in almost every row.

This does not mean enriched fields are uninformative — it means the current sample has one accepted event and the market regime during this window was calm in terms of liquidations and funding extremes. These fields become relevant when comparing across regimes with higher volatility.

### Does vwap_side appear to block otherwise strong short-side cases?

Yes. The 03-21 cluster (09:15, 11:30) and the 03-17 04:23 reject are the clearest examples. All three had:
- strong negative delta
- high volume
- directionally supportive cumulative delta (60m and/or 180m)
- moderate or small dist_vwap (281–709 above)

They were blocked solely by `vwap_side`. The one accepted short (03-20 00:40) had weaker directional support on the 60m/180m horizon but passed because it was below VWAP.

### Next research questions

1. **vwap_side threshold sensitivity**: How many of the 21 vwap_side rejects had `abs_dist_vwap < 500`? Would a relaxed threshold (or a conditional override when 180m cum_delta strongly supports the direction) have allowed structurally mature shorts while still filtering noise?

2. **direction_mismatch recoverability**: Among the 55 direction_mismatch rejects, how many had `interesting_reject_bucket` of `possible_reversal_onset` or `possible_reversal_confirmation`? These are cases where the comparison-stage mismatch may mask an emerging reversal that the current 3/3 rule cannot distinguish from noise.

3. **Enriched-field differentiation under stress**: The current window is low-liquidation and stable-funding. Do enriched fields show discriminative power in historical windows with higher `liq_buy_qty`/`liq_sell_qty` or funding rate extremes? This requires extending the analysis to earlier dates (if available) or waiting for a higher-volatility window.
