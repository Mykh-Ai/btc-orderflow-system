from __future__ import annotations

import json

import pandas as pd

from market_monitor.score_instrumentation import SCORE_INSTRUMENTATION_COLUMNS


POST_SWEEP_OBSERVATION_BARS = 30

POST_SWEEP_OBSERVATION_COLUMNS = [
    "observation_id",
    "source_event_id",
    "source_event_timestamp",
    "market_move_id",
    "market_move_role",
    "market_move_event_count",
    "group_start_timestamp",
    "group_end_timestamp",
    "group_span_minutes",
    "grouping_window_mode",
    "zone_id",
    "side",
    "zone_type",
    "zone_price_lower",
    "zone_price_upper",
    "zone_price_mid",
    "confidence_score",
    "confidence_tier",
    "source_timeframes",
    *SCORE_INSTRUMENTATION_COLUMNS,
    "observation_start_timestamp",
    "observation_end_timestamp",
    "observation_bars_expected",
    "observation_bars_available",
    "observation_complete",
    "max_high_after_event",
    "min_low_after_event",
    "close_at_window_end",
    "max_excursion_beyond_zone",
    "max_return_inside_zone",
    "bars_inside_zone",
    "bars_above_zone",
    "bars_below_zone",
    "first_return_inside_at",
    "first_close_inside_at",
    "first_close_beyond_at",
    "net_close_change_abs",
    "net_close_change_pct",
    "post_volume_sum",
    "post_buy_qty_sum",
    "post_sell_qty_sum",
    "post_delta_sum",
    "post_delta_pct",
    "post_trades_sum",
    "post_oi_change",
    "post_max_volume_zscore",
    "post_max_abs_delta_zscore",
    "evidence_json",
    "data_quality",
]


def build_post_sweep_observations(
    *,
    event_log: pd.DataFrame,
    feed: pd.DataFrame,
    volume_delta_state: pd.DataFrame,
) -> pd.DataFrame:
    if event_log.empty or feed.empty:
        return pd.DataFrame(columns=POST_SWEEP_OBSERVATION_COLUMNS)

    unresolved = event_log[
        event_log["event_type"] == "LIQUIDITY_SWEEP_UNRESOLVED"
    ].copy()
    if unresolved.empty:
        return pd.DataFrame(columns=POST_SWEEP_OBSERVATION_COLUMNS)
    for column, default in [
        ("market_move_id", ""),
        ("market_move_role", "NONE"),
        ("market_move_event_count", 0),
        ("group_start_timestamp", ""),
        ("group_end_timestamp", ""),
        ("group_span_minutes", ""),
        ("grouping_window_mode", ""),
    ]:
        if column not in unresolved.columns:
            unresolved[column] = default

    unresolved = unresolved.sort_values(
        ["event_timestamp", "market_move_id", "zone_id", "event_id"], kind="mergesort"
    )
    frame = feed.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    context = _context_frame(volume_delta_state)
    rows = []
    for _, event in unresolved.iterrows():
        rows.append(_observation_row(event, frame, context))

    out = pd.DataFrame(rows, columns=POST_SWEEP_OBSERVATION_COLUMNS)
    out["observation_id"] = [f"observation_{idx + 1:06d}" for idx in range(len(out))]
    return out[POST_SWEEP_OBSERVATION_COLUMNS]


def observation_stats(observations: pd.DataFrame) -> dict[str, int]:
    if observations.empty:
        return {
            "total": 0,
            "complete": 0,
            "incomplete": 0,
            "window_bars": POST_SWEEP_OBSERVATION_BARS,
        }
    complete = observations["observation_complete"].astype(str).str.lower() == "true"
    return {
        "total": len(observations),
        "complete": int(complete.sum()),
        "incomplete": int((~complete).sum()),
        "window_bars": POST_SWEEP_OBSERVATION_BARS,
    }


