from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from market_monitor.accumulation_zones import build_accumulation_zones
from market_monitor.context_windows import build_market_context_windows
from market_monitor.liquidity_zones import build_liquidity_map
from market_monitor.market_structure_state import _classify_state as classify_market_structure_state
from market_monitor.market_structure_state import _oi_context as market_structure_oi_context
from market_monitor.market_structure_state import _window_metrics as market_structure_window_metrics
from market_monitor.outputs import build_market_state_timeline, build_volume_delta_state
from market_monitor.significant_market_zones import build_significant_market_zones
from market_monitor.structure import build_structure_levels
from market_monitor.zone_registry import build_zone_registry, forward_liquidity_from_registry


SNAPSHOT_SCHEMA_VERSION = "market_monitor_snapshot_v1"
LOCAL_WINDOWS_MINUTES = (15, 60, 240)


def build_market_monitor_snapshot(
    feed: pd.DataFrame,
    *,
    context_feed: pd.DataFrame | None = None,
    cutoff_ts=None,
    current_price: float | None = None,
    src_event: dict[str, Any] | None = None,
    symbol: str | None = None,
    max_zones: int = 5,
) -> dict[str, Any]:
    cutoff = _resolve_cutoff(feed, cutoff_ts)
    current = _filter_to_cutoff(feed, cutoff)
    context = _context_feed(context_feed, current, cutoff)
    latest_price = _latest_price(current, current_price)

    volume_delta_state = build_volume_delta_state(current)
    context_volume_delta_state = build_volume_delta_state(context)
    market_context_windows = build_market_context_windows(context, end_timestamp=cutoff)
    local_context = _local_context(current)
    broad_context = _broad_context(market_context_windows)

    structure_levels = build_structure_levels(current)
    liquidity_map = build_liquidity_map(structure_levels, latest_price)
    liquidity_zone_registry, registry_stats = build_zone_registry(
        liquidity_map=liquidity_map,
        feed=current,
    )
    forward_liquidity_map = forward_liquidity_from_registry(liquidity_zone_registry, latest_price)
    local_inventory_zones = build_accumulation_zones(current, volume_delta_state)
    context_inventory_zones = build_accumulation_zones(context, context_volume_delta_state)
    significant_market_zones = build_significant_market_zones(
        inventory_zones=context_inventory_zones,
        liquidity_zone_registry=liquidity_zone_registry,
        market_context_windows=market_context_windows,
    )
    market_state = build_market_state_timeline(
        current,
        market_context_windows=market_context_windows,
        significant_market_zones=significant_market_zones,
    )
    market_structure_state = _market_structure_state(
        current=current,
        significant_market_zones=significant_market_zones,
    )

    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "cutoff_ts": _format_ts(cutoff),
        "symbol": symbol or "",
        "data_quality": _snapshot_quality(current=current, context=context),
        "src_event": src_event or {},
        "local_context": local_context,
        "broad_context": broad_context,
        "market_state": _market_state(market_state),
        "market_structure_state": market_structure_state,
        "significant_market_zones": _zone_buckets(
            significant_market_zones,
            latest_price=latest_price,
            max_zones=max_zones,
        ),
        "liquidity_zones": _liquidity_buckets(
            forward_liquidity_map,
            latest_price=latest_price,
            max_zones=max_zones,
        ),
        "context_conflicts": _context_conflicts(
            src_event=src_event or {},
            local_context=local_context,
            broad_context=broad_context,
        ),
        "monitor_artifacts": {
            "market_context_windows_csv": "",
            "significant_market_zones_csv": "",
            "market_state_timeline_csv": "",
        },
        "boundary": "descriptive market-state snapshot only",
        "diagnostics": {
            "current_rows": int(len(current)),
            "context_rows": int(len(context)),
            "local_inventory_zone_count": int(len(local_inventory_zones)),
            "context_inventory_zone_count": int(len(context_inventory_zones)),
            "registry_stats": registry_stats,
        },
    }
    return _json_roundtrip(snapshot)


