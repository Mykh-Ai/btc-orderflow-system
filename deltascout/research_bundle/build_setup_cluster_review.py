from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CLUSTER_GAP_MINUTES = 45.0
MOVE_THRESHOLD_USD = 1000.0


@dataclass(frozen=True)
class SetupCluster:
    cluster_id: str
    start_ts: str
    end_ts: str
    day: str
    direction: str
    status: str
    dominant_track: str
    row_count: int
    m2_6_count: int
    reject_followthrough_count: int
    accepted_reference_count: int
    late_warning_count: int
    move_1000_row_count: int
    representative_ts: str
    max_directional_ret_fwd_60m: str
    max_favorable_max_30m: str
    max_favorable_max_60m: str
    max_priority_score: str
    top_source_types: str
    top_reject_reasons: str
    top_interesting_buckets: str
    next_action: str
    notes: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[SetupCluster]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SetupCluster.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _float_text(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _fmt_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _parse_ts(row: dict[str, str]) -> datetime:
    return datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")


def _scope_id_from_path(path: Path) -> str:
    match = re.search(r"setup_candidates_(\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if match:
        return match.group(1)
    return "unknown_scope"


def _counter_summary(values: list[str], limit: int = 4) -> str:
    counter = Counter(value for value in values if value)
    return "; ".join(f"{key}:{count}" for key, count in counter.most_common(limit))


def _dominant_track(rows: list[dict[str, str]]) -> str:
    counter = Counter(row.get("setup_track", "") for row in rows if row.get("setup_track", ""))
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def _cluster_status(rows: list[dict[str, str]]) -> tuple[str, str]:
    row_count = len(rows)
    m2_count = sum(1 for row in rows if row.get("source_type") == "m2_6_chain_candidate")
    reject_count = sum(1 for row in rows if row.get("setup_track") == "rejected_family_followthrough")
    late_count = sum(1 for row in rows if row.get("setup_track") == "m2_6_late_no_edge_warning")
    accepted_count = sum(1 for row in rows if row.get("source_type") == "accepted_peak_lifecycle_reference")
    move_count = sum(1 for row in rows if row.get("move_1000_hit") == "true")

    if accepted_count and not m2_count and not reject_count:
        return "reference_only", "Use as PEAK lifecycle comparison, not setup promotion."
    if late_count >= max(2, row_count // 2):
        return "late_or_no_edge_warning", "Review as timing/exhaustion filter before entry logic."
    if row_count >= 3 and move_count >= 2 and m2_count and reject_count:
        return "candidate_setup_with_reject_support", "Promote to manual setup review with sequence and entry timing."
    if row_count >= 3 and move_count >= 2 and m2_count:
        return "candidate_setup", "Promote to manual setup review with sequence and entry timing."
    if move_count and reject_count:
        return "reject_followthrough_candidate", "Review rejected-family blocker logic before any filter change."
    if move_count:
        return "needs_more_evidence", "Keep for comparison; require repeat cluster evidence."
    return "archive_reference", "Keep as context only."


def _make_cluster(cluster_index: int, rows: list[dict[str, str]]) -> SetupCluster:
    ordered = sorted(rows, key=_parse_ts)
    start_ts = ordered[0]["ts"]
    end_ts = ordered[-1]["ts"]
    day = ordered[0].get("day", start_ts[:10])
    direction = ordered[0].get("direction", "")
    m2_count = sum(1 for row in ordered if row.get("source_type") == "m2_6_chain_candidate")
    reject_count = sum(1 for row in ordered if row.get("setup_track") == "rejected_family_followthrough")
    accepted_count = sum(1 for row in ordered if row.get("source_type") == "accepted_peak_lifecycle_reference")
    late_count = sum(1 for row in ordered if row.get("setup_track") == "m2_6_late_no_edge_warning")
    move_count = sum(1 for row in ordered if row.get("move_1000_hit") == "true")
    best_row = max(ordered, key=lambda row: _float_text(row.get("priority_score")) or 0.0)
    max_dir60 = max((_float_text(row.get("directional_ret_fwd_60m")) or 0.0 for row in ordered), default=0.0)
    max_fav30 = max((_float_text(row.get("favorable_max_30m")) or 0.0 for row in ordered), default=0.0)
    max_fav60 = max((_float_text(row.get("favorable_max_60m")) or 0.0 for row in ordered), default=0.0)
    max_priority = max((_float_text(row.get("priority_score")) or 0.0 for row in ordered), default=0.0)
    status, next_action = _cluster_status(ordered)
    notes = []
    if late_count:
        notes.append(f"late_warning_rows={late_count}")
    if reject_count:
        notes.append("has_rejected_family_followthrough")
    if accepted_count:
        lifecycle = _counter_summary([row.get("lifecycle_bucket", "") for row in ordered])
        if lifecycle:
            notes.append(f"accepted_lifecycle={lifecycle}")
    return SetupCluster(
        cluster_id=f"{day}_{direction}_c{cluster_index:03d}",
        start_ts=start_ts,
        end_ts=end_ts,
        day=day,
        direction=direction,
        status=status,
        dominant_track=_dominant_track(ordered),
        row_count=len(ordered),
        m2_6_count=m2_count,
        reject_followthrough_count=reject_count,
        accepted_reference_count=accepted_count,
        late_warning_count=late_count,
        move_1000_row_count=move_count,
        representative_ts=best_row.get("ts", ""),
        max_directional_ret_fwd_60m=_fmt_float(max_dir60),
        max_favorable_max_30m=_fmt_float(max_fav30),
        max_favorable_max_60m=_fmt_float(max_fav60),
        max_priority_score=_fmt_float(max_priority),
        top_source_types=_counter_summary([row.get("source_type", "") for row in ordered]),
        top_reject_reasons=_counter_summary([row.get("reject_reason", "") for row in ordered]),
        top_interesting_buckets=_counter_summary([row.get("interesting_bucket", "") for row in ordered]),
        next_action=next_action,
        notes="; ".join(notes),
    )


def _cluster_rows(rows: list[dict[str, str]]) -> list[SetupCluster]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row.get("day", ""), row.get("direction", "")), []).append(row)

    clusters: list[SetupCluster] = []
    cluster_index = 1
    for _, group_rows in sorted(grouped.items()):
        ordered = sorted(group_rows, key=_parse_ts)
        current: list[dict[str, str]] = []
        previous_ts: datetime | None = None
        for row in ordered:
            row_ts = _parse_ts(row)
            if previous_ts is None:
                current = [row]
            else:
                gap_minutes = (row_ts - previous_ts).total_seconds() / 60.0
                if gap_minutes <= CLUSTER_GAP_MINUTES:
                    current.append(row)
                else:
                    clusters.append(_make_cluster(cluster_index, current))
                    cluster_index += 1
                    current = [row]
            previous_ts = row_ts
        if current:
            clusters.append(_make_cluster(cluster_index, current))
            cluster_index += 1
    return sorted(clusters, key=lambda row: float(row.max_priority_score or 0.0), reverse=True)


def _write_summary(path: Path, rows: list[SetupCluster], scope_id: str) -> None:
    by_status = Counter(row.status for row in rows)
    top_rows = rows[:12]
    lines = [
        "# Setup Cluster Review",
        "",
        f"scope: `{scope_id}`",
        f"cluster_gap_minutes: `{CLUSTER_GAP_MINUTES:.0f}`",
        f"cluster_rows: `{len(rows)}`",
        "",
        "## Status Counts",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_status.items()))
    lines.extend(["", "## Top Clusters", ""])
    for row in top_rows:
        lines.append(
            f"- `{row.cluster_id}` `{row.start_ts}` -> `{row.end_ts}` `{row.direction}` "
            f"`{row.status}` rows={row.row_count} move1000={row.move_1000_row_count} "
            f"dir60={row.max_directional_ret_fwd_60m} fav30={row.max_favorable_max_30m} "
            f"fav60={row.max_favorable_max_60m}; "
            f"next: {row.next_action}"
        )
    lines.extend(
        [
            "",
            "## Promotion Rule",
            "",
            "A cluster is not an `AI_EMIT` spec yet. Promote only after manual sequence review confirms repeatability, entry timing, lifecycle compatibility, and a realistic stop model.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_setup_cluster_review(setup_candidates_path: Path, output_root: Path) -> tuple[Path, Path, int]:
    scope_id = _scope_id_from_path(setup_candidates_path)
    rows = _read_csv_rows(setup_candidates_path)
    clusters = _cluster_rows(rows)
    output_root.mkdir(parents=True, exist_ok=True)
    out_csv = output_root / f"setup_cluster_review_{scope_id}.csv"
    out_md = output_root / f"setup_cluster_review_{scope_id}.md"
    _write_csv(out_csv, clusters)
    _write_summary(out_md, clusters, scope_id)
    return out_csv, out_md, len(clusters)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build DeltaScout setup candidate cluster review")
    parser.add_argument("--setup-candidates", required=True, help="setup_candidates_<scope>.csv")
    parser.add_argument("--output-root", required=True, help="Directory for cluster review outputs")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_csv, out_md, row_count = build_setup_cluster_review(
        setup_candidates_path=Path(args.setup_candidates),
        output_root=Path(args.output_root),
    )
    print("DeltaScout Setup Cluster Review Build")
    print(f"setup_cluster_review={out_csv}")
    print(f"setup_cluster_review_summary={out_md}")
    print(f"cluster_rows={row_count}")


if __name__ == "__main__":
    main()
