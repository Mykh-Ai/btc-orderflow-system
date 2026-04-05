# EXECUTIVE SUMMARY
Fact: 4 accepted `PEAK_EMIT` rows were discovered locally.
Fact: same-day matches = 2, D+1-only matches = 2, D+2-only matches = 0, still missing = 0, ambiguous = 0.
Interpretation: The local truth gap is real. Some accepted peaks were outcome-missing in their original daily review only because the close landed on the next UTC day.
Unknown: This package does not prove whether any unresolved case is absent from upstream trade outcomes or only lacks conservative linkage keys.

# DISCOVERED ACCEPTED PEAKS
Fact: `2026-03-20 00:40:00` | `short` | join_quality `same_day_match` | matched_close `yes`.
Fact: `2026-03-29 19:23:00` | `short` | join_quality `same_day_match` | matched_close `yes`.
Fact: `2026-04-03 16:20:00` | `long` | join_quality `next_day_match` | matched_close `yes`.
Fact: `2026-04-04 23:56:00` | `long` | join_quality `next_day_match` | matched_close `yes`.
Interpretation: The local accepted inventory is small and fully enumerable from repository review files.
Unknown: No assumption is made here about accepted peaks outside the locally present review date range.

# SAME-DAY MATCHES
Fact: `2026-03-20 00:40:00` matched same-day close file `2026-03-20` with close `2026-03-20 03:30:18.814608+00:00` and reason `SL`.
Fact: `2026-03-29 19:23:00` matched same-day close file `2026-03-29` with close `2026-03-29 20:24:54.088716+00:00` and reason `SL`.
Interpretation: Same-day linkage works when the close stays on the emit date and `close_outcomes` already carries `peak_ts`/`peak_kind` linkage.
Unknown: This section does not validate builder correctness beyond the locally generated files.

# CROSS-DAY MATCHES
Fact: `2026-04-03 16:20:00` matched via `next_day_match` in close file date `2026-04-04` with close `2026-04-04 20:10:32.172492+00:00` and trade_key `EX_EN_1775226003`.
Fact: `2026-04-04 23:56:00` matched via `next_day_match` in close file date `2026-04-05` with close `2026-04-05 01:00:08.803730+00:00` and trade_key `EX_EN_1775339769`.
Interpretation: These are the accepted peaks that looked outcome-missing on the emit date but were recoverable by checking the next close date window.
Unknown: Cross-day fallback here is conservative and only uses locally visible linkage clues.

# STILL-MISSING CASES
Fact: No accepted peaks remained unresolved after same-day plus cross-day lookup.
Interpretation: Remaining unresolved cases, if any, require stronger keys than the local package exposes.
Unknown: A missing match does not by itself prove that a trade never closed.

# WHAT THE OLD DAILY REVIEW MISSED
Fact: Daily review on `2026-04-03` did not show the outcome for peak `2026-04-03 16:20:00`, but cross-day lookup found a close on `2026-04-04`.
Fact: Daily review on `2026-04-04` did not show the outcome for peak `2026-04-04 23:56:00`, but cross-day lookup found a close on `2026-04-05`.
Interpretation: The old daily review missed cross-day closures because accepted peaks live on emit date while close outcomes live on close date.
Unknown: This memo does not assess whether any other review fields suffer from the same date-boundary issue.

# MINIMAL NEXT STEP
Fact: The repaired package now provides one conservative truth row per accepted peak plus an explicit unresolved list.
Interpretation: This package is sufficient to use accepted peaks as a research truth layer without relying only on same-day accepted review tables.
Unknown: No broader dataset rebuild was performed here.
