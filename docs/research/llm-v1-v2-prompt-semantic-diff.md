# LLM Trade Judge: last pre-V2 prompt versus V2

Research-only audit, 2026-09-20. Sources are Git blobs, not the modified working tree. The last pre-V2 prompt is the function at `ae10ace^` (equivalent to `6288f1e` for this file); V2 first appears in `ae10acef` on 2026-09-11. “V1” below means this last historical prompt, not a persisted prompt-version identifier.

## Git evidence

`git status` found pre-existing uncommitted production/test edits; none is used as the source for this diff. `git log --oneline -n 50` identifies `b366e19` (2026-06-29) and `ae10ace` (2026-09-11). Required `git log -p -S` searches for “Calibrate verdict strictly”, “late chase”, “local 60m/240m extreme”, “Prefer UNCLEAR”, and “bearish expansion” all show addition in `b366e19` and removal in `ae10ace`. `git blame` assigns old calibration lines 1040–1045 and repaired structure lines 1027–1029 to `b366e19`; V2 lines 304–317 to `ae10ace`. The test assertions on those concepts were added with the implementation in `b366e19`; they corroborate intent, but do not prove efficacy.

## Literal source diff

The complete prompt-building function blocks are diffed below. The evidence JSON is dynamic; source code, rather than a fabricated filled example, is compared.

```diff
--- ae10ace^:executor_mod/llm_trade_judge.py:1019-1050
+++ HEAD:executor_mod/entry_snapshot.py:304-317
@@ -1,35 +1,16 @@
-def build_llm_trade_judge_prompt(evidence_pack: Dict[str, Any]) -> str:
+def build_entry_prompt(snapshot: Mapping[str, Any]) -> str:
+    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
+        raise EntrySnapshotError("Prompt requires LLM_ENTRY_SNAPSHOT_V2")
     return (
-        "You are LLM Trade Judge for an automated Binance execution engine.\n"
-        "Judge only the trade signal quality at entry time.\n"
-        "You only see information available until analysis_cutoff_ts, which is normalized UTC.\n"
-        "peak_ts_raw may be legacy feed local time. Do not use raw timestamps for filtering; use analysis_cutoff_ts.\n"
-        "The evidence pack includes src_evt/current PEAK, market_context.deltascout, and market_context.aggregated.\n"
-        "The evidence pack may include market_monitor_snapshot: a descriptive pre-cutoff Market Monitor snapshot "
-        "with local 15m/60m/240m context, broad 1d/3d/7d/30d context, market state, market_structure_state, "
-        "zones, liquidity zones, data-quality flags, and context conflicts. market_structure_state is repaired 37E state evidence "
-        "with range_pct, close_position, dominant_side, and range_quality; use it to avoid misreading bearish expansion as range/support. "
-        "It is not a trading instruction and must not modify live orders.\n"
-        "All market_context and market_monitor_snapshot records are intended to be pre-cutoff only; "
-        "do not use or infer data after analysis_cutoff_ts.\n"
-        "Do not infer future outcome. Do not mention whether the trade won or lost.\n"
-        "The LLM is advisory only and must not suggest changing live orders.\n"
-        "Return only JSON, no markdown.\n"
-        "Allowed verdict values: SUPPORT, REJECT, UNCLEAR.\n"
-        "SUPPORT means the bot side is favored. REJECT means reject the bot trade. "
-        "UNCLEAR counts as reject-side in the game. If market_context is sufficient and the signal is weak or bad, use REJECT. "
-        "Use UNCLEAR only when the edge still cannot be assessed after reading market_context.\n"
-        "Calibrate verdict strictly: SUPPORT requires clear, fresh directional edge after accounting for risk_flags. "
-        "Do not use SUPPORT merely because local momentum agrees with the bot when the entry is a late chase. "
-        "Prefer REJECT when the bot direction is already stretched into a local 60m/240m extreme, the peak is weak or moderate, "
-        "or a significant liquidity/market zone immediately opposes continuation. Prefer UNCLEAR when broad 1d/3d/7d context "
-        "conflicts with local flow, data quality is degraded/recovered, or zone evidence is mixed enough that edge is not reliable. "
-        "If you still choose SUPPORT with multiple material risk_flags, lower confidence and explain why those risks are outweighed.\n"
-        "If direction conflicts with VWAP, rolling_vwap_approx, or orderflow/imbalance context, reflect it in reason_codes or risk_flags.\n"
-        "Allowed setup_class values: continuation_pressure, reversal_onset, reversal_confirmation, "
-        "exhaustion, trap_false_break, absorption_like, honest_directional_flow, noisy_peak, unknown.\n"
-        "Evidence pack follows:\n"
-        f"{json.dumps(evidence_pack, ensure_ascii=False, separators=(',', ':'), default=str)}"
+        "You are an entry quality assessor for an automated Binance trading signal.\n"
+        "Make one assessment at decision_cutoff_utc using only this snapshot.\n"
+        "The snapshot is pre-entry only. Do not infer later prices, fills, outcomes, or management actions.\n"
+        "The execution_geometry block is known at entry and describes planned risk distance and target distances; it is context, not an instruction to manage the position.\n"
+        "The upstream_admission block explains two upstream loss-avoidance checks. Filter A rejects a weak same-side PEAK when same_side_peak_percentile_24h <= 50.0. Filter B rejects when trusted OI falls over 60m and direction-adjusted delta over 240m is below 0.06. A or B is a blocker; PASS means the blocker condition was false, BLOCK means it matched, and UNKNOWN means the value was unavailable. Treat UNKNOWN as uncertainty, not as PASS.\n"
+        "Use the monitor fields, units, quality gaps, and filter definitions together. Do not invent values for null, partial, recovered, or missing data.\n"
+        "SUPPORT means the bot direction has a clear edge. REJECT means the evidence argues against entry. UNCLEAR means the edge cannot be assessed reliably. Return only JSON matching the schema.\n"
+        f"Output schema: {_canonical(output_schema())}\n"
+        f"Entry snapshot: {_canonical(snapshot)}"
     )


```

