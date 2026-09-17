from __future__ import annotations

import json

import pandas as pd


PATTERN_STRUCTURES_COLUMNS = [
    "pattern_id",
    "created_at",
    "pattern_type",
    "pattern_role",
    "side",
    "status",
    "confidence_tier",
    "price_lower",
    "price_upper",
    "price_mid",
    "neckline_price",
    "left_point_timestamp",
    "left_point_price",
    "head_point_timestamp",
    "head_point_price",
    "right_point_timestamp",
    "right_point_price",
    "source_timeframe",
    "source_level_ids",
    "pattern_source_points_json",
    "linked_zone_id",
    "invalidated_at",
    "invalidation_reason",
    "data_quality",
]

PATTERN_LEVEL_TYPES = {
    "DOUBLE_TOP_HIGH": ("DOUBLE_TOP", "BUY_SIDE_LIQUIDITY", "DOUBLE_TOP_LIQUIDITY_ZONE"),
    "DOUBLE_BOTTOM_LOW": ("DOUBLE_BOTTOM", "SELL_SIDE_LIQUIDITY", "DOUBLE_BOTTOM_LIQUIDITY_ZONE"),
    "EQUAL_HIGHS": ("EQUAL_HIGHS_CLUSTER", "BUY_SIDE_LIQUIDITY", "EQUAL_HIGHS_ZONE"),
    "EQUAL_LOWS": ("EQUAL_LOWS_CLUSTER", "SELL_SIDE_LIQUIDITY", "EQUAL_LOWS_ZONE"),
}

INACTIVE_PATTERN_STATUSES = {
    "CONSUMED",
    "CHOPPED_THROUGH",
    "INVALIDATED",
    "EXPIRED",
}


