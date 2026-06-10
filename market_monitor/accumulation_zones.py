from __future__ import annotations

import json

import pandas as pd


ACCUMULATION_ZONES_COLUMNS = [
    "zone_id",
    "created_at",
    "start_timestamp",
    "end_timestamp",
    "price_lower",
    "price_upper",
    "zone_type",
    "confidence_score",
    "confidence_tier",
    "evidence_json",
    "status",
    "data_quality",
]


def build_accumulation_zones(
    feed: pd.DataFrame,
    volume_delta_state: pd.DataFrame,
) -> pd.DataFrame:
    if feed.empty:
        return pd.DataFrame(columns=ACCUMULATION_ZONES_COLUMNS)

    frame = feed.sort_values("Timestamp", kind="mergesort").reset_index(drop=True).copy()
    context = _context_by_timestamp(volume_delta_state)
    day_avg_qty = float(frame["TotalQty"].sum()) / max(len(frame), 1)
    rows: list[dict[str, object]] = []

    for window_minutes in (60, 240, 720, 1440):
        if len(frame) < window_minutes:
            continue
        for start in range(0, len(frame) - window_minutes + 1, window_minutes):
            window = frame.iloc[start : start + window_minutes].copy()
            zone = _build_zone_candidate(
                window=window,
                context=context,
                day_avg_qty=day_avg_qty,
                window_minutes=window_minutes,
            )
            if zone is not None:
                rows.append(zone)

    if not rows:
        return pd.DataFrame(columns=ACCUMULATION_ZONES_COLUMNS)

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["start_timestamp", "end_timestamp", "price_lower", "price_upper"],
        kind="mergesort",
    ).reset_index(drop=True)
    result["zone_id"] = [f"accumulation_zone_{index:06d}" for index in range(1, len(result) + 1)]
    return result[ACCUMULATION_ZONES_COLUMNS]


def _build_zone_candidate(
    *,
    window: pd.DataFrame,
    context: dict[str, dict[str, float]],
    day_avg_qty: float,
    window_minutes: int,
) -> dict[str, object] | None:
    open_price = float(window.iloc[0]["OpenPrice"])
    close_price = float(window.iloc[-1]["ClosePrice"])
    high = float(window["HiPrice"].max())
    low = float(window["LowPrice"].min())
    total_qty = float(window["TotalQty"].sum())
    avg_qty = total_qty / max(len(window), 1)
    volume_multiplier = avg_qty / day_avg_qty if day_avg_qty > 0 else 0.0
    buy_qty = float(window["BuyQty"].sum())
    sell_qty = float(window["SellQty"].sum())
    delta = buy_qty - sell_qty
    delta_pct = delta / total_qty if total_qty > 0 else 0.0
    oi_change = float(window.iloc[-1]["OpenInterest"] - window.iloc[0]["OpenInterest"])
    liq_buy = float(window["LiqBuyQty"].sum()) if "LiqBuyQty" in window.columns else 0.0
    liq_sell = float(window["LiqSellQty"].sum()) if "LiqSellQty" in window.columns else 0.0
    liquidation_total = liq_buy + liq_sell
    price_pct = (close_price / open_price - 1.0) * 100.0 if open_price else 0.0
    price_range = max(high - low, 0.0)
    price_progress = abs(close_price - open_price)
    progress_efficiency = price_progress / price_range if price_range > 0 else 0.0
    max_volume_zscore, max_abs_delta_zscore = _max_context_scores(window, context)

    low_progress = progress_efficiency <= 0.35 or abs(price_pct) <= 0.12
    has_flow_anomaly = (
        max_volume_zscore >= 3.5
        or max_abs_delta_zscore >= 3.5
        or volume_multiplier >= 1.75
        or liquidation_total >= 100.0
    )
    has_inventory_signature = low_progress or abs(price_pct) >= 0.25 or liquidation_total >= 100.0
    if not has_flow_anomaly or not has_inventory_signature:
        return None

    zone_type = _zone_type(
        price_pct=price_pct,
        delta=delta,
        oi_change=oi_change,
        low_progress=low_progress,
        liquidation_total=liquidation_total,
        liq_buy=liq_buy,
        liq_sell=liq_sell,
    )
    confidence_score = _confidence_score(
        max_volume_zscore=max_volume_zscore,
        max_abs_delta_zscore=max_abs_delta_zscore,
        volume_multiplier=volume_multiplier,
        liquidation_total=liquidation_total,
        delta_pct=delta_pct,
        oi_change=oi_change,
        price_pct=price_pct,
        low_progress=low_progress,
    )
    if confidence_score < 35:
        return None

    evidence = {
        "window_minutes": window_minutes,
        "open_price": round(open_price, 8),
        "close_price": round(close_price, 8),
        "price_change_pct": round(price_pct, 6),
        "price_range": round(price_range, 8),
        "progress_efficiency": round(progress_efficiency, 6),
        "total_qty": round(total_qty, 6),
        "volume_multiplier_vs_day_avg": round(volume_multiplier, 6),
        "delta": round(delta, 6),
        "delta_pct": round(delta_pct, 6),
        "open_interest_change": round(oi_change, 6),
        "liq_buy_qty": round(liq_buy, 6),
        "liq_sell_qty": round(liq_sell, 6),
        "liquidation_total": round(liquidation_total, 6),
        "max_volume_zscore": round(max_volume_zscore, 6),
        "max_abs_delta_zscore": round(max_abs_delta_zscore, 6),
        "interpretation_scope": "descriptive_inventory_context_only",
    }
    quality = "RAW" if set(window["DataQuality"].astype(str)) == {"RAW"} else "RECOVERED_DEGRADED"
    return {
        "zone_id": "",
        "created_at": _format_ts(window.iloc[0]["Timestamp"]),
        "start_timestamp": _format_ts(window.iloc[0]["Timestamp"]),
        "end_timestamp": _format_ts(window.iloc[-1]["Timestamp"]),
        "price_lower": low,
        "price_upper": high,
        "zone_type": zone_type,
        "confidence_score": confidence_score,
        "confidence_tier": _confidence_tier(confidence_score),
        "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        "status": "ACTIVE" if confidence_score >= 45 else "TRACKING_ONLY",
        "data_quality": quality,
    }


