from __future__ import annotations

import argparse
import glob
from collections import Counter
from pathlib import Path

from .config import DEFAULT_ARCHIVE_GLOB, DEFAULT_FEED_GLOB
from .modules.archive_reader import read_archive_events
from .modules.build_events_base import build_events_base_dataset
from .modules.feed_reader import read_feed_rows
from .modules.integrity_checks import run_integrity_checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeltaScout delta_analyzer Phase 1 CLI")
    parser.add_argument("--archive-glob", default=DEFAULT_ARCHIVE_GLOB, help="Glob for archive JSONL files")
    parser.add_argument("--feed-glob", default=DEFAULT_FEED_GLOB, help="Glob for feed CSV files")
    return parser


def _expand_glob(pattern: str) -> list[Path]:
    return [Path(path) for path in sorted(glob.glob(pattern))]


def main() -> None:
    args = build_parser().parse_args()
    archive_files = _expand_glob(args.archive_glob)
    feed_files = _expand_glob(args.feed_glob)

    events = read_archive_events(archive_files)
    feed_rows = read_feed_rows(feed_files)
    dataset = build_events_base_dataset(events, feed_rows)
    checks = run_integrity_checks(dataset)

    event_counts = Counter(row.event_type for row in dataset)

    print("Delta Analyzer Phase 1 Summary")
    print(f"archive_files={len(archive_files)}")
    print(f"feed_files={len(feed_files)}")
    print(f"events={len(events)}")
    print(f"events_base_rows={len(dataset)}")
    print(f"event_type_counts={dict(event_counts)}")
    print(f"missing_feed_match_count={checks.missing_feed_match_count}")
    print(f"multi_event_timestamps={checks.multi_event_timestamps}")
    print(f"raw_delta_without_terminal_decision={checks.raw_delta_without_terminal_decision}")
    print(f"unmatched_events={len(checks.unmatched_events)}")
    if checks.unmatched_events:
        print("unmatched_event_samples=")
        for item in checks.unmatched_events[:5]:
            print(f"  - {item}")


if __name__ == "__main__":
    main()
