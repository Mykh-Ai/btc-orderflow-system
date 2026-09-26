"""Milestone decision contract over unchanged Snapshot V2 inputs."""
from __future__ import annotations

from typing import Any, Mapping

from docs.research.open_trade_outcome_predictor_v1.snapshot_v2 import (
    SCHEMA_VERSION, assert_model_view, canonical_json, sha256_text,
)


PROMPT_VERSION = "OPEN_TRADE_HIERARCHICAL_MILESTONE_V1"
Q1 = ("TP1_FIRST", "SL_FIRST", "UNCLEAR_MISSING_EVIDENCE")
Q2 = ("TP2_REACHED", "TP2_NOT_REACHED", "UNCLEAR_MISSING_EVIDENCE")
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "question_1": {"type": "string", "enum": list(Q1)},
        "question_2": {"type": ["string", "null"], "enum": [*Q2, None]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "primary_evidence_for": {"type": "array", "items": {"type": "string"}},
        "primary_evidence_against": {"type": "array", "items": {"type": "string"}},
        "uncertainty_reason": {"type": ["string", "null"]},
        "missing_evidence": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question_1", "question_2", "confidence", "primary_evidence_for",
                 "primary_evidence_against", "uncertainty_reason", "missing_evidence"],
}

INSTRUCTIONS = """You are a research predictor of milestones in an already opened trade before terminal closure.
Use only the attached pre-outcome Snapshot V2. Answer these questions in order.

QUESTION 1: Will TP1 be reached before the initial trade thesis terminates at SL?
Choose TP1_FIRST, SL_FIRST, or UNCLEAR_MISSING_EVIDENCE.

QUESTION 2: Only if question_1 is TP1_FIRST, conditional on TP1 being reached, will TP2 also be reached before the remaining trade terminates?
Choose TP2_REACHED, TP2_NOT_REACHED, or UNCLEAR_MISSING_EVIDENCE. Otherwise set question_2 to null.

This is not an entry recommendation, order-management instruction, or PnL prediction. Do not infer later price path, TP/SL completion, trailing state, historical verdict, or realized PnL. The signal and actual initial execution geometry are already known at prediction time. The historical prediction timestamp is a conservative Executor-observed fill proxy, not an exact former model-call timestamp. Market rows end at the stated closed-minute cutoff.

Evaluate price, Delta, fractional delta_pct, quantity, source OpenInterest, structure lifecycle, execution geometry, and quality together. Segment observations are non-overlapping. OpenInterest changes are endpoint differences, not additive. A zone or liquidity pool is not an automatic veto. Structure acceptance and returns are factual history before cutoff; infer continuation or rejection yourself. Do not invent values for missing evidence.

If evidence is mixed, confidence is low, or the market is difficult, still choose the applicable concrete milestone answer. Use UNCLEAR_MISSING_EVIDENCE only for a materially missing pre-outcome fact. For that answer, set a specific nonempty uncertainty_reason and use exact code(s) from quality.missing_evidence in missing_evidence. If quality.missing_evidence is empty, UNCLEAR_MISSING_EVIDENCE is invalid. For concrete answers, uncertainty_reason must be null and missing_evidence must be empty. Give specific pre-cutoff facts in primary_evidence_for and primary_evidence_against. Return only strict JSON matching the schema.
"""


def render(snapshot: Mapping[str, Any]) -> str:
    assert_model_view(snapshot)
    if snapshot["quality"].get("snapshot_schema_version") != SCHEMA_VERSION:
        raise ValueError("wrong frozen snapshot schema")
    prompt = INSTRUCTIONS + "\nOutput schema: " + canonical_json(OUTPUT_SCHEMA) + "\nSnapshot V2: " + canonical_json(snapshot)
    if any(label in prompt for label in ("NEGATIVE", "MIXED", "STRONG_FAVORABLE")):
        raise ValueError("direct lifecycle class leaked into milestone prompt")
    return prompt


def prompt_record(snapshot: Mapping[str, Any]) -> dict[str, str]:
    prompt = render(snapshot)
    return {"prompt_version": PROMPT_VERSION, "prompt_sha256": sha256_text(prompt), "prompt": prompt}


def validate_and_derive(value: Any, snapshot: Mapping[str, Any]) -> str:
    if not isinstance(value, dict) or set(value) != set(OUTPUT_SCHEMA["required"]):
        raise ValueError("strict output keys mismatch")
    first, second = value["question_1"], value["question_2"]
    if first not in Q1:
        raise ValueError("invalid question_1")
    if first == "TP1_FIRST":
        if second not in Q2:
            raise ValueError("question_2 required after TP1_FIRST")
    elif second is not None:
        raise ValueError("question_2 must be null unless TP1_FIRST")
    confidence = value["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence outside 0..1")
    for field in ("primary_evidence_for", "primary_evidence_against", "missing_evidence"):
        if not isinstance(value[field], list) or not all(isinstance(item, str) and item.strip() for item in value[field]):
            raise ValueError(f"invalid {field}")
    unclear = first == "UNCLEAR_MISSING_EVIDENCE" or second == "UNCLEAR_MISSING_EVIDENCE"
    if unclear:
        available = set(snapshot["quality"].get("missing_evidence") or [])
        if not isinstance(value["uncertainty_reason"], str) or not value["uncertainty_reason"].strip():
            raise ValueError("INVALID_UNCLEAR_CONTRACT: uncertainty_reason absent")
        if not value["missing_evidence"] or not available:
            raise ValueError("INVALID_UNCLEAR_CONTRACT: no missing required evidence")
        if not set(value["missing_evidence"]).issubset(available):
            raise ValueError("INVALID_UNCLEAR_CONTRACT: claimed evidence is present")
        return "UNCLEAR"
    if value["uncertainty_reason"] is not None or value["missing_evidence"]:
        raise ValueError("concrete answer cannot claim missing evidence")
    if first == "SL_FIRST":
        return "NEGATIVE"
    if second == "TP2_REACHED":
        return "STRONG_FAVORABLE"
    return "MIXED"
