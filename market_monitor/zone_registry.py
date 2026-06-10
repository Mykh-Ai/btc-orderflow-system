from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_monitor.liquidity_zones import LIQUIDITY_MAP_COLUMNS
from market_monitor.score_instrumentation import (
    HARD_WIDE_ZONE_WIDTH_PCT,
    PRECISION_LOW,
    PRECISION_TOO_WIDE,
    SCORE_INSTRUMENTATION_COLUMNS,
    precision_status_for_width,
    score_instrumentation_fields,
)
from market_monitor.structure import aggregate_timeframe


REGISTRY_COLUMNS = [
    "zone_id",
    "first_seen_at",
    "last_seen_at",
    "last_updated_at",
    "side",
    "zone_type",
    "price_lower",
    "price_upper",
    "price_mid",
    "source_level_ids",
    "source_timeframes",
    "source_timeframe_primary",
    "htf_level_type",
    "htf_origin_timestamp",
    "htf_origin_price",
    "htf_confirmation_timestamp",
    "status",
    "consumption_status",
    "active_forward",
    "cross_through_count",
    "close_above_count",
    "close_below_count",
    "alternating_close_count",
    "bars_inside_zone_lifetime",
    "last_clean_reaction_at",
    "consumed_at",
    "consumption_reason",
    "zone_outer_lower",
    "zone_outer_upper",
    "zone_core_lower",
    "zone_core_upper",
    "zone_origin_start",
    "zone_origin_end",
    "first_sweep_at",
    "resweep_count",
    "failed_acceptance_count",
    "rejection_without_sweep_count",
    "drift_away_confirmed_at",
    "accepted_above_at",
    "accepted_below_at",
    "structural_zone_mode",
    "zone_behavior_state",
    "active_forward_role",
    "htf_lifecycle_status",
    "m1_interaction_count",
    "htf_sweep_count",
    "htf_close_through_count",
    "htf_acceptance_count",
    "history_context_start",
    "history_context_incomplete",
    "sweep_importance_class",
    "confidence_score",
    "confidence_tier",
    "age_bars",
    "age_days",
    "touch_count",
    "cross_count",
    "active_days",
    "last_touch_at",
    "last_cross_at",
    "merged_into_zone_id",
    "data_quality",
    "invalidation_reason",
    *SCORE_INSTRUMENTATION_COLUMNS,
]

CARRY_FORWARD_STATUSES = {
    "ACTIVE",
    "APPROACHED",
    "TOUCHED",
    "REACTED",
    "FLIPPED_REACTION_ZONE",
    "CROSSED_UNCLASSIFIED",
}
INACTIVE_STATUSES = {"INVALIDATED", "EXPIRED", "MERGED"}
MAX_ZONE_AGE_DAYS = 7
MAX_ZONE_AGE_REASON = "MAX_ZONE_AGE_DAYS_EXCEEDED"
MAX_CROSS_THROUGH_COUNT = 3
MAX_ALTERNATING_CLOSE_COUNT = 3
MAX_BARS_INSIDE_ZONE_LIFETIME = 20
REACTION_LOOKAHEAD_BARS_FOR_LIFECYCLE = 30
ACCEPTANCE_CLOSE_BARS = 3
ACTIVE_FORWARD_STATUSES = {"ACTIVE", "TOUCHED", "REACTED", "FLIPPED_REACTION_ZONE"}
INACTIVE_CONSUMPTION_STATUSES = {"CONSUMED", "CHOPPED_THROUGH", "EXPIRED"}
BROAD_STRUCTURAL_MODES = {
    "BROAD_STRUCTURAL_ZONE",
    "PATTERN_DERIVED_ZONE",
    "REACTION_ZONE",
}
ACTIVE_AUDIT_ROLES = {
    "FRESH_LIQUIDITY",
    "REACTION_ZONE",
    "DISTRIBUTION_ZONE",
    "RETEST_ZONE",
}
NON_FRESH_ACTIVE_ROLES = {"REACTION_ZONE", "DISTRIBUTION_ZONE", "RETEST_ZONE"}
LOCAL_SESSION_HEAVY_M1_INTERACTION_COUNT = 240
LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES = {
    "LOCAL_SESSION_CONTEXT",
    "LOCAL_REPEATED_INTERACTION",
    "LOCAL_NOISY_ZONE",
    "SESSION_CHOPPED",
}
M15_ACTIVE_FORWARD_ROLES = {
    "M15_MINIMUM_STRUCTURE",
    "M15_REACTION_ZONE",
    "M15_STRUCTURE_SWEEP",
    "M15_CONSUMED",
}
M15_LIFECYCLE_STATUSES = {
    "M15_ACTIVE",
    "M15_SWEPT",
    "M15_CLOSE_THROUGH",
    "M15_ACCEPTED",
}


def load_registry(path: str | Path | None) -> pd.DataFrame:
    if path is None:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    registry_path = Path(path)
    if not registry_path.exists():
        raise FileNotFoundError(f"Registry input not found: {registry_path}")
    registry = pd.read_csv(registry_path, dtype=str)
    return _normalize_registry(registry)