def write_market_monitor_snapshot(
    snapshot: dict[str, Any],
    path: str | Path,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_cutoff(feed: pd.DataFrame, cutoff_ts) -> pd.Timestamp:
    if cutoff_ts is not None:
        return _to_utc(cutoff_ts)
    if feed.empty:
        raise ValueError("cutoff_ts is required when feed is empty")
    return _to_utc(feed["Timestamp"].max())


def _filter_to_cutoff(feed: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if feed.empty:
        return feed.copy()
    frame = feed.sort_values("Timestamp", kind="mergesort").copy()
    return frame[frame["Timestamp"] <= cutoff].copy()


def _context_feed(
    context_feed: pd.DataFrame | None,
    current: pd.DataFrame,
    cutoff: pd.Timestamp,
) -> pd.DataFrame:
    source = context_feed if context_feed is not None and not context_feed.empty else current
    if source.empty:
        return source.copy()
    start = cutoff - pd.Timedelta(days=30)
    frame = source.sort_values("Timestamp", kind="mergesort").copy()
    return frame[(frame["Timestamp"] >= start) & (frame["Timestamp"] <= cutoff)].copy()


def _latest_price(feed: pd.DataFrame, current_price: float | None) -> float | None:
    if current_price is not None:
        return float(current_price)
    if feed.empty:
        return None
    return float(feed.iloc[-1]["ClosePrice"])


def _snapshot_quality(*, current: pd.DataFrame, context: pd.DataFrame) -> dict[str, Any]:
    return {
        "current": _quality_summary(current),
        "context": _quality_summary(context),
        "current_rows": int(len(current)),
        "context_rows": int(len(context)),
    }


def _local_context(feed: pd.DataFrame) -> dict[str, Any]:
    result = {}
    for minutes in LOCAL_WINDOWS_MINUTES:
        window = feed.tail(minutes).copy()
        result[f"{minutes}m"] = _window_metrics(window, expected_minutes=minutes)
    return result


def _window_metrics(window: pd.DataFrame, *, expected_minutes: int) -> dict[str, Any]:
    if window.empty:
        return {
            "rows_used": 0,
            "expected_minutes": expected_minutes,
            "data_quality": "none",
            "price_change_pct": 0.0,
            "total_qty": 0.0,
            "delta": 0.0,
            "delta_pct": 0.0,
            "open_interest_change": 0.0,
            "funding_last": 0.0,
            "liq_buy_qty": 0.0,
            "liq_sell_qty": 0.0,
        }
    open_price = float(window.iloc[0]["OpenPrice"])
    close_price = float(window.iloc[-1]["ClosePrice"])
    total_qty = float(window["TotalQty"].sum())
    delta = float((window["BuyQty"] - window["SellQty"]).sum())
    return {
        "start_timestamp": _format_ts(window.iloc[0]["Timestamp"]),
        "end_timestamp": _format_ts(window.iloc[-1]["Timestamp"]),
        "rows_used": int(len(window)),
        "expected_minutes": int(expected_minutes),
        "data_quality": _quality_summary(window),
        "price_change_pct": _round((close_price / open_price - 1.0) * 100.0 if open_price else 0.0),
        "total_qty": _round(total_qty),
        "delta": _round(delta),
        "delta_pct": _round(delta / total_qty if total_qty > 0 else 0.0, digits=8),
        "open_interest_change": _round(float(window.iloc[-1]["OpenInterest"] - window.iloc[0]["OpenInterest"])),
        "funding_last": _round(float(window.iloc[-1]["FundingRate"]), digits=10),
        "liq_buy_qty": _round(float(window["LiqBuyQty"].sum()) if "LiqBuyQty" in window.columns else 0.0),
        "liq_sell_qty": _round(float(window["LiqSellQty"].sum()) if "LiqSellQty" in window.columns else 0.0),
    }


def _broad_context(context_windows: pd.DataFrame) -> dict[str, Any]:
    result = {}
    if context_windows.empty:
        return result
    for _, row in context_windows.sort_values("window_days", kind="mergesort").iterrows():
        key = f"{int(row['window_days'])}d"
        result[key] = {
            "start_timestamp": row["start_timestamp"],
            "end_timestamp": row["end_timestamp"],
            "rows_used": int(row["rows_used"]),
            "data_quality": row["data_quality"],
            "data_quality_flags": row["data_quality_flags"],
            "price_change_pct": _round(float(row["price_change_pct"])),
            "total_qty": _round(float(row["total_qty"])),
            "delta": _round(float(row["delta"])),
            "delta_pct": _round(float(row["delta_pct"]), digits=8),
            "open_interest_change": _round(float(row["open_interest_change"])),
            "funding_last": _round(float(row["funding_last"]), digits=10),
            "funding_mean": _round(float(row["funding_mean"]), digits=10),
            "liq_buy_qty": _round(float(row["liq_buy_qty"])),
            "liq_sell_qty": _round(float(row["liq_sell_qty"])),
            "regime_bias": row["regime_bias"],
            "confidence_tier": row["confidence_tier"],
        }
    return result


def _market_state(market_state: pd.DataFrame) -> dict[str, Any]:
    if market_state.empty:
        return {}
    row = market_state.iloc[-1]
    return {
        "state": row["state"],
        "confidence_tier": row["confidence_tier"],
        "start_timestamp": row["start_timestamp"],
        "end_timestamp": row["end_timestamp"],
        "data_quality": row["data_quality"],
        "evidence": _parse_json(row["evidence_json"]),
    }


def _market_structure_state(
    *,
    current: pd.DataFrame,
    significant_market_zones: pd.DataFrame,
) -> dict[str, Any]:
    if current.empty:
        return {
            "schema_version": "market_structure_state_snapshot_v1",
            "status": "unavailable",
            "data_gaps": ["market_structure_state_current_feed_empty"],
        }
    try:
        metrics = market_structure_window_metrics(current)
    except Exception as exc:
        return {
            "schema_version": "market_structure_state_snapshot_v1",
            "status": "unavailable",
            "data_gaps": [f"market_structure_state_metrics_error:{type(exc).__name__}"],
        }

    close = float(metrics.get("close", 0.0) or 0.0)
    support = _nearest_market_structure_zone(significant_market_zones, close, role="SUPPORT")
    resistance = _nearest_market_structure_zone(significant_market_zones, close, role="RESISTANCE")
    try:
        state, confidence, bias, candidate_strength, evidence = classify_market_structure_state(
            metrics=metrics,
            support=support,
            resistance=resistance,
            previous_states=[],
        )
    except Exception as exc:
        return {
            "schema_version": "market_structure_state_snapshot_v1",
            "status": "unavailable",
            "data_gaps": [f"market_structure_state_classifier_error:{type(exc).__name__}"],
            "metrics": _market_structure_metrics(metrics),
            "support": _market_structure_zone_item(support),
            "resistance": _market_structure_zone_item(resistance),
        }

    data_gaps = []
    if support.empty:
        data_gaps.append("market_structure_state_support_zone_missing")
    if resistance.empty:
        data_gaps.append("market_structure_state_resistance_zone_missing")
    return {
        "schema_version": "market_structure_state_snapshot_v1",
        "status": "partial" if data_gaps else "ok",
        "state_version": "SHI_RESET_37E_ONLINE_MARKET_STRUCTURE_STATE_MEMORY_V0",
        "classification_scope": "pre_cutoff_current_feed_window_with_snapshot_zones",
        "market_state": state,
        "confidence_tier": confidence,
        "candidate_bias": bias,
        "candidate_strength": candidate_strength,
        "metrics": _market_structure_metrics(metrics),
        "oi_context": market_structure_oi_context(metrics),
        "support": _market_structure_zone_item(support),
        "resistance": _market_structure_zone_item(resistance),
        "evidence_summary": evidence,
        "data_gaps": data_gaps,
    }


def _market_structure_metrics(metrics: dict[str, float]) -> dict[str, Any]:
    return {
        "price_open": _round(float(metrics.get("open", 0.0) or 0.0)),
        "price_close": _round(float(metrics.get("close", 0.0) or 0.0)),
        "price_high": _round(float(metrics.get("high", 0.0) or 0.0)),
        "price_low": _round(float(metrics.get("low", 0.0) or 0.0)),
        "price_change_pct": _round(float(metrics.get("price_change_pct", 0.0) or 0.0)),
        "range_pct": _round(float(metrics.get("range_pct", 0.0) or 0.0)),
        "close_position": _round(float(metrics.get("close_position", 0.0) or 0.0), digits=4),
        "delta_pct": _round(float(metrics.get("delta_pct", 0.0) or 0.0)),
        "open_interest_change": _round(float(metrics.get("open_interest_change", 0.0) or 0.0)),
    }


def _nearest_market_structure_zone(zones: pd.DataFrame, close: float, *, role: str) -> pd.Series:
    if zones.empty or close <= 0:
        return pd.Series(dtype=object)
    required = {"price_lower", "price_upper", "significance_score"}
    if not required.issubset(set(zones.columns)):
        return pd.Series(dtype=object)
    frame = zones.copy()
    frame["price_lower"] = pd.to_numeric(frame["price_lower"], errors="coerce")
    frame["price_upper"] = pd.to_numeric(frame["price_upper"], errors="coerce")
    frame["strength_score"] = pd.to_numeric(frame["significance_score"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["price_lower", "price_upper"])
    if role == "SUPPORT":
        candidates = frame[frame["price_upper"] < close].copy()
        if candidates.empty:
            return pd.Series(dtype=object)
        candidates["_distance"] = close - candidates["price_upper"]
        row = candidates.sort_values(["_distance", "strength_score"], ascending=[True, False], kind="mergesort").iloc[0].copy()
    else:
        candidates = frame[frame["price_lower"] > close].copy()
        if candidates.empty:
            return pd.Series(dtype=object)
        candidates["_distance"] = candidates["price_lower"] - close
        row = candidates.sort_values(["_distance", "strength_score"], ascending=[True, False], kind="mergesort").iloc[0].copy()
    row["band_id"] = row.get("zone_id", "")
    row["role"] = role
    return row


def _market_structure_zone_item(row: pd.Series) -> dict[str, Any]:
    if row.empty:
        return {}
    return {
        "zone_id": str(row.get("zone_id", row.get("band_id", ""))),
        "role": str(row.get("role", "")),
        "price_lower": _round(float(row.get("price_lower", 0.0) or 0.0)),
        "price_upper": _round(float(row.get("price_upper", 0.0) or 0.0)),
        "strength_score": _round(float(row.get("strength_score", row.get("significance_score", 0.0)) or 0.0)),
        "confidence_tier": str(row.get("confidence_tier", "")),
        "status": str(row.get("status", "")),
    }

def _zone_buckets(
    zones: pd.DataFrame,
    *,
    latest_price: float | None,
    max_zones: int,
) -> dict[str, list[dict[str, Any]]]:
    if zones.empty or latest_price is None:
        return {"near_price": [], "above_price": [], "below_price": []}
    frame = zones.copy()
    frame["distance"] = (frame["price_mid"].astype(float) - float(latest_price)).abs()
    near = frame.sort_values(["distance", "significance_score"], ascending=[True, False], kind="mergesort").head(max_zones)
    above = frame[frame["price_lower"].astype(float) > latest_price].sort_values(
        ["price_lower", "significance_score"], ascending=[True, False], kind="mergesort"
    ).head(max_zones)
    below = frame[frame["price_upper"].astype(float) < latest_price].sort_values(
        ["price_upper", "significance_score"], ascending=[False, False], kind="mergesort"
    ).head(max_zones)
    return {
        "near_price": [_significant_zone_item(row) for _, row in near.iterrows()],
        "above_price": [_significant_zone_item(row) for _, row in above.iterrows()],
        "below_price": [_significant_zone_item(row) for _, row in below.iterrows()],
    }


def _liquidity_buckets(
    zones: pd.DataFrame,
    *,
    latest_price: float | None,
    max_zones: int,
) -> dict[str, list[dict[str, Any]]]:
    if zones.empty or latest_price is None:
        return {"above_price": [], "below_price": []}
    above = zones[zones["price_lower"].astype(float) > latest_price].copy()
    below = zones[zones["price_upper"].astype(float) < latest_price].copy()
    above["distance"] = above["price_lower"].astype(float) - latest_price
    below["distance"] = latest_price - below["price_upper"].astype(float)
    return {
        "above_price": [_liquidity_zone_item(row) for _, row in above.sort_values("distance", kind="mergesort").head(max_zones).iterrows()],
        "below_price": [_liquidity_zone_item(row) for _, row in below.sort_values("distance", kind="mergesort").head(max_zones).iterrows()],
    }


def _significant_zone_item(row: pd.Series) -> dict[str, Any]:
    return {
        "zone_id": row["zone_id"],
        "price_lower": _round(float(row["price_lower"])),
        "price_upper": _round(float(row["price_upper"])),
        "source_zone_count": int(row["source_zone_count"]),
        "source_day_count": int(row["source_day_count"]),
        "dominant_zone_types": row["dominant_zone_types"],
        "significance_score": int(row["significance_score"]),
        "confidence_tier": row["confidence_tier"],
        "status": row["status"],
        "context_1d": row["context_1d"],
        "context_3d": row["context_3d"],
        "context_7d": row["context_7d"],
        "context_30d": row["context_30d"],
        "data_quality": row["data_quality"],
    }


def _liquidity_zone_item(row: pd.Series) -> dict[str, Any]:
    return {
        "zone_id": row["zone_id"],
        "side": row["side"],
        "zone_type": row["zone_type"],
        "price_lower": _round(float(row["price_lower"])),
        "price_upper": _round(float(row["price_upper"])),
        "confidence_tier": row["confidence_tier"],
        "status": row["status"],
        "data_quality": row["data_quality"],
    }


def _context_conflicts(
    *,
    src_event: dict[str, Any],
    local_context: dict[str, Any],
    broad_context: dict[str, Any],
) -> list[dict[str, Any]]:
    direction = str(src_event.get("kind") or src_event.get("direction") or "").lower()
    local_60m = local_context.get("60m", {})
    delta_60m = float(local_60m.get("delta", 0.0) or 0.0)
    broad_3d = str(broad_context.get("3d", {}).get("regime_bias", ""))
    broad_7d = str(broad_context.get("7d", {}).get("regime_bias", ""))
    observations = []
    if direction == "long" and delta_60m > 0 and (
        broad_3d in {"DISTRIBUTION_PRESSURE", "BEARISH_FLOW"}
        or broad_7d in {"DISTRIBUTION_PRESSURE", "BEARISH_FLOW"}
    ):
        observations.append(
            {
                "type": "LOCAL_BUY_FLOW_WITH_BROAD_DISTRIBUTION_CONTEXT",
                "severity": "HIGH" if broad_3d == "DISTRIBUTION_PRESSURE" and broad_7d in {"DISTRIBUTION_PRESSURE", "BEARISH_FLOW"} else "MEDIUM",
                "description": "Local buy-flow context differs from broad 3d/7d market context.",
                "evidence": {
                    "local_60m_delta": _round(delta_60m),
                    "context_3d": broad_3d,
                    "context_7d": broad_7d,
                },
            }
        )
    if direction == "short" and delta_60m < 0 and (
        broad_3d in {"ACCUMULATION_PRESSURE", "BULLISH_FLOW"}
        or broad_7d in {"ACCUMULATION_PRESSURE", "BULLISH_FLOW"}
    ):
        observations.append(
            {
                "type": "LOCAL_SELL_FLOW_WITH_BROAD_ACCUMULATION_CONTEXT",
                "severity": "HIGH" if broad_3d == "ACCUMULATION_PRESSURE" and broad_7d in {"ACCUMULATION_PRESSURE", "BULLISH_FLOW"} else "MEDIUM",
                "description": "Local sell-flow context differs from broad 3d/7d market context.",
                "evidence": {
                    "local_60m_delta": _round(delta_60m),
                    "context_3d": broad_3d,
                    "context_7d": broad_7d,
                },
            }
        )
    return observations


def _quality_summary(frame: pd.DataFrame) -> str:
    if frame.empty or "DataQuality" not in frame.columns:
        return "none"
    counts = frame["DataQuality"].astype(str).value_counts().sort_index()
    return ", ".join(f"{name}={int(count)}" for name, count in counts.items())


def _parse_json(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_roundtrip(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _round(value: float, *, digits: int = 6) -> float:
    return round(float(value), digits)


def _to_utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _format_ts(value) -> str:
    return _to_utc(value).isoformat().replace("+00:00", "Z")
