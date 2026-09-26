# Snapshot V2 / GPT-5.6 A/B/C — evidence audit

Status: **BLOCKED_BY_INPUT_RECONSTRUCTION**. Research only. No V2 builder, renderer, historical model inputs, model calls, new verdicts, or unblinded comparison have been produced. This is a completed source audit and a proposed implementation contract, not a completed experiment.

## Repository and integrity

- Audited branch: `codex/canonical-39a-monitor-normalization`.
- Starting HEAD verified by clone and `git rev-parse HEAD`: `f716d54d7a58867e74eb1062d2d0960e00d92f32`.
- Starting `git status`: clean and up to date with its remote tracking branch.
- The supplied Executor ZIP is a separate, older working copy on `v2.0`, HEAD `880b62e`, with unstaged changes. It does not contain the verified research commit, the canonical research modules, or historical CSV feed files. It was not modified or used as the research baseline.
- All required status/log/pickaxe/numbered-source/search commands were run, together with builder/renderer/runner and dependency blame. `evidence/commands.json` records 31 commands, exit codes, and output hashes. `evidence/source-audit.tar.gz` preserves their output.
- `evidence/frozen-baseline-sha256.json` hashes all 25 existing files in the three prior research directories. This includes V1 frozen inputs, all old prompt/results files and evaluation artifacts. Hashing an outcome artifact is not an outcome join.
- The old blind manifest has exactly 20 eligible keys. Each eligible V1 snapshot line matches its manifest SHA-256. Old results have 60 unique trade/arm pairs and zero recorded errors. All 60 rendered prompt strings match their recorded hashes. Only identifiers/settings/error status were extracted for these integrity checks; verdict values were not used for design.

## Source map

| Concern | Audited source | Finding |
| --- | --- | --- |
| V1 builder | `executor_mod/trade_evaluation_snapshot.py` | Allowlists signal, actual fill/initial exits, nine rolling horizons, zone geometry, derived classifiers and quality. SHA-256 covers canonical JSON before the self-hash field is added. It is a research contract, not a replacement production hook. |
| Historical rebuild | `docs/research/canonical_trade_evaluation_snapshot/rebuild_cases.py` | Uses `floor(fill, minute)` as market cutoff, loads a 30-day feed context, clips rows, recomputes synthetic quality, rebuilds 39A and V1. The old script reads outcomes and verdict journals; it must NOT be reused as the V2 blind runner/rebuilder. |
| Source identity | `docs/research/llm_judge_calibration/rebuild_cases.py:feed_lookup` and `source_feed_hashes.csv` | Requires exact per-day file length and SHA-256. Manifest lists 155 daily files, 2026-04-13 through 2026-09-14, totalling 31,215,192 bytes. |
| Feed normalization | `market_monitor/feed_adapter.py` | Maps historical OHLC/Volume column names, preserves duplicates by default, sorts by timestamp. Missing OpenPrice is replaced with ClosePrice. Missing flow/OI/other numeric columns are replaced with zero. V2 must retain raw column-presence provenance before this normalization. |
| Delta | `market_monitor/snapshot_builder_v39a.py:_window_metrics` | `sum(BuyQty - SellQty)`. Quantity is `sum(TotalQty)`. `delta_pct = Delta / quantity`, a fraction, not percentage points; existing zero-quantity convention is 0. Delta and quantity are additive, price/OI window changes are not. |
| Price | Same function | First selected row's OpenPrice to last selected row's ClosePrice. Range high/low are extrema over selected rows. A ClosePrice fallback is not a measured open and must be marked if used. |
| OI | Same function; `market_monitor/context_windows.py` | Last selected row's OpenInterest minus first selected row's OpenInterest, in `feed_contract_units`. This is an endpoint level difference, not sum of per-minute changes and not a difference of overlapping horizon metrics. Repository evidence does not prove the upstream OI instrument, physical denomination or sampling provenance. Missing source OI must be null, not adapter-generated zero. |
| Canonical zones | `market_monitor/canonical_features.py:build_canonical_features` | Rolling 1440m structure → liquidity map → registry; context feed → accumulation inventory → significant zones. Registry lifecycle is recomputed from the supplied, clipped feed with no persisted future registry. |
| Qualified support/resistance | `canonical_features.py:_nearest_market_structure_zone`; V1 builder | Current nearest helper selects by location/distance before V1 filters for SIGNIFICANT/QUALIFIED. This can discard a nearest TRACKING_ONLY candidate while overlooking a farther qualified one. V2 must filter qualification first across the full registry and then select nearest. Do not change the production helper. |
| Active liquidity | `market_monitor/zone_registry.py:forward_liquidity_from_registry`, `_is_active_forward` | Uses role, lifecycle, consumption, precision and active-forward flags, then BUY_SIDE above or SELL_SIDE below current price. Preserve this existing eligibility; do not invent a status-only replacement or rename liquidity as resistance/support. |
| Signal/fill | `open_entry_flow.py`, `pending_entry_flow.py`, `llm_trade_judge.py:build_pretrade_evidence_pack` | Source event carries PEAK facts; fill time is Executor observation time, not exchange transaction time. Actual entry and initial `prices` are copied into the Judge-hook evidence pack. |
| Assessment | `exits_flow.py` and `llm_trade_judge.py` | Judge hook follows initial exit placement. Old exact invocation time is not durable; later verdict creation time cannot supply it. Preserve unknown assessment timestamp. |
| Renderer | `docs/research/gpt56_prompt_abc/canonical_prompt_variants.py` | A=current V2 decision semantics; B=pre-V2 calibration; C=minimal neutral assessor. Shared strict schema and shared evidence contract. B explicitly refers to 60m/240m extrema, horizon VWAP and structure state; schema adaptation needs a complete prefix diff and must not silently rewrite calibration. |
| Runner | `docs/research/gpt56_prompt_abc/run_blind_eval.py` | `gpt-5.6-sol`, medium, 4000 output tokens, store=false, no tools/history, strict output; fsynced STARTED, result, COMPLETED, no retries, refusal on unresolved STARTED. |
| Old freeze | `git log`; old research artifacts | Prompt freeze `1ff6833`, source hash normalization `55e681b`, blind result freeze `756dde5`, evaluation `f716d54`. Existing artifacts remain immutable. |

