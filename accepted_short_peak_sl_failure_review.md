# EXECUTIVE VERDICT
Fact: The local evidence contains 2 accepted short `PEAK_EMIT` cases with visible close outcome `SL`: `2026-03-20 00:40:00` and `2026-03-29 19:23:00`.
Interpretation: The package supports a mixed failure picture, not a single-mode failure. One case looks consistent with a late short into an already extended downside context, while the other looks more like a structurally weak short that failed to convert into downside follow-through.
Hypothesis: The current accepted-short `PEAK_EMIT` failures appear to reflect both timing failure and setup-family weakness.
Unknown: With only 2 local accepted short `PEAK_EMIT` + `SL` cases, confidence is limited.

# CASE INVENTORY
Fact:
- `2026-03-20 00:40:00` | entry `69828.18` | close `SL` | cum_delta_24h `-8341.59299999997` | cum_delta_180m `-243.92799999999534` | cum_delta_60m `526.4170000000013` | ret_15m `240.60000000000582` | ret_60m `509.6000000000058`
- `2026-03-29 19:23:00` | entry `66187.66` | close `SL` | cum_delta_24h `-2424.075999999996` | cum_delta_180m `-802.8819999999996` | cum_delta_60m `68.98500000000004` | ret_15m `8.599999999991269` | ret_60m `52.80000000000291`
Interpretation: The sample is narrow but internally diverse. `2026-03-20 00:40:00` arrived after a much larger recent move context than `2026-03-29 19:23:00`.
Hypothesis: The two losses should not be treated as one homogeneous short-failure bucket.
Unknown: The selected-case bundles show nearby context but do not by themselves expose hidden gate decisions.

# COMMON TIMING FEATURES
Fact: `2026-03-20 00:40:00` had `same_side_event_count_prev_5m = 0` and `same_side_event_count_prev_15m = 0`.
Fact: `2026-03-29 19:23:00` had `same_side_event_count_prev_5m = 2`, `same_side_event_count_prev_15m = 2`, and `minutes_since_prev_same_side_event = 1`.
Fact: The local sequence file shows no same-side short event before `2026-03-20 00:40:00` inside the visible +/-90 minute window, while `2026-03-29 19:23:00` had a same-side `DELTA_MIN` and same-side reject at `19:22:00`.
Fact: `2026-03-20 00:40:00` had `pre_emit_price_move_5m = 92.60000000000582`, `pre_emit_price_move_15m = 188.40000000000873`, and `pre_emit_delta_sum_15m = 279.492`.
Fact: `2026-03-29 19:23:00` had `pre_emit_price_move_5m = -3.3999999999941792`, `pre_emit_price_move_15m = -11.0`, and `pre_emit_delta_sum_15m = -18.637`.
Interpretation: There is no shared late-burst timing signature across both losses. Only `2026-03-29 19:23:00` shows dense same-side activity immediately before emit, while `2026-03-20 00:40:00` looks more like a short fired after a large recent move but without nearby same-side event clustering.
Hypothesis: Timing failure is present, but it is not expressed through one repeatable pre-emit event-count pattern in this 2-case sample.
Unknown: The local files do not prove whether the `19:22 -> 19:23` short reject-to-emit transition is a repeatable accepted-short weakness or just a single-case pattern.

# COMMON STRUCTURAL FEATURES
Fact: In `accepted_event_context`, both cases were short, `PEAK_EMIT`, and `price_vs_vwap_side = below` with large negative `dist_vwap` values.
Fact: In the same-minute mechanics rows, both cases showed `delta_sign = positive`, `price_move_sign = up`, and `delta_price_alignment_1m = aligned`.
Fact: `2026-03-20 00:40:00` carried mixed broader context: `cum_delta_24h = -8341.59299999997`, `cum_delta_180m = -243.92799999999534`, `cum_delta_60m = 526.4170000000013`, `ret_15m = 240.60000000000582`, `ret_60m = 509.6000000000058`.
Fact: `2026-03-29 19:23:00` carried much flatter recent return context: `cum_delta_24h = -2424.075999999996`, `cum_delta_180m = -802.8819999999996`, `cum_delta_60m = 68.98500000000004`, `ret_15m = 8.599999999991269`, `ret_60m = 52.80000000000291`.
Interpretation: The common structural overlap is weak. Both emits fired from below-VWAP event context, but the minute-close mechanics at the same timestamps were locally up/positive, which points to short-side fragility at entry rather than a clean downside continuation state.
Hypothesis: The structural problem may be that some accepted short `PEAK_EMIT` cases pass on broader below-VWAP context even when the immediate minute is already rotating against the short.
Unknown: The local materials do not justify inventing a new family label for that structure.

