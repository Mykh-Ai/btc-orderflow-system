"""Research-only prompt variants for one frozen canonical entry snapshot.

No API calls are made here. The production prompt and model setting are untouched.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from executor_mod.entry_snapshot import build_entry_prompt, output_schema


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def build_variant(name: str, snapshot: Mapping[str, Any]) -> str:
    if snapshot.get("schema_version") != "LLM_ENTRY_SNAPSHOT_V2":
        raise ValueError("Canonical LLM entry snapshot required")
    if snapshot.get("market", {}).get("monitor_snapshot", {}).get("schema_version") != "market_monitor_snapshot_v39a":
        raise ValueError("Canonical 39A monitor required")
    if name == "A":
        return build_entry_prompt(snapshot)
    if name == "B":
        instruction = (
            "You are LLM Trade Judge for an automated Binance execution engine.\n"
            "Judge only entry-time signal quality at decision_cutoff_utc. Use only this canonical snapshot. "
            "Do not infer future prices, fills, outcomes, or management actions; do not suggest live order changes.\n"
            "The snapshot contains a DeltaScout candidate, canonical Market Monitor windows, broad context, "
            "market_state, market_structure_state, structure and zones. Read market_structure_state.metrics "
            "and its state so bearish expansion is not misread as range/support.\n"
            "SUPPORT means the bot side is favored. REJECT means reject the bot trade. "
            "UNCLEAR counts as reject-side in the game. If context is sufficient and the signal is weak or bad, "
            "use REJECT. Use UNCLEAR only when the edge still cannot be assessed after reading the context.\n"
            "Calibrate strictly: SUPPORT requires clear, fresh directional edge after accounting for risk_flags. "
            "Do not use SUPPORT merely because local momentum agrees with the bot when the entry is a late chase. "
            "Prefer REJECT when the direction is stretched into a local 60m/240m extreme, the PEAK is weak "
            "or moderate, or a significant liquidity/market zone immediately opposes continuation. "
            "Prefer UNCLEAR when broad 1d/3d/7d context conflicts with local flow, data quality is degraded "
            "or recovered, or zone evidence is mixed enough that edge is not reliable. "
            "If choosing SUPPORT with multiple material risk_flags, lower confidence and explain why risks are outweighed.\n"
            "If direction conflicts with signal VWAP, canonical window vwap_approx or orderflow/imbalance, "
            "reflect it in reason_codes or risk_flags. POC may be unavailable; do not invent it.\n"
            "Allowed setup_class values: continuation_pressure, reversal_onset, reversal_confirmation, "
            "exhaustion, trap_false_break, absorption_like, honest_directional_flow, noisy_peak, unknown.\n"
        )
    elif name == "C":
        instruction = (
            "Assess the DeltaScout LONG/SHORT candidate at decision_cutoff_utc using only this canonical "
            "pre-entry market snapshot. Weigh available market evidence and its quality to return SUPPORT, "
            "REJECT, or UNCLEAR with a coherent confidence, reason_codes, risk_flags, and brief summary. "
            "Do not assume any horizon, zone, or indicator is an automatic veto or endorsement. "
            "Do not invent missing values or infer later prices, fills, outcomes, or management actions. "
            "Return only JSON matching the schema.\n"
        )
    else:
        raise ValueError(f"Unknown prompt variant: {name}")
    return instruction + f"Output schema: {_json(output_schema())}\nEntry snapshot: {_json(snapshot)}"


__all__ = ["build_variant"]
