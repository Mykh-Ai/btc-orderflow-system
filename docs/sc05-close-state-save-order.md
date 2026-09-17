# SC-05: persist cleared after-close lifecycle flags

Base: freshly fetched `v2.0`, `22f9e103b4889edf5873e31fad93cb838afa477c`.

`margin_guard.on_after_position_closed()` saved state inside the cleanup success
path, before clearing `mg_runtime.borrow_started`, `borrow_done`,
`after_open_done` and `margin.active_trade_key`. Reloading that file restored
stale flags. Cleanup exceptions skipped the save entirely.

The existing save block now runs once after those fields are cleared, including
when cleanup raises or its optional callback is absent. Repayment remains before
cleanup; existing debt evidence and `repay_started`/`repay_done` dedup maps are
preserved. Clearing lifecycle flags does not assert that debt is zero. Spot/auto
and other early-return guards remain unchanged. There is no state schema change.

The existing injected save callback writes the state file; no production file
is edited by this repair. If saving fails, the existing
`POST_CLOSE_MARGIN_DEBT_CLEANUP_SAVE_ERROR` log is emitted and the hook returns.
This patch does not promise persistence after an I/O failure or add a retry
scheduler. The regression test explicitly verifies the old disk state survives
a failed save.

## Verification

Python 3.12.14, existing test dependencies; mocked policy/API and real temporary
JSON state files. Tests verify on-disk flags, retained audit/debt data, repayment
dedup after reload, cleanup statuses/exceptions, repayment exceptions, missing
optional cleanup, save failure and unchanged no-op modes.

```bash
python -m pytest -q test/test_sc05_close_state_persistence.py --tb=short
python -m pytest -q test/test_sc05_close_state_persistence.py test/test_margin_guard.py test/test_margin_policy.py test/test_sc04_margin_debt_evidence.py --tb=short
python -m pytest -q --tb=short
python -m py_compile executor_mod/margin_guard.py
git diff --check
```

- New tests before fix: 14 failed, 2 passed.
- After fix: all 16 new tests pass; combined margin suite: 109 passed.
- Baseline full suite: 406 passed, 1 failed, 2 subtests passed.
- Patched full suite: 422 passed, 1 failed, 2 subtests passed.
- Unchanged failure:
  `test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`.
  No test was skipped or altered to hide it; the full suite is not green.

No deployment, restart, live exchange action or lifecycle extraction is included.
SC-03 remains deferred and SC-06 remains open. Future deployment requires fresh
branch comparison and verification inside the running container. Reverting this
patch restores the stale-flag persistence defect; preserve state and audit data.
