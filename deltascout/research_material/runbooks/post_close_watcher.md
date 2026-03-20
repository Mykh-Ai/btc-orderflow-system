# Post-close watcher

`scripts/offline/run_post_close_watcher.py` is a small cron-friendly orchestrator for DeltaScout post-close research automation.

## Canonical trigger source

The watcher uses only `/root/volume-alert/data/state/trade_outcomes.jsonl` as its close-event trigger source.
It does not use `executor.log`, `executor_state.json`, generated close outcome CSVs, or review outputs as triggers.

## Behavior

- Reads the latest valid close/outcome row from `trade_outcomes.jsonl`.
- Skips malformed JSONL rows safely.
- If `trade_outcomes.jsonl` is missing, empty, or has no new valid close row, the watcher exits cleanly without running the pipeline.
- Processes only one latest close marker at a time, using `trade_key` when present and a timestamp/reason/side fallback when it is not.
- Runs, in order, `build_phase1_derived`, `build_close_outcomes`, and `delta_analyzer --build-review` for the discovered UTC close date.
- Updates `/root/volume-alert/data/state/post_close_watcher_state.json` only after all three steps succeed.

## Intended usage

Run it once per day from cron, for example early in the morning UTC after close outcomes for the prior session are expected to exist.
Repeated daily runs are safe because the watcher exits quickly when the latest close marker is already processed.

Recommended manual run pattern:

```bash
cd /root/volume-alert
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python scripts/offline/run_post_close_watcher.py
```

Recommended cron pattern with log redirection under the current project layout:

```cron
10 6 * * * cd /root/volume-alert && PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python scripts/offline/run_post_close_watcher.py >> /root/volume-alert/data/logs/post_close_watcher.log 2>&1
```
