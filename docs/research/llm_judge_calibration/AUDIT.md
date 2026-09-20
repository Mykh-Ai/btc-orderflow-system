# LLM Judge V1/V2 calibration research — canonical 39A input

**Research only, 2026-09-20.** Base: `6ee065272d01c7aafde21cf5395631d84a84267e` on `codex/canonical-39a-monitor-normalization`. This does not change the production prompt, model, tests, trading logic, Executor process, deployment, or historical verdicts. The branch remains WIP and is not a merge recommendation. The known prompt-contract test remains failing and unmasked.

## Evidence and the actual prompt eras

`git log -p -S '60m/240m extreme' -- executor_mod/llm_trade_judge.py` places the calibration wording in `b366e19` and its removal in `ae10ace` (2026-09-11). The last real pre-V2 production prompt is `ae10ace^:executor_mod/llm_trade_judge.py::build_llm_trade_judge_prompt`, not an invented `V1` version string. It received the full `evidence_pack`: `src_evt`, `market_context.deltascout`, `market_context.aggregated`, and an optional day-scoped `market_monitor_snapshot_v1`. The response schema constrained `setup_class` to nine values. The prompt explicitly warned about legacy local timestamps and future outcomes.

The current `LLM_ENTRY_PROMPT_V2` is `executor_mod/entry_snapshot.py::build_entry_prompt` at this branch head. It receives `LLM_ENTRY_SNAPSHOT_V2`: normalized cutoff, signal, upstream admission, planned execution geometry, `market.monitor_snapshot`, `market.context`, quality and lineage. This branch now requires the self-contained `market_monitor_snapshot_v39a` when the Judge is enabled; the historical September 14 V2 journal still contained v1 monitor evidence and cannot be treated as a valid current-canonical V2 observation. V2 supplies a JSON schema but its `setup_class` property is an unrestricted string. The local runtime still defaults `LLM_TRADE_JUDGE_MODEL` to `gpt-5.5`; this research does not alter it.

Journal records do not persist exact pre-V2 prompt hashes. Commit chronology therefore establishes source history, not which prompt revision every historical call actually used. The existing regression test preserves the old calibration requirements but fails after a valid canonical fixture is supplied; that is evidence of contract loss, not proof of V1 trading efficacy.

## Semantic diff and classification

| Pre-V2 instruction/concept | V2 treatment | Classification and decision |
| --- | --- | --- |
| Judge entry quality at normalized UTC cutoff; never use later outcomes or alter orders | Retained and clearer | **Anti-hindsight, useful.** Keep the boundary. Raw local-time workaround prose is obsolete once input is normalized. |
| `src_evt`, `market_context.deltascout/aggregated`, optional monitor paths | Replaced by entry snapshot | **Schema-specific obsolete wording.** Preserve source identity in data lineage, not old names in the prompt. |
| Repaired 37E `market_structure_state` distinguishes bearish expansion from range/support | No interpretation cue; canonical structure state is now explicit | **Useful market reasoning.** A nearby support band alone cannot establish a bullish regime. The exact 37E version wording is obsolete. |
| “SUPPORT means the bot side is favored” | “bot direction has a clear edge” | **Potential SUPPORT bias.** “Favored” can reward agreement with DeltaScout; no causal effect is established. |
| “UNCLEAR counts as reject-side in the game” | Removed | **Obsolete game framing, potential REJECT bias.** Do not restore in a production prompt. Preserve only in historical comparison arm B. |
| Weak/bad signal with sufficient evidence ⇒ REJECT; UNCLEAR only when edge cannot be assessed | Generic REJECT/UNCLEAR definitions | **Useful calibration.** Separate adverse evidence from unavailable or genuinely mixed evidence. V2 may overuse UNCLEAR, unproven. |
| SUPPORT requires clear, *fresh* edge after risk flags | “clear edge” | **Useful market reasoning.** Freshness and risk accounting disappeared; a mandatory numeric threshold would be unsupported. |
| Local momentum alone cannot justify SUPPORT for a late chase | Absent | **Useful anti-rubber-stamp question.** Assess location and remaining room; do not make every strong move a rejection. |
| Prefer REJECT at local 60m/240m extreme, weak PEAK, or immediate opposing zone | Absent | **Useful facts but potentially biased wording.** Location, PEAK strength and qualified opposing distance matter; the categorical preference could over-reject breakouts. |
| Prefer UNCLEAR on 1d/3d/7d conflict, degraded feed or mixed zones | Generic uncertainty sentence | **Useful uncertainty cues but potentially UNCLEAR bias.** Conflict and degradation are evidence to weigh, not automatic verdicts. |
| Lower confidence and explain SUPPORT despite several material risk flags | Absent | **Useful coherence check.** Confidence should match rationale; rigid lowering rule is unvalidated. |
| Report conflict with VWAP, rolling approximation or imbalance | Absent | **Useful evidence accounting, schema-specific names obsolete.** Sources/horizons must be labeled before comparing. |
| Nine setup-class labels | Generic string | **Possibly redundant/obsolete taxonomy.** Label drift is possible; do not restore until classes have an evaluated purpose. |
| JSON only | Schema-enforced JSON | **Duplicated/preserved.** V2 is stronger on output shape. |
| Two upstream filters and entry geometry | Added in V2 | **New information, not lost V1 guidance.** Historical case records lack proven decision-time values; UNKNOWN cannot be backfilled from fills. |

