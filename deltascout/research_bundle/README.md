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
python -m deltascout.research_bundle.build_bundle --input-root <local-reviews-root> --output-root <local-bundles-root> --raw-feed-root <local-raw-feed-root>
```

Optional selection cap:

```bash
python -m deltascout.research_bundle.build_bundle --input-root <local-reviews-root> --output-root <local-bundles-root> --raw-feed-root <local-raw-feed-root> --max-selected-cases 12
```

Setup discovery surface:

```bash
python -m deltascout.research_bundle.build_setup_candidates --review-root <local-reviews-root> --minute-dataset-root <local-minute-datasets-root> --output-root <local-output-root>
```

Setup cluster review:

```bash
python -m deltascout.research_bundle.build_setup_cluster_review --setup-candidates <setup_candidates_SCOPE.csv> --output-root <local-output-root>
```

Top cluster quantitative pre-review:

```bash
python -m deltascout.research_bundle.build_top_cluster_manual_review --cluster-review <setup_cluster_review_SCOPE.csv> --setup-candidates <setup_candidates_SCOPE.csv> --accepted-ledger <accepted_outcome_ledger_SCOPE.csv> --minute-dataset-root <local-minute-datasets-root> --output-root <local-output-root>
```

Move-first research windows:

```bash
python -m deltascout.research_bundle.build_move_first_windows --review-root <local-reviews-root> --minute-dataset-root <local-minute-datasets-root> --output-root <local-output-root>
```

Fast-money pre-impulse event-study table:

```bash
python -m deltascout.research_bundle.build_fast_money_pre_impulse_table --review-root <local-reviews-root> --minute-dataset-root <local-minute-datasets-root> --output-root <local-output-root> --move-first <move_first_windows_SCOPE.csv>
```

Fast-money setup cases:

```bash
python -m deltascout.research_bundle.build_fast_money_setup_cases --pre-impulse-table <fast_money_pre_impulse_table_SCOPE.csv> --output-root <local-output-root>
```

---

## Inputs

Required:

- local daily review folders under the local-only DeltaScout research workspace

Optional / stage-dependent:

- local raw feed under the local-only DeltaScout research workspace

Scope is discovered automatically from valid date-like folders under the input root.

---

## Output layout

Bundle artifacts are written under the chosen output root using the discovered scope:

- a local-only bundle folder for `<START>_to_<END>`

Current bundle outputs:

- `reviews_<START>_to_<END>_index_summary.csv`
- `selected_cases_<START>_to_<END>.csv`
- `selected_case_sequence_context_<START>_to_<END>.csv`
- `selected_case_raw_feed_micro_<START>_to_<END>.csv`
- `research_bundle_manifest.csv`

Setup discovery outputs:

- `setup_candidates_<START>_to_<END>.csv`
- `setup_candidates_<START>_to_<END>_summary.md`
- `setup_cluster_review_<START>_to_<END>.csv`
- `setup_cluster_review_<START>_to_<END>.md`
- `top_cluster_manual_review_<START>_to_<END>.csv`
- `top_cluster_manual_review_<START>_to_<END>.md`
- `move_first_windows_<START>_to_<END>.csv`
- `move_first_windows_<START>_to_<END>.md`
- `fast_money_pre_impulse_table_<START>_to_<END>.csv`
- `fast_money_pre_impulse_table_<START>_to_<END>_summary.md`
- `fast_money_setup_cases_<START>_to_<END>.csv`
- `fast_money_setup_cases_<START>_to_<END>_summary.md`

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

### Setup Discovery

- move-first research windows built from market movement before detector annotations
- accepted PEAK lifecycle reference rows
- M2.6 chain candidates with `$1000+` directional movement potential
- rejected-family candidates with `$1000+` follow-through
- lifecycle-aware comparison surface for future setup-class validation
- cluster review that groups setup-candidate rows into time-local candidate setup clusters
- first-pass quantitative pre-review of top clusters with entry proxy, favorable/adverse move, $1000 hit timing, and AI_EMIT lesson
- fast-money pre-impulse table with earliest/best move-first proxies, M2.6 density/context, reject/PEAK proximity, stop survival, $500/$1000 hit timing, and candidate-family labels
- fast-money setup cases that deduplicate proxy rows into one case per move cluster and assign quality class, repeatability family, review priority, and representative entry proxy

Not implemented yet:

- reconstruction layer
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

- local-only runbook placeholders in the private DeltaScout runbook area
