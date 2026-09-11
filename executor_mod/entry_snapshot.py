"""Build the entry-only payload sent to the LLM trade judge.

The Executor keeps a richer evidence pack for its journal, but the model must
receive a separate, explicit view.  This module is intentionally dependency
free and does not know how to place, amend, or close an order.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping


SNAPSHOT_SCHEMA_VERSION = "LLM_ENTRY_SNAPSHOT_V2"
PROMPT_VERSION = "LLM_ENTRY_PROMPT_V2"


class EntrySnapshotError(ValueError):
    """Raised when the entry payload cannot be built safely."""


_SIGNAL_FIELDS = (
    "kind",
    "price",
    "price_usdt",
    "delta",
    "vol",
    "volume",
    "imb",
    "imbalance",
    "vwap",
    "poc",
    "strength",
    "timestamp",
    "ts",
)
_POLICY_FIELDS = (
    "INITIAL_STOP_POLICY",
    "INITIAL_STOP_LOOKBACK_MINUTES",
    "INITIAL_STOP_LOOKBACK",
    "INITIAL_STOP_LR_PERCENTILE",
    "INITIAL_STOP_LR",
    "INITIAL_STOP_BUFFER",
    "INITIAL_STOP_CAP",
    "INITIAL_STOP_FULL_WINDOW",
)
_POST_ENTRY_KEYS = {
    "orders",
    "order_id",
    "client_id",
    "opened_at",
    "filled_at",
    "closed_at",
    "exit",
    "outcome",
    "pnl",
    "realized_pnl",
    "unrealized_pnl",
    "trailing",
    "trail",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _compact(value: Any, *, list_limit: int = 250) -> Any:
    """Copy descriptive context while removing execution/post-entry fields."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in _POST_ENTRY_KEYS:
                continue
            result[key_text] = _compact(child, list_limit=list_limit)
        return result
    if isinstance(value, list):
        # Keep the most recent descriptive observations if a legacy context
        # contains a long event tail. The cutoff has already been selected by
        # the caller, so this is only a payload-size bound.
        items = value[-list_limit:]
        return [_compact(item, list_limit=list_limit) for item in items]
    return value


