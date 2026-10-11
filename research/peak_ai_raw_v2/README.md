# Peak_Ai raw v2

Independent entry research from every archived DELTA_MIN/MAX, not from admitted
PEAK events. Read PROTOCOL.md for fixed hypotheses, chronology and limitations.
The report is generated after all stages. No production or repository-tracked
files are changed. This directory is a new experiment; v1 is retained separately.

## Reproduce

Checkout Mykh-Ai/btc-orderflow-system at
84fcb9ec257dd2c28b04ff6149b48b52d628fdca. Extract the two bundled research archives
as directed by docs/research/scout_replay_work_handoff_2026_10_02.md. Copy this
research/peak_ai_raw_v2 directory into that checkout. Archive prior results rather
than overwriting them. Python 3.12, pandas, numpy and pytest are required.

Run from repository root:

```bash
python -m pytest -q tests/offline/scout_backtester research/peak_ai_raw_v2/test_signals.py
python -m research.peak_ai_raw_v2.run prepare
python -m research.peak_ai_raw_v2.run development
python -m research.peak_ai_raw_v2.run shortlist
python -m research.peak_ai_raw_v2.run validation
python -m research.peak_ai_raw_v2.run select
python -m research.peak_ai_raw_v2.run historical_retest
python -m research.peak_ai_raw_v2.run sensitivity
python -m research.peak_ai_raw_v2.report
```

prepared.pkl is a locally generated performance cache, excluded from the delivered
archive. Rebuild it with prepare; never load an untrusted pickle. input_hashes.csv
identifies all source files. seed_audit.csv accounts for every raw event; candidates.csv
retains causal features; duplicate_signals.csv records repeated confirmation lineage.
Every native replay outcome is kept in independent and portfolio ledgers. Their
counts must not be confused: independent trades can overlap; portfolio allows one
position. Frozen shortlist/selection files record hashes and timestamps.

The legacy normalized Spot input synthesizes Open from previous Close, and expands
High/Low accordingly. It is not tick data. No SHI Futures features, Open Interest,
archived PEAK admissions, previous-PEAK comparison, or loss-filter decisions are used.
The native engine controls all fills and exits. Borrow interest is unmodeled. The
July–August historical retest has been seen in earlier research, so it is not fresh
out-of-sample evidence. A successful historical result alone cannot authorize live use.
