# SC-04: require evidence before certifying post-close debt cleanup

Baseline: fetched `v2.0` at
`1b8defab7c9f0b9d6597fff61149b5b7b7eaf8e6`, including SC-01 and SC-02.
This is an authorized behavior repair, not lifecycle extraction or deployment.

## Safety contract and implementation decisions

`cleanup_post_close_margin_debt` must not infer zero debt from an absent asset,
missing field, malformed response, or invalid numeric value. It validates the
entire configured asset scope before its first repayment, then validates a fresh
account snapshot after repayment. Every requested asset must explicitly provide
finite, nonnegative `borrowed`, `interest`, and `free` values. Repayment amounts
remain `min(borrowed + interest, free)` using Decimal arithmetic.

Cross margin requires `userAssets`. Isolated margin requires exactly one matching
symbol in `assets`, with matching base/quote assets; unrelated isolated pairs
cannot supply the evidence. Duplicate asset rows and an empty cleanup scope are
errors. The allowlist is never narrowed automatically. In particular, an isolated
BTCUSDC response cannot certify the default BTC/USDC/BNB scope without BNB evidence;
an explicitly configured BTC/USDC scope is needed for that pair.

Invalid evidence produces `cleanup_status=error` with stage
`pre_account_validation` or `post_account_validation`. Post-validation failure
retains the attempted repayment audit. The existing after-close hook logs,
alerts through `POST_CLOSE_MARGIN_DEBT_CLEANUP_FAIL`, and saves this result.
Residual valid debt retains the existing `residual_debt` behavior.

Per-trade result version 2 adds `validated_phases`. A cached `clean` is reusable
only with both pre/post validations and the same symbol, isolation mode, and
allowlist. Older or uncertified clean records are rechecked immediately, even
inside the TTL. No destructive state migration is required: existing records
remain readable and are upgraded on the next invocation. The enclosing cleanup
state format is unchanged.

Uncertain results retain the existing TTL throttle. A subsequent cleanup-hook
invocation after TTL reads current debt again instead of replaying the old repay
amount. This repair adds no background retry scheduler. Tests cover persistence
and reload, including the existing tracked-repayment dedup marker.

Scope is the audited post-close cleanup stage. The earlier `repay_if_any` hook,
its permissive legacy parsers, borrow tracking, and final flag save ordering are
unchanged. Therefore the pre-validation guarantee above applies to cleanup's own
repayments, not every repayment made by the complete after-close hook. SC-03 is
deferred; SC-05 and SC-06 remain separate work.

## Test evidence

Review environment: Python 3.12.14, existing temporary pytest dependencies.
Exchange calls are mocked; state persistence uses temporary JSON files.

```bash
python -m pytest -q test/test_sc04_margin_debt_evidence.py
python -m pytest -q test/test_sc04_margin_debt_evidence.py test/test_margin_policy.py test/test_margin_guard.py --tb=short
python -m pytest -q --tb=short
python -m py_compile executor_mod/margin_policy.py
git diff --check
```

| Check | Result |
|---|---|
| New tests before production fix | 57 failed, 1 passed |
| New SC-04 cases after fix | 58 passed |
| SC-04 plus existing margin policy/guard tests | 93 passed |
| Full suite on baseline | 348 passed, 1 failed, 2 subtests passed |
| Full suite after fix | 406 passed, 1 failed, 2 subtests passed |

The unchanged full-suite failure is
`test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`:
its expected `market_context.deltascout` substring is absent from the prompt.
The test is neither changed nor skipped; the full suite is not green.

The existing successful-cleanup fixture now supplies explicit zero balances for
all three default assets. No assertions were removed. Missing-asset uncertainty
is covered separately by the new tests, alongside malformed pre/post snapshots,
numeric edge cases, all-assets-before-repay validation, exact repayment amounts,
isolated account scope, legacy clean revalidation, configuration changes, alerts,
TTL and restart recovery.

## Deployment and rollback boundary

No server files, services, orders or runtime configuration were changed. GitHub
merge does not establish that the server runs this fix. Any separately authorized
deployment must compare against fresh `v2.0`, reconcile newer commits, and verify
the actual running container's code/imports; host file checks alone are invalid.
Runtime validation should confirm cleanup evidence, persisted results and alerts
without manufacturing a live debt scenario.

For a future rollback, preserve state and repayment audit, inspect unresolved
cleanup errors, and reconcile actual debt first. Reverting restores the original
false-clean risk; it must not be treated as evidence that debt is zero. No
lifecycle extraction readiness is claimed by this patch.

Response shapes follow Binance's [margin account documentation](https://developers.binance.com/en/docs/catalog/core-trading-margin-trading/api/rest-api/account).
