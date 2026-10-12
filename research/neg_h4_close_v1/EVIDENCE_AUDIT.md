# NEG_H4_CLOSE_V1 evidence audit

Base: `966dabcc0bef0ac7289905fcdfaf93252e1d1198`, branch `codex/peak-ai-research-consolidated-2026-10-11`. Working branch starts at that exact commit. Remote Git object was fetched successfully. Original local full-data consolidation remains on its original branch. The canonical lossless archive restored 133 files with SHA-256 verification; no source feed was edited.

The raw command outputs in `evidence/` record status, 30 commits, both requested pickaxe histories, blame, numbered engine/runner/portfolio/adapter/structure, and all requested searches. Canonical history contains the prior publication snapshot: local pre-publication implementation commits are not ancestors of the API-published snapshot, so blame attributes that snapshot.

## Confirmed contracts

- `engine.py` in corrected all-signs research: HORIZON = four hours. Completed H1 requires 60 valid contiguous close-labelled minutes. Strict close < lower; seed timestamp < confirmation <= deadline. Pending expiration follows the exact-boundary confirmation check. Gaps/invalid bars cancel pending before confirmation. First owner, zone/episode and same-timestamp SHORT dedup are chronological.
- Same engine: numeric delta is checked against buy_qty - sell_qty, separately from DELTA_MIN/MAX event names. Thus NEG is numeric delta < 0, not an event-name assumption. Sweep high updates through confirmation; 0.0001 buffer.
- `run.py`: decision range March 20–August 17, outcomes through August 19; original 3000 USDC, turnover commission 0.000744, slippage 0/1/2 bps, candidate_sweep, limit-then-market 90-second proxy. Existing replay functions can be imported without editing them.
- `portfolio.py`: one active position/pending entry, existing cooldown, explicit BLOCKED copies and opportunity audit. Use unchanged.
- Monitor `closed_structure_adapter.py`: minute_frame shifts availability timestamps back one minute; references publish after confirming HTF completion. Native zone query selects nearest eligible upper boundary, score tie-break then stable ID; frozen single-reference H1/H4 structural identity. No recalculation of pending zones.
- Monitor `structure.py` `aggregate_timeframe`: H4 maps to rule `4h`, applied by `Timestamp.dt.floor(rule)` (the code uses the rule variable, not literal `floor("4h")`). Reuse this function. The native aggregator itself can return partial bars; the experiment must enforce all 240 contiguous valid minutes before using its close.
- Cache `query_cache_v2`: immutable exact-timestamp native queries; existing loader validates every partition and code hash. Reuse these, with no new score or level filter.

## Comparison caveat fixed before results

The supplied historical NEG baseline is a contribution to all-sign pending/dedup and portfolio state. A new NEG-only experiment changes admission as explicitly required; POS owners no longer suppress NEG. Report the supplied historical baseline, AND an additional NEG-only H1 control using the same new engine with H1 confirmation. H1 versus H4 in that matched pair isolates the timeframe change. No time-delay, strength, volatility, session or other filter is added.

## Gate

Rebuild original all-sign H1 candidates from source minutes, journal and verified cache. Require all 516 candidate records (515 decision-eligible), all 2846 seed statuses, per-trade replay fields and supplied aggregate totals to match. STOP before new H4 interpretation if any mismatch is unexplained. Historical source-path prefixes are provenance paths; compare canonical candidate records after normalizing only those prefixes if necessary, never prices, times or financial fields.
