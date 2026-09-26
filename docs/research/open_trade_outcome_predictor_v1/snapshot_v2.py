"""Outcome-blind, research-only snapshot for an already opened trade.

Only frozen pre-outcome signal/execution facts and verified source feed rows enter
this builder. The caller must clip the feed to the conservative fill-minute
cutoff before calling it. No production module imports this file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from market_monitor.accumulation_zones import build_accumulation_zones
from market_monitor.context_windows import CONTEXT_WINDOW_DAYS, build_market_context_windows
from market_monitor.feed_adapter import HISTORICAL_TO_PROTECTED, load_feed
from market_monitor.liquidity_zones import build_liquidity_map
from market_monitor.outputs import build_volume_delta_state
from market_monitor.significant_market_zones import build_significant_market_zones
from market_monitor.structure import build_structure_levels
from market_monitor.zone_registry import build_zone_registry, forward_liquidity_from_registry


SCHEMA_VERSION = "OPEN_TRADE_OUTCOME_PREDICTOR_SNAPSHOT_V2"
MODEL_BLOCKS = ("signal", "execution", "temporal_market", "structure_geometry", "quality")
SEGMENTS = (
    ("T-1440_TO_T-240", 1439, 240),
    ("T-240_TO_T-60", 239, 60),
    ("T-60_TO_T-15", 59, 15),
    ("T-15_TO_T-5", 14, 5),
    ("T-5_TO_T0", 4, 0),
)
RAW_COLUMNS = ("OpenPrice", "ClosePrice", "HiPrice", "LowPrice", "TotalQty", "BuyQty", "SellQty", "OpenInterest")
QUALIFIED = {"SIGNIFICANT", "QUALIFIED"}
FORBIDDEN_MODEL_KEYS = {
    "outcome", "lifecycle_class", "tp1_done", "tp2_done", "sl_done", "trailing",
    "realized_pnl", "pnl", "verdict", "historical_verdict", "last_closed",
}


class SnapshotContractError(ValueError):
    """Pre-outcome source evidence does not satisfy the frozen contract."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc(value: Any) -> pd.Timestamp:
    result = pd.Timestamp(value)
    if pd.isna(result):
        raise SnapshotContractError("timestamp unavailable")
    return result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")


def iso(value: pd.Timestamp) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    if not pd.notna(number):
        return None
    return round(number, 10)


def source_columns(paths: list[Path]) -> dict[str, set[str]]:
    result = {}
    for path in paths:
        columns = set(pd.read_csv(path, nrows=0).columns)
        result[path.name] = {HISTORICAL_TO_PROTECTED.get(name, name) for name in columns}
    return result


def load_verified_feed(paths: list[Path], cutoff: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, set[str]]]:
    """Normalize verified files while retaining pre-normalization column facts."""
    columns = source_columns(paths)
    feed = load_feed(paths)
    cutoff = utc(cutoff).floor("min")
    feed = feed.loc[feed["Timestamp"] <= cutoff].copy()
    if feed.empty:
        raise SnapshotContractError("no feed rows at prediction cutoff")
    for path in paths:
        raw = pd.read_csv(path, usecols=lambda name: name in {"Timestamp", "IsSynthetic"})
        times = pd.to_datetime(raw["Timestamp"], utc=True, errors="raise")
        degraded = ("feed_recovered" in {part.lower() for part in path.parts}) or (
            "IsSynthetic" in raw and pd.to_numeric(raw.loc[times <= cutoff, "IsSynthetic"], errors="coerce").fillna(0).ne(0).any()
        )
        feed.loc[feed["SourceFile"] == path.name, "DataQuality"] = "RECOVERED_DEGRADED" if degraded else "RAW"
    return feed, columns


