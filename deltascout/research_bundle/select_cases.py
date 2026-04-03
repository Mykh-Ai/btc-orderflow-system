from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import DATE_FORMAT, ScopeInfo

ACCEPTED_PRIORITY_BASE = 1000
REJECT_PRIORITY_BASE = 100
REJECT_REASON_BONUS = {
    "3of3_fail": 40,
    "vwap_side": 30,
    "direction_mismatch": 20,
}
SHORT_KIND_BONUS = 10
INTERESTING_BUCKET_BONUS = {
    "possible_reversal_confirmation": 15,
    "possible_reversal_onset": 15,
    "possible_continuation_pressure": 12,
    "possible_trap_or_false_break": 12,
}
ANOMALY_PRIORITY_BASE = 500
ANOMALY_BUCKET_BONUS = {
    "unclear_but_constructive": 40,
}
ANOMALY_RULE_BONUS = {
    "IR_F1": 40,
}


@dataclass(frozen=True)
class SelectedCase:
    target_ts: str
    session_date: str
    event_type: str
    kind: str
    reject_reason: str
    reason_selected: str
    selection_priority: int
    source_basis: str
    selected_case_source: str


class CaseSelectionError(RuntimeError):
    """Raised when selected-case materialization fails."""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _find_file(review_dir: Path, prefix: str) -> Path:
    matches = sorted(review_dir.glob(f"{prefix}_{review_dir.name}.*"))
    if not matches:
        raise CaseSelectionError(f"missing required file in {review_dir}: {prefix}_{review_dir.name}.*")
    return matches[0]


def _priority_tuple(case: SelectedCase) -> tuple[int, datetime, str, str]:
    ts = datetime.strptime(case.target_ts, "%Y-%m-%d %H:%M:%S")
    return (-case.selection_priority, ts, case.event_type, case.kind)


def _anomaly_metric_strength(row: dict[str, str]) -> float:
    total = 0.0
    for field in ("cum_delta_60m", "cum_delta_180m", "ret_15m", "ret_60m"):
        try:
            total += abs(float(row.get(field, "") or 0.0))
        except ValueError:
            continue
    return total


def _anomaly_priority_tuple(case: SelectedCase, anomaly_metric_strength: float) -> tuple[int, float, datetime, str, str]:
    ts = datetime.strptime(case.target_ts, "%Y-%m-%d %H:%M:%S")
    return (-case.selection_priority, -anomaly_metric_strength, ts, case.event_type, case.kind)


def _make_accepted_case(row: dict[str, str], session_date: str) -> SelectedCase:
    return SelectedCase(
        target_ts=row.get("ts", ""),
        session_date=session_date,
        event_type=row.get("event_type", ""),
        kind=row.get("kind", ""),
        reject_reason=row.get("reject_reason", ""),
        reason_selected="accepted reference case",
        selection_priority=ACCEPTED_PRIORITY_BASE,
        source_basis="accepted_event_context",
        selected_case_source="accepted_reference",
    )


def _make_reject_case(
    row: dict[str, str],
    interesting_lookup: dict[tuple[str, str, str], dict[str, str]],
    session_date: str,
) -> SelectedCase:
    priority = REJECT_PRIORITY_BASE
    reject_reason = row.get("reject_reason", "")
    priority += REJECT_REASON_BONUS.get(reject_reason, 0)
    if row.get("kind") == "short":
        priority += SHORT_KIND_BONUS
    interesting = interesting_lookup.get((row.get("ts", ""), row.get("kind", ""), reject_reason))
    bucket = ""
    if interesting:
        bucket = interesting.get("interesting_reject_bucket", "")
        priority += INTERESTING_BUCKET_BONUS.get(bucket, 0)
    reasons: list[str] = []
    if row.get("kind") == "short":
        reasons.append("short-side reject")
    if reject_reason:
        reasons.append(reject_reason)
    if bucket:
        reasons.append(bucket)
    return SelectedCase(
        target_ts=row.get("ts", ""),
        session_date=session_date,
        event_type=row.get("event_type", ""),
        kind=row.get("kind", ""),
        reject_reason=reject_reason,
        reason_selected=", ".join(reasons) if reasons else "auto-priority reject",
        selection_priority=priority,
        source_basis="reject_event_context+interesting_rejects" if interesting else "reject_event_context",
        selected_case_source="auto_priority",
    )


