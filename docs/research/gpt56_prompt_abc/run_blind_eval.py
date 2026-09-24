"""Run one independent GPT-5.6 Sol call per frozen trade/prompt variant.

This runner never reads lifecycle outcomes. It binds the immutable A/B/C
instruction text to the immutable post-fill snapshot through one shared
research adapter, then writes each attempt durably before starting the next.
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

from docs.research.gpt56_prompt_abc.canonical_prompt_variants import (
    OUTPUT_SCHEMA as EVAL_SCHEMA,
    RENDERER_VERSION,
    SEMANTIC_SOURCES,
    VARIANTS,
    canonical_json as _canonical,
    prompt_record,
)


MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "medium"
MAX_OUTPUT_TOKENS = 4000
TEXT_FILE_HASH_CONTRACT = "UTF8_LF_NORMALIZED_SHA256_V1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _utf8_lf_normalized_bytes(value: bytes) -> bytes:
    """Return UTF-8 bytes with every text line ending normalized to LF."""
    text = value.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _sha256_utf8_lf_normalized_bytes(value: bytes) -> str:
    return _sha256_bytes(_utf8_lf_normalized_bytes(value))


def _sha256_utf8_lf_normalized_file(path: Path) -> str:
    return _sha256_utf8_lf_normalized_bytes(path.read_bytes())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(_canonical(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_snapshots(path: Path) -> dict[str, tuple[dict[str, Any], str]]:
    result: dict[str, tuple[dict[str, Any], str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        snapshot = json.loads(line)
        if snapshot.get("schema_version") != "CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1":
            raise ValueError("unexpected frozen snapshot schema")
        trade_key = str((snapshot.get("signal") or {}).get("trade_key") or "")
        if not trade_key or trade_key in result:
            raise ValueError("missing or duplicate frozen trade_key")
        result[trade_key] = (snapshot, _sha256_text(line))
    return result


def _load_eligible(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if list(rows[0]) != ["trade_key", "snapshot_sha256", "eligibility_status", "exclusion_reason"]:
        raise ValueError("blind manifest columns changed")
    eligible = [row for row in rows if row["eligibility_status"] == "ELIGIBLE"]
    if any(row["exclusion_reason"] for row in eligible):
        raise ValueError("eligible row has exclusion reason")
    return eligible


def _freeze_prompts(path: Path, eligible: list[dict[str, str]], snapshots: dict[str, tuple[dict[str, Any], str]]) -> list[dict[str, str]]:
    prompts: list[dict[str, str]] = []
    rendered_lines: list[str] = []
    for row in eligible:
        key = row["trade_key"]
        if key not in snapshots:
            raise ValueError(f"eligible snapshot missing: {key}")
        snapshot, actual_hash = snapshots[key]
        if actual_hash != row["snapshot_sha256"]:
            raise ValueError(f"snapshot hash mismatch: {key}")
        for variant in VARIANTS:
            rendered = prompt_record(variant, snapshot)
            prompt = rendered["prompt"]
            item = {
                "trade_key": key,
                "variant": variant,
                "semantic_source": rendered["semantic_source"],
                "renderer_version": rendered["renderer_version"],
                "snapshot_sha256": actual_hash,
                "prompt_sha256": rendered["prompt_sha256"],
                "prompt": prompt,
            }
            prompts.append(item)
            rendered_lines.append(_canonical(item))
    frozen = "\n".join(rendered_lines) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != frozen:
        raise ValueError("rendered prompts changed after freeze")
    path.write_text(frozen, encoding="utf-8", newline="\n")
    return prompts


def _output_text(response: dict[str, Any]) -> str:
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("response has no output_text")


def _validate_parsed(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(EVAL_SCHEMA["required"]):
        raise ValueError("parsed output keys do not match strict schema")
    if value["verdict"] not in {"SUPPORT", "REJECT", "UNCLEAR"}:
        raise ValueError("invalid verdict")
    confidence = float(value["confidence"])
    if not 0 <= confidence <= 1:
        raise ValueError("confidence outside 0..1")
    if not isinstance(value["setup_class"], str) or not isinstance(value["summary"], str):
        raise ValueError("invalid text fields")
    if not all(isinstance(item, str) for field in ("reason_codes", "risk_flags") for item in value[field]):
        raise ValueError("invalid list fields")
    value["confidence"] = confidence
    return value


def _call_api(prompt: str, api_key: str) -> tuple[dict[str, Any], int]:
    payload = {
        "model": MODEL,
        "input": prompt,
        "reasoning": {"effort": REASONING_EFFORT},
        "text": {"format": {"type": "json_schema", "name": "trade_evaluation", "strict": True, "schema": EVAL_SCHEMA}},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=_canonical(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read().decode("utf-8")
            return json.loads(body), int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            raw: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError:
            raw = {"unparsed_error_body": body}
        return raw, int(exc.code)


def _write_blind_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fields = [
        "trade_key", "variant", "model_requested", "model_returned", "reasoning_effort",
        "snapshot_sha256", "prompt_sha256", "request_timestamp", "response_id", "verdict",
        "confidence", "setup_class", "reason_codes", "risk_flags", "summary", "token_usage", "error",
    ]
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({
                field: _canonical(record.get(field)) if field in {"reason_codes", "risk_flags", "token_usage"} else record.get(field, "")
                for field in fields
            })
    os.replace(temp, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "raw_results.jsonl"
    attempts_path = output / "attempts.jsonl"
    prompts_path = output / "rendered_prompts.jsonl"
    blind_csv = output / "verdicts_blind.csv"
    eligible = _load_eligible(args.manifest)
    snapshots = _load_snapshots(args.snapshots)
    prompts = _freeze_prompts(prompts_path, eligible, snapshots)
    metadata = {
        "schema_version": "GPT56_PROMPT_ABC_RUN_METADATA_V1",
        "created_at": _utc_now(), "model": MODEL, "reasoning_effort": REASONING_EFFORT,
        "max_output_tokens": MAX_OUTPUT_TOKENS, "eligible_trade_count": len(eligible),
        "planned_call_count": len(prompts), "variants": list(VARIANTS), "output_schema": EVAL_SCHEMA,
        "source_text_hash_contract": TEXT_FILE_HASH_CONTRACT,
        "manifest_sha256": _sha256_utf8_lf_normalized_file(args.manifest),
        "snapshots_file_sha256": _sha256_utf8_lf_normalized_file(args.snapshots),
        "renderer_version": RENDERER_VERSION,
        "renderer_source_sha256": _sha256_utf8_lf_normalized_file(args.renderer),
        "semantic_sources": SEMANTIC_SOURCES,
        "adapter": "canonical_snapshot_native_renderer",
        "previous_response_id_used": False, "tools_supplied": False,
    }
    metadata_path = output / "run_metadata.json"
    if metadata_path.exists():
        prior = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key in set(metadata) - {"created_at"}:
            if prior.get(key) != metadata.get(key):
                raise ValueError(f"run metadata changed: {key}")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.prepare_only:
        print(f"BLIND_PROMPTS_FROZEN trades={len(eligible)} prompts={len(prompts)}", flush=True)
        return
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("BLOCKED_BY_API_ACCESS")
    attempts = _load_jsonl(attempts_path)
    records = _load_jsonl(raw_path)
    completed = {(str(row["trade_key"]), str(row["variant"])) for row in records}
    started = {(str(row["trade_key"]), str(row["variant"])) for row in attempts if row.get("status") == "STARTED"}
    ambiguous = started - completed
    if ambiguous:
        raise RuntimeError(f"refusing possible repeat calls for unresolved attempts: {sorted(ambiguous)}")
    for prompt_item in prompts:
        pair = (prompt_item["trade_key"], prompt_item["variant"])
        if pair in completed:
            continue
        request_timestamp = _utc_now()
        _append_jsonl(attempts_path, {
            "trade_key": pair[0], "variant": pair[1], "status": "STARTED",
            "request_timestamp": request_timestamp, "snapshot_sha256": prompt_item["snapshot_sha256"],
            "prompt_sha256": prompt_item["prompt_sha256"],
        })
        started_at = time.monotonic()
        raw_response: dict[str, Any] = {}
        http_status: int | None = None
        error = ""
        parsed: dict[str, Any] = {}
        try:
            raw_response, http_status = _call_api(prompt_item["prompt"], api_key)
            if http_status != 200:
                error = f"openai_http_{http_status}"
            elif raw_response.get("status") != "completed":
                error = f"response_status_{raw_response.get('status')}"
            else:
                parsed = _validate_parsed(json.loads(_output_text(raw_response)))
        except Exception as exc:  # One attempt only: record and continue.
            error = f"{type(exc).__name__}:{exc}"
        record = {
            "schema_version": "GPT56_PROMPT_ABC_RAW_RESULT_V1",
            "trade_key": pair[0], "variant": pair[1], "model_requested": MODEL,
            "model_returned": raw_response.get("model"), "reasoning_effort": REASONING_EFFORT,
            "snapshot_sha256": prompt_item["snapshot_sha256"], "prompt_sha256": prompt_item["prompt_sha256"],
            "request_timestamp": request_timestamp, "response_id": raw_response.get("id"),
            "verdict": parsed.get("verdict"), "confidence": parsed.get("confidence"),
            "setup_class": parsed.get("setup_class"), "reason_codes": parsed.get("reason_codes", []),
            "risk_flags": parsed.get("risk_flags", []), "summary": parsed.get("summary"),
            "token_usage": raw_response.get("usage"), "http_status": http_status,
            "elapsed_seconds": round(time.monotonic() - started_at, 6), "error": error,
            "raw_response": raw_response,
        }
        _append_jsonl(raw_path, record)
        _append_jsonl(attempts_path, {
            "trade_key": pair[0], "variant": pair[1], "status": "COMPLETED",
            "completed_at": _utc_now(), "response_id": raw_response.get("id"), "error": error,
        })
        records.append(record)
        completed.add(pair)
        _write_blind_csv(blind_csv, records)
        print(f"{len(records)}/{len(prompts)} {pair[0]} {pair[1]} {'ERROR '+error if error else parsed['verdict']}", flush=True)
    if len(records) != len(prompts):
        raise RuntimeError("blind evaluation incomplete")
    print(f"BLIND_CALLS_COMPLETE count={len(records)} errors={sum(bool(row.get('error')) for row in records)}", flush=True)


if __name__ == "__main__":
    main()
