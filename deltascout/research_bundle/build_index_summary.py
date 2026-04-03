from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .models import REQUIRED_INDEX_COLUMNS, ScopeInfo


class IndexBuildError(RuntimeError):
    """Raised when the index summary cannot be built."""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_required_file(review_dir: Path, prefix: str) -> Path:
    matches = sorted(review_dir.glob(f"{prefix}_{review_dir.name}.*"))
    if not matches:
        raise IndexBuildError(f"missing required file in {review_dir}: {prefix}_{review_dir.name}.*")
    return matches[0]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _top_pairs(counter: Counter[str], size: int) -> list[tuple[str, int]]:
    return counter.most_common(size) + [("", "")] * max(0, size - len(counter))


def build_index_summary(scope: ScopeInfo) -> Path:
    scope.bundle_dir.mkdir(parents=True, exist_ok=True)
    out_path = scope.bundle_dir / f"reviews_{scope.scope_start}_to_{scope.scope_end}_index_summary.csv"
    rows_out: list[dict[str, str | int]] = []

    for review_dir in scope.review_dirs:
        accepted_rows = _read_csv_rows(_find_required_file(review_dir, "accepted_event_context"))
        reject_rows = _read_csv_rows(_find_required_file(review_dir, "reject_event_context"))
        interesting_rows = _read_csv_rows(_find_required_file(review_dir, "interesting_rejects"))
        reason_rows = _read_csv_rows(_find_required_file(review_dir, "reject_reason_summary"))
        close_rows = _read_csv_rows(_find_required_file(review_dir, "close_outcomes"))

        reason_counter = Counter()
        for row in reason_rows:
            reason = (row.get("reject_reason") or "").strip()
            count = row.get("count") or "0"
            if reason:
                reason_counter[reason] += int(float(count))

        bucket_counter = Counter()
        for row in interesting_rows:
            bucket = (row.get("interesting_reject_bucket") or "").strip()
            if bucket:
                bucket_counter[bucket] += 1

        reject_kind_counter = Counter()
        for row in reject_rows:
            kind = (row.get("kind") or "").strip()
            if kind:
                reject_kind_counter[kind] += 1

        top_reasons = _top_pairs(reason_counter, 3)
        top_buckets = _top_pairs(bucket_counter, 2)
        accepted_case = accepted_rows[0] if accepted_rows else {}
        notes_flag = []
        if not close_rows:
            notes_flag.append("missing_close_outcomes")
        if not interesting_rows:
            notes_flag.append("no_interesting_rejects")

        row = {
            "date": review_dir.name,
            "accepted_count": len(accepted_rows),
            "reject_count": len(reject_rows),
            "interesting_reject_count": len(interesting_rows),
            "close_outcome_count": len(close_rows),
            "top_reject_reason_1": top_reasons[0][0],
            "top_reject_reason_1_count": top_reasons[0][1],
            "top_reject_reason_2": top_reasons[1][0],
            "top_reject_reason_2_count": top_reasons[1][1],
            "top_reject_reason_3": top_reasons[2][0],
            "top_reject_reason_3_count": top_reasons[2][1],
            "dominant_bucket_1": top_buckets[0][0],
            "dominant_bucket_1_count": top_buckets[0][1],
            "dominant_bucket_2": top_buckets[1][0],
            "dominant_bucket_2_count": top_buckets[1][1],
            "has_accepted": _yes_no(bool(accepted_rows)),
            "has_close_outcome": _yes_no(bool(close_rows)),
            "accepted_case_ts": accepted_case.get("ts", ""),
            "accepted_case_kind": accepted_case.get("kind", ""),
            "accepted_case_close_reason": accepted_case.get("close_reason", ""),
            "dominant_side_reject_bias": reject_kind_counter.most_common(1)[0][0] if reject_kind_counter else "",
            "contains_vwap_side_rejects": _yes_no("vwap_side" in reason_counter),
            "contains_direction_mismatch_rejects": _yes_no("direction_mismatch" in reason_counter),
            "contains_3of3_fail_rejects": _yes_no("3of3_fail" in reason_counter),
            "contains_possible_reversal_onset": _yes_no("possible_reversal_onset" in bucket_counter),
            "contains_possible_reversal_confirmation": _yes_no("possible_reversal_confirmation" in bucket_counter),
            "contains_possible_continuation_pressure": _yes_no("possible_continuation_pressure" in bucket_counter),
            "contains_possible_trap_or_false_break": _yes_no("possible_trap_or_false_break" in bucket_counter),
            "notes_flag": ";".join(notes_flag),
        }
        rows_out.append(row)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_INDEX_COLUMNS)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)
    return out_path
