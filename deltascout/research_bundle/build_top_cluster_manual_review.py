from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

TOP_CLUSTER_IDS = [
    "2026-03-23_long_c005",
    "2026-03-21_short_c004",
    "2026-04-07_long_c025",
    "2026-04-16_short_c037",
    "2026-04-12_short_c032",
]
PRE_CONTEXT_MINUTES = 180
POST_CONTEXT_MINUTES = 120
NEARBY_ACCEPTED_LOOKAHEAD_MINUTES = 180
MOVE_THRESHOLD_USD = 1000.0


@dataclass(frozen=True)
class ManualClusterReview:
    cluster_id: str
    review_window_start: str
    cluster_start: str
    cluster_end: str
    review_window_end: str
    day: str
    direction: str
    preliminary_verdict: str
    entry_quality: str
    ai_emit_lesson: str
    row_count: str
    candidate_source_counts: str
    reject_support: str
    accepted_peak_near_window: str
    representative_ts: str
    representative_price: str
    favorable_move_after_rep: str
    adverse_move_after_rep: str
    hit_1000_after_rep: str
    time_to_1000_min: str
    adverse_before_1000: str
    pre_context_directional_move: str
    pre_context_delta_sum: str
    cluster_directional_move: str
    cluster_delta_sum: str
    post_context_directional_move: str
    post_context_delta_sum: str
    risk_note: str
    next_action: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[ManualClusterReview]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ManualClusterReview.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _fmt_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _float(value: str | None) -> float | None:
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


def _day_range(start: datetime, end: datetime) -> list[str]:
    days: list[str] = []
    current = datetime(start.year, start.month, start.day)
    final = datetime(end.year, end.month, end.day)
    while current <= final:
        days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def _load_outcome_rows(minute_dataset_root: Path, start: datetime, end: datetime) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day in _day_range(start, end):
        rows.extend(_read_csv_rows(minute_dataset_root / f"minute_events_outcomes_{day}.csv"))
    selected = [row for row in rows if start <= _parse_ts(row["ts"]) <= end]
    return sorted(selected, key=lambda row: _parse_ts(row["ts"]))


def _price(row: dict[str, str], field: str) -> float | None:
    return _float(row.get(field))


def _directional_move(direction: str, start_price: float | None, end_price: float | None) -> float | None:
    if start_price is None or end_price is None:
        return None
    move = end_price - start_price
    if direction == "short":
        return -move
    return move


def _sum_delta(rows: list[dict[str, str]]) -> float:
    return sum(_float(row.get("delta_1m")) or 0.0 for row in rows)


def _slice(rows: list[dict[str, str]], start: datetime, end: datetime) -> list[dict[str, str]]:
    return [row for row in rows if start <= _parse_ts(row["ts"]) <= end]


def _counter_summary(values: list[str], limit: int = 4) -> str:
    counter = Counter(value for value in values if value)
    return "; ".join(f"{key}:{count}" for key, count in counter.most_common(limit))


def _nearest_price(rows: list[dict[str, str]], ts: datetime) -> tuple[str, float | None]:
    if not rows:
        return "", None
    nearest = min(rows, key=lambda row: abs((_parse_ts(row["ts"]) - ts).total_seconds()))
    return nearest["ts"], _price(nearest, "close")


def _forward_risk(rows: list[dict[str, str]], direction: str, entry_ts: datetime, entry_price: float | None) -> tuple[str, str, str, str, str]:
    if entry_price is None:
        return "", "", "false", "", ""
    forward = [row for row in rows if _parse_ts(row["ts"]) >= entry_ts]
    if not forward:
        return "", "", "false", "", ""

    favorable = 0.0
    adverse = 0.0
    hit_ts: datetime | None = None
    adverse_before_hit = 0.0
    for row in forward:
        high = _price(row, "high")
        low = _price(row, "low")
        if high is None or low is None:
            continue
        if direction == "short":
            row_favorable = entry_price - low
            row_adverse = high - entry_price
            hit_now = low <= entry_price - MOVE_THRESHOLD_USD
        else:
            row_favorable = high - entry_price
            row_adverse = entry_price - low
            hit_now = high >= entry_price + MOVE_THRESHOLD_USD
        favorable = max(favorable, row_favorable)
        adverse = max(adverse, row_adverse)
        if hit_ts is None:
            adverse_before_hit = max(adverse_before_hit, row_adverse)
            if hit_now:
                hit_ts = _parse_ts(row["ts"])

    if hit_ts is None:
        return _fmt_float(favorable), _fmt_float(adverse), "false", "", ""
    return (
        _fmt_float(favorable),
        _fmt_float(adverse),
        "true",
        _fmt_float((hit_ts - entry_ts).total_seconds() / 60.0),
        _fmt_float(adverse_before_hit),
    )


def _segment_summary(rows: list[dict[str, str]], direction: str) -> tuple[str, str]:
    if len(rows) < 2:
        return "", ""
    start_price = _price(rows[0], "close")
    end_price = _price(rows[-1], "close")
    return _fmt_float(_directional_move(direction, start_price, end_price)), _fmt_float(_sum_delta(rows))


