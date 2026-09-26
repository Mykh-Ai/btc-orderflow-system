# Proposed ADR — CANONICAL_TRADE_EVALUATION_SNAPSHOT_V2

Status: specified after Evidence Audit; not implemented or validated against historical source rows. Scope is offline research only. No state migration, watchdog/reconciliation mutation, finalization change or live wiring is permitted.

## Temporal and evidence boundary

1. Preserve the durable signal timestamp exactly. `market_cutoff_utc = signal.signal_time_utc`. The inclusive minute-row boundary is `market_bar_cutoff_utc = floor(market_cutoff_utc, minute)`, using the audited `UTC_minute_close_label` contract. A non-minute signal timestamp is disclosed, never silently rounded in the signal field.
2. Filter raw observations before metrics, quality summaries, zone construction, touch detection and hashes of pre-cutoff rows. No future IsSynthetic flag may degrade earlier evidence. Full-day file hashes are audit-only provenance.
3. Execution entry, Executor-observed fill, quantity and initial SL/TP remain the frozen pre-outcome facts. They may follow market cutoff and must never move it forward. Preserve missing conversion and exact assessment time as missing.
4. Separate audit evidence (source rows/identities, full horizon metrics, full registry, derivations) from an explicit, recursively allowlisted model view. Neither audit artifacts nor old result/outcome files enter the isolated runner directory.

## Non-overlapping temporal sequence

For inclusive minute boundary `C`, use exactly:

| Segment | First close label | Last close label | Expected rows |
| --- | --- | --- | ---: |
| 0–5m | C−4m | C | 5 |
| 5–15m | C−14m | C−5m | 10 |
| 15–60m | C−59m | C−15m | 45 |
| 60–240m | C−239m | C−60m | 180 |
| 240–1440m | C−1439m | C−240m | 1200 |

Serialize oldest segment first for temporal readability. The same five disjoint sets partition all 1440 minute labels even across UTC midnight. Reject duplicates rather than choosing an arbitrary row. Incomplete intervals must report exact missing data; do not silently relabel a partial sum as a complete interval.

For each segment publish timestamps, price change percent (first actual open to last close), Delta, total quantity, fractional delta_pct, endpoint OI difference only with proven source-column availability, and compact completeness/degradation/unavailable metadata. Preserve existing canonical zero-volume delta_pct convention with explicit zero-volume status. Do not sum or subtract endpoint OI changes to produce parent intervals; boundary transitions make them non-additive. A single-row segment has no observed OI transition and must disclose insufficient endpoint coverage rather than imply a measured change.

Use finite numeric values, deterministic sorting and precision; reject NaN/Infinity. Raw column provenance must survive the adapter's zero/default-open substitution. Missing BuyQty/SellQty makes Delta unavailable; missing OI makes OI unavailable. No STRONG/WEAK or market-pattern classification is generated.

## Location, zones, reaction and geometry

- Publish signal-cutoff close, 240m and 1440m range positions, and distances to the 240m high/low. Keep broad numeric backdrop to 1d/3d/7d price_change_pct and delta_pct with per-period quality. Preserve 30d only in audit; the unchanged canonical zone construction can still use its historical context, with lineage disclosed.
- Rebuild the full canonical registry from pre-cutoff rows. Qualified support/resistance are selected after filtering SIGNIFICANT/QUALIFIED, then by nearest band distance with deterministic ties. Preserve existing definition of support below and resistance above cutoff close. Do not use the truncated displayed zone buckets as the full selection universe.
- Select BUY_SIDE and SELL_SIDE liquidity separately using the existing active-forward eligibility contract. Keep null when no eligible candidate exists. No liquidity candidate becomes qualified structure merely from its position relative to price.
- For qualified zones scan only `[C−239m,C]`. A historical bar intersects a zone when bar high ≥ lower bound and bar low ≤ upper bound. This is factual intersection of the current cutoff zone bounds, not proof that the zone was known or tradable at the touch time. Record that distinction. If zone creation/history cannot support a stronger claim, leave that stronger claim unavailable.
- Last touch is the latest intersecting eligible row. Minutes since touch use exact cutoff time and must state that unit convention; displacement is cutoff close minus last-touch close, with percent using last-touch close. Do not infer intrabar path or a traded touch price. Missing bars invalidate claims of no touch or an exact last touch across the gap.
- Preserve native quote zone bounds and signal-price distance. Entry-relative distances require the durable positive quote conversion and remain approximate. R uses actual entry and initial stop. Missing conversion yields null cross-quote fields and a named quality gap.
- Choose the nearest qualified opposing zone along the trade direction from actual entry in the converted quote. If entry is inside a zone, distance is zero. Never substitute liquidity for a missing qualified zone. TP targets before the near boundary, inside inclusive bounds, or beyond the far boundary map to BEFORE/INSIDE/BEYOND, oriented for long/short. Retain adverse target geometry instead of silently clamping it. Publish the nearest active directional-liquidity distance separately.

