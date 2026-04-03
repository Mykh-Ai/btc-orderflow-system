# Focused Accepted SL Postmortem

## 1. Purpose

- Fact: this memo studies only accepted `PEAK_EMIT` cases that later closed by `SL`.
- Fact: it does not summarize the full batch and it does not treat current PEAK as the whole research program.
- Fact: the goal is to test whether accepted SL cases are failing for the same structural reason or for different reasons.

## 2. Accepted SL universe

- Fact: the currently available local materials show two accepted `PEAK_EMIT` cases with `close_reason=SL`.

| Timestamp UTC | Kind | Entry | Close reason | Close ts | Duration (min) | price_vs_vwap_side | cum_delta_60m | cum_delta_180m | ret_15m | ret_60m | Raw micro available | Same-session nearby rejects available |
| --- | --- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- |
| 2026-03-20 00:40:00 | short | 69828.18 | SL | 2026-03-20 03:30:18+00:00 | 230 | below | 526.417 | -243.928 | 240.6 | 509.6 | yes | yes |
| 2026-03-29 19:23:00 | short | 66187.66 | SL | 2026-03-29 20:24:54+00:00 | 61 | below | 68.985 | -802.882 | 8.6 | 52.8 | yes | yes |

## 3. Direct accepted-vs-accepted comparison

- Fact: both accepted SL cases are short and `price_vs_vwap_side=below` at acceptance.
- Fact: both therefore passed the current funnel in structurally aligned short-side placement, yet both still closed by `SL`.

- Fact: the two accepted SL cases do not have the same medium-horizon profile.
- Fact: `2026-03-20 00:40:00` has stronger visible near-to-medium support on the current fields:
  - `cum_delta_60m=526.417` vs `68.985`
  - `ret_15m=240.6` vs `8.6`
  - `ret_60m=509.6` vs `52.8`
- Fact: `2026-03-29 19:23:00` has the more negative `cum_delta_180m`:
  - `-802.882` vs `-243.928`
- Interpretation: one accepted SL case looks like a stronger immediate momentum/continuation acceptance, while the other looks narrower and more modest at entry.

- Fact: post-entry raw micro behavior also differs.
- Fact: `2026-03-20 00:40:00` moves against the short very quickly on the visible raw-micro window:
  - event close `70205.80`
  - `+5m` close `70188.40`
  - `+30m` close `70361.10`
- Fact: `2026-03-29 19:23:00` initially moves in favor of the short on the visible raw-micro window:
  - event close `66422.20`
  - `+5m` close `66392.80`
  - `+15m` close `66355.00`
  - `+30m` close `66323.50`
- Interpretation: the first accepted SL case reads more like immediate invalidation / continuation against entry, while the second reads more like a trade that initially worked and then later failed.

- Fact: duration to stop also differs materially:
  - `2026-03-20 00:40:00` stopped after about `230` minutes
  - `2026-03-29 19:23:00` stopped after about `61` minutes
- Interpretation: the accepted SL cases do not look like the same temporal failure shape.

## 4. Same-session context comparison

### 2026-03-20 00:40:00

- Fact: nearby same-session rows are visible in the sequence context.
- Fact: the only nearby same-side reject in the current local sequence window is `2026-03-20 02:00:00` short `direction_mismatch`.
- Fact: the accepted case is stronger than that reject on several visible metrics:
  - `cum_delta_60m=526.417` vs `354.598`
  - `ret_15m=240.6` vs `-169.5`
  - `ret_60m=509.6` vs `211.0`
  - accepted case is `below` VWAP-side while the reject is `above`
- Interpretation: the accepted case was not obviously weaker than the nearby same-side reject.
- Interpretation: however, its later `SL` means that passing the funnel here did not protect against a fast adverse path after entry.

### 2026-03-29 19:23:00

- Fact: there is a nearby same-side reject one minute earlier: `2026-03-29 19:22:00` short `direction_mismatch`.
- Fact: the accepted and rejected cases look very close on visible metrics:
  - `cum_delta_60m`: `68.985` vs `71.807`
  - `cum_delta_180m`: `-802.882` vs `-777.112`
  - `ret_15m`: `8.6` vs `-13.5`
  - `ret_60m`: `52.8` vs `-18.2`
  - both are `below` VWAP-side
- Interpretation: this accepted case does not read as clearly stronger than the nearby reject.
- Interpretation: it looks more like a narrow survival through the funnel than a decisively superior structure.

## 5. Failure-mode reading

### 2026-03-20 00:40:00

- Fact: immediate post-entry raw micro does not support a clean short continuation path.
- Fact: the visible micro path rises by `+30m` instead of extending down.
- Interpretation: this case most likely fits **continuation against entry**.
- Interpretation: **immediate invalidation** is also plausible from the visible early path.
- Unknown: the current files do not show the full micro path from `+30m` to stop, so the precise transition into `SL` remains only partially visible.

### 2026-03-29 19:23:00

- Fact: immediate post-entry raw micro initially supports the short.
- Fact: the trade still closed by `SL` about `61` minutes later.
- Interpretation: this case most likely fits **late entry** or **unresolved / ambiguous** failure rather than immediate invalidation.
- Unknown: the current local micro slice does not extend far enough to show the exact reversal path into the stop.

## 6. Hard verdict

- Fact: the accepted SL cases do **not** appear to fail for the same immediate reason.
- Interpretation: `2026-03-20 00:40:00` looks like an accepted case that was structurally allowed but then moved against the short quickly enough to invalidate the entry.
- Interpretation: `2026-03-29 19:23:00` looks like an accepted case that initially behaved correctly, then later failed after a narrower survival through the funnel.
- Interpretation: the strongest common weakness is **not one identical post-entry path**.
- Interpretation: the stronger common weakness is that accepted flow can pass the funnel without being clearly stronger than nearby same-session reject alternatives.
- Fact: both accepted SL cases are short, below VWAP-side, and accepted under a funnel that nearby rejects only narrowly fail or miss.
- Interpretation: accepted PEAK flow here looks more like a **narrow survival path through the funnel** than a robust protection against later failure.
- Unknown: the current files still do not reveal the full hidden acceptance-vs-rejection discriminator or the exact stop path beyond the visible raw-micro window.

## 7. Minimal next request

- Fact: artifact 1 wanted: raw-feed micro extension from event time until close for the two accepted SL cases.
- Fact: why it matters: it would show whether the losing path was immediate, delayed, or reversal-like in exact sequence form.

- Fact: artifact 2 wanted: same-session selected-case sequence windows widened beyond the current narrow accepted context for `2026-03-20 00:40:00` and `2026-03-29 19:23:00`.
- Fact: why it matters: it would show whether there were later same-side rejects or alternative structures that make the accepted cases look merely narrow rather than strong.

- Fact: artifact 3 wanted: accepted-case-specific gate diagnostics for the accepted PEAK rows themselves, if such source fields are locally available anywhere.
- Fact: why it matters: current blocker diagnostics clarify rejected `3of3_fail` rows, but they do not yet explain why these accepted rows passed when nearby rejects failed.