## Semantic changes

| Decision concept | Last pre-V2 | V2 | Assessment |
|---|---|---|---|
| Entry edge | “clear, fresh directional edge after accounting for risk_flags” | “clear edge” | Freshness and risk accounting no longer explicit. Useful concept, not validated as an outcome rule. |
| Late chase | Local momentum alone must not justify SUPPORT for a late entry | No example or check | Useful anti-rubber-stamp guard. Requires range position and room, not a blanket REJECT. |
| 60m/240m extreme | “Prefer REJECT” when already stretched | No equivalent | Useful geometry question; the old preference could over-reject valid breakouts and sometimes read day-scoped incomplete windows. |
| Broad conflict | “Prefer UNCLEAR” when 1d/3d/7d context conflicts with local flow | Generic UNCLEAR definition | Conflict was uncertainty/risk, not an automatic veto. Must distinguish strong counterevidence from noisy context. |
| Opposing zone | “Prefer REJECT” when significant zone immediately opposes continuation | Monitor fields only | Useful if zone distance, strength and target room are proven; wording may overweight an unqualified zone. |
| Bearish expansion | Repaired 37E state: range_pct, close_position, dominant_side, range_quality; avoid calling bearish expansion support/range | No explicit interpretation instruction | The `b366e19` code changed structure classification and added a regression test, so this was a data/classification repair plus prompt cue. V2 v39A wraps a legacy structure value inside `market_state`, but does not expose an unambiguous top-level repaired structure contract. |
| UNCLEAR boundary | Use UNCLEAR only when edge still cannot be assessed; weak/bad signal with sufficient context => REJECT | Generic “cannot be assessed reliably” | Partial preservation; useful distinction between adverse evidence and missing/mixed evidence. |
| Multiple risk flags | SUPPORT requires lower confidence and an explanation why risks are outweighed | No equivalent | Useful coherence check; hard confidence rule would be arbitrary. |
| VWAP/flow conflict | Mention conflict in reason_codes/risk_flags | No equivalent | Useful evidence accounting, but depends on clean VWAP/POC and source. |
| Output | Enumerated setup_class values, JSON only | JSON schema but setup_class unconstrained string | JSON shape preserved; semantic setup classes are no longer constrained. |
| Scope/time | UTC cutoff, raw local timestamp warning, no future outcomes/orders | Decision cutoff and pre-entry boundary | Intent preserved and clearer in V2. Raw local timestamps should be removed from input rather than explained in prompt. |
| Game framing | UNCLEAR “counts as reject-side in the game” | Removed | Correct to remove from entry assessor; it can bias toward REJECT. |
| Upstream filters | Not specified | Detailed A/B definitions and UNKNOWN handling | New V2 material, not a loss. Their unavailable historical provenance is an input gap, not prompt efficacy evidence. |

The literal diff proves instruction loss; it does not prove that V1 outperformed V2. Only one eligible real V2 call is recorded, and no same-input model A/B has been run.
