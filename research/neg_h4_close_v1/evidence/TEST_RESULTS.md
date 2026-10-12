# Test execution

- `PYTHONPATH=.:../aitrader-monitor PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --import-mode=importlib research/neg_h4_close_v1/test_engine.py research/peak_ai_delta_h1/test_engine.py tests/offline/scout_backtester`: **129 passed**.
- `PYTHONPATH=.:../peak-ai-research PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_closed_structure_adapter.py tests/test_market_monitor_zone_registry.py tests/test_market_monitor_zone_registry_status.py tests/test_significant_zone_selector.py` in AiTrader: **26 passed**.
- `PYTHONPATH=.:../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.test_engine`: **7 passed**. This historical module supplies its own unittest suite because its helper test functions take arguments without pytest parameterization.

Total: **162 passed**. Initial environment had no pytest; installed pytest. The first combined pytest collection hit duplicate `test_engine` module names; using pytest's standard importlib mode resolved collection. No test was removed or skipped to resolve it.

The new parametrized tests cover all 12 requested contracts, plus numeric sign versus event name, no PEAK_EMIT/LONG, positive/zero exclusion, same-confirmation dedup, censoring and prefix equivalence. Existing native replay and Monitor suites remain unchanged.
