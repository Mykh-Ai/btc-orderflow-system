from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .contracts import CANDIDATE_CONTRACT_VERSION, FEED_CONTRACT_VERSION, ReplayConfig


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def input_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    record: dict[str, Any] = {"path": str(path), "size": stat.st_size, "sha256": sha256_file(path)}
    if path.suffix.lower() in {".csv", ".jsonl"}:
        with path.open("rb") as handle:
            line_count = sum(chunk.count(b"\n") for chunk in iter(lambda: handle.read(1024 * 1024), b""))
            if stat.st_size:
                handle.seek(-1, 2)
                if handle.read(1) != b"\n":
                    line_count += 1
        record["line_count"] = line_count
        record["data_row_count"] = max(0, line_count - 1) if path.suffix.lower() == ".csv" else line_count
    return record


def git_state(repo_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root, text=True)
        return {"commit": commit, "dirty": bool(status.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": "unknown", "dirty": True}


def code_fingerprint(package_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_root.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_run_fingerprint(
    *,
    config: ReplayConfig,
    input_records: list[dict[str, Any]],
    code_hash: str,
    date_from: str,
    date_to: str,
    candidate_groups: list[str],
    replay_modes: list[str],
    candidate_selection: dict[str, Any] | None = None,
) -> str:
    payload = {
        "config": config.to_dict(),
        "inputs": input_records,
        "code_hash": code_hash,
        "date_from": date_from,
        "date_to": date_to,
        "candidate_groups": candidate_groups,
        "candidate_selection": candidate_selection or {},
        "replay_modes": replay_modes,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_manifest(
    path: Path,
    *,
    config: ReplayConfig,
    repo_root: Path,
    input_records: list[dict[str, Any]],
    run_fingerprint: str,
    date_from: str,
    date_to: str,
    signal_feed_date_from: str,
    signal_feed_date_to: str,
    execution_feed_date_from: str,
    execution_feed_date_to: str,
    candidate_groups: list[str],
    replay_modes: list[str],
    candidate_count: int,
    quality_count: int,
    signal_feed_quality_counts: dict[str, int],
    execution_feed_quality_counts: dict[str, int],
    exclusions: dict[str, int],
    output_paths: Iterable[Path],
    research_analysis: dict[str, Any] | None = None,
    candidate_selection: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "experiment_id": config.experiment_id,
        "description": config.description,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git": git_state(repo_root),
        "code_fingerprint": code_fingerprint(repo_root / "deltascout" / "research_bundle" / "scout_backtester"),
        "run_fingerprint": run_fingerprint,
        "candidate_contract_version": CANDIDATE_CONTRACT_VERSION,
        "feed_contract_version": FEED_CONTRACT_VERSION,
        "date_range": {
            "candidate_from": date_from,
            "candidate_to": date_to,
            "signal_feed_from": signal_feed_date_from,
            "signal_feed_to": signal_feed_date_to,
            "execution_feed_from": execution_feed_date_from,
            "execution_feed_to": execution_feed_date_to,
        },
        "candidate_groups": candidate_groups,
        "candidate_selection": candidate_selection or {},
        "replay_modes": replay_modes,
        "resolved_config": config.to_dict(),
        "input_files": input_records,
        "candidate_count": candidate_count,
        "candidate_quality_count": quality_count,
        "signal_feed_quality_counts": signal_feed_quality_counts,
        "execution_feed_quality_counts": execution_feed_quality_counts,
        "exclusions": exclusions,
        "output_artifacts": [input_record(item) for item in output_paths],
    }
    if research_analysis is not None:
        payload["research_analysis"] = research_analysis
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=list) + "\n", encoding="utf-8")
    return path
