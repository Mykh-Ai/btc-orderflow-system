# ADR: LLM Trade Judge Game

## Status

Accepted as documentation baseline for current evidence.

Readiness split:

- Game v0 basic research logging: ready to document from existing pre-trade
  verdict and outcome journals.
- Snapshot-enriched analysis: runtime validation pending while
  `trade_execution_snapshots.jsonl` is absent and no post-patch closed trade has
  occurred yet.
- Post-trade LLM self-review loop: not ready while no durable review artifact
  exists.
- LLM data-request loop: protocol defined, not active, no requests recorded.

## Problem

Executor now has durable evidence for some immutable pre-trade LLM verdicts and
durable trade outcomes. The project needs a game/research documentation layer
that compares the pre-trade judge against realized lifecycle outcomes without
changing execution behavior or inventing missing data.

The documentation must separate current runtime facts from planned research-loop
protocols.

## Decision

Use an evidence-first LLM Trade Judge Game:

1. A pre-trade verdict is immutable once recorded as the primary verdict for a
   trade key.
2. A trade outcome is read from durable closure evidence, currently
   `trade_outcomes.jsonl` and `executor_state.json`.
3. Game v0 scoring can be documented from pre-trade verdict plus durable outcome
   lifecycle.
4. Snapshot-enriched analysis requires `trade_execution_snapshots.jsonl`.
5. Post-trade self-review and LLM data-request loops are planned protocols, not
   current runtime behavior.

No execution code changes are part of this ADR.

## Non-Goals

- No execution logic changes.
- No SL, TP, margin, reconciliation, finalization, or order placement changes.
- No Binance/API additions.
- No post-trade LLM runtime implementation.
- No invented data backlog items.
- No retroactive edits to pre-trade verdict records.

## Game Rules

- The LLM judge evaluates only the signal quality at entry time.
- The judge must use `analysis_cutoff_ts` as the evidence cutoff.
- The judge must not use future data or realized trade outcome.
- The judge is advisory only and must never affect live orders.
- A primary pre-trade verdict for a `trade_key` is immutable for scoring.
- Outcome scoring begins only after durable close evidence exists.

## Verdict Classes

- `SUPPORT`: the bot side is favored.
- `REJECT`: the bot trade should be rejected.
- `UNCLEAR`: the edge cannot be assessed from available pre-cutoff evidence.

## UNCLEAR Competitive Interpretation

`UNCLEAR` counts as reject-side in the game. It is not a neutral class for
competitive scoring.

## Lifecycle Classes

Current lifecycle classes are derived from durable close evidence:

- `plain_sl`: no TP1, no TP2, SL done.
- `tp1_sl`: TP1 done, TP2 not done, SL done.
- `tp1_tp2_trailing_stop`: TP1 and TP2 done.
- `manual_or_unknown`: lifecycle cannot be classified from current fields.

## Scoring Matrix

Game v0 scoring is based on immutable pre-trade verdict vs durable lifecycle:

| Verdict | Lifecycle | Interpretation |
| --- | --- | --- |
| SUPPORT | plain_sl | Bot-supported trade lost; judge miss. |
| SUPPORT | tp1_sl | Partial support; mixed outcome. |
| SUPPORT | tp1_tp2_trailing_stop | Bot-supported trade won; judge hit. |
| REJECT | plain_sl | Rejection aligned with poor outcome. |
| REJECT | tp1_sl | Partial rejection; mixed outcome. |
| REJECT | tp1_tp2_trailing_stop | Rejection missed a strong outcome. |
| UNCLEAR | plain_sl | Reject-side uncertainty aligned with poor outcome. |
| UNCLEAR | tp1_sl | Unclear vs mixed outcome. |
| UNCLEAR | tp1_tp2_trailing_stop | Reject-side uncertainty missed a strong outcome. |

Implementation-specific numeric scoring, if used, must cite the exact code or
scoring document version used for that report.

## Exclusions

Exclude from scoring only when durable evidence or explicit configuration marks
the trade as excluded. Known exclusion categories from current code include:

- configured manual false-peak mechanics test keys
- reconciliation exchange clear
- entry canceled/no fill
- failsafe cleanup
- local cleanup

