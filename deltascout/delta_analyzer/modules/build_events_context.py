from __future__ import annotations

from datetime import timedelta

from ..types import EventsBaseRow, EventsContextRow, FeedRow
from .context_features import FeedContextIndex


def build_events_context_dataset(
    base_rows: list[EventsBaseRow],
    feed_rows: list[FeedRow],
) -> list[EventsContextRow]:
    """Extend Phase 1 rows with backward-looking flow and price context.

    Rolling windows use all available feed rows inside each lookback window and do
    not pad missing history; partial history is preserved as-is for honest research.
    """

    context_index = FeedContextIndex(feed_rows)
    dataset: list[EventsContextRow] = []

    for row in base_rows:
        dist_vwap, abs_dist_vwap, price_vs_vwap_side = context_index.dist_vwap(row.price, row.vwap)
        dataset.append(
            EventsContextRow(
                ts=row.ts,
                event_type=row.event_type,
                kind=row.kind,
                reject_reason=row.reject_reason,
                delta=row.delta,
                vol=row.vol,
                imb=row.imb,
                price=row.price,
                vwap=row.vwap,
                poc=row.poc,
                matched_feed_ts=row.matched_feed_ts,
                source_file=row.source_file,
                terminal_decision_present=row.terminal_decision_present,
                cum_delta_24h=context_index.rolling_cum_delta(row.ts, timedelta(hours=24)),
                cum_delta_180m=context_index.rolling_cum_delta(row.ts, timedelta(minutes=180)),
                cum_delta_60m=context_index.rolling_cum_delta(row.ts, timedelta(minutes=60)),
                cum_delta_utc_day=context_index.utc_day_cum_delta(row.ts),
                ret_15m=context_index.price_delta(row.ts, timedelta(minutes=15)),
                ret_60m=context_index.price_delta(row.ts, timedelta(minutes=60)),
                dist_vwap=dist_vwap,
                abs_dist_vwap=abs_dist_vwap,
                price_vs_vwap_side=price_vs_vwap_side,
            )
        )
    return dataset
