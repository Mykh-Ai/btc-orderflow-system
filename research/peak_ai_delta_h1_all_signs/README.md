# Corrected Peak_Ai H1 SHORT hypothesis: both signs

The earlier positive-only version omitted negative raw delta triggers. This
version corrects that omission. Every raw DELTA_MIN/MAX can arm the same SHORT
setup; numeric sign does not determine trade direction. The level, H1 deadline,
stop and execution rules are otherwise unchanged. See PROTOCOL.md.

Both signs share one chronological candidate lifecycle and one portfolio. A
repeat delta never extends the original timer. Candidate attribution follows
the first eligible trigger. The report groups executed trades by its numeric
delta sign; those groups are portfolio contributions, not isolated strategies.

## Reproduce

Use the same repositories and immutable Scout Replay handoff inputs as v1.
From btc-orderflow-system with the modified AiTrader checkout adjacent:

```bash
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.test_engine
PYTHONPATH=../aitrader-monitor OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m research.peak_ai_delta_h1_all_signs.query_cache prepare --workers 8
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.query_cache positive_parity
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.run prepare
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.run base
PYTHONPATH=../aitrader-monitor python -m research.peak_ai_delta_h1_all_signs.run double_slippage
python research/peak_ai_delta_h1_all_signs/utilities/report.py
```

The query cache contains immutable native Monitor outputs for all raw trigger
timestamps. Workers reconstruct full available zone lifetime histories; they
do not reset the market to their assigned date ranges. The engine processes
all minutes and both signs together chronologically after cache completion.
Cache hashes and original positive-only candidate equivalence are checked.
No test of a new entry rule or parameter search is included in this correction.

Use a new output folder for another campaign. Cache preparation resumes only
matching frozen code, input manifest and worker partitioning. The original
positive-only v1 outputs remain unchanged for audit and parity checks.

Scope remains individual H1/H4 zones, not full Monitor 39A. No LONG, no
without-delta control, no new holdout, no production or live-order changes.

The completed partial query cache before workload rebalancing is retained as
query_cache_before_rebalance. Its records may be reused only when input hashes
and every decision-code hash match; the orchestration module is the sole permitted
difference. Six long partitions were replaced by small chronological batches
across eight workers. Original native calculations and full histories are unchanged.

## Completed historical result

226 closed simulated shared-portfolio SHORT trades; net -1401.95 USDC. Positive
triggers: 151 trades, -995.77; negative triggers: 75 trades, -406.18. Both groups
negative. See REPORT_UA.md and results_v2/sign_analysis.json. Supplied completed
cache is verified; reproduction from this archive may start at positive_parity.
The completion flag alone is insufficient: actual unique query count must be
2846 and all manifest hashes must match. This was verified before this replay.
