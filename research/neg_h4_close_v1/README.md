# NEG_H4_CLOSE_V1

Research-only hypothesis: numeric NEG raw delta, frozen significant upper H1/H4 structural zone, first completed canonical H4 CLOSE below its lower boundary within four hours, SHORT only. See `PROTOCOL.md`, `EVIDENCE_AUDIT.md`, `REPORT_UA.md` and `results/`.

## Reproduce

Checkout the pinned canonical base plus this research branch. Restore baseline data once with `python research/peak_ai_archive/restore.py`. Historical source inputs remain external under the unchanged `deltascout/research_material/` layout; exact required files/hashes are in `results/input_hashes.csv`. Use the existing AiTrader Monitor checkout containing `market_monitor/closed_structure_adapter.py` (published research tree `6865ea18b73daf1b9fcc236b3f38328150e0b0f2`); code hashes are enforced by the prior query-cache contract. No new Monitor implementation is included.

From the replay repository, with AiTrader at `../aitrader-monitor`:

```sh
export PYTHONPATH=.:../aitrader-monitor
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --import-mode=importlib research/neg_h4_close_v1/test_engine.py research/peak_ai_delta_h1/test_engine.py tests/offline/scout_backtester
python -m research.peak_ai_delta_h1_all_signs.test_engine
python -m research.neg_h4_close_v1.baseline
python -m research.neg_h4_close_v1.run
python research/neg_h4_close_v1/utilities/report.py
python research/neg_h4_close_v1/utilities/package_results.py
```

The baseline and run commands intentionally refuse to overwrite existing result directories. For reproduction use a separate checkout/output copy and relocate existing `baseline_parity/` and `results/` first. No automatic source download, live API, orders, deployment or production merge.

Dependencies: existing replay/Monitor Python dependencies (numpy, pandas), plus pytest for tests. Publication compresses CSV files larger than 500 KB as `.csv.gz`; standard pandas reads them directly. Original uncompressed hashes are in `artifact_manifest.json`. Decompress beside the archive to inspect the original CSV. No research data is dropped.

`NEG_H1_BASELINE` is the negative contribution to the historical all-sign run. `NEG_H1_CONTROL` is a separately replayed NEG-only control. Use the latter to isolate confirmation timeframe; use the former to reconcile the supplied known totals. Structural and timing breakdowns are contributions to shared dedup/portfolio state, not separate optimized strategies.
