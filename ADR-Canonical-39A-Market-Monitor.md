# ADR: One canonical 39A Market Monitor

## Status

WIP / research. Blocked by the unchanged prompt-contract test; not ready for merge. No deployment or Executor restart.

## Decision

The sole production route is `feed_adapter.load_feed(..., deduplicate=False)` → `market_monitor.snapshot_builder_v39a.build_market_monitor_snapshot_v39a` → `LLM_ENTRY_SNAPSHOT_V2` → advisory LLM Trade Judge. The Executor finalization path never reads the LLM verdict as a gate.

The 39A builder owns the canonical snapshot. It directly composes the source algorithms in `market_monitor/canonical_features.py` for rolling market state, structure classification, significant zones and liquidity zones. It does not consume another snapshot. The old v1 snapshot builder and duplicate Executor 39A builder are removed. No environment setting selects a Market Monitor implementation or reactivates a legacy fallback.

## Data contract

- The six required local windows are exactly 5, 15, 30, 60, 240 and 1440 closed UTC minute labels ending at the inclusive cutoff. The loader reads all available CSV files, so these windows cross UTC day and file boundaries.
- Each window reports expected and actual rows, up to ten missing timestamps, duplicate count, completeness, and `metrics_valid`. A partial window is never valid evidence. Duplicates in the 30 day context also block readiness.
- `quality.readiness` is `READY`, `READY_WITH_DEGRADED_DATA`, or `INCOMPLETE`. Recovered or otherwise non-RAW source rows make a complete snapshot degraded. Incomplete snapshots cannot be sent to the LLM.
- `market_state` is the descriptive rolling 1440 minute regime from `outputs.build_market_state_timeline`. `market_structure_state` is the price-relative classifier from `market_structure_state._classify_state` and is the only source of `candidate_bias`. `structure.levels` are observed 240/1440 extrema, not qualified setups. `significant_market_zones` and `liquidity_zones` are separately typed outputs of the direct zone algorithms, with no fallback from persisted state.
- `delta_pct` is a fraction of total quantity in all exposed fields, including structure metrics. `price_change_pct` is percentage points. `range_position` is a 0–1 fraction. Open interest change retains feed contract units. OHLC typical-price `vwap_approx` is explicitly approximate; true POC is `null` because minute OHLCV lacks price-volume distribution. `current.price` is the last closed minute's close.
- Broad 1d/3d/7d/30d context carries its own quality flags. The six local windows are mandatory for readiness; broad context can be partial and is labeled as such.
- The state file records the cutoff, day rollover and current descriptive state. Atomic writes occur only after complete evidence. A corrupt, incompatible or future state fails loudly. Repeating the same cutoff does not increase carry-forward count; restart at the same feed and cutoff is deterministic.

## Boundaries

The LLM entry snapshot validator accepts only the self-contained canonical 39A contract with complete windows and direct feature lineage. An invalid monitor yields an advisory error record and cannot alter placement, exit, position size or finalization. This ADR does not approve live monitor deployment, order changes, historical verdict changes, or prompt calibration changes.

## Historical evidence

`LOG.md` and prior refactor/parity evidence record the old runtime and old configuration at their historical dates. They are not deployment instructions for this ADR. The checked-in repository has no tracked docker-compose, example env or deployment configuration file to edit.
