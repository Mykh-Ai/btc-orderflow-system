# DeltaScout Research Bundle Spec v0.3

## 1. Purpose

This spec defines the implementation contract for the DeltaScout research bundle package.

It specifies:

- CLI contract
- filesystem contract
- artifact contract
- selection/annotation boundaries
- degraded-output rules
- failure semantics

This spec applies only to the research/materialization layer.

It does not define:

- live trading logic
- signal rules
- backtester rules
- permanent research truth

---

## 2. Design Principle

The package must:

> materialize evidence, derived context, and bounded annotations

The package must not:

> encode current research interpretation as immutable truth

Implications:

- annotations are allowed
- annotations must remain bounded and revisable
- memo-derived labels must not be promoted into truth claims
- missingness must remain explicit

---

## 3. CLI Contract

### Primary command

Suggested canonical entrypoint:

```bash
python -m deltascout.research_bundle.build_bundle --input-root <PATH> --output-root <PATH>
```

### Required arguments

- `--input-root`
- `--output-root`

### Optional arguments

- `--raw-feed-root`
- `--raw-archive-root`
- `--memo-root`
- `--include-blocker-breakdown`
- `--manifest-path`
- `--max-selected-cases`

### CLI behavior

The command must:

1. discover scope automatically from `input-root`
2. build the standard bundle artifacts
3. build manifest on every successful base run
4. optionally build blocker breakdown when enabled and possible
5. fail clearly on blocking input absence
6. preserve degraded-but-honest output for partial non-blocking coverage

### Determinism rule

Given the same discovered input files and the same CLI arguments, the builder must produce the same selected-case set and the same artifact scope.

---

## 4. Filesystem Contract

### Canonical input roots

Primary input root:

the local-only DeltaScout reviews workspace

Optional input roots:

- local raw feed workspace
- local raw archive workspace
- local DeltaScout research materials workspace
- local review folders
- memo/handoff docs under local research material if explicitly consumed

### Canonical output root

Bundle artifacts must be written to one explicit output root.

Suggested default:

the local-only DeltaScout bundle workspace

Within that root, one bundle run should write a single scope-specific folder or a consistent scope-specific file set.

Example:

the local-only bundle output folder for `<START>_to_<END>`

This is preferred over scattering outputs across unrelated folders.

### Scope discovery

Scope must be discovered only from valid date-like daily folders under:

`input-root`

Rules:

- include all valid daily folders
- sort ascending
- derive `scope_start`
- derive `scope_end`
- derive `bundle_scope_id`

Suggested `bundle_scope_id` form:

`<START>_to_<END>`

If no valid daily folders exist:

- fail clearly
- produce no artifacts

---

## 5. Standard Output Set

### Required outputs

1. `reviews_<START>_to_<END>_final_research_review.md`
2. `reviews_<START>_to_<END>_index_summary.csv`
3. `selected_case_sequence_context_<START>_to_<END>.csv`
4. `selected_case_raw_feed_micro_<START>_to_<END>.csv`
5. `research_bundle_manifest.csv`

### Optional output

6. `selected_case_blocker_breakdown_<START>_to_<END>.csv`

This artifact is experimental and must not be required for base bundle success.

---

## 6. Artifact Contract

### Artifact 1: Final Research Review Markdown

#### Mandatory inputs

- discovered daily review folders
- enough daily review artifacts for batch synthesis

#### Optional inputs

- index summary
- sequence context
- raw micro
- memos
- handoff docs

#### Rules

- may build without all optional enrichments
- must explicitly acknowledge missing depth
- must not imply confidence unsupported by files

### Artifact 2: Index Summary CSV

#### Mandatory inputs

- discovered daily review folders
- enough daily artifacts to extract core per-day counts and distributions

#### Optional inputs

- close outcomes
- accepted-case close reason
- richer daily flags

#### Rules

- unavailable fields remain blank
- whole bundle should not fail unless core per-day summarization is impossible

### Artifact 3: Selected Case Sequence Context CSV

#### Mandatory inputs

- selected cases
- enough local review/event context to construct sequence rows for at least some cases

#### Optional inputs

- memo-linked annotations
- richer linkage metadata

#### Rules

- partial coverage is allowed
- blanks must remain honest
- manifest must reflect missing sequence coverage

### Artifact 4: Selected Case Raw Feed Micro CSV

#### Mandatory inputs

- selected cases
- local raw feed coverage for at least some selected timestamps

#### Optional inputs

- full coverage for all selected cases

#### Rules

- include only covered rows
- do not fabricate placeholder rows
- manifest must record missing raw micro coverage

### Artifact 5: Manifest CSV

#### Mandatory inputs

- always required on successful base run

#### Rules

- must always be produced when base bundle succeeds
- must be machine-readable
- must represent completeness/partiality status

### Artifact 6: Blocker Breakdown CSV

