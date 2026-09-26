# Snapshot V2 A/B/C research

**BLOCKED_BY_INPUT_RECONSTRUCTION**

Completed: evidence audit at `f716d54d7a58867e74eb1062d2d0960e00d92f32`, prior artifact hash verification, exact 20-case chronology inventory, proposed ADR, and three boundary examples.

Not completed: V2 implementation/characterization tests, source-row reconstruction, frozen V2 inputs/prompts, 60-call rerun, blind-result freeze, or unblinded comparison. No empirical A/B/C/D conclusion is available.

Files:

- `AUDIT.md`: source map, findings, blockers and validation limits.
- `ADR.md`: proposed research contract and acceptance gates.
- `BOUNDARY_EXAMPLES.md`: verified old execution facts and required new boundaries for the three requested cases; no fabricated V2 market values.
- `required_source_feed_hashes.csv`: the existing source manifest, copied byte-identically. Supply the matching 155 daily CSVs (2026-04-13–2026-09-14; 31,215,192 bytes total), retaining their original filenames and raw columns.
- `evidence/`: archived command output, command/output hashes, old-file baseline hashes, blind chronology facts, and verification status.

The new run will also require pytest in the execution environment and an API key provided through `OPENAI_API_KEY`; do not commit credentials. Neither is a substitute for the missing source rows.

No production merge, deployment, restart, DeltaScout change, order-lifecycle change or production prompt replacement.