def build_pattern_structures(
    structure_levels: pd.DataFrame,
    liquidity_zone_registry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if structure_levels.empty:
        return pd.DataFrame(columns=PATTERN_STRUCTURES_COLUMNS)

    registry = (
        liquidity_zone_registry.copy()
        if liquidity_zone_registry is not None
        else pd.DataFrame()
    )
    levels = structure_levels.copy()
    rows = []
    for _, level in levels[levels["level_type"].isin(PATTERN_LEVEL_TYPES)].iterrows():
        rows.append(_pattern_row(level, levels, registry))
    if not rows:
        return pd.DataFrame(columns=PATTERN_STRUCTURES_COLUMNS)
    out = pd.DataFrame(rows, columns=PATTERN_STRUCTURES_COLUMNS)
    out = out.sort_values(
        ["created_at", "pattern_type", "price_mid", "source_level_ids"],
        kind="mergesort",
    ).reset_index(drop=True)
    out["pattern_id"] = [f"pattern_{idx + 1:06d}" for idx in range(len(out))]
    return out[PATTERN_STRUCTURES_COLUMNS]


def _pattern_row(level: pd.Series, levels: pd.DataFrame, registry: pd.DataFrame) -> dict[str, object]:
    pattern_type, role, zone_type = PATTERN_LEVEL_TYPES[str(level["level_type"])]
    source_ids = _source_ids(level)
    sources = _source_levels(levels, source_ids)
    points = _source_points(sources if not sources.empty else pd.DataFrame([level]))
    linked_zone = _linked_zone(registry, source_ids, zone_type)
    status = _pattern_status(linked_zone)
    price_mid = float(level["price"])
    band = max(abs(price_mid) * 0.0005, 10.0)
    return {
        "pattern_id": "",
        "created_at": _format_ts(level["created_at"]),
        "pattern_type": pattern_type,
        "pattern_role": role,
        "side": str(level["side"]),
        "status": status,
        "confidence_tier": _confidence_tier(level),
        "price_lower": price_mid - band,
        "price_upper": price_mid + band,
        "price_mid": price_mid,
        "neckline_price": "",
        "left_point_timestamp": _point_value(points, 0, "timestamp"),
        "left_point_price": _point_value(points, 0, "price"),
        "head_point_timestamp": "",
        "head_point_price": "",
        "right_point_timestamp": _point_value(points, 1, "timestamp"),
        "right_point_price": _point_value(points, 1, "price"),
        "source_timeframe": _source_timeframes(sources, level),
        "source_level_ids": "|".join(source_ids),
        "pattern_source_points_json": json.dumps(points, sort_keys=True, separators=(",", ":")),
        "linked_zone_id": str(linked_zone.get("zone_id", "")) if not linked_zone.empty else "",
        "invalidated_at": _invalidated_at(linked_zone),
        "invalidation_reason": str(linked_zone.get("invalidation_reason", "")) if not linked_zone.empty else "",
        "data_quality": str(level["data_quality"]),
    }


def _source_ids(level: pd.Series) -> list[str]:
    ids = [part for part in str(level.get("source_level_ids", "")).split("|") if part]
    return ids or [str(level["level_id"])]


def _source_levels(levels: pd.DataFrame, source_ids: list[str]) -> pd.DataFrame:
    if not source_ids or "level_id" not in levels.columns:
        return levels.iloc[0:0]
    return levels[levels["level_id"].astype(str).isin(source_ids)].sort_values(
        ["created_at", "level_timestamp", "level_id"], kind="mergesort"
    )


def _source_points(sources: pd.DataFrame) -> list[dict[str, object]]:
    points = []
    for _, source in sources.iterrows():
        points.append(
            {
                "level_id": str(source.get("level_id", "")),
                "level_type": str(source.get("level_type", "")),
                "timestamp": _format_ts(source.get("level_timestamp", source.get("created_at", ""))),
                "created_at": _format_ts(source.get("created_at", source.get("level_timestamp", ""))),
                "price": float(source.get("price", 0.0)),
                "timeframe": str(source.get("timeframe", "")),
            }
        )
    return points


def _linked_zone(registry: pd.DataFrame, source_ids: list[str], zone_type: str) -> pd.Series:
    if registry.empty:
        return pd.Series(dtype=object)
    candidates = registry[registry.get("zone_type", "").astype(str) == zone_type].copy()
    if candidates.empty:
        return pd.Series(dtype=object)
    source_set = set(source_ids)
    candidates["_source_overlap"] = candidates.get("source_level_ids", "").map(
        lambda value: len(source_set & {part for part in str(value).split("|") if part})
    )
    candidates = candidates[candidates["_source_overlap"] > 0]
    if candidates.empty:
        return pd.Series(dtype=object)
    return candidates.sort_values(
        ["_source_overlap", "first_seen_at", "zone_id"],
        ascending=[False, True, True],
        kind="mergesort",
    ).iloc[0]


def _pattern_status(linked_zone: pd.Series) -> str:
    if linked_zone.empty:
        return "ACTIVE"
    consumption = str(linked_zone.get("consumption_status", ""))
    status = str(linked_zone.get("status", ""))
    if consumption in {"CONSUMED", "CHOPPED_THROUGH"}:
        return consumption
    if status == "EXPIRED":
        return "EXPIRED"
    if status == "CROSSED_UNCLASSIFIED":
        return "SWEPT"
    if status in {"REACTED", "FLIPPED_REACTION_ZONE"}:
        return "REACTED"
    if status in INACTIVE_PATTERN_STATUSES:
        return status
    return "ACTIVE"


def _invalidated_at(linked_zone: pd.Series) -> str:
    if linked_zone.empty:
        return ""
    if _pattern_status(linked_zone) in INACTIVE_PATTERN_STATUSES:
        return str(linked_zone.get("consumed_at", "") or linked_zone.get("last_updated_at", ""))
    return ""


def _confidence_tier(level: pd.Series) -> str:
    score = int(float(level.get("strength_score", 0) or 0))
    if score <= 39:
        return "LOW"
    if score <= 69:
        return "MEDIUM"
    return "HIGH"


def _source_timeframes(sources: pd.DataFrame, level: pd.Series) -> str:
    if sources.empty:
        return str(level.get("timeframe", ""))
    return "|".join(sorted({str(value) for value in sources["timeframe"] if str(value)}))


def _point_value(points: list[dict[str, object]], index: int, key: str):
    if len(points) <= index:
        return ""
    return points[index][key]


def _format_ts(value) -> str:
    if value == "":
        return ""
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")