def _accepted_near_window(ledger_rows: list[dict[str, str]], direction: str, start: datetime, end: datetime) -> str:
    notes = []
    for row in ledger_rows:
        ts_text = row.get("accepted_ts", "")
        if not ts_text:
            continue
        ts = _parse_ts(ts_text)
        if start <= ts <= end and row.get("side", "") == direction:
            notes.append(
                f"{ts_text} {row.get('side', '')} {row.get('close_reason', '')}/{row.get('lifecycle_bucket', '')}"
            )
    return "; ".join(notes)


def _entry_quality(cluster: dict[str, str], hit_1000: str, time_to_1000: str, adverse_before_1000: str) -> tuple[str, str, str, str]:
    reject_support = int(cluster.get("reject_followthrough_count", "") or 0)
    late_count = int(cluster.get("late_warning_count", "") or 0)
    row_count = int(cluster.get("row_count", "") or 0)
    adverse = _float(adverse_before_1000) or 0.0
    time_to_hit = _float(time_to_1000)

    if hit_1000 != "true":
        return (
            "needs_visual_validation",
            "unproven_entry_proxy",
            "Do not promote until chart/sequence review validates the entry trigger and stop model.",
            "No $1000 hit after representative entry proxy in the reviewed window.",
        )
    if late_count and late_count >= row_count / 2:
        return (
            "late_no_edge_warning",
            "late_or_exhausted_entry_proxy",
            "Use this pattern as a no-entry/timing warning unless manual review isolates earlier valid rows.",
            "Quantitative proxy only; cluster is dominated by late-warning rows.",
        )
    if time_to_hit is not None and time_to_hit <= 15 and adverse <= 250:
        quality = "quant_fast_move_candidate"
    elif adverse <= 350:
        quality = "quant_move_candidate"
    else:
        quality = "wide_stop_quant_candidate"

    if reject_support:
        verdict = "quant_candidate_with_reject_support"
        lesson = "AI_EMIT research should test this process phase and separately inspect why current PEAK/reject logic filtered part of the move."
    else:
        verdict = "quant_candidate_needs_visual_validation"
        lesson = "AI_EMIT research should treat this M2.6 sequence as a candidate grammar only after manual chart/sequence validation."
    risk_note = (
        "Quantitative proxy only: adverse-before-hit is small, but entry trigger and stop model are not visually validated."
        if adverse <= 350
        else "Quantitative proxy only: potential stop width is large; needs realistic SL model and visual validation."
    )
    return verdict, quality, lesson, risk_note


def _review_cluster(
    cluster: dict[str, str],
    candidate_rows: list[dict[str, str]],
    ledger_rows: list[dict[str, str]],
    minute_dataset_root: Path,
) -> ManualClusterReview:
    start = _parse_ts(cluster["start_ts"])
    end = _parse_ts(cluster["end_ts"])
    review_start = start - timedelta(minutes=PRE_CONTEXT_MINUTES)
    review_end = end + timedelta(minutes=POST_CONTEXT_MINUTES)
    nearby_accepted_end = end + timedelta(minutes=NEARBY_ACCEPTED_LOOKAHEAD_MINUTES)
    direction = cluster["direction"]
    rows = _load_outcome_rows(minute_dataset_root, review_start, review_end)
    representative_ts = _parse_ts(cluster["representative_ts"])
    rep_price_ts, rep_price = _nearest_price(rows, representative_ts)
    favorable, adverse, hit_1000, time_to_1000, adverse_before_1000 = _forward_risk(
        rows, direction, representative_ts, rep_price
    )

    pre_rows = _slice(rows, review_start, start)
    cluster_rows = _slice(rows, start, end)
    post_rows = _slice(rows, end, review_end)
    pre_move, pre_delta = _segment_summary(pre_rows, direction)
    cluster_move, cluster_delta = _segment_summary(cluster_rows, direction)
    post_move, post_delta = _segment_summary(post_rows, direction)

    relevant_candidates = [
        row
        for row in candidate_rows
        if row.get("day") == cluster.get("day")
        and row.get("direction") == direction
        and start <= _parse_ts(row["ts"]) <= end
    ]
    verdict, quality, lesson, risk_note = _entry_quality(cluster, hit_1000, time_to_1000, adverse_before_1000)
    accepted_note = _accepted_near_window(ledger_rows, direction, review_start, nearby_accepted_end)
    reject_support = "true" if int(cluster.get("reject_followthrough_count", "") or 0) > 0 else "false"

    return ManualClusterReview(
        cluster_id=cluster["cluster_id"],
        review_window_start=_fmt_ts(review_start),
        cluster_start=cluster["start_ts"],
        cluster_end=cluster["end_ts"],
        review_window_end=_fmt_ts(review_end),
        day=cluster["day"],
        direction=direction,
        preliminary_verdict=verdict,
        entry_quality=quality,
        ai_emit_lesson=lesson,
        row_count=cluster.get("row_count", ""),
        candidate_source_counts=_counter_summary([row.get("source_type", "") for row in relevant_candidates]),
        reject_support=reject_support,
        accepted_peak_near_window=accepted_note,
        representative_ts=cluster["representative_ts"],
        representative_price=_fmt_float(rep_price),
        favorable_move_after_rep=favorable,
        adverse_move_after_rep=adverse,
        hit_1000_after_rep=hit_1000,
        time_to_1000_min=time_to_1000,
        adverse_before_1000=adverse_before_1000,
        pre_context_directional_move=pre_move,
        pre_context_delta_sum=pre_delta,
        cluster_directional_move=cluster_move,
        cluster_delta_sum=cluster_delta,
        post_context_directional_move=post_move,
        post_context_delta_sum=post_delta,
        risk_note=risk_note,
        next_action="Manual chart/sequence review required before any setup spec draft.",
    )


