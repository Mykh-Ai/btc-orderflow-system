# Hierarchical milestone decision on frozen Snapshot V2

Research only. This is a post-unblinding **development ablation** of the rejected direct-class predictor V1, not a new holdout and not a production change.

The input is the exact `frozen_model_view_snapshots.jsonl` committed in V1 blind checkpoint `0c740d094e53b8bc29dd35eb8041e7dfe5fe1011`. This experiment creates no replacement Snapshot V2 file and changes no Snapshot V2 feature, calculation, market cutoff, feed row, or quality flag. The same 20 trade keys receive one independent `gpt-5.6-sol` response each with medium reasoning, strict structured output, `store=false`, no tools/history, and no retries. The model-facing prompt contains none of the three lifecycle class names.

The prompt asks `TP1_FIRST` versus `SL_FIRST`, then, only after `TP1_FIRST`, `TP2_REACHED` versus `TP2_NOT_REACHED`. `UNCLEAR_MISSING_EVIDENCE` is allowed at either question only with a specific missing pre-outcome fact whose code appears in the frozen snapshot. Code maps the two milestone answers to the lifecycle class after the model response. The prompt and schema are in `milestone_prompt.py`; `prepare.py` verifies the committed Snapshot V2 bytes and freezes the 20 rendered prompts; `run.py` verifies all identities and records each `STARTED`, raw response, parsed/derived result, and `COMPLETED` without reading outcome files.

The pre-call [chronology audit](CHRONOLOGY_AUDIT.md) found an inconsistent timezone interpretation in `EX_EN_1779900918`. All 20 calls are made for paired inspection; the primary scored comparison excludes that case from **both** predictors. No frozen input is edited.

Blind call status: 20/20 completed with no transport or validation errors. The blind results are in `blind_run/`. Outcome comparison must be run only after the blind results are committed as a checkpoint; no outcome metric belongs in this pre-checkpoint document.
