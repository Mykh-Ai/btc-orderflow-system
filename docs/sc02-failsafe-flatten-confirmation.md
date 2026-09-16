# SC-02: confirm failsafe closure before releasing the position

Baseline: current fetched v2.0 at
`005097cdb5ff48202130a4b0bcab740f92a2d18e` (includes SC-01, PR #165).
This is the user's authorized SC-02 behavior repair. No lifecycle extraction or
deployment is included. FAILSAFE_FLATTEN remains disabled by default; its retry
threshold and grace configuration are unchanged.

## Required contract

An attempted MARKET close, a successful POST response, a timeout, and empty
openOrders are not sufficient grounds to release the position. The executor must
confirm the identified closing order is FILLED for the entire requested quantity.
It must retain position ownership and avoid another MARKET submission while that
result is uncertain, including across restarts.

## Implementation decisions

1. Before submitting, persist `position.failsafe_flatten`: unique client ID,
   symbol, position side, exact requested quantity, trade mode/isolation setting,
   start timestamp, status and polling deadline. A failed save prevents the POST.
2. Submit one MARKET using that identity. The HTTP transport makes one attempt
   with no host failover for MARKET order POSTs whose reserved client ID begins
   `EX_FLAT_`. Other requests retain their existing transport behavior. A client
   ID alone must not be treated as an exactly-once guarantee after an order fills.
3. Query the existing order endpoint using `origClientOrderId`, including when
   the POST response was lost. The adapter supports both spot and margin; margin
   includes the configured `isIsolated` value. This adds no Binance endpoint.
4. Require matching client ID, symbol, opposite side, MARKET type, positive order
   ID, original quantity and finite executed quantity. Closure is confirmed only
   when status is FILLED and executed quantity equals the persisted request.
   Changed position quantity or account mode/isolation leaves the intent blocked.
5. On confirmation, save evidence and use the existing finalization path.
   `last_closed.flatten_confirmation` retains the order identity and execution
   quantity. Archive and after-close hooks run only after the closure state save.
6. Otherwise persist uncertainty, throttle further GET checks across restarts and
   emit `FAILSAFE_FLATTEN_UNCONFIRMED`. Notify on a changed uncertainty message;
   stable repeated uncertainty does not flood webhooks. Submission errors use
   `FAILSAFE_FLATTEN_SUBMIT_ERROR`; confirmed closure uses
   `FAILSAFE_FLATTEN_CONFIRMED`.

While an intent exists, normal exit placement/management and generic startup
reconciliation cannot take ownership or clear the slot. Main-loop shutdown does
not invoke margin shutdown repayment for that position. New entry remains blocked
by the retained active position. Confirmation continues even if FAILSAFE_FLATTEN
is later disabled; that flag controls new submissions, not recovery of one already
attempted.

## Uncertainty and operator intervention

NEW, PARTIALLY_FILLED, terminal partial/rejected orders, malformed responses,
not-found and lookup errors all retain the slot. Partial executed quantity is
recorded on the intent; the original position quantity remains the accounting
reference until full confirmation. No automatic second close is attempted for a
remainder or rejection.

A crash after intent persistence but before the POST cannot be distinguished
locally from a crash after the exchange accepted the POST. Both recover via GET
only. If the exchange cannot establish the result, manual exchange/state
reconciliation is required. Do not delete the marker or resubmit MARKET blindly.
This deliberately favors retaining uncertainty over risking a reversed position.

Confirmation is order-level evidence for the executor's tracked quantity. It does
not certify zero account-wide debt or reconcile separate manual/orphan orders.
Rollback/orphan-order handling and unrelated margin defects remain separate audit
work. There is no claim of exactly-once execution across multiple executor
processes sharing one account or loss/corruption of the state file.

## Test evidence

```bash
python -m pytest -q test/sc02 test/sc01
python -m pytest -q
python -m py_compile executor.py executor_mod/binance_api.py
git diff --check
```

Review environment: Python 3.12.14, existing temporary pytest dependencies.

| Run | Result |
|---|---|
| SC-02 tests | 50 passed |
| SC-02 plus merged SC-01 tests | 83 passed |
| Full suite | 348 passed, 1 failed, 2 subtests passed |
| Compile and whitespace checks | Passed |

The sole full-suite failure is unchanged from the base:
`test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`.
Its assertion at line 432 expects an obsolete prompt substring. It is not skipped
or changed; the full suite is not represented as green.

Tests exercise LONG/SHORT, full/partial/terminal fills, invalid or missing fill
evidence, POST timeout/rejection, lookup failure and recovery, persisted polling,
crashes on either side of submission, pre-submit/final-save failures, restart
entry/exit guards, shutdown repayment suppression, configuration drift, unchanged
failsafe thresholds, successful exit retry, spot/margin query payloads, and real
adapter transport behavior. All exchange calls are mocked; no live orders occur.

## API references and deployment boundary

Binance documents the client-order-ID query and execution fields in its
[margin order query](https://developers.binance.com/docs/margin_trading/trade/Query-Margin-Account-Order).
The [spot trading endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/trading-endpoints)
also document client-order IDs and order queries. The implementation does not rely
on POST replay being idempotent.

No server command, restart or deployment is authorized by this repair. A future
deployment must verify the actual running container's code and imports. Host-only
file checks are insufficient. For rollback, an unresolved failsafe intent must
first be reconciled: old code ignores this marker and may recreate exits. Do not
blindly run the old version against an in-flight intent or overwrite its state.

SC-03, SC-04, SC-05 and SC-06 remain separate findings. This change does not grant
lifecycle-refactor readiness or assert that the deployed runtime has been updated.