def _write_md(path: Path, rows: list[ManualClusterReview]) -> None:
    lines = [
        "# Top Setup Cluster Quantitative Pre-Review",
        "",
        "This is not manual validation. It is a first-pass calculation around representative entry proxies.",
        "The review window includes pre-context and post-context; it is not the proposed trade window.",
        "",
        f"pre_context_minutes: `{PRE_CONTEXT_MINUTES}`",
        f"post_context_minutes: `{POST_CONTEXT_MINUTES}`",
        f"nearby_accepted_lookahead_minutes: `{NEARBY_ACCEPTED_LOOKAHEAD_MINUTES}`",
        "",
        "## Verdict Table",
        "",
        "| cluster | direction | verdict | entry_quality | fav_after_rep | adverse_before_1000 | time_to_1000_min | lesson |",
        "|---|---:|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.cluster_id}` | `{row.direction}` | `{row.preliminary_verdict}` | "
            f"`{row.entry_quality}` | `{row.favorable_move_after_rep}` | "
            f"`{row.adverse_before_1000}` | `{row.time_to_1000_min}` | {row.ai_emit_lesson} |"
        )
    lines.extend(["", "## Cluster Notes", ""])
    for row in rows:
        lines.extend(
            [
                f"### {row.cluster_id}",
                "",
                f"- Review window: `{row.review_window_start}` to `{row.review_window_end}`; cluster: `{row.cluster_start}` to `{row.cluster_end}`.",
                f"- Representative entry proxy: `{row.representative_ts}` at `{row.representative_price}`.",
                f"- Pre-context directional move/delta: `{row.pre_context_directional_move}` / `{row.pre_context_delta_sum}`.",
                f"- Cluster directional move/delta: `{row.cluster_directional_move}` / `{row.cluster_delta_sum}`.",
                f"- Post-context directional move/delta: `{row.post_context_directional_move}` / `{row.post_context_delta_sum}`.",
                f"- Candidate sources: `{row.candidate_source_counts}`; reject support: `{row.reject_support}`.",
                f"- Nearby accepted PEAK: `{row.accepted_peak_near_window or 'none'}`.",
                f"- Risk note: {row.risk_note}",
                "",
            ]
        )
    lines.extend(
        [
            "## Use",
            "",
        "This is first-pass quantitative pre-review. It is not manual chart validation and not a live signal spec.",
        "The next step is manual chart/sequence validation before any `AI_EMIT` setup spec draft.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_top_cluster_manual_review(
    cluster_review_path: Path,
    setup_candidates_path: Path,
    accepted_ledger_path: Path,
    minute_dataset_root: Path,
    output_root: Path,
) -> tuple[Path, Path, int]:
    clusters = {row["cluster_id"]: row for row in _read_csv_rows(cluster_review_path)}
    candidate_rows = _read_csv_rows(setup_candidates_path)
    ledger_rows = _read_csv_rows(accepted_ledger_path)
    reviews = [
        _review_cluster(clusters[cluster_id], candidate_rows, ledger_rows, minute_dataset_root)
        for cluster_id in TOP_CLUSTER_IDS
        if cluster_id in clusters
    ]
    output_root.mkdir(parents=True, exist_ok=True)
    out_csv = output_root / "top_cluster_manual_review_2026-03-17_to_2026-05-02.csv"
    out_md = output_root / "top_cluster_manual_review_2026-03-17_to_2026-05-02.md"
    _write_csv(out_csv, reviews)
    _write_md(out_md, reviews)
    return out_csv, out_md, len(reviews)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build first-pass manual review for top DeltaScout setup clusters")
    parser.add_argument("--cluster-review", required=True)
    parser.add_argument("--setup-candidates", required=True)
    parser.add_argument("--accepted-ledger", required=True)
    parser.add_argument("--minute-dataset-root", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_csv, out_md, row_count = build_top_cluster_manual_review(
        cluster_review_path=Path(args.cluster_review),
        setup_candidates_path=Path(args.setup_candidates),
        accepted_ledger_path=Path(args.accepted_ledger),
        minute_dataset_root=Path(args.minute_dataset_root),
        output_root=Path(args.output_root),
    )
    print("DeltaScout Top Cluster Manual Review Build")
    print(f"top_cluster_manual_review={out_csv}")
    print(f"top_cluster_manual_review_summary={out_md}")
    print(f"review_rows={row_count}")


if __name__ == "__main__":
    main()
