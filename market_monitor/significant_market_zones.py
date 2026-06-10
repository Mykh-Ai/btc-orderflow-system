from __future__ import annotations

import json
from collections import Counter

import pandas as pd


SIGNIFICANT_MARKET_ZONE_COLUMNS = [
    "zone_id",
    "created_at",
    "first_seen_at",
    "last_seen_at",
    "price_lower",
    "price_upper",
    "price_mid",
    "source_zone_count",
    "source_day_count",
    "source_window_types",
    "dominant_zone_types",
    "total_qty",
    "net_delta",
    "open_interest_change",
    "liq_buy_qty",
    "liq_sell_qty",
    "reaction_count",
    "structural_overlap_count",
    "phase_transition_context",
    "context_1d",
    "context_3d",
    "context_7d",
    "context_30d",
    "significance_score",
    "confidence_tier",
    "status",
    "evidence_json",
    "data_quality",
]


def build_significant_market_zones(
    *,
    inventory_zones: pd.DataFrame,
    liquidity_zone_registry: pd.DataFrame,
    market_context_windows: pd.DataFrame,
) -> pd.DataFrame:
    if inventory_zones.empty:
        return pd.DataFrame(columns=SIGNIFICANT_MARKET_ZONE_COLUMNS)

    sources = _normalize_sources(inventory_zones)
    if not sources:
        return pd.DataFrame(columns=SIGNIFICANT_MARKET_ZONE_COLUMNS)

    clusters = _cluster_sources(sources)
    context_by_days = _context_by_days(market_context_windows)
    rows = []
    median_qty = _median_total_qty(clusters)
    for index, cluster in enumerate(clusters, start=1):
        rows.append(
            _build_zone_row(
                index=index,
                cluster=cluster,
                liquidity_zone_registry=liquidity_zone_registry,
                context_by_days=context_by_days,
                median_qty=median_qty,
            )
        )
    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["significance_score", "source_day_count", "source_zone_count", "first_seen_at"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    result = _suppress_overlapping_rows(result)
    result["zone_id"] = [f"significant_zone_{index:06d}" for index in range(1, len(result) + 1)]
    return result[SIGNIFICANT_MARKET_ZONE_COLUMNS]


def _normalize_sources(inventory_zones: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for _, row in inventory_zones.iterrows():
        evidence = _parse_json(row.get("evidence_json"))
        price_lower = float(row["price_lower"])
        price_upper = float(row["price_upper"])
        price_mid = (price_lower + price_upper) / 2.0
        if price_lower <= 0 or price_upper <= price_lower or price_mid <= 0:
            continue
        width_pct = (price_upper - price_lower) / price_mid
        if width_pct > 0.04:
            continue
        rows.append(
            {
                "zone_id": str(row.get("zone_id", "")),
                "start_timestamp": str(row["start_timestamp"]),
                "end_timestamp": str(row["end_timestamp"]),
                "day": str(pd.Timestamp(row["start_timestamp"]).date()),
                "price_lower": price_lower,
                "price_upper": price_upper,
                "price_mid": price_mid,
                "zone_type": str(row["zone_type"]),
                "confidence_tier": str(row.get("confidence_tier", "")),
                "data_quality": str(row.get("data_quality", "")),
                "window_minutes": int(float(evidence.get("window_minutes", 0) or 0)),
                "total_qty": float(evidence.get("total_qty", 0.0) or 0.0),
                "delta": float(evidence.get("delta", 0.0) or 0.0),
                "open_interest_change": float(evidence.get("open_interest_change", 0.0) or 0.0),
                "liq_buy_qty": float(evidence.get("liq_buy_qty", 0.0) or 0.0),
                "liq_sell_qty": float(evidence.get("liq_sell_qty", 0.0) or 0.0),
            }
        )
    return sorted(rows, key=lambda item: (float(item["price_lower"]), float(item["price_upper"]), str(item["start_timestamp"])))


def _cluster_sources(sources: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    clusters: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_mid = None
    for source in sources:
        mid = float(source["price_mid"])
        if not current:
            current = [source]
            current_mid = mid
            continue
        if current_mid is not None and abs(mid - current_mid) / current_mid <= 0.012:
            current.append(source)
            current_mid = sum(float(item["price_mid"]) for item in current) / len(current)
        else:
            clusters.append(current)
            current = [source]
            current_mid = mid
    if current:
        clusters.append(current)
    return clusters


def _build_zone_row(
    *,
    index: int,
    cluster: list[dict[str, object]],
    liquidity_zone_registry: pd.DataFrame,
    context_by_days: dict[int, str],
    median_qty: float,
) -> dict[str, object]:
    price_lower = min(float(item["price_lower"]) for item in cluster)
    price_upper = max(float(item["price_upper"]) for item in cluster)
    price_mid = (price_lower + price_upper) / 2.0
    start_ts = min(str(item["start_timestamp"]) for item in cluster)
    end_ts = max(str(item["end_timestamp"]) for item in cluster)
    source_days = sorted({str(item["day"]) for item in cluster})
    source_windows = sorted({int(item["window_minutes"]) for item in cluster if int(item["window_minutes"]) > 0})
    zone_type_counts = Counter(str(item["zone_type"]) for item in cluster)
    total_qty = sum(float(item["total_qty"]) for item in cluster)
    net_delta = sum(float(item["delta"]) for item in cluster)
    oi_change = sum(float(item["open_interest_change"]) for item in cluster)
    liq_buy = sum(float(item["liq_buy_qty"]) for item in cluster)
    liq_sell = sum(float(item["liq_sell_qty"]) for item in cluster)
    structural_overlap_count = _structural_overlap_count(
        liquidity_zone_registry,
        price_lower=price_lower,
        price_upper=price_upper,
    )
    reaction_count = _reaction_count(
        liquidity_zone_registry,
        price_lower=price_lower,
        price_upper=price_upper,
    )
    phase_context = _phase_transition_context(zone_type_counts)
    score, evidence = _score_zone(
        source_zone_count=len(cluster),
        source_day_count=len(source_days),
        total_qty=total_qty,
        median_qty=median_qty,
        open_interest_change=oi_change,
        liq_buy=liq_buy,
        liq_sell=liq_sell,
        structural_overlap_count=structural_overlap_count,
        reaction_count=reaction_count,
        phase_transition_context=phase_context,
    )
    data_quality = _data_quality(cluster)
    evidence.update(
        {
            "source_zone_id_sample": "|".join(str(item["zone_id"]) for item in cluster[:20]),
            "source_zone_id_sample_truncated": len(cluster) > 20,
            "source_days": "|".join(source_days),
            "dominant_zone_types": _format_counts(zone_type_counts),
            "interpretation_scope": "descriptive_market_memory_zone_only",
        }
    )
    return {
        "zone_id": f"significant_zone_{index:06d}",
        "created_at": start_ts,
        "first_seen_at": start_ts,
        "last_seen_at": end_ts,
        "price_lower": round(price_lower, 8),
        "price_upper": round(price_upper, 8),
        "price_mid": round(price_mid, 8),
        "source_zone_count": int(len(cluster)),
        "source_day_count": int(len(source_days)),
        "source_window_types": "|".join(str(value) for value in source_windows),
        "dominant_zone_types": _format_counts(zone_type_counts),
        "total_qty": round(total_qty, 6),
        "net_delta": round(net_delta, 6),
        "open_interest_change": round(oi_change, 6),
        "liq_buy_qty": round(liq_buy, 6),
        "liq_sell_qty": round(liq_sell, 6),
        "reaction_count": int(reaction_count),
        "structural_overlap_count": int(structural_overlap_count),
        "phase_transition_context": phase_context,
        "context_1d": context_by_days.get(1, ""),
        "context_3d": context_by_days.get(3, ""),
        "context_7d": context_by_days.get(7, ""),
        "context_30d": context_by_days.get(30, ""),
        "significance_score": int(score),
        "confidence_tier": _confidence_tier(score),
        "status": "SIGNIFICANT" if score >= 55 else "TRACKING_ONLY",
        "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        "data_quality": data_quality,
    }


def _score_zone(
    *,
    source_zone_count: int,
    source_day_count: int,
    total_qty: float,
    median_qty: float,
    open_interest_change: float,
    liq_buy: float,
    liq_sell: float,
    structural_overlap_count: int,
    reaction_count: int,
    phase_transition_context: str,
) -> tuple[int, dict[str, object]]:
    score = 10
    source_score = min(max(source_zone_count - 1, 0) * 5, 20)
    day_score = 0
    if source_day_count >= 3:
        day_score = 25
    elif source_day_count == 2:
        day_score = 15
    volume_score = 0
    if median_qty > 0 and total_qty >= median_qty * 4:
        volume_score = 20
    elif median_qty > 0 and total_qty >= median_qty * 2:
        volume_score = 10
    liq_total = liq_buy + liq_sell
    liquidation_score = 16 if liq_total >= 250 else 10 if liq_total >= 100 else 0
    oi_score = 16 if abs(open_interest_change) >= 1500 else 8 if abs(open_interest_change) >= 500 else 0
    structure_score = 14 if structural_overlap_count >= 3 else 8 if structural_overlap_count >= 1 else 0
    reaction_score = 12 if reaction_count >= 4 else 8 if reaction_count >= 2 else 0
    phase_score = 8 if phase_transition_context != "MIXED_OR_LOCAL" else 0
    score += source_score + day_score + volume_score + liquidation_score + oi_score + structure_score + reaction_score + phase_score
    score = int(max(0, min(score, 100)))
    evidence = {
        "score_components": {
            "base": 10,
            "source_score": source_score,
            "day_score": day_score,
            "volume_score": volume_score,
            "liquidation_score": liquidation_score,
            "open_interest_score": oi_score,
            "structure_score": structure_score,
            "reaction_score": reaction_score,
            "phase_score": phase_score,
        }
    }
    return score, evidence


def _suppress_overlapping_rows(frame: pd.DataFrame) -> pd.DataFrame:
    kept: list[pd.Series] = []
    for _, row in frame.iterrows():
        lower = float(row["price_lower"])
        upper = float(row["price_upper"])
        width = max(upper - lower, 1e-9)
        overlaps_existing = False
        for kept_row in kept:
            kept_lower = float(kept_row["price_lower"])
            kept_upper = float(kept_row["price_upper"])
            kept_width = max(kept_upper - kept_lower, 1e-9)
            overlap = max(0.0, min(upper, kept_upper) - max(lower, kept_lower))
            if overlap / min(width, kept_width) >= 0.5:
                overlaps_existing = True
                break
        if not overlaps_existing:
            kept.append(row)
    if not kept:
        return frame.head(0).copy()
    return pd.DataFrame(kept).reset_index(drop=True)


def _structural_overlap_count(
    registry: pd.DataFrame,
    *,
    price_lower: float,
    price_upper: float,
) -> int:
    if registry.empty or "price_lower" not in registry.columns or "price_upper" not in registry.columns:
        return 0
    lower = pd.to_numeric(registry["price_lower"], errors="coerce")
    upper = pd.to_numeric(registry["price_upper"], errors="coerce")
    overlaps = (lower <= price_upper) & (upper >= price_lower)
    return int(overlaps.fillna(False).sum())


def _reaction_count(
    registry: pd.DataFrame,
    *,
    price_lower: float,
    price_upper: float,
) -> int:
    if registry.empty or "price_lower" not in registry.columns or "price_upper" not in registry.columns:
        return 0
    lower = pd.to_numeric(registry.get("price_lower"), errors="coerce")
    upper = pd.to_numeric(registry.get("price_upper"), errors="coerce")
    overlaps = (lower <= price_upper) & (upper >= price_lower)
    if not overlaps.any():
        return 0
    total = 0
    for column in ("touch_count", "cross_count", "m1_interaction_count", "htf_sweep_count"):
        if column in registry.columns:
            total += int(pd.to_numeric(registry.loc[overlaps, column], errors="coerce").fillna(0).sum())
    return total


def _phase_transition_context(zone_type_counts: Counter[str]) -> str:
    bearish = sum(
        count
        for zone_type, count in zone_type_counts.items()
        if zone_type in {"DISTRIBUTION_REBALANCE_ZONE", "TRAPPED_BUYING_DISTRIBUTION_ZONE", "MARKDOWN_VOLUME_EXPANSION_ZONE"}
    )
    bullish = sum(
        count
        for zone_type, count in zone_type_counts.items()
        if zone_type in {"ACCUMULATION_REBALANCE_ZONE", "TRAPPED_SELLING_ACCUMULATION_ZONE", "MARKUP_VOLUME_EXPANSION_ZONE"}
    )
    if bearish >= max(2, bullish * 2):
        return "DISTRIBUTION_OR_MARKDOWN_MEMORY"
    if bullish >= max(2, bearish * 2):
        return "ACCUMULATION_OR_MARKUP_MEMORY"
    if any("LIQUIDATION_REPRICING" in zone_type for zone_type in zone_type_counts):
        return "LIQUIDATION_REPRICING_MEMORY"
    return "MIXED_OR_LOCAL"


def _context_by_days(context_windows: pd.DataFrame) -> dict[int, str]:
    if context_windows.empty:
        return {}
    result = {}
    for _, row in context_windows.iterrows():
        result[int(row["window_days"])] = str(row["regime_bias"])
    return result


def _median_total_qty(clusters: list[list[dict[str, object]]]) -> float:
    totals = [sum(float(item["total_qty"]) for item in cluster) for cluster in clusters]
    if not totals:
        return 0.0
    return float(pd.Series(totals).median())


def _data_quality(cluster: list[dict[str, object]]) -> str:
    values = {str(item["data_quality"]) for item in cluster if str(item["data_quality"])}
    if values == {"RAW"}:
        return "RAW"
    if not values:
        return "UNKNOWN"
    return "RECOVERED_DEGRADED" if "RECOVERED_DEGRADED" in values else "|".join(sorted(values))


def _confidence_tier(score: int) -> str:
    if score >= 75:
        return "HIGH"
    if score >= 55:
        return "MEDIUM"
    return "LOW"


def _format_counts(counts: Counter[str]) -> str:
    if not counts:
        return ""
    return "|".join(f"{name}={int(count)}" for name, count in sorted(counts.items()))


def _parse_json(raw) -> dict[str, object]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