# COMMON PARTICIPATION FEATURES
Fact: `2026-03-20 00:40:00` had `oi_change_1m = -5.279999999998836`, `delta_oi_alignment_flag = opposed`, `price_oi_alignment_flag = opposed`, `liq_total_1m = 1.13`, `liq_dominant_side = buy`.
Fact: `2026-03-29 19:23:00` had `oi_change_1m = 14.789999999993597`, `delta_oi_alignment_flag = aligned`, `price_oi_alignment_flag = aligned`, `liq_total_1m = 0.0`, `liq_dominant_side = balanced_or_unknown`.
Interpretation: There is no common OI/price participation signature across both losses. One case had opposition plus buy-side liquidation activity; the other had aligned OI expansion but no liquidation support.
Hypothesis: Participation looks case-specific rather than the primary shared failure axis.
Unknown: With 2 cases, it is not possible to rank OI opposition versus liquidation absence as the dominant accepted-short failure driver.

# FORWARD OUTCOME SHAPE
Fact: `2026-03-20 00:40:00` showed `ret_fwd_5m = -17.40000000000873`, `ret_fwd_15m = -50.5`, then reversed to `ret_fwd_30m = 155.3000000000029` and `ret_fwd_60m = 322.3000000000029`.
Fact: `2026-03-29 19:23:00` showed `ret_fwd_5m = -29.39999999999418`, `ret_fwd_15m = -67.19999999999709`, `ret_fwd_30m = -98.69999999999709`, then reversed to `ret_fwd_60m = 186.40000000000873`.
Fact: In both cases, 5m favorable/adverse asymmetry was poor for the short-side thesis because adverse excursion exceeded favorable excursion by the required horizon framing: `43.5 > 32.69999999999709` on 2026-03-20 and `53.30000000000291 > 25.80000000000291` on 2026-03-29.
Interpretation: Both losses lacked durable immediate follow-through. One failed fast and trended against the short almost immediately; the other offered some early downside but still lacked lasting 60m downside conversion.
Hypothesis: Weak near-term favorable/adverse asymmetry is a stronger shared sign than any shared regime bucket.
Unknown: The outcome files use their own reference-direction framing, so these forward fields should be interpreted as local path shape evidence, not as hidden trade PnL logic.

# TIMING FAILURE VS SETUP-FAMILY FAILURE
Fact: `2026-03-20 00:40:00` combines a large prior move context with positive recent returns and a same-minute up/positive mechanics profile.
Interpretation: This case fits a timing-failure reading better than a pure structural-family reading. The short appears late against a market that had already traveled materially and was locally pushing up at the emit minute.
Fact: `2026-03-29 19:23:00` does not show the same large pre-emit downside extension. Its recent returns were comparatively small, but the emit still arrived on a locally up/positive minute with no liquidation support.
Interpretation: This case fits a structurally weak setup reading better than a pure late-burst reading.
Hypothesis: The best answer from the local evidence is `a mixture of both`.
Unknown: A larger accepted-short loss sample is needed before claiming one category dominates.

# MOST LIKELY FAILURE MODES
Fact: Both cases lacked strong immediate favorable/adverse asymmetry after emit.
Interpretation: The first likely failure mode is a fragile accepted short that does not convert into durable downside follow-through even when the broader event context looks acceptable.
Fact: Only the 2026-03-20 case shows a strong late/extended pre-emit context.
Interpretation: The second likely failure mode is a late continuation short after too much prior move has already occurred.
Fact: The 2026-03-29 case had a same-side reject one minute before acceptance, zero liquidation support, and only mild broader-return context.
Interpretation: The third likely failure mode is a structurally weak short class that still passes because broader below-VWAP context looks acceptable while local conversion is weak.
Hypothesis: The losses are more consistent with two neighboring failure modes than with one universal defect.
Unknown: The files do not support a finer family taxonomy than that.

# WHAT THIS IMPLIES FOR CURRENT DELTASCOUT
Fact: The accepted short `PEAK_EMIT` loss sample does not support a single clean common regime signature.
Interpretation: The current accepted-short logic may be vulnerable at two edges: late continuation timing and short structures that are locally rotating up at emit despite acceptable broader context.
Hypothesis: The accepted-short failure surface is probably narrower than the full short-side space and should be studied as accepted-losses specifically, not merged with all shorts or all rejects.
Unknown: This package alone does not justify any code or filter change.

# MINIMAL NEXT RESEARCH STEP
Fact: The current package isolates all visible local accepted short `PEAK_EMIT` + `SL` cases and preserves their comparison fields and nearby event chains.
Interpretation: The minimal next step is to extend the same package format to the next locally available accepted short `PEAK_EMIT` losses as more review days accumulate, keeping the exact same matrix fields so the timing-vs-structure split can be tested on a larger sample.
Hypothesis: The timing-versus-setup-family question becomes answerable only after the accepted-short loss inventory grows beyond 2 cases.
Unknown: No stronger next step can be supported from the current local evidence without broadening scope.