These are semantic risks and design hypotheses. Historical counts or outcomes cannot isolate prompt effects because prompts, monitor schema, feed quality, and time period changed together.

## Why 60m/240m appeared, and whether they should stay special

The pre-V2 monitor description highlighted 15m/60m/240m local context; the old aggregated context also published 60m/240m ranges. The old prompt consequently used those extrema as chase examples. V2 later added Filter B with **60m trusted OI** and **240m direction-adjusted delta**, which is an upstream admission rule, not evidence that these are universally superior entry horizons. Git history and available journals provide no controlled horizon ablation or edge proof. Keep the old 60m/240m wording only in experimental arm B. A future monitor should publish normalized, comparable facts for all supported horizons and let the model weigh them. The exact Filter B calculation should remain labeled as upstream policy data, separate from objective monitor facts.

## Current 39A information contract

`market_monitor/snapshot_builder_v39a.py` builds exact local windows; `canonical_features.py` builds broad context and direct structure/zones. At the same cutoff, the model can see:

| Horizon | Price change; high/low; range position | Delta, delta_pct, OI, activity | VWAP/POC | Completeness |
| --- | --- | --- | --- | --- |
| 5, 15, 30, 60, 240, 1440 minutes | All present | All present | OHLC typical-price volume-weighted `vwap_approx`; POC explicitly null | Exact expected/used rows, missing times, duplicates, `metrics_valid`, quality counts |
| 1d, 3d, 7d, 30d | Price change only; **high/low and range position missing** | Present | **Missing** | `expected_rows`, `rows_used`, `complete`, quality flags; no explicit missing timestamp list |

`delta_pct` is a **fraction of total quantity** throughout the new monitor; `price_change_pct` is in percent points. The internal structure classifier uses percent points but canonical serialization divides by 100. `open_interest_change` retains feed-contract units; the source and trust of OI require explicit provenance. `vwap_approx` is not trade-level VWAP. Exact POC is unavailable without a price-volume distribution.

