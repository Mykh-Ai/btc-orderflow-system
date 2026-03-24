Task: create final compact DeltaScout research summary for 2026-03-17 through 2026-03-22 using the latest rebuilt artifacts

Input location:
`deltascout/research_material/reviews`

Dates:
- 2026-03-17
- 2026-03-18
- 2026-03-19
- 2026-03-20
- 2026-03-21
- 2026-03-22

Important:
Use only the latest rebuilt artifacts generated after:
1. enriched feed cutover
2. `Close` price-column fix
3. previous-day feed horizon fix for `ret_15m` / `ret_60m`

Do NOT:
- change code
- rebuild anything
- create new datasets beyond a compact summary
- speculate beyond the files

Goal:
Produce one final analyst-facing markdown summary so the batch can be reviewed without reopening all CSV files manually.

Document requirements:

1) Daily snapshot
For each date:
- accepted count
- reject count
- interesting reject count
- close outcome count
- top reject reasons
- dominant interesting_reject buckets

2) Accepted events
List all accepted events across the window with:
- date/time
- kind
- price
- cum_delta_60m
- cum_delta_180m
- ret_15m
- ret_60m
- price_vs_vwap_side
- matched_open_interest
- matched_funding_rate
- matched_liq_buy_qty
- matched_liq_sell_qty
- joined close outcome summary if present

3) Key short-side rejects
Select the most relevant short-side rejects across the window, especially:
- `vwap_side`
- `direction_mismatch`
- `possible_reversal_confirmation`
- `possible_continuation_pressure`

Keep it selective.

4) Focused comparison
Include a compact comparison between:
- accepted short on 2026-03-20 00:40
- short-side candidates on 2026-03-21 09:15
- short-side candidates on 2026-03-21 11:30

Use only evidence from the files:
- structural maturity
- ret_15m / ret_60m
- matched OI/funding/liquidation fields
- no unsupported claims

5) Batch-level conclusion
End with:
- dominant reject patterns in 17–22
- whether enriched fields changed interpretation materially
- whether `vwap_side` appears to block otherwise strong short-side cases
- 2–3 concrete next research questions

Output:
Create one markdown file only.

Preferred filename:
`reviews_2026-03-17_to_2026-03-22_final_compact_summary.md`