# DeltaScout Local Research Materials

This directory is the local-only DeltaScout research workspace.

## Human Entry Points

Read these first:

1. `PROJECTLOG.md` - operational state, latest coverage, latest bundle, what to run next
2. `RESEARCHLOG.md` - curated research memory and durable conclusions

Do not start from random `reviews_*` or `bundles/*` files unless `PROJECTLOG.md` points there.

## Normal Prompts

Use only these prompts as normal entrypoints:

- `runbooks/RUN_AGENT_RESEARCH_WORKFLOW.md`
  - sync, rebuild, cover missing days, materialize datasets, build bundle, update logs
- `runbooks/RUN_LLM_RESEARCH_ANALYSIS.md`
  - interpret the latest package and decide research priorities

Older stage prompts are deprecated/reference material.

## Artifact Map

- `reviews/YYYY-MM-DD/` - per-day synced review and dataset artifacts
- `reviews/reviews_*final*.md` - batch review artifacts, not canonical memory
- `bundles/<START>_to_<END>/` - LLM/analyst handoff bundles
- `minute_datasets/` - local minute-event datasets and M2.6 artifacts
- `raw_archive/` - copied DeltaScout JSONL archive
- `raw_feed/` - copied enriched feed CSV files
- `runbooks/` - local workflow prompts and references
- `_tmp_*` - historical scratch material; do not treat as current state

## Public Repo Policy

- Treat this folder as local/private research material.
- Do not publish server hosts, SSH commands, absolute server paths, cron entries, or private operational prompts unless the user explicitly asks for a sanitized public version.

## Agent Routing

Agents must read:

1. repo-level `AGENTS.md`
2. `deltascout/research_material/AGENTS.md`
3. `PROJECTLOG.md`
4. `RESEARCHLOG.md`

Then use the normal prompt that matches the task.
