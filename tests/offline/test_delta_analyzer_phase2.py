from __future__ import annotations

from datetime import datetime, timedelta, timezone

from deltascout.delta_analyzer.modules.context_features import FeedContextIndex
from deltascout.delta_analyzer.types import FeedRow


def _feed_row(ts: datetime, *, buy_qty: float | None, sell_qty: float | None, price: float = 0.0, source_file: str) -> FeedRow:
    return FeedRow(
        ts=ts,
        price=price,
        buy_qty=buy_qty,
        sell_qty=sell_qty,
        row={},
        source_file=source_file,
    )


def test_rolling_windows_use_continuous_history_across_feed_files():
    index = FeedContextIndex(
        [
            _feed_row(datetime(2026, 1, 1, 23, 30, tzinfo=timezone.utc), buy_qty=5.0, sell_qty=1.0, source_file='day1.csv'),
            _feed_row(datetime(2026, 1, 2, 0, 10, tzinfo=timezone.utc), buy_qty=2.0, sell_qty=1.0, source_file='day2.csv'),
        ]
    )

    assert index.feed_rows[0].source_file == 'day1.csv'
    assert index.feed_rows[1].source_file == 'day2.csv'
    assert index.rolling_cum_delta(datetime(2026, 1, 2, 0, 15, tzinfo=timezone.utc), timedelta(minutes=60)) == 5.0



def test_missing_flow_inside_window_returns_none_instead_of_zero_fill():
    index = FeedContextIndex(
        [
            _feed_row(datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc), buy_qty=3.0, sell_qty=1.0, source_file='day2.csv'),
            _feed_row(datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc), buy_qty=None, sell_qty=2.0, source_file='day2.csv'),
            _feed_row(datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc), buy_qty=4.0, sell_qty=1.0, source_file='day2.csv'),
        ]
    )

    event_ts = datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)

    assert index.rolling_cum_delta(event_ts, timedelta(hours=24)) is None
    assert index.rolling_cum_delta(event_ts, timedelta(minutes=180)) is None
    assert index.rolling_cum_delta(event_ts, timedelta(minutes=60)) is None
    assert index.rolling_cum_delta(event_ts, timedelta(minutes=20)) == 3.0
