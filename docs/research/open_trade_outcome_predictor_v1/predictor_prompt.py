"""Frozen research prompt and output validation for open-trade outcomes."""
from __future__ import annotations

from typing import Any, Mapping

from .snapshot_v2 import SCHEMA_VERSION, assert_model_view, canonical_json, sha256_text


PROMPT_VERSION = "OPEN_TRADE_OUTCOME_PREDICTOR_V1"
CLASSES = ("NEGATIVE", "MIXED", "STRONG_FAVORABLE", "UNCLEAR")
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "predicted_outcome_class": {"type": "string", "enum": list(CLASSES)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "primary_evidence_for": {"type": "array", "items": {"type": "string"}},
        "primary_evidence_against": {"type": "array", "items": {"type": "string"}},
        "uncertainty_reason": {"type": ["string", "null"]},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["predicted_outcome_class", "confidence", "primary_evidence_for", "primary_evidence_against", "uncertainty_reason", "missing_evidence"],
}


INSTRUCTIONS = """You are a research predictor of the furthest lifecycle milestone reached by an already opened trade before terminal closure.
Use only the attached pre-outcome Snapshot V2. Predict one of:
- NEGATIVE: terminal SL without TP1.
- MIXED: TP1 reached but TP2 not reached.
- STRONG_FAVORABLE: TP2 reached regardless of later trailing or SL management.
- UNCLEAR: a specific required pre-outcome fact is unavailable and materially prevents classification.

This is not an entry recommendation, order-management instruction, or PnL prediction. Do not infer later price path, TP/SL completion, trailing state, historical verdict, or realized PnL. The signal and actual initial execution geometry are already known at prediction time. The historical prediction timestamp is a conservative Executor-observed fill proxy, not an exact former model-call timestamp. Market rows end at the stated closed-minute cutoff.

Evaluate price, Delta, fractional delta_pct, quantity, source OpenInterest, structure lifecycle, execution geometry, and quality together. Segment observations are non-overlapping. OpenInterest changes are endpoint differences, not additive. A zone or liquidity pool is not an automatic veto. Structure acceptance and returns are factual history before cutoff; infer continuation or rejection yourself. Do not invent values for missing evidence.

If evidence is mixed, confidence is low, or the market is difficult, still choose NEGATIVE, MIXED, or STRONG_FAVORABLE. Use UNCLEAR only for a materially missing pre-outcome fact. For UNCLEAR, set a specific nonempty uncertainty_reason and use exact code(s) from quality.missing_evidence in missing_evidence. If quality.missing_evidence is empty, UNCLEAR is invalid. For another class, uncertainty_reason must be null and missing_evidence must be empty. Give specific pre-cutoff facts in primary_evidence_for and primary_evidence_against. Return only strict JSON matching the schema.
"""


def render(snapshot: Mapping[str, Any]) -> str:
    assert_model_view(snapshot)
    if snapshot["quality"].get("snapshot_schema_version") != SCHEMA_VERSION:
        raise ValueError("wrong snapshot schema")
    return INSTRUCTIONS + "\nOutput schema: " + canonical_json(OUTPUT_SCHEMA) + "\nSnapshot V2: " + canonical_json(snapshot)


def prompt_record(snapshot: Mapping[str, Any]) -> dict[str, str]:
    prompt = render(snapshot)
    return {"prompt_version": PROMPT_VERSION, "prompt_sha256": sha256_text(prompt), "prompt": prompt}


def validate_prediction(value: Any, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(OUTPUT_SCHEMA["required"]):
        raise ValueError("strict output keys mismatch")
    category = value["predicted_outcome_class"]
    if category not in CLASSES:
        raise ValueError("unknown prediction class")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence outside 0..1")
    for field in ("primary_evidence_for", "primary_evidence_against", "missing_evidence"):
        if not isinstance(value[field], list) or not all(isinstance(item, str) and item.strip() for item in value[field]):
            raise ValueError(f"invalid {field}")
    if category == "UNCLEAR":
        available_missing = set(snapshot["quality"].get("missing_evidence") or [])
        if not isinstance(value["uncertainty_reason"], str) or not value["uncertainty_reason"].strip():
            raise ValueError("INVALID_UNCLEAR_CONTRACT: uncertainty_reason absent")
        if not value["missing_evidence"] or not available_missing:
            raise ValueError("INVALID_UNCLEAR_CONTRACT: no missing required evidence")
        if not set(value["missing_evidence"]).issubset(available_missing):
            raise ValueError("INVALID_UNCLEAR_CONTRACT: claimed evidence is present")
    elif value["uncertainty_reason"] is not None or value["missing_evidence"]:
        raise ValueError("non-UNCLEAR cannot claim missing evidence")
    return value