Do not invent exclusions.

## Timestamp Contract

- `analysis_cutoff_ts` is the only timestamp used to define what the LLM could
  see at judgment time.
- `peak_ts_raw` or legacy feed timestamps may be local naive feed time and must
  not be used directly for filtering.
- Timestamp normalization must be recorded when available.
- Missing or invalid timestamp evidence must be documented as a data gap.

## Durable Data Sources

Current primary sources:

- `/data/state/llm_trade_verdicts.jsonl`
- `/data/state/trade_outcomes.jsonl`
- `/data/state/executor_state.json`
- `/data/logs/executor.log`

Snapshot-enriched source:

- `/data/state/trade_execution_snapshots.jsonl`

As of the current evidence baseline, the snapshot journal is absent. Runtime
validation is pending because there has been no post-patch closed trade yet.
Action: verify after the next closed trade.

## Current Evidence: EX_EN_1778813539

- pre-trade verdict exists: `SUPPORT`
- competitive_side: `BOT`
- outcome exists: `plain_sl`
- post-trade LLM review: not found / not yet implemented
- LLM data requests: none recorded
- request backlog items created: none
- snapshot journal: absent
- snapshot runtime validation: pending
- snapshot validation reason: no post-patch closed trade yet
- snapshot validation action: verify after next closed trade

## Planned Post-Trade Self-Review

This is planned research-loop behavior, not current runtime behavior.

A future post-trade review may compare:

- immutable pre-trade verdict
- pre-cutoff evidence pack
- durable lifecycle outcome
- optional snapshot-enriched fills and fees
- documented data gaps

The post-trade review must not rewrite the original pre-trade verdict. It may
produce a separate review artifact with lessons, calibration notes, and explicit
requests for future data.

## Planned LLM Data-Request Protocol

This is planned research-loop contract, not current runtime behavior.

Future post-trade LLM reviews may request additional data for better research
analysis. These requests must only be recorded when they appear in durable
records or explicit post-trade review output.

The system must not assume recurring needs such as order book, ETF data, funding
rates, macro context, news, or similar data unless:

- the model explicitly requested it in a durable post-trade review, or
- the architect explicitly added it to backlog.

### Request Handling Protocol

Each real request must be classified by:

- `request`: exact requested data or capability.
- `source`: durable record, explicit post-trade review output, or architect
  directive.
- `availability`: `available`, `unavailable`, `partial`, or `unknown`.
- `risk`: execution risk, data-quality risk, privacy/security risk, operational
  risk, or `none`.
- `backlog`: `create`, `defer`, `reject`, or `already_exists`.
- `architect_decision`: `approved`, `rejected`, `needs_review`, or
  `not_decided`.

No backlog item may be created from inference alone.

## Safety Contracts

- The game is documentation/research only.
- LLM verdicts and reviews must not modify orders.
- Journal writes must remain best-effort and must not block execution cleanup.
- Documentation agents must not change execution without a separate TZ.
- Missing evidence must be marked as missing, not filled with assumptions.

## Failure Modes

- Missing pre-trade verdict.
- Duplicate primary verdict.
- Missing outcome journal record.
- Missing snapshot record after an eligible post-patch close event.
- Missing or invalid cutoff timestamp.
- Contradictory state, log, and JSONL records.
- LLM API failure.
- Post-trade review artifact absent.
- LLM data request absent or ambiguous.

## Rollout

1. Document Game v0 from existing verdict and outcome journals.
2. Keep snapshot-enriched analysis in runtime-validation-pending state until a
   post-patch closed trade creates a snapshot record.
3. Add post-trade self-review only under a separate TZ.
4. Activate data-request backlog only after durable requests or explicit
   architect directives exist.

## Rollback

Rollback is documentation-only:

- Stop publishing Game v0 summaries.
- Mark affected entries as superseded or invalidated with evidence.
- Do not alter runtime execution behavior.

## Open Questions

- After the next post-patch closed trade, does
  `trade_execution_snapshots.jsonl` appear with a matching snapshot record?
- Which exact commit/tag maps to the operator phrase "Patch 3.1"?
- Should Game v0 numeric scoring be documented in a separate stable scoring
  table or generated from code for each report?
