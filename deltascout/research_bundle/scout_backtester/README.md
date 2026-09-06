# DeltaScout Scout Replay Backtester

Offline deterministic replay for archived DeltaScout terminal candidates.

The package is isolated from the live signal bus, Executor state, exchange adapters,
and order placement. It implements the versioned research contract in
`docs/DeltaScout_Scout_Replay_Backtester_Spec_v0_1.md`.

Main entrypoint:

```powershell
python -m deltascout.research_bundle.scout_backtester.cli --help
```

Core boundaries:

- candidate outcome replay, not detector replay;
- pure `EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2` policy copied from audited semantics,
  not imported from the side-effectful live module;
- separate BTCUSDT Futures signal/shadow and BTCUSDC Spot execution contours;
- recovered signal-feed quality and official Spot provenance joined per minute;
- frozen signal-cutoff BTCUSDC/BTCUSDT conversion ratio for the initial plan;
- BTCUSDT Low/High trailing swings, BTCUSDT Close-only confirmation, and a fresh
  same-minute historical BTCUSDC/BTCUSDT conversion proxy for each trail quote;
- OHLC execution with explicit same-bar policies;
- fixed-notional USDC economics with declared commission and slippage;
- independent-opportunity and one-position portfolio views;
- parity evidence remains separate from strategy promotion.

Two entry-fill models are available. `MARKETABLE_LIMIT_NEXT_BAR_V0_1` preserves the
original configurable bar-expiry control. The opt-in
`LIMIT_THEN_MARKET_90S_GUARDED_V0_1` models the live fallback with `0.25R`, past-TP1,
and price-availability guards. Because the archive is one-minute OHLC, it uses the
first complete post-signal bar as the LIMIT window and the second post-signal bar's
open as a declared timeout-price proxy; it does not claim historical bid/ask or
partial-fill fidelity.

Generated experiments are local-only under
`deltascout/research_material/backtests/<experiment_id>/`.

## Opt-in volume-backed initial stop research

The default remains `window_extreme` with the declared baseline parameters. The
research-only `volume_confirmed_swing` policy selects the highest-volume confirmed
fractal swing whose buffered stop remains inside the configured distance cap. It can
require a complete lookback window and persists the selected swing evidence in every
trade row.

Relevant CLI parameters:

```text
--initial-stop-policy volume_confirmed_swing
--swing-lookback-minutes 1440
--initial-swing-lr 25
--initial-swing-buffer-usd 50
--initial-swing-max-distance-usd 1200
--initial-swing-require-full-window
```

This policy is an offline counterfactual only. A missing full window or absence of an
eligible swing becomes an explicit blocked candidate rather than a silent fallback.

For cohort-isolated ALMOST 2/3 comparisons, optionally restrict the compiled
candidate set with a comma-separated list of supported failed-gate variants:

```text
--comparison-setup-variants ALMOST_2OF3_PRICE_FAIL,ALMOST_2OF3_VWAP_FAIL
```

The selector is validated against the comparison-variant registry and persisted in
the run manifest under `candidate_selection`. An unknown variant or an empty match is
a contract error. Omit the option for the normal unfiltered replay.

To apply the frozen loss-avoidance veto before replay, use:

```text
--candidate-loss-filter UNION_A_OR_B
```

`COMPONENT_A` and `COMPONENT_B` are also supported for isolated sensitivities.
Only a definite `true` is removed; unknown/untrusted component values are kept
fail-open. The policy, counts, and excluded candidate identities are persisted in
the manifest and `candidate_loss_filter_exclusions.csv`.

Normalize official Binance Vision BTCUSDC Spot 1m archives before replay:

```powershell
python -m deltascout.research_bundle.scout_backtester.acquire_binance_spot_klines `
  --symbol BTCUSDC `
  --interval 1m `
  --date-from 2026-03-19 `
  --date-to 2026-08-19 `
  --output-root deltascout/research_material/execution_feed/btcusdc_spot_1m `
  --archives-root deltascout/research_material/execution_feed_btcusdc/raw
```
