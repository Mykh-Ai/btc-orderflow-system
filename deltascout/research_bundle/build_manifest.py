from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .models import BUNDLE_VERSION, SPEC_VERSION, ScopeInfo


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    return "complete" if path.stat().st_size > 0 else "partial"


def build_manifest(
    scope: ScopeInfo,
    index_summary_path: Path,
    selected_cases_path: Path | None = None,
    sequence_context_path: Path | None = None,
    raw_micro_path: Path | None = None,
    blocker_breakdown_path: Path | None = None,
    blocker_breakdown_requested: bool = False,
    selected_case_count: int = 0,
    missing_raw_micro_case_count: int = 0,
    missing_sequence_case_count: int = 0,
    sequence_context_status_override: str | None = None,
    raw_feed_micro_status_override: str | None = None,
    blocker_breakdown_status_override: str | None = None,
    notes: str = "",
) -> Path:
    manifest_path = scope.bundle_dir / "research_bundle_manifest.csv"
    review_markdown_path = scope.bundle_dir / f"reviews_{scope.scope_start}_to_{scope.scope_end}_final_research_review.md"
    sequence_context_path = sequence_context_path or scope.bundle_dir / f"selected_case_sequence_context_{scope.scope_start}_to_{scope.scope_end}.csv"
    selected_cases_path = selected_cases_path or scope.bundle_dir / f"selected_cases_{scope.scope_start}_to_{scope.scope_end}.csv"
    raw_micro_path = raw_micro_path or scope.bundle_dir / f"selected_case_raw_feed_micro_{scope.scope_start}_to_{scope.scope_end}.csv"
    blocker_path = blocker_breakdown_path or scope.bundle_dir / f"selected_case_blocker_breakdown_{scope.scope_start}_to_{scope.scope_end}.csv"

    sequence_status = sequence_context_status_override or _artifact_status(sequence_context_path)
    selected_cases_status = _artifact_status(selected_cases_path)
    raw_status = raw_feed_micro_status_override or _artifact_status(raw_micro_path)
    blocker_status = blocker_breakdown_status_override or _artifact_status(blocker_path)
    partial_statuses = [sequence_status, raw_status]
    if blocker_breakdown_requested:
        partial_statuses.append(blocker_status)
    partial_coverage = any(status != "complete" for status in partial_statuses)
    row = {
        "bundle_version": BUNDLE_VERSION,
        "spec_version": SPEC_VERSION,
        "bundle_scope_id": scope.bundle_scope_id,
        "bundle_built_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(scope.input_root),
        "output_root": str(scope.bundle_dir),
        "scope_start": scope.scope_start,
        "scope_end": scope.scope_end,
        "daily_folder_count": len(scope.review_dirs),
        "review_memo_present": "no",
        "index_summary_present": "yes" if index_summary_path.exists() else "no",
        "selected_cases_present": "yes" if selected_cases_path.exists() else "no",
        "sequence_context_present": "yes" if sequence_context_path.exists() else "no",
        "raw_feed_micro_present": "yes" if raw_micro_path.exists() else "no",
        "blocker_breakdown_present": "yes" if blocker_path.exists() else "no",
        "review_markdown_status": _artifact_status(review_markdown_path),
        "index_summary_status": _artifact_status(index_summary_path),
        "selected_cases_status": selected_cases_status,
        "sequence_context_status": sequence_status,
        "raw_feed_micro_status": raw_status,
        "blocker_breakdown_status": blocker_status,
        "selected_case_count": selected_case_count,
        "missing_raw_micro_case_count": missing_raw_micro_case_count,
        "missing_sequence_case_count": missing_sequence_case_count,
        "partial_coverage_flag": "yes" if partial_coverage else "no",
        "notes": notes,
    }
    fieldnames = list(row.keys())
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    return manifest_path