def _window(frame: pd.DataFrame, cutoff: pd.Timestamp, first_offset: int, last_offset: int,
            columns: Mapping[str, set[str]]) -> dict[str, Any]:
    start = cutoff - pd.Timedelta(minutes=first_offset)
    end = cutoff - pd.Timedelta(minutes=last_offset)
    rows = frame.loc[(frame["Timestamp"] >= start) & (frame["Timestamp"] <= end)].copy()
    expected = first_offset - last_offset + 1
    timestamps = pd.DatetimeIndex(rows["Timestamp"])
    complete = len(rows) == expected and not timestamps.has_duplicates and len(pd.date_range(start, end, freq="min").difference(timestamps)) == 0
    files = sorted(set(rows["SourceFile"].astype(str)))
    missing_columns = sorted({name for file in files for name in RAW_COLUMNS if name not in columns[file]})
    quality = sorted(set(rows["DataQuality"].astype(str)))
    item: dict[str, Any] = {
        "start_timestamp": iso(start), "end_timestamp": iso(end),
        "rows_expected": expected, "rows_used": len(rows), "complete": complete,
        "source_quality": "EMPTY" if rows.empty else "RECOVERED_DEGRADED" if "RECOVERED_DEGRADED" in quality else "RAW",
    }
    if rows.empty:
        item.update({name: None for name in ("price_open", "price_close", "high", "low", "price_change_pct", "delta", "total_qty", "delta_pct", "open_interest_change")})
        return item
    first = rows.iloc[0]
    last = rows.iloc[-1]
    price_open = float(first["OpenPrice"])
    price_close = float(last["ClosePrice"])
    delta = float((rows["BuyQty"] - rows["SellQty"]).sum()) if not ({"BuyQty", "SellQty"} & set(missing_columns)) else None
    qty = float(rows["TotalQty"].sum()) if "TotalQty" not in missing_columns else None
    oi = float(last["OpenInterest"] - first["OpenInterest"]) if "OpenInterest" not in missing_columns else None
    item.update({
        "price_open": _number(price_open), "price_close": _number(price_close),
        "high": _number(rows["HiPrice"].max()), "low": _number(rows["LowPrice"].min()),
        "price_change_pct": _number((price_close / price_open - 1) * 100) if price_open else None,
        "delta": _number(delta), "total_qty": _number(qty),
        "delta_pct": _number(delta / qty) if delta is not None and qty else (0.0 if qty == 0 else None),
        "open_interest_change": _number(oi),
    })
    return item


def _range_location(rows: pd.DataFrame, price: float) -> dict[str, Any]:
    if rows.empty:
        return {name: None for name in ("high", "low", "position_in_range", "distance_to_high", "distance_to_low")}
    high, low = float(rows["HiPrice"].max()), float(rows["LowPrice"].min())
    return {
        "high": _number(high), "low": _number(low),
        "position_in_range": _number((price - low) / (high - low)) if high != low else 0.5,
        "distance_to_high": _number(high - price), "distance_to_low": _number(price - low),
    }


def _structure_frames(current: pd.DataFrame, context: pd.DataFrame, cutoff: pd.Timestamp):
    price = float(current.iloc[-1]["ClosePrice"])
    levels = build_structure_levels(current)
    liquidity_map = build_liquidity_map(levels, price)
    registry, _ = build_zone_registry(liquidity_map=liquidity_map, feed=current)
    active = forward_liquidity_from_registry(registry, price)
    context_rows = []
    for days in CONTEXT_WINDOW_DAYS:
        start = cutoff - pd.Timedelta(minutes=days * 1440 - 1)
        scoped = context.loc[(context["Timestamp"] >= start) & (context["Timestamp"] <= cutoff)]
        built = build_market_context_windows(scoped, end_timestamp=cutoff, windows_days=(days,))
        if not built.empty:
            context_rows.append(built.iloc[0].to_dict())
    context_windows = pd.DataFrame(context_rows)
    inventory = build_accumulation_zones(context, build_volume_delta_state(context))
    significant = build_significant_market_zones(
        inventory_zones=inventory, liquidity_zone_registry=registry, market_context_windows=context_windows,
    )
    return registry, active, significant


