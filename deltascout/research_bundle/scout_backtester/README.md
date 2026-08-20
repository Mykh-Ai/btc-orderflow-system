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
- pure `EXECUTOR_V15_REPLAY_V0_1` policy copied from audited semantics, not imported
  from the side-effectful live module;
- OHLC execution with explicit same-bar policies;
- recovered-feed quality joined per minute;
- fixed-notional USDC economics with declared commission and slippage;
- independent-opportunity and one-position portfolio views;
- parity evidence remains separate from strategy promotion.

Generated experiments are local-only under
`deltascout/research_material/backtests/<experiment_id>/`.
