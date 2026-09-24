"""Research-only prompts for CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1.

The historical A/B/C artifact remains unchanged. This renderer adapts only
schema and timing references required by the post-fill canonical contract.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


RENDERER_VERSION = "GPT56_CANONICAL_PROMPT_RENDERER_V1"
SNAPSHOT_SCHEMA_VERSION = "CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1"
VARIANTS = ("A_CANONICAL", "B_CANONICAL", "C_CANONICAL")
SEMANTIC_SOURCES = {
    "A_CANONICAL": "LLM_ENTRY_PROMPT_V2 current decision semantics at ee30183; canonical schema/timing adaptation only",
    "B_CANONICAL": "last pre-V2 calibration semantics recovered from b366e19 and ae10ace^; canonical schema adaptation only",
    "C_CANONICAL": "minimal neutral canonical executed-entry assessor specified by GPT56_CANONICAL_PROMPT_ADAPTER_AND_REAL_TRADE_ABC_V1",
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "verdict": {"type": "string", "enum": ["SUPPORT", "REJECT", "UNCLEAR"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "setup_class": {"type": "string"},
        "reason_codes": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["verdict", "confidence", "setup_class", "reason_codes", "risk_flags", "summary"],
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(f"{SNAPSHOT_SCHEMA_VERSION} required")
    if not isinstance(snapshot.get("signal"), Mapping):
        raise ValueError("canonical signal block required")
    if not isinstance(snapshot.get("execution"), Mapping):
        raise ValueError("canonical execution block required")
    market = snapshot.get("market")
    if not isinstance(market, Mapping) or market.get("schema_version") != "market_monitor_snapshot_v39a":
        raise ValueError("canonical market block required")
    if not isinstance(snapshot.get("quality"), Mapping):
        raise ValueError("canonical quality block required")


_COMMON = (
    "\nCommon evidence contract:\n"
    "The supplied object is CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1. "
    "signal contains factual DeltaScout PEAK evidence; execution contains the actual Executor fill and the initial stop/target geometry known for this assessment; "
    "market contains closed observations no later than market_cutoff_utc; quality states completeness, degradation, reconstruction, units, and missing evidence.\n"
    "assessment_cutoff_utc can be null in a historical reconstruction because the exact old Judge invocation time was not durable. "
    "Do not treat a null cutoff or partial/degraded data as complete evidence.\n"
    "Actual entry and initial SL/TP geometry are allowed evidence. Do not infer or claim eventual TP/SL completion, trailing behavior, later price path, historical model verdict, PnL, or net profitability.\n"
    "Use the supplied units and provenance. Do not invent values for null or missing fields.\n"
    "Return only JSON matching the common output schema.\n"
)


_INSTRUCTIONS = {
    "A_CANONICAL": (
        "You are an entry quality assessor for an automated Binance trading signal.\n"
        "Make one assessment of the actual executed entry using only this snapshot.\n"
        "Use the signal facts, actual initial execution geometry, market evidence, units, and quality gaps together. "
        "The execution block is context for entry assessment, not an instruction to manage the position.\n"
        "SUPPORT means the DeltaScout direction has a clear edge. REJECT means the evidence argues against the executed entry. "
        "UNCLEAR means the edge cannot be assessed reliably.\n"
    ),
    "B_CANONICAL": (
        "You are LLM Trade Judge for an automated Binance execution engine.\n"
        "Judge only the quality of the actual executed entry represented by this snapshot.\n"
        "SUPPORT means the DeltaScout side is favored. REJECT means reject the trade thesis. "
        "If evidence is sufficient and the signal is weak or bad, use REJECT. Use UNCLEAR only when the edge still cannot be assessed after reading the supplied evidence.\n"
        "Calibrate strictly: SUPPORT requires clear, fresh directional edge after accounting for risk_flags. "
        "Do not use SUPPORT merely because local momentum agrees with DeltaScout when the actual entry is a late chase. "
        "Consider whether the direction is already stretched into the observed 60m/240m extrema, whether the PEAK evidence is weak or moderate, "
        "and whether a significant or liquidity zone immediately opposes continuation. "
        "Prefer UNCLEAR when broad 1d/3d/7d evidence conflicts with local flow, data quality is degraded or reconstructed, "
        "or zone evidence is mixed enough that edge is not reliable. Distinguish adverse evidence, which supports REJECT, from missing or genuinely mixed evidence, which supports UNCLEAR. "
        "If choosing SUPPORT with several material risk flags, lower confidence and explain why the risks are outweighed.\n"
        "If direction conflicts with signal VWAP/POC, canonical horizon vwap_approx, order flow, imbalance, structure state, or zone geometry, reflect it in reason_codes or risk_flags. "
        "POC can be unavailable; do not invent it.\n"
        "Use a concise setup_class such as continuation_pressure, reversal_onset, reversal_confirmation, exhaustion, trap_false_break, "
        "absorption_like, honest_directional_flow, noisy_peak, or unknown.\n"
    ),
    "C_CANONICAL": (
        "Assess the quality of this actual executed DeltaScout trade using the supplied signal facts, actual initial Executor geometry, and market state.\n"
        "Return SUPPORT, REJECT, or UNCLEAR. Weigh the supplied evidence and its quality yourself. "
        "Do not assume that any timeframe, indicator, classifier, or zone is automatically decisive. "
        "Do not apply an automatic zone veto or broad-context veto.\n"
    ),
}


def build_canonical_variant(name: str, snapshot: Mapping[str, Any]) -> str:
    _validate_snapshot(snapshot)
    if name not in VARIANTS:
        raise ValueError(f"unknown canonical prompt variant: {name}")
    return (
        _INSTRUCTIONS[name]
        + _COMMON
        + f"Output schema: {canonical_json(OUTPUT_SCHEMA)}\n"
        + f"Canonical trade evaluation snapshot: {canonical_json(snapshot)}"
    )


def prompt_record(name: str, snapshot: Mapping[str, Any]) -> dict[str, str]:
    prompt = build_canonical_variant(name, snapshot)
    return {
        "variant": name,
        "semantic_source": SEMANTIC_SOURCES[name],
        "renderer_version": RENDERER_VERSION,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "prompt": prompt,
    }


__all__ = [
    "OUTPUT_SCHEMA", "RENDERER_VERSION", "SEMANTIC_SOURCES", "SNAPSHOT_SCHEMA_VERSION",
    "VARIANTS", "build_canonical_variant", "canonical_json", "prompt_record",
]