def _observation_row(
    event: pd.Series,
    feed: pd.DataFrame,
    context: pd.DataFrame,
) -> dict[str, object]:
    evidence = json.loads(str(event["evidence_json"]))
    event_ts = pd.Timestamp(event["event_timestamp"])
    observed = feed[feed["Timestamp"] > event_ts].head(POST_SWEEP_OBSERVATION_BARS)
    event_feed = feed[feed["Timestamp"] == event_ts]

    lower = float(evidence["price_lower"])
    upper = float(evidence["price_upper"])
    mid = float(evidence["price_mid"])
    side = str(event["side"])
    available = len(observed)
    complete = available >= POST_SWEEP_OBSERVATION_BARS
    quality = _quality(event, observed)

    if observed.empty:
        metrics = _empty_metrics(event, event_feed)
        start_ts = ""
        end_ts = ""
    else:
        metrics = _window_metrics(
            observed=observed,
            context=context,
            event=event,
            event_feed=event_feed,
            side=side,
            lower=lower,
            upper=upper,
        )
        start_ts = _format_ts(observed.iloc[0]["Timestamp"])
        end_ts = _format_ts(observed.iloc[-1]["Timestamp"])

    row = {
        "observation_id": "",
        "source_event_id": event["event_id"],
        "source_event_timestamp": event["event_timestamp"],
        "market_move_id": str(event.get("market_move_id", "")),
        "market_move_role": str(event.get("market_move_role", "NONE")),
        "market_move_event_count": int(float(event.get("market_move_event_count", 0) or 0)),
        "group_start_timestamp": str(event.get("group_start_timestamp", "")),
        "group_end_timestamp": str(event.get("group_end_timestamp", "")),
        "group_span_minutes": event.get("group_span_minutes", ""),
        "grouping_window_mode": str(event.get("grouping_window_mode", "")),
        "zone_id": event["zone_id"],
        "side": side,
        "zone_type": evidence["zone_type"],
        "zone_price_lower": lower,
        "zone_price_upper": upper,
        "zone_price_mid": mid,
        "confidence_score": evidence.get("confidence_score", ""),
        "confidence_tier": evidence.get("confidence_tier", ""),
        "source_timeframes": evidence.get("source_timeframes", ""),
        **_score_instrumentation_from_evidence(evidence),
        "observation_start_timestamp": start_ts,
        "observation_end_timestamp": end_ts,
        "observation_bars_expected": POST_SWEEP_OBSERVATION_BARS,
        "observation_bars_available": available,
        "observation_complete": bool(complete),
        "data_quality": quality,
        **metrics,
    }
    row["evidence_json"] = _json(
        {
            "bars_above_zone": int(row["bars_above_zone"]),
            "bars_below_zone": int(row["bars_below_zone"]),
            "bars_inside_zone": int(row["bars_inside_zone"]),
            "data_quality": quality,
            "first_close_beyond_at": row["first_close_beyond_at"],
            "first_close_inside_at": row["first_close_inside_at"],
            "first_return_inside_at": row["first_return_inside_at"],
            "max_excursion_beyond_zone": float(row["max_excursion_beyond_zone"]),
            "max_return_inside_zone": float(row["max_return_inside_zone"]),
            "group_end_timestamp": str(row["group_end_timestamp"]),
            "group_span_minutes": (
                float(row["group_span_minutes"]) if row["group_span_minutes"] != "" else ""
            ),
            "group_start_timestamp": str(row["group_start_timestamp"]),
            "market_move_event_count": int(row["market_move_event_count"]),
            "market_move_id": str(row["market_move_id"]),
            "market_move_role": str(row["market_move_role"]),
            "observation_bars_available": int(available),
            "observation_bars_expected": POST_SWEEP_OBSERVATION_BARS,
            "observation_class": "POST_SWEEP_OBSERVATION",
            "observation_complete": bool(complete),
            "reaction_verdict": "NOT_CLASSIFIED",
            "side": side,
            "source_event_id": str(event["event_id"]),
            "source_event_timestamp": str(event["event_timestamp"]),
            "zone_id": str(event["zone_id"]),
            "zone_price_lower": lower,
            "zone_price_mid": mid,
            "zone_price_upper": upper,
            "zone_type": str(evidence["zone_type"]),
            "confidence_score": evidence.get("confidence_score", ""),
            "confidence_tier": evidence.get("confidence_tier", ""),
            "source_timeframes": evidence.get("source_timeframes", ""),
            **_score_instrumentation_from_evidence(evidence),
        }
    )
    return row


