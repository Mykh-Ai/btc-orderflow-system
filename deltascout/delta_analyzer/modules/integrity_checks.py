from __future__ import annotations

from collections import Counter

from ..config import RAW_DELTA_EVENTS
from ..types import EventsBaseRow, IntegrityReport


def run_integrity_checks(rows: list[EventsBaseRow]) -> IntegrityReport:
    ts_counts = Counter(row.ts for row in rows)
    unmatched_events = [
        f"{row.ts.isoformat()}::{row.event_type}::{row.source_file}"
        for row in rows
        if row.matched_feed_ts is None
    ]
    raw_delta_without_terminal_decision = sum(
        1
        for row in rows
        if row.event_type in RAW_DELTA_EVENTS and not row.terminal_decision_present
    )
    multi_event_timestamps = sum(1 for count in ts_counts.values() if count > 1)

    return IntegrityReport(
        missing_feed_match_count=len(unmatched_events),
        multi_event_timestamps=multi_event_timestamps,
        unmatched_events=unmatched_events,
        raw_delta_without_terminal_decision=raw_delta_without_terminal_decision,
    )
