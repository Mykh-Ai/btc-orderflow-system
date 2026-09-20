# Next LLM entry-assessment contract: architecture proposal

Research-only proposal, 2026-09-20. No runtime prompt, production code, test, trading behavior or historical verdict was changed. This is ready for architect review; it is **not** approval to promote a new production prompt. Matched GPT-5.5 A/B remains NOT_RUN.

## A. Canonical Market Monitor facts to supply

1. One decision cutoff in UTC, minute-close semantics, and source hashes. Every value must be computed from rows at or before cutoff. Never expose legacy local-naive timestamp strings as if UTC.
2. For 5/15/30/60/240/1440m and 1d/3d/7d/30d: start/end, expected/used rows, missing/duplicate count, recovered/synthetic count, metric validity, and source. A summary readiness flag must fail or distinguish partial broad context.
3. For local windows: OHLC, high/low, range position, price change, signed delta, delta_pct with explicit fractional unit, direction-adjusted delta separately, OI change with trust, and a consistent current price. Local range position is descriptive, not a veto.
4. One VWAP and POC comparison per declared horizon/source, including distance and quality. Avoid mixing signal VWAP, rolling approximation and feed VWAP without labels.
5. Structure and zones with one resolved descriptive state. Supply nearest opposing support/resistance/liquidity zone by side, price bounds, absolute/percentage/R distance, significance, age and data quality. Distinguish observed rolling extrema from qualified structural levels. Supply target room versus the nearest credible obstacle when planned target and risk are known; otherwise null with a reason.
6. Broad context should state direction, flow, structure and coverage for 1d/3d/7d/30d, plus explicit local/broad conflicts. Broad context is evidence, not an automatic override.
7. Keep upstream admission, planned entry/stop/targets and their decision-time provenance separate from the monitor. If unavailable before entry, set UNKNOWN; do not backfill from fills or later order state.
8. Emit a single canonical state/bias with source and confidence, and suppress or label legacy duplicates. Do not silently promote v1 zone/state names to v39A semantics.

## B. Prompt interpretation contract

A concise candidate for review, not a deployed prompt:

> Assess whether the bot direction has a clear, fresh entry edge at the UTC decision cutoff using only this snapshot. Compare local flow with entry location, credible opposing structure, target room and broader context. Momentum aligned with the signal is evidence, but does not by itself establish a favorable new entry. Use REJECT when material evidence argues against entry; use UNCLEAR when missing/degraded facts or genuinely mixed evidence prevent reliable assessment. Treat broad conflict and zone proximity as risks to weigh, not automatic vetoes. If choosing SUPPORT despite material risks, explain why those risks are outweighed and reflect uncertainty in confidence. Do not infer future outcomes or propose order changes. Return the common JSON schema.

This preserves the defensible V1 *questions* (freshness, location/room, opposing room, contradictory structure, uncertainty) without retaining its hard directional preference. It needs facts from section A before it can be evaluated fairly. The exact wording should be chosen only after matched input/model comparison and blinded rationale review.

## C. Keep out of the prompt

- Automatic REJECT at any 60m/240m extreme, automatic UNCLEAR on every broad-timeframe conflict, or any hard-coded outcome-fitted threshold.
- “UNCLEAR counts as reject-side in the game,” “bot side is favored,” or other scoring/DeltaScout loyalty framing.
- Instructions to recompute market metrics or guess zone distance, VWAP/POC source, target room or recovered-data quality.
- Legacy schema trivia, duplicated market-state classifications and raw local-time workaround prose.
- Future fills, trade lifecycle, PnL and post-entry management.

## D. Tests and research gate

Code contract tests should verify full rolling windows across UTC midnight, broad coverage flags, source/units, range position, zone distances and target room from pre-entry facts, and rejection of future/post-entry fields. Prompt tests should assert a semantic contract (for example, no automatic support from momentum alone, material adverse evidence distinct from missing evidence, broad disagreement represented as uncertainty/risk) using controlled paired canonical fixtures and a rubric. Avoid assertions that simply search for V1 strings. Keep output-schema and no-hindsight checks.

Before a production prompt proposal: recover and time-validate upstream filter and planned-geometry provenance; audit 30d feed gaps and timestamp anomalies; run the same frozen snapshot through A/B/C on the same GPT-5.5 model and parameters with outcomes hidden; inspect repeated-run stability, verdict collapse, rationale coherence and confidence; then perform an architecture review. No result should be called edge proof from 21 selected trades.

## Explicit answers

1. **Lost:** explicit fresh-edge/risk accounting, late-chase caution, local 60m/240m extreme and opposing-zone preferences, broad-conflict/degraded-data UNCLEAR examples, bearish-expansion interpretation, VWAP conflict reporting, risk-adjusted confidence and enumerated setup classes. V2 retained generic verdicts, JSON and no-hindsight rules, and added filter/geometry explanation.
2. **Useful:** assess entry freshness, location/room, opposing evidence, local-versus-broad conflict, repaired bearish structure, and meaningful uncertainty. Their historical exact verdict preferences remain unproven.
3. **Old wording/schema:** `market_context.deltascout` paths, raw-local-time warning, specific setup labels if no longer governed, and “game” scoring language.
4. **Possible V1 bias:** “Prefer REJECT” on local extreme or nearby zone can over-reject breakouts; “Prefer UNCLEAR” on any broad conflict/degradation can overuse uncertainty; “UNCLEAR counts as reject-side” can tilt game reasoning. Earlier “bot side is favored” could rubber-stamp DeltaScout. These are risks, not observed causal effects.
5. **Possible V2 behavior:** generic REJECT/UNCLEAR boundary and missing calibration examples could change decisions; V2's long A/B explanation plus UNKNOWN filter and absent geometry may also create uncertainty. There is only one eligible recorded V2 verdict, so no current distribution or cause is established.
6. **Sufficiency:** current v39A window evidence is necessary but not sufficient for a full entry assessment. Historical actual verdicts used v1 monitor.
7. **Missing/misleading:** direct range position, VWAP/POC provenance, credible opposing distance and target room, broad coverage, one structure meaning, decision-time filter/geometry provenance, and correct readiness for incomplete windows. The two day-scoped historical 240m inputs were materially incomplete.
8. **Data shape:** better structured data with fewer duplicate classifications. Add missing derived facts and quality/lineage; avoid indiscriminate raw-history expansion.
9. **Teach:** how to weigh fresh edge against chase/location/room, adverse versus unavailable evidence, and confidence/rationale coherence.
10. **Do not teach:** automatic timeframe/zone vetoes, arbitrary thresholds, game scoring, guessed market facts, or outcomes.
11. **Production readiness:** no. We have 21 frozen research inputs but only 10 fully covered, non-day-corrupted canonical reconstructions; all lack proven pre-entry admission/geometry, pre-V2 deployed prompt hashes are not journaled, one V2 call exists, and matched model A/B was not authorized/run. Architecture review can proceed; prompt promotion needs the gate above.

**Research status: `CALIBRATION_RESEARCH_COMPLETE_READY_FOR_ARCHITECT_REVIEW`.**
