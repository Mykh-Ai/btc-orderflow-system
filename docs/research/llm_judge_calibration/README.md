# LLM Judge calibration research package

This is a **WIP / research artifact** on `codex/canonical-39a-monitor-normalization`. Read [AUDIT.md](AUDIT.md) first. No prompt variant here is approved for production.

| File | Role |
| --- | --- |
| `AUDIT.md` | Git prompt history, semantic diff, 39A field audit, case limitations and the 13 architecture answers |
| `frozen_canonical_entry_snapshots.jsonl` | One current-canonical, pre-entry model input per real case; **no verdict/outcome** |
| `case_ledger.csv` | Input class, model-input hash, historical verdict and outcome field; never pass this file to the model |
| `prompt_variants.py` | A = exact current V2; B = historical semantics adapted to the same canonical JSON; C = minimal neutral; no API call |
| `rebuild_cases.py` | Rebuilds the frozen inputs from SHA-256-matched feed files; writes no monitor state |
| `source_signals.jsonl` | Compact historical signal seeds extracted from prior forensic frozen inputs |
| `source_case_ledger.csv` | Prior forensic case metadata, including outcome fields, kept separate from model input |
| `source_feed_hashes.csv` | Full-day source archive provenance; these hashes are **not** in model input |

The source seeds and original case ledger came from `codex/llm-trade-judge-calibration-forensics` at `5dee697c719d4decb424cbc1bda3b706b5e1acb`. The feed manifest covers 155 daily CSVs. Exact regeneration requires local files with the listed SHA-256 values and this branch's code. Pass the directories containing those files as repeated `--feed-root` arguments. Run `rebuild_cases.py` from the repository root with `PYTHONPATH` set to that root and point `--prior-snapshots`, `--prior-cases`, and `--feed-manifest` at the three `source_*` files here. Output should be this directory. The script rejects a missing hash match before writing cases.

The prepared comparison is **not run**. For each eligible `INPUT_RECONSTRUCTED_CANONICAL` case, call `build_variant("A"|"B"|"C", snapshot)` with the same snapshot and the same `gpt-5.6-sol` Responses API settings. Freeze and record each prompt hash before calls. Outcomes and historical verdicts remain sealed until all new verdicts are stored. The two `INPUT_HISTORICALLY_CORRUPTED` cases are input-quality sensitivity cases; `INPUT_INSUFFICIENT` cases are diagnostics. Keep the unresolved production prompt-contract failure visible.
