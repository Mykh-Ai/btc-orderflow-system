"""One independent server-key model call per frozen milestone prompt; no outcomes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from docs.research.open_trade_outcome_predictor_v1.remote_transport import call_on_server
from docs.research.open_trade_outcome_predictor_v1.run_blind import (
    MAX_OUTPUT_TOKENS, MODEL, REASONING_EFFORT, _append, _now, _read_jsonl, _text, _verify_bundle,
)
from docs.research.open_trade_outcome_predictor_v1.snapshot_v2 import sha256_text

from .milestone_prompt import OUTPUT_SCHEMA, PROMPT_VERSION, prompt_record, validate_and_derive
from .prepare import SOURCE_BUNDLE, _check_committed_source, _sha_normalized


def _verify(directory: Path) -> list[tuple[dict[str, str], dict, dict]]:
    _check_committed_source()
    source_pairs = _verify_bundle(SOURCE_BUNDLE)
    metadata = json.loads((directory / "run_metadata.json").read_text(encoding="utf-8"))
    if (metadata["model"], metadata["reasoning_effort"], metadata["output_schema"], metadata["prompt_version"]) != (
        MODEL, REASONING_EFFORT, OUTPUT_SCHEMA, PROMPT_VERSION
    ):
        raise ValueError("frozen model contract changed")
    if _sha_normalized(Path(__file__).with_name("milestone_prompt.py")) != metadata["prompt_source_sha256_lf_normalized"]:
        raise ValueError("milestone prompt source changed")
    if _sha_normalized(Path(__file__).with_name("prepare.py")) != metadata["builder_sha256_lf_normalized"]:
        raise ValueError("milestone prompt builder changed")
    if hashlib.sha256((SOURCE_BUNDLE / "frozen_model_view_snapshots.jsonl").read_bytes()).hexdigest() != metadata["source_snapshots_sha256"]:
        raise ValueError("frozen Snapshot V2 bytes changed")
    if hashlib.sha256((SOURCE_BUNDLE / "blind_manifest.csv").read_bytes()).hexdigest() != metadata["source_manifest_sha256"]:
        raise ValueError("source blind manifest bytes changed")
    prompts_path = directory / "frozen_prompts.jsonl"
    manifest_path = directory / "blind_manifest.csv"
    if hashlib.sha256(prompts_path.read_bytes()).hexdigest() != metadata["prompts_file_sha256"]:
        raise ValueError("frozen prompts changed")
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != metadata["manifest_file_sha256"]:
        raise ValueError("frozen manifest changed")
    prompts = {item["trade_key"]: item for item in _read_jsonl(prompts_path)}
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    if len(source_pairs) != len(manifest) or len(prompts) != len(manifest) or len(manifest) != metadata["planned_calls"]:
        raise ValueError("paired cohort cardinality changed")
    pairs = []
    for (old_row, snapshot, _), row in zip(source_pairs, manifest, strict=True):
        key = old_row["trade_key"]
        prompt = prompts[key]
        if row["trade_key"] != key or row["snapshot_sha256"] != old_row["snapshot_sha256"]:
            raise ValueError("snapshot identity changed")
        rendered = prompt_record(snapshot)
        if prompt != {"trade_key": key, "snapshot_sha256": row["snapshot_sha256"], **rendered}:
            raise ValueError("prompt rendering changed")
        if row["prompt_sha256"] != sha256_text(prompt["prompt"]):
            raise ValueError("prompt hash changed")
        pairs.append((row, snapshot, prompt))
    if sum(row["score_eligible"] == "true" for row, _, _ in pairs) != metadata["scored_calls"]:
        raise ValueError("scoring cohort changed")
    return pairs


def _blind_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = ("trade_key", "question_1", "question_2", "derived_outcome_class", "confidence",
              "snapshot_sha256", "prompt_sha256", "response_id", "model_returned", "error")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def run(directory: Path, ssh_host: str) -> None:
    pairs = _verify(directory)
    call_on_server(ssh_host)  # credential/model preflight, no prompt sent
    attempts_path = directory / "attempts.jsonl"
    raw_path = directory / "raw_results.jsonl"
    attempts = _read_jsonl(attempts_path)
    records = _read_jsonl(raw_path)
    completed = {r["trade_key"] for r in records}
    started = {r["trade_key"] for r in attempts if r.get("status") == "STARTED"}
    if started - completed:
        raise RuntimeError(f"unresolved STARTED; refusing repeat calls: {sorted(started - completed)}")
    if len(completed) != len(records):
        raise RuntimeError("duplicate blind result")
    expected = {row["trade_key"]: row for row, _, _ in pairs}
    for record in records:
        row = expected.get(record["trade_key"])
        if row is None or record.get("snapshot_sha256") != row["snapshot_sha256"] or record.get("prompt_sha256") != row["prompt_sha256"]:
            raise RuntimeError("existing blind result does not match manifest")
    for row, snapshot, prompt in pairs:
        key = row["trade_key"]
        if key in completed:
            continue
        request_time = _now()
        _append(attempts_path, {"trade_key": key, "status": "STARTED", "request_timestamp": request_time,
                                "snapshot_sha256": row["snapshot_sha256"], "prompt_sha256": row["prompt_sha256"]})
        started_at = time.monotonic()
        payload = {
            "model": MODEL, "input": prompt["prompt"], "reasoning": {"effort": REASONING_EFFORT},
            "text": {"format": {"type": "json_schema", "name": "open_trade_milestone_prediction", "strict": True, "schema": OUTPUT_SCHEMA}},
            "max_output_tokens": MAX_OUTPUT_TOKENS, "store": False,
        }
        response: dict[str, Any] = {}
        http_status = None
        parsed: dict[str, Any] = {}
        derived = None
        error = ""
        try:
            response, http_status = call_on_server(ssh_host, payload)
            if http_status != 200:
                error = f"openai_http_{http_status}"
            elif response.get("status") != "completed":
                error = f"response_status_{response.get('status')}"
            else:
                parsed = json.loads(_text(response))
                derived = validate_and_derive(parsed, snapshot)
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        record = {
            "schema_version": "HIERARCHICAL_MILESTONE_RAW_RESULT_V1", "trade_key": key,
            "model_requested": MODEL, "model_returned": response.get("model"),
            "reasoning_effort": REASONING_EFFORT, "snapshot_sha256": row["snapshot_sha256"],
            "prompt_sha256": row["prompt_sha256"], "request_timestamp": request_time,
            "response_id": response.get("id"), "http_status": http_status,
            "elapsed_seconds": round(time.monotonic() - started_at, 6),
            "token_usage": response.get("usage"), "error": error,
            "derived_outcome_class": derived, "transport": "ssh_server_key",
            "raw_response": response, **parsed,
        }
        _append(raw_path, record)
        _append(attempts_path, {"trade_key": key, "status": "COMPLETED", "completed_at": _now(),
                                "response_id": response.get("id"), "error": error})
        records.append(record)
        completed.add(key)
        _blind_csv(directory / "predictions_blind.csv", records)
        print(f"{len(records)}/{len(pairs)} {key} {error or (parsed.get('question_1'), parsed.get('question_2'))}", flush=True)
    print(f"MILESTONE_BLIND_CALLS_COMPLETE calls={len(records)} errors={sum(bool(r.get('error')) for r in records)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--ssh-host", required=True)
    args = parser.parse_args()
    run(args.bundle, args.ssh_host)


if __name__ == "__main__":
    main()
