Task: orchestrate the full DeltaScout research handoff workflow for a specified UTC date range.

Goal:
Run the correct sequence of DeltaScout research steps so the local repo ends with:
- rebuilt artifacts on the server when requested
- synced research materials in `deltascout/research_material/`
- one analyst-facing final compact markdown summary for the same date range
- one standard local research bundle ready for analyst or LLM handoff

This runbook is the master workflow above:
1. `agent_rebuild_date_range_prompt.md`
2. `agent_analyze_materials_prompt.md`
3. `agent_summary_promt.md`
4. `agent_step4_hend.md`

Use this runbook when the user wants an end-to-end research package ready for analyst review or handoff to a stronger LLM.

Important:
- Do NOT change code, tests, docs, or pipeline files
- Do NOT restart watchers
- Do NOT touch `/opt/aitrader` scripts or config
- Stop on the first blocking failure
- Do not silently skip a stage that is required by the chosen mode

Parameters (must be explicit):
- `DATE_FROM` - first UTC date, inclusive, `YYYY-MM-DD`
- `DATE_TO` - last UTC date, inclusive, `YYYY-MM-DD`
- `MODE` - one of:
  - `full_rebuild`
  - `sync_only`
  - `summary_only`

Mode semantics:

1. `full_rebuild`
- Rebuild the full date range on the server
- Sync all resulting artifacts to the local repo
- Produce the final compact summary markdown for the same date range
- Build the standard research bundle from the currently available local review folders

2. `sync_only`
- Do not rebuild
- Verify server artifacts already exist for the full date range
- Sync all artifacts to the local repo
- Produce a concise pre-summary
- Do not produce the final compact summary unless the user explicitly asks for it
- Do not run the standard bundle step

3. `summary_only`
- Do not rebuild
- Do not sync from server
- Use only the already present local files in `deltascout/research_material/`
- Produce the final compact summary markdown for the full date range
- Build the standard research bundle from the currently available local review folders

If the user does not provide:
- a date range: ask before proceeding
- a mode: default to `full_rebuild` only if the user explicitly asked for a rebuild; otherwise default to `sync_only`

Server access:
- `ssh -F NUL root@95.216.139.172`

Server runtime root:
- `/root/volume-alert`

Local repo root:
- `D:\Project_V\btc-orderflow-system`

---

Workflow

Stage 1. Rebuild range when mode is `full_rebuild`

Execute the logic from:
- `deltascout/research_material/runbooks/agent_rebuild_date_range_prompt.md`

Apply it to every date from `DATE_FROM` through `DATE_TO`, inclusive.

Requirements:
- run the documented 4-step pipeline exactly as written
- stop on first failure
- after success, verify all expected outputs exist on the server
- sync all outputs to local repo

If Stage 1 fails:
- stop immediately
- return the failure in the same structure as the rebuild runbook
- do not continue to Stage 2, Stage 3, or Stage 4

If Stage 1 succeeds:
- continue automatically to Stage 2 using the same date range

Stage 2. Sync and prepare pre-summary when mode is `full_rebuild` or `sync_only`

Execute the logic of:
- `deltascout/research_material/runbooks/agent_analyze_materials_prompt.md`

But adapt it from "latest processed date" to the explicit range:
- `DATE_FROM` through `DATE_TO`

For every date in the range:
- verify the expected server artifacts exist
- copy them into the correct local `research_material` folders
- verify copied files exist and are non-empty

Then prepare a concise range-level pre-summary:
- accepted counts per date
- reject counts per date
- interesting reject counts per date
- whether any accepted-to-close join exists
- dominant interesting buckets/rule_ids
- dominant reject reasons visible from daily summaries
- whether raw archive/feed are synced locally
- whether the local package is ready for deeper analysis

If Stage 2 fails:
- stop immediately
- do not continue to Stage 3 or Stage 4

If mode is `sync_only`:
- stop after Stage 2
- do not create the final compact summary markdown
- do not run the standard bundle step

If Stage 2 succeeds and mode is `full_rebuild`:
- continue automatically to Stage 3

Stage 3. Final compact summary when mode is `full_rebuild` or `summary_only`

Execute the logic from:
- `deltascout/research_material/runbooks/agent_summary_promt.md`

Use only the latest local artifacts under:
- `deltascout/research_material/reviews`

Apply the summary prompt to:
- `DATE_FROM` through `DATE_TO`

The output must be one markdown file only.

Filename rule:
- `reviews_DATE_FROM_to_DATE_TO_final_research_review.md`

Required contents:
- compact batch summary
- analytical memo
- all required claim discipline and case-comparison sections defined in the summary prompt

If Stage 3 fails:
- report the failure clearly
- preserve Stage 1 and Stage 2 outputs
- do not continue to Stage 4

If Stage 3 succeeds:
- continue automatically to Stage 4 when mode is `full_rebuild` or `summary_only`

Stage 4. Standard research bundle when mode is `full_rebuild` or `summary_only`

Execute the logic from:
- `deltascout/research_material/runbooks/agent_step4_hend.md`

Important adaptation rule:
- do not force `DATE_FROM` / `DATE_TO` onto this stage
- this stage must discover the currently available local daily review folders automatically from `deltascout/research_material/reviews`
- use the discovered earliest and latest dates for artifact filenames

Expected outputs from Stage 4:
1. `reviews_<START>_to_<END>_final_research_review.md`
2. `reviews_<START>_to_<END>_index_summary.csv`
3. `selected_case_sequence_context_<START>_to_<END>.csv`
4. `selected_case_raw_feed_micro_<START>_to_<END>.csv`

If Stage 4 fails:
- report the failure clearly
- preserve Stage 1, Stage 2, and Stage 3 outputs

---

Return structure

1. Requested mode and range
- mode
- date range
- whether all needed inputs were present

2. Stage 1 rebuild
- skipped or executed
- per-date status if executed
- first blocker if failed

3. Stage 2 sync and pre-summary
- skipped or executed
- per-date sync status if executed
- package readiness assessment

4. Stage 3 final summary
- skipped or executed
- exact output markdown path if created
- whether final summary is ready for analyst/LLM handoff

5. Stage 4 standard bundle
- skipped or executed
- exact output paths if created
- discovered local scope used by the bundle
- whether the bundle is ready for analyst/LLM handoff

6. Blockers or anomalies
- missing inputs
- pipeline failure
- missing synced files
- empty files
- low coverage warnings
- bundle-generation failure
- anything that weakens confidence in the final package

Rules:
- stop on first blocking failure
- keep date range explicit for Stages 1 to 3
- do not infer "latest" unless the mode explicitly says latest and the user asked for latest
- do not rebuild outside the requested range
- Stage 4 must use filesystem-discovered local review folders rather than a forced date list
- do not create extra files outside the artifacts required by the stage being executed
