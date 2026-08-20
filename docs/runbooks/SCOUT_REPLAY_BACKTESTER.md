# Scout Replay Backtester Runbook

## Purpose

Run the offline DeltaScout candidate replay without changing live thresholds,
orders, Executor state, or server files.

The authoritative contract is
`docs/DeltaScout_Scout_Replay_Backtester_Spec_v0_1.md`.

## Preconditions

1. Run from the repository root.
2. Use local `reviews`, `raw_archive`, `effective_feed`, recovery sidecar, and
   `server_state` artifacts.
3. Do not substitute the original broken enriched rows inside the documented
   2026-04-23 through 2026-05-06 gap.
4. Choose a new experiment id. Existing non-empty experiment directories are
   rejected and never overwritten.

## Baseline command

```powershell
python -m deltascout.research_bundle.scout_backtester.cli `
  --candidate-root deltascout/research_material/reviews `
  --raw-archive-root deltascout/research_material/raw_archive `
  --feed-root deltascout/research_material/effective_feed `
  --quality-sidecar-root deltascout/research_material/recovery_reports `
  --server-state-root deltascout/research_material/server_state `
  --date-from 2026-03-20 `
  --date-to 2026-08-20 `
  --candidate-groups PEAK_EMIT_BASELINE,ALMOST_PEAK_2_OF_3 `
  --execution-policy EXECUTOR_V15_REPLAY_V0_1 `
  --fill-model MARKETABLE_LIMIT_NEXT_BAR_V0_1 `
  --same-bar-policy CONSERVATIVE_STOP_FIRST_V0_1 `
  --cost-model COMMISSION_TURNOVER_RATE_V0_1 `
  --replay-modes independent_opportunity,executor_portfolio `
  --experiment-id scout_mvp_peak_vs_almost_peak_v0
```

The baseline automatically writes target-first same-bar sensitivity and a
zero-slippage diagnostic alongside the configured adverse-slippage result.

## Validation before interpreting results

```powershell
python -m pytest tests/offline/scout_backtester -q
```

Require all synthetic state-machine tests to pass. Then review:

1. `run_manifest.json` for resolved parameters, input hashes, code state, and the
   deterministic run fingerprint;
2. `candidate_quality.csv` for duplicates, invalid rows, missing coverage, and
   untrusted synthetic interruptions;
3. `parity_report.csv` for planning versus lifecycle parity and classified
   mismatches;
4. `same_bar_sensitivity.csv` and `cost_sensitivity.csv`;
5. `summary.md` only after the evidence tables above.

## Portfolio quality boundary

If an active replay crosses an untrusted synthetic minute, the position state is
unknown. Later portfolio rows are labeled `NO_FEED_COVERAGE`; they are not counted as
position-lock opportunity cost. Independent candidates remain separately replayable
where their own paths have reliable coverage.

## Interpretation rules

- Do not show a percentage without its count and denominator.
- Keep normalized R separate from fixed-notional USDC PnL.
- Treat `TP1_SL` as scratch-neutral utility even when costs make net PnL negative.
- Do not treat recovered funding or liquidation fields as trusted evidence.
- Do not label `EXECUTOR_V15_REPLAY_V0_1` parity-validated while the summary reports
  `PLANNING_AUDIT_REQUIRED`.
- Do not promote a candidate rule to live logic from this output.