| Field/fact | Audit class | Consequence |
| --- | --- | --- |
| Local `open/close/high/low`, `price_change_pct`, `range_position` | USEFUL | Compare entry location and movement across all six windows. The extrema are observations, not support/resistance claims. |
| Local `delta`, fractional `delta_pct`, `total_qty`, OI change | USEFUL | Compare participation and flow; signed OI change alone has no directional interpretation. |
| Local `vwap_approx` and `poc_status` | USEFUL / AMBIGUOUS | Approximation and missing POC are labeled; explicit current-price distance to VWAP is absent, and signal VWAP/POC can use another source/horizon. |
| Broad price change, flow, OI, activity, regime and coverage | USEFUL | Local-vs-broad comparison is possible, provided coverage is read. |
| Broad high/low, range position, VWAP/POC | MISSING | Late-entry geometry cannot be compared symmetrically across 3d/7d/30d. |
| `structure.levels` (240/1440 observed extrema) | USEFUL / REDUNDANT | Repeats window highs/lows; its `OBSERVED_EXTREME` lifecycle must not be promoted to qualified structure. |
| `significant_market_zones`, `liquidity_zones`, classifier support/resistance | USEFUL / REDUNDANT | Zone prices and scores exist; buckets can repeat the same zone. They are not uniformly horizon-scoped, and source-day count is not zone age. Deduplicate by ID/source. |
| Opposing-zone distance and target room in price, percent or R | MISSING | The source algorithm sorts by distance internally but does not publish a single candidate-relative distance or room-to-target contract. Never guess it in the prompt. |
| `market_state.state`, `market_structure_state.state`, `candidate_bias` | AMBIGUOUS | Different classifiers/scope coexist. Primary cases include `CHOP` with `FAILED_BREAKOUT_SELLER_RECLAIM` and `ACCUMULATION` with `EXPANSION_UP`; the model needs declared precedence or separate descriptive roles. |
| `context_conflicts` | AMBIGUOUS / REDUNDANT | Current derived conflicts test only 60m signed delta against 3d/7d regime for candidate direction; absence of an item does not mean all horizons agree. |
| `quality.readiness`, local `complete`, broad `complete` | USEFUL / CONTRADICTORY | Readiness fails on local incompleteness/duplicates, but does not incorporate broad-window completeness; a `READY` summary can coexist with an incomplete 30d field. Broad coverage must be checked separately. |
| `market.context.aggregated` and signal VWAP/POC beside monitor facts | AMBIGUOUS / potentially CONTRADICTORY | Sources, cutoffs, and formulas differ. Research frozen inputs omit legacy context to avoid presenting two competing facts as one. Production still passes it. |
| `state_memory` and lineage | USEFUL | Replay has deterministic `INITIALIZED` state with no prior persisted state; this does not reproduce every historical live state transition. |

The self-contained 39A monitor is sufficient for objective **local** market evidence and many broad-flow comparisons. It is not sufficient for full entry geometry/room assessment across all horizons. Add missing facts to the data contract before trying to compensate with prescriptive prompt rules.

## Real case set and leakage boundary

`source_case_ledger.csv` and `source_signals.jsonl` derive from the prior clean forensic research branch at `5dee697c719d4decb424cbc1bda3b706b5e1acb`; `source_feed_hashes.csv` records the 155 historical daily feed SHA-256 values. `rebuild_cases.py` matched all 155 hashes against local read-only archives, retained only rows at or before each cutoff, recomputed synthetic/degraded quality from those rows, and reran the **current** canonical builder with no persisted state write. Full-day hashes remain in the separate manifest because their final values were unavailable at cutoff. The script generated one `LLM_ENTRY_SNAPSHOT_V2` JSON per real trade in `frozen_canonical_entry_snapshots.jsonl` and separately wrote outcomes/verdicts to `case_ledger.csv`. The model-input JSON contains no historical verdict, outcome, fill, PnL or management data. Local timestamp fields from old signals and old market context were excluded. Per-input SHA-256 is in the ledger.

The 21 cases classify as **10 `INPUT_RECONSTRUCTED_CANONICAL`**, **2 `INPUT_HISTORICALLY_CORRUPTED`**, and **9 `INPUT_INSUFFICIENT`**. All ten primary reconstructions pass the current canonical entry validator, have 240/240 and 1440/1440 rows, and complete 1d/3d/7d/30d context. Nine of the ten have degraded context in the 30d lookback; the model must see that quality. Two historical v1 inputs were day-scoped: `EX_EN_1785025567` used 27/240 and `EX_EN_1789351940` used 133/240, versus 240/240 in canonical replay. Those recorded verdicts cannot grade the old prompt on matched evidence. Nine insufficient cases have incomplete 30d context or a timestamp anomaly; two also fail the current local-window validator with 1439/1440 rows.

All 21 frozen inputs show `UPSTREAM_FILTER_PROVENANCE_MISSING` and `INCOMPLETE_EXECUTION_GEOMETRY`; the earlier journal cannot prove those values were known before entry. The ten primary cases are suitable for **prompt-semantics comparison under missing geometry/admission**, not a complete trade-quality or profitability evaluation. No GPT-5.6 verdicts or same-input A/B/C results have been generated. Historical GPT-5.5 verdicts are observational baseline only. Outcomes in the separate ledger may be joined only after model verdicts are stored.

## GPT-5.6 and comparison design

