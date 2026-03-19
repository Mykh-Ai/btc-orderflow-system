from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedEvent:
    ts: datetime
    event_type: str
    kind: str | None
    reject_reason: str | None
    delta: float | None
    vol: float | None
    imb: float | None
    price: float | None
    vwap: float | None
    poc: float | None
    source_file: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class FeedRow:
    ts: datetime
    price: float | None
    row: dict[str, Any]
    source_file: str


@dataclass(frozen=True)
class EventsBaseRow:
    ts: datetime
    event_type: str
    kind: str | None
    reject_reason: str | None
    delta: float | None
    vol: float | None
    imb: float | None
    price: float | None
    vwap: float | None
    poc: float | None
    matched_feed_ts: datetime | None
    source_file: str
    terminal_decision_present: bool


@dataclass(frozen=True)
class IntegrityReport:
    missing_feed_match_count: int
    multi_event_timestamps: int
    unmatched_events: list[str]
    raw_delta_without_terminal_decision: int
