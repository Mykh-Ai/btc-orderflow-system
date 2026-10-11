# Peak_Ai delta-triggered H1 research family

Research-only implementation of raw DELTA_MAX → significant H1/H4 upper zone →
closed H1 back below the zone within four hours. See PROTOCOL.md for the frozen
rule, timestamps, stop, costs and explicit limitations.

## Repositories

- Replay task branch: codex/peak-ai-delta-h1-replay-v1 in btc-orderflow-system.
- Monitor task branch: codex/peak-ai-delta-h1-v1 in aitrader, based on canonical/market-monitor-39a.
- Add the modified AiTrader checkout to PYTHONPATH. The old Executor ZIP is not a dependency.
- No production Executor or DeltaScout modules were modified. The new stop policy
  is opt-in in the offline replay only; defaults are unchanged.

## Inputs

Use the prepared Scout Replay handoff bundles documented in
`docs/research/scout_replay_work_handoff_2026_10_02.md`.
Required folders below `deltascout/research_material`:

- `raw_archive/`: DELTA_MIN/MAX journal events;
- `execution_feed/btcusdt_legacy_spot_1m/daily/`: signal/structure reference;
- `execution_feed/btcusdc_spot_1m/daily/`: execution.

Inputs are read-only and SHA-256 checked. Liquidations are missing from these
normalized archives and do not enter this first hypothesis.

## Run from the btc-orderflow-system checkout

Example with the AiTrader checkout in the adjacent `aitrader-monitor` directory:

```bash
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1.run prepare --output research/peak_ai_delta_h1/my_run
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1.run base --output research/peak_ai_delta_h1/my_run
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1.run double_slippage --output research/peak_ai_delta_h1/my_run
```

Use a fresh output directory. Preparation saves a checkpoint approximately every
20 seconds of computation. To resume an interrupted preparation with unchanged
code and inputs, repeat its command with `--resume`. Only resume a checkpoint
created locally by this program; pickle is not an untrusted interchange format.

The incomplete initial `results_v1` directory is retained as interruption evidence.
The completed recovery campaign, when present, is `results_v1_checkpointed`.
Its protocol is unchanged; the recovery adds checkpointing and equivalent
faster timestamp iteration in three native lifecycle helpers.

## Outputs

- `protocol_freeze.json`, `input_hashes.csv`: parameters, source versions and hashes.
- `structural_inventory.csv`: H1/H4 references with actual availability timestamps.
- `seed_audit.csv`: every raw seed, including excluded DELTA_MIN and every refusal.
- `zone_selection_audit.csv`: relevant zone scores at each trigger.
- `candidate_events.csv`: ARMED, H1_CLOSE, EXPIRED, CONFIRMED, gap/censor events.
- `candidates.json` / `.csv`: confirmed research candidates, not live trades.
- `base/` and `double_slippage/`: independent and portfolio trade/event ledgers and metrics.
- `progress.json`: explicit completed flag; a started process is not a completed run.

## Tests

Run the existing `tests/offline/scout_backtester` suite, this folder's
`test_engine.py`, and AiTrader's `tests/test_closed_structure_adapter.py` plus
its native selector/registry/HTF lifecycle tests. The tests cover future-prefix
invariance, confirmed-candle availability, strict boundaries, gap rejection,
exact deadline, duplicate timer behavior and verification of the sweep stop.

## Interpretation

This adapter uses immutable individual H1/H4 swing zones and native lifecycle /
significance. It is not the complete v39A Monitor: no clustered zones, M15,
sessions, patterns, hidden-flow or post-sweep scoring bonuses. A profitable replay
would not prove delta adds value; a separately specified without-delta control
and unused-period validation are still required. All tested months were already
available to earlier research.
