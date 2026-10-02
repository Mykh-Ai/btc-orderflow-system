# Hierarchical milestone decision — paired development result

**Decision: REJECTED, NO-MERGE.** The hierarchical decision contract did not improve discrimination over direct-class predictor V1 on the same frozen Snapshot V2 inputs. This is a post-unblinding development ablation, not an independent holdout.

## Protocol integrity

- The model received the **same 20 Snapshot V2 JSON objects** committed in V1 checkpoint `0c740d0`; no snapshot byte, feature, market row, or cutoff was edited.
- The new prompt contains no `NEGATIVE`, `MIXED`, or `STRONG_FAVORABLE` labels. It asks `TP1_FIRST`/`SL_FIRST`, then conditionally `TP2_REACHED`/`TP2_NOT_REACHED`; code derives the final class. Strict missing-evidence `UNCLEAR` validation remains.
- Model and call settings stayed `gpt-5.6-sol`, medium reasoning, strict Structured Output, `store=false`, no tools/history/retries. All 20 independent responses returned HTTP 200 with the requested model, valid structured output, and one durable `STARTED`/`COMPLETED` pair each. No `UNCLEAR` occurred.
- The new blind prompts/results were committed as `cf45a81` **before** the evaluator read outcomes. `evaluate.py` verifies both committed blind checkpoints before the join.
- The [chronology audit](CHRONOLOGY_AUDIT.md) identified a timezone interpretation defect for `EX_EN_1779900918`. All 20 calls remain available for audit; the primary comparison excludes this same case from both arms and scores 19 trades.

## Paired result on the 19 valid comparison cases

| Measure | Direct V1 | Hierarchical milestone |
| --- | ---: | ---: |
| Correct | 4/19 | 4/19 |
| Raw accuracy | 0.2105 | 0.2105 |
| Balanced accuracy | 0.2870 | 0.2870 |
| Macro F1 | 0.1556 | 0.1558 |
| Predicted `NEGATIVE` | 3 | 2 |
| Predicted `MIXED` | 16 | 17 |
| Predicted `STRONG_FAVORABLE` | 0 | 0 |

True class counts were 9 `NEGATIVE`, 4 `MIXED`, and 6 `STRONG_FAVORABLE`. The hierarchical model answered `TP1_FIRST` on 17/19 and never answered `TP2_REACHED`. Question 1 was correct on 10/19. Question 2 was correct on 3/9 cases where both the model and the actual lifecycle reached TP1; all three were `TP2_NOT_REACHED`. Of the 19 paired cases, both prompts were right on 3, V1 alone on 1, hierarchical alone on 1, and both wrong on 14. Including the flagged case for audit leaves both at 4/20.

The change in wording did **not** remove the effective middle-class concentration. It also did not separate trades that later reached TP2. The result rejects this particular decision-contract remedy on this historical cohort. It does **not** prove that the frozen price, Delta, OI, and structure fields contain no predictive signal: a different model, estimation method, or genuinely new cohort could test that separately. Further prompt changes chosen by inspecting these same 20 outcomes would be another exploratory iteration, not confirmation.

The machine-readable [paired_evaluation.json](paired_evaluation.json) contains both confusion matrices, class precision/recall/F1, primary and all-20 audit metrics, checkpoint hashes, milestone answers, and every paired case. Snapshot V2, Executor, DeltaScout, services, and production prompts remain unchanged.

Focused milestone-contract tests: 5 passed. The repository suite after this research addition had 919 passes, 24 subtests, and one unchanged failure in `test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`.
