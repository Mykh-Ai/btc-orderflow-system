# Scout Replay Backtester Runbook

## Purpose

Run the offline DeltaScout candidate replay without changing live thresholds,
orders, Executor state, or server files.

The authoritative contract is
`docs/DeltaScout_Scout_Replay_Backtester_Spec_v0_1.md`.

## Preconditions

1. Run from the repository root.
2. Use local `reviews`, `raw_archive`, `effective_feed`, official BTCUSDC Spot
   execution feed, recovery sidecar, and `server_state` artifacts.
3. Do not substitute the original broken enriched rows inside the documented
   2026-04-23 through 2026-05-06 gap.
4. Choose a new experiment id. Existing non-empty experiment directories are
   rejected and never overwritten.

## Prepare the execution feed

The signal/shadow contour remains the enriched BTCUSDT Futures feed. Lifecycle
execution requires official Binance Vision BTCUSDC Spot 1m bars. Normalize already
downloaded and checksum-verified archives with:

```powershell
python -m deltascout.research_bundle.scout_backtester.acquire_binance_spot_klines `
  --symbol BTCUSDC `
  --interval 1m `
  --date-from 2026-03-19 `
  --date-to 2026-08-19 `
  --output-root deltascout/research_material/execution_feed/btcusdc_spot_1m `
  --archives-root deltascout/research_material/execution_feed_btcusdc/raw
```

The normalizer verifies each archive checksum and writes daily UTC bars plus
`provenance/source_manifest.json` and `provenance/daily_quality.csv`.

## Baseline command

```powershell
python -m deltascout.research_bundle.scout_backtester.cli `
  --candidate-root deltascout/research_material/reviews `
  --raw-archive-root deltascout/research_material/raw_archive `
  --feed-root deltascout/research_material/effective_feed `
  --execution-feed-root deltascout/research_material/execution_feed/btcusdc_spot_1m/daily `
  --quality-sidecar-root deltascout/research_material/recovery_reports `
  --server-state-root deltascout/research_material/server_state `
  --date-from 2026-03-20 `
  --date-to 2026-08-20 `
  --candidate-groups PEAK_EMIT_BASELINE,ALMOST_PEAK_2_OF_3 `
  --execution-policy EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2 `
  --fill-model MARKETABLE_LIMIT_NEXT_BAR_V0_1 `
  --same-bar-policy CONSERVATIVE_STOP_FIRST_V0_1 `
  --cost-model COMMISSION_TURNOVER_RATE_V0_1 `
  --replay-modes independent_opportunity,executor_portfolio `
  --experiment-id scout_peak_vs_almost_peak_btcusdc_spot_dual_feed_v1
```

The baseline automatically writes target-first same-bar sensitivity and a
zero-slippage diagnostic alongside the configured adverse-slippage result.

For the guarded live-entry fallback sensitivity, replace the fill-model argument
and keep the frozen live defaults explicit:

```powershell
  --fill-model LIMIT_THEN_MARKET_90S_GUARDED_V0_1 `
  --live-entry-timeout-seconds 90 `
  --planb-max-dev-r-mult 0.25 `
  --planb-max-dev-usd 0 `
  --planb-require-price `
  --planb-abort-if-past-tp1 `
  --planb-price-proxy SECOND_NEXT_BAR_OPEN
```

Treat this as a one-minute proxy for the live chain, not exact book-ticker replay.
Review `entry_fill_method`, `planb_decision`, and `planb_abort_reason` in the trade
ledger before interpreting aggregate results.

## Isolated ALMOST 2/3 cohort replay

To remove cross-cohort competition from the one-position portfolio diagnostic,
restrict a run to one or more registered ALMOST 2/3 failed-gate variants:

```powershell
  --candidate-groups ALMOST_PEAK_2_OF_3 `
  --comparison-setup-variants ALMOST_2OF3_PRICE_FAIL
```

Supported values are the registered comparison variants, including
`ALMOST_2OF3_PRICE_FAIL`, `ALMOST_2OF3_VOLUME_FAIL`, and
`ALMOST_2OF3_VWAP_FAIL`. The selector is written to `run_manifest.json` under
`candidate_selection`; unknown values and selectors that match no candidates fail
the run. Use a distinct experiment id for every isolated cohort and stop-policy
combination.

To apply the frozen live-style A-or-B veto before replay, add:

```powershell
  --candidate-loss-filter UNION_A_OR_B
```

The alternative research sensitivities are `COMPONENT_A` and `COMPONENT_B`.
Filtering occurs after shadow-feature enrichment and before independent or
portfolio replay. Only definite `true` values are removed; unknown/untrusted values
remain admitted under the fail-open contract. Audit the blocked identities in
`candidate_loss_filter_exclusions.csv` and the counts in the manifest's
`research_analysis.applied_candidate_loss_filter` object.

## Validation before interpreting results

```powershell
python -m pytest tests/offline/scout_backtester -q
```

Require all synthetic state-machine tests to pass. Then review:

1. `run_manifest.json` for resolved parameters, input hashes, code state, and the
   deterministic run fingerprint;
2. `candidate_quality.csv` for duplicates, invalid rows, missing coverage, and
   untrusted synthetic interruptions;
3. the execution-feed provenance manifest and daily quality table for checksum,
   UTC coverage, gaps, and duplicates;
4. `parity_report.csv` for planning versus lifecycle parity and classified
   mismatches;
5. `loss_avoidance_summary.md`, including protected outcomes blocked per cohort;
6. `same_bar_sensitivity.csv` and `cost_sensitivity.csv`;
7. `summary.md` only after the evidence tables above.

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
- Do not label `EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2` parity-validated while the summary reports
  `PLANNING_AUDIT_REQUIRED`.
- Do not promote a candidate rule to live logic from this output.
- Treat earlier single-feed runs, including `v5`, as superseded for lifecycle and
  expectancy conclusions. They remain forensic artifacts and must not be overwritten.
