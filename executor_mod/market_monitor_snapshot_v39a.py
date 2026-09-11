"""Additive 39A monitor snapshot contract.

This module does not replace the existing monitor engine.  It adds the pieces
that were missing at the Executor boundary: exact closed minute windows,
explicit data quality/lineage, and a small persisted state envelope that can
carry the descriptive monitor state across calls and UTC day boundaries.

The state envelope is intentionally descriptive.  It is not a setup engine,
signal gate, order manager, or outcome recorder.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


SNAPSHOT_SCHEMA_VERSION = "market_monitor_snapshot_v39a"
STATE_SCHEMA_VERSION = "SHI_RESET_39A_RUNTIME_STATE_CARRY_FORWARD_V1"
BASE_CONTRACT_VERSION = "market_monitor_snapshot_v1"
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
    base_snapshot: Mapping[str, Any] | None = None,
    lineage: Mapping[str, Any] | None = None,
    persist_state: bool = True,
) -> dict[str, Any]:
    """Build an entry-time monitor snapshot from closed feed rows.

    ``base_snapshot`` may contain the existing v1 structure/zone summaries.
    When supplied, those summaries are carried under an explicit v1 lineage
    field; they are never silently presented as new 39A logic.
    """
    frame = _normalise_feed(feed)
    if frame.empty:
        raise MonitorSnapshotV39AError("feed is empty")
    cutoff = _resolve_cutoff(frame, cutoff_ts)
    current = frame[frame["Timestamp"] <= cutoff].copy()
    if current.empty:
        raise MonitorSnapshotV39AError("no feed rows at or before cutoff")
    context = _normalise_feed(context_feed) if context_feed is not None else current.copy()
    context = context[context["Timestamp"] <= cutoff].copy()
    previous_state, state_load = _load_state(state_path)
    windows = {
        str(minutes): _window_metrics(current, minutes=minutes, cutoff=cutoff)
        for minutes in LOCAL_WINDOWS_MINUTES
    }
    quality = _quality_summary(frame, current, context, windows, cutoff)
    current_price = float(current.iloc[-1]["ClosePrice"])
    structure = _structure_summary(windows, current_price)
    zones = _zone_summary(base_snapshot)
    market_state = _market_state_summary(base_snapshot, windows)
    state_memory, next_state = _advance_state(
        previous_state=previous_state,
        state_load=state_load,
        cutoff=cutoff,
        structure=structure,
        zones=zones,
        market_state=market_state,
        quality=quality,
    )
    effective_zones = zones if zones.get("available") else next_state.get("liquidity_zones", zones)
    if state_path is not None and persist_state:
        _write_state(Path(state_path), next_state)

    source_files = sorted({str(x) for x in current["SourceFile"].dropna().tolist()})
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "cutoff_ts": _format_ts(cutoff),
        "symbol": symbol,
        "bar_contract": {
            "timestamp_semantics": "UTC_minute_close_label",
            "closed_rows_only": True,
            "cutoff_inclusive": True,
            "windows_minutes": list(LOCAL_WINDOWS_MINUTES),
        },
        "current": {
            "price": round(current_price, 8),
            "rows_used": int(len(current)),
            "last_timestamp": _format_ts(current["Timestamp"].iloc[-1]),
        },
        "windows": windows,
        "market_state": market_state,
        "structure": structure,
        "liquidity_zones": effective_zones,
        "state_memory": state_memory,
        "quality": quality,
        "lineage": {
            "source_files": source_files,
            "source_file_count": len(source_files),
            "source_hashes": dict((lineage or {}).get("source_hashes", {})),
            "feed_identity": (lineage or {}).get("feed_identity", "") or "",
            "base_snapshot_schema": (
                str((base_snapshot or {}).get("schema_version", ""))
                if base_snapshot is not None
                else ""
            ),
            "base_monitor_contract": BASE_CONTRACT_VERSION if base_snapshot is not None else "not_supplied",
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
    status = "COMPLETE_RECOVERED_DEGRADED" if complete and recovered else "COMPLETE_RAW" if complete else "PARTIAL"
    if window.empty:
        return {
            "start_timestamp": _format_ts(start),
            "end_timestamp": _format_ts(cutoff),
            "expected_rows": int(len(expected)),
            "rows_used": 0,
            "complete": False,
            "status": "EMPTY",
            "missing_timestamps": [_format_ts(ts) for ts in expected[:10]],
            "duplicate_rows": 0,
            "data_quality_counts": {},
        }
    total_qty = float(window["TotalQty"].sum())
    open_price = float(window.iloc[0]["OpenPrice"])
    close_price = float(window.iloc[-1]["ClosePrice"])
    return {
        "start_timestamp": _format_ts(start),
        "end_timestamp": _format_ts(cutoff),
        "expected_rows": int(len(expected)),
        "rows_used": int(len(window)),
        "complete": bool(complete),
        "status": status,
        "missing_timestamps": [_format_ts(ts) for ts in missing[:10]],
        "duplicate_rows": duplicate_count,
        "data_quality_counts": quality_counts,
        "recovered_degraded": bool(recovered),
        "open": round(open_price, 8),
        "close": round(close_price, 8),
        "high": round(float(window["HiPrice"].max()), 8),
        "low": round(float(window["LowPrice"].min()), 8),
        "price_change_pct": round((close_price / open_price - 1.0) * 100.0, 8) if open_price else None,
        "total_qty": round(total_qty, 8),
        "delta": round(float((window["BuyQty"] - window["SellQty"]).sum()), 8),
        "delta_pct": round(float((window["BuyQty"] - window["SellQty"]).sum()) / total_qty, 10) if total_qty else 0.0,
        "open_interest_change": round(float(window.iloc[-1]["OpenInterest"] - window.iloc[0]["OpenInterest"]), 8),
        "funding_last": round(float(window.iloc[-1]["FundingRate"]), 12),
    }


def _quality_summary(
    input_frame: pd.DataFrame,
    current: pd.DataFrame,
    context: pd.DataFrame,
    windows: Mapping[str, Mapping[str, Any]],
    cutoff: pd.Timestamp,
) -> dict[str, Any]:
    future_rows = int((input_frame["Timestamp"] > cutoff).sum())
    missing_windows = [key for key, value in windows.items() if not value.get("complete")]
    counts = {
        str(key): int(value)
        for key, value in current["DataQuality"].value_counts().sort_index().items()
    }
    return {
        "cutoff_is_latest_used_row": bool(current["Timestamp"].max() == cutoff),
        "future_rows_excluded": future_rows,
        "current_rows": int(len(current)),
        "context_rows": int(len(context)),
        "current_data_quality_counts": counts,
        "recovered_degraded_present": "RECOVERED_DEGRADED" in counts,
        "incomplete_windows": missing_windows,
        "readiness": "READY_WITH_RECOVERED_DATA" if "RECOVERED_DEGRADED" in counts else "READY",
    }


def _structure_summary(windows: Mapping[str, Mapping[str, Any]], current_price: float) -> dict[str, Any]:
    levels: list[dict[str, Any]] = []
    for key in ("240", "1440"):
        metrics = windows.get(key, {})
        if not metrics.get("rows_used"):
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


def _zone_summary(base_snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not base_snapshot:
        return {
            "available": False,
            "source": "not_supplied",
            "significant_market_zones": [],
            "liquidity_zones": [],
        }
    return {
        "available": True,
        "source": "base_monitor_snapshot_v1",
        "significant_market_zones": base_snapshot.get("significant_market_zones", {}),
        "liquidity_zones": base_snapshot.get("liquidity_zones", {}),
    }


def _market_state_summary(base_snapshot: Mapping[str, Any] | None, windows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if base_snapshot:
        structure_state = base_snapshot.get("market_structure_state")
        if isinstance(structure_state, Mapping) and structure_state:
            return {"source": "base_monitor_snapshot_v1", "value": _json_safe(structure_state)}
        market_state = base_snapshot.get("market_state")
        if isinstance(market_state, Mapping) and market_state:
            return {"source": "base_monitor_snapshot_v1", "value": _json_safe(market_state)}
    m = windows.get("1440", {})
    delta = float(m.get("delta", 0.0) or 0.0)
    change = float(m.get("price_change_pct", 0.0) or 0.0)
    bias = "BULLISH_FLOW" if delta > 0 and change >= 0 else "BEARISH_FLOW" if delta < 0 and change <= 0 else "MIXED_FLOW"
    return {"source": "v39a_descriptive_fallback", "value": {"bias": bias}}


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
    prior_zones = (prior or {}).get("liquidity_zones") or {}
    current_zones = zones if zones.get("available") else prior_zones
    carried = prior is not None
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
    next_state = {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "last_cutoff_ts": _format_ts(cutoff),
        "market_day_utc": cutoff.date().isoformat(),
        "carry_forward_count": int((prior or {}).get("carry_forward_count", 0)) + (1 if carried else 0),
        "daily_boundary": state_memory["daily_boundary"],
        "structure": structure,
        "liquidity_zones": current_zones,
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