The current project uses `https://api.openai.com/v1/responses`, strict JSON-schema text format, `max_output_tokens` default 2000, and no explicit reasoning or temperature parameter. Local defaults remain `gpt-5.5`. Official OpenAI documentation identifies **`gpt-5.6-sol`** as the pinned GPT-5.6 Sol model ID, while `gpt-5.6` is an alias; Responses API and structured outputs are supported: [model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [model catalog](https://developers.openai.com/api/docs/models). Use `gpt-5.6-sol` for all new research runs; record returned model ID, prompt hash, input hash, parameters, response and errors. No production model setting is changed here.

`prompt_variants.py` prepares A = exact current V2 function; B = last pre-V2 semantics translated to the **same canonical input**; C = minimal neutral assessor. C is justified by the absence of evidence that hard 60m/240m or zone verdict preferences improve decisions. Use the same frozen snapshot, same `gpt-5.6-sol`, same response schema and call parameters; only prompt instructions may differ. Do not mix monitor revisions into that comparison. Keep outcomes hidden until verdict storage. Compare verdict diversity, consistency of reason/confidence with evidence, handling of weak/late entries, opposing zones and broad conflicts, and repeat stability. Randomize A/B/C order with a recorded seed. Do not promote a prompt from this selected, small cohort alone. See [OpenAI model migration guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6) for testing prompt changes on representative evals.

## Direct answers for architecture review

1. **Disappeared:** fresh-edge/risk accounting; late-chase guard; 60m/240m, weak PEAK and opposing-zone examples; broad/degraded/mixed-zone UNCLEAR examples; bearish-expansion cue; VWAP/flow conflict reporting; confidence-risk explanation; setup taxonomy.
2. **Obsolete:** raw local-time workaround, old evidence paths, game scoring language, and unvalidated setup labels.
3. **Genuinely useful:** assess freshness, entry location, remaining room, contrary structure and flow, data quality, and adverse-versus-unknown evidence.
4. **Possible V1 SUPPORT bias:** “bot side is favored” framing and reliance on local momentum; incomplete old windows could distort inputs. No causal rate is established.
5. **Possible V2 REJECT/UNCLEAR bias:** generic uncertainty boundary, UNKNOWN admission and absent geometry may drive caution; one historical V2 call cannot establish a distribution. V1 itself also contained explicit REJECT/UNCLEAR preferences.
6. **60m/240m emphasis:** inherited from old available local ranges and Filter B definitions, not a measured optimum.
7. **Keep special?** No general special status without a controlled ablation. Preserve them as named policy inputs where Filter B requires them.
8. **39A sufficient?** For exact local windows and descriptive broad-flow evidence, yes; for complete entry geometry and consistent cross-horizon structure, no.
9. **Missing:** broad ranges/range position/VWAP, qualified opposing distance/target room, decision-time admission/geometry provenance, and broad coverage in summary readiness.
10. **Redundant/contradictory:** repeated 240/1440 extrema and zones, multiple state classifiers, signal/legacy VWAP beside monitor approximation, and readiness that can understate broad incompleteness.
11. **GPT-5.6 input:** one cutoff-normalized candidate plus one canonical monitor, per-horizon units/quality/source, qualified structure distance and planned geometry only when known at cutoff.
12. **Prompt guidance:** weigh fresh edge, location/room, contrary evidence and uncertainty; distinguish REJECT from UNCLEAR; explain SUPPORT despite material risks; forbid future inference.
13. **Prompt exclusions:** automatic horizon/zone vetoes, invented thresholds or missing values, game scoring, raw local-time hacks, outcomes and order-management advice.

## Verification on this branch

- SHA-256 matches all 155 historical source files used by the replay. Independent validation found 21 unique frozen inputs, 21 matching ledger hashes, no post-entry keys, no future ISO timestamps and no full-day source hashes inside model input.
- For all 21 cases, research variants A/B/C embed byte-identical canonical snapshot JSON and have distinct prompt instructions. `python -m compileall -q docs/research/llm_judge_calibration` and `git diff --cached --check` passed.
- Full `python -m pytest -q`: **873 passed, 1 failed, 24 subtests passed**. The sole failure is the pre-existing `TestMarketContextUntilCutoff.test_prompt_mentions_market_context_and_no_hindsight`: V2 lacks the old `market_context.deltascout` wording and later calibration assertions in that same test also target lost guidance. The test was neither edited, skipped, nor xfailed.
- No GPT-5.6 API comparison was run. A/B/C results therefore remain unknown.

**Status: `CALIBRATION_RESEARCH_COMPLETE_READY_FOR_ARCHITECT_REVIEW`.** This status is for the audit and frozen research design, not production prompt promotion.
