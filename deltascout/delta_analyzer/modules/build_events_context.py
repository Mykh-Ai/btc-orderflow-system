from __future__ import annotations

from datetime import timedelta

from ..types import EventsBaseRow, EventsContextRow, FeedRow
from .context_features import FeedContextIndex


def build_events_context_dataset(
    base_rows: list[EventsBaseRow],
    feed_rows: list[FeedRow],
) -> list[EventsContextRow]:
    """Extend Phase 1 rows with backward-looking flow and price context.

    Rolling windows use the globally merged, timestamp-sorted feed history across
    all discovered feed files. They do not reset at file/day boundaries, do not pad
    missing history, and return None when the requested window includes unknown flow.
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
                matched_open_interest=row.matched_open_interest,
                matched_funding_rate=row.matched_funding_rate,
                matched_liq_buy_qty=row.matched_liq_buy_qty,
                matched_liq_sell_qty=row.matched_liq_sell_qty,
                source_file=row.source_file,
                terminal_decision_present=row.terminal_decision_present,
                prev_price=row.prev_price,
                prev_vol=row.prev_vol,
                prev_vwap=row.prev_vwap,
                comparison_price_pass=row.comparison_price_pass,
                comparison_vol_pass=row.comparison_vol_pass,
                comparison_vwap_pass=row.comparison_vwap_pass,
                comparison_3of3_pass_count=row.comparison_3of3_pass_count,
                comparison_3of3_failed_subconditions=row.comparison_3of3_failed_subconditions,
                cum_delta_24h=context_index.rolling_cum_delta(row.ts, timedelta(hours=24)),
                cum_delta_180m=context_index.rolling_cum_delta(row.ts, timedelta(minutes=180)),
                cum_delta_60m=context_index.rolling_cum_delta(row.ts, timedelta(minutes=60)),
                ret_15m=context_index.price_delta(row.ts, timedelta(minutes=15)),
                ret_60m=context_index.price_delta(row.ts, timedelta(minutes=60)),
                dist_vwap=dist_vwap,
                abs_dist_vwap=abs_dist_vwap,
                price_vs_vwap_side=price_vs_vwap_side,
            )
        )
    return dataset
