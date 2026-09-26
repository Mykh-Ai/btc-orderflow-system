"""Unblind only after a committed, complete blind prediction checkpoint."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .predictor_prompt import validate_prediction
from .run_blind import MODEL, REASONING_EFFORT, _read_jsonl, _verify_bundle
from .snapshot_v2 import canonical_json


ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_LEDGER = ROOT / "docs/research/canonical_trade_evaluation_snapshot/case_ledger.csv"
TRUE_CLASSES = ("NEGATIVE", "MIXED", "STRONG_FAVORABLE")
PREDICTED_CLASSES = (*TRUE_CLASSES, "UNCLEAR")


def _committed_bytes(commit: str, path: Path) -> bytes:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    result = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise ValueError(f"blind checkpoint missing {relative} at {commit}")
    return result.stdout


def _verify_checkpoint(commit: str, bundle: Path) -> dict[str, str]:
    digests = {}
    for name in ("frozen_model_view_snapshots.jsonl", "frozen_prompts.jsonl", "blind_manifest.csv",
                 "run_metadata.json", "attempts.jsonl", "raw_results.jsonl", "predictions_blind.csv"):
        path = bundle / name
        local = path.read_bytes()
        committed = _committed_bytes(commit, path)
        # Windows checkout can convert text line endings. Normalize only that
        # transport difference; content and row order must remain identical.
        normalized = lambda value: value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalized(local) != normalized(committed):
            raise ValueError(f"blind artifact differs from checkpoint: {name}")
        digests[name] = hashlib.sha256(normalized(local)).hexdigest()
    return digests


def _truth(row: dict[str, str]) -> str:
    tp1 = str(row.get("tp1_done", "")).strip().lower()
    tp2 = str(row.get("tp2_done", "")).strip().lower()
    if tp2 == "true":
        return "STRONG_FAVORABLE"
    if tp1 == "true" and tp2 == "false":
        return "MIXED"
    if tp1 == "false" and tp2 == "false" and str(row.get("outcome_reason", "")).strip().upper() == "SL":
        return "NEGATIVE"
    return "UNKNOWN"


def _distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def evaluate(bundle: Path, checkpoint: str, output: Path) -> dict[str, Any]:
    pairs = _verify_bundle(bundle)
    artifacts = _verify_checkpoint(checkpoint, bundle)
    records = _read_jsonl(bundle / "raw_results.jsonl")
    attempts = _read_jsonl(bundle / "attempts.jsonl")
    if len(records) != len(pairs) or len(attempts) != 2 * len(pairs):
        raise ValueError("blind calls are incomplete")
    by_key = {record["trade_key"]: record for record in records}
    if len(by_key) != len(records):
        raise ValueError("duplicate blind prediction")
    for row, _, _ in pairs:
        result = by_key[row["trade_key"]]
        if result.get("model_returned") != MODEL or result.get("reasoning_effort") != REASONING_EFFORT:
            raise ValueError("model-call identity mismatch")
        if result.get("error") and "INVALID_UNCLEAR_CONTRACT" not in result["error"]:
            raise ValueError("blind model call failed")
        statuses = [item["status"] for item in attempts if item["trade_key"] == row["trade_key"]]
        if statuses != ["STARTED", "COMPLETED"]:
            raise ValueError("durable call sequence invalid")
    with LIFECYCLE_LEDGER.open(encoding="utf-8", newline="") as stream:
        ledger = {row["trade_key"]: row for row in csv.DictReader(stream)}
    confusion = {true: {pred: 0 for pred in PREDICTED_CLASSES} for true in TRUE_CLASSES}
    truth_counts = Counter()
    predicted_counts = Counter()
    right_confidence = []
    wrong_confidence = []
    unknown_ground_truth = []
    misses = []
    unclear_audit = []
    for row, snapshot, _ in pairs:
        key = row["trade_key"]
        result = by_key[key]
        predicted = result.get("predicted_outcome_class")
        truth = _truth(ledger.get(key, {}))
        if truth == "UNKNOWN":
            unknown_ground_truth.append(key)
            continue
        if predicted not in PREDICTED_CLASSES:
            raise ValueError(f"invalid predicted class: {key}")
        confusion[truth][predicted] += 1
        truth_counts[truth] += 1
        predicted_counts[predicted] += 1
        confidence = float(result["confidence"])
        (right_confidence if predicted == truth else wrong_confidence).append(confidence)
        if predicted == "UNCLEAR":
            prediction = {field: result.get(field) for field in (
                "predicted_outcome_class", "confidence", "primary_evidence_for",
                "primary_evidence_against", "uncertainty_reason", "missing_evidence",
            )}
            try:
                validate_prediction(prediction, snapshot)
                status = "VALID_MISSING_EVIDENCE"
            except ValueError:
                status = "INVALID_UNCLEAR_CONTRACT"
            unclear_audit.append({"trade_key": key, "status": status,
                                  "claimed_missing_evidence": result.get("missing_evidence"),
                                  "actual_missing_evidence": snapshot["quality"].get("missing_evidence")})
        if predicted != truth:
            misses.append({"trade_key": key, "frozen_prediction": predicted, "confidence": confidence,
                           "frozen_primary_evidence_for": result.get("primary_evidence_for"),
                           "frozen_primary_evidence_against": result.get("primary_evidence_against"),
                           "true_lifecycle": truth})
    support = sum(truth_counts.values())
    per_class = {}
    for category in TRUE_CLASSES:
        true_positive = confusion[category][category]
        recall = true_positive / truth_counts[category] if truth_counts[category] else 0.0
        precision = true_positive / predicted_counts[category] if predicted_counts[category] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[category] = {"precision": precision, "recall": recall, "f1": f1}
    report = {
        "status": "DEVELOPMENT_EVALUATION_ONLY", "blind_checkpoint": checkpoint,
        "blind_artifact_sha256_lf_normalized": artifacts,
        "cohort_size": len(pairs), "known_ground_truth_count": support,
        "unknown_ground_truth": unknown_ground_truth,
        "true_class_counts": dict(truth_counts), "predicted_class_counts": dict(predicted_counts),
        "confusion_matrix": confusion, "per_class": per_class,
        "macro_f1": statistics.mean(item["f1"] for item in per_class.values()),
        "balanced_accuracy": statistics.mean(item["recall"] for item in per_class.values()),
        "raw_accuracy": len(right_confidence) / support if support else None,
        "unclear_count": predicted_counts["UNCLEAR"],
        "invalid_unclear_count": sum(item["status"] == "INVALID_UNCLEAR_CONTRACT" for item in unclear_audit),
        "confidence_correct": _distribution(right_confidence),
        "confidence_incorrect": _distribution(wrong_confidence),
        "unclear_audit": unclear_audit, "misclassified_cases": misses,
        "limitations": ["historical 20-trade development cohort; outcomes previously inspected by humans",
                        "historical Executor-observed fill proxy; exact prediction call time unavailable",
                        "prospective new-trade holdout required before predictive claim"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--blind-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.bundle, args.blind_commit, args.output)
    print(canonical_json({key: report[key] for key in ("known_ground_truth_count", "raw_accuracy", "macro_f1", "balanced_accuracy", "invalid_unclear_count")}))


if __name__ == "__main__":
    main()
