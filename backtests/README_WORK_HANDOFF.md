# Backtest handoff — 2026-10-02

These are frozen local Executor research scripts, reports, manifests, and run outputs copied for GitHub Work. They are historical offline analysis, not deployed trading behavior.

The large duplicated raw Spot archive under `imbalance_045_075_through_2026-09-27_v1/source/` was omitted (1,252 files, 161,974,439 bytes). `source_snapshot_manifest.json` retains its source hashes. The enriched feed, legacy feed, and DeltaScout archives are available in `../docs/research/source_data_2026_10_02/`. The omitted Spot archive is a separate source and must be reacquired by hash for exact replay.

`AB_FILTER_REVIEW.md` contains detailed A/B rejection cases. The strategy checkpoint and scope are in the DeltaScout `RESEARCHLOG.md` on the separate `codex/scout-replay-backtester-v0-1` branch. Paths inside older run artifacts may still refer to the Windows checkout.
