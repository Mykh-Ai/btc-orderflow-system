# Peak_Ai delta-triggered H1 reclaim — corrected both-signs SHORT v2

Research-only, 2026-10-11. Supersedes the incomplete positive-only scope for this user hypothesis. No production hooks, orders, deployment or strategy promotion.
Monitor base: Mykh-Ai/aitrader canonical/market-monitor-39a
064247c4e3081a02ef9fc227e333ae6ca8dc6cec. Replay base:
84fcb9ec257dd2c28b04ff6149b48b52d628fdca. This is a new family, not raw-v2 tuning.

## Frozen hypothesis

Every raw journal DELTA_MAX or DELTA_MIN can arm SHORT, regardless of its numeric sign.
No LONG entries. Both signs share pending-zone, episode and confirmation deduplication
and ONE portfolio; the earliest eligible trigger owns the candidate. Repeated deltas
of either sign do not restart its timer. Numeric zero would be retained separately
in sign analysis, not assigned a positive/negative sign. No PEAK_EMIT, comparison gates or M2 future labels.
Minute price, OHLC, buy/sell quantities and structure all come from the same
normalized legacy Spot feed. Liquidations are not an eligibility filter; they
are unavailable in this archived normalized input and must not be reported as zero.

Native completed-minute labels are availability timestamps. H1 consists of
(hour start, hour end] minute labels, and is available at hour end. Internally,
the Monitor adapter shifts those labels by -1 minute to its OPEN-label geometry.
All 60 minutes must be real and contiguous. Flat traded bars are valid.

1. At a new DELTA_MAX or DELTA_MIN, query pre-existing H1/H4 upper structural references.
2. H1 strict fractal LR=2, H4 LR=1 reuse canonical geometry. A reference is
   available only after the last confirming HTF candle CLOSE; partial/missing
   confirmation bars reject it. No earlier availability at bar open.
3. Use canonical single-reference zone bands, lifecycle and significance scorer.
   Require MAJOR/PRIMARY and no inactive/consumed/chopped/expired status. All
   relevant H1/H4 references are considered, not the visible-seven subset.
4. Price must be strictly above the upper boundary. The latest close-cross from
   <= upper to > upper must be no more than 240 minutes old and after the level
   became known. This operationalizes 'current move' before observing outcomes.
5. Among eligible zones choose nearest upper boundary below price, then highest
   native significance, then stable zone id. Freeze boundaries, score, origin,
   crossing time and trigger time. One pending candidate per zone; repeat deltas
   do not extend its deadline. One attempt per zone/crossing episode.
6. Observe closed H1 at t > delta time and t <= delta time + 4 hours. First close
   strictly below the lower boundary confirms SHORT. Equality/inside-zone/ticks
   below do not confirm. Exact-deadline H1 is eligible. Otherwise EXPIRED.
7. Stop anchor is max minute High from start of the crossing H1 through the
   confirmation, plus 1 basis point. Never inside the sweep, never later highs.
8. Missing/invalid minutes cancel pending candidates; a zone with incomplete
   history since its availability is not eligible. End-of-data pending is
   right-censored (not expiration). Same-minute/side confirmations are deduped
   with lineage preserved before portfolio replay.

## Adapter scope / explicit differences from the complete monitor

This is a bounded research adapter, NOT the complete v39A snapshot or existing
setup_builder. It preserves immutable individual H1/H4 swing references; it does
not merge them into widening/reidentified clusters. M15, sessions, daily levels,
pattern zones, hidden flow, event bonuses and post-sweep observation bonuses are
outside this first family. Native lifecycle is reconstructed from all history
since each reference was available, using complete HTF candles only. There are
no resets between days. This scope must be stated in any result report.

## Execution / evaluation

Use existing Scout Replay, with a new opt-in `candidate_sweep` stop policy.
Default policies remain unchanged. Stop metadata must match the reference feed
maximum over the declared interval; otherwise reject. Keep existing USDT/USDC
conversion, limit-then-market 90s proxy, TP1=1R/TP2=2R, thirds, BE and trailing.
Fixed notional 3000 USDC; commission 0.000744 per turnover; entry/exit/stop
slippage 0/1/2 bps, conservative stop-first. Double-slippage diagnostic is fixed
in advance. No fitting of targets or filters to outcomes.

Run available aligned history March20-August17; use outcomes through August19.
Carry monitor history from first available March16 input; do not reset monthly.
Report independent opportunities and one-position portfolio, unresolved positions,
all rejections and counts, monthly results, gross/cost/net and closed-trade DD.
All available months have been researched before; no fresh holdout claim.

The first run tests this exact delta-triggered rule. A fair without-delta control
requires its own explicit activation clock (crossing instead of delta), and is
not silently presented as the same intervention. This implementation exposes
the candidate lifecycle for that later predeclared comparison, but the initial
run alone cannot attribute any observed result specifically to delta.

Input limitations: legacy Open is synthesized from previous Close, High/Low
expanded to include it by the supplied normalizer. Execution is official BTCUSDC
Spot. No borrow interest, order book, latency or real partial-fill model. No
account mark-to-market drawdown or live-readiness claim.

## Correction and execution of this experiment

The earlier v1 improperly excluded DELTA_MIN. This changes only raw-event admission
and research identity, not level conditions, H1 timing, stops, costs or exits.
Report both total portfolio results and the contribution of executed trades split
by numeric seed delta >0 / <0 / =0. These are contributions to a shared portfolio,
not standalone filtered strategies. Keep historical v1 artifacts unchanged.

For performance, immutable as-of monitor queries may be precomputed in parallel.
Each worker processes its query timestamps chronologically and reconstructs each
zone from ALL available history since its publication, using the original adapter.
No recent-history truncation, state reset, new scoring or future-price access is
introduced. Candidate lifecycle and portfolio still run once in chronological order.
Required cache verification: original positive-only engine using these queries
must reproduce all original 400 candidate records exactly.
