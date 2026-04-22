from __future__ import annotations

from datetime import timedelta

from ..types import MinuteEventMechanicsRow, MinuteEventOutcomesRow

UP = "up"
DOWN = "down"
UNKNOWN = "unknown"
FLAT_OR_UNKNOWN = "flat_or_unknown"
POSITIVE = "positive"
NEGATIVE = "negative"

HORIZONS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "60m": timedelta(minutes=60),
}
THRESHOLDS = {
    "10bp": 0.001,
    "25bp": 0.0025,
    "50bp": 0.005,
}


def _reference_direction(row: MinuteEventMechanicsRow) -> str:
    if row.price_move_sign == UP:
        return UP
    if row.price_move_sign == DOWN:
        return DOWN
    if row.price_move_sign == FLAT_OR_UNKNOWN and row.delta_sign == POSITIVE:
        return UP
    if row.price_move_sign == FLAT_OR_UNKNOWN and row.delta_sign == NEGATIVE:
        return DOWN
    return UNKNOWN


def _future_rows(
    rows: list[MinuteEventMechanicsRow],
    current_idx: int,
    horizon: timedelta,
) -> list[MinuteEventMechanicsRow]:
    current_ts = rows[current_idx].ts
    boundary = current_ts + horizon
    result: list[MinuteEventMechanicsRow] = []
    idx = current_idx + 1
    while idx < len(rows) and rows[idx].ts <= boundary:
        if rows[idx].ts > current_ts:
            result.append(rows[idx])
        idx += 1
    return result


def _latest_future_close(rows: list[MinuteEventMechanicsRow]) -> float | None:
    latest_close: float | None = None
    for row in rows:
        if row.close is not None:
            latest_close = row.close
    return latest_close


def _upside_max(current_close: float, rows: list[MinuteEventMechanicsRow]) -> float | None:
    values: list[float] = []
    for row in rows:
        future_price = row.high if row.high is not None else row.close
        if future_price is not None:
            values.append(future_price - current_close)
    if not values:
        return None
    return max(values)


def _downside_max(current_close: float, rows: list[MinuteEventMechanicsRow]) -> float | None:
    values: list[float] = []
    for row in rows:
        future_price = row.low if row.low is not None else row.close
        if future_price is not None:
            values.append(current_close - future_price)
    if not values:
        return None
    return max(values)


def _threshold_metrics(
    current_row: MinuteEventMechanicsRow,
    future_rows: list[MinuteEventMechanicsRow],
    threshold: float,
) -> dict[str, bool | float | None]:
    if current_row.close is None:
        return {
            "up_hit": None,
            "down_hit": None,
            "up_time": None,
            "down_time": None,
            "up_before_down": None,
            "down_before_up": None,
            "both_hit": None,
        }
    if not future_rows:
        return {
            "up_hit": None,
            "down_hit": None,
            "up_time": None,
            "down_time": None,
            "up_before_down": None,
            "down_before_up": None,
            "both_hit": None,
        }

    up_level = current_row.close * (1 + threshold)
    down_level = current_row.close * (1 - threshold)
    up_time: float | None = None
    down_time: float | None = None

    for row in future_rows:
        if up_time is None:
            up_price = row.high if row.high is not None else row.close
            if up_price is not None and up_price >= up_level:
                up_time = (row.ts - current_row.ts).total_seconds() / 60.0
        if down_time is None:
            down_price = row.low if row.low is not None else row.close
            if down_price is not None and down_price <= down_level:
                down_time = (row.ts - current_row.ts).total_seconds() / 60.0
        if up_time is not None and down_time is not None:
            break

    up_hit = up_time is not None
    down_hit = down_time is not None
    both_hit = up_hit and down_hit
    up_before_down = both_hit and up_time < down_time
    down_before_up = both_hit and down_time < up_time

    return {
        "up_hit": up_hit,
        "down_hit": down_hit,
        "up_time": up_time,
        "down_time": down_time,
        "up_before_down": up_before_down,
        "down_before_up": down_before_up,
        "both_hit": both_hit,
    }


def _favorable_adverse(
    reference_direction: str,
    upside: float | None,
    downside: float | None,
) -> tuple[float | None, float | None]:
    if reference_direction == UP:
        return upside, downside
    if reference_direction == DOWN:
        return downside, upside
    return None, None


