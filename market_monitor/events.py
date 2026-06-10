from __future__ import annotations

import json

import pandas as pd

from market_monitor.score_instrumentation import PRECISION_TOO_WIDE, SCORE_INSTRUMENTATION_COLUMNS
from market_monitor.zone_registry import (
    LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES,
    local_session_context_role,
)


APPROACH_THRESHOLD_FRACTION = 0.001
APPROACH_THRESHOLD_MIN_USD = 20.0
SWEEP_MIN_EXCURSION_FRACTION = 0.0002
SWEEP_MIN_EXCURSION_USD = 10.0
SWEEP_ACTIVITY_ZSCORE_THRESHOLD = 1.5
MARKET_MOVE_GROUP_WINDOW_MINUTES = 2
GROUPING_WINDOW_MODE = "ANCHORED_FIXED_WINDOW"

EVENT_LOG_COLUMNS = [
    "event_id",
    "event_timestamp",
    "event_type",
    "zone_id",
    "side",
    "price_before",
    "event_high",
    "event_low",
    "event_close",
    "excursion_abs",
    "excursion_atr",
    "volume_zscore",
    "delta_zscore",
    "oi_change",
    "reaction_status",
    "market_move_id",
    "market_move_role",
    "market_move_event_count",
    "group_start_timestamp",
    "group_end_timestamp",
    "group_span_minutes",
    "grouping_window_mode",
    "evidence_json",
    "data_quality",
]

MARKET_MOVE_GROUP_COLUMNS = [
    "market_move_id",
    "group_start_timestamp",
    "group_end_timestamp",
    "group_span_minutes",
    "grouping_window_minutes",
    "grouping_window_mode",
    "event_timestamp",
    "side",
    "primary_event_id",
    "primary_zone_id",
    "primary_selection_reason",
    "primary_selection_components_json",
    "event_count",
    "zone_ids",
    "event_ids",
    "min_zone_price_lower",
    "max_zone_price_upper",
    "representative_zone_price_mid",
    "max_excursion_abs",
    "max_volume_zscore",
    "max_abs_delta_zscore",
    "total_oi_change",
    "precision_statuses",
    "confidence_tiers",
    "data_quality",
    "evidence_json",
]

LIFECYCLE_EVENT_TYPES = {
    "LIQUIDITY_ZONE_APPROACHED",
    "LIQUIDITY_ZONE_TOUCHED",
    "LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED",
    "LIQUIDITY_ZONE_MERGED",
    "LIQUIDITY_ZONE_EXPIRED",
}
INTERPRETIVE_EVENT_TYPES = {
    "LIQUIDITY_SWEEP_UNRESOLVED",
}
ALLOWED_EVENT_TYPES = LIFECYCLE_EVENT_TYPES | INTERPRETIVE_EVENT_TYPES
EVENT_TYPE_ORDER = {
    "LIQUIDITY_ZONE_APPROACHED": 10,
    "LIQUIDITY_ZONE_TOUCHED": 20,
    "LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED": 30,
    "LIQUIDITY_SWEEP_UNRESOLVED": 31,
    "LIQUIDITY_ZONE_MERGED": 40,
    "LIQUIDITY_ZONE_EXPIRED": 50,
}


