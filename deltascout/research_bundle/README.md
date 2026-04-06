# DeltaScout Research Bundle

`deltascout.research_bundle` is the local research bundle package for DeltaScout.

Its purpose is to build a deterministic, scope-bound research bundle from already synced local review materials.

This package is part of the research/materialization layer only.
It does not modify:

- live DeltaScout logic
- analyzer runtime behavior
- server watcher behavior
- signal-generation rules

---

## Canonical CLI

```bash
python -m deltascout.research_bundle.build_bundle --input-root deltascout/research_material/reviews --output-root deltascout/research_material/bundles --raw-feed-root deltascout/research_material/raw_feed
```

Optional selection cap:

```bash
python -m deltascout.research_bundle.build_bundle --input-root deltascout/research_material/reviews --output-root deltascout/research_material/bundles --raw-feed-root deltascout/research_material/raw_feed --max-selected-cases 12
```

---

## Inputs

Required:

- local daily review folders under `deltascout/research_material/reviews`

Optional / stage-dependent:

- local raw feed under `deltascout/research_material/raw_feed`

Scope is discovered automatically from valid date-like folders under the input root.

---

## Output layout

Bundle artifacts are written under the chosen output root using the discovered scope:

- `deltascout/research_material/bundles/<START>_to_<END>/`

Current bundle outputs:

- `reviews_<START>_to_<END>_index_summary.csv`
- `selected_cases_<START>_to_<END>.csv`
- `selected_case_sequence_context_<START>_to_<END>.csv`
- `selected_case_raw_feed_micro_<START>_to_<END>.csv`
- `research_bundle_manifest.csv`

---

## Current bundle stages

### P1

- scope discovery
- index summary
- manifest

### P2

- deterministic selected cases
- minimum viable sequence context

### P3

- raw micro extract for selected cases

Not implemented yet:

- blocker breakdown / reconstruction layer
- full review markdown builder in this package
- annotation-heavy enrichment layer

---

## Partial success semantics

The bundle may succeed with partial coverage.

Examples:

- sequence context exists but some selected cases have weak context
- raw micro exists only for part of the selected set

Rules:

- no fake rows
- no fake linkage
- no fake decomposition
- missingness must remain visible in artifacts and manifest

---

## Manifest meaning

`research_bundle_manifest.csv` is the machine-readable status layer.

Key fields to inspect:

- `bundle_scope_id`
- `selected_case_count`
- `selected_cases_status`
- `sequence_context_status`
- `raw_feed_micro_status`
- `missing_sequence_case_count`
- `missing_raw_micro_case_count`
- `partial_coverage_flag`

Status meanings:

- `complete` = artifact exists and is usable for the current bundle stage
- `partial` = artifact exists but coverage is incomplete
- `missing` = artifact is absent or not built

---

## Determinism

Given the same discovered inputs and the same CLI arguments, the package is expected to keep stable:

- discovered scope
- selected-case set
- artifact filenames
- sequence/raw row ordering

`bundle_built_at` in the manifest changes across reruns and is expected to differ.

---

## Workflow position

Typical workflow:

1. watcher completes on the server
2. local review materials are synced
3. bundle builder runs locally
4. manifest is checked
5. analyst or LLM uses:
   - index summary
   - selected cases
   - sequence context
   - raw micro

For operator flow after watcher, see:

- `deltascout/research_material/runbooks/after_watcher_to_llm.md`