from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone

from ..types import FeedRow

PRICE_VS_VWAP_AT_OR_UNKNOWN = "at_or_unknown"
PRICE_VS_VWAP_ABOVE = "above"
PRICE_VS_VWAP_BELOW = "below"


class FeedContextIndex:
    """Index globally merged feed rows so Phase 2 windows stay continuous across files."""

    def __init__(self, feed_rows: list[FeedRow]):
        # Feed rows are treated as one merged UTC timeline across all source files.
        self.feed_rows = sorted(feed_rows, key=lambda item: item.ts)
        self.feed_ts = [row.ts for row in self.feed_rows]
        self.prefix_delta, self.prefix_unknown = self._build_prefix_flow_state()

    def match_row(self, event_ts: datetime) -> FeedRow | None:
        idx = self._index_at_or_before(event_ts)
        if idx is None:
            return None
        return self.feed_rows[idx]

    def rolling_cum_delta(self, event_ts: datetime, lookback: timedelta) -> float | None:
        end_idx = self._index_at_or_before(event_ts)
        if end_idx is None:
            return None
        start_boundary = event_ts - lookback
        start_idx = bisect_right(self.feed_ts, start_boundary - timedelta(microseconds=1))
        if self.prefix_unknown[end_idx + 1] - self.prefix_unknown[start_idx] > 0:
            return None
        return self.prefix_delta[end_idx + 1] - self.prefix_delta[start_idx]

    def utc_day_cum_delta(self, event_ts: datetime) -> float | None:
        end_idx = self._index_at_or_before(event_ts)
        if end_idx is None:
            return None
        day_start = self._utc_day_start(event_ts)
        start_idx = bisect_right(self.feed_ts, day_start - timedelta(microseconds=1))
        if self.prefix_unknown[end_idx + 1] - self.prefix_unknown[start_idx] > 0:
            return None
        return self.prefix_delta[end_idx + 1] - self.prefix_delta[start_idx]

    def price_delta(self, event_ts: datetime, lookback: timedelta) -> float | None:
        current_row = self.match_row(event_ts)
        if current_row is None or current_row.price is None:
            return None
        boundary_row = self.match_row(event_ts - lookback)
        if boundary_row is None or boundary_row.price is None:
            return None
        return current_row.price - boundary_row.price

    @staticmethod
    def dist_vwap(price: float | None, vwap: float | None) -> tuple[float | None, float | None, str]:
        if price is None or vwap is None:
            return None, None, PRICE_VS_VWAP_AT_OR_UNKNOWN
        dist = price - vwap
        if dist > 0:
            side = PRICE_VS_VWAP_ABOVE
        elif dist < 0:
            side = PRICE_VS_VWAP_BELOW
        else:
            side = PRICE_VS_VWAP_AT_OR_UNKNOWN
        return dist, abs(dist), side

    def _index_at_or_before(self, ts: datetime) -> int | None:
        idx = bisect_right(self.feed_ts, ts) - 1
        if idx < 0:
            return None
        return idx

    @staticmethod
    def _utc_day_start(ts: datetime) -> datetime:
        if ts.tzinfo is None:
            return ts.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def _build_prefix_flow_state(self) -> tuple[list[float], list[int]]:
        prefix_delta = [0.0]
        prefix_unknown = [0]
        running_delta = 0.0
        running_unknown = 0
        for row in self.feed_rows:
            if row.buy_qty is None or row.sell_qty is None:
                running_unknown += 1
            else:
                running_delta += row.buy_qty - row.sell_qty
            prefix_delta.append(running_delta)
            prefix_unknown.append(running_unknown)
        return prefix_delta, prefix_unknown
