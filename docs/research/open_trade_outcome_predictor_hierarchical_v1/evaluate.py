"""Paired post-checkpoint evaluation of direct and hierarchical decisions."""
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

from docs.research.open_trade_outcome_predictor_v1.evaluate_development import (
    LIFECYCLE_LEDGER, TRUE_CLASSES, PREDICTED_CLASSES, _truth,
)
from docs.research.open_trade_outcome_predictor_v1.run_blind import _read_jsonl
from docs.research.open_trade_outcome_predictor_v1.snapshot_v2 import canonical_json

from .prepare import ROOT, SOURCE_BUNDLE, SOURCE_COMMIT
from .run import _verify


def _checkpoint_bytes(commit: str, path: Path) -> bytes:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    result = subprocess.run(["git", "show", f"{commit}:{relative}"], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise ValueError(f"checkpoint missing {relative} at {commit}")
    return result.stdout


def _verify_checkpoint(commit: str, paths: list[Path]) -> dict[str, str]:
    hashes = {}
    for path in paths:
        local = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        committed = _checkpoint_bytes(commit, path).replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if local != committed:
            raise ValueError(f"blind artifact differs from committed checkpoint: {path}")
        hashes[path.name] = hashlib.sha256(local).hexdigest()
    return hashes


def _metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    confusion = {true: {pred: 0 for pred in PREDICTED_CLASSES} for true in TRUE_CLASSES}
    counts = Counter()
    predicted = Counter()
    for row in rows:
        true, pred = row["true_lifecycle"], row[field]
        confusion[true][pred] += 1
        counts[true] += 1
        predicted[pred] += 1
    per_class = {}
    for category in TRUE_CLASSES:
        tp = confusion[category][category]
        recall = tp / counts[category] if counts[category] else 0.0
        precision = tp / predicted[category] if predicted[category] else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[category] = {"precision": precision, "recall": recall, "f1": f1}
    return {
        "n": len(rows), "true_class_counts": dict(counts), "predicted_class_counts": dict(predicted),
        "confusion_matrix": confusion, "per_class": per_class,
        "raw_accuracy": sum(row["true_lifecycle"] == row[field] for row in rows) / len(rows),
        "balanced_accuracy": statistics.mean(item["recall"] for item in per_class.values()),
        "macro_f1": statistics.mean(item["f1"] for item in per_class.values()),
    }


def evaluate(bundle: Path, blind_commit: str, output: Path) -> dict[str, Any]:
    pairs = _verify(bundle)
    new_paths = [bundle / name for name in (
        "frozen_prompts.jsonl", "blind_manifest.csv", "run_metadata.json",
        "attempts.jsonl", "raw_results.jsonl", "predictions_blind.csv")]
    new_hashes = _verify_checkpoint(blind_commit, new_paths)
    old_paths = [SOURCE_BUNDLE / name for name in (
        "frozen_model_view_snapshots.jsonl", "blind_manifest.csv", "attempts.jsonl",
        "raw_results.jsonl", "predictions_blind.csv")]
    old_hashes = _verify_checkpoint(SOURCE_COMMIT, old_paths)
    current = {r["trade_key"]: r for r in _read_jsonl(bundle / "raw_results.jsonl")}
    previous = {r["trade_key"]: r for r in _read_jsonl(SOURCE_BUNDLE / "raw_results.jsonl")}
    attempts = _read_jsonl(bundle / "attempts.jsonl")
    if len(current) != len(pairs) or len(previous) != len(pairs) or len(attempts) != 2 * len(pairs):
        raise ValueError("paired blind calls incomplete")
    for row, _, _ in pairs:
        key = row["trade_key"]
        item = current[key]
        if item["error"] or previous[key]["error"]:
            raise ValueError("blind response error")
        if item["snapshot_sha256"] != row["snapshot_sha256"] or item["prompt_sha256"] != row["prompt_sha256"]:
            raise ValueError("blind response identity mismatch")
        if [x["status"] for x in attempts if x["trade_key"] == key] != ["STARTED", "COMPLETED"]:
            raise ValueError("durable call sequence invalid")
    # Only now may the evaluator open the outcome ledger.
    with LIFECYCLE_LEDGER.open(encoding="utf-8", newline="") as stream:
        ledger = {row["trade_key"]: row for row in csv.DictReader(stream)}
    cases = []
    for row, _, _ in pairs:
        key = row["trade_key"]
        truth = _truth(ledger.get(key, {}))
        if truth not in TRUE_CLASSES:
            raise ValueError(f"unknown ground truth: {key}")
        old, new = previous[key], current[key]
        cases.append({
            "trade_key": key, "score_eligible": row["score_eligible"] == "true",
            "true_lifecycle": truth,
            "direct_class": old["predicted_outcome_class"], "direct_confidence": old["confidence"],
            "question_1": new["question_1"], "question_2": new["question_2"],
            "hierarchical_class": new["derived_outcome_class"], "hierarchical_confidence": new["confidence"],
        })
    primary = [case for case in cases if case["score_eligible"]]
    paired = Counter()
    for case in primary:
        old_correct = case["direct_class"] == case["true_lifecycle"]
        new_correct = case["hierarchical_class"] == case["true_lifecycle"]
        paired[(old_correct, new_correct)] += 1
    q1_correct = sum(case["question_1"] == ("SL_FIRST" if case["true_lifecycle"] == "NEGATIVE" else "TP1_FIRST") for case in primary)
    q2_applicable = [case for case in primary if case["question_1"] == "TP1_FIRST" and case["true_lifecycle"] != "NEGATIVE"]
    q2_correct = sum((case["question_2"] == "TP2_REACHED") == (case["true_lifecycle"] == "STRONG_FAVORABLE") for case in q2_applicable)
    report = {
        "status": "HISTORICAL_DEVELOPMENT_ABLATION_ONLY",
        "new_blind_checkpoint": blind_commit, "direct_blind_checkpoint": SOURCE_COMMIT,
        "new_blind_artifact_sha256_lf_normalized": new_hashes,
        "direct_blind_artifact_sha256_lf_normalized": old_hashes,
        "primary_excluded_trade_key": next(case["trade_key"] for case in cases if not case["score_eligible"]),
        "primary_eligible_count": len(primary),
        "direct_primary": _metrics(primary, "direct_class"),
        "hierarchical_primary": _metrics(primary, "hierarchical_class"),
        "direct_all_20_for_audit": _metrics(cases, "direct_class"),
        "hierarchical_all_20_for_audit": _metrics(cases, "hierarchical_class"),
        "question_1_primary_correct": q1_correct, "question_1_primary_n": len(primary),
        "question_2_primary_correct_conditional_on_predicted_tp1_and_actual_tp1": q2_correct,
        "question_2_primary_n_conditional_on_predicted_tp1_and_actual_tp1": len(q2_applicable),
        "paired_correctness": {
            "both_correct": paired[(True, True)], "direct_only": paired[(True, False)],
            "hierarchical_only": paired[(False, True)], "both_wrong": paired[(False, False)],
        },
        "cases": cases,
        "limitations": [
            "same historical 20 trades were inspected before prompt redesign; this is not a holdout",
            "one frozen snapshot has a proven timezone interpretation defect and is excluded from primary scoring for both prompts",
            "historical fill timestamp is a proxy for exact prediction-call time",
            "failure of one prompt form does not prove the frozen features contain no predictive signal",
        ],
    }
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--blind-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.bundle, args.blind_commit, args.output)
    print(canonical_json({k: report[k] for k in ("primary_eligible_count", "direct_primary", "hierarchical_primary", "paired_correctness")}))


if __name__ == "__main__":
    main()
