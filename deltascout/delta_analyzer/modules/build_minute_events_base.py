from __future__ import annotations

from ..types import FeedRow, MinuteEventRow


def _minute_delta(feed_row: FeedRow) -> float | None:
    if feed_row.buy_qty is None or feed_row.sell_qty is None:
        return None
    return feed_row.buy_qty - feed_row.sell_qty


def _minute_imbalance(delta_1m: float | None, vol_1m: float | None) -> float | None:
    if delta_1m is None or vol_1m is None or vol_1m == 0:
        return None
    return delta_1m / vol_1m


def build_minute_events_base_dataset(feed_rows: list[FeedRow]) -> list[MinuteEventRow]:
    dataset: list[MinuteEventRow] = []
    for row in sorted(feed_rows, key=lambda item: item.ts):
        delta_1m = _minute_delta(row)
        dataset.append(
            MinuteEventRow(
                ts=row.ts,
                day=row.ts.strftime("%Y-%m-%d"),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                buy_qty=row.buy_qty,
                sell_qty=row.sell_qty,
                vol_1m=row.vol_1m,
                delta_1m=delta_1m,
                imbalance_1m=_minute_imbalance(delta_1m, row.vol_1m),
                vwap=row.vwap,
                open_interest=row.open_interest,
                funding_rate=row.funding_rate,
                liq_buy_qty=row.liq_buy_qty,
                liq_sell_qty=row.liq_sell_qty,
                is_synthetic=row.is_synthetic,
                source_file=row.source_file,
            )
        )
    return dataset
