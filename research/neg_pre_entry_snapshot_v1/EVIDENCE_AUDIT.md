# Evidence audit

Replay base d6f82fccd0ffea27831e878382eaf8f2662a39bb, clean before task. Monitor local head 652fb5bd644ec29c3e7dcced40838acfc40982fb, tree-identical to published research head e628e22e625a00e9bbb25d9bcf1e3e52640ae5b8; no Monitor edits intended. Raw git status/log/pickaxe/blame/numbered code/search evidence for BOTH repositories is under `evidence/`.

- NEG_H4 runner persists 262 decision-eligible NEG_H1_CONTROL independent opportunities and separate portfolio records; forensic joins use independent IDs only.
- Replay build_execution_plan truncates both reference and execution feeds at signal_ts_utc before selecting/validating candidate_sweep and converting/rounding stop/TP. Simulated fill is later; it must not set snapshot cutoff.
- Canonical snapshot_builder_v39a explicitly consumes close-labelled rows <= cutoff and does not discover a complete zone map itself; its zone summary is supplied through base_snapshot. Existing original research cache is upper-side activation queries, not a fresh S1/full lower map.
- Native structure aggregate_timeframe uses dt.floor(rule); confirmed swing H1 LR=2 / H4 LR=1. Adapter publishes only at the last confirming HTF close and uses individual reference zones. New forensic map keeps this scope and extends to BOTH HIGH and LOW references; it is not full merged/session/M15 architecture.
- Native registry `_update_lifecycle` reconstructs full history since first_seen. Scorer uses max(touch_count,m1_interaction_count), max(sweep_count,resweep_count,htf_sweep_count), source/timeframe, confidence, distances, lifecycle and precision. Native visibility and buckets are reused unchanged. Exact prefix-index/oracle parity is required.
- Native outputs.build_volume_delta_state: rolling z-score window 20, population standard deviation, current minute included. Native helper zero-fills missing warm-up; forensic exports instead mask unavailable contexts. Market-state timeline in outputs is explicitly `skeleton_no_classifier`, not an available meaningful regime label.
- Native events.build_event_log and post_sweep_observation.build_post_sweep_observations exist; post window is 30 minutes and includes incomplete windows explicitly. We reconstruct only from prefix data and preserve observation completeness. Reaction verdict can remain UNCLASSIFIED; no invented classifier.

## Historical source availability

Scanned all 234866 normalized legacy Spot minutes: OpenInterest/FundingRate/LiqBuyQty/LiqSellQty are empty throughout, not observed zeros. VWAP/AggTrades columns are nonempty. `normalize_legacy_aggregator_feed.py` line 152 maps VWAP from legacy AvgPrice, so use the honest minute_average_price label. Raw DELTA_MIN (1429) and DELTA_MAX (1417) journal records carry POC/VWAP observations. The contemporaneous DeltaScout code `_context` uses its rolling context and price-bin volume; these are recorded DeltaScout observations, not independently verified exchange trade-level POC. Keep only records whose converted UTC timestamp <= snapshot cutoff and record staleness. No filter uses them.

The original loader intentionally dropped these optional observed fields for replay; adding them to forensic evidence does not alter source data or replay.

## Scope correction, 2026-10-12

The user explicitly stopped the proposed Monitor/zone reconstruction and requested FEED-only S0/S1 snapshots. Earlier descriptions above document the investigation, not the delivered implementation. The unfinished two-sided-map prototype was removed before commit. No zone map, lower-structure ranking or Monitor post-sweep reconstruction is used in this task. Prior strategy levels are not revalidated by this forensic study. Raw journal delta identity remains separate from current minute flow.
