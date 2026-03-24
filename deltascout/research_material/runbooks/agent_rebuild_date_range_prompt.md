Task: rebuild DeltaScout research datasets for a specified date range on the server and sync results to local repo.

Goal:
Re-run the full 4-step offline pipeline on the server for each date in the requested range, then copy all generated artifacts to the local repo under `deltascout/research_material/`.

This is a fallback operation for cases when:
- the automatic post-close watcher missed dates
- code was updated and outputs need regeneration
- a specific date range needs to be reprocessed from scratch

Important:
- Do NOT modify code, tests, docs, or pipeline files
- Do NOT touch `/opt/aitrader` scripts or config — it is a separate project
- Do NOT rebuild dates outside the requested range
- Do NOT skip pipeline steps or reorder them
- If any step fails for a date, stop the entire run and report the failure

Parameters (provided by the user at invocation):
- `DATE_FROM` — first UTC date to rebuild (inclusive), YYYY-MM-DD
- `DATE_TO` — last UTC date to rebuild (inclusive), YYYY-MM-DD

If the user does not provide a range, ask before proceeding.
Do NOT assume "today" or "latest" — the range must be explicit.

Server access:
- `ssh -F NUL root@95.216.139.172`

Server runtime root:
- `/root/volume-alert`

Server paths:
- Python: `/opt/aitrader/.venv/bin/python`
- PYTHONPATH: `/root/volume-alert`
- Working directory for all commands: `/root/volume-alert`
- Input root: `/root/volume-alert/data`
- Output root: `/root/volume-alert/data/archive/datasets`
- Enriched feed root: `/opt/aitrader/feed`
- Trade outcomes journal: `/root/volume-alert/data/state/trade_outcomes.jsonl`

Local repo root:
- `D:\Project_V\btc-orderflow-system`

---

Required workflow:

A. Pre-flight checks

Before rebuilding, verify on the server that required inputs exist for every date in the range:

1. Archive JSONL: `/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl`
2. Enriched feed: `/opt/aitrader/feed/YYYY-MM-DD.csv`

If any input is missing for any date, stop and report exactly which files are missing.
Do NOT attempt partial rebuilds for dates with missing inputs.

Also verify:
- Trade outcomes journal exists: `/root/volume-alert/data/state/trade_outcomes.jsonl`
- Python binary is accessible: `/opt/aitrader/.venv/bin/python --version`

B. Run the 4-step pipeline for each date

For each date in the range (in chronological order), run all 4 steps sequentially on the server.
All commands must run from `/root/volume-alert` with `PYTHONPATH=/root/volume-alert`.

Step 1 — Phase 1 derived datasets:
```bash
/opt/aitrader/.venv/bin/python scripts/offline/build_phase1_derived.py \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data \
  --output-root /root/volume-alert/data/archive/datasets \
  --feed-root /opt/aitrader/feed
```

Step 2 — Close outcomes join:
```bash
/opt/aitrader/.venv/bin/python scripts/offline/build_close_outcomes.py \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data \
  --output-root /root/volume-alert/data/archive/datasets \
  --trade-outcomes-file /root/volume-alert/data/state/trade_outcomes.jsonl
```

Step 3 — Build events_context CSV:
```bash
/opt/aitrader/.venv/bin/python -m deltascout.delta_analyzer.cli \
  --archive-glob "/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl" \
  --feed-glob "/opt/aitrader/feed/YYYY-MM-DD.csv" \
  --date YYYY-MM-DD \
  --output-root /root/volume-alert/data/archive/datasets
```

Step 4 — Daily review package:
```bash
/opt/aitrader/.venv/bin/python -m deltascout.delta_analyzer.cli \
  --build-review \
  --date YYYY-MM-DD \
  --input-root /root/volume-alert/data/archive/datasets \
  --output-root /root/volume-alert/data/archive/datasets
```

Failure handling:
- If any step fails (non-zero exit), stop immediately
- Report the failing step name, date, and exit code
- Do NOT continue to the next date
- Do NOT proceed to sync

C. Verify outputs on the server

After all dates complete successfully, verify that the following files exist for every date in the range:

Under `/root/volume-alert/data/archive/datasets/`:
- `reject_dataset_YYYY-MM-DD.csv`
- `baseline_init_YYYY-MM-DD.csv`
- `window_owner_miss_YYYY-MM-DD.csv`
- `late_peak_YYYY-MM-DD.csv`
- `close_outcomes_YYYY-MM-DD.csv`
- `events_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/accepted_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/interesting_rejects_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_reason_summary_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/daily_review_summary_YYYY-MM-DD.md`

Report line counts for each file.

D. Sync artifacts to local repo

For each date in the range, copy from server to local:

1. All review + dataset outputs into:
   `D:\Project_V\btc-orderflow-system\deltascout\research_material\reviews\YYYY-MM-DD\`

Files:
- `accepted_event_context_YYYY-MM-DD.csv`
- `reject_event_context_YYYY-MM-DD.csv`
- `interesting_rejects_YYYY-MM-DD.csv`
- `reject_reason_summary_YYYY-MM-DD.csv`
- `daily_review_summary_YYYY-MM-DD.md`
- `close_outcomes_YYYY-MM-DD.csv`
- `baseline_init_YYYY-MM-DD.csv`
- `late_peak_YYYY-MM-DD.csv`
- `reject_dataset_YYYY-MM-DD.csv`
- `window_owner_miss_YYYY-MM-DD.csv`
- `events_context_YYYY-MM-DD.csv`

2. Raw archive into:
   `D:\Project_V\btc-orderflow-system\deltascout\research_material\raw_archive\`

File: `YYYY-MM-DD.jsonl`

3. Raw enriched feed into:
   `D:\Project_V\btc-orderflow-system\deltascout\research_material\raw_feed\`

File: `YYYY-MM-DD.csv`

Before copying, ensure local target directories exist.
After copy, verify local files exist and are non-empty.

E. Post-rebuild validation

For each date, report from the pipeline output:
- `ret_15m` coverage (non-null count / total)
- `ret_60m` coverage (non-null count / total)
- accepted row count
- reject row count
- matched close count (if any)

Flag any date where `ret_15m` or `ret_60m` coverage is below 90% — this may indicate a missing previous-day feed file.

F. Return this exact output structure

1. Pre-flight
   - date range requested
   - inputs verified (archive + feed per date)

2. Pipeline execution
   - per-date: 4 step names, pass/fail, key row counts from stdout

3. Server verification
   - per-date: files found, line counts

4. Local sync
   - per-date: files copied, non-empty confirmed

5. Validation summary
   - per-date: ret_15m coverage, ret_60m coverage, accepted/reject/close counts
   - any flagged anomalies

6. Blockers or anomalies
   - missing inputs
   - step failures
   - empty outputs
   - low coverage warnings

Rules:
- no code changes
- no test changes
- no doc changes
- no watcher restarts
- execute pipeline steps exactly as documented above
- stop on first failure
