# Reviews 2026-04-05 to 2026-04-05 Final Research Review

## Compact Batch Summary

### Daily snapshot
- Fact: local intraday review package for `2026-04-05` contains `0` accepted rows, `8` reject rows, `6` interesting rejects, and `1` close-outcome row.
- Fact: standard bundle selection did not automatically include the later `14:34` `PEAK_EMIT`; this case had to be added from synced archive/raw materials.
- Fact: bundle index note is now marked `intraday_peak_emit_14_34_present_in_archive_only`.

### Accepted events
- Fact: no accepted event context rows are present in the synced intraday review package.

### Key rejects and late case
- Fact: early-day selected bundle cases are dominated by `3of3_fail`, `direction_mismatch`, and one `vwap_side` short reject.
- Fact: the latest visible archive-side high-interest case is `2026-04-05 14:34:00`, `PEAK_EMIT`, `short`.
- Fact: its archive fields are `delta=-20.4`, `vol=33.17`, `imb=0.615`, `price=66774.628139`, `vwap=67121`, `price_now=66751.0`, `ema50_now=66929.457155`.

### Batch-level conclusion
- Interpretation: intraday evidence stays short-biased below VWAP, but the late `14:34` emit behaves more like a short impulse with limited staying power than a clean continuation collapse.

## Analytical Memo

### A. Batch verdict
- Fact: the standard bundle captures the early intraday review structure, but not the late `14:34` emit.
- Interpretation: the late case is important enough that the bundle would understate the day if left unchanged.

### B. Strongest evidence clusters
- Fact: `14:31`, `14:33`, and `14:34` form a same-side short cluster in archive/raw micro.
- Fact: raw micro from `14:31` to `14:34` shows repeated sell dominance and falling closes.

### C. Structural paradoxes and tensions
- Fact: the emit itself is bearish on the minute.
- Interpretation: post-emit path is mixed: favorable short follow-through exists by `15m`, but `30m` path is degraded by rebound.

### D. Expanded key case notes

#### 2026-04-05 14:34:00 ? PEAK_EMIT short
- Fact: event type `PEAK_EMIT`, kind `short`.
- Fact: raw minute row at the same timestamp has `BuyQty=6.385620`, `SellQty=26.785230`, `Close=66751`, `High=66813`, `Low=66748`.
- Fact: immediate micro context shows same-side short pressure at `14:31`, `14:32`, `14:33`, `14:34`.
- Interpretation: the minute itself is structurally bearish and below VWAP.
- Interpretation: `15m` forward path favors the short more than the long, but `30m` path no longer preserves clean continuation.
- Unknown: regime metrics such as `cum_delta_24h`, `cum_delta_180m`, `cum_delta_60m`, `ret_15m`, and `ret_60m` are not available for this late case inside the synced review layer.
- Hypothesis: this is a valid short emission minute, but not a strong persistence case.

Blocker status: visible blocker but other hidden blockers possible

Sequence note:
- Fact: cluster-like.
- Fact: same-side rejects appear nearby at `14:31` and `14:33`.
- Fact: no later same-side accepted event is visible in the synced archive window after `14:34`.
- Fact: no later same-side stronger reject is visible after `14:34`.

### D2. Case-comparison discipline
- Fact: compared with the earlier selected bundle rejects, `14:34` is later, more directional, and closer to an actual emit than the selected early rejects.
- Unknown: because the synced review/event-context layer does not carry full late-case context, it cannot yet be judged against an accepted reference class.

### E. Accepted vs rejected reference-class judgment
- Fact: no accepted reference row is present today in the synced review package.
- Unknown: accepted-vs-rejected class comparison is incomplete for this intraday package.

### F. What remains unknown
- Unknown: canonical enriched M2b/M2.5 fields at `14:34` are unavailable because live enriched feed currently stops earlier than the archive/raw tail.
- Unknown: funding/liquidation/OI alignment at `14:34` inside the canonical minute stack.

### G. Next best research direction
- Interpretation: treat `14:34` as a late intraday priority case and refresh the canonical enriched minute layer once the feed catches up.

### H. Missing-evidence escalation
- Fact: late intraday event capture in bundle/review artifacts is lagging behind archive/raw availability.

### I. Minimal additional data request
- Fact: next needed input is the enriched minute feed covering `2026-04-05 14:34:00` so the full M2b/M2.5 row can be materialized canonically.
