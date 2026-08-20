from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

MOVE_THRESHOLD_USD = 1000.0
FORWARD_MINUTES = 60
CLUSTER_GAP_MINUTES = 5.0
CONTEXT_MINUTES = 180
DETECTOR_LOOKBACK_MINUTES = 60
DETECTOR_LOOKAHEAD_MINUTES = 30


@dataclass(frozen=True)
class MoveFirstWindow:
    move_cluster_id: str
    day: str
    direction: str
    move_signal_start: str
    move_signal_end: str
    row_count: int
    earliest_proxy_ts: str
    earliest_proxy_price: str
    earliest_time_to_1000_min: str
    earliest_adverse_before_1000: str
    best_proxy_ts: str
    best_proxy_price: str
    best_time_to_1000_min: str
    best_adverse_before_1000: str
    max_favorable_60m: str
    max_adverse_before_1000: str
    pre_context_directional_move: str
    pre_context_delta_sum: str
    detector_window_start: str
    detector_window_end: str
    accepted_peak_count_near: int
    m2_6_count_near: int
    reject_count_near: int
    interesting_reject_count_near: int
    nearest_accepted_peak: str
    nearest_m2_6: str
    nearest_reject: str
    source_basis: str
    review_priority: str
    notes: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[MoveFirstWindow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MoveFirstWindow.__dataclass_fields__.keys()))
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


def _outcome_paths(minute_dataset_root: Path) -> list[Path]:
    return sorted(minute_dataset_root.glob("minute_events_outcomes_*.csv"))


def _mechanics_rows(minute_dataset_root: Path, start: datetime, end: datetime) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day in _day_range(start, end):
        rows.extend(_read_csv_rows(minute_dataset_root / f"minute_events_mechanics_{day}.csv"))
    return [row for row in rows if start <= _parse_ts(row["ts"]) <= end]


def _directional_context_move(rows: list[dict[str, str]], direction: str) -> float | None:
    if len(rows) < 2:
        return None
    start = _float(rows[0].get("close"))
    end = _float(rows[-1].get("close"))
    if start is None or end is None:
        return None
    move = end - start
    return -move if direction == "short" else move


def _sum_delta(rows: list[dict[str, str]]) -> float:
    return sum(_float(row.get("delta_1m")) or 0.0 for row in rows)


def _candidate_signal_rows(path: Path, direction: str) -> list[dict[str, str]]:
    rows = []
    for row in _read_csv_rows(path):
        ts = row.get("ts", "")
        if not ts:
            continue
        if direction == "long" and (_float(row.get("upside_max_60m")) or 0.0) >= MOVE_THRESHOLD_USD:
            rows.append(row)
        if direction == "short" and (_float(row.get("downside_max_60m")) or 0.0) >= MOVE_THRESHOLD_USD:
            rows.append(row)
    return sorted(rows, key=lambda row: _parse_ts(row["ts"]))


