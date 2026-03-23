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
    buy_qty: float | None
    sell_qty: float | None
    open_interest: float | None
    funding_rate: float | None
    liq_buy_qty: float | None
    liq_sell_qty: float | None
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
    matched_open_interest: float | None
    matched_funding_rate: float | None
    matched_liq_buy_qty: float | None
    matched_liq_sell_qty: float | None
    source_file: str
    terminal_decision_present: bool


@dataclass(frozen=True)
class EventsContextRow:
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
    matched_open_interest: float | None
    matched_funding_rate: float | None
    matched_liq_buy_qty: float | None
    matched_liq_sell_qty: float | None
    source_file: str
    terminal_decision_present: bool
    cum_delta_24h: float | None
    cum_delta_180m: float | None
    cum_delta_60m: float | None
    ret_15m: float | None
    ret_60m: float | None
    dist_vwap: float | None
    abs_dist_vwap: float | None
    price_vs_vwap_side: str


@dataclass(frozen=True)
class IntegrityReport:
    missing_feed_match_count: int
    multi_event_timestamps: int
    unmatched_events: list[str]
    raw_delta_without_terminal_decision: int
