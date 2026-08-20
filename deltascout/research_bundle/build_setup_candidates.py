from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import DATE_FORMAT

MOVE_THRESHOLD_USD = 1000.0


@dataclass(frozen=True)
class SetupCandidate:
    ts: str
    day: str
    source_type: str
    direction: str
    family_hint: str
    setup_track: str
    maturity: str
    lifecycle_bucket: str
    outcome_source: str
    reject_reason: str
    interesting_bucket: str
    interesting_rule_id: str
    price_vs_vwap_side: str
    cum_delta_24h: str
    cum_delta_180m: str
    cum_delta_60m: str
    ret_15m: str
    ret_60m: str
    ret_fwd_30m: str
    ret_fwd_60m: str
    directional_ret_fwd_30m: str
    directional_ret_fwd_60m: str
    favorable_max_30m: str
    favorable_max_60m: str
    adverse_max_30m: str
    adverse_max_60m: str
    move_1000_hit: str
    priority_score: str
    notes: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[SetupCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SetupCandidate.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _write_summary(path: Path, rows: list[SetupCandidate], scope_id: str) -> None:
    by_source = Counter(row.source_type for row in rows)
    by_track = Counter(row.setup_track for row in rows)
    by_direction = Counter(row.direction for row in rows)
    by_lifecycle = Counter(row.lifecycle_bucket for row in rows if row.lifecycle_bucket)
    top_rows = sorted(rows, key=lambda row: float(row.priority_score or 0.0), reverse=True)[:12]

    lines = [
        "# Setup Candidate Discovery Summary",
        "",
        f"scope: `{scope_id}`",
        f"move_threshold_usd: `{MOVE_THRESHOLD_USD:.0f}`",
        f"candidate_rows: `{len(rows)}`",
        "",
        "## Source Counts",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_source.items()))
    lines.extend(["", "## Track Counts", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_track.items()))
    lines.extend(["", "## Direction Counts", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_direction.items()))
    lines.extend(["", "## Accepted Lifecycle Coverage", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_lifecycle.items()))
    lines.extend(["", "## Top Priority Candidates", ""])
    for row in top_rows:
        lines.append(
            f"- `{row.ts}` `{row.direction}` `{row.source_type}` "
            f"`{row.setup_track}` score={row.priority_score} "
            f"dir60={row.directional_ret_fwd_60m} fav60={row.favorable_max_60m}"
        )
    lines.extend(
        [
            "",
            "## Use",
            "",
            "This file is a research surface, not a live signal spec.",
            "Promote a row family only after clustered repeatability, lifecycle fit, and entry timing are reviewed.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


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


def _directional_value(direction: str, raw_value: str | None) -> float | None:
    value = _float_text(raw_value)
    if value is None:
        return None
    if direction == "short":
        return -value
    return value


def _max_present(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present)


def _day_from_ts(ts: str) -> str:
    return ts[:10]


def _parse_day(path: Path) -> str | None:
    try:
        datetime.strptime(path.name, DATE_FORMAT)
    except ValueError:
        return None
    return path.name


def _discover_scope(review_root: Path) -> tuple[list[Path], str]:
    review_dirs = [path for path in sorted(review_root.iterdir()) if path.is_dir() and _parse_day(path)]
    if not review_dirs:
        raise RuntimeError(f"no daily review folders found in {review_root}")
    return review_dirs, f"{review_dirs[0].name}_to_{review_dirs[-1].name}"


def _load_outcomes(minute_dataset_root: Path, day: str) -> dict[str, dict[str, str]]:
    path = minute_dataset_root / f"minute_events_outcomes_{day}.csv"
    return {row.get("ts", ""): row for row in _read_csv_rows(path)}


def _outcome_direction_fields(direction: str, outcome: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    dir30 = _directional_value(direction, outcome.get("ret_fwd_30m"))
    dir60 = _directional_value(direction, outcome.get("ret_fwd_60m"))
    if direction == "short":
        fav30 = _float_text(outcome.get("downside_max_30m"))
        fav60 = _float_text(outcome.get("downside_max_60m"))
        adv30 = _float_text(outcome.get("upside_max_30m"))
        adv60 = _float_text(outcome.get("upside_max_60m"))
    else:
        fav30 = _float_text(outcome.get("upside_max_30m"))
        fav60 = _float_text(outcome.get("upside_max_60m"))
        adv30 = _float_text(outcome.get("downside_max_30m"))
        adv60 = _float_text(outcome.get("downside_max_60m"))
    return (
        _fmt_float(dir30),
        _fmt_float(dir60),
        _fmt_float(fav30),
        _fmt_float(fav60),
        _fmt_float(adv30),
        _fmt_float(adv60),
    )


def _move_hit(*values: str) -> bool:
    for value in values:
        parsed = _float_text(value)
        if parsed is not None and parsed >= MOVE_THRESHOLD_USD:
            return True
    return False


def _priority(*values: str, source_bonus: float = 0.0) -> str:
    parsed = [_float_text(value) for value in values]
    best = _max_present(parsed) or 0.0
    return _fmt_float(best + source_bonus)


def _candidate_track_for_m2(row: dict[str, str]) -> tuple[str, str]:
    family = row.get("family_hint", "")
    role = row.get("chain_role_hypothesis", "")
    if family == "F1" and "late" in role:
        return "m2_6_late_no_edge_warning", "late/no-edge warning"
    if family in {"F1", "F2"}:
        return "m2_6_process_chain", "candidate setup class"
    return "m2_6_process_chain", "entry candidate"


def _build_m2_candidates(minute_dataset_root: Path) -> list[SetupCandidate]:
    candidates: list[SetupCandidate] = []
    for path in sorted((minute_dataset_root / "m2_6").glob("minute_event_chain_candidates_*.csv")):
        for row in _read_csv_rows(path):
            direction = row.get("direction", "")
            dir30 = _directional_value(direction, row.get("ret_fwd_30m"))
            dir60 = _directional_value(direction, row.get("ret_fwd_60m"))
            fav30 = _float_text(row.get("favorable_max_30m"))
            fav60 = None
            adv30 = _float_text(row.get("adverse_max_30m"))
            adv60 = None
            if (_max_present([dir30, dir60, fav30]) or 0.0) < MOVE_THRESHOLD_USD:
                continue
            setup_track, maturity = _candidate_track_for_m2(row)
            candidates.append(
                SetupCandidate(
                    ts=row.get("ts", ""),
                    day=row.get("day", "") or _day_from_ts(row.get("ts", "")),
                    source_type="m2_6_chain_candidate",
                    direction=direction,
                    family_hint=row.get("family_hint", ""),
                    setup_track=setup_track,
                    maturity=maturity,
                    lifecycle_bucket="",
                    outcome_source="forward_return_dataset",
                    reject_reason="",
                    interesting_bucket="",
                    interesting_rule_id="",
                    price_vs_vwap_side=row.get("price_vs_vwap_side", ""),
                    cum_delta_24h=row.get("cum_delta_24h", ""),
                    cum_delta_180m=row.get("cum_delta_180m", ""),
                    cum_delta_60m=row.get("cum_delta_60m", ""),
                    ret_15m=row.get("ret_15m", ""),
                    ret_60m=row.get("ret_60m", ""),
                    ret_fwd_30m=row.get("ret_fwd_30m", ""),
                    ret_fwd_60m=row.get("ret_fwd_60m", ""),
                    directional_ret_fwd_30m=_fmt_float(dir30),
                    directional_ret_fwd_60m=_fmt_float(dir60),
                    favorable_max_30m=_fmt_float(fav30),
                    favorable_max_60m=_fmt_float(fav60),
                    adverse_max_30m=_fmt_float(adv30),
                    adverse_max_60m=_fmt_float(adv60),
                    move_1000_hit="true",
                    priority_score=_priority(_fmt_float(dir30), _fmt_float(dir60), _fmt_float(fav30), source_bonus=200.0),
                    notes=f"reference_window_id={row.get('reference_window_id', '')}; role={row.get('chain_role_hypothesis', '')}",
                )
            )
    return candidates


def _build_reject_candidates(review_dirs: list[Path], minute_dataset_root: Path) -> list[SetupCandidate]:
    candidates: list[SetupCandidate] = []
    outcomes_cache: dict[str, dict[str, dict[str, str]]] = {}
    for review_dir in review_dirs:
        day = review_dir.name
        outcomes_cache[day] = _load_outcomes(minute_dataset_root, day)
        interesting_rows = _read_csv_rows(review_dir / f"interesting_rejects_{day}.csv")
        interesting_lookup = {
            (row.get("ts", ""), row.get("kind", ""), row.get("reject_reason", "")): row
            for row in interesting_rows
        }
        for row in _read_csv_rows(review_dir / f"reject_event_context_{day}.csv"):
            direction = row.get("kind", "")
            outcome = outcomes_cache[day].get(row.get("ts", ""), {})
            dir30, dir60, fav30, fav60, adv30, adv60 = _outcome_direction_fields(direction, outcome)
            interesting = interesting_lookup.get((row.get("ts", ""), direction, row.get("reject_reason", "")), {})
            is_interesting = bool(interesting)
            if not is_interesting and not _move_hit(dir30, dir60, fav30, fav60):
                continue
            if not _move_hit(dir30, dir60, fav30, fav60):
                continue
            candidates.append(
                SetupCandidate(
                    ts=row.get("ts", ""),
                    day=day,
                    source_type="interesting_reject" if is_interesting else "reject_1000_hit",
                    direction=direction,
                    family_hint="",
                    setup_track="rejected_family_followthrough",
                    maturity="entry candidate",
                    lifecycle_bucket="",
                    outcome_source="reject_context+minute_outcomes",
                    reject_reason=row.get("reject_reason", ""),
                    interesting_bucket=interesting.get("interesting_reject_bucket", ""),
                    interesting_rule_id=interesting.get("interesting_rule_id", ""),
                    price_vs_vwap_side=row.get("price_vs_vwap_side", ""),
                    cum_delta_24h=row.get("cum_delta_24h", ""),
                    cum_delta_180m=row.get("cum_delta_180m", ""),
                    cum_delta_60m=row.get("cum_delta_60m", ""),
                    ret_15m=row.get("ret_15m", ""),
                    ret_60m=row.get("ret_60m", ""),
                    ret_fwd_30m=outcome.get("ret_fwd_30m", ""),
                    ret_fwd_60m=outcome.get("ret_fwd_60m", ""),
                    directional_ret_fwd_30m=dir30,
                    directional_ret_fwd_60m=dir60,
                    favorable_max_30m=fav30,
                    favorable_max_60m=fav60,
                    adverse_max_30m=adv30,
                    adverse_max_60m=adv60,
                    move_1000_hit="true",
                    priority_score=_priority(dir30, dir60, fav30, fav60, source_bonus=100.0 if is_interesting else 50.0),
                    notes=interesting.get("interesting_reject_note", ""),
                )
            )
    return candidates


def _build_accepted_reference_candidates(review_root: Path, minute_dataset_root: Path) -> list[SetupCandidate]:
    ledger_paths = sorted(review_root.glob("accepted_outcome_ledger_*.csv"))
    if not ledger_paths:
        return []
    ledger_path = ledger_paths[-1]
    candidates: list[SetupCandidate] = []
    outcomes_cache: dict[str, dict[str, dict[str, str]]] = {}
    accepted_context_cache: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    for row in _read_csv_rows(ledger_path):
        ts = row.get("accepted_ts", "")
        day = _day_from_ts(ts)
        direction = row.get("side", "")
        if day not in outcomes_cache:
            outcomes_cache[day] = _load_outcomes(minute_dataset_root, day)
        if day not in accepted_context_cache:
            rows = _read_csv_rows(review_root / day / f"accepted_event_context_{day}.csv")
            accepted_context_cache[day] = {(item.get("ts", ""), item.get("kind", "")): item for item in rows}
        context = accepted_context_cache[day].get((ts, direction), {})
        outcome = outcomes_cache[day].get(ts, {})
        dir30, dir60, fav30, fav60, adv30, adv60 = _outcome_direction_fields(direction, outcome)
        candidates.append(
            SetupCandidate(
                ts=ts,
                day=day,
                source_type="accepted_peak_lifecycle_reference",
                direction=direction,
                family_hint="",
                setup_track="current_peak_emit_reference",
                maturity="phase marker only",
                lifecycle_bucket=row.get("lifecycle_bucket", ""),
                outcome_source=row.get("outcome_source", ""),
                reject_reason="",
                interesting_bucket="",
                interesting_rule_id="",
                price_vs_vwap_side=context.get("price_vs_vwap_side", ""),
                cum_delta_24h=context.get("cum_delta_24h", ""),
                cum_delta_180m=context.get("cum_delta_180m", ""),
                cum_delta_60m=context.get("cum_delta_60m", ""),
                ret_15m=context.get("ret_15m", ""),
                ret_60m=context.get("ret_60m", ""),
                ret_fwd_30m=outcome.get("ret_fwd_30m", ""),
                ret_fwd_60m=outcome.get("ret_fwd_60m", ""),
                directional_ret_fwd_30m=dir30,
                directional_ret_fwd_60m=dir60,
                favorable_max_30m=fav30,
                favorable_max_60m=fav60,
                adverse_max_30m=adv30,
                adverse_max_60m=adv60,
                move_1000_hit="true" if _move_hit(dir30, dir60, fav30, fav60) else "false",
                priority_score=_priority(dir30, dir60, fav30, fav60, source_bonus=25.0),
                notes=row.get("notes", ""),
            )
        )
    return candidates


def build_setup_candidates(review_root: Path, minute_dataset_root: Path, output_root: Path) -> tuple[Path, Path, int]:
    review_dirs, scope_id = _discover_scope(review_root)
    rows = []
    rows.extend(_build_accepted_reference_candidates(review_root, minute_dataset_root))
    rows.extend(_build_m2_candidates(minute_dataset_root))
    rows.extend(_build_reject_candidates(review_dirs, minute_dataset_root))
    deduped: dict[tuple[str, str, str, str, str], SetupCandidate] = {}
    for row in sorted(rows, key=lambda item: float(item.priority_score or 0.0), reverse=True):
        key = (row.ts, row.source_type, row.direction, row.reject_reason, row.family_hint)
        if key not in deduped:
            deduped[key] = row
    final_rows = sorted(deduped.values(), key=lambda item: (item.day, item.ts, item.source_type, item.direction))
    out_csv = output_root / f"setup_candidates_{scope_id}.csv"
    out_md = output_root / f"setup_candidates_{scope_id}_summary.md"
    _write_csv(out_csv, final_rows)
    _write_summary(out_md, final_rows, scope_id)
    return out_csv, out_md, len(final_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build DeltaScout setup discovery candidate table")
    parser.add_argument("--review-root", required=True, help="Root with daily review folders and accepted outcome ledger")
    parser.add_argument("--minute-dataset-root", required=True, help="Root with minute_events_* datasets and m2_6 candidates")
    parser.add_argument("--output-root", required=True, help="Directory for setup candidate outputs")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_csv, out_md, row_count = build_setup_candidates(
        review_root=Path(args.review_root),
        minute_dataset_root=Path(args.minute_dataset_root),
        output_root=Path(args.output_root),
    )
    print("DeltaScout Setup Candidate Discovery Build")
    print(f"setup_candidates={out_csv}")
    print(f"setup_candidates_summary={out_md}")
    print(f"candidate_rows={row_count}")


if __name__ == "__main__":
    main()
