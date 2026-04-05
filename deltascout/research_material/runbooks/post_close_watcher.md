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
- Runs, in order, four pipeline steps for the discovered UTC close date:
  1. `build_phase1_derived` вЂ” rejects, baseline, ownership misses, late peaks
  2. `build_close_outcomes` вЂ” close outcome join from trade_outcomes journal
  3. `delta_analyzer.cli` (main mode) вЂ” builds `events_context_YYYY-MM-DD.csv` from archive + enriched feed
  4. `delta_analyzer.cli --build-review` вЂ” daily review package from prebuilt datasets
- Updates `/root/volume-alert/data/state/post_close_watcher_state.json` only after all four steps succeed.
- For DeltaScout event-linked research, `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv` is the canonical event-source minute base because it is produced by the same raw writer chain as runtime `aggregated.csv` and underlies actual `PEAK_EMIT` generation.
- `build_phase1_derived` may use `--feed-root /opt/aitrader/feed` as a secondary enrichment layer for additional minute context. It falls back to `--input-root/feed/YYYY-MM-DD.csv` only when `--feed-root` is not supplied, and any enrichment-derived fields must remain explicitly separated from canonical event-source feed fields.
- Step 3 automatically loads the previous day's feed file (when available) to compute `ret_15m`/`ret_60m` for early-day events.

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


