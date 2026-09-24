"""Integrity checks for the research-only canonical A/B/C renderer."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from docs.research.gpt56_prompt_abc.canonical_prompt_variants import (
    RENDERER_VERSION,
    VARIANTS,
    build_canonical_variant,
    canonical_json,
    prompt_record,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "docs" / "research" / "canonical_trade_evaluation_snapshot" / "frozen_trade_evaluation_snapshots.jsonl"
MANIFEST = ROOT / "docs" / "research" / "gpt56_prompt_abc" / "eval_manifest_blind.csv"


def _first_eligible() -> tuple[dict, str]:
    manifest = {row["trade_key"]: row for row in csv.DictReader(MANIFEST.open(encoding="utf-8", newline=""))}
    for line in FROZEN.read_text(encoding="utf-8").splitlines():
        snapshot = json.loads(line)
        key = snapshot["signal"]["trade_key"]
        if manifest[key]["eligibility_status"] == "ELIGIBLE":
            assert hashlib.sha256(line.encode("utf-8")).hexdigest() == manifest[key]["snapshot_sha256"]
            return snapshot, line
    raise AssertionError("no eligible frozen snapshot")


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key).lower() for key in value} | set().union(*(_keys(child) for child in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(child) for child in value), set())
    return set()


def test_all_canonical_variants_accept_and_embed_identical_snapshot_bytes() -> None:
    snapshot, line = _first_eligible()
    before = canonical_json(snapshot)
    assert before == line
    suffix = "Canonical trade evaluation snapshot: " + before
    prompts = {name: build_canonical_variant(name, snapshot) for name in VARIANTS}
    assert all(prompt.endswith(suffix) for prompt in prompts.values())
    assert len({prompt.removesuffix(suffix) for prompt in prompts.values()}) == 3
    assert canonical_json(snapshot) == before
    assert hashlib.sha256(before.encode("utf-8")).hexdigest() == hashlib.sha256(line.encode("utf-8")).hexdigest()


def test_records_freeze_semantic_source_renderer_and_exact_prompt_hash() -> None:
    snapshot, _ = _first_eligible()
    for name in VARIANTS:
        record = prompt_record(name, snapshot)
        assert record["variant"] == name
        assert record["semantic_source"]
        assert record["renderer_version"] == RENDERER_VERSION
        assert record["prompt_sha256"] == hashlib.sha256(record["prompt"].encode("utf-8")).hexdigest()


def test_snapshot_contains_no_outcome_or_management_fields() -> None:
    forbidden = {
        "outcome", "historical_verdict", "pnl", "realized_pnl", "unrealized_pnl",
        "tp1_done", "tp2_done", "sl_done", "trailing", "trail", "close_reason",
    }
    for line in FROZEN.read_text(encoding="utf-8").splitlines():
        assert not (_keys(json.loads(line)) & forbidden)


def test_a_does_not_gain_historical_calibration_and_c_stays_neutral() -> None:
    snapshot, _ = _first_eligible()
    a = build_canonical_variant("A_CANONICAL", snapshot).split("\nCommon evidence contract:", 1)[0]
    b = build_canonical_variant("B_CANONICAL", snapshot).split("\nCommon evidence contract:", 1)[0]
    c = build_canonical_variant("C_CANONICAL", snapshot).split("\nCommon evidence contract:", 1)[0]
    assert "late chase" not in a.lower()
    assert "60m/240m" not in a
    assert "filter a" not in a.lower()
    assert "late chase" in b.lower()
    assert "60m/240m" in b
    assert "automatically decisive" in c
    assert "60m/240m" not in c
    assert "filter a" not in c.lower()


def test_wrong_schema_is_rejected_and_production_prompt_is_not_wired_to_renderer() -> None:
    with pytest.raises(ValueError, match="CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1 required"):
        build_canonical_variant("A_CANONICAL", {"schema_version": "LLM_ENTRY_SNAPSHOT_V2"})
    entry_source = (ROOT / "executor_mod" / "entry_snapshot.py").read_text(encoding="utf-8")
    judge_source = (ROOT / "executor_mod" / "llm_trade_judge.py").read_text(encoding="utf-8")
    assert 'PROMPT_VERSION = "LLM_ENTRY_PROMPT_V2"' in entry_source
    assert "canonical_prompt_variants" not in entry_source
    assert "canonical_prompt_variants" not in judge_source
