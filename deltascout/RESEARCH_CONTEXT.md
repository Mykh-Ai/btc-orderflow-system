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

At the moment, the early copied sample showed:

- meaningful `CANDIDATE_COMPARISON_REJECT` coverage
- almost no `CANDIDATE_GATE_REJECT`
- no `PEAK_EMIT` in the sampled days

That means the first analysis modules should focus on:

- archive coverage and archive health
- reject-reason distribution
- comparison-stage bottlenecks
- joins between decision timestamps and same-day feed context

Do not assume accepted-signal analytics is the first priority unless new archive coverage shows otherwise.

## Local Research Material

The first copied working material is stored here:

- `deltascout/дослідницький матеріал/`

Current contents:

- `raw_archive/` copied DeltaScout archive JSONL files
- `raw_feed/` copied feed CSV files for the same dates
- `2026-03-16_to_2026-03-19_initial_findings.md`

When future agents inspect early research state, this folder should be treated as the starting material set.

## Core Research Documents

Future agents should read these documents before proposing analyzer design changes:

- `deltascout/дослідницький матеріал/research_manifesto.md`
- `deltascout/дослідницький матеріал/delta_analyzer_implementation_plan_v1.md`
- `deltascout/дослідницький матеріал/2026-03-16_to_2026-03-19_initial_findings.md`

## Server Workflow

Server:

- `root@95.216.139.172`

Project root on server:

- `/root/volume-alert`

Virtual environment:

- `source .venv/bin/activate`

If local Windows SSH config causes permission issues, use:

- `ssh -F NUL root@95.216.139.172`

## Common Server Commands

Connect:

```bash
ssh -F NUL root@95.216.139.172
cd /root/volume-alert
source .venv/bin/activate
```

Quick environment check:

```bash
python --version
python -c "import pandas; print(pandas.__version__)"
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
python scripts/offline/build_phase1_derived.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
python scripts/offline/build_close_outcomes.py --date YYYY-MM-DD --input-root /data --output-root /data/archive/datasets
```

Check produced datasets:

```bash
ls -lh /data/archive/datasets | tail -n 20
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
- When useful, copy raw server material into `deltascout/дослідницький матеріал/` before designing analysis code

## Recommended Next Work

Good next tasks for future agents:

- build a small archive-health and reject-analysis module
- summarize reject reasons by day and by event kind
- join reject timestamps with feed context from `raw_feed/`
- identify which pre-gate constraints are most likely suppressing future PEAK growth

Less urgent until more data appears:

- accepted-signal performance analytics
- outcome analytics tied to `PEAK_EMIT`
- pass-vs-reject comparative modeling
