"""One independent GPT-5.6 Sol response per frozen open-trade prompt.

This module does not import outcome data or any evaluation module.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .predictor_prompt import OUTPUT_SCHEMA, validate_prediction
from .remote_transport import call_on_server
from .snapshot_v2 import assert_model_view, canonical_json, sha256_text


MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 4000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def _text(response: dict[str, Any]) -> str:
    for item in response.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("response has no output_text")


def _call(prompt: str, api_key: str, ssh_host: str | None = None) -> tuple[dict[str, Any], int]:
    payload = {
        "model": MODEL, "input": prompt, "reasoning": {"effort": REASONING_EFFORT},
        "text": {"format": {"type": "json_schema", "name": "open_trade_outcome_prediction", "strict": True, "schema": OUTPUT_SCHEMA}},
        "max_output_tokens": MAX_OUTPUT_TOKENS, "store": False,
    }
    if ssh_host:
        response, status = call_on_server(ssh_host, payload)
        assert status is not None
        return response, status
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses", data=canonical_json(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8")), int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body), int(exc.code)
        except json.JSONDecodeError:
            return {"unparsed_error_body": body}, int(exc.code)


def _verify_bundle(directory: Path) -> list[tuple[dict[str, str], dict, dict]]:
    metadata = json.loads((directory / "run_metadata.json").read_text(encoding="utf-8"))
    source_dir = Path(__file__).resolve().parent
    for name, key in (("prepare_blind.py", "builder_sha256_lf_normalized"),
                      ("snapshot_v2.py", "snapshot_builder_sha256_lf_normalized"),
                      ("predictor_prompt.py", "prompt_source_sha256_lf_normalized")):
        value = (source_dir / name).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
        if sha256_text(value) != metadata[key]:
            raise ValueError(f"frozen research source changed: {name}")
    if metadata["output_schema"] != OUTPUT_SCHEMA or metadata["model"] != MODEL or metadata["reasoning_effort"] != REASONING_EFFORT:
        raise ValueError("frozen model-call contract changed")
    snapshots_path = directory / "frozen_model_view_snapshots.jsonl"
    prompts_path = directory / "frozen_prompts.jsonl"
    if hashlib.sha256(snapshots_path.read_bytes()).hexdigest() != metadata["snapshots_file_sha256"]:
        raise ValueError("frozen snapshots file changed")
    if hashlib.sha256(prompts_path.read_bytes()).hexdigest() != metadata["prompts_file_sha256"]:
        raise ValueError("frozen prompts file changed")
    snapshots = {}
    for line in snapshots_path.read_text(encoding="utf-8").splitlines():
        snapshot = json.loads(line)
        assert_model_view(snapshot)
        snapshots[snapshot["signal"]["trade_key"]] = (snapshot, sha256_text(line))
    prompts = {item["trade_key"]: item for item in _read_jsonl(prompts_path)}
    with (directory / "blind_manifest.csv").open(encoding="utf-8", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    if len(manifest) != metadata["planned_calls"] or len(snapshots) != len(manifest) or len(prompts) != len(manifest):
        raise ValueError("blind cohort cardinality changed")
    pairs = []
    for row in manifest:
        key = row["trade_key"]
        snapshot, digest = snapshots[key]
        prompt = prompts[key]
        if digest != row["snapshot_sha256"] or prompt["snapshot_sha256"] != digest:
            raise ValueError(f"snapshot identity changed: {key}")
        if sha256_text(prompt["prompt"]) != row["prompt_sha256"] or prompt["prompt_sha256"] != row["prompt_sha256"]:
            raise ValueError(f"prompt identity changed: {key}")
        pairs.append((row, snapshot, prompt))
    return pairs


def _blind_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = ("trade_key", "model_requested", "model_returned", "reasoning_effort", "snapshot_sha256", "prompt_sha256", "request_timestamp", "response_id", "predicted_outcome_class", "confidence", "primary_evidence_for", "primary_evidence_against", "uncertainty_reason", "missing_evidence", "error")
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: canonical_json(record.get(field)) if field in {"primary_evidence_for", "primary_evidence_against", "missing_evidence"} else record.get(field, "") for field in fields})
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def run(directory: Path, ssh_host: str | None = None) -> None:
    pairs = _verify_bundle(directory)
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key and not ssh_host:
        raise SystemExit("BLOCKED_BY_MODEL_EXECUTION: OPENAI_API_KEY absent")
    if ssh_host:
        call_on_server(ssh_host)
    attempts_path = directory / "attempts.jsonl"
    raw_path = directory / "raw_results.jsonl"
    attempts = _read_jsonl(attempts_path)
    records = _read_jsonl(raw_path)
    completed = {row["trade_key"] for row in records}
    started = {row["trade_key"] for row in attempts if row.get("status") == "STARTED"}
    if started - completed:
        raise RuntimeError(f"unresolved STARTED; refusing repeat calls: {sorted(started - completed)}")
    if len(completed) != len(records):
        raise RuntimeError("duplicate blind result")
    expected = {row["trade_key"]: row for row, _, _ in pairs}
    for record in records:
        row = expected.get(record["trade_key"])
        if row is None or record.get("snapshot_sha256") != row["snapshot_sha256"] or record.get("prompt_sha256") != row["prompt_sha256"]:
            raise RuntimeError("existing blind result does not match frozen manifest")
    for row, snapshot, prompt in pairs:
        key = row["trade_key"]
        if key in completed:
            continue
        request_time = _now()
        _append(attempts_path, {"trade_key": key, "status": "STARTED", "request_timestamp": request_time,
                                "snapshot_sha256": row["snapshot_sha256"], "prompt_sha256": row["prompt_sha256"]})
        start = time.monotonic()
        response: dict[str, Any] = {}
        http_status = None
        parsed: dict[str, Any] = {}
        error = ""
        try:
            response, http_status = _call(prompt["prompt"], api_key, ssh_host)
            if http_status != 200:
                error = f"openai_http_{http_status}"
            elif response.get("status") != "completed":
                error = f"response_status_{response.get('status')}"
            else:
                parsed = json.loads(_text(response))
                validate_prediction(parsed, snapshot)
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        record = {
            "schema_version": "OPEN_TRADE_OUTCOME_RAW_RESULT_V1", "trade_key": key,
            "model_requested": MODEL, "model_returned": response.get("model"),
            "reasoning_effort": REASONING_EFFORT, "snapshot_sha256": row["snapshot_sha256"],
            "prompt_sha256": row["prompt_sha256"], "request_timestamp": request_time,
            "response_id": response.get("id"), "http_status": http_status,
            "elapsed_seconds": round(time.monotonic() - start, 6),
            "token_usage": response.get("usage"), "error": error,
            "transport": "ssh_server_key" if ssh_host else "local_api_key",
            "raw_response": response, **parsed,
        }
        _append(raw_path, record)
        _append(attempts_path, {"trade_key": key, "status": "COMPLETED", "completed_at": _now(),
                                "response_id": response.get("id"), "error": error})
        records.append(record)
        completed.add(key)
        _blind_csv(directory / "predictions_blind.csv", records)
        print(f"{len(records)}/{len(pairs)} {key} {error or parsed['predicted_outcome_class']}", flush=True)
    print(f"BLIND_CALLS_COMPLETE calls={len(records)} errors={sum(bool(row.get('error')) for row in records)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--ssh-host", help="SSH host with /root/volume-alert/.executor.env")
    args = parser.parse_args()
    run(args.bundle, args.ssh_host)


if __name__ == "__main__":
    main()
