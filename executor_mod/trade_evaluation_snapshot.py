"""Research contract for a post-fill trade assessment. No model or order calls."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "CANONICAL_TRADE_EVALUATION_SNAPSHOT_V1"
HORIZONS = ("5m", "15m", "30m", "60m", "240m", "1440m", "3d", "7d", "30d")
SIGNAL_FIELDS = ("delta", "vol", "volume", "imb", "imbalance", "vwap", "poc", "strength")
HORIZON_FIELDS = (
    "start_timestamp", "end_timestamp", "expected_rows", "rows_used", "complete",
    "metrics_valid", "status", "missing_timestamps", "missing_timestamp_count", "duplicate_rows", "data_quality_counts",
    "recovered_degraded", "open", "close", "high", "low", "price_change",
    "price_change_pct", "range_position", "delta", "delta_pct", "total_qty",
    "open_interest_change", "vwap_approx", "price_minus_vwap_approx",
    "price_minus_vwap_approx_pct", "poc", "poc_status",
)


class TradeEvaluationSnapshotError(ValueError):
    """The source facts cannot support a safe snapshot."""


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TradeEvaluationSnapshotError(f"invalid timestamp: {value}") from exc
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _round(value: float | None) -> float | None:
    return round(value, 10) if value is not None else None


def _distance_to_band(price: float, lower: float, upper: float) -> float:
    return lower - price if price < lower else upper - price if price > upper else 0.0


def _zone_geometry(zone: Mapping[str, Any], *, category: str, entry: float, tp1: float,
                   tp2: float, risk: float, conversion: float | None) -> dict[str, Any]:
    low = _float(zone.get("price_lower"))
    high = _float(zone.get("price_upper"))
    if low is None or high is None or low > high:
        raise TradeEvaluationSnapshotError("invalid canonical zone bounds")
    converted_low = low * conversion if conversion is not None else None
    converted_high = high * conversion if conversion is not None else None
    distance = _distance_to_band(entry, converted_low, converted_high) if converted_low is not None and converted_high is not None else None
    def between(target: float) -> bool | None:
        if converted_low is None or converted_high is None:
            return None
        return converted_high >= min(entry, target) and converted_low <= max(entry, target)
    return {
        "zone_id": zone.get("zone_id"), "category": category,
        "type": zone.get("zone_type") or zone.get("dominant_zone_types") or zone.get("role"),
        "source_horizon": zone.get("source_window_minutes") or "canonical_39a_zone_registry",
        "quality": zone.get("data_quality"), "qualification": zone.get("status") or zone.get("lifecycle_status"),
        "confidence_tier": zone.get("confidence_tier"),
        "price_lower_market_quote": low, "price_upper_market_quote": high,
        "price_lower_execution_quote_approx": _round(converted_low),
        "price_upper_execution_quote_approx": _round(converted_high),
        "signed_distance_from_actual_entry_usd_approx": _round(distance),
        "signed_distance_from_actual_entry_pct_approx": _round(distance / entry * 100) if distance is not None else None,
        "signed_distance_from_actual_entry_R_approx": _round(distance / risk) if distance is not None else None,
        "intersects_entry_to_tp1": between(tp1), "intersects_entry_to_tp2": between(tp2),
        "signed_distance_from_tp1_usd_approx": _round(_distance_to_band(tp1, converted_low, converted_high)) if converted_low is not None and converted_high is not None else None,
        "signed_distance_from_tp2_usd_approx": _round(_distance_to_band(tp2, converted_low, converted_high)) if converted_low is not None and converted_high is not None else None,
    }


def build_trade_evaluation_snapshot(
    evidence_pack: Mapping[str, Any], monitor: Mapping[str, Any], *,
    assessment_cutoff_utc: str | None,
    assessment_cutoff_source: str,
    signal_facts: Mapping[str, Any] | None = None,
    market_quote_currency: str = "USDT",
    execution_quote_currency: str = "USDC",
    reconstructed: bool = False,
) -> dict[str, Any]:
    """Build an allowlisted model input from contemporaneous facts only.

    An unknown historical invocation time stays null; it is never inferred from
    a verdict journal's later creation time. The monitor has its own earlier
    cutoff and remains explicitly partial when any broad horizon is missing.
    """
    if monitor.get("schema_version") != "market_monitor_snapshot_v39a":
        raise TradeEvaluationSnapshotError("canonical monitor required")
    src = evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), Mapping) else {}
    extra = signal_facts or {}
    fields = extra.get("fields") if isinstance(extra.get("fields"), Mapping) else {}
    side = str(evidence_pack.get("direction") or src.get("kind") or "").lower()
    if side not in {"long", "short"}:
        raise TradeEvaluationSnapshotError("known signal side required")
    signal_ts = _time(extra.get("signal_ts_utc") or evidence_pack.get("peak_ts") or src.get("ts"))
    fill_ts = _time(evidence_pack.get("filled_at"))
    assessment_ts = _time(assessment_cutoff_utc)
    market_ts = _time(monitor.get("cutoff_ts"))
    if signal_ts is None or fill_ts is None or market_ts is None:
        raise TradeEvaluationSnapshotError("signal, observed fill, and market cutoffs required")
    if signal_ts > fill_ts or (assessment_ts is not None and (fill_ts > assessment_ts or market_ts > assessment_ts)):
        raise TradeEvaluationSnapshotError("preassessment chronology invalid")
    if market_ts > fill_ts and assessment_ts is None:
        raise TradeEvaluationSnapshotError("historical market cutoff exceeds last proven preassessment time")
    entry = _float(evidence_pack.get("entry_actual"))
    qty = _float(evidence_pack.get("executedQty")) or _float(evidence_pack.get("qty"))
    prices = evidence_pack.get("prices") if isinstance(evidence_pack.get("prices"), Mapping) else {}
    stop, tp1, tp2 = (_float(prices.get(key)) for key in ("sl", "tp1", "tp2"))
    if any(value is None or value <= 0 for value in (entry, qty, stop, tp1, tp2)):
        raise TradeEvaluationSnapshotError("actual fill and initial execution geometry required")
    assert entry is not None and qty is not None and stop is not None and tp1 is not None and tp2 is not None
    direction = 1 if side == "long" else -1
    risk = (entry - stop) * direction
    if risk <= 0:
        raise TradeEvaluationSnapshotError("initial stop is on wrong side of actual entry")
    k_entry = _float(evidence_pack.get("k_entry"))
    conversion = 1.0 if market_quote_currency == execution_quote_currency else k_entry
    signal_raw = _float(src.get("price_usdt") or src.get("price") or fields.get("price_usdt") or fields.get("price"))
    if signal_raw is None:
        raise TradeEvaluationSnapshotError("source signal price required")
    signal_converted = signal_raw * conversion if conversion is not None else None
    signal_fields = {key: src.get(key, fields.get(key)) for key in SIGNAL_FIELDS if src.get(key, fields.get(key)) is not None}
    reward1, reward2 = ((target - entry) * direction for target in (tp1, tp2))
    horizons = monitor.get("horizons")
    if not isinstance(horizons, Mapping) or any(key not in horizons for key in HORIZONS):
        raise TradeEvaluationSnapshotError("comparable canonical horizons required")
    market_horizons: dict[str, Any] = {}
    if (monitor.get("quality") or {}).get("cutoff_is_latest_used_row") is False:
        raise TradeEvaluationSnapshotError("monitor includes observations beyond cutoff")
    for key in HORIZONS:
        raw = horizons[key]
        if not isinstance(raw, Mapping):
            raise TradeEvaluationSnapshotError(f"invalid {key} horizon")
        if _time(raw.get("end_timestamp")) != market_ts:
            raise TradeEvaluationSnapshotError(f"future or mismatched {key} horizon")
        item = {field: raw.get(field) for field in HORIZON_FIELDS}
        item["current_price_position_in_range"] = item.pop("range_position")
        market_horizons[key] = item
    zones = []
    seen: set[tuple[str, str]] = set()
    structure_state = monitor.get("market_structure_state") or {}
    for category, candidates in (
        ("nearest_qualified_support", [structure_state.get("support")]),
        ("nearest_qualified_resistance", [structure_state.get("resistance")]),
        ("significant", [z for bucket in (monitor.get("significant_market_zones") or {}).values() for z in bucket]),
        ("liquidity", [z for bucket in (monitor.get("liquidity_zones") or {}).values() for z in bucket]),
    ):
        for zone in candidates:
            if not isinstance(zone, Mapping) or not zone.get("zone_id"):
                continue
            if category.startswith("nearest_qualified_") and zone.get("status") not in {"SIGNIFICANT", "QUALIFIED"}:
                continue
            identity = (category, str(zone["zone_id"]))
            if identity in seen:
                continue
            seen.add(identity)
            zones.append(_zone_geometry(zone, category=category, entry=entry, tp1=tp1, tp2=tp2, risk=risk, conversion=conversion))
    state = monitor.get("market_state") or {}
    conflicts = monitor.get("context_conflicts") or []
    quality = monitor.get("quality") or {}
    missing = []
    if assessment_ts is None:
        missing.append("exact_judge_invocation_cutoff_not_durable")
    if conversion is None:
        missing.append("market_to_execution_quote_conversion_missing")
    if quality.get("readiness") != "READY":
        missing.append("market_monitor_" + str(quality.get("readiness", "UNKNOWN")).lower())
    if not signal_fields:
        missing.append("signal_measurements_missing")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "assessment_cutoff_utc": _iso(assessment_ts),
        "assessment_cutoff_source": assessment_cutoff_source,
        "market_cutoff_utc": _iso(market_ts),
        "signal": {
            "source": "DeltaScout PEAK", "trade_key": evidence_pack.get("trade_key"), "side": side,
            "signal_time_utc": _iso(signal_ts), "signal_price": signal_raw,
            "signal_quote_currency": market_quote_currency, "measurements": signal_fields,
            "upstream_source": src.get("source"), "upstream_action": src.get("action"),
            "raw_signal_plan_usdt": {
                key: _float(src.get(key)) for key in ("entry_usdt", "sl_usdt", "tp1_usdt", "tp2_usdt")
            },
            "measurement_provenance": "durable_src_evt_or_frozen_signal_research_record",
        },
        "execution": {
            "source": "Executor position at EXITS_PLACED_V15 Judge hook",
            "actual_entry_price": entry, "actual_fill_timestamp_utc": _iso(fill_ts),
            "actual_fill_timestamp_semantics": "executor_observed_fill_time_not_exchange_transaction_time",
            "filled_qty": qty, "filled_qty_source": "executedQty" if _float(evidence_pack.get("executedQty")) else "position_qty",
            "entry_mode": evidence_pack.get("entry_mode"), "execution_quote_currency": execution_quote_currency,
            "signal_price": signal_raw, "signal_price_in_execution_quote_approx": _round(signal_converted),
            "quote_conversion_at_entry_approx": conversion,
            "entry_minus_signal_usd_approx": _round(entry - signal_converted) if signal_converted is not None else None,
            "entry_minus_signal_pct_approx": _round((entry / signal_converted - 1) * 100) if signal_converted else None,
            "initial_stop_price": stop, "tp1_price": tp1, "tp2_price": tp2,
            "risk_entry_to_sl_usd": _round(risk), "risk_entry_to_sl_pct": _round(risk / entry * 100),
            "reward_entry_to_tp1_usd": _round(reward1), "reward_entry_to_tp1_pct": _round(reward1 / entry * 100),
            "tp1_R": _round(reward1 / risk),
            "reward_entry_to_tp2_usd": _round(reward2), "reward_entry_to_tp2_pct": _round(reward2 / entry * 100),
            "tp2_R": _round(reward2 / risk),
            "initial_stop_provenance": "Executor_position.prices.sl_at_judge_hook",
            "initial_targets_provenance": "Executor_position.prices.tp1_tp2_at_judge_hook",
            "fill_provenance": "Executor_position.entry_actual_at_judge_hook",
        },
        "market": {
            "source": "canonical_39a_monitor", "schema_version": monitor["schema_version"],
            "market_quote_currency": market_quote_currency, "cutoff_utc": _iso(market_ts),
            "current_price": (monitor.get("current") or {}).get("price"),
            "horizon_aliases": {"1d": "1440m"}, "horizons": market_horizons,
            "zones": zones,
            "classifiers": {
                "rolling_market_state": {"role": "derived_regime_interpretation", "scope": "rolling_1440_closed_minutes", "algorithm": state.get("algorithm"), "state": state.get("state"), "confidence_tier": state.get("confidence_tier")},
                "rolling_structure_state": {"role": "derived_structure_interpretation", "scope": "rolling_1440_closed_minutes_with_canonical_zones", "algorithm": structure_state.get("algorithm"), "state": structure_state.get("state"), "confidence_tier": structure_state.get("confidence_tier")},
                "candidate_bias": {"role": "derived_subfield_of_rolling_structure_state_not_independent_signal", "value": structure_state.get("candidate_bias")},
                "context_conflicts": {"role": "derived_local_60m_vs_broad_3d_7d_observations", "observations": conflicts},
            },
        },
        "quality": {
            "status": "PARTIAL" if missing else "READY", "missing_or_degraded": missing,
            "monitor_readiness": quality.get("readiness"),
            "incomplete_horizons": [key for key, row in market_horizons.items() if not row.get("complete")],
            "recovered_degraded_present": quality.get("recovered_degraded_present"),
            "exact_assessment_cutoff": assessment_ts is not None,
            "reconstructed": reconstructed,
            "market_rows_after_cutoff_excluded": (quality.get("future_rows_excluded") or 0),
            "units": {"price": "quote_currency_per_BTC", "price_distance": "execution_quote_currency_per_BTC", "price_change_pct": "percent", "delta": "BTC", "delta_pct": "fraction_of_total_qty", "range_position": "fraction_low_to_high", "open_interest_change": "feed_contract_units", "vwap_approx": "OHLC_typical_price_weighted_by_TotalQty", "poc": "unavailable_without_price_volume_distribution"},
        },
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    snapshot["snapshot_sha256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return snapshot