def _make_anomaly_case(
    row: dict[str, str],
    interesting_lookup: dict[tuple[str, str, str], dict[str, str]],
    session_date: str,
) -> tuple[SelectedCase, float] | None:
    reject_reason = row.get("reject_reason", "")
    interesting = interesting_lookup.get((row.get("ts", ""), row.get("kind", ""), reject_reason))
    if not interesting:
        return None

    bucket = interesting.get("interesting_reject_bucket", "")
    rule_id = interesting.get("interesting_rule_id", "")
    if row.get("kind") != "short":
        return None
    if bucket != "unclear_but_constructive" and rule_id != "IR_F1":
        return None

    priority = ANOMALY_PRIORITY_BASE
    priority += ANOMALY_BUCKET_BONUS.get(bucket, 0)
    priority += ANOMALY_RULE_BONUS.get(rule_id, 0)
    if reject_reason == "3of3_fail":
        priority += 20
    if row.get("price_vs_vwap_side", "") == "below":
        priority += 10

    strength = _anomaly_metric_strength(row)
    reasons = ["anomaly coverage"]
    if reject_reason:
        reasons.append(reject_reason)
    if bucket:
        reasons.append(bucket)
    if rule_id:
        reasons.append(rule_id)

    return (
        SelectedCase(
            target_ts=row.get("ts", ""),
            session_date=session_date,
            event_type=row.get("event_type", ""),
            kind=row.get("kind", ""),
            reject_reason=reject_reason,
            reason_selected=", ".join(reasons),
            selection_priority=priority,
            source_basis="reject_event_context+interesting_rejects",
            selected_case_source="anomaly_case",
        ),
        strength,
    )


def build_selected_cases(scope: ScopeInfo, max_selected_cases: int) -> tuple[Path, list[SelectedCase]]:
    if max_selected_cases <= 0:
        raise CaseSelectionError("max_selected_cases must be positive")

    candidates: list[SelectedCase] = []
    anomaly_candidates: list[tuple[SelectedCase, float]] = []
    for review_dir in scope.review_dirs:
        try:
            datetime.strptime(review_dir.name, DATE_FORMAT)
        except ValueError as exc:
            raise CaseSelectionError(f"invalid review folder date: {review_dir.name}") from exc

        accepted_rows = _read_csv_rows(_find_file(review_dir, "accepted_event_context"))
        reject_rows = _read_csv_rows(_find_file(review_dir, "reject_event_context"))
        interesting_rows = _read_csv_rows(_find_file(review_dir, "interesting_rejects"))
        interesting_lookup = {
            (row.get("ts", ""), row.get("kind", ""), row.get("reject_reason", "")): row
            for row in interesting_rows
        }

        for row in accepted_rows:
            candidates.append(_make_accepted_case(row, review_dir.name))
        for row in reject_rows:
            candidates.append(_make_reject_case(row, interesting_lookup, review_dir.name))
            anomaly_case = _make_anomaly_case(row, interesting_lookup, review_dir.name)
            if anomaly_case is not None:
                anomaly_candidates.append(anomaly_case)

    deduped: dict[str, SelectedCase] = {}
    for case in sorted(candidates, key=_priority_tuple):
        key = f"{case.target_ts}|{case.event_type}|{case.kind}|{case.reject_reason}"
        if key not in deduped:
            deduped[key] = case

    selected = sorted(deduped.values(), key=_priority_tuple)[:max_selected_cases]

    if anomaly_candidates:
        best_anomaly_case, best_anomaly_strength = sorted(
            anomaly_candidates,
            key=lambda item: _anomaly_priority_tuple(item[0], item[1]),
        )[0]
        selected_keys = {f"{case.target_ts}|{case.event_type}|{case.kind}|{case.reject_reason}" for case in selected}
        anomaly_key = f"{best_anomaly_case.target_ts}|{best_anomaly_case.event_type}|{best_anomaly_case.kind}|{best_anomaly_case.reject_reason}"
        if anomaly_key not in selected_keys:
            replaceable = [
                case for case in selected
                if case.selected_case_source not in {"accepted_reference", "anomaly_case"}
            ]
            if replaceable:
                weakest_case = sorted(replaceable, key=lambda case: (-case.selection_priority, datetime.strptime(case.target_ts, "%Y-%m-%d %H:%M:%S"), case.event_type, case.kind), reverse=True)[0]
                selected = [case for case in selected if case != weakest_case]
                selected.append(best_anomaly_case)
                selected = sorted(selected, key=_priority_tuple)[:max_selected_cases]

    scope.bundle_dir.mkdir(parents=True, exist_ok=True)
    out_path = scope.bundle_dir / f"selected_cases_{scope.scope_start}_to_{scope.scope_end}.csv"
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "target_ts",
                "session_date",
                "event_type",
                "kind",
                "reject_reason",
                "reason_selected",
                "selection_priority",
                "source_basis",
                "selected_case_source",
            ],
        )
        writer.writeheader()
        for case in selected:
            writer.writerow(case.__dict__)
    return out_path, selected