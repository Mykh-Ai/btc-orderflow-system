# Entry math characterization before extraction

Current production source: fetched `v2.0` at
`ac5d86ea5661e31163cf59271966287d9a17f72e`.
Reference tests: `test/test_entry_math.py` on
`codex/refactor-executor-finalization-v1` at
`46c77e5171995ad60739d4941b754f5377260983`.

`test/test_entry_math_current.py` adapts four reference test cases to call the
current `executor.py` implementations of `build_entry_price`, `notional_to_qty`,
`validate_qty` and `compute_tps`. It adds four non-tick-aligned TP cases for
BUY/SELL with tick sizes 0.1 and 0.2, plus a test of live configuration changes.
Environment changes are restored after every case. No extracted runtime module
is copied from the reference branch; no production source is changed.

Validation (Python 3.12.14, existing temporary test dependencies):

```bash
python -m pytest -q test/test_entry_math_current.py --tb=short
python -m pytest -q --tb=short
git diff --check
```

- Focused tests: 9 passed.
- Full suite: 431 passed, 1 failed, 2 subtests passed.
- The existing failure remains
  `test/test_llm_trade_judge.py::TestMarketContextUntilCutoff::test_prompt_mentions_market_context_and_no_hindsight`.
  It is not modified or skipped; the full suite is not green.

This establishes the listed current behaviors, not exhaustive input or lifecycle
coverage. Tests for old swing-stop/Plan B modules and old module-purity checks are
not included in this four-function scope. No extraction or deployment was done.
SC-03 and SC-06 remain deferred. The separate refactor merge gate, including the
existing full-suite failure, remains unresolved.
