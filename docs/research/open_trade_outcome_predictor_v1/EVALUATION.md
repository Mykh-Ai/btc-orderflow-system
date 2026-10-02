# OPEN_TRADE_OUTCOME_PREDICTOR_V1 — development evaluation

**Architect decision: predictor V1 REJECTED, NO-MERGE.** Snapshot V2 remains frozen. This is a historical 20-trade development benchmark; it does not establish prospective predictive ability. A separate paired hierarchical milestone test is recorded in [its evaluation](../open_trade_outcome_predictor_hierarchical_v1/EVALUATION.md).

## Freeze and call integrity

- Research baseline after the audited GitHub update: `c876234868a0325418b48f395905c9c2445661c1`; previous research head: `f716d54d7a58867e74eb1062d2d0960e00d92f32`.
- All 155 original daily feed files matched the audit manifest by filename, byte size, and SHA-256. The raw feed remained local and was not committed.
- The model view has exactly `signal`, `execution`, `temporal_market`, `structure_geometry`, and `quality`. Its market cutoff is the UTC-minute floor of the historical Executor-observed fill proxy, explicitly flagged as a proxy.
- The prompt source LF-normalized SHA-256 is `b57264e6bcb19c54074fa9fe9c79e489565827f52874d323bebc1fbeef7ec4f9`; the 20 frozen rendered prompts have SHA-256 `4b488648b7d575b3785641cabde91b7e2641fc76c16dc011d575878454004c66`.
- The 20 independent calls requested `gpt-5.6-sol` with medium reasoning, strict JSON output, `store=false`, no tools, no conversation history, and no retries. Every call returned HTTP 200, the requested model, a valid output, and one `STARTED` / one `COMPLETED` audit record. The server-held key was used without copying it locally or changing the server.
- Blind artifacts were committed as `0c740d0` before evaluation read `case_ledger.csv`. `evaluate_development.py` verifies the committed files against the local blind bundle before joining outcomes.

## Results

Rows are true lifecycle classes; columns are frozen predictions.

| True class | NEGATIVE | MIXED | STRONG_FAVORABLE | UNCLEAR | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| NEGATIVE | 1 | 9 | 0 | 0 | 10 |
| MIXED | 1 | 3 | 0 | 0 | 4 |
| STRONG_FAVORABLE | 1 | 5 | 0 | 0 | 6 |
| **Predicted total** | **3** | **17** | **0** | **0** | **20** |

| Measure | Result |
| --- | ---: |
| Raw accuracy | 4/20 = 0.2000 |
| Balanced accuracy | 0.2833 |
| Macro F1 | 0.1465 |
| NEGATIVE precision / recall | 0.3333 / 0.1000 |
| MIXED precision / recall | 0.1765 / 0.7500 |
| STRONG_FAVORABLE precision / recall | 0 / 0 |
| Correct confidence mean / median | 0.5125 / 0.5150 (n=4) |
| Incorrect confidence mean / median | 0.5150 / 0.5150 (n=16) |
| UNCLEAR / invalid UNCLEAR | 0 / 0 |
| Unknown ground truth | 0 |

The predictor concentrated 17 of 20 answers in `MIXED`, missed all six `STRONG_FAVORABLE` trades, and identified only one of ten `NEGATIVE` trades. Confidence did not separate correct from incorrect predictions in this cohort. The zero invalid-`UNCLEAR` count is vacuous because the model emitted no `UNCLEAR` verdicts.

## Misclassified cases

| Trade key | Frozen prediction | True lifecycle | Confidence |
| --- | --- | --- | ---: |
| `EX_EN_1778689753` | MIXED | STRONG_FAVORABLE | 0.54 |
| `EX_EN_1779438963` | MIXED | STRONG_FAVORABLE | 0.49 |
| `EX_EN_1779805524` | MIXED | NEGATIVE | 0.55 |
| `EX_EN_1779900918` | MIXED | NEGATIVE | 0.52 |
| `EX_EN_1780067415` | MIXED | NEGATIVE | 0.46 |
| `EX_EN_1781221266` | MIXED | NEGATIVE | 0.52 |
| `EX_EN_1782306796` | MIXED | STRONG_FAVORABLE | 0.49 |
| `EX_EN_1782477849` | MIXED | NEGATIVE | 0.58 |
| `EX_EN_1784376441` | MIXED | STRONG_FAVORABLE | 0.46 |
| `EX_EN_1785025567` | NEGATIVE | MIXED | 0.46 |
| `EX_EN_1785961338` | MIXED | NEGATIVE | 0.48 |
| `EX_EN_1786107369` | MIXED | NEGATIVE | 0.51 |
| `EX_EN_1786131443` | MIXED | NEGATIVE | 0.56 |
| `EX_EN_1787063409` | MIXED | STRONG_FAVORABLE | 0.55 |
| `EX_EN_1788166698` | MIXED | NEGATIVE | 0.48 |
| `EX_EN_1789351940` | NEGATIVE | STRONG_FAVORABLE | 0.59 |

The machine-readable [development_evaluation.json](development_evaluation.json) contains all 16 misclassified trade keys, each frozen prediction and confidence, the model's original evidence for and against, and the true lifecycle. It includes no later price path, PnL, or post-trade narrative in those case records. The original blind responses remain in [raw_results.jsonl](blind_run_v3/raw_results.jsonl).

## Limits and next gate

Humans had already inspected some historical cases when this representation was designed. The fill timestamp is a reconstruction proxy, not the exact historical prediction-call time. This result must not be represented as an unbiased holdout or a production performance claim. No Snapshot V2 calculation, feature, prompt, output schema, or model parameter was changed after unblinding. A new cohort with exact `prediction_cutoff_utc` persisted before each model call is required for a prospective holdout; keep this contract frozen through that cohort.

Focused research tests: 23 passed. The final repository suite had 914 passes, 24 subtests, and one unrelated existing failure in `test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`. No production logic, deployment, restart, merge, or production prompt change occurred.
