# DeltaScout Research Context

## Current Working Context

- Active branch: `research`
- Main focus: building the DeltaScout research and analytics layer
- Goal: expand and analyze the candidate funnel around DeltaScout so future `PEAK_EMIT` count can grow without obvious quality loss

This work is not about replacing the current strict `PEAK_EMIT` logic. The current task is to understand:

- which candidate events are being rejected
- which metrics and filters dominate the funnel
- where future expansion ideas should be tested
- how to build an analysis layer around archived DeltaScout decisions

Phase 2 (backward-looking event context) has been validated. Phase 2.5 review-package outputs now exist and are the primary daily analysis surface when present.

## What DeltaScout Already Produces

Runtime research events are written by DeltaScout into a separate research archive.

Important event types:

- `DELTA_MAX`
- `DELTA_MIN`
- `CANDIDATE_COMPARISON_REJECT`
- `CANDIDATE_GATE_REJECT`
- `PEAK_EMIT`

Primary operational close-outcomes source:

- `/data/state/trade_outcomes.jsonl`

Primary research archive path in the server project layout:

- `/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl`

Matching feed archive path:

- `/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv`

Derived dataset output path:

- `/data/archive/datasets/`

## Current Research Direction

The near-term focus is the reject funnel, especially:

- comparison-stage rejects
- very low gate-reject frequency
- identifying metrics that may allow future PEAK expansion without obvious quality collapse

The early copied sample showed meaningful `CANDIDATE_COMPARISON_REJECT` coverage and almost no `CANDIDATE_GATE_REJECT`. The sample now includes at least one `PEAK_EMIT`, so accepted-event review should no longer be ignored completely.

This does not make current PEAK the center of the research program. Current PEAK remains a reference class, not the boundary of thinking.

Primary research framing should remain:

- market state
- transition
- setup-class discovery
- entry-timing implications

Accepted-event review should be treated as one input into broader market-behavior research, not as the sole priority. It does not replace reject-funnel analysis, and it does not justify collapsing the research program into PEAK-only thinking.

When Phase 2.5 review-package outputs are available, the recommended working order is:

1. `daily_review_summary_YYYY-MM-DD.md` — start here for the day's picture
2. `accepted_event_context_YYYY-MM-DD.csv` — accepted-event rows with Phase 2 context attached
3. `reject_event_context_YYYY-MM-DD.csv` — reject rows with context for funnel analysis
4. `raw_archive/` and `raw_feed/` — secondary sources for drill-down, anomaly checks, or deeper sequence/transition analysis

Raw archive and feed files are not obsolete. They remain the authoritative sources for any interpretation that requires full event sequences or transition-level context that derived outputs do not expose.

The first analysis modules should focus on:

- archive coverage and archive health
- reject-reason distribution
- comparison-stage bottlenecks
- joins between decision timestamps and same-day feed context
- accepted-event to close-outcome review where accepted rows exist
- comparing accepted context versus same-day reject context

## Local Research Material

The first copied working material is stored here:

- `deltascout/research_material/`

Current contents:

- `raw_archive/` — copied DeltaScout archive JSONL files
- `raw_feed/` — copied feed CSV files for the same dates
- `2026-03-16_to_2026-03-20_initial_findings.md`

Phase 2.5 review-package outputs (derived analyzer artifacts, present when Phase 2.5 has been run for a date):

- `accepted_event_context_YYYY-MM-DD.csv` — accepted events with backward-looking Phase 2 context attached
- `reject_event_context_YYYY-MM-DD.csv` — reject events with backward-looking Phase 2 context attached
- `daily_review_summary_YYYY-MM-DD.md` — human-readable daily review summary

When Phase 2.5 outputs exist for a date, treat them as the primary daily research artifacts. Use raw archive and raw feed for drill-down, anomaly checks, or deeper sequence/transition analysis that derived outputs do not expose.

When future agents inspect early research state, this folder should be treated as the starting material set.

## Core Research Documents

Read these documents before proposing analyzer design, research priorities, or PEAK-family expansion:

- `deltascout/research_material/research_manifesto.md`
- `deltascout/research_material/delta_analyzer_implementation_plan_v1_1.md`
- `deltascout/research_material/2026-03-16_to_2026-03-20_initial_findings.md`

## Server Workflow

Server:

- `root@95.216.139.172`

Research code and data root on server:

- `/root/volume-alert`

Known working Python environment on server:

- `/opt/aitrader/.venv/bin/python`

Important deployment note:

- offline DeltaScout builders and research data currently live under `/root/volume-alert`
- the currently working Python environment with `pandas` may live outside that tree
- if `/root/volume-alert/.venv` is missing, run builders from `/root/volume-alert` with `PYTHONPATH=/root/volume-alert` and `/opt/aitrader/.venv/bin/python`

If local Windows SSH config causes permission issues, use:

- `ssh -F NUL root@95.216.139.172`

## Common Server Commands

Connect:

```bash
ssh -F NUL root@95.216.139.172
cd /root/volume-alert
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python --version
```

Quick environment check:

```bash
/opt/aitrader/.venv/bin/python --version
/opt/aitrader/.venv/bin/python -c "import pandas; print(pandas.__version__)"
```

List DeltaScout archive files:

```bash
ls -1 /root/volume-alert/data/archive/deltascout
```

List feed archive files:

```bash
ls -1 /root/volume-alert/data/archive/feed
```

Inspect one research archive file:

```bash
head -n 20 /root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl
tail -n 20 /root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl
```

Rebuild offline datasets after a close date:

```bash
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python -m scripts.offline.build_phase1_derived --date YYYY-MM-DD --input-root /root/volume-alert/data --output-root /root/volume-alert/data/archive/datasets
PYTHONPATH=/root/volume-alert /opt/aitrader/.venv/bin/python -m scripts.offline.build_close_outcomes --date YYYY-MM-DD --input-root /root/volume-alert/data --output-root /root/volume-alert/data/archive/datasets
```

Check produced datasets:

```bash
ls -lh /root/volume-alert/data/archive/datasets | tail -n 20
```

## Deployment and Git Rules

- Work primarily in branch `research`
- Server deployment should include only codebase/runtime-relevant changes
- Do not deploy tests to the server
- Avoid bundling unrelated local artifacts into commits

## Working Principles for Future Agents

- Preserve separation between live bus, research archive, and offline datasets
- Prefer additive instrumentation and analysis over broad refactors
- When making research claims, anchor them to copied archive material or server inspection
- If the next step is analytics, start from the reject funnel and event coverage before inventing strategy changes
- When useful, copy raw server material into `deltascout/research_material/` before designing analysis code
- When Phase 2.5 review-package outputs exist, start daily analysis from `daily_review_summary` before opening raw archive files
- Accepted-event review is a legitimate input when accepted rows exist; it is not the primary directive and does not override reject-funnel analysis or the core market-state → transition → setup-class framing

## Recommended Next Work

Good next tasks for future agents:

- use Phase 2.5 review-package outputs as the primary daily analysis surface when present
- continue reject-funnel analysis: summarize reject reasons by day and by event kind
- review accepted-event rows and compare their context against same-day reject context where accepted rows exist
- join reject timestamps with feed context from `raw_feed/` for transition-level interpretation
- identify which pre-gate constraints are most likely suppressing future PEAK growth
- use repeated review-package outputs across multiple days to decide what later layers are justified before building them

Not yet justified based on current data:

- broad market-state engine or full setup taxonomy
- profitability conclusions from sparse accepted-flow samples
- live logic changes
- PEAK-centric research framing that treats accepted-event review as the sole or primary research objective
