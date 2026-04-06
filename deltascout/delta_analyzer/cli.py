from __future__ import annotations

import argparse
import csv
import glob
from collections import Counter
from dataclasses import fields as dataclass_fields
from datetime import datetime, timedelta
from pathlib import Path

from .config import DEFAULT_ARCHIVE_GLOB, DEFAULT_FEED_GLOB
from .modules.archive_reader import read_archive_events
from .modules.build_events_base import build_events_base_dataset
from .modules.build_events_context import build_events_context_dataset
from .modules.build_minute_events_base import build_minute_events_base_dataset
from .modules.build_minute_events_mechanics import build_minute_events_mechanics_dataset
from .modules.build_minute_events_outcomes import build_minute_events_outcomes_dataset
from .modules.build_minute_event_process_chain import build_m2_6_outputs_for_scope
from .modules.build_review_tables import ReviewBuildError, build_daily_review_package
from .modules.feed_reader import read_feed_rows
from .modules.integrity_checks import run_integrity_checks
from .types import EventsContextRow, MinuteEventMechanicsRow, MinuteEventOutcomesRow, MinuteEventRow


DATASET_CHOICES = ("events_base", "events_context", "minute_events_base", "minute_events_mechanics", "minute_events_outcomes")
DEFAULT_DATASET_ROOT = "/data/archive/datasets"
CONTEXT_COVERAGE_FIELDS = (
    "cum_delta_24h",
    "cum_delta_180m",
    "cum_delta_60m",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
)
MECHANICS_COVERAGE_FIELDS = (
    "delta_pct_60m",
    "delta_pct_180m",
    "vol_pct_60m",
    "vol_pct_180m",
    "body_to_range_ratio",
    "dist_from_vwap",
)
OUTCOMES_COVERAGE_FIELDS = (
    "ret_fwd_15m",
    "upside_max_15m",
    "downside_max_15m",
    "favorable_max_15m",
    "up_hit_10bp_15m_flag",
    "both_hit_10bp_15m_flag",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeltaScout delta_analyzer CLI")
    parser.add_argument("--archive-glob", default=DEFAULT_ARCHIVE_GLOB, help="Glob for archive JSONL files")
    parser.add_argument("--feed-glob", default=DEFAULT_FEED_GLOB, help="Glob for feed CSV files")
    parser.add_argument(
        "--dataset",
        choices=DATASET_CHOICES,
        default="events_context",
        help="Highest dataset layer to build. events_context also builds events_base.",
    )
    parser.add_argument("--build-review", action="store_true", help="Build Phase 2.5 daily review artifacts from dataset CSV inputs.")
    parser.add_argument("--build-m2-6", action="store_true", help="Build M2.6 process-chain bridge outputs from minute datasets.")
    parser.add_argument("--date", help="UTC date for review build mode in YYYY-MM-DD format.")
    parser.add_argument("--date-from", help="Start UTC date for range builds in YYYY-MM-DD format.")
    parser.add_argument("--date-to", help="End UTC date for range builds in YYYY-MM-DD format.")
    parser.add_argument("--input-root", default=DEFAULT_DATASET_ROOT, help="Dataset root for review-builder inputs.")
    parser.add_argument("--output-root", default=DEFAULT_DATASET_ROOT, help="Dataset root for review-builder outputs.")
    return parser


def _expand_glob(pattern: str) -> list[Path]:
    return [Path(path) for path in sorted(glob.glob(pattern))]


def _resolve_feed_files(pattern: str) -> list[Path]:
    return _expand_glob(pattern)


def _resolve_prev_day_feed(feed_files: list[Path], date_str: str) -> Path | None:
    if not feed_files or not date_str:
        return None
    prev_date = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    feed_dir = feed_files[0].parent
    for suffix in (".csv",):
        candidate = feed_dir / f"{prev_date}{suffix}"
        if candidate.exists():
            return candidate
    return None


def _write_dataclass_csv(rows: list[object], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return out_path
    field_names = [f.name for f in dataclass_fields(type(rows[0]))]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(field_names)
        for row in rows:
            vals = [getattr(row, f) for f in field_names]
            writer.writerow(["" if v is None else v for v in vals])
    return out_path


def _write_events_context_csv(rows: list[EventsContextRow], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    field_names = [f.name for f in dataclass_fields(EventsContextRow)]
    header = [field_names[0], "day"] + field_names[1:]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            ts_val = row.ts
            day_val = ts_val.strftime("%Y-%m-%d") if ts_val else ""
            vals = [getattr(row, f) for f in field_names]
            vals.insert(1, day_val)
            writer.writerow(["" if v is None else v for v in vals])
    return out_path


def _write_minute_events_base_csv(rows: list[MinuteEventRow], out_path: Path) -> Path:
    return _write_dataclass_csv(rows, out_path)


def _write_minute_events_mechanics_csv(rows: list[MinuteEventMechanicsRow], out_path: Path) -> Path:
    return _write_dataclass_csv(rows, out_path)


def _write_minute_events_outcomes_csv(rows: list[MinuteEventOutcomesRow], out_path: Path) -> Path:
    return _write_dataclass_csv(rows, out_path)


def main() -> None:
    args = build_parser().parse_args()
    if args.build_review:
        if not args.date:
            raise SystemExit("--date is required with --build-review")
        try:
            result = build_daily_review_package(args.date, args.input_root, args.output_root)
        except ReviewBuildError as exc:
            raise SystemExit(str(exc)) from exc
        print("Delta Analyzer Review Build")
        print(f"processed_date={result.date}")
        print(f"accepted_rows={result.accepted_count}")
        print(f"reject_rows={result.reject_count}")
        print(f"matched_accepted_close_rows={result.matched_close_count}")
        print(f"output_dir={result.output_dir}")
        return
    if args.build_m2_6:
        if args.date and (args.date_from or args.date_to):
            raise SystemExit("--date cannot be combined with --date-from/--date-to in --build-m2-6 mode")
        if args.date_from and not args.date_to:
            args.date_to = args.date_from
        try:
            result = build_m2_6_outputs_for_scope(
                input_root=args.input_root,
                output_root=args.output_root,
                date=args.date,
                date_from=args.date_from,
                date_to=args.date_to,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print("Delta Analyzer M2.6 Build")
        print(f"minute_event_chain_candidates_csv={result['candidates']}")
        print(f"minute_event_chain_reference_cases_csv={result['reference_cases']}")
        print(f"chain_cluster_summaries_csv={result['cluster_summaries']}")
        return

    feed_files = _resolve_feed_files(args.feed_glob)
    if not feed_files:
        raise SystemExit(f"no feed files matched: {args.feed_glob}")

    feed_rows = read_feed_rows(feed_files)
    minute_events_base: list[MinuteEventRow] = []
    if args.dataset in {"minute_events_base", "minute_events_mechanics", "minute_events_outcomes"}:
        minute_events_base = build_minute_events_base_dataset(feed_rows)

    if args.dataset == "minute_events_base":
        if args.date:
            dated = [r for r in minute_events_base if r.day == args.date]
            out_path = Path(args.output_root) / f"minute_events_base_{args.date}.csv"
            written = _write_minute_events_base_csv(dated, out_path)
            print(f"minute_events_base_csv={written} rows={len(dated)}")
        print(f"Delta Analyzer Summary ({args.dataset})")
        print(f"feed_files={len(feed_files)}")
        print(f"minute_events_base_rows={len(minute_events_base)}")
        return

    minute_events_mechanics: list[MinuteEventMechanicsRow] = []
    if args.dataset in {"minute_events_mechanics", "minute_events_outcomes"}:
        minute_events_mechanics = build_minute_events_mechanics_dataset(minute_events_base)

    if args.dataset == "minute_events_mechanics":
        if args.date:
            dated = [r for r in minute_events_mechanics if r.day == args.date]
            out_path = Path(args.output_root) / f"minute_events_mechanics_{args.date}.csv"
            written = _write_minute_events_mechanics_csv(dated, out_path)
            print(f"minute_events_mechanics_csv={written} rows={len(dated)}")
        print(f"Delta Analyzer Summary ({args.dataset})")
        print(f"feed_files={len(feed_files)}")
        print(f"minute_events_base_rows={len(minute_events_base)}")
        print(f"minute_events_mechanics_rows={len(minute_events_mechanics)}")
        print("mechanics_non_null_coverage=")
        total_rows = len(minute_events_mechanics)
        for field in MECHANICS_COVERAGE_FIELDS:
            non_null = sum(1 for row in minute_events_mechanics if getattr(row, field) is not None)
            print(f"  {field}={non_null}/{total_rows}")
        return

    minute_events_outcomes: list[MinuteEventOutcomesRow] = []
    if args.dataset == "minute_events_outcomes":
        minute_events_outcomes = build_minute_events_outcomes_dataset(minute_events_mechanics)
        if args.date:
            dated = [r for r in minute_events_outcomes if r.day == args.date]
            out_path = Path(args.output_root) / f"minute_events_outcomes_{args.date}.csv"
            written = _write_minute_events_outcomes_csv(dated, out_path)
            print(f"minute_events_outcomes_csv={written} rows={len(dated)}")
        print(f"Delta Analyzer Summary ({args.dataset})")
        print(f"feed_files={len(feed_files)}")
        print(f"minute_events_base_rows={len(minute_events_base)}")
        print(f"minute_events_mechanics_rows={len(minute_events_mechanics)}")
        print(f"minute_events_outcomes_rows={len(minute_events_outcomes)}")
        print("outcomes_non_null_coverage=")
        total_rows = len(minute_events_outcomes)
        for field in OUTCOMES_COVERAGE_FIELDS:
            non_null = sum(1 for row in minute_events_outcomes if getattr(row, field) is not None)
            print(f"  {field}={non_null}/{total_rows}")
        return

    archive_files = _expand_glob(args.archive_glob)
    events = read_archive_events(archive_files)
    context_feed_rows = feed_rows
    if args.date:
        prev_feed = _resolve_prev_day_feed(feed_files, args.date)
        if prev_feed:
            prev_rows = read_feed_rows([prev_feed])
            context_feed_rows = sorted(prev_rows + feed_rows, key=lambda r: r.ts)
    events_base = build_events_base_dataset(events, feed_rows)
    events_context: list[EventsContextRow] = []
    if args.dataset == "events_context":
        events_context = build_events_context_dataset(events_base, context_feed_rows)
    checks = run_integrity_checks(events_base)

    if events_context and args.date:
        output_root = Path(args.output_root)
        out_path = output_root / f"events_context_{args.date}.csv"
        dated = [r for r in events_context if r.ts.strftime("%Y-%m-%d") == args.date]
        written = _write_events_context_csv(dated, out_path)
        print(f"events_context_csv={written} rows={len(dated)}")

    event_counts = Counter(row.event_type for row in events_base)

    print(f"Delta Analyzer Summary ({args.dataset})")
    print(f"archive_files={len(archive_files)}")
    print(f"feed_files={len(feed_files)}")
    print(f"events={len(events)}")
    print(f"events_base_rows={len(events_base)}")
    print(f"events_context_rows={len(events_context)}")
    print(f"event_type_counts={dict(event_counts)}")
    print(f"missing_feed_match_count={checks.missing_feed_match_count}")
    print(f"multi_event_timestamps={checks.multi_event_timestamps}")
    print(f"raw_delta_without_terminal_decision={checks.raw_delta_without_terminal_decision}")
    print(f"unmatched_events={len(checks.unmatched_events)}")
    if checks.unmatched_events:
        print("unmatched_event_samples=")
        for item in checks.unmatched_events[:5]:
            print(f"  - {item}")
    if events_context:
        print("context_non_null_coverage=")
        total_rows = len(events_context)
        for field in CONTEXT_COVERAGE_FIELDS:
            non_null = sum(1 for row in events_context if getattr(row, field) is not None)
            print(f"  {field}={non_null}/{total_rows}")


if __name__ == "__main__":
    main()