def _cluster_signal_rows(rows: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    clusters: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    previous_ts: datetime | None = None
    for row in rows:
        ts = _parse_ts(row["ts"])
        if previous_ts is None:
            current = [row]
        else:
            gap = (ts - previous_ts).total_seconds() / 60.0
            if gap <= CLUSTER_GAP_MINUTES:
                current.append(row)
            else:
                clusters.append(current)
                current = [row]
        previous_ts = ts
    if current:
        clusters.append(current)
    return clusters


def _forward_rows(minute_dataset_root: Path, start: datetime) -> list[dict[str, str]]:
    end = start + timedelta(minutes=FORWARD_MINUTES)
    rows: list[dict[str, str]] = []
    for day in _day_range(start, end):
        rows.extend(_read_csv_rows(minute_dataset_root / f"minute_events_outcomes_{day}.csv"))
    return [row for row in rows if start <= _parse_ts(row["ts"]) <= end]


def _entry_price(row: dict[str, str]) -> float | None:
    return _float(row.get("close"))


def _forward_stats(minute_dataset_root: Path, row: dict[str, str], direction: str) -> tuple[float | None, float | None, float | None]:
    entry_ts = _parse_ts(row["ts"])
    entry = _entry_price(row)
    if entry is None:
        return None, None, None
    favorable = 0.0
    adverse_before_hit = 0.0
    hit_ts: datetime | None = None
    for fwd in _forward_rows(minute_dataset_root, entry_ts):
        high = _float(fwd.get("high"))
        low = _float(fwd.get("low"))
        if high is None or low is None:
            continue
        if direction == "short":
            row_favorable = entry - low
            row_adverse = high - entry
            hit = low <= entry - MOVE_THRESHOLD_USD
        else:
            row_favorable = high - entry
            row_adverse = entry - low
            hit = high >= entry + MOVE_THRESHOLD_USD
        favorable = max(favorable, row_favorable)
        if hit_ts is None:
            adverse_before_hit = max(adverse_before_hit, row_adverse)
            if hit:
                hit_ts = _parse_ts(fwd["ts"])
    if hit_ts is None:
        return favorable, None, adverse_before_hit
    return favorable, (hit_ts - entry_ts).total_seconds() / 60.0, adverse_before_hit


def _load_detector_rows(review_root: Path, minute_dataset_root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    accepted: list[dict[str, str]] = []
    rejects: list[dict[str, str]] = []
    interesting: list[dict[str, str]] = []
    for day_dir in sorted(review_root.iterdir()):
        if not day_dir.is_dir():
            continue
        day = day_dir.name
        accepted.extend(_read_csv_rows(day_dir / f"accepted_event_context_{day}.csv"))
        rejects.extend(_read_csv_rows(day_dir / f"reject_event_context_{day}.csv"))
        interesting.extend(_read_csv_rows(day_dir / f"interesting_rejects_{day}.csv"))
    m2_rows: list[dict[str, str]] = []
    for path in sorted((minute_dataset_root / "m2_6").glob("minute_event_chain_candidates_*.csv")):
        m2_rows.extend(_read_csv_rows(path))
    return accepted, m2_rows, rejects, interesting


def _detector_key_ts(row: dict[str, str]) -> str:
    return row.get("ts", "") or row.get("accepted_ts", "")


def _detector_direction(row: dict[str, str]) -> str:
    return row.get("direction", "") or row.get("kind", "") or row.get("side", "")


def _within_detector_window(row: dict[str, str], direction: str, start: datetime, end: datetime) -> bool:
    ts_text = _detector_key_ts(row)
    if not ts_text:
        return False
    row_direction = _detector_direction(row)
    return row_direction == direction and start <= _parse_ts(ts_text) <= end


def _nearest_detector(rows: list[dict[str, str]], direction: str, center: datetime, start: datetime, end: datetime, label: str) -> str:
    scoped = [row for row in rows if _within_detector_window(row, direction, start, end)]
    if not scoped:
        return ""
    nearest = min(scoped, key=lambda row: abs((_parse_ts(_detector_key_ts(row)) - center).total_seconds()))
    ts = _detector_key_ts(nearest)
    extra = nearest.get("reject_reason", "") or nearest.get("family_hint", "") or nearest.get("close_reason", "")
    return f"{label}:{ts}:{extra}"


def _review_priority(row_count: int, max_favorable: float | None, best_adverse: float | None, detector_hits: int) -> float:
    favorable = max_favorable or 0.0
    adverse = best_adverse or 0.0
    return favorable + row_count * 10.0 + detector_hits * 50.0 - adverse


def _make_move_window(
    cluster_index: int,
    rows: list[dict[str, str]],
    direction: str,
    minute_dataset_root: Path,
    accepted: list[dict[str, str]],
    m2_rows: list[dict[str, str]],
    rejects: list[dict[str, str]],
    interesting: list[dict[str, str]],
) -> MoveFirstWindow:
    ordered = sorted(rows, key=lambda row: _parse_ts(row["ts"]))
    start = _parse_ts(ordered[0]["ts"])
    end = _parse_ts(ordered[-1]["ts"])
    day = ordered[0].get("day", start.strftime("%Y-%m-%d"))
    start_window = start - timedelta(minutes=DETECTOR_LOOKBACK_MINUTES)
    end_window = end + timedelta(minutes=DETECTOR_LOOKAHEAD_MINUTES)

    stats = []
    for row in ordered:
        favorable, time_to_hit, adverse_before_hit = _forward_stats(minute_dataset_root, row, direction)
        if time_to_hit is not None:
            stats.append((row, favorable, time_to_hit, adverse_before_hit))
    if stats:
        earliest = sorted(stats, key=lambda item: _parse_ts(item[0]["ts"]))[0]
        best = sorted(stats, key=lambda item: ((item[3] or 999999.0), item[2], _parse_ts(item[0]["ts"])))[0]
    else:
        earliest = (ordered[0], None, None, None)
        best = earliest

    context_rows = _mechanics_rows(minute_dataset_root, start - timedelta(minutes=CONTEXT_MINUTES), start)
    pre_context_move = _directional_context_move(context_rows, direction)
    pre_context_delta = _sum_delta(context_rows)

    accepted_near = [row for row in accepted if _within_detector_window(row, direction, start_window, end_window)]
    m2_near = [row for row in m2_rows if _within_detector_window(row, direction, start_window, end_window)]
    rejects_near = [row for row in rejects if _within_detector_window(row, direction, start_window, end_window)]
    interesting_near = [row for row in interesting if _within_detector_window(row, direction, start_window, end_window)]
    detector_hits = len(accepted_near) + len(m2_near) + len(rejects_near) + len(interesting_near)
    max_favorable = max((item[1] or 0.0 for item in stats), default=0.0)
    max_adverse = max((item[3] or 0.0 for item in stats), default=0.0)
    priority = _review_priority(len(ordered), max_favorable, best[3], detector_hits)

    return MoveFirstWindow(
        move_cluster_id=f"{day}_{direction}_mf{cluster_index:03d}",
        day=day,
        direction=direction,
        move_signal_start=ordered[0]["ts"],
        move_signal_end=ordered[-1]["ts"],
        row_count=len(ordered),
        earliest_proxy_ts=earliest[0]["ts"],
        earliest_proxy_price=_fmt_float(_entry_price(earliest[0])),
        earliest_time_to_1000_min=_fmt_float(earliest[2]),
        earliest_adverse_before_1000=_fmt_float(earliest[3]),
        best_proxy_ts=best[0]["ts"],
        best_proxy_price=_fmt_float(_entry_price(best[0])),
        best_time_to_1000_min=_fmt_float(best[2]),
        best_adverse_before_1000=_fmt_float(best[3]),
        max_favorable_60m=_fmt_float(max_favorable),
        max_adverse_before_1000=_fmt_float(max_adverse),
        pre_context_directional_move=_fmt_float(pre_context_move),
        pre_context_delta_sum=_fmt_float(pre_context_delta),
        detector_window_start=_fmt_ts(start_window),
        detector_window_end=_fmt_ts(end_window),
        accepted_peak_count_near=len(accepted_near),
        m2_6_count_near=len(m2_near),
        reject_count_near=len(rejects_near),
        interesting_reject_count_near=len(interesting_near),
        nearest_accepted_peak=_nearest_detector(accepted, direction, start, start_window, end_window, "accepted"),
        nearest_m2_6=_nearest_detector(m2_rows, direction, start, start_window, end_window, "m2_6"),
        nearest_reject=_nearest_detector(rejects, direction, start, start_window, end_window, "reject"),
        source_basis="minute_events_outcomes_move_first",
        review_priority=_fmt_float(priority),
        notes="market move first; detectors are annotations only",
    )


def _write_summary(path: Path, rows: list[MoveFirstWindow], scope_id: str) -> None:
    by_direction = Counter(row.direction for row in rows)
    no_detector = [
        row
        for row in rows
        if row.accepted_peak_count_near == 0 and row.m2_6_count_near == 0 and row.reject_count_near == 0
    ]
    with_accepted = [row for row in rows if row.accepted_peak_count_near > 0]
    with_m2 = [row for row in rows if row.m2_6_count_near > 0]
    with_reject = [row for row in rows if row.reject_count_near > 0]
    top_rows = sorted(rows, key=lambda row: float(row.review_priority or 0.0), reverse=True)[:20]
    lines = [
        "# Move-First Research Windows",
        "",
        f"scope: `{scope_id}`",
        f"move_threshold_usd: `{MOVE_THRESHOLD_USD:.0f}`",
        f"forward_minutes: `{FORWARD_MINUTES}`",
        f"move_window_count: `{len(rows)}`",
        "",
        "## Direction Counts",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_direction.items()))
    lines.extend(
        [
            "",
            "## Detector Coverage",
            "",
            f"- move windows with nearby accepted PEAK: `{len(with_accepted)}`",
            f"- move windows with no nearby accepted PEAK: `{len(rows) - len(with_accepted)}`",
            f"- move windows with nearby M2.6 candidate: `{len(with_m2)}`",
            f"- move windows with nearby reject row: `{len(with_reject)}`",
            f"- move windows with no nearby accepted/M2.6/reject annotation: `{len(no_detector)}`",
            "",
            "## Top Move-First Windows",
            "",
        ]
    )
    for row in top_rows:
        lines.append(
            f"- `{row.move_cluster_id}` `{row.move_signal_start}` -> `{row.move_signal_end}` "
            f"`{row.direction}` fav60={row.max_favorable_60m} "
            f"best={row.best_proxy_ts} adverse={row.best_adverse_before_1000} "
            f"accepted={row.accepted_peak_count_near} m2_6={row.m2_6_count_near} rejects={row.reject_count_near}"
        )
    lines.extend(
        [
            "",
            "## Use",
            "",
            "This artifact starts from market movement, not PEAK/M2.6/reject rows.",
            "Use detector fields only to ask whether existing logic saw the move, missed it, or filtered it.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_move_first_windows(review_root: Path, minute_dataset_root: Path, output_root: Path) -> tuple[Path, Path, int]:
    accepted, m2_rows, rejects, interesting = _load_detector_rows(review_root, minute_dataset_root)
    windows: list[MoveFirstWindow] = []
    cluster_index = 1
    paths = _outcome_paths(minute_dataset_root)
    for path in paths:
        for direction in ("long", "short"):
            signal_rows = _candidate_signal_rows(path, direction)
            for cluster in _cluster_signal_rows(signal_rows):
                windows.append(
                    _make_move_window(
                        cluster_index,
                        cluster,
                        direction,
                        minute_dataset_root,
                        accepted,
                        m2_rows,
                        rejects,
                        interesting,
                    )
                )
                cluster_index += 1
    if not paths:
        raise RuntimeError(f"no minute_events_outcomes files found under {minute_dataset_root}")
    first_day = paths[0].stem.replace("minute_events_outcomes_", "")
    last_day = paths[-1].stem.replace("minute_events_outcomes_", "")
    scope_id = f"{first_day}_to_{last_day}"
    output_root.mkdir(parents=True, exist_ok=True)
    out_csv = output_root / f"move_first_windows_{scope_id}.csv"
    out_md = output_root / f"move_first_windows_{scope_id}.md"
    final_rows = sorted(windows, key=lambda row: float(row.review_priority or 0.0), reverse=True)
    _write_csv(out_csv, final_rows)
    _write_summary(out_md, final_rows, scope_id)
    return out_csv, out_md, len(final_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build market move-first research windows independent of PEAK selection")
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--minute-dataset-root", required=True)
    parser.add_argument("--output-root", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_csv, out_md, row_count = build_move_first_windows(
        review_root=Path(args.review_root),
        minute_dataset_root=Path(args.minute_dataset_root),
        output_root=Path(args.output_root),
    )
    print("DeltaScout Move-First Research Window Build")
    print(f"move_first_windows={out_csv}")
    print(f"move_first_summary={out_md}")
    print(f"move_window_count={row_count}")


if __name__ == "__main__":
    main()
