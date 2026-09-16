# SC-01: retain exposure after a terminal entry order

Baseline: fetched `v2.0` at `11acef1ce911b6e4eb6e4a3148cdd5ebbfa96411`.
This is an explicitly authorized behavior repair, not executor refactoring.

## Problem and change

PENDING polling previously cleared the position on CANCELED, EXPIRED or REJECTED
even when Binance reported nonzero executedQty. Executed exposure was then lost
from local state.

The existing fill path now handles these terminal statuses when executedQty is
positive: persist OPEN_FILLED, actual executed quantity and average fill price
before after-open hooks and exit placement. The original entry identity remains.
The existing exit placement/retry logic manages the filled portion.

An explicit zero quantity retains the previous clear behavior. Missing, null,
blank, nonnumeric, nonfinite or negative terminal quantities remain PENDING and
produce LIVE_POLL_ERROR; uncertainty is not interpreted as zero exposure.
Ordinary FILLED and nonterminal partial-fill handling remain unchanged.

Terminal fills emit ENTRY_TERMINAL_PARTIAL_FILLED with their terminal status.
Both cumulative quote-quantity field spellings are supported for terminal fills.
No module extraction, state-schema migration, new endpoint or margin policy is
included.

## Validation

Tests are isolated under `test/sc01/`; their fixtures do not apply to other test
directories. They invoke the real main loop and real exit orchestration, use
actual temporary JSON save/load, block requests HTTP and reject unscripted
exchange calls. Notifications and margin hook boundaries are spies.

```bash
python -m pytest -q test/sc01
python -m pytest -q
git diff --check
```

The review environment used Python 3.12.14 and its existing temporary pytest
dependencies. No project dependency change was needed.

| Run | Result |
|---|---|
| Unchanged baseline full suite | 265 passed, 1 failed, 2 subtests passed |
| SC-01 suite | 33 passed |
| Full suite with repair | 298 passed, 1 failed, 2 subtests passed |
| Diff whitespace check | Passed |

The identical pre-existing full-suite failure is
`test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`:
line 432 expects `market_context.deltascout` in the current prompt. It is neither
modified nor skipped. The full suite is not reported as green.

Coverage includes:

- CANCELED/EXPIRED/REJECTED, LONG/SHORT and both quote-field spellings;
- durable fill promotion before protective SL placement, quantities and entry ID;
- no false closure, repayment/after-close hook, archive or Plan B;
- replay/restart without duplicate exits;
- exit-placement failure, persisted retry throttle and later recovery;
- interruption after promotion and before exits, followed by restart recovery;
- malformed/unknown terminal quantities;
- unchanged zero-fill terminal, regular FILLED, nonterminal partial-fill,
  timeout cancel-confirmation and late-fill paths.

## Limits and remaining audit findings

Exchange acceptance cannot be guaranteed by these scripted tests. Existing exit
filters may reject a small filled quantity. The position is retained for the
existing retry path. Recovery tests disable FAILSAFE_FLATTEN: the independently
identified SC-02 failure still clears state if flatten throws after its threshold.

Other audit findings remain out of scope: SC-03 concurrent TP1/SL finalization,
SC-04 malformed debt data treated as clean, SC-05 after-close persistence, and
SC-06 durable borrow intent. Their unmerged failing characterization tests remain
in the audit workspace; they are not part of this narrowly scoped repair PR.

The user's subsequent instruction authorizes publication and merge of this
repair. It does not authorize deployment or establish lifecycle-refactor readiness.
No runtime server/container validation or deployment is claimed. Further lifecycle
extraction remains blocked by the unresolved audit findings and coverage gaps.
