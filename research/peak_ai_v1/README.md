# Peak_Ai v1 — offline research package

Status: **REJECTED_FOR_LIVE**. Six causal signal variants, fixed Executor V8 replay exits. Selected diagnostic `failed_extreme_30` failed the development profitability gate and subsequently lost money in the untouched holdout. No claim of optimality or profitable edge. Production files are unchanged.

## Reproduce

1. Clone `Mykh-Ai/btc-orderflow-system` branch `codex/scout-replay-backtester-v0-1` and use immutable commit `84fcb9ec257dd2c28b04ff6149b48b52d628fdca` in a fresh checkout.
2. Copy this package's `research/peak_ai_v1` directory into that checkout. Use the source files; keep prior `results` elsewhere as immutable evidence, rather than overwriting them.
3. Verify and extract the two `docs/research/scout_replay_*_2026_10_02.tar.gz` bundles following the repository handoff. Expected hashes are in that handoff and this report.
4. Python 3.12 with numpy, pandas and pytest; run from repository root. No exchange credentials or LLM calls.

```bash
python -m pytest -q tests/offline/scout_backtester research/peak_ai_v1/test_signals.py
python -m research.peak_ai_v1.run prepare
python -m research.peak_ai_v1.run development
python -m research.peak_ai_v1.run validation
python -m research.peak_ai_v1.run select
python -m research.peak_ai_v1.run holdout
python -m research.peak_ai_v1.run sensitivity
```

`run.py` calls the existing offline `replay_candidate` and `replay_portfolio` APIs. It does not register fake archived PEAKs or modify the production detector. All candidate features are computed from completed signal bars. Official Spot timestamps are shifted only by the existing loader, not in source files.

The generated `prepared.pkl` is a local performance cache, deliberately excluded from the delivery archive. Regenerate with `prepare`; do not unpickle caches from untrusted sources. `results/candidates.csv` contains the derived candidate evidence; `results/input_hashes.csv` records a source inventory; period folders contain every independent and portfolio result. `frozen_selection.json` was written before any holdout outcome was calculated. Separate portfolio starts and two closing-only days prevent training outcomes reaching validation/test periods. A filled unresolved trade is not a zero-PnL close.

The supplied hypotheses are deliberately limited. Historical archived PEAK is a comparator under changing historical admission settings, not an exact re-run of today's detector. A/B is reapplied to admitted archived PEAK only. Minutely OHLC is not tick or live exchange parity. Margin interest is missing. Do not promote this package to production.