#### Mandatory inputs

- none for base success

#### Rules

- build only when enough information exists for best-effort reconstruction
- must distinguish:
  - `fully_reconstructed`
  - `partially_reconstructed`
  - `not_reconstructable`
- no fake precision

---

## 7. Artifact Schemas

### 7.1 Index Summary Minimum Schema

Required columns:

- `date`
- `accepted_count`
- `reject_count`
- `interesting_reject_count`
- `close_outcome_count`
- `top_reject_reason_1`
- `top_reject_reason_1_count`
- `top_reject_reason_2`
- `top_reject_reason_2_count`
- `top_reject_reason_3`
- `top_reject_reason_3_count`
- `dominant_bucket_1`
- `dominant_bucket_1_count`
- `dominant_bucket_2`
- `dominant_bucket_2_count`
- `has_accepted`
- `has_close_outcome`
- `accepted_case_ts`
- `accepted_case_kind`
- `accepted_case_close_reason`
- `dominant_side_reject_bias`
- `contains_vwap_side_rejects`
- `contains_direction_mismatch_rejects`
- `contains_3of3_fail_rejects`
- `contains_possible_reversal_onset`
- `contains_possible_reversal_confirmation`
- `contains_possible_continuation_pressure`
- `contains_possible_trap_or_false_break`
- `notes_flag`

Boolean-like fields must use only `yes` / `no`.

### 7.2 Sequence Context Minimum Schema

Required columns:

- `target_ts`
- `session_date`
- `ts`
- `minutes_from_target`
- `is_target_case`
- `event_type`
- `kind`
- `reject_reason`
- `interesting_reject_bucket`
- `rule_id`
- `price`
- `price_vs_vwap_side`
- `cum_delta_60m`
- `cum_delta_180m`
- `ret_15m`
- `ret_60m`
- `same_side_as_target`
- `later_same_side_event_in_window`
- `later_same_side_accepted_in_window`
- `later_same_side_stronger_reject_in_window`

Optional annotation columns:

- `family_lane`
- `family_subtype_candidate`
- `cluster_id`
- `cluster_role`
- `visible_blocker_status`
- `research_priority`
- `reference_doc`
- `reference_section`
- `assignment_basis`
- `assignment_confidence`
- `selected_case_source`

### 7.3 Raw Feed Micro Minimum Schema

Required columns:

- `target_ts`
- `Timestamp`
- `minutes_from_target`
- `Close`
- `VWAP`
- `BuyQty`
- `SellQty`
- `OpenInterest`
- `FundingRate`
- `LiqBuyQty`
- `LiqSellQty`
- `IsSynthetic`
- `delta_1m`
- `vol_1m`
- `price_minus_vwap`

Recommended additional metadata:

- `selected_case_source`

### 7.4 Blocker Breakdown Minimum Schema

Required columns:

- `ts`
- `kind`
- `reject_reason`
- `price_vs_vwap_side`
- `prev_candidate_price_check`
- `prev_candidate_vol_check`
- `prev_candidate_vwap_check`
- `three_of_three_pass_count`
- `decomposition_status`
- `notes_short`

### 7.5 Manifest Minimum Schema

Required columns:

- `bundle_version`
- `spec_version`
- `bundle_scope_id`
- `bundle_built_at`
- `input_root`
- `output_root`
- `scope_start`
- `scope_end`
- `daily_folder_count`
- `review_memo_present`
- `index_summary_present`
- `sequence_context_present`
- `raw_feed_micro_present`
- `blocker_breakdown_present`
- `review_markdown_status`
- `index_summary_status`
- `sequence_context_status`
- `raw_feed_micro_status`
- `blocker_breakdown_status`
- `selected_case_count`
- `missing_raw_micro_case_count`
- `missing_sequence_case_count`
- `partial_coverage_flag`
- `notes`

Allowed artifact status values:

- `complete`
- `partial`
- `missing`

---

## 8. Layer Separation

Implementation must separate:

1. scope discovery
2. case selection policy
3. artifact builders
4. optional annotation layer

Builders may consume annotations, but must not require them unless explicitly part of that artifact's contract.

---

## 9. Case Selection Contract

Case selection must be a separate layer from artifact building.

### Purpose

Select a bounded high-value case set for:

- sequence context
- raw micro
- optional blocker breakdown

### Default priorities

Prefer:

- accepted reference cases
- short-side rejects
- `vwap_side`
- `3of3_fail`
- `direction_mismatch`
- same-session clusters
- paradox cases
- memo-highlighted cases when memos are present

### Suggested selection output

- `target_ts`
- `reason_selected`
- `selection_priority`
- `source_basis`
- `selected_case_source`

Suggested `selected_case_source` values:

- `auto_priority`
- `memo_highlight`
- `accepted_reference`
- `paradox_case`

---

## 10. Annotation Contract

### Allowed annotations

