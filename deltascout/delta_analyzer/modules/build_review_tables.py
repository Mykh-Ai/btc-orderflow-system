from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACCEPTED_EVENT_TYPE = "PEAK_EMIT"
REJECT_EVENT_TYPES = (
    "CANDIDATE_COMPARISON_REJECT",
    "CANDIDATE_GATE_REJECT",
)
BASE_FIELDS = (
    "ts",
    "day",
    "event_type",
    "kind",
    "reject_reason",
    "delta",
    "vol",
    "imb",
    "price",
    "vwap",
    "poc",
    "matched_feed_ts",
    "source_file",
    "terminal_decision_present",
)
CONTEXT_FIELDS = (
    "cum_delta_24h",
    "cum_delta_180m",
    "cum_delta_60m",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
    "abs_dist_vwap",
    "price_vs_vwap_side",
)
ACCEPTED_JOIN_FIELDS = (
    "join_status",
    "join_confidence",
    "close_ts",
    "close_reason",
    "entry",
    "side",
)


class ReviewBuildError(RuntimeError):
    """Raised when deterministic review-builder inputs are missing or invalid."""


@dataclass(frozen=True)
class ReviewBuildResult:
    date: str
    accepted_count: int
    reject_count: int
    matched_close_count: int
    output_dir: Path
    accepted_path: Path
    reject_path: Path
    summary_path: Path


def build_daily_review_package(date: str, input_root: Path | str, output_root: Path | str) -> ReviewBuildResult:
    input_root = Path(input_root)
    output_root = Path(output_root)

    events_context_rows = _load_required_csv(input_root / f"events_context_{date}.csv", required_name="events_context")
    close_outcome_rows = _load_optional_csv(input_root / f"close_outcomes_{date}.csv")
    close_outcomes_by_key = _index_close_outcomes(close_outcome_rows)

    accepted_rows = build_accepted_event_context_rows(events_context_rows, close_outcomes_by_key)
    reject_rows = build_reject_event_context_rows(events_context_rows)

    review_dir = output_root / "reviews" / date
    review_dir.mkdir(parents=True, exist_ok=True)

    accepted_path = review_dir / f"accepted_event_context_{date}.csv"
    reject_path = review_dir / f"reject_event_context_{date}.csv"
    summary_path = review_dir / f"daily_review_summary_{date}.md"

    _write_csv(accepted_path, accepted_rows, BASE_FIELDS + CONTEXT_FIELDS + ACCEPTED_JOIN_FIELDS)
    _write_csv(reject_path, reject_rows, _ordered_reject_fields(reject_rows))
    summary_path.write_text(_build_summary(date, accepted_rows, reject_rows, accepted_path, reject_path, summary_path), encoding="utf-8")

    return ReviewBuildResult(
        date=date,
        accepted_count=len(accepted_rows),
        reject_count=len(reject_rows),
        matched_close_count=sum(1 for row in accepted_rows if row.get("join_status")),
        output_dir=review_dir,
        accepted_path=accepted_path,
        reject_path=reject_path,
        summary_path=summary_path,
    )


def build_accepted_event_context_rows(
    events_context_rows: list[dict[str, str]],
    close_outcomes_by_key: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in events_context_rows:
        if row.get("event_type") != ACCEPTED_EVENT_TYPE:
            continue
        output_row = {field: row.get(field, "") for field in BASE_FIELDS + CONTEXT_FIELDS}
        close_row = close_outcomes_by_key.get((_normalize_ts_key(row.get("ts")), _normalize_kind_key(row.get("kind"))))
        for field in ACCEPTED_JOIN_FIELDS:
            output_row[field] = close_row.get(field, "") if close_row else ""
        rows.append(output_row)
    return rows


def build_reject_event_context_rows(events_context_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in events_context_rows:
        if row.get("event_type") in REJECT_EVENT_TYPES:
            rows.append(dict(row))
    return rows


def _ordered_reject_fields(rows: list[dict[str, str]]) -> tuple[str, ...]:
    preferred = list(BASE_FIELDS + CONTEXT_FIELDS)
    extras: list[str] = []
    for row in rows:
        for key in row:
            if key not in preferred and key not in extras:
                extras.append(key)
    return tuple(preferred + extras)


def _load_required_csv(path: Path, *, required_name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise ReviewBuildError(f"missing {required_name} input: {path}")
    return _load_csv(path)


def _load_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return _load_csv(path)


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _index_close_outcomes(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (_normalize_ts_key(row.get("peak_ts")), _normalize_kind_key(row.get("peak_kind")))
        if not key[0]:
            continue
        indexed.setdefault(key, {field: row.get(field, "") for field in ACCEPTED_JOIN_FIELDS})
    return indexed


def _normalize_ts_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc)
    return ts.replace(microsecond=0).isoformat()


def _normalize_kind_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _build_summary(
    date: str,
    accepted_rows: list[dict[str, str]],
    reject_rows: list[dict[str, str]],
    accepted_path: Path,
    reject_path: Path,
    summary_path: Path,
) -> str:
    matched_close_count = sum(1 for row in accepted_rows if row.get("join_status"))
    reason_counts: dict[str, int] = {}
    for row in reject_rows:
        reason = (row.get("reject_reason") or "").strip() or "<missing>"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    lines = [
        f"# Daily Review Summary {date}",
        "",
        f"- processed_date: {date}",
        f"- accepted_row_count: {len(accepted_rows)}",
        f"- reject_row_count: {len(reject_rows)}",
        f"- accepted_with_close_outcomes: {matched_close_count}",
        "- reject_counts_by_reason:",
    ]
    if reason_counts:
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"  - {reason}: {count}")
    else:
        lines.append("  - <none>: 0")
    lines.extend(
        [
            "- files_created:",
            f"  - {accepted_path.name}",
            f"  - {reject_path.name}",
            f"  - {summary_path.name}",
            "",
        ]
    )
    return "\n".join(lines)
