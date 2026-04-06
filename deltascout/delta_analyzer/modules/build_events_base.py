from __future__ import annotations

from collections import defaultdict

from ..config import RAW_DELTA_EVENTS
from ..types import EventsBaseRow, FeedRow, NormalizedEvent
from .matcher import FeedMatcher


def _comparison_diagnostics(event: NormalizedEvent) -> dict[str, object]:
    raw = event.raw if isinstance(event.raw, dict) else {}
    prev_price = raw.get("prev_price")
    prev_vol = raw.get("prev_vol")
    prev_vwap = raw.get("prev_vwap")
    if event.reject_reason != "3of3_fail":
        return {
            "prev_price": prev_price,
            "prev_vol": prev_vol,
            "prev_vwap": prev_vwap,
            "comparison_price_pass": None,
            "comparison_vol_pass": None,
            "comparison_vwap_pass": None,
            "comparison_3of3_pass_count": None,
            "comparison_3of3_failed_subconditions": "",
        }

    checks: list[tuple[str, bool | None]] = []
    if event.price is not None and prev_price is not None:
        checks.append(("price", event.price > prev_price if event.kind == "long" else event.price < prev_price))
    else:
        checks.append(("price", None))
    if event.vol is not None and prev_vol is not None:
        checks.append(("vol", event.vol > prev_vol))
    else:
        checks.append(("vol", None))
    if event.vwap is not None and prev_vwap is not None:
        checks.append(("vwap", event.vwap > prev_vwap if event.kind == "long" else event.vwap < prev_vwap))
    else:
        checks.append(("vwap", None))

    pass_count = sum(1 for _, passed in checks if passed is True)
    failed = [name for name, passed in checks if passed is False]
    values = {name: passed for name, passed in checks}
    return {
        "prev_price": prev_price,
        "prev_vol": prev_vol,
        "prev_vwap": prev_vwap,
        "comparison_price_pass": values["price"],
        "comparison_vol_pass": values["vol"],
        "comparison_vwap_pass": values["vwap"],
        "comparison_3of3_pass_count": pass_count,
        "comparison_3of3_failed_subconditions": "|".join(failed),
    }



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

        comparison = _comparison_diagnostics(event)
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
                matched_open_interest=matched_feed.open_interest if matched_feed else None,
                matched_funding_rate=matched_feed.funding_rate if matched_feed else None,
                matched_liq_buy_qty=matched_feed.liq_buy_qty if matched_feed else None,
                matched_liq_sell_qty=matched_feed.liq_sell_qty if matched_feed else None,
                source_file=event.source_file,
                terminal_decision_present=terminal_present,
                prev_price=comparison["prev_price"],
                prev_vol=comparison["prev_vol"],
                prev_vwap=comparison["prev_vwap"],
                comparison_price_pass=comparison["comparison_price_pass"],
                comparison_vol_pass=comparison["comparison_vol_pass"],
                comparison_vwap_pass=comparison["comparison_vwap_pass"],
                comparison_3of3_pass_count=comparison["comparison_3of3_pass_count"],
                comparison_3of3_failed_subconditions=comparison["comparison_3of3_failed_subconditions"],
            )
        )
    return dataset
