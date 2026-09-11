"""Entry-only LLM snapshot and prompt boundary.

This module is deliberately separate from the live Executor.  It consumes the
offline ``monitor_feed_contract`` snapshot and produces the smallest
machine-verifiable payload that an entry assessor may see.  It does not import
the Executor, call a model, or carry execution-management fields.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import monitor_feed_contract


SNAPSHOT_SCHEMA_VERSION = "LLM_ENTRY_SNAPSHOT_V2"
PROMPT_VERSION = "LLM_ENTRY_PROMPT_V2"
ENTRY_OUTPUT_SCHEMA_VERSION = "LLM_ENTRY_VERDICT_V2"


class EntrySnapshotError(ValueError):
    """Raised when an entry payload cannot be proven to be pre-cutoff only."""


# These names are intentionally broader than the current monitor schema.  A
# future caller must fail closed rather than silently pass management state to
# an entry-only model.
_FORBIDDEN_KEY_PARTS = (
    "trailing",
    "stop",
    "sl",
    "take_profit",
    "tp1",
    "tp2",
    "exit",
    "pnl",
    "realized",
    "outcome",
)

_TIMESTAMP_KEYS = {
    "cutoff_utc",
    "analysis_cutoff_ts",
    "start_exclusive_utc",
    "end_inclusive_utc",
    "close_utc",
    "available_no_earlier_than_utc",
    "latest_usable_source_close_utc",
    "signal_ts_utc",
    "timestamp_utc",
}

_SRC_EVENT_FIELDS = {
    "kind",
    "price",
    "price_usdt",
    "delta",
    "volume",
    "total_qty",
    "buy_qty",
    "sell_qty",
    "imbalance",
    "strength",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unique(values: list[str]) -> list[str]:
    return sorted({str(value) for value in values if value})


def _has_forbidden_key(value: Any, path: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                return f"{path}.{key_text}" if path else key_text
            found = _has_forbidden_key(child, f"{path}.{key_text}" if path else key_text)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _has_forbidden_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _check_pre_cutoff_timestamps(value: Any, cutoff, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if key_text in _TIMESTAMP_KEYS and child is not None:
                try:
                    timestamp = monitor_feed_contract.utc_cutoff(str(child))
                except Exception as exc:
                    raise EntrySnapshotError(f"Invalid timestamp at {child_path}") from exc
                if timestamp > cutoff:
                    raise EntrySnapshotError(f"Future timestamp at {child_path}: {timestamp.isoformat()}")
            _check_pre_cutoff_timestamps(child, cutoff, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_pre_cutoff_timestamps(child, cutoff, f"{path}[{index}]")


def _source_lineage(feed_manifest: Mapping[str, Any] | None) -> tuple[dict, list[str]]:
    gaps: list[str] = []
    if not isinstance(feed_manifest, Mapping):
        return {"source_files": [], "source_hashes": {}, "manifest_sha256": None}, ["SOURCE_MANIFEST_NOT_SUPPLIED"]

    source_files = []
    source_hashes: dict[str, str] = {}
    for item in feed_manifest.get("source_files") or []:
        if not isinstance(item, Mapping) or not item.get("sha256"):
            gaps.append("SOURCE_FILE_HASH_MISSING")
            continue
        name = Path(str(item.get("path") or item.get("name") or "")).name
        digest = str(item["sha256"])
        source_files.append({"name": name, "sha256": digest})
        source_hashes[name] = digest

    sidecar = feed_manifest.get("recovery_sidecar")
    if isinstance(sidecar, Mapping) and sidecar.get("sha256"):
        source_hashes[Path(str(sidecar.get("path") or "recovery_sidecar")).name] = str(sidecar["sha256"])
    elif sidecar is not None:
        gaps.append("RECOVERY_SIDECAR_HASH_MISSING")

    lineage = {
        "contract_version": feed_manifest.get("contract_version"),
        "cutoff_utc": feed_manifest.get("cutoff_utc"),
        "history_minutes": feed_manifest.get("history_minutes"),
        "source_files": source_files,
        "source_hashes": source_hashes,
        "raw_inputs_modified": bool(feed_manifest.get("raw_inputs_modified", False)),
    }
    lineage["manifest_sha256"] = _sha256(lineage)
    return lineage, _unique(gaps)


def _code_lineage(code_hashes: Mapping[str, str] | None) -> dict:
    if code_hashes is not None:
        files = {str(name): str(digest) for name, digest in code_hashes.items()}
    else:
        files = {
            "llm_entry_snapshot.py": _hash_file(Path(__file__)),
            "monitor_feed_contract.py": _hash_file(Path(monitor_feed_contract.__file__)),
        }
    return {"files": files, "manifest_sha256": _sha256(files)}


def _entry_signal(evidence_pack: Mapping[str, Any], cutoff) -> tuple[dict, list[str]]:
    src = evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), Mapping) else {}
    gaps: list[str] = []
    symbol = evidence_pack.get("symbol")
    direction = evidence_pack.get("direction")
    entry_price = evidence_pack.get("entry_actual")
    if entry_price is None:
        entry_price = evidence_pack.get("entry")
    if entry_price is None:
        entry_price = src.get("price_usdt", src.get("price"))
    if not symbol:
        gaps.append("MISSING_SYMBOL")
    if not direction:
        gaps.append("MISSING_DIRECTION")
    if entry_price is None:
        gaps.append("MISSING_ENTRY_PRICE")

    event = {key: src.get(key) for key in sorted(_SRC_EVENT_FIELDS) if src.get(key) is not None}
    raw_ts = evidence_pack.get("peak_ts") or src.get("timestamp") or src.get("ts")
    signal_ts = None
    if raw_ts is not None:
        try:
            signal_ts = monitor_feed_contract.utc_cutoff(str(raw_ts)).isoformat()
        except Exception:
            gaps.append("SIGNAL_TIMESTAMP_INVALID")
        else:
            if monitor_feed_contract.utc_cutoff(signal_ts) > cutoff:
                raise EntrySnapshotError("Signal timestamp is after decision cutoff")

    execution_quote = str(symbol).upper() if symbol else None
    execution_domain = execution_quote if execution_quote and execution_quote.endswith(("USDT", "USDC")) else None
    if execution_domain and execution_domain != "BTCUSDT":
        gaps.append("PRICE_DOMAIN_CONVERSION_NOT_SUPPLIED")

    return {
        "trade_key": evidence_pack.get("trade_key"),
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "entry_price_domain": execution_domain,
        "signal_kind": src.get("kind"),
        "signal_ts_utc": signal_ts,
        "signal_fields": event,
    }, gaps


def _monitor_context(monitor_snapshot: Mapping[str, Any], gaps: list[str]) -> dict:
    """Keep descriptive pre-entry monitor fields and mark unavailable state."""
    structure = {
        "status": "NOT_IMPLEMENTED_IN_THIS_ADAPTER",
        "market_state": None,
        "levels": None,
        "level_reactions": None,
        "gaps": ["STRUCTURE_LEVEL_LIFECYCLE_UNIMPLEMENTED"],
    }
    if any(key in monitor_snapshot for key in ("market_state", "market_structure_state", "significant_market_zones", "liquidity_zones")):
        structure = {
            "status": "DESCRIPTIVE_ONLY",
            "market_state": monitor_snapshot.get("market_state"),
            "market_structure_state": monitor_snapshot.get("market_structure_state"),
            "levels": monitor_snapshot.get("significant_market_zones"),
            "liquidity_zones": monitor_snapshot.get("liquidity_zones"),
            "level_reactions": None,
            "gaps": ["LEVEL_REACTION_HISTORY_UNIMPLEMENTED"],
        }
    context = {
        "price_domain": monitor_snapshot.get("price_symbol", "BTCUSDT"),
        "timestamp_contract": monitor_snapshot.get("timestamp_contract"),
        "field_units": monitor_snapshot.get("field_units", {}),
        "windows": monitor_snapshot.get("windows", {}),
        "closed_bars": monitor_snapshot.get("closed_bars", {}),
        "broad_context": monitor_snapshot.get("broad_context"),
        "market_state": monitor_snapshot.get("market_state"),
        "data_quality": monitor_snapshot.get("data_quality"),
        "context_conflicts": monitor_snapshot.get("context_conflicts"),
        "structure": structure,
    }
    gaps.extend(str(item) for item in monitor_snapshot.get("gaps", []) if item)
    gaps.extend(str(item) for item in monitor_snapshot.get("data_gaps", []) if item)
    return context


def build_entry_snapshot(
    evidence_pack: Mapping[str, Any],
    monitor_snapshot: Mapping[str, Any],
    *,
    feed_manifest: Mapping[str, Any] | None = None,
    code_hashes: Mapping[str, str] | None = None,
) -> dict:
    """Build a strict one-time entry payload from pre-cutoff evidence.

    ``monitor_snapshot`` should be produced by ``build_data_snapshot`` or by a
    descriptive monitor adapter.  Any management or post-entry key causes a
    fail-closed error; it is never silently hidden from the caller.
    """
    if not isinstance(evidence_pack, Mapping) or not isinstance(monitor_snapshot, Mapping):
        raise EntrySnapshotError("Evidence and monitor snapshot must be mappings")
    forbidden = _has_forbidden_key(evidence_pack)
    if forbidden:
        # The raw Executor pack often contains order-management fields.  This
        # adapter accepts that source only when its caller has selected the
        # entry fields explicitly; passing the full pack is unsafe.
        raise EntrySnapshotError(f"Post-entry field is not allowed: {forbidden}")
    forbidden = _has_forbidden_key(monitor_snapshot)
    if forbidden:
        raise EntrySnapshotError(f"Post-entry field is not allowed: {forbidden}")

    cutoff_value = evidence_pack.get("analysis_cutoff_ts") or monitor_snapshot.get("cutoff_utc")
    if cutoff_value is None:
        raise EntrySnapshotError("Missing explicit analysis cutoff")
    cutoff = monitor_feed_contract.utc_cutoff(str(cutoff_value))
    monitor_cutoff = monitor_snapshot.get("cutoff_utc")
    if monitor_cutoff is not None and monitor_feed_contract.utc_cutoff(str(monitor_cutoff)) != cutoff:
        raise EntrySnapshotError("Evidence and monitor cutoff differ")
    _check_pre_cutoff_timestamps(monitor_snapshot, cutoff)

    gaps = [str(item) for item in evidence_pack.get("data_gaps", []) if item]
    signal, signal_gaps = _entry_signal(evidence_pack, cutoff)
    gaps.extend(signal_gaps)
    source, source_gaps = _source_lineage(feed_manifest)
    gaps.extend(source_gaps)
    code = _code_lineage(code_hashes)
    context = _monitor_context(monitor_snapshot, gaps)
    readiness = {
        "local_window_readiness": monitor_snapshot.get("local_window_readiness", "UNKNOWN"),
        "window_status": {str(key): value.get("status") for key, value in (monitor_snapshot.get("windows") or {}).items() if isinstance(value, Mapping)},
        "latest_usable_source_close_utc": monitor_snapshot.get("latest_usable_source_close_utc"),
        "source_label_age_seconds": monitor_snapshot.get("source_label_age_seconds"),
        "live_decision_eligible": False,
        "state_memory": "NOT_IMPLEMENTED_IN_THIS_ADAPTER",
    }
    gaps.append("LIVE_DECISION_ELIGIBILITY_NOT_CERTIFIED")
    gaps = _unique(gaps)

    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "snapshot_type": "ENTRY_ONLY",
        "decision_cutoff_utc": cutoff.isoformat(),
        "cutoff_source": evidence_pack.get("cutoff_source"),
        "signal": signal,
        "market": context,
        "quality": {
            "readiness": readiness,
            "gaps": gaps,
            "status": "READY" if not gaps else "PARTIAL",
            "unsupported_fields_are_null": True,
        },
        "lineage": {
            "timestamp_contract": monitor_snapshot.get("timestamp_contract"),
            "price_domain": "BTCUSDT",
            "source": source,
            "code": code,
            "input_sha256": _sha256({"cutoff": cutoff.isoformat(), "signal": signal, "monitor": monitor_snapshot}),
        },
    }
    payload["lineage"]["pre_cutoff_evidence_sha256"] = _sha256(payload)
    return payload


def entry_output_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ENTRY_OUTPUT_SCHEMA_VERSION,
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


def build_entry_judge_prompt(snapshot: Mapping[str, Any]) -> str:
    """Render the entry-only prompt without calling any model."""
    if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise EntrySnapshotError("Prompt requires an LLM_ENTRY_SNAPSHOT_V2 payload")
    forbidden = _has_forbidden_key(snapshot)
    if forbidden:
        raise EntrySnapshotError(f"Prompt payload contains forbidden field: {forbidden}")
    return (
        "You are an entry quality assessor for an automated trading signal.\n"
        "Make one assessment at the decision cutoff in decision_cutoff_utc.\n"
        "Use only facts in the JSON snapshot whose timestamps are at or before that cutoff.\n"
        "Assess whether the signal has a clear, sufficiently supported directional edge at that instant.\n"
        "Treat null, missing, partial, recovered, or unsupported values as uncertainty; never replace them with zero or an inferred value.\n"
        "Respect the stated price domain and field units. Do not invent structure, level history, reactions, or readiness when the snapshot marks them unavailable.\n"
        "This is a one-time entry assessment. Do not infer any later event, outcome, or action from information outside the snapshot.\n"
        "Return only JSON matching the schema below.\n"
        "SUPPORT means the signal side has a clear edge. REJECT means the evidence argues against taking the signal. "
        "UNCLEAR means the available evidence is insufficient or materially conflicting.\n"
        f"Output schema: {_canonical(entry_output_schema())}\n"
        f"Entry snapshot: {_canonical(snapshot)}"
    )


__all__ = [
    "ENTRY_OUTPUT_SCHEMA_VERSION",
    "EntrySnapshotError",
    "PROMPT_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "build_entry_judge_prompt",
    "build_entry_snapshot",
    "entry_output_schema",
]
