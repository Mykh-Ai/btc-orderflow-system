# DeltaScout Local Runbooks

Use this folder through two normal entrypoints.

## Normal Entry Points

- `RUN_AGENT_RESEARCH_WORKFLOW.md`
  - Use for sync, rebuild, covering missing days, dataset materialization, M2.6, bundle creation, and project log updates.
- `RUN_LLM_RESEARCH_ANALYSIS.md`
  - Use for interpretation after the package is ready.

## Reference

- `post_close_watcher.md`
  - Server watcher reference. Usually not a manual prompt.

## Deprecated Stage Prompts

Old stage prompts have been moved to `deprecated/`.

They are kept for traceability, but the user should not need to decide between them manually.

The old prompt family was:

- latest sync
- date-range rebuild
- full handoff
- final summary
- bundle handoff
- LLM analysis

That routing is now collapsed into:

1. run `RUN_AGENT_RESEARCH_WORKFLOW.md` to prepare materials;
2. run `RUN_LLM_RESEARCH_ANALYSIS.md` to interpret materials.
