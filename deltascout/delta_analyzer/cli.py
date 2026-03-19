from __future__ import annotations

import argparse
import glob
from collections import Counter
from pathlib import Path

from .config import DEFAULT_ARCHIVE_GLOB, DEFAULT_FEED_GLOB
from .modules.archive_reader import read_archive_events
from .modules.build_events_base import build_events_base_dataset
from .modules.build_events_context import build_events_context_dataset
from .modules.feed_reader import read_feed_rows
from .modules.integrity_checks import run_integrity_checks


DATASET_CHOICES = ("events_base", "events_context")
CONTEXT_COVERAGE_FIELDS = (
    "cum_delta_24h",
    "cum_delta_180m",
    "cum_delta_60m",
    "cum_delta_utc_day",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
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
    return parser


def _expand_glob(pattern: str) -> list[Path]:
    return [Path(path) for path in sorted(glob.glob(pattern))]


def main() -> None:
    args = build_parser().parse_args()
    archive_files = _expand_glob(args.archive_glob)
    feed_files = _expand_glob(args.feed_glob)

    events = read_archive_events(archive_files)
    feed_rows = read_feed_rows(feed_files)
    events_base = build_events_base_dataset(events, feed_rows)
    events_context = []
    if args.dataset == "events_context":
        events_context = build_events_context_dataset(events_base, feed_rows)
    checks = run_integrity_checks(events_base)

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