def _zone_fact(zone: Mapping[str, Any], *, cutoff: pd.Timestamp, current: pd.DataFrame) -> dict[str, Any]:
    lower, upper = float(zone["price_lower"]), float(zone["price_upper"])
    first_seen = str(zone.get("first_seen_at") or zone.get("created_at") or "")
    history = current.loc[current["Timestamp"] >= utc(first_seen)] if first_seen else current.iloc[0:0]
    interactions = history.loc[(history["HiPrice"] >= lower) & (history["LowPrice"] <= upper)]
    def prior(name: str) -> str | None:
        value = str(zone.get(name) or "")
        if value and utc(value) > cutoff:
            raise SnapshotContractError(f"zone {name} after prediction cutoff")
        return value or None
    return {
        "zone_id": str(zone.get("zone_id") or ""),
        "zone_type": str(zone.get("zone_type") or zone.get("dominant_zone_types") or ""),
        "lower": _number(lower), "upper": _number(upper),
        "status": str(zone.get("status") or ""),
        "consumption_status": str(zone.get("consumption_status") or "") or None,
        "first_sweep_timestamp": prior("first_sweep_at"),
        "resweep_count": int(float(zone.get("resweep_count") or 0)),
        "close_above_count": int(float(zone.get("close_above_count") or 0)),
        "close_below_count": int(float(zone.get("close_below_count") or 0)),
        "accepted_above_timestamp": prior("accepted_above_at"),
        "accepted_below_timestamp": prior("accepted_below_at"),
        "failed_acceptance_count": int(float(zone.get("failed_acceptance_count") or 0)),
        "last_clean_reaction_timestamp": prior("last_clean_reaction_at"),
        "interaction_count": int(len(interactions)),
        "last_interaction_timestamp": iso(interactions.iloc[-1]["Timestamp"]) if not interactions.empty else None,
        "consumed_timestamp": prior("consumed_at"),
        "consumption_reason": str(zone.get("consumption_reason") or "") or None,
        "data_quality": str(zone.get("data_quality") or "") or None,
    }


def _nearest_qualified(significant: pd.DataFrame, price: float, side: str) -> dict[str, Any] | None:
    """Filter qualifications before any nearest-zone selection."""
    if significant.empty:
        return None
    qualified = significant.loc[significant["status"].isin(QUALIFIED)].copy()
    if side == "long":
        qualified = qualified.loc[qualified["price_upper"].astype(float) >= price].copy()
        qualified["distance"] = (qualified["price_lower"].astype(float) - price).clip(lower=0)
    else:
        qualified = qualified.loc[qualified["price_lower"].astype(float) <= price].copy()
        qualified["distance"] = (price - qualified["price_upper"].astype(float)).clip(lower=0)
    if qualified.empty:
        return None
    qualified = qualified.sort_values(["distance", "zone_id"], kind="mergesort")
    return qualified.iloc[0].to_dict()


def _matched_registry(zone: Mapping[str, Any], registry: pd.DataFrame) -> dict[str, Any] | None:
    if registry.empty:
        return None
    lower, upper = float(zone["price_lower"]), float(zone["price_upper"])
    overlaps = registry.loc[(registry["price_upper"].astype(float) >= lower) & (registry["price_lower"].astype(float) <= upper)].copy()
    if overlaps.empty:
        return None
    midpoint = (lower + upper) / 2
    overlaps["distance"] = (overlaps["price_mid"].astype(float) - midpoint).abs()
    return overlaps.sort_values(["distance", "zone_id"], kind="mergesort").iloc[0].to_dict()