def _zone_type(
    *,
    price_pct: float,
    delta: float,
    oi_change: float,
    low_progress: bool,
    liquidation_total: float,
    liq_buy: float,
    liq_sell: float,
) -> str:
    if price_pct <= -0.35 and delta > 0:
        return "TRAPPED_BUYING_DISTRIBUTION_ZONE"
    if price_pct >= 0.35 and delta < 0:
        return "TRAPPED_SELLING_ACCUMULATION_ZONE"
    if price_pct <= -0.35:
        return "MARKDOWN_VOLUME_EXPANSION_ZONE"
    if price_pct >= 0.35:
        return "MARKUP_VOLUME_EXPANSION_ZONE"
    if low_progress and delta < 0 and oi_change > 0:
        return "DISTRIBUTION_REBALANCE_ZONE"
    if low_progress and delta > 0 and oi_change > 0:
        return "ACCUMULATION_REBALANCE_ZONE"
    if liquidation_total > 0 and liq_sell > liq_buy * 2:
        return "SELL_LIQUIDATION_REPRICING_ZONE"
    if liquidation_total > 0 and liq_buy > liq_sell * 2:
        return "BUY_LIQUIDATION_REPRICING_ZONE"
    return "REDISTRIBUTION_BALANCE_ZONE"


def _confidence_score(
    *,
    max_volume_zscore: float,
    max_abs_delta_zscore: float,
    volume_multiplier: float,
    liquidation_total: float,
    delta_pct: float,
    oi_change: float,
    price_pct: float,
    low_progress: bool,
) -> int:
    score = 20
    if max_volume_zscore >= 4:
        score += 20
    elif max_volume_zscore >= 3:
        score += 12
    if max_abs_delta_zscore >= 4:
        score += 16
    elif max_abs_delta_zscore >= 3:
        score += 10
    if volume_multiplier >= 2.5:
        score += 16
    elif volume_multiplier >= 1.75:
        score += 10
    if liquidation_total >= 250:
        score += 16
    elif liquidation_total >= 100:
        score += 10
    if abs(delta_pct) >= 0.25:
        score += 8
    if low_progress:
        score += 10
    if price_pct < 0 and oi_change > 0:
        score += 8
    if price_pct > 0 and oi_change > 0:
        score += 4
    return int(max(0, min(score, 100)))


def _confidence_tier(score: int) -> str:
    if score >= 70:
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    return "LOW"


def _max_context_scores(
    window: pd.DataFrame,
    context: dict[str, dict[str, float]],
) -> tuple[float, float]:
    max_volume = 0.0
    max_delta = 0.0
    for value in window["Timestamp"]:
        item = context.get(_format_ts(value))
        if not item:
            continue
        max_volume = max(max_volume, abs(float(item.get("volume_zscore", 0.0))))
        max_delta = max(max_delta, abs(float(item.get("delta_zscore", 0.0))))
    return max_volume, max_delta


def _context_by_timestamp(volume_delta_state: pd.DataFrame) -> dict[str, dict[str, float]]:
    if volume_delta_state.empty:
        return {}
    return {
        str(row["timestamp"]): {
            "volume_zscore": float(row.get("volume_zscore", 0.0) or 0.0),
            "delta_zscore": float(row.get("delta_zscore", 0.0) or 0.0),
        }
        for _, row in volume_delta_state.iterrows()
    }


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")
