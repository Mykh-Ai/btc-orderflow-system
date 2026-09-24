# GPT-5.6 real-trade prompt A/B/C evaluation

Offline research only on `codex/canonical-39a-monitor-normalization`. Nothing in this directory is imported by Executor. The runner does not deploy, restart services, place orders, create trades, modify the production prompt/model, rebuild Market Monitor data, or change frozen snapshots.

## Frozen blind cohort

`eval_manifest_blind.csv` was derived before any API call from the frozen snapshot ledger at commit `ee3018387720b1f4c73855e501b5ba347a93269f`. Its only columns are `trade_key`, `snapshot_sha256`, `eligibility_status`, and `exclusion_reason`. It contains 20 eligible historical production trades and six exclusions: five `ERROR_NOT_SCORED` supplemental records and one impossible-chronology record. It contains no outcome, historical verdict, TP completion, lifecycle, or PnL field.

The runner reads only this blind manifest and `canonical_trade_evaluation_snapshot/frozen_trade_evaluation_snapshots.jsonl`. Outcome data is not copied into the API execution bundle.

## Evidence mapping and canonical renderer

The production V2 prompt, the last pre-V2 prompt (`ae10ace^` with calibration added in `b366e19`), the unchanged historical research artifact `llm_judge_calibration/prompt_variants.py`, the new schema builder, and all 24 frozen objects were inspected before the canonical renderer was written.

| Old prompt concept | Proven canonical location | Renderer treatment |
| --- | --- | --- |
| `decision_cutoff_utc` / `analysis_cutoff_ts` | top-level `assessment_cutoff_utc`, `assessment_cutoff_source`, `market_cutoff_utc`; `market.cutoff_utc` | All arms use the new timing contract. Historical null assessment cutoff remains explicit; market facts end at the market cutoff. |
| PEAK direction, time, price and raw measurements | `signal.side`, `signal.signal_time_utc`, `signal.signal_price`, `signal.measurements`, `signal.raw_signal_plan_usdt` | All arms identify these as factual DeltaScout evidence. |
| `execution_geometry.entry_price` | `execution.actual_entry_price` | Uses the actual Executor fill, never the signal/planned price. |
| planned SL/TP and risk/R | `execution.initial_stop_price`, `tp1_price`, `tp2_price`, risk/reward distances and `tp1_R`/`tp2_R` | Treated as initial executed-entry geometry known before assessment, with no later management inference. |
| `upstream_admission` and Filter A/B verdicts | **No canonical equivalent** | Omitted. Raw signal measurements do not prove historical Filter A/B decisions. A_CANONICAL therefore removes V2's Filter explanation instead of fabricating a mapping. |
| local monitor windows | `market.horizons.5m` through `240m` and `1440m` | Comparable factual horizons with shared units and quality. A/C add no preferred timeframe; B retains recovered historical 60m/240m consideration. |
| broad 1d/3d/7d/30d context | `market.horizons.1440m`, `3d`, `7d`, `30d`; alias `market.horizon_aliases.1d=1440m` | One numeric 1d representation; no obsolete parallel broad-context path. |
| signal VWAP/POC and rolling VWAP | `signal.measurements.vwap/poc`; each `market.horizons.*.vwap_approx` and explicit POC status | B may compare them with provenance; no arm invents unavailable POC. |
| `market_state`, `market_structure_state`, `candidate_bias`, conflicts | `market.classifiers.rolling_market_state`, `rolling_structure_state`, `candidate_bias`, `context_conflicts` | Presented as separately scoped derived interpretations, not interchangeable facts. |
| support/resistance, significant and liquidity zones | `market.zones` with category, bounds, qualification, entry/TP distance and intersection geometry | Geometry is factual. A/C introduce no automatic veto; B retains historical opposing-zone consideration. |
| local/broad completeness and data gaps | `quality` plus every horizon's completeness, missing timestamp count, duplicates and data-quality counts | Partial/degraded/reconstructed evidence is explicit and cannot masquerade as complete. |
| prohibition on future outcomes | common canonical temporal contract | Eventual TP/SL, trailing, later path, historical verdict and PnL remain forbidden in every arm. |

`canonical_prompt_variants.py` is a new research-only renderer. It does not import or replace the production prompt and does not modify the historical A/B/C artifact. It defines:

- **A_CANONICAL:** current V2 decision semantics with only canonical schema and executed-entry timing translations. It adds no late-chase rule, horizon preference, threshold, or veto.
- **B_CANONICAL:** recovered pre-V2 freshness, late-chase, local-extrema, opposing-zone, broad-conflict, data-quality, and adverse-versus-unknown calibration mapped to current fields.
- **C_CANONICAL:** minimal neutral assessment of signal, actual initial geometry, market facts, and quality, with no automatic timeframe, classifier, or zone rule.

All arms receive one byte-identical canonical snapshot JSON suffix and one common strict output schema. `prompt_record` records semantic source, renderer version, and exact rendered SHA-256. Every rendered prompt is frozen in `rendered_prompts.jsonl` before the first API request. `run_metadata.json` records source hashes and call settings. Any source or prompt change after freeze aborts the run.

## Call integrity

Each eligible trade receives one independent call for A, B, and C with:

- model `gpt-5.6-sol`;
- Responses API;
- `reasoning.effort=medium`;
- strict Structured Output schema;
- no tools;
- no conversation or `previous_response_id`;
- `store=false`;
- `max_output_tokens=4000`.

Before each request, the runner durably appends a `STARTED` record. It then stores the raw API response and parsed result in `raw_results.jsonl`, appends `COMPLETED`, and atomically refreshes `verdicts_blind.csv`. It performs no retry. If a process stops after `STARTED` but before a durable result, a later invocation refuses to repeat that ambiguous call.

The OpenAI API key is read only from the runner process environment. It is never printed or written to an artifact.

Unblinding and evaluation are performed by a separate script only after all 60 call records exist without errors.
