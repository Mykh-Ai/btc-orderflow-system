# Window definition

Analyze from `2026-03-26 04:45:00` through `2026-03-27 10:39:00`.

# Candidate inventory

Source artifacts:
- `deltascout/research_material/reviews/2026-03-26/events_context_2026-03-26.csv`
- `deltascout/research_material/reviews/2026-03-26/interesting_rejects_2026-03-26.csv`
- `deltascout/research_material/reviews/2026-03-27/events_context_2026-03-27.csv`
- `deltascout/research_material/reviews/2026-03-27/interesting_rejects_2026-03-27.csv`

| timestamp | event_type | kind | reject_reason / status | interesting_reject_bucket | rule_id | price_vs_vwap_side | cum_delta_24h | cum_delta_180m | cum_delta_60m | ret_15m | ret_60m |
|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|
| 2026-03-26 04:45:00 | CANDIDATE_COMPARISON_REJECT | short | 3of3_fail | possible_reversal_confirmation | IR_B1 | below | 3083.311999999999 | -633.0500000000006 | -226.81700000000092 | -28.69999999999709 | -18.09999999999127 |
| 2026-03-26 06:10:00 | CANDIDATE_GATE_REJECT | short | imb_band |  |  | at_or_unknown | 771.3469999999994 | -2429.1050000000014 | -1751.0229999999995 | -15.0 | -457.29999999998836 |
| 2026-03-26 06:56:00 | CANDIDATE_COMPARISON_REJECT | short | vwap_distance |  |  | below | 1236.9689999999994 | -2048.7120000000004 | 139.75999999999976 | 115.09999999999127 | 138.3000000000029 |
| 2026-03-26 16:10:00 | CANDIDATE_COMPARISON_REJECT | short | direction_mismatch | unclear_but_constructive | IR_F1 | below | -3403.423000000004 | -651.9219999999991 | -1990.2449999999997 | -190.3000000000029 | -169.5 |
| 2026-03-26 18:50:00 | CANDIDATE_COMPARISON_REJECT | short | direction_mismatch | unclear_but_constructive | IR_F1 | below | -6450.632000000001 | -1220.738 | -1310.7189999999998 | 153.09999999999127 | -296.6000000000058 |
| 2026-03-26 21:55:00 | CANDIDATE_COMPARISON_REJECT | short | direction_mismatch | unclear_but_constructive | IR_F1 | below | -6402.093 | 419.25199999999995 | -492.5150000000003 | -61.5 | -56.40000000000873 |
| 2026-03-27 03:25:00 | CANDIDATE_COMPARISON_REJECT | short | direction_mismatch | unclear_but_constructive | IR_F1 | below | -6418.842999999992 | 219.81399999999303 | -93.98299999999836 | 28.0 | -251.60000000000582 |
| 2026-03-27 03:35:00 | CANDIDATE_COMPARISON_REJECT | short | 3of3_fail | possible_continuation_pressure | IR_C2 | below | -6453.775999999993 | 279.1719999999923 | -124.84099999999944 | 38.70000000001164 | -170.09999999999127 |
| 2026-03-27 06:40:00 | CANDIDATE_GATE_REJECT | short | imb_band |  |  | at_or_unknown | -4518.685000000003 | -323.3830000000089 | -51.200000000004366 | -61.0 | 159.20000000001164 |
| 2026-03-27 09:36:00 | CANDIDATE_COMPARISON_REJECT | short | direction_mismatch | unclear_but_constructive | IR_F1 | below | -6190.338000000008 | -2761.0360000000064 | -2131.3300000000017 | -110.29999999998836 | -187.79999999998836 |

# Regime flip check

Fact: within the short candidate inventory, `cum_delta_24h` is still positive at `2026-03-26 06:56:00` (`1236.9689999999994`) and is already negative by `2026-03-26 16:10:00` (`-3403.423000000004`).

Interpretation: the visible regime flip for short candidates occurs between `2026-03-26 06:56:00` and `2026-03-26 16:10:00`.

Candidate placement relative to the flip:
- Before regime flip: `2026-03-26 04:45:00`, `2026-03-26 06:10:00`, `2026-03-26 06:56:00`
- During transition: exact flip minute is not visible from candidate rows; transition interval is `2026-03-26 06:56:00` to `2026-03-26 16:10:00`
- After regime flip: `2026-03-26 16:10:00`, `2026-03-26 18:50:00`, `2026-03-26 21:55:00`, `2026-03-27 03:25:00`, `2026-03-27 03:35:00`, `2026-03-27 06:40:00`, `2026-03-27 09:36:00`

Additional anchor:
- Manual raw-feed checksum at `2026-03-27 08:00:00` gives `cum_delta_24h = -4578.63800000002`
- Manual raw-feed checksum at `2026-03-27 10:39:00` gives `cum_delta_24h = -10050.612`

# Stronger-candidate check

Fact: the early anchor case `2026-03-26 04:45:00` has positive `cum_delta_24h` (`3083.311999999999`) but negative `cum_delta_180m`, negative `cum_delta_60m`, and negative `ret_15m` / `ret_60m`. This is the earlier B1-like aligned short failure inside a still-positive 24h regime.

Fact: several later short candidates occur after the regime flip with all of the following already in place:
- `price_vs_vwap_side = below`
- strongly negative `cum_delta_24h`
- strongly negative `cum_delta_60m`
- often strongly negative `cum_delta_180m`
- often negative `ret_15m` and `ret_60m`

Interpretation: these later candidates are structurally different from the earlier B1-like lane because the broader 24h regime is no longer fighting the short. They read less like post-alignment failures inside a positive reservoir and more like bearish continuation or late continuation inside an already negative regime.

Key post-flip checks:
- `2026-03-26 16:10:00`
  - strongest clean alignment among post-flip rows visible from current files: negative `cum_delta_24h`, negative `cum_delta_180m`, negative `cum_delta_60m`, negative `ret_15m`, negative `ret_60m`, `below` VWAP
  - Interpretation: strongest clean continuation-style short candidate in the window
- `2026-03-26 18:50:00`
  - mixed timing: very negative 24h / 180m / 60m, but `ret_15m` turns positive
  - Interpretation: late or noisy continuation rather than clean entry timing
- `2026-03-27 03:35:00`
  - interesting because it is the only post-flip `3of3_fail` row with `possible_continuation_pressure` / `IR_C2`
  - but `cum_delta_180m` is positive and `ret_15m` is positive
  - Interpretation: continuation-like, but less clean than `2026-03-26 16:10:00`
- `2026-03-27 09:36:00`
  - most extreme bearish local structure: `cum_delta_24h = -6190.338000000008`, `cum_delta_180m = -2761.0360000000064`, `cum_delta_60m = -2131.3300000000017`, `ret_15m = -110.29999999998836`, `ret_60m = -187.79999999998836`
  - Interpretation: strongest terminal bearish candidate in the inventory, but likely later in the downside move rather than cleaner earlier continuation

# Hard verdict

Fact: yes, the window contains meaningful short candidates after `2026-03-26 04:45:00` and before `2026-03-27 10:39:00`.

Interpretation: after the regime flip, the short candidates no longer read like the earlier B1-like setup inside a positive 24h backdrop. They look more like a different post-regime-flip continuation class: broader bearish regime already aligned, with some rows appearing cleaner continuation entries and others appearing late/terminal continuation.

Interpretation: the strongest candidate in the window is `2026-03-26 16:10:00` if the question is clean post-flip continuation alignment, while `2026-03-27 09:36:00` is the strongest if the question is raw bearish intensity. Those are not the same thing.