def _window_metrics(
    *,
    observed: pd.DataFrame,
    context: pd.DataFrame,
    event: pd.Series,
    event_feed: pd.DataFrame,
    side: str,
    lower: float,
    upper: float,
) -> dict[str, object]:
    inside = (observed["LowPrice"] <= upper) & (observed["HiPrice"] >= lower)
    close_inside = (observed["ClosePrice"] >= lower) & (observed["ClosePrice"] <= upper)
    close_above = observed["ClosePrice"] > upper
    close_below = observed["ClosePrice"] < lower
    beyond_close = close_above if side == "BUY_SIDE" else close_below

    max_high = float(observed["HiPrice"].max())
    min_low = float(observed["LowPrice"].min())
    close_end = float(observed.iloc[-1]["ClosePrice"])
    event_close = float(event["event_close"])
    total_qty = float(observed["TotalQty"].sum())
    buy_qty = float(observed["BuyQty"].sum())
    sell_qty = float(observed["SellQty"].sum())
    delta = buy_qty - sell_qty

    matched_context = _matched_context(context, observed)
    if matched_context.empty:
        max_volume_zscore = 0.0
        max_abs_delta_zscore = 0.0
    else:
        max_volume_zscore = float(matched_context["volume_zscore"].max())
        max_abs_delta_zscore = float(matched_context["delta_zscore"].abs().max())

    return {
        "max_high_after_event": max_high,
        "min_low_after_event": min_low,
        "close_at_window_end": close_end,
        "max_excursion_beyond_zone": _max_excursion(observed, side, lower, upper),
        "max_return_inside_zone": _max_return_inside(observed, side, lower, upper),
        "bars_inside_zone": int(inside.sum()),
        "bars_above_zone": int(close_above.sum()),
        "bars_below_zone": int(close_below.sum()),
        "first_return_inside_at": _first_ts(observed, inside),
        "first_close_inside_at": _first_ts(observed, close_inside),
        "first_close_beyond_at": _first_ts(observed, beyond_close),
        "net_close_change_abs": abs(close_end - event_close),
        "net_close_change_pct": abs(close_end - event_close) / event_close * 100 if event_close else 0.0,
        "post_volume_sum": total_qty,
        "post_buy_qty_sum": buy_qty,
        "post_sell_qty_sum": sell_qty,
        "post_delta_sum": delta,
        "post_delta_pct": delta / total_qty if total_qty else 0.0,
        "post_trades_sum": float(observed["Trades"].sum()),
        "post_oi_change": _post_oi_change(observed, event_feed),
        "post_max_volume_zscore": max_volume_zscore,
        "post_max_abs_delta_zscore": max_abs_delta_zscore,
    }


def _empty_metrics(event: pd.Series, event_feed: pd.DataFrame) -> dict[str, object]:
    return {
        "max_high_after_event": 0.0,
        "min_low_after_event": 0.0,
        "close_at_window_end": 0.0,
        "max_excursion_beyond_zone": 0.0,
        "max_return_inside_zone": 0.0,
        "bars_inside_zone": 0,
        "bars_above_zone": 0,
        "bars_below_zone": 0,
        "first_return_inside_at": "",
        "first_close_inside_at": "",
        "first_close_beyond_at": "",
        "net_close_change_abs": 0.0,
        "net_close_change_pct": 0.0,
        "post_volume_sum": 0.0,
        "post_buy_qty_sum": 0.0,
        "post_sell_qty_sum": 0.0,
        "post_delta_sum": 0.0,
        "post_delta_pct": 0.0,
        "post_trades_sum": 0.0,
        "post_oi_change": _post_oi_change(pd.DataFrame(), event_feed),
        "post_max_volume_zscore": 0.0,
        "post_max_abs_delta_zscore": 0.0,
    }


def _max_excursion(
    observed: pd.DataFrame, side: str, lower: float, upper: float
) -> float:
    if side == "BUY_SIDE":
        return max(0.0, float((observed["HiPrice"] - upper).max()))
    return max(0.0, float((lower - observed["LowPrice"]).max()))


def _max_return_inside(
    observed: pd.DataFrame, side: str, lower: float, upper: float
) -> float:
    if side == "BUY_SIDE":
        return max(0.0, float((upper - observed["LowPrice"]).max()))
    return max(0.0, float((observed["HiPrice"] - lower).max()))


def _post_oi_change(observed: pd.DataFrame, event_feed: pd.DataFrame) -> float:
    if observed.empty or event_feed.empty:
        return 0.0
    return float(observed.iloc[-1]["OpenInterest"]) - float(event_feed.iloc[0]["OpenInterest"])


def _matched_context(context: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    if context.empty or observed.empty:
        return pd.DataFrame()
    timestamps = set(observed["Timestamp"].map(_format_ts))
    return context[context["timestamp"].isin(timestamps)]


def _context_frame(volume_delta_state: pd.DataFrame) -> pd.DataFrame:
    if volume_delta_state.empty:
        return pd.DataFrame(columns=["timestamp", "volume_zscore", "delta_zscore"])
    return volume_delta_state.copy()


def _first_ts(frame: pd.DataFrame, mask: pd.Series) -> str:
    if not bool(mask.any()):
        return ""
    return _format_ts(frame.loc[mask].iloc[0]["Timestamp"])


def _quality(event: pd.Series, observed: pd.DataFrame) -> str:
    values = {str(event.get("data_quality", ""))}
    if not observed.empty:
        values.update(str(value) for value in observed["DataQuality"])
    if values == {"RAW"}:
        return "RAW"
    if "RECOVERED_DEGRADED" in values:
        return "RECOVERED_DEGRADED"
    return sorted(value for value in values if value)[0] if any(values) else "RAW"


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _score_instrumentation_from_evidence(evidence: dict[str, object]) -> dict[str, object]:
    return {column: evidence.get(column, "") for column in SCORE_INSTRUMENTATION_COLUMNS}