Examples:

- `family_lane`
- `family_subtype_candidate`
- `cluster_id`
- `cluster_role`
- `visible_blocker_status`
- `research_priority`
- `reference_doc`
- `reference_section`

### Required caution fields

When annotation fields are present, support:

- `assignment_basis`
- `assignment_confidence`

Allowed values example:

#### `assignment_basis`

- `memo_reference`
- `sequence_pattern`
- `event_fields_only`
- `manual_context`
- blank

#### `assignment_confidence`

- `supported`
- `tentative`
- `weak`
- blank

### Rule

If basis/confidence cannot be justified, leave annotation blank.

Memos and handoff docs may influence case prioritization and bounded annotations, but must not be the sole source for artifact rows that claim event-level structural facts.

---

## 11. Degraded Output Semantics

### Acceptable degraded behavior

- build index summary even if raw micro is partial
- build sequence context even if some selected cases have weak neighborhood coverage
- build markdown review with explicit missing-evidence notes
- build manifest with partial flags

### Unacceptable degraded behavior

- invent rows
- fabricate decomposition
- silently hide missing coverage
- silently convert tentative interpretation into fact

---

## 12. Failure Semantics

### Hard failure

The builder must fail and produce no bundle when:

- no valid daily review folders are discovered
- core review artifacts are insufficient to build both:
  - index summary
  - review markdown

### Partial success

The builder may succeed with degraded coverage when:

- raw feed exists only for some selected cases
- sequence context is partial but non-empty
- blocker breakdown is unavailable
- optional memos are absent

### Failure reporting

Failure output must state:

- what input class was missing
- which artifact was blocked
- whether failure was total or partial
- what artifacts, if any, were still produced

---

## 13. Scope Consistency Rule

All artifacts produced by one base bundle run must share the same discovered scope in filename and manifest.

If an artifact is built on a narrower or wider scope, that must be treated as either:

- a separate run
- or explicitly marked as `scope-deviant` in the manifest

Mixed-scope bundles must not be emitted silently.

---

## 14. Success Criteria

A base bundle build succeeds when:

1. scope is auto-discovered
2. review markdown is built
3. index summary is built
4. sequence context is built
5. raw micro is built for covered cases
6. manifest is built
7. all missingness is represented honestly

Blocker breakdown is not required for base success.

---

## 15. Non-Functional Requirements

### Core non-functional requirements

#### 1. Deterministic outputs

Given the same discovered inputs and the same CLI arguments, the package must produce:

- the same scope
- the same selected-case set
- the same output filenames
- the same manifest status fields

#### 2. Honest degraded behavior

The package must never fabricate:

- rows
- annotations
- decomposition

The package must never hide, fill, or imply missing coverage as present.

Partial outputs are allowed only when:

- they are explicitly marked as partial
- missingness is visible in artifact content and manifest

#### 3. Strict separation from live logic

The package must not:

- modify live DeltaScout logic
- modify analyzer runtime behavior
- modify server watcher behavior
- change live decision rules
- alter signal-generation semantics

#### 4. Schema/version stability

Artifact schemas must remain stable by default.

If schema changes are introduced:

- they must be versioned
- they must be reflected in manifest/spec version
- they must not silently break downstream usage

The manifest must include at minimum:

- `spec_version`
- `bundle_version`

### Additional non-functional requirements

#### 5. Additive-only implementation

Implementation must remain a small additive research package, not a broad refactor of unrelated systems.

#### 6. Small-scope failure

Failure in one optional artifact must not fail the whole base bundle if base success criteria still hold.

#### 7. Clear failure reporting

Failure output must clearly state:

- which input class was missing
- which artifact failed
- whether failure was total or partial
- what was still produced

#### 8. Filesystem clarity

All outputs from one bundle run must:

- live under one explicit output root
- use one consistent scope
- be easy to locate without guesswork

#### 9. Low operator ambiguity

A human or agent should not need to guess:

- where outputs were written
- whether the bundle is complete
- which artifact is partial
- what remains missing

#### 10. Bounded annotation

The annotation layer must remain explicitly tentative where evidence is weak.
Memo-derived labels must never become silent truth.

#### 11. Inspectability

Artifacts must be easy to inspect with ordinary tools:

- CSV open
- markdown open
- no specialized internal tooling required to understand bundle status

#### 12. No architecture bloat

The implementation must stay narrow, additive, and easy to reason about.

### Highest-priority NFRs

- deterministic outputs
- honest degraded behavior
- schema/version stability
- strict separation from live logic
## 16. Non-Goals

This package does not authorize:

- live signal logic changes
- threshold loosening
- family promotion into production logic
- ontology as truth
- broad refactor without need

---

## 17. Implementation Stance

Preferred implementation style:

- small additive package
- narrow builders
- explicit contracts
- deterministic selection
- honest missingness
- no ontology overreach