def _recent_cleared(registry: pd.DataFrame, current: pd.DataFrame, cutoff: pd.Timestamp,
                    price: float, side: str) -> dict[str, Any] | None:
    if registry.empty:
        return None
    field = "accepted_above_at" if side == "long" else "accepted_below_at"
    candidates = []
    for zone in registry.to_dict("records"):
        if zone.get("side") != ("BUY_SIDE" if side == "long" else "SELL_SIDE"):
            continue
        accepted = str(zone.get(field) or "")
        if not accepted or utc(accepted) > cutoff:
            continue
        if side == "long" and price <= float(zone["price_upper"]):
            continue
        if side == "short" and price >= float(zone["price_lower"]):
            continue
        candidates.append(zone)
    if not candidates:
        return None
    selected = sorted(candidates, key=lambda z: (utc(z[field]), str(z["zone_id"])), reverse=True)[0]
    result = _zone_fact(selected, cutoff=cutoff, current=current)
    accepted = utc(selected[field])
    later = current.loc[current["Timestamp"] > accepted]
    lower, upper = float(selected["price_lower"]), float(selected["price_upper"])
    result.update({
        "accepted_beyond_timestamp": iso(accepted),
        "minutes_since_acceptance": int((cutoff - accepted).total_seconds() // 60),
        "distance_current_price_beyond_zone": _number(price - upper if side == "long" else lower - price),
        "returned_inside_after_acceptance": bool(later["ClosePrice"].between(lower, upper).any()),
        "returned_through_opposite_boundary_after_acceptance": bool((later["ClosePrice"] < lower).any() if side == "long" else (later["ClosePrice"] > upper).any()),
    })
    return result


def _target_relation(target: float, lower: float, upper: float, side: str) -> str:
    if side == "long":
        return "BEFORE" if target < lower else "BEYOND" if target > upper else "INSIDE"
    return "BEFORE" if target > upper else "BEYOND" if target < lower else "INSIDE"


def _structure_view(current: pd.DataFrame, context: pd.DataFrame, cutoff: pd.Timestamp,
                    execution: Mapping[str, Any], side: str) -> tuple[dict[str, Any], list[str]]:
    price = float(current.iloc[-1]["ClosePrice"])
    registry, active, significant = _structure_frames(current, context, cutoff)
    nearest = _nearest_qualified(significant, price, side)
    lifecycle = _matched_registry(nearest, registry) if nearest else None
    zone = _zone_fact(nearest, cutoff=cutoff, current=context) if nearest else None
    if zone is not None:
        zone["qualification"] = str(nearest["status"])
        zone["matched_registry_lifecycle"] = _zone_fact(lifecycle, cutoff=cutoff, current=current) if lifecycle else None
        zone["price_position"] = "BEFORE" if (price < zone["lower"] if side == "long" else price > zone["upper"]) else "BEYOND" if (price > zone["upper"] if side == "long" else price < zone["lower"]) else "INSIDE"
        zone["distance_from_current_price_market_quote"] = _number(max(0, zone["lower"] - price) if side == "long" else max(0, price - zone["upper"]))
        last = zone["last_interaction_timestamp"]
        zone["minutes_since_last_interaction"] = int((cutoff - utc(last)).total_seconds() // 60) if last else None
    forward = active.loc[active["side"] == ("BUY_SIDE" if side == "long" else "SELL_SIDE")].copy() if not active.empty else active
    if not forward.empty:
        forward["distance"] = (forward["price_lower"].astype(float) - price) if side == "long" else (price - forward["price_upper"].astype(float))
        liquidity = forward.sort_values(["distance", "zone_id"], kind="mergesort").iloc[0].to_dict()
        liquidity_view = {"zone_id": str(liquidity["zone_id"]), "side": str(liquidity["side"]), "lower": _number(liquidity["price_lower"]), "upper": _number(liquidity["price_upper"]), "distance_from_current_price": _number(liquidity["distance"])}
    else:
        liquidity_view = None
    conversion = execution.get("quote_conversion_at_entry_approx")
    entry, risk = float(execution["actual_entry_price"]), float(execution["risk_entry_to_sl_usd"])
    geometry = None
    if zone is not None:
        boundary = zone["lower"] if side == "long" else zone["upper"]
        converted = boundary * float(conversion) if conversion is not None else None
        geometry = {
            "near_boundary_market_quote": _number(boundary),
            "distance_from_actual_entry_execution_quote_approx": _number((converted - entry) * (1 if side == "long" else -1)) if converted is not None else None,
            "distance_from_actual_entry_R_approx": _number(((converted - entry) * (1 if side == "long" else -1)) / risk) if converted is not None else None,
            "tp1_relation": _target_relation(float(execution["tp1_price"]), zone["lower"] * float(conversion), zone["upper"] * float(conversion), side) if conversion is not None else None,
            "tp2_relation": _target_relation(float(execution["tp2_price"]), zone["lower"] * float(conversion), zone["upper"] * float(conversion), side) if conversion is not None else None,
        }
    recent = _recent_cleared(registry, current, cutoff, price, side)
    missing = []
    if nearest is None:
        missing.append("qualified_opposing_zone_unavailable")
    elif lifecycle is None:
        missing.append("opposing_zone_registry_lifecycle_unavailable")
    if conversion is None:
        missing.append("market_to_execution_quote_conversion_unavailable")
    return {
        "current_price_market_quote": _number(price),
        "range_240m": _range_location(current.tail(240), price),
        "range_1440m": _range_location(current.tail(1440), price),
        "nearest_qualified_opposing_zone": zone,
        "recent_cleared_structure_in_trade_direction": recent,
        "nearest_active_liquidity_in_trade_direction": liquidity_view,
        "target_clear_air_geometry": geometry,
    }, missing


def assert_model_view(snapshot: Mapping[str, Any]) -> None:
    if set(snapshot) != set(MODEL_BLOCKS):
        raise SnapshotContractError("model input must have exactly five blocks")
    def walk(value: Any):
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key).lower() in FORBIDDEN_MODEL_KEYS:
                    raise SnapshotContractError(f"forbidden future field: {key}")
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
    walk(snapshot)
    canonical_json(snapshot)


def build_snapshot(source: Mapping[str, Any], feed: pd.DataFrame,
                   columns: Mapping[str, set[str]]) -> dict[str, Any]:
    """Build five model-facing blocks from a frozen V1 fact seed and raw rows."""
    signal = dict(source["signal"])
    execution = dict(source["execution"])
    side = str(signal["side"])
    if side not in {"long", "short"}:
        raise SnapshotContractError("unknown side")
    signal_ts, fill = utc(signal["signal_time_utc"]), utc(execution["actual_fill_timestamp_utc"])
    if signal_ts > fill:
        raise SnapshotContractError("signal after observed fill")
    cutoff = fill.floor("min")
    if (feed["Timestamp"] > cutoff).any():
        raise SnapshotContractError("post-prediction feed row supplied")
    current = feed.loc[feed["Timestamp"] >= cutoff - pd.Timedelta(minutes=1439)].copy()
    if current.empty or current["Timestamp"].max() != cutoff:
        raise SnapshotContractError("cutoff market row unavailable")
    if current["Timestamp"].duplicated().any():
        raise SnapshotContractError("duplicate source minute in temporal market")
    segments = [{"segment": name, **_window(current, cutoff, first, last, columns)} for name, first, last in SEGMENTS]
    if all(item["complete"] and item["delta"] is not None and item["total_qty"] is not None for item in segments):
        parent_delta = float((current["BuyQty"] - current["SellQty"]).sum())
        parent_qty = float(current["TotalQty"].sum())
        if abs(sum(item["delta"] for item in segments) - parent_delta) > 1e-7:
            raise SnapshotContractError("segment Delta does not reconcile")
        if abs(sum(item["total_qty"] for item in segments) - parent_qty) > 1e-7:
            raise SnapshotContractError("segment TotalQty does not reconcile")
    broad = {name: _window(feed, cutoff, minutes - 1, 0, columns) for name, minutes in (("1d", 1440), ("3d", 4320), ("7d", 10080))}
    broad = {name: {key: item[key] for key in ("price_change_pct", "delta_pct", "complete", "source_quality", "rows_expected", "rows_used")} for name, item in broad.items()}
    source_files = sorted(set(current["SourceFile"].astype(str)))
    missing_columns = sorted({name for file in source_files for name in RAW_COLUMNS if name not in columns[file]})
    open_fallback = "OpenPrice" in missing_columns
    structure, structure_missing = _structure_view(current, feed, cutoff, execution, side)
    missing = list(structure_missing)
    if "OpenInterest" in missing_columns:
        missing.append("open_interest_source_column_unavailable")
    if open_fallback:
        missing.append("open_price_source_column_unavailable_close_fallback")
    if any(not item["complete"] for item in segments):
        missing.append("temporal_segment_incomplete")
    if not signal.get("measurements"):
        missing.append("durable_signal_measurements_unavailable")
    snapshot = {
        "signal": {
            "trade_key": signal["trade_key"], "side": side,
            "peak_timestamp_utc": iso(signal_ts), "signal_price": signal.get("signal_price"),
            "signal_quote_currency": signal.get("signal_quote_currency"),
            "measurements": signal.get("measurements") or {},
            "raw_signal_plan_usdt": signal.get("raw_signal_plan_usdt") or {},
        },
        "execution": {
            "actual_entry_price": execution["actual_entry_price"],
            "executor_observed_fill_timestamp_utc": iso(fill),
            "filled_quantity": execution["filled_qty"],
            "initial_sl": execution["initial_stop_price"],
            "initial_tp1": execution["tp1_price"], "initial_tp2": execution["tp2_price"],
            "entry_to_sl_risk": execution["risk_entry_to_sl_usd"],
            "tp1_reward": execution["reward_entry_to_tp1_usd"], "tp1_R": execution["tp1_R"],
            "tp2_reward": execution["reward_entry_to_tp2_usd"], "tp2_R": execution["tp2_R"],
            "entry_minus_signal_distance_approx": execution.get("entry_minus_signal_usd_approx"),
            "entry_minus_signal_pct_approx": execution.get("entry_minus_signal_pct_approx"),
            "signal_to_fill_elapsed_seconds": _number((fill - signal_ts).total_seconds()),
            "quote_conversion_at_entry_approx": execution.get("quote_conversion_at_entry_approx"),
            "execution_quote_currency": execution.get("execution_quote_currency"),
        },
        "temporal_market": {
            "prediction_market_cutoff_utc": iso(cutoff),
            "market_bar_cutoff_utc": iso(cutoff),
            "segments": segments, "broad_context": broad,
        },
        "structure_geometry": structure,
        "quality": {
            "snapshot_schema_version": SCHEMA_VERSION,
            "prediction_cutoff_utc": iso(fill),
            "prediction_cutoff_source": "historical_executor_fill_proxy",
            "market_cutoff_contract": "UTC_minute_close_label_inclusive",
            "missing_source_columns": missing_columns,
            "incomplete_segments": [item["segment"] for item in segments if not item["complete"]],
            "incomplete_broad_context": [name for name, item in broad.items() if not item["complete"]],
            "degraded_or_recovered_feed": any(item["source_quality"] == "RECOVERED_DEGRADED" for item in segments),
            "open_price_close_fallback": open_fallback,
            "open_interest_available": "OpenInterest" not in missing_columns,
            "conversion_available": execution.get("quote_conversion_at_entry_approx") is not None,
            "zone_history_available": not any(code in missing for code in ("qualified_opposing_zone_unavailable", "opposing_zone_registry_lifecycle_unavailable")),
            "historical_prediction_cutoff_proxy": True,
            "chronology_anomaly": "signal_to_fill_delay_over_one_hour" if (fill - signal_ts).total_seconds() > 3600 else None,
            "missing_evidence": sorted(set(missing)),
            "units": {"price": "market_USDT_or_execution_USDC_per_BTC_as_labeled", "delta": "BTC", "total_qty": "BTC", "delta_pct": "fraction_of_total_qty", "open_interest_change": "feed_contract_units"},
        },
    }
    assert_model_view(snapshot)
    return snapshot
