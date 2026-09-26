"""Rebuild and freeze blind Snapshot V2 inputs without opening outcomes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from .predictor_prompt import OUTPUT_SCHEMA, PROMPT_VERSION, prompt_record
from .snapshot_v2 import build_snapshot, canonical_json, iso, load_verified_feed, sha256_text, utc


ROOT = Path(__file__).resolve().parents[3]
SOURCE_SNAPSHOTS = ROOT / "docs/research/canonical_trade_evaluation_snapshot/frozen_trade_evaluation_snapshots.jsonl"
OLD_BLIND_MANIFEST = ROOT / "docs/research/gpt56_prompt_abc/eval_manifest_blind.csv"
FEED_MANIFEST = ROOT / "docs/research/gpt56_prompt_abc_snapshot_v2/required_source_feed_hashes.csv"
BASELINE_HASHES = ROOT / "docs/research/gpt56_prompt_abc_snapshot_v2/evidence/frozen-baseline-sha256.json"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha_normalized(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n"))


def verify_old_artifacts() -> None:
    expected = json.loads(BASELINE_HASHES.read_text(encoding="utf-8"))
    failures = [name for name, digest in expected.items() if _sha_normalized(ROOT / name) != digest]
    if failures:
        raise ValueError(f"prior research artifact changed: {failures}")


def verify_feed(root: Path) -> dict[str, Path]:
    sources = {}
    failures = []
    with FEED_MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        path = root / (row["date_utc"] + ".csv")
        if path.name != Path(row["source_path"]).name or not path.is_file():
            failures.append((row["date_utc"], "MISSING_OR_NAME"))
        elif path.stat().st_size != int(row["size_bytes"]):
            failures.append((row["date_utc"], "SIZE"))
        elif _sha_file(path) != row["sha256"]:
            failures.append((row["date_utc"], "SHA256"))
        else:
            sources[row["date_utc"]] = path
    if failures:
        raise ValueError(f"BLOCKED_BY_INPUT_RECONSTRUCTION: {failures}")
    if len(sources) != 155:
        raise ValueError("source manifest cohort changed")
    return sources


def _prior_snapshots() -> dict[str, tuple[dict, str]]:
    result = {}
    for line in SOURCE_SNAPSHOTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        key = item["signal"]["trade_key"]
        if key in result:
            raise ValueError(f"duplicate source snapshot {key}")
        result[key] = item, sha256_text(line)
    return result


def _eligible() -> list[dict[str, str]]:
    with OLD_BLIND_MANIFEST.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if list(rows[0]) != ["trade_key", "snapshot_sha256", "eligibility_status", "exclusion_reason"]:
        raise ValueError("prior blind cohort schema changed")
    eligible = [row for row in rows if row["eligibility_status"] == "ELIGIBLE"]
    if len(eligible) != 20 or any(row["exclusion_reason"] for row in eligible):
        raise ValueError("prior 20-case cohort changed")
    return eligible


def _freeze(path: Path, content: str) -> None:
    if path.exists():
        old = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if old != content:
            raise ValueError(f"frozen artifact changed: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def prepare(feed_root: Path, output: Path) -> dict:
    verify_old_artifacts()
    source_files = verify_feed(feed_root)
    previous = _prior_snapshots()
    eligible = _eligible()
    snapshots = []
    prompts = []
    manifest = []
    for row in eligible:
        key = row["trade_key"]
        source, actual_sha = previous[key]
        if actual_sha != row["snapshot_sha256"]:
            raise ValueError(f"prior blind snapshot hash mismatch: {key}")
        fill = utc(source["execution"]["actual_fill_timestamp_utc"])
        cutoff = fill.floor("min")
        dates = pd.date_range((cutoff - pd.Timedelta(days=30)).floor("D"), cutoff.floor("D"), freq="D", tz="UTC")
        missing = [iso(date)[:10] for date in dates if iso(date)[:10] not in source_files]
        if missing:
            raise ValueError(f"BLOCKED_BY_INPUT_RECONSTRUCTION: {key} {missing}")
        paths = [source_files[iso(date)[:10]] for date in dates]
        feed, columns = load_verified_feed(paths, cutoff)
        model_view = build_snapshot(source, feed, columns)
        if model_view["signal"]["trade_key"] != key:
            raise ValueError("trade identity changed")
        snapshot_line = canonical_json(model_view)
        snapshot_sha = sha256_text(snapshot_line)
        rendered = prompt_record(model_view)
        snapshots.append(snapshot_line)
        prompts.append(canonical_json({"trade_key": key, "snapshot_sha256": snapshot_sha, **rendered}))
        manifest.append({"trade_key": key, "snapshot_sha256": snapshot_sha, "prompt_sha256": rendered["prompt_sha256"], "prediction_cutoff_utc": model_view["quality"]["prediction_cutoff_utc"], "prediction_cutoff_source": "historical_executor_fill_proxy"})
        print(f"PREPARED {len(snapshots)}/{len(eligible)} {key} {snapshot_sha}", flush=True)
    import io
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=list(manifest[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(manifest)
    metadata = {
        "schema_version": "OPEN_TRADE_OUTCOME_BLIND_PREPARATION_V1",
        "cohort_size": len(eligible), "planned_calls": len(eligible),
        "model": "gpt-5.6-sol", "reasoning_effort": "medium", "store": False,
        "tools": False, "previous_response_id": False, "retries": False,
        "source_snapshots_sha256_lf_normalized": _sha_normalized(SOURCE_SNAPSHOTS),
        "old_blind_manifest_sha256_lf_normalized": _sha_normalized(OLD_BLIND_MANIFEST),
        "feed_manifest_sha256_lf_normalized": _sha_normalized(FEED_MANIFEST),
        "builder_sha256_lf_normalized": _sha_normalized(Path(__file__)),
        "snapshot_builder_sha256_lf_normalized": _sha_normalized(Path(__file__).with_name("snapshot_v2.py")),
        "prompt_source_sha256_lf_normalized": _sha_normalized(Path(__file__).with_name("predictor_prompt.py")),
        "prompt_version": PROMPT_VERSION, "output_schema": OUTPUT_SCHEMA,
        "snapshots_file_sha256": sha256_text("\n".join(snapshots) + "\n"),
        "prompts_file_sha256": sha256_text("\n".join(prompts) + "\n"),
    }
    _freeze(output / "frozen_model_view_snapshots.jsonl", "\n".join(snapshots) + "\n")
    _freeze(output / "frozen_prompts.jsonl", "\n".join(prompts) + "\n")
    _freeze(output / "blind_manifest.csv", csv_buffer.getvalue())
    _freeze(output / "run_metadata.json", json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    inspection = [json.loads(line) for line in snapshots[:3]]
    _freeze(output / "precall_inspection.json", json.dumps(inspection, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.feed_root, args.output)
    print(f"BLIND_INPUTS_FROZEN cohort={result['cohort_size']} prompts={result['planned_calls']}")


if __name__ == "__main__":
    main()
