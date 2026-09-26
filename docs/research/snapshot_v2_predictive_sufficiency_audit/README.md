# Snapshot V2 predictive sufficiency audit

Research-only, post-unblinding description of the unchanged frozen Snapshot V2 cohort: 19 chronology-valid trades, with `EX_EN_1779900918` excluded from primary statistics.

- `PREDICTIVE_SUFFICIENCY_AUDIT.md`: evidence gate, methods, Target A/B comparison, decision.
- `feature_distribution.csv`: every numeric feature by target and class, including missingness, quartiles, effect and overlap measures.
- `categorical_distribution.csv`: class counts for categorical/quality/structure states.
- `feature_usefulness.csv`: family-level usefulness and provenance limits.
- `case_feature_matrix.csv`: reproducible per-trade flattened raw and analysis-only fields.
- `case_pair_analysis.md`, `tp2_failure_analysis.md`, `negative_failure_analysis.md`: case-level comparisons.
- `NEXT_RESEARCH.md`: hypotheses for a **new** frozen cohort only.
- `run_audit.py`: deterministic generator for the numeric and categorical CSVs; no model calls.

Run from the repository root with `python docs/research/snapshot_v2_predictive_sufficiency_audit/run_audit.py`. The script derives cohort identity from the **committed hierarchical blind manifest**, independently derives ledger labels, asserts the committed manifest and frozen-input hashes, and reports the frozen input SHA-256. It does not depend on the locally untracked paired evaluation or modify the source snapshots or either blind checkpoint.
