from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_events_context import build_events_context_dataset
from deltascout.delta_analyzer.modules.context_features import FeedContextIndex
from deltascout.delta_analyzer.modules.matcher import FeedMatcher
from deltascout.delta_analyzer.types import EventsBaseRow, FeedRow, NormalizedEvent


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _feed(ts: str, *, price: float | None, buy: float | None, sell: float | None) -> FeedRow:
    return FeedRow(
        ts=_dt(ts),
        price=price,
        buy_qty=buy,
        sell_qty=sell,
        open_interest=None,
        funding_rate=None,
        liq_buy_qty=None,
        liq_sell_qty=None,
        row={},
        source_file="synthetic_feed.csv",
    )


def _event(ts: str) -> NormalizedEvent:
    return NormalizedEvent(
        ts=_dt(ts),
        event_type="DELTA_MAX",
        kind="long",
        reject_reason=None,
        delta=1.0,
        vol=2.0,
        imb=0.5,
        price=101.0,
        vwap=100.0,
        poc=99.0,
        source_file="synthetic_event.jsonl",
        raw={},
    )


def _base_row(ts: str) -> EventsBaseRow:
    return EventsBaseRow(
        ts=_dt(ts),
        event_type="DELTA_MAX",
        kind="long",
        reject_reason=None,
        delta=1.0,
        vol=2.0,
        imb=0.5,
        price=101.0,
        vwap=100.0,
        poc=99.0,
        matched_feed_ts=_dt("2026-01-02T00:15:00"),
        matched_open_interest=None,
        matched_funding_rate=None,
        matched_liq_buy_qty=None,
        matched_liq_sell_qty=None,
        source_file="synthetic_event.jsonl",
        terminal_decision_present=True,
    )


def test_feed_matcher_uses_latest_feed_row_at_or_before_event_ts():
    matcher = FeedMatcher(
        [
            _feed("2026-01-02T00:00:00", price=100.0, buy=1.0, sell=0.0),
            _feed("2026-01-02T00:05:00", price=101.0, buy=2.0, sell=1.0),
        ]
    )

    assert matcher.match(_event("2026-01-02T00:05:00")).ts == _dt("2026-01-02T00:05:00")
    assert matcher.match(_event("2026-01-02T00:04:00")).ts == _dt("2026-01-02T00:00:00")
    assert matcher.match(_event("2026-01-01T23:59:00")) is None


def test_rolling_cum_delta_windows_sum_buy_minus_sell_inside_lookback():
    index = FeedContextIndex(
        [
            _feed("2026-01-01T21:00:00", price=100.0, buy=9.0, sell=3.0),   # +6, inside 24h only
            _feed("2026-01-01T23:30:00", price=101.0, buy=4.0, sell=1.0),   # +3, inside 180m/24h
            _feed("2026-01-02T01:15:00", price=102.0, buy=5.0, sell=2.0),   # +3, inside 60m/180m/24h
            _feed("2026-01-02T01:45:00", price=103.0, buy=1.0, sell=4.0),   # -3, inside 60m/180m/24h
        ]
    )
    event_ts = _dt("2026-01-02T02:00:00")

    assert index.rolling_cum_delta(event_ts, timedelta(minutes=60)) == 0.0
    assert index.rolling_cum_delta(event_ts, timedelta(minutes=180)) == 3.0
    assert index.rolling_cum_delta(event_ts, timedelta(hours=24)) == 9.0



def test_price_delta_uses_backward_boundary_match_and_returns_absolute_difference():
    index = FeedContextIndex(
        [
            _feed("2026-01-02T00:45:00", price=95.0, buy=1.0, sell=0.0),
            _feed("2026-01-02T01:00:00", price=100.0, buy=1.0, sell=0.0),
            _feed("2026-01-02T01:45:00", price=112.0, buy=1.0, sell=0.0),
            _feed("2026-01-02T02:00:00", price=130.0, buy=1.0, sell=0.0),
        ]
    )
    event_ts = _dt("2026-01-02T02:00:00")

    assert index.price_delta(event_ts, timedelta(minutes=15)) == 18.0
    assert index.price_delta(event_ts, timedelta(minutes=60)) == 30.0


def test_missing_history_keeps_partial_delta_but_does_not_invent_price_boundary():
    index = FeedContextIndex(
        [
            _feed("2026-01-02T00:10:00", price=101.0, buy=5.0, sell=1.0),
            _feed("2026-01-02T00:20:00", price=103.0, buy=2.0, sell=1.0),
        ]
    )
    event_ts = _dt("2026-01-02T00:20:00")

    assert index.rolling_cum_delta(event_ts, timedelta(hours=1)) == 5.0
    assert index.price_delta(event_ts, timedelta(minutes=60)) is None


def test_build_events_context_dataset_attaches_expected_phase2_fields():
    rows = build_events_context_dataset(
        [_base_row("2026-01-02T00:30:00")],
        [
            _feed("2026-01-01T23:50:00", price=96.0, buy=3.0, sell=1.0),
            _feed("2026-01-02T00:15:00", price=98.0, buy=5.0, sell=2.0),
            _feed("2026-01-02T00:30:00", price=101.0, buy=4.0, sell=1.0),
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.cum_delta_60m == 8.0
    assert row.ret_15m == 3.0
    assert row.ret_60m is None
    assert row.dist_vwap == 1.0
    assert row.abs_dist_vwap == 1.0
    assert row.price_vs_vwap_side == "above"
