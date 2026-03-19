from __future__ import annotations

from bisect import bisect_right

from ..types import FeedRow, NormalizedEvent


class FeedMatcher:
    def __init__(self, feed_rows: list[FeedRow]):
        self.feed_rows = sorted(feed_rows, key=lambda item: item.ts)
        self.feed_ts = [row.ts for row in self.feed_rows]

    def match(self, event: NormalizedEvent) -> FeedRow | None:
        idx = bisect_right(self.feed_ts, event.ts) - 1
        if idx < 0:
            return None
        return self.feed_rows[idx]
