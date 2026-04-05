from __future__ import annotations

from datetime import timedelta

from ..types import MinuteEventMechanicsRow, MinuteEventRow

MIN_HISTORY_ROWS = 20
FLAT_OR_UNKNOWN = "flat_or_unknown"
POSITIVE = "positive"
NEGATIVE = "negative"
UP = "up"
DOWN = "down"
ALIGNED = "aligned"
OPPOSED = "opposed"
ABOVE = "above"
BELOW = "below"
AT_OR_UNKNOWN = "at_or_unknown"
BUY = "buy"
SELL = "sell"
BALANCED_OR_UNKNOWN = "balanced_or_unknown"
LIQ_BURST_THRESHOLD = 0.95


def _signed_value(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _delta_sign(value: float | None) -> str:
    signed = _signed_value(value)
    if signed == 1:
        return POSITIVE
    if signed == -1:
        return NEGATIVE
    return FLAT_OR_UNKNOWN


def _price_sign(value: float | None) -> str:
    signed = _signed_value(value)
    if signed == 1:
        return UP
    if signed == -1:
        return DOWN
    return FLAT_OR_UNKNOWN


def _alignment(first: float | None, second: float | None) -> str:
    first_sign = _signed_value(first)
    second_sign = _signed_value(second)
    if first_sign in (None, 0) or second_sign in (None, 0):
        return FLAT_OR_UNKNOWN
    if first_sign == second_sign:
        return ALIGNED
    return OPPOSED


def _abs(value: float | None) -> float | None:
    if value is None:
        return None
    return abs(value)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _percentile_rank(
    rows: list[MinuteEventRow],
    current_idx: int,
    lookback: timedelta,
    value_getter,
) -> float | None:
    current_value = value_getter(rows[current_idx])
    if current_value is None:
        return None
    current_ts = rows[current_idx].ts
    boundary = current_ts - lookback
    values: list[float] = []
    idx = current_idx
    while idx >= 0 and rows[idx].ts >= boundary:
        value = value_getter(rows[idx])
        if value is not None:
            values.append(value)
        idx -= 1
    if len(values) < MIN_HISTORY_ROWS:
        return None
    le_count = sum(1 for value in values if value <= current_value)
    return le_count / len(values)


def _percentile_rank_values(
    rows: list[MinuteEventRow],
    values_by_idx: list[float | None],
    current_idx: int,
    lookback: timedelta,
) -> float | None:
    current_value = values_by_idx[current_idx]
    if current_value is None:
        return None
    current_ts = rows[current_idx].ts
    boundary = current_ts - lookback
    values: list[float] = []
    idx = current_idx
    while idx >= 0 and rows[idx].ts >= boundary:
        value = values_by_idx[idx]
        if value is not None:
            values.append(value)
        idx -= 1
    if len(values) < MIN_HISTORY_ROWS:
        return None
    le_count = sum(1 for value in values if value <= current_value)
    return le_count / len(values)


def _oi_change(current: MinuteEventRow, previous: MinuteEventRow | None) -> float | None:
    if previous is None:
        return None
    if current.open_interest is None or previous.open_interest is None:
        return None
    return current.open_interest - previous.open_interest


def _liq_total(row: MinuteEventRow) -> float | None:
    if row.liq_buy_qty is not None and row.liq_sell_qty is not None:
        return row.liq_buy_qty + row.liq_sell_qty
    if row.liq_buy_qty is not None:
        return row.liq_buy_qty
    if row.liq_sell_qty is not None:
        return row.liq_sell_qty
    return None


def _liq_imbalance(row: MinuteEventRow) -> float | None:
    if row.liq_buy_qty is None or row.liq_sell_qty is None:
        return None
    return row.liq_buy_qty - row.liq_sell_qty


def _liq_dominant_side(liq_imbalance_1m: float | None) -> str:
    signed = _signed_value(liq_imbalance_1m)
    if signed == 1:
        return BUY
    if signed == -1:
        return SELL
    return BALANCED_OR_UNKNOWN


def build_minute_events_mechanics_dataset(rows: list[MinuteEventRow]) -> list[MinuteEventMechanicsRow]:
    minute_rows = sorted(rows, key=lambda item: item.ts)
    oi_changes: list[float | None] = []
    abs_oi_changes: list[float | None] = []
    liq_totals: list[float | None] = []
    liq_imbalances: list[float | None] = []

    previous_row: MinuteEventRow | None = None
    for row in minute_rows:
        oi_change_1m = _oi_change(row, previous_row)
        oi_changes.append(oi_change_1m)
        abs_oi_changes.append(_abs(oi_change_1m))
        liq_totals.append(_liq_total(row))
        liq_imbalances.append(_liq_imbalance(row))
        previous_row = row

    dataset: list[MinuteEventMechanicsRow] = []
    for idx, row in enumerate(minute_rows):
        abs_delta_1m = _abs(row.delta_1m)
        delta_to_vol_ratio = _ratio(abs_delta_1m, row.vol_1m)
        close_minus_open = None if row.close is None or row.open is None else row.close - row.open
        high_minus_low = None if row.high is None or row.low is None else row.high - row.low
        body_to_range_ratio = None
        close_location_in_range = None
        if high_minus_low is not None and high_minus_low > 0 and row.close is not None and row.open is not None and row.low is not None:
            body_to_range_ratio = abs(close_minus_open) / high_minus_low if close_minus_open is not None else None
            close_location_in_range = (row.close - row.low) / high_minus_low
        delta_price_efficiency_1m = _ratio(_abs(close_minus_open), _abs(row.delta_1m))
        dist_from_vwap = None if row.close is None or row.vwap is None else row.close - row.vwap
        if dist_from_vwap is None:
            price_vs_vwap_side = AT_OR_UNKNOWN
        elif dist_from_vwap > 0:
            price_vs_vwap_side = ABOVE
        elif dist_from_vwap < 0:
            price_vs_vwap_side = BELOW
        else:
            price_vs_vwap_side = AT_OR_UNKNOWN
        high_above_vwap_flag = None if row.high is None or row.vwap is None else row.high > row.vwap
        low_below_vwap_flag = None if row.low is None or row.vwap is None else row.low < row.vwap
        oi_change_1m = oi_changes[idx]
        abs_oi_change_1m = abs_oi_changes[idx]
        liq_total_1m = liq_totals[idx]
        liq_imbalance_1m = liq_imbalances[idx]
        liq_total_pct_60m = _percentile_rank_values(minute_rows, liq_totals, idx, timedelta(minutes=60))
        dataset.append(
            MinuteEventMechanicsRow(
                ts=row.ts,
                day=row.day,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                buy_qty=row.buy_qty,
                sell_qty=row.sell_qty,
                vol_1m=row.vol_1m,
                delta_1m=row.delta_1m,
                imbalance_1m=row.imbalance_1m,
                vwap=row.vwap,
                open_interest=row.open_interest,
                funding_rate=row.funding_rate,
                liq_buy_qty=row.liq_buy_qty,
                liq_sell_qty=row.liq_sell_qty,
                is_synthetic=row.is_synthetic,
                source_file=row.source_file,
                abs_delta_1m=abs_delta_1m,
                delta_sign=_delta_sign(row.delta_1m),
                delta_to_vol_ratio=delta_to_vol_ratio,
                delta_pct_60m=_percentile_rank(minute_rows, idx, timedelta(minutes=60), lambda item: _abs(item.delta_1m)),
                delta_pct_180m=_percentile_rank(minute_rows, idx, timedelta(minutes=180), lambda item: _abs(item.delta_1m)),
                vol_pct_60m=_percentile_rank(minute_rows, idx, timedelta(minutes=60), lambda item: _abs(item.vol_1m)),
                vol_pct_180m=_percentile_rank(minute_rows, idx, timedelta(minutes=180), lambda item: _abs(item.vol_1m)),
                close_minus_open=close_minus_open,
                high_minus_low=high_minus_low,
                body_to_range_ratio=body_to_range_ratio,
                close_location_in_range=close_location_in_range,
                price_move_sign=_price_sign(close_minus_open),
                delta_price_alignment_1m=_alignment(row.delta_1m, close_minus_open),
                delta_price_efficiency_1m=delta_price_efficiency_1m,
                dist_from_vwap=dist_from_vwap,
                abs_dist_from_vwap=_abs(dist_from_vwap),
                price_vs_vwap_side=price_vs_vwap_side,
                high_above_vwap_flag=high_above_vwap_flag,
                low_below_vwap_flag=low_below_vwap_flag,
                oi_change_1m=oi_change_1m,
                abs_oi_change_1m=abs_oi_change_1m,
                oi_change_pct_60m=_percentile_rank_values(minute_rows, abs_oi_changes, idx, timedelta(minutes=60)),
                oi_change_pct_180m=_percentile_rank_values(minute_rows, abs_oi_changes, idx, timedelta(minutes=180)),
                delta_oi_alignment_flag=_alignment(row.delta_1m, oi_change_1m),
                price_oi_alignment_flag=_alignment(close_minus_open, oi_change_1m),
                liq_total_1m=liq_total_1m,
                liq_imbalance_1m=liq_imbalance_1m,
                liq_dominant_side=_liq_dominant_side(liq_imbalance_1m),
                liq_burst_flag=None if liq_total_pct_60m is None else liq_total_pct_60m >= LIQ_BURST_THRESHOLD,
                delta_vs_liq_relation_flag=_alignment(row.delta_1m, liq_imbalance_1m),
            )
        )
    return dataset