def _nested_gaps(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text.lower() in {"data_gaps", "gaps"} and isinstance(child, list):
                found.extend(f"{child_path}:{item}" for item in child if item)
            found.extend(_nested_gaps(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_nested_gaps(child, f"{path}[{index}]"))
    return found


def _admission(src_evt: Mapping[str, Any], pack: Mapping[str, Any], gaps: list[str]) -> dict[str, Any]:
    raw = src_evt.get("loss_filter_admission")
    if not isinstance(raw, Mapping):
        raw = pack.get("loss_filter_admission")
    if not isinstance(raw, Mapping):
        gaps.append("UPSTREAM_FILTER_PROVENANCE_MISSING")
        return {
            "schema_version": "DS_ENTRY_ADMISSION_V1",
            "source": "not_present_in_signal",
            "policy_id": "DS_PEAK_LOSS_AVOIDANCE_UNION_V1",
            "decision": "EMITTED_WITHOUT_FILTER_PROVENANCE",
            "effective_action": "UNKNOWN",
            "filter_a": {
                "status": "UNKNOWN",
                "purpose": "Reject a weak same-side PEAK relative to the prior 24-hour same-side peak distribution.",
                "condition": "same_side_peak_percentile_24h <= 50.0 => BLOCK",
            },
            "filter_b": {
                "status": "UNKNOWN",
                "purpose": "Reject a move with falling trusted OI and weak direction-adjusted 240-minute flow.",
                "condition": "oi_change_60m < 0 AND directional_delta_pct_240m < 0.06 => BLOCK",
            },
            "combined_rule": "A OR B blocker; both known PASS values are required for KEEP.",
            "unknown_policy": "UNKNOWN_KEEP",
        }

    result = _compact(raw)
    result.setdefault("filter_a", {"status": "UNKNOWN"})
    result.setdefault("filter_b", {"status": "UNKNOWN"})
    result.setdefault("combined_rule", "A OR B blocker; both known PASS values are required for KEEP.")
    result.setdefault("unknown_policy", "UNKNOWN_KEEP")
    return result


def _geometry(pack: Mapping[str, Any], env: Mapping[str, Any], direction: str | None, gaps: list[str]) -> dict[str, Any]:
    prices = pack.get("prices") if isinstance(pack.get("prices"), Mapping) else {}
    entry = _as_float(pack.get("entry_actual"))
    if entry is None:
        entry = _as_float(pack.get("entry"))
    if entry is None:
        entry = _as_float(prices.get("entry"))
    stop = _as_float(prices.get("sl"))
    tp1 = _as_float(prices.get("tp1"))
    tp2 = _as_float(prices.get("tp2"))

    risk_distance = None
    tp1_r = None
    tp2_r = None
    geometry_status = "UNKNOWN"
    if entry is not None and stop is not None and direction in {"long", "short"}:
        risk_distance = abs(entry - stop)
        valid_stop = (direction == "long" and stop < entry) or (direction == "short" and stop > entry)
        if not valid_stop or risk_distance <= 0:
            geometry_status = "INVALID"
            gaps.append("INVALID_ENTRY_STOP_GEOMETRY")
        else:
            geometry_status = "VALID"
            if tp1 is not None:
                tp1_r = abs(tp1 - entry) / risk_distance
            if tp2 is not None:
                tp2_r = abs(tp2 - entry) / risk_distance
    else:
        gaps.append("INCOMPLETE_EXECUTION_GEOMETRY")

    policy = {key: env.get(key) for key in _POLICY_FIELDS if env.get(key) not in (None, "")}
    return {
        "schema_version": "ENTRY_EXECUTION_GEOMETRY_V1",
        "direction": direction,
        "entry_price": entry,
        "planned_stop_loss": stop,
        "planned_take_profit_1": tp1,
        "planned_take_profit_2": tp2,
        "risk_distance": risk_distance,
        "take_profit_1_R": tp1_r,
        "take_profit_2_R": tp2_r,
        "geometry_status": geometry_status,
        "stop_policy": policy,
    }


def build_entry_snapshot(evidence_pack: Mapping[str, Any], *, env: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Select only facts available at entry for the model prompt."""
    if not isinstance(evidence_pack, Mapping):
        raise EntrySnapshotError("Evidence pack must be a mapping")
    cfg = env if isinstance(env, Mapping) else {}
    src_evt = evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), Mapping) else {}
    direction = str(evidence_pack.get("direction") or src_evt.get("kind") or "").lower() or None
    cutoff = _iso(evidence_pack.get("analysis_cutoff_ts") or evidence_pack.get("peak_ts"))
    if not cutoff:
        raise EntrySnapshotError("Missing analysis cutoff")
    symbol = evidence_pack.get("symbol") or cfg.get("SYMBOL")
    gaps = [str(item) for item in evidence_pack.get("data_gaps", []) if item]

    signal_fields = {key: src_evt.get(key) for key in _SIGNAL_FIELDS if src_evt.get(key) is not None}
    signal = {
        "trade_key": evidence_pack.get("trade_key"),
        "symbol": symbol,
        "direction": direction,
        "signal_ts_utc": _iso(evidence_pack.get("peak_ts") or src_evt.get("timestamp") or src_evt.get("ts")),
        "decision_cutoff_utc": cutoff,
        "cutoff_source": evidence_pack.get("cutoff_source"),
        "timestamp_contract": evidence_pack.get("timestamp_contract"),
        "fields": signal_fields,
    }
    if not symbol:
        gaps.append("MISSING_SYMBOL")
    if not direction:
        gaps.append("MISSING_DIRECTION")
    if not signal_fields:
        gaps.append("MISSING_SIGNAL_FIELDS")

    admission = _admission(src_evt, evidence_pack, gaps)
    geometry = _geometry(evidence_pack, cfg, direction, gaps)
    monitor_snapshot = evidence_pack.get("market_monitor_snapshot")
    market_context = evidence_pack.get("market_context")
    if not isinstance(monitor_snapshot, Mapping):
        gaps.append("MARKET_MONITOR_SNAPSHOT_MISSING")
        monitor_snapshot = {}
    if not isinstance(market_context, Mapping):
        gaps.append("MARKET_CONTEXT_MISSING")
        market_context = {}
    monitor = _compact(monitor_snapshot)
    context = _compact(market_context)
    gaps.extend(_nested_gaps(monitor_snapshot))
    gaps.extend(_nested_gaps(market_context))
    unique_gaps = sorted({item for item in gaps if item})

    payload: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "snapshot_type": "ENTRY_ONLY",
        "decision_cutoff_utc": cutoff,
        "signal": signal,
        "upstream_admission": admission,
        "execution_geometry": geometry,
        "market": {
            "monitor_snapshot": monitor,
            "context": context,
        },
        "quality": {
            "status": "READY" if not unique_gaps else "PARTIAL",
            "gaps": unique_gaps,
            "monitor_data_gaps": _nested_gaps(monitor_snapshot),
            "entry_assessment_only": True,
            "future_data_allowed": False,
        },
    }
    payload["lineage"] = {
        "monitor_schema_version": monitor_snapshot.get("schema_version"),
        "market_context_schema_version": market_context.get("schema_version"),
        "input_sha256": _sha256({"cutoff": cutoff, "signal": signal, "admission": admission, "geometry": geometry, "market": payload["market"]}),
    }
    return payload


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": ["SUPPORT", "REJECT", "UNCLEAR"]},
            "competitive_side": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "setup_class": {"type": "string"},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "summary_ua": {"type": ["string", "null"]},
        },
        "required": ["verdict", "competitive_side", "confidence", "setup_class", "reason_codes", "risk_flags", "summary_ua"],
    }


def build_entry_prompt(snapshot: Mapping[str, Any]) -> str:
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise EntrySnapshotError("Prompt requires LLM_ENTRY_SNAPSHOT_V2")
    return (
        "You are an entry quality assessor for an automated Binance trading signal.\n"
        "Make one assessment at decision_cutoff_utc using only this snapshot.\n"
        "The snapshot is pre-entry only. Do not infer later prices, fills, outcomes, or management actions.\n"
        "The execution_geometry block is known at entry and describes planned risk distance and target distances; it is context, not an instruction to manage the position.\n"
        "The upstream_admission block explains two upstream loss-avoidance checks. Filter A rejects a weak same-side PEAK when same_side_peak_percentile_24h <= 50.0. Filter B rejects when trusted OI falls over 60m and direction-adjusted delta over 240m is below 0.06. A or B is a blocker; PASS means the blocker condition was false, BLOCK means it matched, and UNKNOWN means the value was unavailable. Treat UNKNOWN as uncertainty, not as PASS.\n"
        "Use the monitor fields, units, quality gaps, and filter definitions together. Do not invent values for null, partial, recovered, or missing data.\n"
        "SUPPORT means the bot direction has a clear edge. REJECT means the evidence argues against entry. UNCLEAR means the edge cannot be assessed reliably. Return only JSON matching the schema.\n"
        f"Output schema: {_canonical(output_schema())}\n"
        f"Entry snapshot: {_canonical(snapshot)}"
    )


__all__ = ["EntrySnapshotError", "PROMPT_VERSION", "SNAPSHOT_SCHEMA_VERSION", "build_entry_prompt", "build_entry_snapshot", "output_schema"]
