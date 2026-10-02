# ADR: LLM Trade Judge Market Monitor single canonical path

Date: 2026-09-20
Status: proposed for architect review
Scope: advisory entry evidence only

## Evidence and decision

The `v2.0` runtime builds v1 first from a cutoff-day `current_feed`. `LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED` then decides whether the final model-facing snapshot is v1 or v39A. The independent snapshot flag can omit monitor evidence entirely. The stored 2026-09-14 entry snapshot has schema `market_monitor_snapshot_v1` and a 133-row nominal 240-minute window. The 2026-09-11 deployment record proves v39A existed; the exact cause of later routing drift is unproven.

The LLM Trade Judge will always receive one canonical `market_monitor_snapshot_v39a` when it is enabled. Both old routing flags are accepted only as ignored compatibility inputs. A missing context feed, invalid required window, builder error, or noncanonical snapshot prevents the LLM call and creates a durable error verdict, log event, and existing webhook notification. The Executor position lifecycle continues.

## Invariants

A. One production model-facing Market Monitor schema is `market_monitor_snapshot_v39a`.

B. Canonical construction failure never falls back to v1, a fabricated snapshot, or an evidence-poor model call.

C. All six closed-minute windows (5, 15, 30, 60, 240, 1440) use the continuous context feed and cross UTC file/day boundaries.

D. Each window exposes expected and used rows, start and end, completeness, missing timestamps, duplicate rows, and data quality. Incomplete required windows are explicit errors for the LLM assessment.

E. The LLM Judge remains advisory. Its failure cannot interrupt order finalization, SL/TP, reconciliation, margin repayment, or close cleanup.

F. Persisted monitor state is loaded deterministically after restart. An incomplete assessment must not overwrite valid persisted state; a future-dated state must not leak into a historical replay.

## Retained v1 component classification

- Local 15/60/240 metrics from cutoff-day `current_feed`: **UNSAFE**. Exclude from canonical output; v39A windows replace them.
- `market_state` and `market_structure_state`: **UNSAFE** when built from cutoff-day feed. Rebuild the v1 helper on a complete continuous 1440-minute slice, then label its provenance and scope explicitly.
- Local liquidity structure/registry and local accumulation input: **UNSAFE** when built from cutoff-day feed. Rebuild on the same continuous 1440-minute slice.
- Broad context and context inventory/significant zones: **SAFE** relative to this defect because they already use continuous `context_feed`; retain their v1 provenance. Significant zones also incorporate the rebuilt local registry.
- v1 schema itself: **LEGACY internal helper** only; never final model-facing output.

The bounded 1440-minute base slice does not promote the unimplemented 39A level lifecycle or prove a trade edge.

## Migration and rollback

Retain old ENV keys temporarily for deployment compatibility, but ignore both routing flags. Require `LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED` (or its existing alias) for canonical input. The current-feed key can remain as ignored compatibility configuration. Preserve the existing v39A state path and schema. Before deployment, back up Executor source/config, capture container image and selected ENV, then document the exact rollback paths. Deployment requires all local tests and a read-only in-container midnight smoke to pass. Historical verdicts remain immutable.
