Task: synchronize the latest post-close research artifacts from the server into the local repo and prepare a concise pre-summary for the project lead.

Goal:
After the daily post-close watcher has already run on the server, copy the latest generated research artifacts for the most recently processed close date into the local repo under `deltascout/research_material/`, then produce a short pre-summary of what is available for deeper analysis.

Important:
- Do NOT rebuild anything
- Do NOT rerun the watcher
- Do NOT modify code, tests, docs, or pipeline files
- Do NOT modify local research files except by copying the synced artifacts into the correct local folders
- This is a sync + pre-summary task only

Server access:
- `ssh -F NUL root@95.216.139.172`

Server runtime root:
- `/root/volume-alert`

Local repo root:
- `D:\Project_V\btc-orderflow-system`

Required workflow:
1. Read watcher state on the server to discover the latest processed close date
2. Verify the expected review artifacts exist for that date
3. Copy those artifacts into the correct local research_material folders
4. Return a concise pre-summary for the project lead

A. Determine the latest processed date from watcher state
On the server, inspect:
- `/root/volume-alert/data/state/post_close_watcher_state.json`

The state file must exist and must contain at minimum:
- `last_processed_date`
- `last_processed_trade_key` or `last_processed_marker`

If these fields are missing, stop immediately and report:
- the full file content
- the exact reason the task cannot continue

Use:
- `last_processed_date` as `YYYY-MM-DD` for all remaining steps

B. Verify required server artifacts for that date
Using `YYYY-MM-DD = last_processed_date`, verify these files exist on the server:

1. Analyzer outputs (all under `/root/volume-alert/data/archive/datasets/`)
- `reviews/YYYY-MM-DD/accepted_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_event_context_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/interesting_rejects_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/reject_reason_summary_YYYY-MM-DD.csv`
- `reviews/YYYY-MM-DD/daily_review_summary_YYYY-MM-DD.md`
- `close_outcomes_YYYY-MM-DD.csv` (if CSV does not exist, check `.parquet`)
- `baseline_init_YYYY-MM-DD.csv`
- `late_peak_YYYY-MM-DD.csv`
- `reject_dataset_YYYY-MM-DD.csv`
- `window_owner_miss_YYYY-MM-DD.csv`
- `events_context_YYYY-MM-DD.csv`

2. Raw archive/feed inputs for the same date
- `/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl`
- `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv`

If any required file is missing, stop and report exactly which file is missing.

Also report line counts where applicable:
- accepted_event_context csv
- reject_event_context csv
- interesting_rejects csv
- reject_reason_summary csv
- close_outcomes csv if present
- baseline_init csv
- late_peak csv
- reject_dataset csv
- window_owner_miss csv
- events_context csv
- raw archive jsonl
- raw feed csv

C. Copy the artifacts into the local repo
Copy these artifacts from server to local repo:

1. All analyzer outputs into one folder per date:
- `D:\Project_V\btc-orderflow-system\deltascout\research_material\reviews\YYYY-MM-DD\`

Files:
- `accepted_event_context_YYYY-MM-DD.csv`
- `reject_event_context_YYYY-MM-DD.csv`
- `interesting_rejects_YYYY-MM-DD.csv`
- `reject_reason_summary_YYYY-MM-DD.csv`
- `daily_review_summary_YYYY-MM-DD.md`
- `close_outcomes_YYYY-MM-DD.csv` (or parquet if that is the only server artifact present)
- `baseline_init_YYYY-MM-DD.csv`
- `late_peak_YYYY-MM-DD.csv`
- `reject_dataset_YYYY-MM-DD.csv`
- `window_owner_miss_YYYY-MM-DD.csv`
- `events_context_YYYY-MM-DD.csv`

2. Raw archive into:
- `D:\Project_V\btc-orderflow-system\deltascout\research_material\raw_archive\`

File:
- `YYYY-MM-DD.jsonl`

3. Raw feed into:
- `D:\Project_V\btc-orderflow-system\deltascout\research_material\raw_feed\`

File:
- `YYYY-MM-DD.csv`

Before copying, ensure the local target directories exist using the appropriate local shell commands for your environment.
Use local path syntax consistently for the shell you are running in.

After copy, verify the local files exist and are non-empty.

D. Inspect the synced artifacts briefly
After sync, do a brief inspection only:

1. `daily_review_summary_YYYY-MM-DD.md`
- read it fully

2. `accepted_event_context_YYYY-MM-DD.csv`
- show first 5 lines

3. `reject_event_context_YYYY-MM-DD.csv`
- show first 10 lines

4. `interesting_rejects_YYYY-MM-DD.csv`
- show first 10 lines
- report interesting_reject_bucket and interesting_rule_id distribution

6. `close_outcomes_YYYY-MM-DD.csv` if present
- show first 5 lines
- explicitly extract:
  - `join_status`
  - `close_reason`
  - `side`
  - `entry`
  when present

7. `raw_archive/YYYY-MM-DD.jsonl`
- show first 5 lines

Do not perform deep analysis yet.
This is only to prepare a pre-summary.

E. Return this exact output structure

A. Watcher state
- latest processed date
- latest processed trade key or marker
- whether the state file looked valid

B. Server artifacts
- exact files found
- line counts for each file
- whether close_outcomes was CSV or parquet

C. Local sync result
- exact local target paths
- whether each file was copied successfully
- whether each copied file is non-empty

D. Pre-summary for project lead
In 5–10 bullets maximum, summarize only:
- accepted row count
- reject row count
- interesting reject row count and dominant buckets/rule_ids
- whether accepted-to-close join appears present
- dominant reject reasons if visible from summary
- whether raw archive/feed for the same date are now synced locally
- whether the local package now looks ready for deeper analysis

E. Any blockers or anomalies
- missing file
- empty file
- format mismatch
- anything that may affect later analysis

Rules:
- no rebuild
- no watcher rerun
- no code edits
- no deep interpretation
- just sync and prepare the local research package cleanly