## Reconstruction blockers

**No raw daily feed is available in the active workspace.** All 155 original `/opt/aitrader_data/feed/YYYY-MM-DD.csv` paths are absent. Neither the attached archive nor the cloned repository contains them. Library searches did not find a matching feed archive. The available `all_1440_rows.csv` was inspected: it is a September 18–19 stop-selection analysis export with no BuyQty, SellQty, ClosePrice or OI columns, outside this cohort's date range. It is not a substitute.

`required_source_feed_hashes.csv` preserves the original filenames, dates, byte sizes and exact hashes needed to reproduce the existing canonical source context. No newly downloaded market data, synthetic reconstruction or rolling-window subtraction can substitute for those source rows.

**Two frozen signal times contain seconds.** `EX_EN_1778689753` has `16:29:11`; `EX_EN_1779900918` has `14:55:16`. Preserve those facts. The proposed contract keeps exact `market_cutoff_utc = signal.signal_time_utc` and separately defines `market_bar_cutoff_utc = floor(signal_time_utc, minute)` under the existing UTC-minute-close-label contract. Do not silently rewrite the signal timestamp. Inspect source chronology if available; the second case's recorded signal-to-fill delay is 7,300.128756 seconds. No timezone correction is justified by delay alone.

**API setup is not ready in this process.** `OPENAI_API_KEY` is absent from the current environment. No API request was attempted. This is a later execution prerequisite, independent of the primary missing-feed blocker; it does not prove the user lacks API access elsewhere.

## Experimental interpretation

Seven cases have V1 market cutoff later than the signal minute. V2 therefore changes both representation and the information cutoff; it also omits old model-facing classifiers and many redundant metrics. An eventual paired result can measure the complete requested V2 input intervention. It cannot establish that temporal ordering alone caused a change, or demonstrate repeatability from one call per pair. Report this limitation without adding arms or calls.

The audit read existing source documentation that includes aggregate historical evaluation summaries. It did not inspect per-case outcome tables for design, tune to case outcomes, or perform any new outcome join. Any eventual model execution must remain isolated from all outcome/result files.

## Checks and remaining work

Performed: repository identity; source-command capture; 20 eligible V1 line hashes; 60 old prompt hashes; old pair uniqueness; source-file availability; per-case chronology; unchanged old-file hashes; documentation diff whitespace check.

Attempted existing focused test command:

```text
python -m pytest -q test/test_trade_evaluation_snapshot.py test/test_gpt56_canonical_prompt_variants.py test/test_canonical_market_monitor.py
```

It could not collect tests because this Python environment lacks pytest (`No module named pytest`). No passing tests are claimed. No production or research implementation was changed, and no new V2 characterization tests exist yet.

Remaining: supply matched source CSVs; implement research-only builder/renderer and all twelve requested characterization checks; rebuild and freeze all 20 cases with three actual V1/V2 examples; pass pre-call gates; execute/freeze 60 calls; only then join outcomes and evaluate discrimination/transitions. Research question A/B/C/D is **not evaluated**. Missing local input files are not empirical evidence for answer D.

Decision: **NO PRODUCTION MERGE**. Documentation-only changes require no runtime rollback. No deployment, service restart, DeltaScout change, order-lifecycle change or prompt replacement occurred.
