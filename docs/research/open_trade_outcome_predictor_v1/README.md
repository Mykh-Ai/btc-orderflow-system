# Open-trade outcome predictor Snapshot V2 — research only

Engineering status: **BLIND_CALLS_COMPLETE; UNBLINDING_PENDING**. The 20 development inputs and prompts were frozen locally. All 20 independent `gpt-5.6-sol` medium calls completed with HTTP 200 and valid structured responses. The server-held API key was used through SSH without copying its value into the local runner. No outcome ledger was read by the blind runner. The blind checkpoint must be committed before development evaluation. No merge, deployment, service restart, or production prompt replacement has occurred.

This is a separate experiment from the historical `SUPPORT / REJECT / UNCLEAR` entry-quality A/B/C study. The frozen target is the furthest milestone reached before terminal closure: `NEGATIVE` means terminal SL without TP1; `MIXED` means TP1 but not TP2; `STRONG_FAVORABLE` means TP2 regardless of later management. `UNCLEAR` is valid only for a specific missing required pre-outcome fact, with a nonempty reason and a matching code in `quality.missing_evidence`. Mixed signals alone cannot justify `UNCLEAR`. The historical 20-trade cohort is a development benchmark, not a prospective holdout.

## Evidence and scope

- Current research branch baseline: `c876234868a0325418b48f395905c9c2445661c1`, one documentation-only audit commit after the prior `f716d54` research head.
- The 155 original daily CSV files, 2026-04-13 through 2026-09-14, are available locally at `D:\Project_V\Aitrader\feed`. All filenames, sizes, and SHA-256 hashes match `../gpt56_prompt_abc_snapshot_v2/required_source_feed_hashes.csv`. They are not copied to GitHub.
- The builder reads only the prior frozen blind manifest, frozen pre-outcome V1 snapshot lines, and verified feed files. It does not load verdict or outcome journals. The earlier `canonical_trade_evaluation_snapshot/rebuild_cases.py` is not reused because it joins outcomes during reconstruction.
- The five top-level model blocks are exactly `signal`, `execution`, `temporal_market`, `structure_geometry`, and `quality`.
- The historical `prediction_cutoff_utc` is the Executor-observed fill proxy; `market_bar_cutoff_utc` is its UTC-minute floor under the existing minute-close-label contract. This is not an exact historical prediction-call timestamp. One case has a 7,300-second signal-to-fill delay and carries an explicit chronology anomaly flag; the signal and fill ordering is not reversed.
- Source `OpenPrice`, `ClosePrice`, `HiPrice`, `LowPrice`, `TotalQty`, `BuyQty`, `SellQty`, and `OpenInterest` presence is checked before monitor normalization. Missing OI is null; a missing open is marked as a ClosePrice fallback.

## Frozen Snapshot V2 calculation

Five ordered, non-overlapping closed-minute segments contain 1200, 180, 45, 10, and 5 rows. Their union is the last 1440 minutes through the market cutoff. Delta is summed directly from `BuyQty - SellQty`, quantity from `TotalQty`, and fractional `delta_pct = Delta / TotalQty`; complete segments reconcile with their 1440-minute parent. OI is the last minus first source endpoint per segment and is not added across segments. Broad 1d/3d/7d context contains only price change, delta fraction, and completeness/quality. The 30d window is used only by the existing canonical structure algorithms, not exposed as a model horizon.

The research structure path uses the existing 39A zone registry and significant-zone builders on feed clipped to the cutoff. Qualified `SIGNIFICANT`/`QUALIFIED` zones are filtered before nearest selection. The selected significant zone retains its bounds and qualification; a deterministic overlapping registry match supplies factual lifecycle when available. Active forward liquidity uses the existing registry eligibility and keeps its `BUY_SIDE`/`SELL_SIDE` identity. A recent accepted-beyond structure is selected deterministically when available. No probability or prescriptive zone score is computed.

## Blind preparation

`blind_run_v3/` is the valid pre-call bundle. It contains 20 model-view JSON lines, 20 rendered prompts, a blind manifest, hashes/settings, and three pre-outcome inspection examples. All 20 temporal sets are complete. One case lacks durable PEAK measurements and one has no qualified opposing significant zone. Every snapshot and prompt hash matches its blind manifest row. The prompt source LF-normalized SHA-256 is `b57264e6bcb19c54074fa9fe9c79e489565827f52874d323bebc1fbeef7ec4f9`; the frozen rendered-prompt file SHA-256 is `4b488648b7d575b3785641cabde91b7e2641fc76c16dc011d575878454004c66`.

`blind_run/` and `blind_run_v2/` are earlier **rejected pre-call preparations**. The first used a JSON object for segment names; canonical key sorting placed them out of chronological order. The second fixed ordering but counted significant-zone interactions from 1440 minutes rather than the full verified historical context and did not explicitly expose the zone's distance from current price. No model call used either bundle. They are retained as an audit trail. `blind_run_v3/` is the only bundle approved by the current code for model execution.

To reproduce the preparation in another directory, run:

```text
python -m docs.research.open_trade_outcome_predictor_v1.prepare_blind --feed-root D:\Project_V\Aitrader\feed --output <new-output-directory>
```

To run the calls with a process-local `OPENAI_API_KEY`, use:

```text
python -m docs.research.open_trade_outcome_predictor_v1.run_blind --bundle docs/research/open_trade_outcome_predictor_v1/blind_run_v3
```

The completed run used `--ssh-host root@95.216.139.172`. That transport reads the key inside `/root/volume-alert/.executor.env` on the server and sends only the API response back to the research worktree. The server file and production process were not changed. Existing completed rows are not called again.

The runner requests `gpt-5.6-sol`, medium reasoning, strict JSON output, `store=false`, no tools, no conversation state, and no retries. It fsyncs `STARTED`, then the raw and parsed result, then `COMPLETED`; unresolved `STARTED` blocks a repeat. It never reads outcomes. Every invalid `UNCLEAR` is marked `INVALID_UNCLEAR_CONTRACT` and preserved without a retry.

Only after all 20 blind calls are complete and their results are committed may `evaluate_development.py` receive the blind commit SHA. It verifies the committed artifacts before reading the lifecycle ledger. The evaluation reports the requested confusion matrix, class precision/recall, macro F1, balanced/raw accuracy, confidence splits, missed cases, and an independent `UNCLEAR` audit. A future cohort with persisted exact prediction cutoffs remains necessary before any prospective claim.

## Validation

The focused research tests passed (23/23). The repository suite has one previously documented unrelated failure in `test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`; the final full run had 914 passes, one failure, and 24 subtests. No production code or older frozen A/B/C artifact was modified.
