# NEG_PRE_ENTRY_SNAPSHOT_V1 — feed-only forensic snapshots

Research base: `d6f82fccd0ffea27831e878382eaf8f2662a39bb` on
`codex/peak-ai-research-consolidated-2026-10-11`.
Working branch: `codex/neg-pre-entry-snapshot-v1`.

**Scope correction from the user, 2026-10-12:** stop rebuilding/counting Monitor
zones; extract two snapshots using only the available FEED. This supersedes
the initial lower-structure analysis, zone reconstruction and associated tests.
The abandoned zone prototype is not part of this implementation. No production,
Executor, DeltaScout, Monitor, source data, replay semantics or thresholds changed.

All 262 NEG_H1_CONTROL independent opportunities, including 112 blocked by the
portfolio, have one S0 at owning delta time and one S1 at signal decision time.
The later entry fill never supplies snapshot data. Missing OI, funding,
liquidations, POC/session VWAP and post-sweep information stays missing.

Read [REPORT_UA.md](REPORT_UA.md) first. Gross/net comparisons are descriptive,
in-sample and post-hoc; no proposed filter was replayed or deployed.

## Files

- `PROTOCOL.md`: amended protocol, definitions and frozen statistical method.
- `EVIDENCE_AUDIT.md`, `evidence/`: actual git histories, blame, numbered source
  and field searches in both repositories. The audit includes the investigation
  that preceded the user's scope correction, explicitly marked as such.
- `parity/result.json`: original 262-candidate replay and financial parity.
- `config.json`, `input_hashes.json`, `data_availability.json`: feature definitions,
  input SHA-256 and missingness/provenance.
- `data/snapshot_s0.csv`, `data/snapshot_s1.csv`, `data/state_delta.csv`:
  two exact feed snapshots and changes for every opportunity.
- `data/forensic_dataset.csv`: feature matrix plus one-to-one unchanged outcomes.
- `data/validation.json`: pair coverage, financial sums and blocked inclusion.
- `analysis/feature_summary.csv`: all 107 numeric features, coverage and summaries.
- `analysis/gross_winner_loser_comparison.csv`,
  `analysis/net_winner_loser_comparison.csv`: N, mean, median, P25/P75, rank-biserial
  effects, p and BH q for each label family.
- `analysis/quartile_diagnostics.csv`, `analysis/monthly_stability.csv`,
  `analysis/monthly_overall.csv`, `analysis/quartile_contrasts.json`: descriptive
  quartiles, month concentration and contrasts. Quartiles are not entry gates.
- `analysis/categorical_outcomes.csv`, `analysis/associations.csv`,
  `analysis/aggregate_metrics.json`, `analysis/ranked_findings.json`.
- `tests_*.txt`: 146 replay/forensic pytest + 7 all-sign unittest + 26 native
  Monitor regression tests = **179 passed**. New snapshot tests: 17.
- `artifact_manifest.json`: exact stored bytes; `archives.json`: lossless gzip
  original/stored SHA-256 for large audit texts.

No `lower_structure.csv` or lower-zone analysis is claimed: it was explicitly
removed from scope. The historical trade geometry is copied for outcome audit,
not used as a new feed feature or recomputed against imagined zones.

## Reproduce

Use Python with pandas, numpy, scipy and pytest. Repository sibling
`../aitrader-monitor` is needed by the original baseline replay parity, not by
the feed feature calculations. Obtain the same archived inputs and restore the
prior research artifacts with the established archive restore utility if needed.

```bash
export PYTHONPATH=.:../aitrader-monitor
python -m research.neg_pre_entry_snapshot_v1.parity
python -m research.neg_pre_entry_snapshot_v1.run
python -m research.neg_pre_entry_snapshot_v1.analyze
python -m research.neg_pre_entry_snapshot_v1.report
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q --import-mode=importlib research/neg_pre_entry_snapshot_v1/test_feed_snapshots.py research/neg_h4_close_v1/test_engine.py research/peak_ai_delta_h1/test_engine.py tests/offline/scout_backtester
python -m research.peak_ai_delta_h1_all_signs.test_engine
```

Native Monitor regression command, from the Monitor repository:

```bash
PYTHONPATH=.:../peak-ai-research PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_closed_structure_adapter.py tests/test_market_monitor_zone_registry.py tests/test_market_monitor_zone_registry_status.py tests/test_significant_zone_selector.py
```

The parity gate was run before feature construction; `run` also checks its input
ledger SHA and the original input manifest. `prepare_feed` uses backward-looking
windows only. Tests mutate every future row, including the first fill minute,
and compare with prefix-only extraction at both S0 and S1. Warm-up, zero variance,
gaps, early S1, duplicate joins, coverage and exact financial preservation are tested.

Audit files larger than 500KB are deterministic gzip (`mtime=0`). Decompress each
with Python `gzip.decompress`, then verify `original_sha256` from `archives.json`.
All ordinary datasets remain readable CSVs. Generated Python caches are ignored;
historical restored source artifacts retain the existing documented local ignore
policy. No new generated inputs are staged.
