"""Freeze milestone prompts from the exact committed V1 Snapshot V2 cohort."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
from pathlib import Path

from docs.research.open_trade_outcome_predictor_v1.prepare_blind import _freeze, _sha_normalized
from docs.research.open_trade_outcome_predictor_v1.run_blind import MODEL, REASONING_EFFORT, _verify_bundle
from docs.research.open_trade_outcome_predictor_v1.snapshot_v2 import canonical_json, sha256_text

from .milestone_prompt import OUTPUT_SCHEMA, PROMPT_VERSION, prompt_record


ROOT = Path(__file__).resolve().parents[3]
SOURCE_BUNDLE = ROOT / "docs/research/open_trade_outcome_predictor_v1/blind_run_v3"
SOURCE_COMMIT = "0c740d094e53b8bc29dd35eb8041e7dfe5fe1011"
CHRONOLOGY_EXCLUSION = "EX_EN_1779900918"


def _check_committed_source() -> None:
    for name in ("frozen_model_view_snapshots.jsonl", "blind_manifest.csv"):
        path = SOURCE_BUNDLE / name
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:{relative}"], cwd=ROOT)
        normalize = lambda value: value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        if normalize(committed) != normalize(path.read_bytes()):
            raise ValueError(f"committed Snapshot V2 source changed: {name}")


def prepare(output: Path) -> dict:
    _check_committed_source()
    pairs = _verify_bundle(SOURCE_BUNDLE)
    if len(pairs) != 20 or CHRONOLOGY_EXCLUSION not in {row["trade_key"] for row, _, _ in pairs}:
        raise ValueError("frozen paired cohort changed")
    prompts = []
    manifest = []
    for row, snapshot, _ in pairs:
        rendered = prompt_record(snapshot)
        prompts.append(canonical_json({"trade_key": row["trade_key"], "snapshot_sha256": row["snapshot_sha256"], **rendered}))
        manifest.append({"trade_key": row["trade_key"], "snapshot_sha256": row["snapshot_sha256"],
                         "prompt_sha256": rendered["prompt_sha256"],
                         "score_eligible": "false" if row["trade_key"] == CHRONOLOGY_EXCLUSION else "true"})
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(manifest[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(manifest)
    metadata = {
        "schema_version": "HIERARCHICAL_MILESTONE_BLIND_PREPARATION_V1",
        "source_commit": SOURCE_COMMIT,
        "source_snapshots_sha256": hashlib.sha256((SOURCE_BUNDLE / "frozen_model_view_snapshots.jsonl").read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256((SOURCE_BUNDLE / "blind_manifest.csv").read_bytes()).hexdigest(),
        "prompt_source_sha256_lf_normalized": _sha_normalized(Path(__file__).with_name("milestone_prompt.py")),
        "builder_sha256_lf_normalized": _sha_normalized(Path(__file__)),
        "prompt_version": PROMPT_VERSION, "output_schema": OUTPUT_SCHEMA,
        "model": MODEL, "reasoning_effort": REASONING_EFFORT,
        "store": False, "tools": False, "previous_response_id": False, "retries": False,
        "planned_calls": len(pairs), "scored_calls": len(pairs) - 1,
        "chronology_exclusion": CHRONOLOGY_EXCLUSION,
        "prompts_file_sha256": sha256_text("\n".join(prompts) + "\n"),
        "manifest_file_sha256": sha256_text(buffer.getvalue()),
    }
    _freeze(output / "frozen_prompts.jsonl", "\n".join(prompts) + "\n")
    _freeze(output / "blind_manifest.csv", buffer.getvalue())
    _freeze(output / "run_metadata.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    _freeze(output / "precall_inspection.json", json.dumps([
        {"trade_key": row["trade_key"], "score_eligible": row["score_eligible"],
         "snapshot_sha256": row["snapshot_sha256"], "prompt_sha256": row["prompt_sha256"]}
        for row in (manifest[0], manifest[3], manifest[-1])
    ], ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return metadata


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.output)
    print(f"MILESTONE_PROMPTS_FROZEN calls={result['planned_calls']} scored={result['scored_calls']}")


if __name__ == "__main__":
    main()