def build_minute_events_outcomes_dataset(rows: list[MinuteEventMechanicsRow]) -> list[MinuteEventOutcomesRow]:
    minute_rows = sorted(rows, key=lambda item: item.ts)
    dataset: list[MinuteEventOutcomesRow] = []

    for idx, row in enumerate(minute_rows):
        reference_direction = _reference_direction(row)
        outcome_values: dict[str, bool | float | None | str] = {}

        for horizon_name, horizon_delta in HORIZONS.items():
            future_rows = _future_rows(minute_rows, idx, horizon_delta)
            if row.close is None or not future_rows:
                ret_value = None
                upside_value = None
                downside_value = None
            else:
                latest_close = _latest_future_close(future_rows)
                ret_value = None if latest_close is None else latest_close - row.close
                upside_value = _upside_max(row.close, future_rows)
                downside_value = _downside_max(row.close, future_rows)

            outcome_values[f"ret_fwd_{horizon_name}"] = ret_value
            outcome_values[f"upside_max_{horizon_name}"] = upside_value
            outcome_values[f"downside_max_{horizon_name}"] = downside_value
            favorable_value, adverse_value = _favorable_adverse(reference_direction, upside_value, downside_value)
            outcome_values[f"favorable_max_{horizon_name}"] = favorable_value
            outcome_values[f"adverse_max_{horizon_name}"] = adverse_value

            for threshold_name, threshold_value in THRESHOLDS.items():
                metrics = _threshold_metrics(row, future_rows, threshold_value)
                outcome_values[f"up_hit_{threshold_name}_{horizon_name}_flag"] = metrics["up_hit"]
                outcome_values[f"down_hit_{threshold_name}_{horizon_name}_flag"] = metrics["down_hit"]
                outcome_values[f"up_time_to_hit_{threshold_name}_{horizon_name}_min"] = metrics["up_time"]
                outcome_values[f"down_time_to_hit_{threshold_name}_{horizon_name}_min"] = metrics["down_time"]
                outcome_values[f"up_before_down_{threshold_name}_{horizon_name}_flag"] = metrics["up_before_down"]
                outcome_values[f"down_before_up_{threshold_name}_{horizon_name}_flag"] = metrics["down_before_up"]
                outcome_values[f"both_hit_{threshold_name}_{horizon_name}_flag"] = metrics["both_hit"]

        dataset.append(
            MinuteEventOutcomesRow(
                ts=row.ts,
                day=row.day,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                delta_1m=row.delta_1m,
                vol_1m=row.vol_1m,
                vwap=row.vwap,
                source_file=row.source_file,
                delta_sign=row.delta_sign,
                price_move_sign=row.price_move_sign,
                price_vs_vwap_side=row.price_vs_vwap_side,
                reference_direction=reference_direction,
                ret_fwd_5m=outcome_values["ret_fwd_5m"],
                ret_fwd_15m=outcome_values["ret_fwd_15m"],
                ret_fwd_30m=outcome_values["ret_fwd_30m"],
                ret_fwd_60m=outcome_values["ret_fwd_60m"],
                upside_max_5m=outcome_values["upside_max_5m"],
                downside_max_5m=outcome_values["downside_max_5m"],
                upside_max_15m=outcome_values["upside_max_15m"],
                downside_max_15m=outcome_values["downside_max_15m"],
                upside_max_30m=outcome_values["upside_max_30m"],
                downside_max_30m=outcome_values["downside_max_30m"],
                upside_max_60m=outcome_values["upside_max_60m"],
                downside_max_60m=outcome_values["downside_max_60m"],
                favorable_max_5m=outcome_values["favorable_max_5m"],
                adverse_max_5m=outcome_values["adverse_max_5m"],
                favorable_max_15m=outcome_values["favorable_max_15m"],
                adverse_max_15m=outcome_values["adverse_max_15m"],
                favorable_max_30m=outcome_values["favorable_max_30m"],
                adverse_max_30m=outcome_values["adverse_max_30m"],
                favorable_max_60m=outcome_values["favorable_max_60m"],
                adverse_max_60m=outcome_values["adverse_max_60m"],
                up_hit_10bp_5m_flag=outcome_values["up_hit_10bp_5m_flag"],
                down_hit_10bp_5m_flag=outcome_values["down_hit_10bp_5m_flag"],
                up_time_to_hit_10bp_5m_min=outcome_values["up_time_to_hit_10bp_5m_min"],
                down_time_to_hit_10bp_5m_min=outcome_values["down_time_to_hit_10bp_5m_min"],
                up_before_down_10bp_5m_flag=outcome_values["up_before_down_10bp_5m_flag"],
                down_before_up_10bp_5m_flag=outcome_values["down_before_up_10bp_5m_flag"],
                both_hit_10bp_5m_flag=outcome_values["both_hit_10bp_5m_flag"],
                up_hit_10bp_15m_flag=outcome_values["up_hit_10bp_15m_flag"],
                down_hit_10bp_15m_flag=outcome_values["down_hit_10bp_15m_flag"],
                up_time_to_hit_10bp_15m_min=outcome_values["up_time_to_hit_10bp_15m_min"],
                down_time_to_hit_10bp_15m_min=outcome_values["down_time_to_hit_10bp_15m_min"],
                up_before_down_10bp_15m_flag=outcome_values["up_before_down_10bp_15m_flag"],
                down_before_up_10bp_15m_flag=outcome_values["down_before_up_10bp_15m_flag"],
                both_hit_10bp_15m_flag=outcome_values["both_hit_10bp_15m_flag"],
                up_hit_10bp_30m_flag=outcome_values["up_hit_10bp_30m_flag"],
                down_hit_10bp_30m_flag=outcome_values["down_hit_10bp_30m_flag"],
                up_time_to_hit_10bp_30m_min=outcome_values["up_time_to_hit_10bp_30m_min"],
                down_time_to_hit_10bp_30m_min=outcome_values["down_time_to_hit_10bp_30m_min"],
                up_before_down_10bp_30m_flag=outcome_values["up_before_down_10bp_30m_flag"],
                down_before_up_10bp_30m_flag=outcome_values["down_before_up_10bp_30m_flag"],
                both_hit_10bp_30m_flag=outcome_values["both_hit_10bp_30m_flag"],
                up_hit_10bp_60m_flag=outcome_values["up_hit_10bp_60m_flag"],
                down_hit_10bp_60m_flag=outcome_values["down_hit_10bp_60m_flag"],
                up_time_to_hit_10bp_60m_min=outcome_values["up_time_to_hit_10bp_60m_min"],
                down_time_to_hit_10bp_60m_min=outcome_values["down_time_to_hit_10bp_60m_min"],
                up_before_down_10bp_60m_flag=outcome_values["up_before_down_10bp_60m_flag"],
                down_before_up_10bp_60m_flag=outcome_values["down_before_up_10bp_60m_flag"],
                both_hit_10bp_60m_flag=outcome_values["both_hit_10bp_60m_flag"],
                up_hit_25bp_5m_flag=outcome_values["up_hit_25bp_5m_flag"],
                down_hit_25bp_5m_flag=outcome_values["down_hit_25bp_5m_flag"],
                up_time_to_hit_25bp_5m_min=outcome_values["up_time_to_hit_25bp_5m_min"],
                down_time_to_hit_25bp_5m_min=outcome_values["down_time_to_hit_25bp_5m_min"],
                up_before_down_25bp_5m_flag=outcome_values["up_before_down_25bp_5m_flag"],
                down_before_up_25bp_5m_flag=outcome_values["down_before_up_25bp_5m_flag"],
                both_hit_25bp_5m_flag=outcome_values["both_hit_25bp_5m_flag"],
                up_hit_25bp_15m_flag=outcome_values["up_hit_25bp_15m_flag"],
                down_hit_25bp_15m_flag=outcome_values["down_hit_25bp_15m_flag"],
                up_time_to_hit_25bp_15m_min=outcome_values["up_time_to_hit_25bp_15m_min"],
                down_time_to_hit_25bp_15m_min=outcome_values["down_time_to_hit_25bp_15m_min"],
                up_before_down_25bp_15m_flag=outcome_values["up_before_down_25bp_15m_flag"],
                down_before_up_25bp_15m_flag=outcome_values["down_before_up_25bp_15m_flag"],
                both_hit_25bp_15m_flag=outcome_values["both_hit_25bp_15m_flag"],
                up_hit_25bp_30m_flag=outcome_values["up_hit_25bp_30m_flag"],
                down_hit_25bp_30m_flag=outcome_values["down_hit_25bp_30m_flag"],
                up_time_to_hit_25bp_30m_min=outcome_values["up_time_to_hit_25bp_30m_min"],
                down_time_to_hit_25bp_30m_min=outcome_values["down_time_to_hit_25bp_30m_min"],
                up_before_down_25bp_30m_flag=outcome_values["up_before_down_25bp_30m_flag"],
                down_before_up_25bp_30m_flag=outcome_values["down_before_up_25bp_30m_flag"],
                both_hit_25bp_30m_flag=outcome_values["both_hit_25bp_30m_flag"],
                up_hit_25bp_60m_flag=outcome_values["up_hit_25bp_60m_flag"],
                down_hit_25bp_60m_flag=outcome_values["down_hit_25bp_60m_flag"],
                up_time_to_hit_25bp_60m_min=outcome_values["up_time_to_hit_25bp_60m_min"],
                down_time_to_hit_25bp_60m_min=outcome_values["down_time_to_hit_25bp_60m_min"],
                up_before_down_25bp_60m_flag=outcome_values["up_before_down_25bp_60m_flag"],
                down_before_up_25bp_60m_flag=outcome_values["down_before_up_25bp_60m_flag"],
                both_hit_25bp_60m_flag=outcome_values["both_hit_25bp_60m_flag"],
                up_hit_50bp_5m_flag=outcome_values["up_hit_50bp_5m_flag"],
                down_hit_50bp_5m_flag=outcome_values["down_hit_50bp_5m_flag"],
                up_time_to_hit_50bp_5m_min=outcome_values["up_time_to_hit_50bp_5m_min"],
                down_time_to_hit_50bp_5m_min=outcome_values["down_time_to_hit_50bp_5m_min"],
                up_before_down_50bp_5m_flag=outcome_values["up_before_down_50bp_5m_flag"],
                down_before_up_50bp_5m_flag=outcome_values["down_before_up_50bp_5m_flag"],
                both_hit_50bp_5m_flag=outcome_values["both_hit_50bp_5m_flag"],
                up_hit_50bp_15m_flag=outcome_values["up_hit_50bp_15m_flag"],
                down_hit_50bp_15m_flag=outcome_values["down_hit_50bp_15m_flag"],
                up_time_to_hit_50bp_15m_min=outcome_values["up_time_to_hit_50bp_15m_min"],
                down_time_to_hit_50bp_15m_min=outcome_values["down_time_to_hit_50bp_15m_min"],
                up_before_down_50bp_15m_flag=outcome_values["up_before_down_50bp_15m_flag"],
                down_before_up_50bp_15m_flag=outcome_values["down_before_up_50bp_15m_flag"],
                both_hit_50bp_15m_flag=outcome_values["both_hit_50bp_15m_flag"],
                up_hit_50bp_30m_flag=outcome_values["up_hit_50bp_30m_flag"],
                down_hit_50bp_30m_flag=outcome_values["down_hit_50bp_30m_flag"],
                up_time_to_hit_50bp_30m_min=outcome_values["up_time_to_hit_50bp_30m_min"],
                down_time_to_hit_50bp_30m_min=outcome_values["down_time_to_hit_50bp_30m_min"],
                up_before_down_50bp_30m_flag=outcome_values["up_before_down_50bp_30m_flag"],
                down_before_up_50bp_30m_flag=outcome_values["down_before_up_50bp_30m_flag"],
                both_hit_50bp_30m_flag=outcome_values["both_hit_50bp_30m_flag"],
                up_hit_50bp_60m_flag=outcome_values["up_hit_50bp_60m_flag"],
                down_hit_50bp_60m_flag=outcome_values["down_hit_50bp_60m_flag"],
                up_time_to_hit_50bp_60m_min=outcome_values["up_time_to_hit_50bp_60m_min"],
                down_time_to_hit_50bp_60m_min=outcome_values["down_time_to_hit_50bp_60m_min"],
                up_before_down_50bp_60m_flag=outcome_values["up_before_down_50bp_60m_flag"],
                down_before_up_50bp_60m_flag=outcome_values["down_before_up_50bp_60m_flag"],
                both_hit_50bp_60m_flag=outcome_values["both_hit_50bp_60m_flag"],
            )
        )

    return dataset
