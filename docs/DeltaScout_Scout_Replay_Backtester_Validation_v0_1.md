# DeltaScout Scout Replay Backtester Validation v0.1

## Status

The offline Scout replay backtester is implemented for research use. It is not
approved for live signal or execution changes.

Validation date: `2026-08-20`.

## Implemented contract

- deterministic compilation of `PEAK_EMIT_BASELINE` and
  `ALMOST_PEAK_2_OF_3` candidates;
- strict UTC normalization and candidate deduplication;
- effective-feed loading with recovery-quality provenance;
- pure Executor v15 planning policy, next-bar marketable-limit fill model, and
  fixed-notional quantity construction;
- long and short lifecycle replay with TP1 breakeven, TP2 fractal trailing,
  next-bar trail activation, and explicit same-bar policies;
- commission, adverse-slippage, and zero-slippage sensitivity accounting;
- independent-opportunity and one-position portfolio modes;
- candidate, event, trade-leg, portfolio, parity, sensitivity, metric, and
  manifest artifacts;
- cutoff-safe shadow labels and loss-avoidance selectivity reporting.

## Automated verification

Command:

```powershell
python -m pytest tests/offline/scout_backtester -q
```

Result: `22 passed`.

The tests cover candidate compilation, feed-quality handling, execution-plan
construction, same-bar policy behavior, long and short lifecycle transitions,
portfolio locking, costs, parity classification, shadow features, and CLI
overwrite protection.

Python compilation check:

```powershell
python -m compileall -q deltascout/research_bundle/scout_backtester tests/offline/scout_backtester
```

Result: passed.

The broader `tests/offline` suite currently reports
`105 passed, 1 skipped, 3 failed`.
The three failures predate this backtester and occur in Delta Analyzer tests whose
fixtures no longer provide newer required builder/feed-row arguments. They do not
exercise the Scout replay package.

## Baseline evidence run

Experiment: `scout_mvp_peak_vs_almost_peak_v0`.

- candidates: `293`;
- filled independent opportunities: `195/293`;
- resolved lifecycles: `192/195`;
- lifecycle parity: `15/16` comparable operational records (`93.8%`);
- protected operational outcomes replayed as plain stops: `0/16`;
- entry-plan parity: `0/16` under the declared USDT/USDC conversion and available
  operational snapshots.

The policy status is therefore
`LIFECYCLE_THRESHOLD_MET_PLANNING_AUDIT_REQUIRED`. The result supports offline
research use, not live-policy equivalence.

## Determinism and evidence boundary

Repeated baseline runs produced identical hashes for the core output artifacts.
`run_manifest.json` records resolved arguments, input hashes, code state, output
hashes, and a stable run fingerprint.

The known enriched-feed gap is not interpreted as market evidence. Recovered
price/volume/delta rows retain provenance, while untrusted synthetic rows interrupt
active lifecycle state. Funding and liquidation fields in the gap remain unsuitable
for causal claims.

## Remaining gate before live promotion

Before any live use, reconcile entry, stop, target, quantity, symbol-conversion,
and exchange-fill assumptions against authoritative Executor snapshots. Then rerun
the parity audit and require planning parity to meet an explicitly approved
threshold. No threshold or live behavior is changed by this implementation.