def build_event_log(
    *,
    registry: pd.DataFrame,
    feed: pd.DataFrame,
    volume_delta_state: pd.DataFrame,
    previous_registry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if registry.empty or feed.empty:
        return pd.DataFrame(columns=EVENT_LOG_COLUMNS)

    frame = feed.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    run_start = frame["Timestamp"].min()
    run_end = frame["Timestamp"].max()
    previous_status = _previous_status_map(previous_registry)
    context = _context_map(volume_delta_state)
    events: list[dict[str, object]] = []

    for _, row in registry.iterrows():
        zone = row.to_dict()
        events.extend(_interaction_events(zone, frame, previous_status, context))
        lifecycle_event = _registry_lifecycle_event(
            zone, run_start, run_end, previous_status, context
        )
        if lifecycle_event is not None:
            events.append(lifecycle_event)

    if not events:
        return pd.DataFrame(columns=EVENT_LOG_COLUMNS)
    out = pd.DataFrame(events, columns=EVENT_LOG_COLUMNS)
    out = out[out["event_type"].isin(ALLOWED_EVENT_TYPES)].copy()
    out["_event_type_order"] = out["event_type"].map(EVENT_TYPE_ORDER).fillna(999)
    out = out.sort_values(
        ["event_timestamp", "zone_id", "_event_type_order", "event_type"],
        kind="mergesort",
    ).reset_index(drop=True)
    out["event_id"] = [f"event_{idx + 1:06d}" for idx in range(len(out))]
    out = assign_market_move_groups(out)
    return out[EVENT_LOG_COLUMNS]


def assign_market_move_groups(event_log: pd.DataFrame) -> pd.DataFrame:
    out = event_log.copy()
    if out.empty:
        return pd.DataFrame(columns=EVENT_LOG_COLUMNS)
    out["market_move_id"] = ""
    out["market_move_role"] = "NONE"
    out["market_move_event_count"] = 0
    out["group_start_timestamp"] = ""
    out["group_end_timestamp"] = ""
    out["group_span_minutes"] = ""
    out["grouping_window_mode"] = ""
    unresolved = out[out["event_type"] == "LIQUIDITY_SWEEP_UNRESOLVED"].copy()
    if unresolved.empty:
        return out[EVENT_LOG_COLUMNS]

    groups: list[list[int]] = []
    for _, side_frame in unresolved.sort_values(
        ["side", "event_timestamp", "zone_id", "event_id"], kind="mergesort"
    ).groupby("side", sort=True):
        current: list[int] = []
        group_start_ts: pd.Timestamp | None = None
        for idx, row in side_frame.iterrows():
            event_ts = pd.Timestamp(row["event_timestamp"])
            if (
                current
                and group_start_ts is not None
                and event_ts - group_start_ts > pd.Timedelta(minutes=MARKET_MOVE_GROUP_WINDOW_MINUTES)
            ):
                groups.append(current)
                current = []
                group_start_ts = None
            if not current:
                group_start_ts = event_ts
            current.append(idx)
        if current:
            groups.append(current)

    groups.sort(
        key=lambda idxs: (
            pd.Timestamp(out.loc[idxs[0], "event_timestamp"]),
            str(out.loc[idxs[0], "side"]),
            str(out.loc[idxs[0], "event_id"]),
        )
    )
    for group_number, idxs in enumerate(groups, start=1):
        group = out.loc[idxs].copy()
        first_ts = pd.Timestamp(group["event_timestamp"].map(pd.Timestamp).min())
        last_ts = pd.Timestamp(group["event_timestamp"].map(pd.Timestamp).max())
        span_minutes = _span_minutes(first_ts, last_ts)
        side = str(group.iloc[0]["side"])
        move_id = _market_move_id(first_ts, side, group_number)
        primary_idx = _primary_event_index(group)
        out.loc[idxs, "market_move_id"] = move_id
        out.loc[idxs, "market_move_event_count"] = len(idxs)
        out.loc[idxs, "market_move_role"] = "SECONDARY"
        out.loc[idxs, "group_start_timestamp"] = _format_ts(first_ts)
        out.loc[idxs, "group_end_timestamp"] = _format_ts(last_ts)
        out.loc[idxs, "group_span_minutes"] = span_minutes
        out.loc[idxs, "grouping_window_mode"] = GROUPING_WINDOW_MODE
        out.loc[primary_idx, "market_move_role"] = "PRIMARY"
    return out[EVENT_LOG_COLUMNS]


def build_market_move_groups(event_log: pd.DataFrame) -> pd.DataFrame:
    if event_log.empty or "market_move_id" not in event_log.columns:
        return pd.DataFrame(columns=MARKET_MOVE_GROUP_COLUMNS)
    grouped = event_log[
        (event_log["event_type"] == "LIQUIDITY_SWEEP_UNRESOLVED")
        & (event_log["market_move_id"].fillna("").astype(str) != "")
    ].copy()
    if grouped.empty:
        return pd.DataFrame(columns=MARKET_MOVE_GROUP_COLUMNS)

    rows = []
    for _, group in grouped.groupby("market_move_id", sort=True):
        rows.append(_market_move_group_row(group))
    rows = sorted(
        rows,
        key=lambda row: (pd.Timestamp(row["event_timestamp"]), str(row["side"]), str(row["market_move_id"])),
    )
    return pd.DataFrame(rows, columns=MARKET_MOVE_GROUP_COLUMNS)


def event_stats(event_log: pd.DataFrame) -> dict[str, object]:
    if event_log.empty:
        return {
            "total": 0,
            "by_type": "none",
            "approached": 0,
            "touched": 0,
            "crossed_unclassified": 0,
            "merged": 0,
            "expired": 0,
            "unresolved_sweep": 0,
            "unresolved_sweep_by_side": "BUY_SIDE=0, SELL_SIDE=0",
            "unresolved_sweep_by_data_quality": "RAW=0, RECOVERED_DEGRADED=0",
            "crossed_without_sweep_evidence": 0,
            "grouped_market_move_count": 0,
            "multi_event_market_move_count": 0,
            "avg_unresolved_events_per_market_move": "0",
            "max_unresolved_events_per_market_move": 0,
            "max_group_span_minutes": "0",
            "groups_over_configured_window": 0,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
        }
    counts = event_log["event_type"].value_counts().sort_index()
    unresolved = event_log[event_log["event_type"] == "LIQUIDITY_SWEEP_UNRESOLVED"]
    lifecycle = event_log[event_log["event_type"].isin(LIFECYCLE_EVENT_TYPES)]
    move_stats = _market_move_stats(unresolved)
    return {
        "total": len(lifecycle),
        "by_type": ", ".join(f"{name}={count}" for name, count in counts.items()),
        "approached": int((event_log["event_type"] == "LIQUIDITY_ZONE_APPROACHED").sum()),
        "touched": int((event_log["event_type"] == "LIQUIDITY_ZONE_TOUCHED").sum()),
        "crossed_unclassified": int(
            (event_log["event_type"] == "LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED").sum()
        ),
        "merged": int((event_log["event_type"] == "LIQUIDITY_ZONE_MERGED").sum()),
        "expired": int((event_log["event_type"] == "LIQUIDITY_ZONE_EXPIRED").sum()),
        "unresolved_sweep": len(unresolved),
        "unresolved_sweep_by_side": _fixed_counts(unresolved, "side", ["BUY_SIDE", "SELL_SIDE"]),
        "unresolved_sweep_by_data_quality": _fixed_counts(
            unresolved, "data_quality", ["RAW", "RECOVERED_DEGRADED"]
        ),
        "crossed_without_sweep_evidence": _crossed_without_sweep_evidence(event_log),
        **move_stats,
    }


def _interaction_events(
    zone: dict[str, object],
    feed: pd.DataFrame,
    previous_status: dict[str, str],
    context: dict[str, dict[str, float]],
) -> list[dict[str, object]]:
    if str(zone.get("status", "")) in {"MERGED", "EXPIRED"}:
        return []
    first_seen = pd.Timestamp(zone["first_seen_at"])
    run_slice = feed[feed["Timestamp"] >= first_seen].copy()
    if run_slice.empty:
        return []
    if _consumed_before_or_at(zone, run_slice["Timestamp"].min()):
        return []

    cross_row = _first_cross(zone, run_slice)
    touch_row = _first_touch(zone, run_slice)
    if cross_row is not None:
        cross_event = _market_event(
            zone=zone,
            event_type="LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED",
            candle=cross_row,
            feed=feed,
            previous_status=previous_status,
            context=context,
            trigger="price_crossed_zone_far_side",
            excursion_abs=_cross_excursion(zone, cross_row),
            new_status="CROSSED_UNCLASSIFIED",
        )
        events = [cross_event]
        unresolved_event = _unresolved_sweep_event(
            zone=zone,
            candle=cross_row,
            feed=feed,
            previous_status=previous_status,
            context=context,
        )
        if unresolved_event is not None:
            events.append(unresolved_event)
        return events

    if touch_row is not None:
        return [
            _market_event(
                zone=zone,
                event_type="LIQUIDITY_ZONE_TOUCHED",
                candle=touch_row,
                feed=feed,
                previous_status=previous_status,
                context=context,
                trigger="price_entered_zone_range",
                excursion_abs=0,
                new_status="TOUCHED",
            )
        ]

    approach_row = _first_approach(zone, run_slice)
    if approach_row is not None:
        return [
            _market_event(
                zone=zone,
                event_type="LIQUIDITY_ZONE_APPROACHED",
                candle=approach_row,
                feed=feed,
                previous_status=previous_status,
                context=context,
                trigger="price_reached_approach_threshold_without_touch",
                excursion_abs=0,
                new_status="APPROACHED",
            )
        ]
    return []


def _unresolved_sweep_event(
    *,
    zone: dict[str, object],
    candle: pd.Series,
    feed: pd.DataFrame,
    previous_status: dict[str, str],
    context: dict[str, dict[str, float]],
) -> dict[str, object] | None:
    event_timestamp = pd.Timestamp(candle["Timestamp"])
    first_seen_at = pd.Timestamp(zone["first_seen_at"])
    if first_seen_at >= event_timestamp:
        return None
    if _consumed_before_or_at(zone, event_timestamp):
        return None
    if str(zone.get("precision_status", "")) == PRECISION_TOO_WIDE:
        return None
    if _non_fresh_role_before_or_at(zone, event_timestamp):
        return None

    if _is_repeated_prior_cross_without_new_transition(
        zone=zone,
        candle=candle,
        feed=feed,
        previous_status=previous_status,
    ):
        return None

    excursion_abs = _cross_excursion(zone, candle)
    min_excursion_abs = _min_sweep_excursion(zone)
    if excursion_abs <= 0 or excursion_abs < min_excursion_abs:
        return None

    event_ts = _format_ts(event_timestamp)
    ctx = context.get(
        event_ts,
        {"volume_zscore": 0.0, "delta_zscore": 0.0, "oi_change": 0.0},
    )
    data_quality = _event_data_quality(zone, candle)
    activity_evidence = _activity_evidence(ctx, data_quality)
    if not activity_evidence:
        return None

    evidence = {
        "activity_evidence": activity_evidence,
        "activity_passed": True,
        "candidate_evidence_status": "SUFFICIENT_UNRESOLVED",
        "confidence_score": int(float(zone.get("confidence_score", 0) or 0)),
        "confidence_tier": str(zone.get("confidence_tier", "")),
        "data_quality": data_quality,
        "delta_zscore": float(ctx["delta_zscore"]),
        "event_class": "LIQUIDITY_SWEEP_UNRESOLVED",
        "event_close": float(candle["ClosePrice"]),
        "event_high": float(candle["HiPrice"]),
        "event_low": float(candle["LowPrice"]),
        "event_timestamp": event_ts,
        "excursion_abs": float(excursion_abs),
        "excursion_passed": True,
        "first_seen_at": _format_ts(first_seen_at),
        "min_excursion_abs": float(min_excursion_abs),
        "oi_change": float(ctx["oi_change"]),
        "pre_existing_zone": True,
        "price_lower": float(zone["price_lower"]),
        "price_mid": float(zone["price_mid"]),
        "price_upper": float(zone["price_upper"]),
        "reaction_status": "UNRESOLVED",
        "side": str(zone["side"]),
        "active_forward": str(zone.get("active_forward", "")),
        "active_forward_role": str(zone.get("active_forward_role", "")),
        "accepted_above_at": str(zone.get("accepted_above_at", "")),
        "accepted_below_at": str(zone.get("accepted_below_at", "")),
        "consumption_status": str(zone.get("consumption_status", "")),
        "consumed_at": str(zone.get("consumed_at", "")),
        "failed_acceptance_count": int(float(zone.get("failed_acceptance_count", 0) or 0)),
        "first_sweep_at": str(zone.get("first_sweep_at", "")),
        "resweep_count": int(float(zone.get("resweep_count", 0) or 0)),
        "source_timeframes": str(zone.get("source_timeframes", "")),
        "structural_zone_mode": str(zone.get("structural_zone_mode", "")),
        "volume_zscore": float(ctx["volume_zscore"]),
        "zone_behavior_state": str(zone.get("zone_behavior_state", "")),
        "zone_id": str(zone["zone_id"]),
        "zone_outer_lower": float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"]),
        "zone_outer_upper": float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"]),
        "zone_core_lower": float(zone.get("zone_core_lower", zone["price_lower"]) or zone["price_lower"]),
        "zone_core_upper": float(zone.get("zone_core_upper", zone["price_upper"]) or zone["price_upper"]),
        "zone_type": str(zone["zone_type"]),
        **_score_instrumentation_evidence(zone),
    }
    return {
        "event_id": "",
        "event_timestamp": event_ts,
        "event_type": "LIQUIDITY_SWEEP_UNRESOLVED",
        "zone_id": zone["zone_id"],
        "side": zone["side"],
        "price_before": _price_before(feed, event_timestamp),
        "event_high": float(candle["HiPrice"]),
        "event_low": float(candle["LowPrice"]),
        "event_close": float(candle["ClosePrice"]),
        "excursion_abs": float(excursion_abs),
        "excursion_atr": 0,
        "volume_zscore": ctx["volume_zscore"],
        "delta_zscore": ctx["delta_zscore"],
        "oi_change": ctx["oi_change"],
        "reaction_status": "UNRESOLVED",
        "evidence_json": _json(evidence),
        "data_quality": data_quality,
    }


def _registry_lifecycle_event(
    zone: dict[str, object],
    run_start: pd.Timestamp,
    run_end: pd.Timestamp,
    previous_status: dict[str, str],
    context: dict[str, dict[str, float]],
) -> dict[str, object] | None:
    status = str(zone.get("status", ""))
    if status not in {"MERGED", "EXPIRED"}:
        return None
    prior_status = previous_status.get(str(zone["zone_id"]), "")
    if prior_status == status:
        return None
    event_ts = pd.Timestamp(zone.get("last_updated_at") or zone.get("last_seen_at"))
    if event_ts < run_start or event_ts > run_end + pd.Timedelta(days=1):
        return None
    event_type = (
        "LIQUIDITY_ZONE_MERGED"
        if status == "MERGED"
        else "LIQUIDITY_ZONE_EXPIRED"
    )
    evidence = _base_evidence(
        zone=zone,
        previous_status=prior_status,
        new_status=status,
        trigger="registry_lifecycle_update",
        candle_timestamp=_format_ts(event_ts),
        candle_high=0,
        candle_low=0,
        candle_close=0,
        context={"volume_zscore": 0.0, "delta_zscore": 0.0, "oi_change": 0.0},
    )
    if status == "MERGED":
        evidence["merged_from_zone_id"] = str(zone["zone_id"])
        evidence["merged_into_zone_id"] = str(zone.get("merged_into_zone_id", ""))
    else:
        evidence["age_days"] = int(float(zone.get("age_days", 0) or 0))
        evidence["max_zone_age_days"] = 7
        evidence["invalidation_reason"] = str(zone.get("invalidation_reason", ""))
    return {
        "event_id": "",
        "event_timestamp": _format_ts(event_ts),
        "event_type": event_type,
        "zone_id": zone["zone_id"],
        "side": zone["side"],
        "price_before": "",
        "event_high": "",
        "event_low": "",
        "event_close": "",
        "excursion_abs": 0,
        "excursion_atr": 0,
        "volume_zscore": 0,
        "delta_zscore": 0,
        "oi_change": 0,
        "reaction_status": "UNCLASSIFIED",
        "evidence_json": _json(evidence),
        "data_quality": zone["data_quality"],
    }


def _market_event(
    *,
    zone: dict[str, object],
    event_type: str,
    candle: pd.Series,
    feed: pd.DataFrame,
    previous_status: dict[str, str],
    context: dict[str, dict[str, float]],
    trigger: str,
    excursion_abs: float,
    new_status: str,
) -> dict[str, object]:
    event_ts = _format_ts(candle["Timestamp"])
    ctx = context.get(event_ts, {"volume_zscore": 0.0, "delta_zscore": 0.0, "oi_change": 0.0})
    evidence = _base_evidence(
        zone=zone,
        previous_status=previous_status.get(str(zone["zone_id"]), ""),
        new_status=new_status,
        trigger=trigger,
        candle_timestamp=event_ts,
        candle_high=float(candle["HiPrice"]),
        candle_low=float(candle["LowPrice"]),
        candle_close=float(candle["ClosePrice"]),
        context=ctx,
    )
    return {
        "event_id": "",
        "event_timestamp": event_ts,
        "event_type": event_type,
        "zone_id": zone["zone_id"],
        "side": zone["side"],
        "price_before": _price_before(feed, candle["Timestamp"]),
        "event_high": float(candle["HiPrice"]),
        "event_low": float(candle["LowPrice"]),
        "event_close": float(candle["ClosePrice"]),
        "excursion_abs": float(excursion_abs),
        "excursion_atr": 0,
        "volume_zscore": ctx["volume_zscore"],
        "delta_zscore": ctx["delta_zscore"],
        "oi_change": ctx["oi_change"],
        "reaction_status": "UNCLASSIFIED",
        "evidence_json": _json(evidence),
        "data_quality": zone["data_quality"],
    }


def _base_evidence(
    *,
    zone: dict[str, object],
    previous_status: str,
    new_status: str,
    trigger: str,
    candle_timestamp: str,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    context: dict[str, float],
) -> dict[str, object]:
    return {
        "candle_close": candle_close,
        "candle_high": candle_high,
        "candle_low": candle_low,
        "candle_timestamp": candle_timestamp,
        "confidence_score": int(float(zone.get("confidence_score", 0) or 0)),
        "confidence_tier": str(zone.get("confidence_tier", "")),
        "data_quality": str(zone.get("data_quality", "")),
        "delta_zscore": float(context["delta_zscore"]),
        "new_status": new_status,
        "oi_change": float(context["oi_change"]),
        "previous_status": previous_status,
        "price_lower": float(zone["price_lower"]),
        "price_mid": float(zone["price_mid"]),
        "price_upper": float(zone["price_upper"]),
        "side": str(zone["side"]),
        "active_forward": str(zone.get("active_forward", "")),
        "active_forward_role": str(zone.get("active_forward_role", "")),
        "consumption_status": str(zone.get("consumption_status", "")),
        "consumed_at": str(zone.get("consumed_at", "")),
        "first_sweep_at": str(zone.get("first_sweep_at", "")),
        "htf_acceptance_count": int(float(zone.get("htf_acceptance_count", 0) or 0)),
        "htf_close_through_count": int(float(zone.get("htf_close_through_count", 0) or 0)),
        "htf_confirmation_timestamp": str(zone.get("htf_confirmation_timestamp", "")),
        "htf_level_type": str(zone.get("htf_level_type", "")),
        "htf_lifecycle_status": str(zone.get("htf_lifecycle_status", "")),
        "htf_origin_price": float(zone.get("htf_origin_price", 0) or 0),
        "htf_origin_timestamp": str(zone.get("htf_origin_timestamp", "")),
        "htf_sweep_count": int(float(zone.get("htf_sweep_count", 0) or 0)),
        "history_context_incomplete": str(zone.get("history_context_incomplete", "")),
        "history_context_start": str(zone.get("history_context_start", "")),
        "m1_interaction_count": int(float(zone.get("m1_interaction_count", 0) or 0)),
        "resweep_count": int(float(zone.get("resweep_count", 0) or 0)),
        "source_timeframe_primary": str(zone.get("source_timeframe_primary", "")),
        "source_timeframes": str(zone.get("source_timeframes", "")),
        "structural_zone_mode": str(zone.get("structural_zone_mode", "")),
        "sweep_importance_class": str(zone.get("sweep_importance_class", "")),
        "trigger": trigger,
        "volume_zscore": float(context["volume_zscore"]),
        "zone_behavior_state": str(zone.get("zone_behavior_state", "")),
        "zone_id": str(zone["zone_id"]),
        "zone_type": str(zone["zone_type"]),
        **_score_instrumentation_evidence(zone),
    }


def _first_cross(zone: dict[str, object], feed: pd.DataFrame) -> pd.Series | None:
    lower = float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"])
    upper = float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"])
    if zone["side"] == "BUY_SIDE":
        crossed = feed[feed["HiPrice"] > upper]
    else:
        crossed = feed[feed["LowPrice"] < lower]
    if crossed.empty:
        return None
    return crossed.iloc[0]


def _first_touch(zone: dict[str, object], feed: pd.DataFrame) -> pd.Series | None:
    lower = float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"])
    upper = float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"])
    if zone["side"] == "BUY_SIDE":
        touched = feed[(feed["HiPrice"] >= lower) & (feed["HiPrice"] <= upper)]
    else:
        touched = feed[(feed["LowPrice"] <= upper) & (feed["LowPrice"] >= lower)]
    if touched.empty:
        return None
    return touched.iloc[0]


def _first_approach(zone: dict[str, object], feed: pd.DataFrame) -> pd.Series | None:
    latest_close = float(feed.iloc[-1]["ClosePrice"])
    threshold = max(APPROACH_THRESHOLD_MIN_USD, latest_close * APPROACH_THRESHOLD_FRACTION)
    lower = float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"])
    upper = float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"])
    if zone["side"] == "BUY_SIDE":
        approached = feed[(feed["HiPrice"] >= lower - threshold) & (feed["HiPrice"] < lower)]
    else:
        approached = feed[(feed["LowPrice"] <= upper + threshold) & (feed["LowPrice"] > upper)]
    if approached.empty:
        return None
    return approached.iloc[0]


def _cross_excursion(zone: dict[str, object], candle: pd.Series) -> float:
    lower = float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"])
    upper = float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"])
    if zone["side"] == "BUY_SIDE":
        return max(0.0, float(candle["HiPrice"]) - upper)
    return max(0.0, lower - float(candle["LowPrice"]))


def _min_sweep_excursion(zone: dict[str, object]) -> float:
    return max(SWEEP_MIN_EXCURSION_USD, float(zone["price_mid"]) * SWEEP_MIN_EXCURSION_FRACTION)


def _activity_evidence(ctx: dict[str, float], data_quality: str) -> list[str]:
    if data_quality != "RAW":
        return []
    evidence = []
    if float(ctx["volume_zscore"]) >= SWEEP_ACTIVITY_ZSCORE_THRESHOLD:
        evidence.append("volume_zscore")
    if abs(float(ctx["delta_zscore"])) >= SWEEP_ACTIVITY_ZSCORE_THRESHOLD:
        evidence.append("delta_zscore")
    if abs(float(ctx["oi_change"])) > 0:
        evidence.append("oi_change")
    return evidence


def _event_data_quality(zone: dict[str, object], candle: pd.Series) -> str:
    values = {str(zone.get("data_quality", "")), str(candle.get("DataQuality", ""))}
    if values == {"RAW"}:
        return "RAW"
    if "RECOVERED_DEGRADED" in values:
        return "RECOVERED_DEGRADED"
    return sorted(value for value in values if value)[0] if any(values) else "RAW"


def _consumed_before_or_at(zone: dict[str, object], timestamp) -> bool:
    if str(zone.get("consumption_status", "")) not in {"CONSUMED", "CHOPPED_THROUGH", "EXPIRED"}:
        return False
    consumed_at = str(zone.get("consumed_at", "") or "")
    if not consumed_at:
        return True
    return pd.Timestamp(consumed_at) <= pd.Timestamp(timestamp)


def _non_fresh_role_before_or_at(zone: dict[str, object], timestamp) -> bool:
    role = str(zone.get("active_forward_role", "") or "FRESH_LIQUIDITY")
    if role in LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES:
        return True
    if role == "FRESH_LIQUIDITY" and local_session_context_role(zone):
        return True
    if role not in {"AUDIT_ONLY", "INACTIVE"}:
        return False
    first_sweep_at = str(zone.get("first_sweep_at", "") or "")
    if not first_sweep_at:
        return True
    return pd.Timestamp(first_sweep_at) < pd.Timestamp(timestamp)


def _is_repeated_prior_cross_without_new_transition(
    *,
    zone: dict[str, object],
    candle: pd.Series,
    feed: pd.DataFrame,
    previous_status: dict[str, str],
) -> bool:
    if previous_status.get(str(zone["zone_id"])) != "CROSSED_UNCLASSIFIED":
        return False
    previous_rows = feed[feed["Timestamp"] < pd.Timestamp(candle["Timestamp"])]
    if previous_rows.empty:
        return True
    lower = float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"])
    upper = float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"])
    if zone["side"] == "BUY_SIDE":
        return bool((previous_rows["HiPrice"] > upper).all())
    return bool((previous_rows["LowPrice"] < lower).all())


def _price_before(feed: pd.DataFrame, timestamp) -> float | str:
    previous = feed[feed["Timestamp"] < pd.Timestamp(timestamp)]
    if previous.empty:
        return ""
    return float(previous.iloc[-1]["ClosePrice"])


def _previous_status_map(previous_registry: pd.DataFrame | None) -> dict[str, str]:
    if previous_registry is None or previous_registry.empty:
        return {}
    return {
        str(row["zone_id"]): str(row["status"])
        for _, row in previous_registry.iterrows()
    }


def _context_map(volume_delta_state: pd.DataFrame) -> dict[str, dict[str, float]]:
    if volume_delta_state.empty:
        return {}
    return {
        str(row["timestamp"]): {
            "volume_zscore": float(row["volume_zscore"]),
            "delta_zscore": float(row["delta_zscore"]),
            "oi_change": float(row["oi_change"]),
        }
        for _, row in volume_delta_state.iterrows()
    }


def _fixed_counts(frame: pd.DataFrame, column: str, values: list[str]) -> str:
    counts = frame[column].value_counts() if not frame.empty else {}
    return ", ".join(f"{value}={int(counts.get(value, 0))}" for value in values)


def _crossed_without_sweep_evidence(event_log: pd.DataFrame) -> int:
    crossed = event_log[event_log["event_type"] == "LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED"]
    unresolved = event_log[event_log["event_type"] == "LIQUIDITY_SWEEP_UNRESOLVED"]
    unresolved_keys = {
        (str(row["event_timestamp"]), str(row["zone_id"]))
        for _, row in unresolved.iterrows()
    }
    return int(
        sum(
            (str(row["event_timestamp"]), str(row["zone_id"])) not in unresolved_keys
            for _, row in crossed.iterrows()
        )
    )


def _market_move_stats(unresolved: pd.DataFrame) -> dict[str, object]:
    if unresolved.empty or "market_move_id" not in unresolved.columns:
        return {
            "grouped_market_move_count": 0,
            "multi_event_market_move_count": 0,
            "avg_unresolved_events_per_market_move": "0",
            "max_unresolved_events_per_market_move": 0,
            "max_group_span_minutes": "0",
            "groups_over_configured_window": 0,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
        }
    moves = unresolved[unresolved["market_move_id"].fillna("").astype(str) != ""]
    if moves.empty:
        return {
            "grouped_market_move_count": 0,
            "multi_event_market_move_count": 0,
            "avg_unresolved_events_per_market_move": "0",
            "max_unresolved_events_per_market_move": 0,
            "max_group_span_minutes": "0",
            "groups_over_configured_window": 0,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
        }
    counts = moves.groupby("market_move_id", sort=True).size()
    spans = (
        pd.to_numeric(moves.get("group_span_minutes", ""), errors="coerce")
        .groupby(moves["market_move_id"])
        .max()
    )
    max_span = 0.0 if spans.empty else float(spans.max())
    return {
        "grouped_market_move_count": int(len(counts)),
        "multi_event_market_move_count": int((counts > 1).sum()),
        "avg_unresolved_events_per_market_move": f"{float(counts.mean()):.6g}",
        "max_unresolved_events_per_market_move": int(counts.max()),
        "max_group_span_minutes": f"{max_span:.6g}",
        "groups_over_configured_window": int((spans > MARKET_MOVE_GROUP_WINDOW_MINUTES).sum()),
        "grouping_window_mode": GROUPING_WINDOW_MODE,
    }


def _market_move_group_row(group: pd.DataFrame) -> dict[str, object]:
    group = group.sort_values(["event_timestamp", "zone_id", "event_id"], kind="mergesort")
    primary = group[group["market_move_role"] == "PRIMARY"]
    primary_row = primary.iloc[0] if not primary.empty else group.iloc[0]
    group_start_ts = pd.Timestamp(group["event_timestamp"].map(pd.Timestamp).min())
    group_end_ts = pd.Timestamp(group["event_timestamp"].map(pd.Timestamp).max())
    group_span_minutes = _span_minutes(group_start_ts, group_end_ts)
    evidence = [_event_evidence(row) for _, row in group.iterrows()]
    lowers = [_float_or_none(item.get("price_lower", "")) for item in evidence]
    uppers = [_float_or_none(item.get("price_upper", "")) for item in evidence]
    mids = [_float_or_none(item.get("price_mid", "")) for item in evidence]
    representative_mid = _float_or_none(_event_evidence(primary_row).get("price_mid", ""))
    if representative_mid is None:
        representative_mid = next((value for value in mids if value is not None), 0.0)
    precision_statuses = _pipe_unique(str(item.get("precision_status", "")) for item in evidence)
    confidence_tiers = _pipe_unique(str(item.get("confidence_tier", "")) for item in evidence)
    data_quality = _pipe_unique(str(value) for value in group["data_quality"])
    selection_reason, selection_components = _primary_selection_diagnostics(group, primary_row.name)
    row = {
        "market_move_id": str(primary_row["market_move_id"]),
        "group_start_timestamp": _format_ts(group_start_ts),
        "group_end_timestamp": _format_ts(group_end_ts),
        "group_span_minutes": group_span_minutes,
        "grouping_window_minutes": MARKET_MOVE_GROUP_WINDOW_MINUTES,
        "grouping_window_mode": GROUPING_WINDOW_MODE,
        "event_timestamp": _format_ts(group_start_ts),
        "side": str(primary_row["side"]),
        "primary_event_id": str(primary_row["event_id"]),
        "primary_zone_id": str(primary_row["zone_id"]),
        "primary_selection_reason": selection_reason,
        "primary_selection_components_json": _json(selection_components),
        "event_count": len(group),
        "zone_ids": "|".join(str(value) for value in group["zone_id"]),
        "event_ids": "|".join(str(value) for value in group["event_id"]),
        "min_zone_price_lower": min((value for value in lowers if value is not None), default=0.0),
        "max_zone_price_upper": max((value for value in uppers if value is not None), default=0.0),
        "representative_zone_price_mid": representative_mid,
        "max_excursion_abs": _numeric_max(group, "excursion_abs"),
        "max_volume_zscore": _numeric_max(group, "volume_zscore"),
        "max_abs_delta_zscore": _numeric_abs_max(group, "delta_zscore"),
        "total_oi_change": _numeric_sum(group, "oi_change"),
        "precision_statuses": precision_statuses,
        "confidence_tiers": confidence_tiers,
        "data_quality": data_quality,
    }
    row["evidence_json"] = _json(
        {
            "event_count": int(row["event_count"]),
            "event_ids": str(row["event_ids"]),
            "group_end_timestamp": str(row["group_end_timestamp"]),
            "group_span_minutes": float(row["group_span_minutes"]),
            "group_start_timestamp": str(row["group_start_timestamp"]),
            "grouping_rule": "same_side_within_anchored_2_minute_window",
            "grouping_window_minutes": MARKET_MOVE_GROUP_WINDOW_MINUTES,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
            "market_move_id": str(row["market_move_id"]),
            "primary_event_id": str(row["primary_event_id"]),
            "primary_selection_reason": str(row["primary_selection_reason"]),
            "primary_zone_id": str(row["primary_zone_id"]),
            "zone_ids": str(row["zone_ids"]),
        }
    )
    return row


def _primary_event_index(group: pd.DataFrame) -> int:
    scored = group.copy()
    scored["_confidence_score"] = scored.apply(_event_confidence_score, axis=1)
    scored["_zone_width_pct"] = scored.apply(_event_zone_width_pct, axis=1)
    scored["_zone_id_sort"] = scored["zone_id"].astype(str)
    scored["_event_id_sort"] = scored["event_id"].astype(str)
    scored = scored.sort_values(
        [
            "_confidence_score",
            "excursion_abs",
            "_zone_width_pct",
            "_zone_id_sort",
            "_event_id_sort",
        ],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    )
    return int(scored.index[0])


def _primary_selection_diagnostics(group: pd.DataFrame, primary_idx: int) -> tuple[str, dict[str, object]]:
    scored = group.copy()
    scored["_confidence_score"] = scored.apply(_event_confidence_score, axis=1)
    scored["_zone_width_pct"] = scored.apply(_event_zone_width_pct, axis=1)
    selected = scored.loc[primary_idx]
    reason = "highest_confidence_score"
    tie_breakers: list[str] = []

    confidence_peers = scored[scored["_confidence_score"] == selected["_confidence_score"]]
    if len(confidence_peers) > 1:
        tie_breakers.append("highest_excursion_abs")
        excursion_peers = confidence_peers[
            pd.to_numeric(confidence_peers["excursion_abs"], errors="coerce")
            == float(selected["excursion_abs"])
        ]
        reason = "highest_excursion_abs_tiebreak"
        if len(excursion_peers) > 1:
            tie_breakers.append("narrowest_zone")
            width_peers = excursion_peers[
                excursion_peers["_zone_width_pct"] == selected["_zone_width_pct"]
            ]
            reason = "narrowest_zone_tiebreak"
            if len(width_peers) > 1:
                tie_breakers.append("zone_id")
                zone_peers = width_peers[
                    width_peers["zone_id"].astype(str) == str(selected["zone_id"])
                ]
                reason = "zone_id_tiebreak"
                if len(zone_peers) > 1:
                    tie_breakers.append("event_id")
                    reason = "event_id_tiebreak"

    components = {
        "selected_confidence_score": float(selected["_confidence_score"]),
        "selected_event_id": str(selected["event_id"]),
        "selected_excursion_abs": float(selected["excursion_abs"]),
        "selected_zone_id": str(selected["zone_id"]),
        "selected_zone_width_pct": float(selected["_zone_width_pct"]),
        "tie_breakers_used": tie_breakers,
    }
    return reason, components


def _event_confidence_score(row: pd.Series) -> float:
    evidence = _event_evidence(row)
    return _float_or_none(evidence.get("confidence_score", "")) or 0.0


def _event_zone_width_pct(row: pd.Series) -> float:
    evidence = _event_evidence(row)
    value = _float_or_none(evidence.get("zone_width_pct", ""))
    if value is not None:
        return value
    lower = _float_or_none(evidence.get("price_lower", ""))
    upper = _float_or_none(evidence.get("price_upper", ""))
    mid = _float_or_none(evidence.get("price_mid", ""))
    if lower is None or upper is None or not mid:
        return float("inf")
    return abs(upper - lower) / abs(mid) * 100


def _event_evidence(row: pd.Series) -> dict[str, object]:
    try:
        return json.loads(str(row.get("evidence_json", "{}")))
    except json.JSONDecodeError:
        return {}


def _market_move_id(first_ts: pd.Timestamp, side: str, group_number: int) -> str:
    compact_ts = _format_ts(first_ts).replace("-", "").replace(":", "").replace("Z", "")
    compact_ts = compact_ts.replace("T", "_")
    return f"move_{compact_ts}_{side}_{group_number:06d}"


def _float_or_none(value) -> float | None:
    try:
        if value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _numeric_max(frame: pd.DataFrame, column: str) -> float:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return 0.0 if values.empty else float(values.max())


def _numeric_abs_max(frame: pd.DataFrame, column: str) -> float:
    values = pd.to_numeric(frame[column], errors="coerce").dropna().abs()
    return 0.0 if values.empty else float(values.max())


def _numeric_sum(frame: pd.DataFrame, column: str) -> float:
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _span_minutes(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return float((end - start).total_seconds() / 60)


def _pipe_unique(values) -> str:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return "|".join(out)


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _score_instrumentation_evidence(zone: dict[str, object]) -> dict[str, object]:
    return {
        column: zone.get(column, "")
        for column in SCORE_INSTRUMENTATION_COLUMNS
        if column in zone
    }
