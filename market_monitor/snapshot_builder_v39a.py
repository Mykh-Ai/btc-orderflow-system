"""One production Market Monitor: exact 39A windows and direct source features."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from market_monitor.canonical_features import build_canonical_features


SNAPSHOT_SCHEMA_VERSION = "market_monitor_snapshot_v39a"
STATE_SCHEMA_VERSION = "SHI_RESET_39A_RUNTIME_STATE_CARRY_FORWARD_V1"
LOCAL_WINDOWS_MINUTES = (5, 15, 30, 60, 240, 1440)
_ALIASES = {
    "Open": "OpenPrice",
    "High": "HiPrice",
    "Low": "LowPrice",
    "Close": "ClosePrice",
    "Volume": "TotalQty",
    "AggTrades": "Trades",
}
_REQUIRED_PRICE = ("OpenPrice", "HiPrice", "LowPrice", "ClosePrice")
_NUMERIC = (
    "OpenPrice",
    "HiPrice",
    "LowPrice",
    "ClosePrice",
    "TotalQty",
    "Trades",
    "BuyQty",
    "SellQty",
    "OpenInterest",
    "FundingRate",
    "LiqBuyQty",
    "LiqSellQty",
)


class MonitorSnapshotV39AError(ValueError):
    """Raised when the v39A monitor input or state contract is invalid."""


def build_market_monitor_snapshot_v39a(
    feed: pd.DataFrame,
    *,
    context_feed: pd.DataFrame | None = None,
    cutoff_ts: Any | None = None,
    state_path: str | Path | None = None,
    symbol: str = "",
    src_event: Mapping[str, Any] | None = None,
    max_zones: int = 5,
    lineage: Mapping[str, Any] | None = None,
    persist_state: bool = True,
) -> dict[str, Any]:
    """Build descriptive entry evidence using only rows at or before cutoff."""
    frame = _normalise_feed(feed)
    if frame.empty:
        raise MonitorSnapshotV39AError("feed is empty")
    cutoff = _resolve_cutoff(frame, cutoff_ts)
    current = frame[frame["Timestamp"] <= cutoff].copy()
    if current.empty:
        raise MonitorSnapshotV39AError("no feed rows at or before cutoff")
    context = _normalise_feed(context_feed) if context_feed is not None else current.copy()
    context = context[
        (context["Timestamp"] <= cutoff)
        & (context["Timestamp"] >= cutoff - pd.Timedelta(days=30))
    ].copy()
    previous_state, state_load = _load_state(state_path)
    if state_load["status"] in {"INVALID", "INCOMPATIBLE"}:
        raise MonitorSnapshotV39AError("persisted monitor state is invalid")
    previous_cutoff = _parse_ts((previous_state or {}).get("last_cutoff_ts"))
    if previous_cutoff is not None and previous_cutoff > cutoff:
        raise MonitorSnapshotV39AError("persisted monitor state is newer than cutoff")
    windows = {
        str(minutes): _window_metrics(current, minutes=minutes, cutoff=cutoff)
        for minutes in LOCAL_WINDOWS_MINUTES
    }
    horizons = {f"{minutes}m": windows[str(minutes)] for minutes in LOCAL_WINDOWS_MINUTES}
    horizons.update({
        f"{days}d": _window_metrics(context, minutes=days * 1440, cutoff=cutoff)
        for days in (3, 7, 30)
    })
    quality = _quality_summary(frame, current, context, windows, horizons, cutoff)
    current_price = float(current.iloc[-1]["ClosePrice"])
    complete = quality["readiness"] != "INCOMPLETE"
    if complete:
        start = cutoff - pd.Timedelta(minutes=1439)
        rolling = current[current["Timestamp"] >= start].copy()
        features = build_canonical_features(
            rolling,
            context,
            cutoff=cutoff,
            windows=windows,
            src_event=dict(src_event or {}),
            max_zones=max_zones,
        )
    else:
        features = {
            "market_state": {"status": "UNAVAILABLE_INCOMPLETE_WINDOW"},
            "market_structure_state": {"status": "UNAVAILABLE_INCOMPLETE_WINDOW"},
            "broad_context": {},
            "significant_market_zones": {"near_price": [], "above_price": [], "below_price": []},
            "liquidity_zones": {"above_price": [], "below_price": []},
            "context_conflicts": [],
            "diagnostics": {},
        }
    structure = _structure_summary(windows, current_price)
    state_memory, next_state = _advance_state(
        previous_state=previous_state,
        state_load=state_load,
        cutoff=cutoff,
        structure=structure,
        zones=features["liquidity_zones"],
        market_state=features["market_state"],
        quality=quality,
    )
    if state_path is not None and persist_state and complete:
        _write_state(Path(state_path), next_state)

    source_files = sorted({str(x) for x in context["SourceFile"].dropna().tolist()})
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "cutoff_ts": _format_ts(cutoff),
        "symbol": symbol,
        "bar_contract": {
            "timestamp_semantics": "UTC_minute_close_label",
            "closed_rows_only": True,
            "cutoff_inclusive": True,
            "windows_minutes": list(LOCAL_WINDOWS_MINUTES),
            "horizon_aliases": {"1d": "1440m"},
        },
        "current": {
            "price": round(current_price, 8),
            "rows_used": int(len(current)),
            "last_timestamp": _format_ts(current["Timestamp"].iloc[-1]),
        },
        "units": {
            "price": "quote_currency_per_base_asset",
            "quantity": "base_asset",
            "delta": "base_asset",
            "delta_pct": "fraction_of_total_qty",
            "price_change_pct": "percent",
            "range_position": "fraction_low_to_high",
            "open_interest_change": "feed_contract_units",
            "vwap_approx": "quote_currency_per_base_asset; OHLC_typical_price_weighted_by_TotalQty",
            "poc": "unavailable_without_price_volume_distribution",
        },
        "windows": windows,
        "horizons": horizons,
        "market_state": features["market_state"],
        "market_structure_state": features["market_structure_state"],
        "structure": structure,
        "significant_market_zones": features["significant_market_zones"],
        "liquidity_zones": features["liquidity_zones"],
        "broad_context": features["broad_context"],
        "context_conflicts": features["context_conflicts"],
        "diagnostics": features["diagnostics"],
        "state_memory": state_memory,
        "quality": quality,
        "lineage": {
            "source_files": source_files,
            "source_file_count": len(source_files),
            "source_hashes": dict((lineage or {}).get("source_hashes", {})),
            "feed_identity": (lineage or {}).get("feed_identity", "") or "",
            "feature_algorithms": ["structure_levels", "zone_registry", "significant_market_zones", "market_state_timeline", "market_structure_state"],
            "state_file": str(state_path) if state_path is not None else "",
            "state_schema_version": STATE_SCHEMA_VERSION,
        },
        "boundary": "descriptive monitor state only; no orders, outcomes, PnL, or trailing",
    }
    return _json_safe(snapshot)


def _normalise_feed(feed: pd.DataFrame | None) -> pd.DataFrame:
    if feed is None:
        return pd.DataFrame()
    frame = feed.copy()
    frame = frame.rename(columns={key: value for key, value in _ALIASES.items() if key in frame.columns})
    if "Timestamp" not in frame.columns:
        raise MonitorSnapshotV39AError("feed missing Timestamp")
    missing = [column for column in _REQUIRED_PRICE if column not in frame.columns]
    if missing:
        raise MonitorSnapshotV39AError("feed missing price columns: " + ", ".join(missing))
    for column in _NUMERIC:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any():
            raise MonitorSnapshotV39AError(f"invalid numeric values in {column}")
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=True, errors="coerce")
    if frame["Timestamp"].isna().any():
        raise MonitorSnapshotV39AError("invalid Timestamp values")
    if "DataQuality" not in frame.columns:
        if "IsSynthetic" in frame.columns:
            synthetic = pd.to_numeric(frame["IsSynthetic"], errors="coerce").fillna(0)
            frame["DataQuality"] = synthetic.ne(0).map({True: "RECOVERED_DEGRADED", False: "RAW"})
        else:
            frame["DataQuality"] = "RAW"
    frame["DataQuality"] = frame["DataQuality"].fillna("UNKNOWN").astype(str)
    if "SourceFile" not in frame.columns:
        frame["SourceFile"] = "in_memory_feed"
    return frame.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)


def _resolve_cutoff(frame: pd.DataFrame, cutoff_ts: Any | None) -> pd.Timestamp:
    cutoff = pd.Timestamp(cutoff_ts) if cutoff_ts is not None else pd.Timestamp(frame["Timestamp"].max())
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    cutoff = cutoff.floor("min")
    if cutoff > frame["Timestamp"].max():
        raise MonitorSnapshotV39AError("cutoff is later than the available feed")
    return cutoff


def _window_metrics(frame: pd.DataFrame, *, minutes: int, cutoff: pd.Timestamp) -> dict[str, Any]:
    start = cutoff - pd.Timedelta(minutes=minutes - 1)
    window = frame[(frame["Timestamp"] >= start) & (frame["Timestamp"] <= cutoff)].copy()
    expected = pd.date_range(start, cutoff, freq="min", tz="UTC")
    actual = pd.DatetimeIndex(window["Timestamp"])
    missing = expected.difference(actual)
    duplicate_count = int(actual.duplicated().sum())
    complete = len(missing) == 0 and len(window) == len(expected) and duplicate_count == 0
    quality_counts = {
        str(key): int(value)
        for key, value in window["DataQuality"].value_counts().sort_index().items()
    }
    recovered = any(key == "RECOVERED_DEGRADED" for key in quality_counts)
    status = "COMPLETE_DEGRADED" if complete and recovered else "COMPLETE_RAW" if complete else "INCOMPLETE"
    if window.empty:
        return {
            "start_timestamp": _format_ts(start),
            "end_timestamp": _format_ts(cutoff),
            "expected_rows": int(len(expected)),
            "rows_used": 0,
            "complete": False,
            "metrics_valid": False,
            "status": "EMPTY",
            "missing_timestamps": [_format_ts(ts) for ts in expected[:10]],
            "missing_timestamp_count": int(len(expected)),
            "duplicate_rows": 0,
            "data_quality_counts": {},
        }
    total_qty = float(window["TotalQty"].sum())
    open_price = float(window.iloc[0]["OpenPrice"])
    close_price = float(window.iloc[-1]["ClosePrice"])
    high_price = float(window["HiPrice"].max())
    low_price = float(window["LowPrice"].min())
    vwap_approx = float(((((window["HiPrice"] + window["LowPrice"] + window["ClosePrice"]) / 3.0) * window["TotalQty"]).sum()) / total_qty) if total_qty > 0 else None
    return {
        "start_timestamp": _format_ts(start),
        "end_timestamp": _format_ts(cutoff),
        "expected_rows": int(len(expected)),
        "rows_used": int(len(window)),
        "complete": bool(complete),
        "metrics_valid": bool(complete),
        "status": status,
        "missing_timestamps": [_format_ts(ts) for ts in missing[:10]],
        "missing_timestamp_count": int(len(missing)),
        "duplicate_rows": duplicate_count,
        "data_quality_counts": quality_counts,
        "recovered_degraded": bool(recovered),
        "open": round(open_price, 8),
        "close": round(close_price, 8),
        "high": round(high_price, 8),
        "low": round(low_price, 8),
        "price_change": round(close_price - open_price, 8),
        "price_change_pct": round((close_price / open_price - 1.0) * 100.0, 8) if open_price else None,
        "total_qty": round(total_qty, 8),
        "delta": round(float((window["BuyQty"] - window["SellQty"]).sum()), 8),
        "delta_pct": round(float((window["BuyQty"] - window["SellQty"]).sum()) / total_qty, 10) if total_qty else 0.0,
        "open_interest_change": round(float(window.iloc[-1]["OpenInterest"] - window.iloc[0]["OpenInterest"]), 8),
        "funding_last": round(float(window.iloc[-1]["FundingRate"]), 12),
        "range_position": round((close_price - low_price) / (high_price - low_price), 8) if high_price != low_price else 0.5,
        "vwap_approx": round(vwap_approx, 8) if vwap_approx is not None else None,
        "price_minus_vwap_approx": round(close_price - vwap_approx, 8) if vwap_approx is not None else None,
        "price_minus_vwap_approx_pct": round((close_price / vwap_approx - 1.0) * 100.0, 8) if vwap_approx else None,
        "poc": None,
        "poc_status": "UNAVAILABLE_PRICE_VOLUME_DISTRIBUTION_MISSING",
    }


def _quality_summary(
    input_frame: pd.DataFrame,
    current: pd.DataFrame,
    context: pd.DataFrame,
    windows: Mapping[str, Mapping[str, Any]],
    horizons: Mapping[str, Mapping[str, Any]],
    cutoff: pd.Timestamp,
) -> dict[str, Any]:
    future_rows = int((input_frame["Timestamp"] > cutoff).sum())
    missing_windows = [key for key, value in windows.items() if not value.get("complete")]
    missing_broad_horizons = [key for key in ("3d", "7d", "30d") if not horizons[key].get("complete")]
    context_duplicate_rows = int(context["Timestamp"].duplicated().sum())
    counts = {
        str(key): int(value)
        for key, value in context["DataQuality"].value_counts().sort_index().items()
    }
    degraded = any(name != "RAW" for name in counts)
    return {
        "cutoff_is_latest_used_row": bool(current["Timestamp"].max() == cutoff),
        "future_rows_excluded": future_rows,
        "current_rows": int(len(current)),
        "context_rows": int(len(context)),
        "context_duplicate_rows": context_duplicate_rows,
        "context_data_quality_counts": counts,
        "recovered_degraded_present": "RECOVERED_DEGRADED" in counts,
        "incomplete_windows": missing_windows,
        "incomplete_broad_horizons": missing_broad_horizons,
        "readiness": "INCOMPLETE" if missing_windows or context_duplicate_rows else "READY_WITH_PARTIAL_CONTEXT" if missing_broad_horizons else "READY_WITH_DEGRADED_DATA" if degraded else "READY",
    }


def _structure_summary(windows: Mapping[str, Mapping[str, Any]], current_price: float) -> dict[str, Any]:
    levels: list[dict[str, Any]] = []
    for key in ("240", "1440"):
        metrics = windows.get(key, {})
        if not metrics.get("complete"):
            continue
        for role, field in (("SUPPORT_OBSERVED_LOW", "low"), ("RESISTANCE_OBSERVED_HIGH", "high")):
            levels.append(
                {
                    "level_id": f"{key}m_{field}",
                    "role": role,
                    "price": metrics.get(field),
                    "source_window_minutes": int(key),
                    "observed_at": metrics.get("end_timestamp", ""),
                    "lifecycle_status": "OBSERVED_EXTREME",
                }
            )
    return {
        "current_price": round(current_price, 8),
        "levels": levels,
        "contract": "observed_window_extremes_only; no promoted setup lifecycle",
    }


def _load_state(state_path: str | Path | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if state_path is None:
        return None, {"status": "DISABLED", "path": ""}
    path = Path(state_path)
    if not path.exists():
        return None, {"status": "INITIALIZED", "path": str(path)}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"status": "INVALID", "path": str(path), "error": type(exc).__name__}
    if not isinstance(raw, dict) or raw.get("state_schema_version") != STATE_SCHEMA_VERSION:
        return None, {"status": "INCOMPATIBLE", "path": str(path)}
    return raw, {"status": "LOADED", "path": str(path)}


def _advance_state(*, previous_state, state_load, cutoff, structure, zones, market_state, quality):
    previous_cutoff = _parse_ts((previous_state or {}).get("last_cutoff_ts"))
    invalid_future = previous_cutoff is not None and previous_cutoff > cutoff
    prior = None if invalid_future else previous_state
    prior_date = _parse_ts((prior or {}).get("market_day_utc"))
    day_changed = prior_date is not None and prior_date.date() != cutoff.date()
    gap_minutes = None
    if prior_date is not None:
        gap_minutes = int((cutoff - previous_cutoff).total_seconds() // 60) if previous_cutoff else None
    carried = prior is not None
    same_cutoff = previous_cutoff is not None and previous_cutoff == cutoff
    rollover_count = int((prior or {}).get("daily_boundary", {}).get("rollover_count", 0)) + (1 if day_changed else 0)
    continuity = "INVALID_FUTURE_STATE" if invalid_future else "CONTINUOUS_CARRY_FORWARD" if carried else "INITIALIZED"
    state_memory = {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "load_status": state_load.get("status"),
        "previous_cutoff_ts": _format_ts(previous_cutoff) if previous_cutoff is not None else "",
        "carried_forward": bool(carried),
        "continuity": continuity,
        "gap_minutes": gap_minutes,
        "daily_boundary": {
            "utc_day": cutoff.date().isoformat(),
            "changed": bool(day_changed),
            "previous_utc_day": prior_date.date().isoformat() if prior_date is not None else "",
            "rollover_count": rollover_count,
            "state_carried_across_boundary": bool(day_changed and carried),
        },
        "state_source": "persisted_monitor_state" if carried else "initial_snapshot",
        "invalid_future_state_discarded": bool(invalid_future),
    }
    if same_cutoff and prior is not None:
        state_memory["daily_boundary"] = prior.get("daily_boundary", state_memory["daily_boundary"])
        return state_memory, dict(prior)
    next_state = {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "last_cutoff_ts": _format_ts(cutoff),
        "market_day_utc": cutoff.date().isoformat(),
        "carry_forward_count": int((prior or {}).get("carry_forward_count", 0)) + (1 if carried and not same_cutoff else 0),
        "daily_boundary": state_memory["daily_boundary"],
        "structure": structure,
        "liquidity_zones": zones,
        "market_state": market_state,
        "quality": quality,
    }
    return state_memory, next_state


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_json_safe(dict(state)), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _parse_ts(value: Any) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _format_ts(value: Any) -> str:
    ts = _parse_ts(value)
    if ts is None:
        raise MonitorSnapshotV39AError("timestamp is required")
    return ts.isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


__all__ = [
    "LOCAL_WINDOWS_MINUTES",
    "MonitorSnapshotV39AError",
    "SNAPSHOT_SCHEMA_VERSION",
    "STATE_SCHEMA_VERSION",
    "build_market_monitor_snapshot_v39a",
]
