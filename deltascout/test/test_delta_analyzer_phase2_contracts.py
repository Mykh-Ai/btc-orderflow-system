from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_events_context import build_events_context_dataset
from deltascout.delta_analyzer.modules.build_minute_events_base import build_minute_events_base_dataset
from deltascout.delta_analyzer.modules.context_features import FeedContextIndex
from deltascout.delta_analyzer.modules.matcher import FeedMatcher
from deltascout.delta_analyzer.modules.feed_reader import read_feed_rows
from deltascout.delta_analyzer.types import EventsBaseRow, FeedRow, NormalizedEvent


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _feed(
    ts: str,
    *,
    price: float | None,
    buy: float | None,
    sell: float | None,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    vol_1m: float | None = None,
    vwap: float | None = None,
    is_synthetic: bool | None = None,
) -> FeedRow:
    return FeedRow(
        ts=_dt(ts),
        price=price,
        open=open,
        high=high,
        low=low,
        close=close,
        buy_qty=buy,
        sell_qty=sell,
        vol_1m=vol_1m,
        vwap=vwap,
        open_interest=None,
        funding_rate=None,
        liq_buy_qty=None,
        liq_sell_qty=None,
        is_synthetic=is_synthetic,
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
            _feed("2026-01-01T21:00:00", price=100.0, buy=9.0, sell=3.0),
            _feed("2026-01-01T23:30:00", price=101.0, buy=4.0, sell=1.0),
            _feed("2026-01-02T01:15:00", price=102.0, buy=5.0, sell=2.0),
            _feed("2026-01-02T01:45:00", price=103.0, buy=1.0, sell=4.0),
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


def test_read_feed_rows_promotes_m1_fields(tmp_path: Path):
    feed_path = tmp_path / "sample.csv"
    feed_path.write_text(
        "Timestamp,Open,High,Low,Close,Volume,BuyQty,SellQty,VWAP,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty,IsSynthetic\n"
        "2026-01-02 00:00:00,100,110,90,105,20,12,8,102,5000,0.01,1.5,2.5,1\n",
        encoding="utf-8",
    )

    rows = read_feed_rows([feed_path])

    assert len(rows) == 1
    row = rows[0]
    assert row.open == 100.0
    assert row.high == 110.0
    assert row.low == 90.0
    assert row.close == 105.0
    assert row.vol_1m == 20.0
    assert row.vwap == 102.0
    assert row.is_synthetic is True
    assert row.price == 105.0


def test_build_minute_events_base_dataset_preserves_count_and_sorting():
    rows = build_minute_events_base_dataset(
        [
            _feed("2026-01-02T00:02:00", price=103.0, buy=8.0, sell=3.0, close=103.0),
            _feed("2026-01-02T00:01:00", price=101.0, buy=5.0, sell=2.0, close=101.0),
        ]
    )

    assert len(rows) == 2
    assert [row.ts for row in rows] == [_dt("2026-01-02T00:01:00"), _dt("2026-01-02T00:02:00")]


def test_build_minute_events_base_dataset_computes_day_delta_and_imbalance():
    rows = build_minute_events_base_dataset(
        [
            _feed(
                "2026-01-02T00:05:00",
                price=105.0,
                buy=12.0,
                sell=7.0,
                open=100.0,
                high=106.0,
                low=99.0,
                close=105.0,
                vol_1m=25.0,
                vwap=102.5,
                is_synthetic=False,
            )
        ]
    )

    assert len(rows) == 1
    row = rows[0]
    assert row.day == "2026-01-02"
    assert row.delta_1m == 5.0
    assert row.imbalance_1m == 0.2
    assert row.is_synthetic is False


def test_build_minute_events_base_dataset_keeps_optional_fields_null_when_missing():
    rows = build_minute_events_base_dataset(
        [
            _feed(
                "2026-01-02T00:06:00",
                price=None,
                buy=None,
                sell=7.0,
                open=None,
                high=None,
                low=None,
                close=None,
                vol_1m=None,
                vwap=None,
                is_synthetic=None,
            ),
            _feed(
                "2026-01-02T00:07:00",
                price=107.0,
                buy=10.0,
                sell=5.0,
                close=107.0,
                vol_1m=0.0,
            ),
        ]
    )

    first, second = rows
    assert first.delta_1m is None
    assert first.imbalance_1m is None
    assert first.vwap is None
    assert first.is_synthetic is None
    assert second.delta_1m == 5.0
    assert second.imbalance_1m is None