## Signal and quality

Allowlisted signal evidence: side, original PEAK time, raw signal price and quote, raw DeltaScout Delta/volume/imbalance/VWAP/POC/strength where durable, and raw DeltaScout plan. No upstream admission verdict is inferred. Preserve each absent measurement explicitly.

Allowlisted execution evidence: actual entry, observed fill timestamp and its semantics, quantity/source, initial SL/TP1/TP2, risk, TP1/TP2 R, durable entry conversion, entry minus converted signal and signal-to-fill seconds. Do not read subsequent stop amendments, order completion or state closure.

Quality must expose source coverage, degraded/recovered data, each unavailable OI segment, unavailable reaction history, missing conversion and missing signal measurements. Missing source files prevent this cohort from being frozen; missing individual optional fields remain null with reasons. Do not discard or replace any of the 20 eligible trades.

## Prompts and call contract

Copy A/B/C decision prefixes unchanged wherever their schema references remain valid. Change only the shared schema/timing explanation and unavoidable schema references. B's existing consideration of extrema, VWAP and structure must not be rewritten into a new trading rule merely because those old fields are absent: state their unavailability honestly and provide the allowed replacement facts. Archive an exact unified diff and old/new prefix hashes before any call. No Prompt D, learned thresholds or case-specific instruction.

Use the unchanged strict output schema, gpt-5.6-sol, reasoning medium, 4000 output tokens, store=false, no tools or history, one independent request per eligible trade/arm, no retry. Preserve fsynced STARTED/result/COMPLETED protocol and refusal to repeat unresolved STARTED. Every frozen source/manifest/renderer/prompt hash is checked before execution.

## Acceptance and release sequence

Implement all twelve requested characterization groups before rebuilding: exact PEAK cutoff; poison-future exclusion; partition uniqueness; UTC midnight boundaries; additive Delta/quantity reconciliation; endpoint OI semantics with missing-column detection; bounded touches; qualified/liquidity separation; recursive no-outcome allowlist; later execution geometry without cutoff movement; byte determinism; unchanged old frozen artifacts. Include the observed second-bearing timestamps and missing-column defaults as additional cases.

Freeze exactly the prior 20 eligible keys with V2 input line hashes, paired audit evidence, source hashes and prompt hashes. Generate actual representation-only examples for the three requested keys. Pass focused tests and `git diff --check`; preserve evidence in a commit before calls. Create an isolated execution bundle with only the required code, allowlisted inputs and prompt metadata. Freeze all 60 successful blind results in a separate commit before reading case outcomes.

Only then compare OLD A/NEW A, OLD B/NEW B and OLD C/NEW C, retaining the previous lifecycle class definitions. Report verdict distributions, class cross-tabs, polar alignment/misses/UNCLEAR, confidence, all nine old→new verdict cells and requested transition counts. Define wrong/aligned on polar classes; MIXED must remain separate and must not be forced into binary accuracy. Report overlapping requested transition categories transparently if counts are not a disjoint partition. Do not select a winner by raw accuracy or claim causal isolation/repeatability from this one-run intervention.

Rollback: the planned implementation is research-only and has no production imports or state writes; abandon/revert only its research changes if validation fails. No merge to v2.0, deployment, restart or prompt replacement is authorized.
