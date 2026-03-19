from __future__ import annotations

from collections import defaultdict

from ..config import RAW_DELTA_EVENTS
from ..types import EventsBaseRow, FeedRow, NormalizedEvent
from .matcher import FeedMatcher


def _terminal_decision_map(events: list[NormalizedEvent]) -> dict[tuple[object, str | None], bool]:
    grouped: dict[tuple[object, str | None], bool] = defaultdict(bool)
    for event in events:
        if event.event_type not in RAW_DELTA_EVENTS:
            grouped[(event.ts, event.kind)] = True
    return grouped


def build_events_base_dataset(events: list[NormalizedEvent], feed_rows: list[FeedRow]) -> list[EventsBaseRow]:
    matcher = FeedMatcher(feed_rows)
    terminal_map = _terminal_decision_map(events)
    dataset: list[EventsBaseRow] = []

    for event in events:
        matched_feed = matcher.match(event)
        terminal_present = True
        if event.event_type in RAW_DELTA_EVENTS:
            terminal_present = terminal_map.get((event.ts, event.kind), False)

        dataset.append(
            EventsBaseRow(
                ts=event.ts,
                event_type=event.event_type,
                kind=event.kind,
                reject_reason=event.reject_reason,
                delta=event.delta,
                vol=event.vol,
                imb=event.imb,
                price=event.price,
                vwap=event.vwap,
                poc=event.poc,
                matched_feed_ts=matched_feed.ts if matched_feed else None,
                source_file=event.source_file,
                terminal_decision_present=terminal_present,
            )
        )
    return dataset
