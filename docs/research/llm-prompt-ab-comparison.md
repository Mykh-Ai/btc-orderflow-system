# Research-only prompt comparison protocol

**Status: NOT_RUN.** No authorized GPT-5.5 API/model calls were made. Historical verdicts are observational records produced with different prompts, market regimes and input quality; they are not a same-input A/B result.

## Frozen inputs and separation

- `llm-frozen-preentry-snapshots.jsonl` contains 21 unique model-input JSON objects, one per eligible real-model success. Each was replayed read-only from the production feed through the repository's v1 base builder on continuous 1440 closed minutes and the production v39A window builder, with up to 30 days of context. The research snapshot adds explicit base structure/broad context and a formula-derived 60m/240m range position; these additions are **research-only**, not claims about the deployed V2 payload.
- `llm-feed-source-hashes.csv` records SHA-256 and size for the 155 daily production feed files read in the replay. It is provenance only and is not model input.
- Historical verdicts and later outcomes appear only in `llm-canonical-case-set.csv`. None of its outcome fields is inside the frozen JSONL. Post-entry fill, order, PnL and management fields were withheld. Legacy local-time `ts` fields were removed; normalized UTC signal/cutoff fields remain. A recursive timestamp check found no frozen timestamp after the decision cutoff.
- All 21 have complete 5/15/30/60/240/1440m current windows. Input classes: {'INPUT_INSUFFICIENT': 9, 'INPUT_RECONSTRUCTABLE_CANONICAL': 10, 'INPUT_HISTORICALLY_CORRUPTED': 2}. Two old day-scoped 240m windows were actually incomplete: `EX_EN_1785025567` (27/240 rows) and `EX_EN_1789351940` (133/240). Both have complete canonical 240m replay, so their recorded historical verdicts must not be used to judge old prompt quality. Nine cases lack complete 30d context; one of these (`EX_EN_1778813539`) has a verdict creation time 7161 seconds **before** its claimed cutoff. Their reconstructed input remains frozen for diagnostics, not primary A/B scoring.
- Every reconstructed entry snapshot has `UPSTREAM_FILTER_PROVENANCE_MISSING` and `INCOMPLETE_EXECUTION_GEOMETRY` because the durable evidence cannot prove those were available before the decision. V2 explains these fields at length. A prompt experiment on such inputs could measure response to missing data as much as calibration quality. Recover pre-entry admission and planned geometry provenance before interpreting outcome alignment.

## Variants

All variants receive the identical frozen JSON for a case, identical seven-field V2 output schema, model `gpt-5.5`, and the same call parameters (`max_output_tokens=2000`; no temperature override). Do not substitute a different model. Repeat each case three times if output variance is observed; keep prompts and input hashes fixed. Randomize variant order with a recorded seed and record raw output, parsed output, model metadata and errors. Never send the case CSV to the model.

### A — CURRENT V2

Exact `HEAD:executor_mod/entry_snapshot.py` source function, lines 304–317. Invoke `build_entry_prompt(snapshot)` on the frozen snapshot. Source:

```python
def build_entry_prompt(snapshot: Mapping[str, Any]) -> str:
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise EntrySnapshotError("Prompt requires LLM_ENTRY_SNAPSHOT_V2")
    return (
        "You are an entry quality assessor for an automated Binance trading signal.\n"
        "Make one assessment at decision_cutoff_utc using only this snapshot.\n"
        "The snapshot is pre-entry only. Do not infer later prices, fills, outcomes, or management actions.\n"
        "The execution_geometry block is known at entry and describes planned risk distance and target distances; it is context, not an instruction to manage the position.\n"
        "The upstream_admission block explains two upstream loss-avoidance checks. Filter A rejects a weak same-side PEAK when same_side_peak_percentile_24h <= 50.0. Filter B rejects when trusted OI falls over 60m and direction-adjusted delta over 240m is below 0.06. A or B is a blocker; PASS means the blocker condition was false, BLOCK means it matched, and UNKNOWN means the value was unavailable. Treat UNKNOWN as uncertainty, not as PASS.\n"
        "Use the monitor fields, units, quality gaps, and filter definitions together. Do not invent values for null, partial, recovered, or missing data.\n"
        "SUPPORT means the bot direction has a clear edge. REJECT means the evidence argues against entry. UNCLEAR means the edge cannot be assessed reliably. Return only JSON matching the schema.\n"
        f"Output schema: {_canonical(output_schema())}\n"
        f"Entry snapshot: {_canonical(snapshot)}"
    )
```

### B — LAST PRE-V2 SEMANTICS

Only field names and the common schema/cutoff wrapper are adapted. The verdict preferences, game framing and setup taxonomy are retained deliberately; this is a historical comparison, not a recommended prompt.