def build_zone_registry(
    *,
    liquidity_map: pd.DataFrame,
    feed: pd.DataFrame,
    registry_in: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    previous = _normalize_registry(registry_in)
    current_zones = _current_zones_to_registry(liquidity_map, previous)

    historical = previous[~previous["status"].isin(CARRY_FORWARD_STATUSES)].copy()
    carry = previous[previous["status"].isin(CARRY_FORWARD_STATUSES)].copy()
    candidates = _concat_registry_frames([carry, current_zones])

    active_rows, merged_rows = _merge_registry_candidates(candidates)
    active_rows = _update_lifecycle(active_rows, feed)
    active_rows = _apply_expiry(active_rows)

    registry_out = _concat_registry_frames([historical, merged_rows, active_rows])
    registry_out = _normalize_registry(registry_out)
    registry_out = registry_out.sort_values(
        ["first_seen_at", "zone_id", "status"], kind="mergesort"
    ).reset_index(drop=True)

    stats = {
        "carried_loaded": len(carry),
        "new_created": len(current_zones),
        "carried_forward": int(registry_out["status"].isin(CARRY_FORWARD_STATUSES).sum()),
        "merged": int((registry_out["status"] == "MERGED").sum()),
        "expired": int((registry_out["status"] == "EXPIRED").sum()),
        "crossed_unclassified": int(
            (registry_out["status"] == "CROSSED_UNCLASSIFIED").sum()
        ),
        "active_registry": int((registry_out["status"] == "ACTIVE").sum()),
        "active_forward": int(_active_forward_mask(registry_out).sum()),
        "consumed": int((registry_out["consumption_status"] == "CONSUMED").sum()),
        "chopped_through": int((registry_out["consumption_status"] == "CHOPPED_THROUGH").sum()),
    }
    return registry_out, stats


def write_registry(registry: pd.DataFrame, path: str | Path) -> None:
    registry_path = Path(path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    _normalize_registry(registry).to_csv(registry_path, index=False)


def forward_liquidity_from_registry(
    registry: pd.DataFrame, latest_close: float | None
) -> pd.DataFrame:
    registry = _normalize_registry(registry)
    active = registry[_active_forward_mask(registry)].copy()
    if latest_close is not None:
        close = float(latest_close)
        active = active[
            ((active["side"] == "BUY_SIDE") & (active["price_lower"].astype(float) > close))
            | ((active["side"] == "SELL_SIDE") & (active["price_upper"].astype(float) < close))
        ]
    rows = []
    for _, row in active.iterrows():
        rows.append(
            {
                "zone_id": row["zone_id"],
                "created_at": row["first_seen_at"],
                "last_updated_at": row["last_updated_at"],
                "side": row["side"],
                "zone_type": row["zone_type"],
                "price_lower": float(row["price_lower"]),
                "price_upper": float(row["price_upper"]),
                "price_mid": float(row["price_mid"]),
                "source_level_ids": row["source_level_ids"],
                "source_timeframes": row["source_timeframes"],
                "source_timeframe_primary": row["source_timeframe_primary"],
                "htf_level_type": row["htf_level_type"],
                "htf_origin_timestamp": row["htf_origin_timestamp"],
                "htf_origin_price": float(row["htf_origin_price"]),
                "htf_confirmation_timestamp": row["htf_confirmation_timestamp"],
                "status": row["status"],
                "consumption_status": row["consumption_status"],
                "active_forward": _bool_text(row["active_forward"]),
                "cross_through_count": int(float(row["cross_through_count"])),
                "close_above_count": int(float(row["close_above_count"])),
                "close_below_count": int(float(row["close_below_count"])),
                "alternating_close_count": int(float(row["alternating_close_count"])),
                "bars_inside_zone_lifetime": int(float(row["bars_inside_zone_lifetime"])),
                "last_clean_reaction_at": row["last_clean_reaction_at"],
                "consumed_at": row["consumed_at"],
                "consumption_reason": row["consumption_reason"],
                "zone_outer_lower": float(row["zone_outer_lower"]),
                "zone_outer_upper": float(row["zone_outer_upper"]),
                "zone_core_lower": float(row["zone_core_lower"]),
                "zone_core_upper": float(row["zone_core_upper"]),
                "zone_origin_start": row["zone_origin_start"],
                "zone_origin_end": row["zone_origin_end"],
                "first_sweep_at": row["first_sweep_at"],
                "resweep_count": int(float(row["resweep_count"])),
                "failed_acceptance_count": int(float(row["failed_acceptance_count"])),
                "rejection_without_sweep_count": int(float(row["rejection_without_sweep_count"])),
                "drift_away_confirmed_at": row["drift_away_confirmed_at"],
                "accepted_above_at": row["accepted_above_at"],
                "accepted_below_at": row["accepted_below_at"],
                "structural_zone_mode": row["structural_zone_mode"],
                "zone_behavior_state": row["zone_behavior_state"],
                "active_forward_role": row["active_forward_role"],
                "htf_lifecycle_status": row["htf_lifecycle_status"],
                "m1_interaction_count": int(float(row["m1_interaction_count"])),
                "htf_sweep_count": int(float(row["htf_sweep_count"])),
                "htf_close_through_count": int(float(row["htf_close_through_count"])),
                "htf_acceptance_count": int(float(row["htf_acceptance_count"])),
                "history_context_start": row["history_context_start"],
                "history_context_incomplete": _bool_text(row["history_context_incomplete"]),
                "sweep_importance_class": row["sweep_importance_class"],
                "confidence_score": int(float(row["confidence_score"])),
                "confidence_tier": row["confidence_tier"],
                "touch_count": int(float(row["touch_count"])),
                "sweep_count": 0,
                "distance_from_close_pct": _distance_from_close(
                    float(row["price_mid"]), latest_close
                ),
                "data_quality": row["data_quality"],
                "invalidation_reason": row["invalidation_reason"],
                **_instrumentation_from_row(row),
            }
        )
    return pd.DataFrame(rows, columns=LIQUIDITY_MAP_COLUMNS)


def _current_zones_to_registry(
    liquidity_map: pd.DataFrame, previous: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    next_id = _next_zone_index(previous)
    for _, zone in liquidity_map.iterrows():
        zone_id = f"zone_{next_id:06d}"
        next_id += 1
        created = str(zone["created_at"])
        rows.append(
            {
                "zone_id": zone_id,
                "first_seen_at": created,
                "last_seen_at": created,
                "last_updated_at": created,
                "side": zone["side"],
                "zone_type": zone["zone_type"],
                "price_lower": float(zone["price_lower"]),
                "price_upper": float(zone["price_upper"]),
                "price_mid": float(zone["price_mid"]),
                "source_level_ids": zone["source_level_ids"],
                "source_timeframes": zone["source_timeframes"],
                "source_timeframe_primary": str(
                    zone.get("source_timeframe_primary", "")
                    or _source_timeframe_primary_from_row(zone)
                ),
                "htf_level_type": str(zone.get("htf_level_type", "") or ""),
                "htf_origin_timestamp": str(zone.get("htf_origin_timestamp", "") or ""),
                "htf_origin_price": _float_value(zone.get("htf_origin_price", 0)),
                "htf_confirmation_timestamp": str(zone.get("htf_confirmation_timestamp", "") or ""),
                "status": "ACTIVE",
                "consumption_status": str(zone.get("consumption_status", "FRESH") or "FRESH"),
                "active_forward": _bool_text(zone.get("active_forward", True)),
                "cross_through_count": int(float(zone.get("cross_through_count", 0) or 0)),
                "close_above_count": int(float(zone.get("close_above_count", 0) or 0)),
                "close_below_count": int(float(zone.get("close_below_count", 0) or 0)),
                "alternating_close_count": int(float(zone.get("alternating_close_count", 0) or 0)),
                "bars_inside_zone_lifetime": int(float(zone.get("bars_inside_zone_lifetime", 0) or 0)),
                "last_clean_reaction_at": str(zone.get("last_clean_reaction_at", "") or ""),
                "consumed_at": str(zone.get("consumed_at", "") or ""),
                "consumption_reason": str(zone.get("consumption_reason", "") or ""),
                "zone_outer_lower": float(zone.get("zone_outer_lower", zone["price_lower"]) or zone["price_lower"]),
                "zone_outer_upper": float(zone.get("zone_outer_upper", zone["price_upper"]) or zone["price_upper"]),
                "zone_core_lower": float(zone.get("zone_core_lower", zone["price_lower"]) or zone["price_lower"]),
                "zone_core_upper": float(zone.get("zone_core_upper", zone["price_upper"]) or zone["price_upper"]),
                "zone_origin_start": str(zone.get("zone_origin_start", created) or created),
                "zone_origin_end": str(zone.get("zone_origin_end", created) or created),
                "first_sweep_at": str(zone.get("first_sweep_at", "") or ""),
                "resweep_count": int(float(zone.get("resweep_count", 0) or 0)),
                "failed_acceptance_count": int(float(zone.get("failed_acceptance_count", 0) or 0)),
                "rejection_without_sweep_count": int(float(zone.get("rejection_without_sweep_count", 0) or 0)),
                "drift_away_confirmed_at": str(zone.get("drift_away_confirmed_at", "") or ""),
                "accepted_above_at": str(zone.get("accepted_above_at", "") or ""),
                "accepted_below_at": str(zone.get("accepted_below_at", "") or ""),
                "structural_zone_mode": str(
                    zone.get("structural_zone_mode", "")
                    or _structural_zone_mode_from_row(zone)
                ),
                "zone_behavior_state": str(zone.get("zone_behavior_state", "NONE") or "NONE"),
                "active_forward_role": str(
                    zone.get("active_forward_role", "FRESH_LIQUIDITY") or "FRESH_LIQUIDITY"
                ),
                "htf_lifecycle_status": str(
                    zone.get("htf_lifecycle_status", "")
                    or _htf_lifecycle_status(
                        has_htf=_has_htf_source(zone),
                        htf_sweep_count=int(float(zone.get("htf_sweep_count", 0) or 0)),
                        htf_close_through_count=int(float(zone.get("htf_close_through_count", 0) or 0)),
                        htf_acceptance_count=int(float(zone.get("htf_acceptance_count", 0) or 0)),
                        history_context_incomplete=_bool_value(
                            zone.get("history_context_incomplete", False)
                        ),
                    )
                ),
                "m1_interaction_count": int(float(zone.get("m1_interaction_count", 0) or 0)),
                "htf_sweep_count": int(float(zone.get("htf_sweep_count", 0) or 0)),
                "htf_close_through_count": int(float(zone.get("htf_close_through_count", 0) or 0)),
                "htf_acceptance_count": int(float(zone.get("htf_acceptance_count", 0) or 0)),
                "history_context_start": str(zone.get("history_context_start", created) or created),
                "history_context_incomplete": _bool_text(zone.get("history_context_incomplete", False)),
                "sweep_importance_class": str(
                    zone.get("sweep_importance_class", "")
                    or _sweep_importance_class_from_row(zone)
                ),
                "confidence_score": int(zone["confidence_score"]),
                "confidence_tier": zone["confidence_tier"],
                "age_bars": 0,
                "age_days": 0,
                "touch_count": 0,
                "cross_count": 0,
                "active_days": 1,
                "last_touch_at": "",
                "last_cross_at": "",
                "merged_into_zone_id": "",
                "data_quality": zone["data_quality"],
                "invalidation_reason": "",
                **_instrumentation_from_row(zone),
            }
        )
    return _normalize_registry(pd.DataFrame(rows, columns=REGISTRY_COLUMNS))


def _merge_registry_candidates(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidates = _normalize_registry(candidates)
    if candidates.empty:
        return candidates, pd.DataFrame(columns=REGISTRY_COLUMNS)
    active_rows: list[dict[str, object]] = []
    merged_rows: list[dict[str, object]] = []

    for side in ["BUY_SIDE", "SELL_SIDE"]:
        side_rows = candidates[candidates["side"] == side].copy()
        side_rows = side_rows.sort_values(
            ["price_lower", "first_seen_at", "zone_id"], kind="mergesort"
        )
        cluster: list[dict[str, object]] = []
        for row in side_rows.to_dict("records"):
            if not cluster:
                cluster = [row]
                continue
            tolerance = _merge_tolerance(cluster + [row])
            current_upper = max(float(item["price_upper"]) for item in cluster)
            if (
                float(row["price_lower"]) <= current_upper + tolerance
                and _registry_merge_sources_compatible(cluster, row)
                and _registry_cluster_width_pct(cluster + [row]) < HARD_WIDE_ZONE_WIDTH_PCT
            ):
                cluster.append(row)
            else:
                active, merged = _collapse_registry_cluster(cluster)
                active_rows.append(active)
                merged_rows.extend(merged)
                cluster = [row]
        if cluster:
            active, merged = _collapse_registry_cluster(cluster)
            active_rows.append(active)
            merged_rows.extend(merged)
    return (
        _normalize_registry(pd.DataFrame(active_rows, columns=REGISTRY_COLUMNS)),
        _normalize_registry(pd.DataFrame(merged_rows, columns=REGISTRY_COLUMNS)),
    )


def _collapse_registry_cluster(
    cluster: list[dict[str, object]]
) -> tuple[dict[str, object], list[dict[str, object]]]:
    if len(cluster) == 1:
        row = cluster[0].copy()
        row["merged_into_zone_id"] = ""
        return row, []

    target = _merge_target(cluster)
    lower = min(float(row["price_lower"]) for row in cluster)
    upper = max(float(row["price_upper"]) for row in cluster)
    source_level_ids = _pipe_union(row["source_level_ids"] for row in cluster)
    source_timeframes = _pipe_union(row["source_timeframes"] for row in cluster)
    source_zone_types = sorted({str(row["zone_type"]) for row in cluster})
    confidence_components = _merged_confidence_components(
        cluster, source_timeframes, source_zone_types
    )
    confidence_score = int(confidence_components["final_confidence_score"])
    confidence_tier = _confidence_tier(confidence_score)
    instrumentation = score_instrumentation_fields(
        source_level_ids=source_level_ids,
        source_timeframes=source_timeframes,
        zone_type=_registry_merged_zone_type(str(target["side"]), source_zone_types),
        price_lower=lower,
        price_upper=upper,
        price_mid=(lower + upper) / 2,
        confidence_score=confidence_score,
        confidence_tier=confidence_tier,
        score_components=confidence_components,
    )

    active = target.copy()
    active.update(
        {
            "first_seen_at": min(str(row["first_seen_at"]) for row in cluster),
            "last_seen_at": max(str(row["last_seen_at"]) for row in cluster),
            "last_updated_at": max(str(row["last_updated_at"]) for row in cluster),
            "price_lower": lower,
            "price_upper": upper,
            "price_mid": (lower + upper) / 2,
            "source_level_ids": source_level_ids,
            "source_timeframes": source_timeframes,
            "source_timeframe_primary": _merged_source_timeframe_primary(cluster, source_timeframes),
            "htf_level_type": _merged_htf_text(cluster, "htf_level_type"),
            "htf_origin_timestamp": _merged_htf_text(cluster, "htf_origin_timestamp"),
            "htf_origin_price": _merged_htf_price(cluster, (lower + upper) / 2),
            "htf_confirmation_timestamp": _merged_htf_text(cluster, "htf_confirmation_timestamp"),
            "zone_type": _registry_merged_zone_type(str(target["side"]), source_zone_types),
            "consumption_status": _merged_consumption_status(cluster),
            "active_forward": _bool_text(any(_bool_value(row.get("active_forward", True)) for row in cluster)),
            "cross_through_count": max(int(float(row.get("cross_through_count", 0) or 0)) for row in cluster),
            "close_above_count": max(int(float(row.get("close_above_count", 0) or 0)) for row in cluster),
            "close_below_count": max(int(float(row.get("close_below_count", 0) or 0)) for row in cluster),
            "alternating_close_count": max(int(float(row.get("alternating_close_count", 0) or 0)) for row in cluster),
            "bars_inside_zone_lifetime": max(int(float(row.get("bars_inside_zone_lifetime", 0) or 0)) for row in cluster),
            "last_clean_reaction_at": max((str(row.get("last_clean_reaction_at", "") or "") for row in cluster), default=""),
            "consumed_at": max((str(row.get("consumed_at", "") or "") for row in cluster), default=""),
            "consumption_reason": _pipe_union(row.get("consumption_reason", "") for row in cluster),
            "zone_outer_lower": min(float(row.get("zone_outer_lower", row["price_lower"]) or row["price_lower"]) for row in cluster),
            "zone_outer_upper": max(float(row.get("zone_outer_upper", row["price_upper"]) or row["price_upper"]) for row in cluster),
            "zone_core_lower": min(float(row.get("zone_core_lower", row["price_lower"]) or row["price_lower"]) for row in cluster),
            "zone_core_upper": max(float(row.get("zone_core_upper", row["price_upper"]) or row["price_upper"]) for row in cluster),
            "zone_origin_start": min((str(row.get("zone_origin_start", "") or row["first_seen_at"]) for row in cluster), default=""),
            "zone_origin_end": max((str(row.get("zone_origin_end", "") or row["last_seen_at"]) for row in cluster), default=""),
            "first_sweep_at": _min_timestamp_text(row.get("first_sweep_at", "") for row in cluster),
            "resweep_count": max(int(float(row.get("resweep_count", 0) or 0)) for row in cluster),
            "failed_acceptance_count": max(int(float(row.get("failed_acceptance_count", 0) or 0)) for row in cluster),
            "rejection_without_sweep_count": max(int(float(row.get("rejection_without_sweep_count", 0) or 0)) for row in cluster),
            "drift_away_confirmed_at": _min_timestamp_text(row.get("drift_away_confirmed_at", "") for row in cluster),
            "accepted_above_at": _min_timestamp_text(row.get("accepted_above_at", "") for row in cluster),
            "accepted_below_at": _min_timestamp_text(row.get("accepted_below_at", "") for row in cluster),
            "structural_zone_mode": _merged_structural_zone_mode(cluster, source_zone_types),
            "zone_behavior_state": _merged_zone_behavior_state(cluster),
            "active_forward_role": _merged_active_forward_role(cluster),
            "htf_lifecycle_status": _merged_htf_lifecycle_status(cluster),
            "m1_interaction_count": max(int(float(row.get("m1_interaction_count", 0) or 0)) for row in cluster),
            "htf_sweep_count": max(int(float(row.get("htf_sweep_count", 0) or 0)) for row in cluster),
            "htf_close_through_count": max(int(float(row.get("htf_close_through_count", 0) or 0)) for row in cluster),
            "htf_acceptance_count": max(int(float(row.get("htf_acceptance_count", 0) or 0)) for row in cluster),
            "history_context_start": _min_timestamp_text(
                row.get("history_context_start", "") for row in cluster
            ),
            "history_context_incomplete": _bool_text(
                any(_bool_value(row.get("history_context_incomplete", False)) for row in cluster)
            ),
            "sweep_importance_class": _merged_sweep_importance_class(cluster),
            "confidence_score": confidence_score,
            "confidence_tier": confidence_tier,
            "touch_count": sum(int(float(row["touch_count"])) for row in cluster),
            "cross_count": sum(int(float(row["cross_count"])) for row in cluster),
            "active_days": max(int(float(row["active_days"])) for row in cluster),
            "data_quality": _quality_values(row["data_quality"] for row in cluster),
            "merged_into_zone_id": "",
            "invalidation_reason": "",
            **instrumentation,
        }
    )

    merged: list[dict[str, object]] = []
    for row in cluster:
        if row["zone_id"] == target["zone_id"]:
            continue
        merged_row = row.copy()
        merged_row["status"] = "MERGED"
        merged_row["active_forward"] = "false"
        merged_row["active_forward_role"] = "INACTIVE"
        merged_row["merged_into_zone_id"] = target["zone_id"]
        merged_row["invalidation_reason"] = ""
        merged.append(merged_row)
    return active, merged


def _registry_cluster_width_pct(rows: list[dict[str, object]]) -> float:
    lower = min(float(row["price_lower"]) for row in rows)
    upper = max(float(row["price_upper"]) for row in rows)
    return _zone_width_pct(lower, upper, (lower + upper) / 2)


def _merge_target(cluster: list[dict[str, object]]) -> dict[str, object]:
    return sorted(cluster, key=lambda row: (str(row["first_seen_at"]), str(row["zone_id"])))[0]


def _registry_merge_sources_compatible(
    cluster: list[dict[str, object]], row: dict[str, object]
) -> bool:
    row_is_m15 = _has_m15_source(row)
    cluster_has_m15 = any(_has_m15_source(item) for item in cluster)
    if row_is_m15 or cluster_has_m15:
        return row_is_m15 and all(_has_m15_source(item) for item in cluster)
    return True


def _update_lifecycle(registry: pd.DataFrame, feed: pd.DataFrame) -> pd.DataFrame:
    registry = _normalize_registry(registry)
    if registry.empty or feed.empty:
        return registry
    frame = feed.sort_values("Timestamp", kind="mergesort")
    run_end = _format_ts(frame["Timestamp"].max())
    updated = []
    for row in registry.to_dict("records"):
        row = row.copy()
        row_first_seen = _format_ts(row["first_seen_at"])
        effective_seen = max(run_end, row_first_seen)
        status, touch_at, cross_at = _path_status(row, frame)
        if touch_at and not row.get("last_touch_at"):
            row["last_touch_at"] = touch_at
        if cross_at:
            if not row.get("last_cross_at") or row["last_cross_at"] != cross_at:
                row["cross_count"] = int(float(row["cross_count"])) + 1
            row["last_cross_at"] = cross_at
        elif touch_at:
            row["touch_count"] = int(float(row["touch_count"])) + 1
            row["last_touch_at"] = touch_at
        row["status"] = status
        row["last_seen_at"] = effective_seen
        row["last_updated_at"] = effective_seen
        row["age_bars"] = _age_bars(row["first_seen_at"], frame)
        row["age_days"] = _age_days(row["first_seen_at"], effective_seen)
        row.update(_consumption_fields(row, frame))
        if row["consumption_status"] == "REACTED":
            row["status"] = "REACTED"
        if status in CARRY_FORWARD_STATUSES:
            row["active_days"] = max(int(float(row["active_days"])), int(row["age_days"]) + 1)
        row["active_forward_role"] = _active_forward_role(row)
        row["active_forward"] = _bool_text(_is_active_forward(row))
        updated.append(row)
    return _normalize_registry(pd.DataFrame(updated, columns=REGISTRY_COLUMNS))


def _path_status(row: dict[str, object], feed: pd.DataFrame) -> tuple[str, str, str]:
    lower = float(row.get("zone_outer_lower", row["price_lower"]) or row["price_lower"])
    upper = float(row.get("zone_outer_upper", row["price_upper"]) or row["price_upper"])
    after_first_seen = feed[feed["Timestamp"] >= pd.Timestamp(row["first_seen_at"])]
    if after_first_seen.empty:
        return str(row.get("status", "ACTIVE") or "ACTIVE"), "", ""
    if row["side"] == "BUY_SIDE":
        cross = after_first_seen[after_first_seen["HiPrice"] > upper]
        touch = after_first_seen[
            (after_first_seen["HiPrice"] >= lower) & (after_first_seen["LowPrice"] <= upper)
        ]
    else:
        cross = after_first_seen[after_first_seen["LowPrice"] < lower]
        touch = after_first_seen[
            (after_first_seen["LowPrice"] <= upper) & (after_first_seen["HiPrice"] >= lower)
        ]
    touch_at = "" if touch.empty else _format_ts(touch.iloc[0]["Timestamp"])
    cross_at = "" if cross.empty else _format_ts(cross.iloc[0]["Timestamp"])
    if cross_at:
        return "CROSSED_UNCLASSIFIED", touch_at or cross_at, cross_at
    if touch_at:
        return "TOUCHED", touch_at, ""
    return "ACTIVE", "", ""


def _consumption_fields(row: dict[str, object], feed: pd.DataFrame) -> dict[str, object]:
    after_first_seen = feed[feed["Timestamp"] >= pd.Timestamp(row["first_seen_at"])].sort_values(
        "Timestamp", kind="mergesort"
    )
    if after_first_seen.empty:
        return {
            "consumption_status": row.get("consumption_status", "FRESH") or "FRESH",
            "cross_through_count": int(float(row.get("cross_through_count", 0) or 0)),
            "close_above_count": int(float(row.get("close_above_count", 0) or 0)),
            "close_below_count": int(float(row.get("close_below_count", 0) or 0)),
            "alternating_close_count": int(float(row.get("alternating_close_count", 0) or 0)),
            "bars_inside_zone_lifetime": int(float(row.get("bars_inside_zone_lifetime", 0) or 0)),
            "last_clean_reaction_at": row.get("last_clean_reaction_at", "") or "",
            "consumed_at": row.get("consumed_at", "") or "",
            "consumption_reason": row.get("consumption_reason", "") or "",
            "zone_outer_lower": float(row.get("zone_outer_lower", row.get("price_lower", 0)) or 0),
            "zone_outer_upper": float(row.get("zone_outer_upper", row.get("price_upper", 0)) or 0),
            "zone_core_lower": float(row.get("zone_core_lower", row.get("price_lower", 0)) or 0),
            "zone_core_upper": float(row.get("zone_core_upper", row.get("price_upper", 0)) or 0),
            "zone_origin_start": row.get("zone_origin_start", "") or row.get("first_seen_at", ""),
            "zone_origin_end": row.get("zone_origin_end", "") or row.get("last_seen_at", ""),
            "first_sweep_at": row.get("first_sweep_at", "") or "",
            "resweep_count": int(float(row.get("resweep_count", 0) or 0)),
            "failed_acceptance_count": int(float(row.get("failed_acceptance_count", 0) or 0)),
            "rejection_without_sweep_count": int(float(row.get("rejection_without_sweep_count", 0) or 0)),
            "drift_away_confirmed_at": row.get("drift_away_confirmed_at", "") or "",
            "accepted_above_at": row.get("accepted_above_at", "") or "",
            "accepted_below_at": row.get("accepted_below_at", "") or "",
            "structural_zone_mode": row.get("structural_zone_mode", "") or _structural_zone_mode_from_row(row),
            "zone_behavior_state": row.get("zone_behavior_state", "NONE") or "NONE",
            "htf_lifecycle_status": row.get("htf_lifecycle_status", "") or _lifecycle_status_from_row(row),
            "m1_interaction_count": int(float(row.get("m1_interaction_count", 0) or 0)),
            "htf_sweep_count": int(float(row.get("htf_sweep_count", 0) or 0)),
            "htf_close_through_count": int(float(row.get("htf_close_through_count", 0) or 0)),
            "htf_acceptance_count": int(float(row.get("htf_acceptance_count", 0) or 0)),
            "history_context_start": row.get("history_context_start", "") or row.get("first_seen_at", ""),
            "history_context_incomplete": _bool_text(row.get("history_context_incomplete", False)),
            "sweep_importance_class": row.get("sweep_importance_class", "") or _sweep_importance_class_from_row(row),
        }

    lower = float(row.get("zone_outer_lower", row["price_lower"]) or row["price_lower"])
    upper = float(row.get("zone_outer_upper", row["price_upper"]) or row["price_upper"])
    core_lower = float(row.get("zone_core_lower", row["price_lower"]) or row["price_lower"])
    core_upper = float(row.get("zone_core_upper", row["price_upper"]) or row["price_upper"])
    closes = pd.to_numeric(after_first_seen["ClosePrice"], errors="coerce")
    highs = pd.to_numeric(after_first_seen["HiPrice"], errors="coerce")
    lows = pd.to_numeric(after_first_seen["LowPrice"], errors="coerce")
    close_above = closes > upper
    close_below = closes < lower
    inside = closes.between(lower, upper, inclusive="both")
    cross_through = (highs > upper) & (lows < lower)
    positions = [
        "ABOVE" if above else "BELOW" if below else "INSIDE"
        for above, below in zip(close_above.tolist(), close_below.tolist())
    ]
    alternating_count = _alternating_close_count(positions)
    clean_reaction_at = _clean_reaction_at(row, after_first_seen)
    cross_through_count = int(cross_through.sum())
    close_above_count = int(close_above.sum())
    close_below_count = int(close_below.sum())
    bars_inside = int(inside.sum())
    sweep_timestamps = _sweep_transition_timestamps(row, after_first_seen, lower, upper)
    previous_first_sweep = str(row.get("first_sweep_at", "") or "")
    first_sweep_at = previous_first_sweep or (sweep_timestamps[0] if sweep_timestamps else "")
    resweep_count = max(0, len(sweep_timestamps) - 1)
    accepted_above_at = _consecutive_threshold_at(after_first_seen, close_above.tolist())
    accepted_below_at = _consecutive_threshold_at(after_first_seen, close_below.tolist())
    failed_acceptance_count = _failed_acceptance_count(
        row,
        after_first_seen,
        close_above.tolist(),
        close_below.tolist(),
        lower,
        upper,
    )
    rejection_without_sweep_count = _rejection_without_sweep_count(
        row,
        after_first_seen,
        lower,
        upper,
        core_lower,
        core_upper,
    )
    drift_away_confirmed_at = _drift_away_confirmed_at(
        row,
        after_first_seen,
        first_sweep_at,
        failed_acceptance_count,
        lower,
        upper,
        core_lower,
        core_upper,
    )
    structural_zone_mode = str(row.get("structural_zone_mode", "") or _structural_zone_mode_from_row(row))
    is_broad = structural_zone_mode in BROAD_STRUCTURAL_MODES
    has_htf = _has_htf_source(row)
    m1_interaction_count = _m1_interaction_count(row, after_first_seen, lower, upper)
    htf_metrics = _htf_lifecycle_metrics(row, feed, lower, upper)
    htf_sweep_count = htf_metrics["htf_sweep_count"]
    htf_close_through_count = htf_metrics["htf_close_through_count"]
    htf_acceptance_count = htf_metrics["htf_acceptance_count"]
    history_context_start = (
        str(row.get("history_context_start", "") or "")
        or htf_metrics["history_context_start"]
        or _format_ts(after_first_seen["Timestamp"].min())
    )
    history_context_incomplete = _bool_value(row.get("history_context_incomplete", False)) or _bool_value(
        htf_metrics["history_context_incomplete"]
    )

    current_status = str(row.get("status", ""))
    consumption_status = "FRESH"
    consumed_at = ""
    consumption_reason = ""
    has_two_sided_full_close = close_above_count > 0 and close_below_count > 0
    true_broad_chop = (
        is_broad
        and has_two_sided_full_close
        and (
            alternating_count >= MAX_ALTERNATING_CLOSE_COUNT
            or cross_through_count >= MAX_CROSS_THROUGH_COUNT
        )
        and not clean_reaction_at
    )
    if current_status == "EXPIRED":
        consumption_status = "EXPIRED"
        consumed_at = row.get("last_updated_at", "") or row.get("last_seen_at", "")
        consumption_reason = row.get("invalidation_reason", "") or MAX_ZONE_AGE_REASON
    elif has_htf and htf_acceptance_count > 0:
        consumption_status = "SWEPT_ONCE"
    elif has_htf and htf_sweep_count > 0:
        consumption_status = "SWEPT_ONCE"
    elif is_broad and true_broad_chop:
        consumption_status = "CHOPPED_THROUGH"
        consumed_at = _threshold_reached_at(
            after_first_seen,
            positions,
            cross_through.tolist(),
            threshold_kind="alternating_close"
            if alternating_count >= MAX_ALTERNATING_CLOSE_COUNT
            else "cross_through",
        )
        consumption_reason = "broad_full_zone_two_sided_chop"
    elif clean_reaction_at:
        consumption_status = "REACTED"
    elif not is_broad and cross_through_count >= MAX_CROSS_THROUGH_COUNT:
        consumption_status = "CONSUMED"
        consumed_at = _threshold_reached_at(
            after_first_seen,
            positions,
            cross_through.tolist(),
            threshold_kind="cross_through",
        )
        consumption_reason = f"cross_through_count>={MAX_CROSS_THROUGH_COUNT}"
    elif not is_broad and alternating_count >= MAX_ALTERNATING_CLOSE_COUNT:
        consumption_status = "CHOPPED_THROUGH"
        consumed_at = _threshold_reached_at(
            after_first_seen,
            positions,
            cross_through.tolist(),
            threshold_kind="alternating_close",
        )
        consumption_reason = f"alternating_close_count>={MAX_ALTERNATING_CLOSE_COUNT}"
    elif not is_broad and bars_inside >= MAX_BARS_INSIDE_ZONE_LIFETIME:
        consumption_status = "CHOPPED_THROUGH"
        consumed_at = _threshold_reached_at(
            after_first_seen,
            positions,
            cross_through.tolist(),
            threshold_kind="inside_bars",
        )
        consumption_reason = f"bars_inside_zone_lifetime>={MAX_BARS_INSIDE_ZONE_LIFETIME}"
    elif current_status == "CROSSED_UNCLASSIFIED" or int(float(row.get("cross_count", 0) or 0)) > 0:
        consumption_status = "SWEPT_ONCE"
    elif current_status == "TOUCHED" or int(float(row.get("touch_count", 0) or 0)) > 0 or bars_inside > 0:
        consumption_status = "TESTED"

    zone_behavior_state = _zone_behavior_state(
        row=row,
        is_broad=is_broad,
        clean_reaction_at=clean_reaction_at,
        accepted_above_at=accepted_above_at,
        accepted_below_at=accepted_below_at,
        failed_acceptance_count=failed_acceptance_count,
        rejection_without_sweep_count=rejection_without_sweep_count,
        drift_away_confirmed_at=drift_away_confirmed_at,
        resweep_count=resweep_count,
        true_broad_chop=true_broad_chop,
    )

    return {
        "consumption_status": consumption_status,
        "cross_through_count": cross_through_count,
        "close_above_count": close_above_count,
        "close_below_count": close_below_count,
        "alternating_close_count": alternating_count,
        "bars_inside_zone_lifetime": bars_inside,
        "last_clean_reaction_at": clean_reaction_at,
        "consumed_at": consumed_at,
        "consumption_reason": consumption_reason,
        "zone_outer_lower": lower,
        "zone_outer_upper": upper,
        "zone_core_lower": core_lower,
        "zone_core_upper": core_upper,
        "zone_origin_start": row.get("zone_origin_start", "") or row.get("first_seen_at", ""),
        "zone_origin_end": row.get("zone_origin_end", "") or row.get("last_seen_at", ""),
        "first_sweep_at": first_sweep_at,
        "resweep_count": resweep_count,
        "failed_acceptance_count": failed_acceptance_count,
        "rejection_without_sweep_count": rejection_without_sweep_count,
        "drift_away_confirmed_at": drift_away_confirmed_at,
        "accepted_above_at": accepted_above_at,
        "accepted_below_at": accepted_below_at,
        "structural_zone_mode": structural_zone_mode,
        "zone_behavior_state": zone_behavior_state,
        "htf_lifecycle_status": _lifecycle_status_from_values(
            row=row,
            has_htf=has_htf,
            htf_sweep_count=htf_sweep_count,
            htf_close_through_count=htf_close_through_count,
            htf_acceptance_count=htf_acceptance_count,
            history_context_incomplete=history_context_incomplete,
            first_sweep_at=first_sweep_at,
            close_above_count=close_above_count,
            close_below_count=close_below_count,
            accepted_above_at=accepted_above_at,
            accepted_below_at=accepted_below_at,
        ),
        "m1_interaction_count": m1_interaction_count,
        "htf_sweep_count": htf_sweep_count,
        "htf_close_through_count": htf_close_through_count,
        "htf_acceptance_count": htf_acceptance_count,
        "history_context_start": history_context_start,
        "history_context_incomplete": _bool_text(history_context_incomplete),
        "sweep_importance_class": _sweep_importance_class_from_values(
            row=row,
            has_htf=has_htf,
            htf_sweep_count=htf_sweep_count,
            first_sweep_at=first_sweep_at,
            structural_zone_mode=structural_zone_mode,
        ),
    }


def _alternating_close_count(positions: list[str]) -> int:
    previous = ""
    transitions = 0
    for position in positions:
        if position == "INSIDE":
            continue
        if previous and position != previous:
            transitions += 1
        previous = position
    return transitions


def _threshold_reached_at(
    frame: pd.DataFrame,
    positions: list[str],
    cross_through: list[bool],
    *,
    threshold_kind: str,
) -> str:
    cross_count = 0
    alternating = 0
    inside_count = 0
    previous = ""
    for idx, (_, row) in enumerate(frame.iterrows()):
        position = positions[idx]
        if cross_through[idx]:
            cross_count += 1
        if position == "INSIDE":
            inside_count += 1
        elif previous and position != previous:
            alternating += 1
        if position != "INSIDE":
            previous = position
        if threshold_kind == "cross_through" and cross_count >= MAX_CROSS_THROUGH_COUNT:
            return _format_ts(row["Timestamp"])
        if threshold_kind == "alternating_close" and alternating >= MAX_ALTERNATING_CLOSE_COUNT:
            return _format_ts(row["Timestamp"])
        if threshold_kind == "inside_bars" and inside_count >= MAX_BARS_INSIDE_ZONE_LIFETIME:
            return _format_ts(row["Timestamp"])
    return _format_ts(frame.iloc[-1]["Timestamp"])


def _sweep_transition_timestamps(
    row: dict[str, object], frame: pd.DataFrame, lower: float, upper: float
) -> list[str]:
    if str(row.get("side", "")) == "BUY_SIDE":
        swept = pd.to_numeric(frame["HiPrice"], errors="coerce") > upper
    else:
        swept = pd.to_numeric(frame["LowPrice"], errors="coerce") < lower
    timestamps: list[str] = []
    previous = False
    for is_swept, (_, candle) in zip(swept.tolist(), frame.iterrows()):
        if is_swept and not previous:
            timestamps.append(_format_ts(candle["Timestamp"]))
        previous = bool(is_swept)
    return timestamps


def _m1_interaction_count(
    row: dict[str, object], frame: pd.DataFrame, lower: float, upper: float
) -> int:
    highs = pd.to_numeric(frame["HiPrice"], errors="coerce")
    lows = pd.to_numeric(frame["LowPrice"], errors="coerce")
    if str(row.get("side", "")) == "BUY_SIDE":
        interacted = highs >= lower
    else:
        interacted = lows <= upper
    current_count = int(interacted.sum())
    previous_count = int(float(row.get("m1_interaction_count", 0) or 0))
    return max(previous_count, current_count)


def _htf_lifecycle_metrics(
    row: dict[str, object], feed: pd.DataFrame, lower: float, upper: float
) -> dict[str, object]:
    previous_sweeps = int(float(row.get("htf_sweep_count", 0) or 0))
    previous_close_through = int(float(row.get("htf_close_through_count", 0) or 0))
    previous_acceptance = int(float(row.get("htf_acceptance_count", 0) or 0))
    history_context_start = str(row.get("history_context_start", "") or row.get("first_seen_at", "") or "")
    if not _has_htf_source(row):
        return {
            "htf_sweep_count": previous_sweeps,
            "htf_close_through_count": previous_close_through,
            "htf_acceptance_count": previous_acceptance,
            "history_context_start": history_context_start,
            "history_context_incomplete": _bool_text(row.get("history_context_incomplete", False)),
        }

    metric_timeframe = _htf_metric_timeframe(row)
    try:
        htf_frame = aggregate_timeframe(feed, metric_timeframe)
    except Exception:
        htf_frame = pd.DataFrame()
    if htf_frame.empty:
        return {
            "htf_sweep_count": previous_sweeps,
            "htf_close_through_count": previous_close_through,
            "htf_acceptance_count": previous_acceptance,
            "history_context_start": history_context_start,
            "history_context_incomplete": "true",
        }

    start_text = str(row.get("htf_confirmation_timestamp", "") or row.get("first_seen_at", ""))
    if start_text:
        htf_frame = htf_frame[htf_frame["Timestamp"] >= pd.Timestamp(start_text)]
    if htf_frame.empty:
        return {
            "htf_sweep_count": previous_sweeps,
            "htf_close_through_count": previous_close_through,
            "htf_acceptance_count": previous_acceptance,
            "history_context_start": history_context_start or _format_ts(feed["Timestamp"].min()),
            "history_context_incomplete": _bool_text(row.get("history_context_incomplete", False)),
        }

    if str(row.get("side", "")) == "BUY_SIDE":
        swept = pd.to_numeric(htf_frame["HiPrice"], errors="coerce") > upper
        closed_through = pd.to_numeric(htf_frame["ClosePrice"], errors="coerce") > upper
    else:
        swept = pd.to_numeric(htf_frame["LowPrice"], errors="coerce") < lower
        closed_through = pd.to_numeric(htf_frame["ClosePrice"], errors="coerce") < lower
    htf_sweeps = _transition_count(swept.tolist())
    htf_close_through = int(closed_through.sum())
    htf_acceptance = _accepted_run_count(closed_through.tolist())
    return {
        "htf_sweep_count": max(previous_sweeps, htf_sweeps),
        "htf_close_through_count": max(previous_close_through, htf_close_through),
        "htf_acceptance_count": max(previous_acceptance, htf_acceptance),
        "history_context_start": history_context_start or _format_ts(htf_frame["source_start"].min()),
        "history_context_incomplete": _bool_text(row.get("history_context_incomplete", False)),
    }


def _transition_count(flags: list[bool]) -> int:
    count = 0
    previous = False
    for flag in flags:
        if flag and not previous:
            count += 1
        previous = bool(flag)
    return count


def _accepted_run_count(flags: list[bool]) -> int:
    accepted = 0
    run = 0
    counted_run = False
    for flag in flags:
        if flag:
            run += 1
            if run >= ACCEPTANCE_CLOSE_BARS and not counted_run:
                accepted += 1
                counted_run = True
        else:
            run = 0
            counted_run = False
    return accepted


def _consecutive_threshold_at(frame: pd.DataFrame, flags: list[bool]) -> str:
    count = 0
    for is_flagged, (_, candle) in zip(flags, frame.iterrows()):
        count = count + 1 if is_flagged else 0
        if count >= ACCEPTANCE_CLOSE_BARS:
            return _format_ts(candle["Timestamp"])
    return ""


def _failed_acceptance_count(
    row: dict[str, object],
    frame: pd.DataFrame,
    close_above: list[bool],
    close_below: list[bool],
    lower: float,
    upper: float,
) -> int:
    closes = pd.to_numeric(frame["ClosePrice"], errors="coerce").tolist()
    if str(row.get("side", "")) == "BUY_SIDE":
        attempt_flags = close_above
        failed_return = lambda close: float(close) <= upper
    else:
        attempt_flags = close_below
        failed_return = lambda close: float(close) >= lower

    failures = 0
    idx = 0
    while idx < len(attempt_flags):
        if not attempt_flags[idx]:
            idx += 1
            continue
        run_start = idx
        while idx < len(attempt_flags) and attempt_flags[idx]:
            idx += 1
        run_length = idx - run_start
        if run_length >= ACCEPTANCE_CLOSE_BARS:
            continue
        lookahead = closes[idx : idx + ACCEPTANCE_CLOSE_BARS]
        if any(failed_return(close) for close in lookahead):
            failures += 1
    return failures


def _rejection_without_sweep_count(
    row: dict[str, object],
    frame: pd.DataFrame,
    lower: float,
    upper: float,
    core_lower: float,
    core_upper: float,
) -> int:
    closes = pd.to_numeric(frame["ClosePrice"], errors="coerce")
    highs = pd.to_numeric(frame["HiPrice"], errors="coerce")
    lows = pd.to_numeric(frame["LowPrice"], errors="coerce")
    if str(row.get("side", "")) == "BUY_SIDE":
        approached_without_sweep = (highs >= core_lower) & (highs <= upper)
        away = closes < core_lower
    else:
        approached_without_sweep = (lows <= core_upper) & (lows >= lower)
        away = closes > core_upper
    count = 0
    pending = False
    for approached, moved_away in zip(approached_without_sweep.tolist(), away.tolist()):
        if approached:
            pending = True
        elif pending and moved_away:
            count += 1
            pending = False
    return count


def _drift_away_confirmed_at(
    row: dict[str, object],
    frame: pd.DataFrame,
    first_sweep_at: str,
    failed_acceptance_count: int,
    lower: float,
    upper: float,
    core_lower: float,
    core_upper: float,
) -> str:
    if not first_sweep_at and failed_acceptance_count <= 0:
        return ""
    start = pd.Timestamp(first_sweep_at) if first_sweep_at else pd.Timestamp(frame.iloc[0]["Timestamp"])
    post = frame[frame["Timestamp"] >= start]
    closes = pd.to_numeric(post["ClosePrice"], errors="coerce")
    if str(row.get("side", "")) == "BUY_SIDE":
        drift = closes < min(core_lower, lower)
    else:
        drift = closes > max(core_upper, upper)
    found = post[drift]
    return "" if found.empty else _format_ts(found.iloc[0]["Timestamp"])


def _zone_behavior_state(
    *,
    row: dict[str, object],
    is_broad: bool,
    clean_reaction_at: str,
    accepted_above_at: str,
    accepted_below_at: str,
    failed_acceptance_count: int,
    rejection_without_sweep_count: int,
    drift_away_confirmed_at: str,
    resweep_count: int,
    true_broad_chop: bool,
) -> str:
    if not is_broad or true_broad_chop:
        return "NONE"
    if accepted_above_at and not accepted_below_at:
        return "ACCEPTED_ABOVE_ZONE"
    if accepted_below_at and not accepted_above_at:
        return "ACCEPTED_BELOW_ZONE"
    if drift_away_confirmed_at:
        return "DRIFT_AWAY_FROM_ZONE"
    if failed_acceptance_count >= 2:
        return "DISTRIBUTION_CANDIDATE"
    if failed_acceptance_count >= 1:
        return "FAILED_ACCEPTANCE"
    if rejection_without_sweep_count >= 1 or clean_reaction_at:
        return "REJECTION_FROM_ZONE"
    if resweep_count >= 1:
        return "REPEATED_SWEEP_ZONE"
    if str(row.get("consumption_status", "")) == "SWEPT_ONCE":
        return "RETEST_OF_SWEPT_ZONE"
    return "NONE"


def _clean_reaction_at(row: dict[str, object], feed: pd.DataFrame) -> str:
    if str(row.get("status", "")) in {"REACTED", "FLIPPED_REACTION_ZONE"}:
        return str(row.get("last_touch_at", "") or row.get("last_cross_at", ""))

    lower = float(row.get("zone_outer_lower", row["price_lower"]) or row["price_lower"])
    upper = float(row.get("zone_outer_upper", row["price_upper"]) or row["price_upper"])
    if str(row["side"]) == "BUY_SIDE":
        crossed = feed[feed["HiPrice"].astype(float) > upper]
        away_predicate = lambda close: float(close) < lower
    else:
        crossed = feed[feed["LowPrice"].astype(float) < lower]
        away_predicate = lambda close: float(close) > upper
    if crossed.empty:
        return ""

    cross_ts = pd.Timestamp(crossed.iloc[0]["Timestamp"])
    post = feed[feed["Timestamp"] >= cross_ts].head(REACTION_LOOKAHEAD_BARS_FOR_LIFECYCLE + 1)
    inside_seen = False
    for _, candle in post.iterrows():
        close = float(candle["ClosePrice"])
        if lower <= close <= upper:
            inside_seen = True
        if inside_seen and away_predicate(close):
            return _format_ts(candle["Timestamp"])
    return ""


def _is_active_forward(row: dict[str, object] | pd.Series) -> bool:
    role = str(row.get("active_forward_role", "") or "FRESH_LIQUIDITY")
    if role in {"AUDIT_ONLY", "INACTIVE"} | LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES:
        return False
    if role == "FRESH_LIQUIDITY" and _has_m15_source(row):
        return False
    if role == "FRESH_LIQUIDITY" and local_session_context_role(row):
        return False
    status = str(row.get("status", ""))
    mode = str(row.get("structural_zone_mode", ""))
    status_ok = status in ACTIVE_FORWARD_STATUSES or (
        status == "CROSSED_UNCLASSIFIED"
        and mode in BROAD_STRUCTURAL_MODES
        and role in NON_FRESH_ACTIVE_ROLES
    )
    if not status_ok:
        return False
    if str(row.get("precision_status", "")) == PRECISION_TOO_WIDE:
        return False
    if str(row.get("consumption_status", "")) in INACTIVE_CONSUMPTION_STATUSES:
        return False
    flag = row.get("active_forward", True)
    if str(flag).strip() == "":
        return True
    return _bool_value(flag)


def _active_forward_mask(registry: pd.DataFrame) -> pd.Series:
    if registry.empty:
        return pd.Series(dtype=bool)
    return registry.apply(_is_active_forward, axis=1)


def _apply_expiry(registry: pd.DataFrame) -> pd.DataFrame:
    registry = _normalize_registry(registry)
    rows = []
    for row in registry.to_dict("records"):
        if (
            row["status"] in CARRY_FORWARD_STATUSES
            and int(float(row["age_days"])) > MAX_ZONE_AGE_DAYS
            and not _expiry_exempt(row)
        ):
            row = row.copy()
            row["status"] = "EXPIRED"
            row["consumption_status"] = "EXPIRED"
            row["active_forward"] = "false"
            row["active_forward_role"] = "INACTIVE"
            row["consumed_at"] = row.get("last_updated_at", "") or row.get("last_seen_at", "")
            row["invalidation_reason"] = MAX_ZONE_AGE_REASON
            row["consumption_reason"] = MAX_ZONE_AGE_REASON
        row["active_forward_role"] = _active_forward_role(row)
        row["active_forward"] = _bool_text(_is_active_forward(row))
        rows.append(row)
    return _normalize_registry(pd.DataFrame(rows, columns=REGISTRY_COLUMNS))


def _expiry_exempt(row: dict[str, object]) -> bool:
    zone_type = str(row["zone_type"])
    source_timeframes = set(str(row["source_timeframes"]).split("|"))
    confidence_score = int(float(row["confidence_score"]))
    precision_status = _row_precision_status(row)
    if precision_status in {PRECISION_LOW, PRECISION_TOO_WIDE}:
        return False
    if _has_explicit_htf_lineage(row):
        return True
    if row["confidence_tier"] == "HIGH" and "H4" in source_timeframes:
        return True
    if "PDH" in zone_type or "PDL" in zone_type:
        return True
    if "CLUSTERED" in zone_type and confidence_score >= 70:
        return True
    return False


def _normalize_registry(registry: pd.DataFrame | None) -> pd.DataFrame:
    if registry is None or registry.empty:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    frame = registry.copy()
    for column in REGISTRY_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    frame = frame[REGISTRY_COLUMNS]
    for column in [
        "price_lower",
        "price_upper",
        "price_mid",
        "htf_origin_price",
        "confidence_score",
        "age_bars",
        "age_days",
        "touch_count",
        "cross_count",
        "cross_through_count",
        "close_above_count",
        "close_below_count",
        "alternating_close_count",
        "bars_inside_zone_lifetime",
        "zone_outer_lower",
        "zone_outer_upper",
        "zone_core_lower",
        "zone_core_upper",
        "resweep_count",
        "failed_acceptance_count",
        "rejection_without_sweep_count",
        "m1_interaction_count",
        "htf_sweep_count",
        "htf_close_through_count",
        "htf_acceptance_count",
        "active_days",
        "source_level_count",
        "source_ref_count",
        "cluster_member_count",
        "zone_width",
        "zone_width_pct",
    ]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
    text_columns = [column for column in REGISTRY_COLUMNS if column not in frame.select_dtypes("number").columns]
    for column in text_columns:
        frame[column] = frame[column].fillna("").astype(str)
    blank_consumption = frame["consumption_status"].astype(str).str.len().eq(0)
    frame.loc[blank_consumption, "consumption_status"] = "FRESH"
    for target, fallback in [
        ("zone_outer_lower", "price_lower"),
        ("zone_outer_upper", "price_upper"),
        ("zone_core_lower", "price_lower"),
        ("zone_core_upper", "price_upper"),
    ]:
        blank = pd.to_numeric(frame[target], errors="coerce").fillna(0).eq(0)
        frame.loc[blank, target] = frame.loc[blank, fallback]
    blank_origin_start = frame["zone_origin_start"].astype(str).str.len().eq(0)
    frame.loc[blank_origin_start, "zone_origin_start"] = frame.loc[blank_origin_start, "first_seen_at"]
    blank_origin_end = frame["zone_origin_end"].astype(str).str.len().eq(0)
    frame.loc[blank_origin_end, "zone_origin_end"] = frame.loc[blank_origin_end, "last_seen_at"]
    blank_mode = frame["structural_zone_mode"].astype(str).str.len().eq(0)
    frame.loc[blank_mode, "structural_zone_mode"] = frame.loc[blank_mode].apply(
        _structural_zone_mode_from_row,
        axis=1,
    )
    blank_primary = frame["source_timeframe_primary"].astype(str).str.len().eq(0)
    frame.loc[blank_primary, "source_timeframe_primary"] = frame.loc[blank_primary].apply(
        _source_timeframe_primary_from_row,
        axis=1,
    )
    blank_htf_status = frame["htf_lifecycle_status"].astype(str).str.len().eq(0)
    frame.loc[blank_htf_status, "htf_lifecycle_status"] = frame.loc[blank_htf_status].apply(
        _lifecycle_status_from_row,
        axis=1,
    )
    blank_history_start = frame["history_context_start"].astype(str).str.len().eq(0)
    frame.loc[blank_history_start, "history_context_start"] = frame.loc[
        blank_history_start, "first_seen_at"
    ]
    frame["history_context_incomplete"] = frame["history_context_incomplete"].map(_bool_text)
    blank_importance = frame["sweep_importance_class"].astype(str).str.len().eq(0)
    frame.loc[blank_importance, "sweep_importance_class"] = frame.loc[blank_importance].apply(
        _sweep_importance_class_from_row,
        axis=1,
    )
    blank_behavior = frame["zone_behavior_state"].astype(str).str.len().eq(0)
    frame.loc[blank_behavior, "zone_behavior_state"] = "NONE"
    blank_role = frame["active_forward_role"].astype(str).str.len().eq(0)
    frame.loc[blank_role, "active_forward_role"] = frame.loc[blank_role].apply(
        _active_forward_role,
        axis=1,
    )
    blank_active_forward = frame["active_forward"].astype(str).str.len().eq(0)
    frame.loc[blank_active_forward, "active_forward"] = frame.loc[blank_active_forward].apply(
        lambda row: _bool_text(_is_active_forward(row)),
        axis=1,
    )
    frame["active_forward"] = frame["active_forward"].map(_bool_text)
    if "precision_status" in frame.columns:
        blank_precision = frame["precision_status"].astype(str).str.len().eq(0)
        frame.loc[blank_precision, "precision_status"] = frame.loc[blank_precision].apply(
            lambda row: precision_status_for_width(
                _zone_width_pct(
                    float(row["price_lower"]),
                    float(row["price_upper"]),
                    float(row["price_mid"]),
                )
            ),
            axis=1,
        )
    if "source_ref_count" in frame.columns and "source_level_count" in frame.columns:
        missing_ref_count = pd.to_numeric(frame["source_ref_count"], errors="coerce").fillna(0).eq(0)
        frame.loc[missing_ref_count, "source_ref_count"] = frame.loc[
            missing_ref_count, "source_level_count"
        ]
    return frame[REGISTRY_COLUMNS]


def _concat_registry_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    populated = [frame for frame in frames if frame is not None and not frame.empty]
    if not populated:
        return pd.DataFrame(columns=REGISTRY_COLUMNS)
    return pd.concat(populated, ignore_index=True)


def _next_zone_index(registry: pd.DataFrame) -> int:
    max_index = 0
    for zone_id in registry.get("zone_id", []):
        try:
            max_index = max(max_index, int(str(zone_id).split("_")[-1]))
        except ValueError:
            continue
    return max_index + 1


def _merge_tolerance(rows: list[dict[str, object]]) -> float:
    mids = [float(row["price_mid"]) for row in rows]
    reference = sum(mids) / len(mids) if mids else 0
    return max(10.0, reference * 0.0005)


def _registry_merged_zone_type(side: str, source_zone_types: list[str]) -> str:
    if len(source_zone_types) == 1:
        return source_zone_types[0]
    for pattern_zone_type in [
        "DOUBLE_TOP_LIQUIDITY_ZONE",
        "DOUBLE_BOTTOM_LIQUIDITY_ZONE",
        "HNS_HEAD_LIQUIDITY_ZONE",
        "HNS_SHOULDER_LIQUIDITY_ZONE",
        "HNS_NECKLINE_ZONE",
        "INVERSE_HNS_HEAD_LIQUIDITY_ZONE",
        "INVERSE_HNS_SHOULDER_LIQUIDITY_ZONE",
        "INVERSE_HNS_NECKLINE_ZONE",
    ]:
        if pattern_zone_type in source_zone_types:
            return pattern_zone_type
    if side == "BUY_SIDE":
        return "CLUSTERED_BUY_SIDE_ZONE"
    return "CLUSTERED_SELL_SIDE_ZONE"


def _merged_confidence_score(
    rows: list[dict[str, object]], source_timeframes: str, source_zone_types: list[str]
) -> int:
    return int(
        _merged_confidence_components(rows, source_timeframes, source_zone_types)[
            "final_confidence_score"
        ]
    )


def _merged_confidence_components(
    rows: list[dict[str, object]], source_timeframes: str, source_zone_types: list[str]
) -> dict[str, object]:
    prior_score = max(int(float(row["confidence_score"])) for row in rows)
    bounded_prior_score = min(prior_score, 88)
    source_count = len(_pipe_union(row["source_level_ids"] for row in rows).split("|"))
    max_known_source_count = max(
        len([part for part in str(row["source_level_ids"]).split("|") if part])
        for row in rows
    )
    fresh_source_count = max(source_count - max_known_source_count, 0)
    source_families = _registry_source_families(source_timeframes, source_zone_types)
    source_diversity_bonus = min(max(len(source_families) - 1, 0) * 2, 6)
    fresh_source_bonus = min(fresh_source_count * 3, 6)
    raw_source_count_bonus = fresh_source_bonus
    source_count_bonus = fresh_source_bonus
    h4_component = 2 if "H4" in source_timeframes and fresh_source_count > 0 else 0
    pdh_pdl_component = (
        4
        if any("PDH" in zone_type or "PDL" in zone_type for zone_type in source_zone_types)
        else 0
    )
    width_penalty = _width_penalty(
        zone_width_pct := _zone_width_pct(
            min(float(row["price_lower"]) for row in rows),
            max(float(row["price_upper"]) for row in rows),
            (
                min(float(row["price_lower"]) for row in rows)
                + max(float(row["price_upper"]) for row in rows)
            )
            / 2,
        )
    )
    carry_forward_decay_or_penalty = _carry_forward_decay_or_penalty(
        rows=rows,
        fresh_source_count=fresh_source_count,
        source_families=source_families,
    )
    data_quality_penalty = (
        -5 if _quality_values(row["data_quality"] for row in rows) != "RAW" else 0
    )
    pre_clamp_score = (
        bounded_prior_score
        + source_diversity_bonus
        + fresh_source_bonus
        + h4_component
        + pdh_pdl_component
        + width_penalty
        + carry_forward_decay_or_penalty
        + data_quality_penalty
    )
    final_score = max(0, min(100, pre_clamp_score))
    precision_status = precision_status_for_width(zone_width_pct)
    return {
        "base_score": 0,
        "timeframe_score": h4_component,
        "timeframe_component_total": h4_component,
        "h1_component": None,
        "h4_component": h4_component,
        "session_component": None,
        "pdh_pdl_component": pdh_pdl_component,
        "equal_level_component": None,
        "source_diversity_bonus": source_diversity_bonus,
        "raw_source_count_bonus": raw_source_count_bonus,
        "source_count_bonus": source_count_bonus,
        "cluster_bonus": 0,
        "touch_bonus": None,
        "width_penalty": width_penalty,
        "precision_status": precision_status,
        "hard_wide_zone_width_pct": HARD_WIDE_ZONE_WIDTH_PCT,
        "data_quality_penalty": data_quality_penalty,
        "carry_forward_decay_or_penalty": carry_forward_decay_or_penalty,
        "carry_forward_prior_score": prior_score,
        "bounded_prior_score": bounded_prior_score,
        "fresh_source_count": fresh_source_count,
        "pre_clamp_score": pre_clamp_score,
        "final_confidence_score": final_score,
        "confidence_tier": _confidence_tier(final_score),
        "source_level_count": source_count,
        "cluster_member_count": len(rows),
        "source_timeframes": source_timeframes,
        "source_families": "|".join(sorted(source_families)),
        "source_zone_types": "|".join(source_zone_types),
        "merged_from_zone_ids": sorted(str(row["zone_id"]) for row in rows),
        "registry_status_before": "|".join(sorted({str(row["status"]) for row in rows})),
        "registry_status_after": "post_merge_pre_lifecycle",
        "instrumentation_limitations": (
            "registry merge uses bounded prior confidence and fresh-source bonuses only; "
            "post-event observation metrics are not used"
        ),
    }


def _registry_source_families(source_timeframes: str, source_zone_types: list[str]) -> set[str]:
    timeframes = {part for part in str(source_timeframes).split("|") if part}
    zone_type_text = "|".join(source_zone_types)
    families: set[str] = set()
    for timeframe in ["H4", "H1", "M15", "SESSION"]:
        if timeframe in timeframes:
            families.add(timeframe)
    if "PDH" in zone_type_text or "PDL" in zone_type_text:
        families.add("PDH_PDL")
    if "EQUAL_HIGHS" in zone_type_text or "EQUAL_LOWS" in zone_type_text:
        families.add("EQUAL_LEVEL")
    return families


def _carry_forward_decay_or_penalty(
    *, rows: list[dict[str, object]], fresh_source_count: int, source_families: set[str]
) -> int:
    max_active_days = max(int(float(row.get("active_days", 1) or 1)) for row in rows)
    if fresh_source_count > 0:
        return 0
    decay = max(max_active_days - 3, 0) * 2
    cap = 6 if source_families & {"H4", "PDH_PDL"} else 10
    return -min(decay, cap)


def _width_penalty(zone_width_pct: float) -> int:
    if zone_width_pct >= 0.50:
        return -12
    if zone_width_pct >= 0.25:
        return -6
    return 0


def _row_precision_status(row: dict[str, object]) -> str:
    precision_status = str(row.get("precision_status", "") or "")
    if precision_status:
        return precision_status
    return precision_status_for_width(
        _zone_width_pct(
            float(row.get("price_lower", 0) or 0),
            float(row.get("price_upper", 0) or 0),
            float(row.get("price_mid", 0) or 0),
        )
    )


def _zone_width_pct(price_lower: float, price_upper: float, price_mid: float) -> float:
    if price_mid <= 0:
        return 0.0
    return (price_upper - price_lower) / price_mid * 100.0


def _instrumentation_from_row(row) -> dict[str, object]:
    return {column: row[column] if column in row else "" for column in SCORE_INSTRUMENTATION_COLUMNS}


def _pipe_union(values) -> str:
    parts: set[str] = set()
    for value in values:
        parts.update(part for part in str(value).split("|") if part)
    return "|".join(sorted(parts))


def _merged_consumption_status(rows: list[dict[str, object]]) -> str:
    if any(_has_htf_source(row) for row in rows):
        statuses = [
            str(row.get("consumption_status", "") or "FRESH")
            for row in rows
            if _has_htf_source(row)
        ]
        for status in ["SWEPT_ONCE", "REACTED", "TESTED"]:
            if status in statuses:
                return status
        return "FRESH"
    statuses = [str(row.get("consumption_status", "") or "FRESH") for row in rows]
    for status in ["CONSUMED", "CHOPPED_THROUGH", "EXPIRED", "REACTED", "SWEPT_ONCE", "TESTED"]:
        if status in statuses:
            return status
    return "FRESH"


def _structural_zone_mode_from_row(row: dict[str, object] | pd.Series) -> str:
    existing = str(row.get("structural_zone_mode", "") or "")
    if existing:
        return existing
    if _has_htf_source(row):
        return "HTF_STRUCTURAL_LEVEL"
    zone_type = str(row.get("zone_type", ""))
    if any(marker in zone_type for marker in ["DOUBLE_", "HNS_", "NECKLINE"]):
        return "PATTERN_DERIVED_ZONE"
    source_ids = [part for part in str(row.get("source_level_ids", "")).split("|") if part]
    source_timeframes = set(str(row.get("source_timeframes", "")).split("|"))
    if (
        len(source_ids) > 1
        or "CLUSTER" in source_timeframes
        or zone_type.startswith("CLUSTERED_")
        or zone_type in {"EQUAL_HIGHS_ZONE", "EQUAL_LOWS_ZONE"}
        or float(row.get("zone_width_pct", 0) or 0) >= 0.25
    ):
        return "BROAD_STRUCTURAL_ZONE"
    return "THIN_LEVEL"


def _merged_structural_zone_mode(rows: list[dict[str, object]], source_zone_types: list[str]) -> str:
    modes = {_structural_zone_mode_from_row(row) for row in rows}
    if any("DOUBLE_" in zone_type or "HNS_" in zone_type or "NECKLINE" in zone_type for zone_type in source_zone_types):
        return "PATTERN_DERIVED_ZONE"
    if "PATTERN_DERIVED_ZONE" in modes:
        return "PATTERN_DERIVED_ZONE"
    if len(rows) > 1 or "BROAD_STRUCTURAL_ZONE" in modes:
        return "BROAD_STRUCTURAL_ZONE"
    if "HTF_STRUCTURAL_LEVEL" in modes:
        return "HTF_STRUCTURAL_LEVEL"
    if "REACTION_ZONE" in modes:
        return "REACTION_ZONE"
    if "THIN_LEVEL" in modes:
        return "THIN_LEVEL"
    return "UNKNOWN"


def _merged_zone_behavior_state(rows: list[dict[str, object]]) -> str:
    states = [str(row.get("zone_behavior_state", "") or "NONE") for row in rows]
    for state in [
        "ACCEPTED_ABOVE_ZONE",
        "ACCEPTED_BELOW_ZONE",
        "DRIFT_AWAY_FROM_ZONE",
        "DISTRIBUTION_CANDIDATE",
        "FAILED_ACCEPTANCE",
        "REJECTION_FROM_ZONE",
        "REPEATED_SWEEP_ZONE",
        "RETEST_OF_SWEPT_ZONE",
    ]:
        if state in states:
            return state
    return "NONE"


def _merged_active_forward_role(rows: list[dict[str, object]]) -> str:
    roles = [str(row.get("active_forward_role", "") or "FRESH_LIQUIDITY") for row in rows]
    if any(_has_htf_source(row) for row in rows):
        for role in ["REACTION_ZONE", "RETEST_ZONE", "DISTRIBUTION_ZONE", "AUDIT_ONLY"]:
            if role in roles:
                return role
        return "FRESH_LIQUIDITY"
    if any(_has_m15_source(row) for row in rows):
        for role in ["M15_CONSUMED", "M15_REACTION_ZONE", "M15_STRUCTURE_SWEEP", "M15_MINIMUM_STRUCTURE"]:
            if role in roles:
                return role
        return "M15_MINIMUM_STRUCTURE"
    for role in [
        "INACTIVE",
        "AUDIT_ONLY",
        "DISTRIBUTION_ZONE",
        "REACTION_ZONE",
        "RETEST_ZONE",
        "SESSION_CHOPPED",
        "LOCAL_REPEATED_INTERACTION",
        "LOCAL_NOISY_ZONE",
        "LOCAL_SESSION_CONTEXT",
    ]:
        if role in roles:
            return role
    return "FRESH_LIQUIDITY"


def _active_forward_role(row: dict[str, object] | pd.Series) -> str:
    if str(row.get("status", "")) in INACTIVE_STATUSES:
        return "INACTIVE"
    if str(row.get("precision_status", "")) == PRECISION_TOO_WIDE:
        return "INACTIVE"
    if str(row.get("consumption_status", "")) in INACTIVE_CONSUMPTION_STATUSES:
        return "INACTIVE"
    local_context_role = local_session_context_role(row)
    if local_context_role:
        return local_context_role
    if _has_m15_source(row):
        return _m15_active_forward_role(row)
    state = str(row.get("zone_behavior_state", "") or "NONE")
    if state in {"DISTRIBUTION_CANDIDATE", "FAILED_ACCEPTANCE"}:
        return "DISTRIBUTION_ZONE"
    if state in {"REJECTION_FROM_ZONE", "DRIFT_AWAY_FROM_ZONE"}:
        return "REACTION_ZONE"
    if state in {"RETEST_OF_SWEPT_ZONE", "REPEATED_SWEEP_ZONE", "ACCEPTED_ABOVE_ZONE", "ACCEPTED_BELOW_ZONE"}:
        return "RETEST_ZONE"
    if str(row.get("status", "")) == "CROSSED_UNCLASSIFIED" and str(row.get("first_sweep_at", "") or ""):
        return "AUDIT_ONLY"
    return "FRESH_LIQUIDITY"


def _has_htf_source(row: dict[str, object] | pd.Series) -> bool:
    if str(row.get("htf_level_type", "") or ""):
        return True
    if str(row.get("source_timeframe_primary", "") or "") in {"H1", "H4"}:
        return True
    return bool({"H1", "H4"} & {part for part in str(row.get("source_timeframes", "") or "").split("|") if part})


def _has_m15_source(row: dict[str, object] | pd.Series) -> bool:
    if _has_htf_source(row):
        return False
    primary = str(row.get("source_timeframe_primary", "") or "")
    source_timeframes = {
        part for part in str(row.get("source_timeframes", "") or "").split("|") if part
    }
    zone_type = str(row.get("zone_type", "") or "")
    return primary == "M15" or "M15" in source_timeframes or zone_type.startswith("M15_")


def _m15_active_forward_role(row: dict[str, object] | pd.Series) -> str:
    if str(row.get("consumption_status", "")) in INACTIVE_CONSUMPTION_STATUSES:
        return "M15_CONSUMED"
    state = str(row.get("zone_behavior_state", "") or "NONE")
    if state in {"REJECTION_FROM_ZONE", "DRIFT_AWAY_FROM_ZONE", "DISTRIBUTION_CANDIDATE", "FAILED_ACCEPTANCE"}:
        return "M15_REACTION_ZONE"
    if str(row.get("first_sweep_at", "") or "") or str(row.get("consumption_status", "")) == "SWEPT_ONCE":
        return "M15_STRUCTURE_SWEEP"
    return "M15_MINIMUM_STRUCTURE"


def local_session_context_role(row: dict[str, object] | pd.Series) -> str:
    if not _is_local_session_context_source(row):
        return ""
    if _has_explicit_broad_behavior(row):
        return ""
    if str(row.get("consumption_status", "")) == "CHOPPED_THROUGH":
        return "SESSION_CHOPPED"

    resweep_count = int(float(row.get("resweep_count", 0) or 0))
    failed_acceptance_count = int(float(row.get("failed_acceptance_count", 0) or 0))
    m1_interaction_count = int(float(row.get("m1_interaction_count", 0) or 0))
    if resweep_count > 0 or failed_acceptance_count > 0:
        return "LOCAL_REPEATED_INTERACTION"
    if m1_interaction_count >= LOCAL_SESSION_HEAVY_M1_INTERACTION_COUNT:
        return "LOCAL_NOISY_ZONE"

    status = str(row.get("status", ""))
    sweep_class = str(row.get("sweep_importance_class", "") or "")
    if (
        str(row.get("first_sweep_at", "") or "")
        or status in {"REACTED", "CROSSED_UNCLASSIFIED"}
        or sweep_class == "LOCAL_SESSION_SWEEP"
    ):
        return "LOCAL_SESSION_CONTEXT"
    return ""


def _is_local_session_context_source(row: dict[str, object] | pd.Series) -> bool:
    if _has_htf_source(row):
        return False
    if _has_m15_source(row):
        return False
    primary = _source_timeframe_primary_from_row(row)
    source_timeframes = {
        part for part in str(row.get("source_timeframes", "") or "").split("|") if part
    }
    sweep_class = str(row.get("sweep_importance_class", "") or "")
    structural_mode = _structural_zone_mode_from_row(row)
    return (
        str(row.get("htf_lifecycle_status", "") or "") == "LOCAL_ONLY"
        or primary in {"SESSION", "PATTERN"}
        or "SESSION" in source_timeframes
        or sweep_class.startswith("LOCAL_SESSION")
        or structural_mode == "PATTERN_DERIVED_ZONE"
    )


def _has_explicit_broad_behavior(row: dict[str, object] | pd.Series) -> bool:
    mode = _structural_zone_mode_from_row(row)
    state = str(row.get("zone_behavior_state", "") or "NONE")
    return mode in BROAD_STRUCTURAL_MODES and state != "NONE"


def _has_explicit_htf_lineage(row: dict[str, object] | pd.Series) -> bool:
    if str(row.get("htf_level_type", "") or ""):
        return True
    if str(row.get("htf_origin_timestamp", "") or ""):
        return True
    return _float_value(row.get("htf_origin_price", 0)) != 0


def _htf_metric_timeframe(row: dict[str, object] | pd.Series) -> str:
    primary = str(row.get("source_timeframe_primary", "") or "")
    source_timeframes = {part for part in str(row.get("source_timeframes", "") or "").split("|") if part}
    htf_level_type = str(row.get("htf_level_type", "") or "")
    if primary == "H4" or "H4" in source_timeframes or htf_level_type.startswith("H4_"):
        return "H4"
    return "H1"


def _float_value(value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(parsed):
        return 0.0
    return parsed


def _source_timeframe_primary_from_row(row: dict[str, object] | pd.Series) -> str:
    existing = str(row.get("source_timeframe_primary", "") or "")
    if existing:
        return existing
    timeframes = {part for part in str(row.get("source_timeframes", "") or "").split("|") if part}
    for timeframe in ["H4", "H1", "M15", "SESSION", "PATTERN", "D1", "CLUSTER"]:
        if timeframe in timeframes:
            return timeframe
    return sorted(timeframes)[0] if timeframes else ""


def _merged_source_timeframe_primary(rows: list[dict[str, object]], source_timeframes: str) -> str:
    for timeframe in ["H4", "H1", "M15", "SESSION", "PATTERN", "D1", "CLUSTER"]:
        if any(_source_timeframe_primary_from_row(row) == timeframe for row in rows):
            return timeframe
        if timeframe in {part for part in source_timeframes.split("|") if part}:
            return timeframe
    values = [_source_timeframe_primary_from_row(row) for row in rows]
    values = [value for value in values if value]
    return values[0] if values else ""


def _merged_htf_text(rows: list[dict[str, object]], column: str) -> str:
    htf_rows = [row for row in rows if _has_htf_source(row)]
    candidates = htf_rows or rows
    values = [str(row.get(column, "") or "") for row in candidates]
    values = [value for value in values if value]
    if not values:
        return ""
    if column in {"htf_origin_timestamp", "htf_confirmation_timestamp"}:
        return min(values)
    return values[0]


def _merged_htf_price(rows: list[dict[str, object]], fallback: float) -> float:
    htf_rows = [row for row in rows if _has_htf_source(row)]
    values = [_float_value(row.get("htf_origin_price", 0)) for row in htf_rows]
    values = [value for value in values if value != 0]
    if not values:
        return fallback if htf_rows else 0.0
    return min(values, key=lambda value: abs(value - fallback))


def _htf_lifecycle_status(
    *,
    has_htf: bool,
    htf_sweep_count: int,
    htf_close_through_count: int,
    htf_acceptance_count: int,
    history_context_incomplete: bool,
) -> str:
    if not has_htf:
        return "LOCAL_ONLY"
    if history_context_incomplete:
        return "HTF_HISTORY_INCOMPLETE"
    if htf_acceptance_count > 0:
        return "HTF_ACCEPTED"
    if htf_close_through_count > 0:
        return "HTF_CLOSE_THROUGH"
    if htf_sweep_count > 0:
        return "HTF_SWEPT"
    return "HTF_ACTIVE"


def _lifecycle_status_from_row(row: dict[str, object] | pd.Series) -> str:
    return _lifecycle_status_from_values(
        row=row,
        has_htf=_has_htf_source(row),
        htf_sweep_count=int(float(row.get("htf_sweep_count", 0) or 0)),
        htf_close_through_count=int(float(row.get("htf_close_through_count", 0) or 0)),
        htf_acceptance_count=int(float(row.get("htf_acceptance_count", 0) or 0)),
        history_context_incomplete=_bool_value(row.get("history_context_incomplete", False)),
        first_sweep_at=str(row.get("first_sweep_at", "") or ""),
        close_above_count=int(float(row.get("close_above_count", 0) or 0)),
        close_below_count=int(float(row.get("close_below_count", 0) or 0)),
        accepted_above_at=str(row.get("accepted_above_at", "") or ""),
        accepted_below_at=str(row.get("accepted_below_at", "") or ""),
    )


def _lifecycle_status_from_values(
    *,
    row: dict[str, object] | pd.Series,
    has_htf: bool,
    htf_sweep_count: int,
    htf_close_through_count: int,
    htf_acceptance_count: int,
    history_context_incomplete: bool,
    first_sweep_at: str,
    close_above_count: int,
    close_below_count: int,
    accepted_above_at: str,
    accepted_below_at: str,
) -> str:
    if _has_m15_source(row):
        return _m15_lifecycle_status(
            row=row,
            first_sweep_at=first_sweep_at,
            close_above_count=close_above_count,
            close_below_count=close_below_count,
            accepted_above_at=accepted_above_at,
            accepted_below_at=accepted_below_at,
        )
    return _htf_lifecycle_status(
        has_htf=has_htf,
        htf_sweep_count=htf_sweep_count,
        htf_close_through_count=htf_close_through_count,
        htf_acceptance_count=htf_acceptance_count,
        history_context_incomplete=history_context_incomplete,
    )


def _m15_lifecycle_status(
    *,
    row: dict[str, object] | pd.Series,
    first_sweep_at: str,
    close_above_count: int,
    close_below_count: int,
    accepted_above_at: str,
    accepted_below_at: str,
) -> str:
    if str(row.get("side", "")) == "BUY_SIDE":
        close_through_count = close_above_count
        accepted_at = accepted_above_at
    else:
        close_through_count = close_below_count
        accepted_at = accepted_below_at
    if accepted_at:
        return "M15_ACCEPTED"
    if close_through_count > 0:
        return "M15_CLOSE_THROUGH"
    if first_sweep_at:
        return "M15_SWEPT"
    return "M15_ACTIVE"


def _merged_htf_lifecycle_status(rows: list[dict[str, object]]) -> str:
    values = [str(row.get("htf_lifecycle_status", "") or "") for row in rows]
    for status in [
        "HTF_ACCEPTED",
        "HTF_CLOSE_THROUGH",
        "HTF_SWEPT",
        "HTF_HISTORY_INCOMPLETE",
        "HTF_ACTIVE",
    ]:
        if status in values:
            return status
    for status in [
        "M15_ACCEPTED",
        "M15_CLOSE_THROUGH",
        "M15_SWEPT",
        "M15_ACTIVE",
    ]:
        if status in values:
            return status
    return "LOCAL_ONLY"


def _sweep_importance_class_from_row(row: dict[str, object] | pd.Series) -> str:
    return _sweep_importance_class_from_values(
        row=row,
        has_htf=_has_htf_source(row),
        htf_sweep_count=int(float(row.get("htf_sweep_count", 0) or 0)),
        first_sweep_at=str(row.get("first_sweep_at", "") or ""),
        structural_zone_mode=_structural_zone_mode_from_row(row),
    )


def _sweep_importance_class_from_values(
    *,
    row: dict[str, object] | pd.Series,
    has_htf: bool,
    htf_sweep_count: int,
    first_sweep_at: str,
    structural_zone_mode: str,
) -> str:
    primary = _source_timeframe_primary_from_row(row)
    swept = bool(first_sweep_at) or htf_sweep_count > 0
    if has_htf or primary == "H4":
        return "HTF_STRUCTURAL_SWEEP" if swept else "HTF_STRUCTURAL_LEVEL"
    if primary == "H1":
        return "HTF_STRUCTURAL_SWEEP" if swept else "HTF_STRUCTURAL_LEVEL"
    if primary == "M15" or _has_m15_source(row):
        return "M15_STRUCTURE_SWEEP" if swept else "M15_MINIMUM_STRUCTURE_LEVEL"
    if primary == "SESSION":
        return "LOCAL_SESSION_SWEEP" if swept else "LOCAL_SESSION_ZONE"
    if structural_zone_mode == "PATTERN_DERIVED_ZONE" or primary == "PATTERN":
        return "LOCAL_SESSION_SWEEP" if swept else "LOCAL_SESSION_ZONE"
    return "MICRO_SWEEP" if swept else "M1_LOCAL_ZONE"


def _merged_sweep_importance_class(rows: list[dict[str, object]]) -> str:
    values = [_sweep_importance_class_from_row(row) for row in rows]
    for value in [
        "HTF_STRUCTURAL_SWEEP",
        "HTF_STRUCTURAL_LEVEL",
        "M15_STRUCTURE_SWEEP",
        "M15_MINIMUM_STRUCTURE_LEVEL",
        "LOCAL_SESSION_SWEEP",
        "LOCAL_SESSION_ZONE",
        "MICRO_SWEEP",
        "M1_LOCAL_ZONE",
    ]:
        if value in values:
            return value
    return values[0] if values else ""


def _min_timestamp_text(values) -> str:
    timestamps = [str(value) for value in values if str(value or "")]
    if not timestamps:
        return ""
    return min(timestamps)


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _bool_text(value) -> str:
    return "true" if _bool_value(value) else "false"


def _quality_values(values) -> str:
    unique = set(values)
    if unique == {"RAW"}:
        return "RAW"
    if "RECOVERED_DEGRADED" in unique:
        return "RECOVERED_DEGRADED"
    return sorted(unique)[0] if unique else "RAW"


def _confidence_tier(score: int) -> str:
    if score <= 39:
        return "LOW"
    if score <= 69:
        return "MEDIUM"
    return "HIGH"


def _distance_from_close(price_mid: float, latest_close: float | None) -> float:
    if latest_close is None or latest_close == 0:
        return 0.0
    return (price_mid - float(latest_close)) / float(latest_close) * 100.0


def _age_bars(first_seen_at: str, feed: pd.DataFrame) -> int:
    first_seen = pd.Timestamp(first_seen_at)
    if first_seen > feed["Timestamp"].max():
        return 0
    return int((feed["Timestamp"] >= first_seen).sum())


def _age_days(first_seen_at: str, run_end: str) -> int:
    return max(0, (pd.Timestamp(run_end).date() - pd.Timestamp(first_seen_at).date()).days)


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")
