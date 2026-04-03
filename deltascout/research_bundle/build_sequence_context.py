from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import ScopeInfo
from .select_cases import SelectedCase

WINDOW_MINUTES = 90
SEQUENCE_FIELDNAMES = [
    "target_ts",
    "session_date",
    "ts",
    "minutes_from_target",
    "is_target_case",
    "event_type",
    "kind",
    "reject_reason",
    "interesting_reject_bucket",
    "rule_id",
    "price",
    "price_vs_vwap_side",
    "cum_delta_24h",
    "cum_delta_60m",
    "cum_delta_180m",
    "ret_15m",
    "ret_60m",
    "same_side_as_target",
    "later_same_side_event_in_window",
    "later_same_side_accepted_in_window",
    "later_same_side_stronger_reject_in_window",
]


@dataclass(frozen=True)
class SequenceBuildResult:
    path: Path
    row_count: int
    missing_case_count: int
    status: str


class SequenceBuildError(RuntimeError):
    """Raised when selected-case sequence context cannot be built."""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_file(review_dir: Path, prefix: str) -> Path:
    matches = sorted(review_dir.glob(f"{prefix}_{review_dir.name}.*"))
    if not matches:
        raise SequenceBuildError(f"missing required file in {review_dir}: {prefix}_{review_dir.name}.*")
    return matches[0]


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _load_review_rows(review_dir: Path) -> list[dict[str, str]]:
    accepted = _read_csv_rows(_find_file(review_dir, "accepted_event_context"))
    rejects = _read_csv_rows(_find_file(review_dir, "reject_event_context"))
    interesting = _read_csv_rows(_find_file(review_dir, "interesting_rejects"))
    interesting_lookup = {
        (row.get("ts", ""), row.get("kind", ""), row.get("reject_reason", "")): row
        for row in interesting
    }
    merged: list[dict[str, str]] = []
    for row in accepted + rejects:
        joined = dict(row)
        extra = interesting_lookup.get((row.get("ts", ""), row.get("kind", ""), row.get("reject_reason", "")))
        joined["interesting_reject_bucket"] = extra.get("interesting_reject_bucket", "") if extra else ""
        joined["rule_id"] = extra.get("interesting_rule_id", "") if extra else ""
        merged.append(joined)
    return sorted(
        merged,
        key=lambda row: (
            _parse_ts(row.get("ts", "1970-01-01 00:00:00")),
            row.get("event_type", ""),
            row.get("kind", ""),
        ),
    )


def _stronger_reject_exists(target: dict[str, str], rows: list[dict[str, str]]) -> str:
    target_value = target.get("cum_delta_60m", "")
    try:
        target_abs = abs(float(target_value))
    except ValueError:
        return ""
    target_kind = target.get("kind", "")
    target_ts = target.get("ts", "")
    for row in rows:
        if row.get("ts", "") <= target_ts:
            continue
        if row.get("kind", "") != target_kind:
            continue
        if row.get("event_type", "") != "CANDIDATE_COMPARISON_REJECT":
            continue
        try:
            row_abs = abs(float(row.get("cum_delta_60m", "")))
        except ValueError:
            continue
        if row_abs > target_abs:
            return "yes"
    return "no"


def build_sequence_context(scope: ScopeInfo, selected_cases: list[SelectedCase]) -> SequenceBuildResult:
    out_path = scope.bundle_dir / f"selected_case_sequence_context_{scope.scope_start}_to_{scope.scope_end}.csv"
    rows_out: list[dict[str, str]] = []
    missing_case_count = 0
    review_rows_cache: dict[str, list[dict[str, str]]] = {}

    for case in selected_cases:
        review_dir = scope.input_root / case.session_date
        if case.session_date not in review_rows_cache:
            review_rows_cache[case.session_date] = _load_review_rows(review_dir)
        day_rows = review_rows_cache[case.session_date]
        target_dt = _parse_ts(case.target_ts)
        target_matches = [
            row
            for row in day_rows
            if row.get("ts", "") == case.target_ts
            and row.get("kind", "") == case.kind
            and row.get("event_type", "") == case.event_type
        ]
        if not target_matches:
            missing_case_count += 1
            continue
        target_row = target_matches[0]
        window_rows = []
        for row in day_rows:
            delta_minutes = int((_parse_ts(row.get("ts", "")) - target_dt).total_seconds() / 60)
            if abs(delta_minutes) <= WINDOW_MINUTES:
                window_rows.append((delta_minutes, row))
        if not window_rows:
            missing_case_count += 1
            continue

        later_same_side_event = any(delta > 0 and row.get("kind", "") == case.kind for delta, row in window_rows)
        later_same_side_accepted = any(
            delta > 0 and row.get("kind", "") == case.kind and row.get("event_type", "") == "PEAK_EMIT"
            for delta, row in window_rows
        )
        stronger_reject = _stronger_reject_exists(target_row, [row for _, row in window_rows])

        for delta_minutes, row in sorted(
            window_rows,
            key=lambda item: (item[0], item[1].get("event_type", ""), item[1].get("kind", "")),
        ):
            rows_out.append(
                {
                    "target_ts": case.target_ts,
                    "session_date": case.session_date,
                    "ts": row.get("ts", ""),
                    "minutes_from_target": str(delta_minutes),
                    "is_target_case": "yes" if row is target_row else "no",
                    "event_type": row.get("event_type", ""),
                    "kind": row.get("kind", ""),
                    "reject_reason": row.get("reject_reason", ""),
                    "interesting_reject_bucket": row.get("interesting_reject_bucket", ""),
                    "rule_id": row.get("rule_id", ""),
                    "price": row.get("price", ""),
                    "price_vs_vwap_side": row.get("price_vs_vwap_side", ""),
                    "cum_delta_24h": row.get("cum_delta_24h", ""),
                    "cum_delta_60m": row.get("cum_delta_60m", ""),
                    "cum_delta_180m": row.get("cum_delta_180m", ""),
                    "ret_15m": row.get("ret_15m", ""),
                    "ret_60m": row.get("ret_60m", ""),
                    "same_side_as_target": "yes" if row.get("kind", "") == case.kind else "no",
                    "later_same_side_event_in_window": "yes" if later_same_side_event else "no",
                    "later_same_side_accepted_in_window": "yes" if later_same_side_accepted else "no",
                    "later_same_side_stronger_reject_in_window": stronger_reject,
                }
            )

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SEQUENCE_FIELDNAMES)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)

    status = "missing"
    if rows_out:
        status = "partial" if missing_case_count else "complete"
    return SequenceBuildResult(path=out_path, row_count=len(rows_out), missing_case_count=missing_case_count, status=status)