```text
You are LLM Trade Judge for an automated Binance execution engine.
Judge only the trade signal quality at decision_cutoff_utc using this entry snapshot. Do not infer future outcomes or suggest changing live orders.
The snapshot includes signal, market.context, and market.monitor_snapshot. The monitor has local 15m/60m/240m context, broad 1d/3d/7d/30d context, market state, market_structure_state, zones, liquidity zones, data-quality flags, and context conflicts. market_structure_state is repaired 37E state evidence with range_pct, close_position, dominant_side, and range_quality; use it to avoid misreading bearish expansion as range/support.
SUPPORT means the bot side is favored. REJECT means reject the bot trade. UNCLEAR counts as reject-side in the game. If market.context is sufficient and the signal is weak or bad, use REJECT. Use UNCLEAR only when the edge still cannot be assessed after reading market.context.
Calibrate verdict strictly: SUPPORT requires clear, fresh directional edge after accounting for risk_flags. Do not use SUPPORT merely because local momentum agrees with the bot when the entry is a late chase. Prefer REJECT when the bot direction is already stretched into a local 60m/240m extreme, the peak is weak or moderate, or a significant liquidity/market zone immediately opposes continuation. Prefer UNCLEAR when broad 1d/3d/7d context conflicts with local flow, data quality is degraded/recovered, or zone evidence is mixed enough that edge is not reliable. If you still choose SUPPORT with multiple material risk_flags, lower confidence and explain why those risks are outweighed.
If direction conflicts with VWAP, rolling_vwap_approx, or orderflow/imbalance context, reflect it in reason_codes or risk_flags.
Allowed setup_class values: continuation_pressure, reversal_onset, reversal_confirmation, exhaustion, trap_false_break, absorption_like, honest_directional_flow, noisy_peak, unknown.
Return only JSON matching the supplied common output schema.
Entry snapshot follows:
{{SNAPSHOT_JSON}}
```

### C — MINIMAL HYBRID

The late-entry, location/room, conflict and uncertainty concepts have a defensible decision purpose even though their historical preferences may over-reject. C keeps these concepts without automatic timeframe/zone vetoes or outcome-fitted thresholds.

```text
You assess whether the bot direction has a clear, fresh entry edge at decision_cutoff_utc. Use only the frozen pre-entry snapshot and the common output schema.
Consider local flow together with 60m/240m range position, distance to credible opposing structure and available target room. Directional agreement alone does not establish a good entry. Treat broader context as evidence about risk and uncertainty, not an automatic veto.
Use REJECT for material evidence against the entry; use UNCLEAR when data quality, missing facts or genuinely mixed evidence prevents a reliable assessment. If SUPPORT is chosen despite material risks, explain why the favorable evidence outweighs them and reflect uncertainty in confidence.
Do not infer later prices, fills, outcomes or management actions. Do not invent absent market facts, thresholds or zone strength.
Return only JSON matching the supplied common output schema.
Entry snapshot follows:
{{SNAPSHOT_JSON}}
```

## Evaluation plan and present evidence

Primary cohort: 10 `INPUT_RECONSTRUCTABLE_CANONICAL` cases. The two `INPUT_HISTORICALLY_CORRUPTED` cases are a separate input-quality sensitivity cohort. The nine `INPUT_INSUFFICIENT` cases are diagnostics only. For each model run, score discrimination by verdict distribution and case diversity; sensitivity to canonical delta/OI/range position, opposing-zone distance, target room and broad quality; summary/verdict coherence; confidence ordering; and collapse labels `RUBBER_STAMP_DELTASCOUT`, `OVER_REJECT`, `OVER_USE_UNCLEAR`, `OVERWEIGHT_BROAD_CONTEXT`, `OVERWEIGHT_LOCAL_MOMENTUM`, `OVERWEIGHT_ZONE_PROXIMITY`. Target-room and explicit structure-distance sensitivity cannot be scored until those facts are supplied.

Static input variation exists: 240m delta_pct ranges from -0.083059 to +0.153295 (fraction), OI change from -1477.70 to +1884.27, and research-derived 240m range position from 0.003649 to 1.0. This shows inputs differ; it is **not** model sensitivity evidence.

Historical observational counts only (not A/B): {'UNCLEAR': 4, 'SUPPORT': 11, 'REJECT': 6}. `SUPPORT`: {'unverified': 1, 'tp1_tp2_trailing_stop': 2, 'plain_sl': 5, 'tp1_sl': 3}; `REJECT`: {'plain_sl': 5, 'tp1_tp2_trailing_stop': 1}; `UNCLEAR`: {'unverified': 1, 'tp1_tp2_trailing_stop': 2, 'tp1_sl': 1}. Thus recorded SUPPORT includes 5 plain SL and 2 TP1+TP2+trail lifecycles; REJECT includes 5 plain SL and 1 strong favorable lifecycle; UNCLEAR includes 2 strong favorable lifecycles, 1 mixed and 1 outcome with no execution snapshot. Gross PnL is present for three of the five strong lifecycles; net PnL is null in partial exchange snapshots, so no net-win claim follows. Prompt-era inference from commit dates is {'PRE_CALIBRATION_COMMIT_DEPLOY_UNVERIFIED': 13, 'POST_CALIBRATION_COMMIT_DEPLOY_UNVERIFIED': 7, 'V2_RECORDED': 1}; exact deployed pre-V2 prompt hashes were not persisted. There is one recorded eligible V2 verdict (`UNCLEAR`) and no contemporaneous matched V1 call.

**No discrimination, confidence, coherence, causal outcome-alignment or bias result for A/B/C is available while calls are NOT_RUN.** A small, nonrandom historical cohort cannot establish trading edge or a production prompt.
