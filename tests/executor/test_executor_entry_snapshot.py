from __future__ import annotations

import json

import pytest

from executor_mod.entry_snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    build_entry_prompt,
    build_entry_snapshot,
)


def _pack(*, with_admission: bool = True) -> dict:
    src_evt = {
        "kind": "short",
        "price_usdt": 78689.37,
        "delta": -100.0,
        "vol": 500.0,
        "imb": -0.2,
        "ts": "2026-07-26T00:26:00+00:00",
    }
    if with_admission:
        src_evt["loss_filter_admission"] = {
            "schema_version": "DS_ENTRY_ADMISSION_V1",
            "policy_id": "DS_PEAK_LOSS_AVOIDANCE_UNION_V1",
            "decision": "KEEP",
            "effective_action": "EMIT",
            "filter_a": {
                "status": "PASS",
                "purpose": "weak same-side peak",
                "condition": "same_side_peak_percentile_24h <= 50.0 => BLOCK",
                "actual_value": 80.0,
                "threshold": 50.0,
            },
            "filter_b": {
                "status": "PASS",
                "purpose": "falling OI and weak 240m flow",
                "condition": "oi_change_60m < 0 AND directional_delta_pct_240m < 0.06 => BLOCK",
                "oi_change_60m": 12.0,
                "directional_delta_pct_240m": 0.11,
                "oi_trusted_60m": True,
            },
            "combined_rule": "A OR B blocker; both known PASS values are required for KEEP.",
            "unknown_policy": "UNKNOWN_KEEP",
        }
    return {
        "trade_key": "EXAMPLE-1",
        "symbol": "BTCUSDC",
        "direction": "short",
        "entry": 78690.0,
        "entry_actual": 78689.37,
        "prices": {"entry": 78690.0, "sl": 79000.0, "tp1": 78000.0, "tp2": 77400.0},
        "analysis_cutoff_ts": "2026-07-26T00:26:00+00:00",
        "peak_ts": "2026-07-26T00:26:00+00:00",
        "src_evt": src_evt,
        "market_monitor_snapshot": {
            "schema_version": "market_monitor_snapshot_v1",
            "data_gaps": [],
            "windows": {"240": {"status": "READY", "directional_delta_pct": 0.11}},
            "market_structure_state": {"status": "partial", "range_quality": "wide"},
        },
        "market_context": {"schema_version": "context_v1", "deltascout": {"events": [{"ts": "2026-07-26T00:25:00+00:00", "delta": -50}] }},
        "data_gaps": [],
    }


def test_snapshot_contains_geometry_and_filter_meaning_without_management_fields() -> None:
    snapshot = build_entry_snapshot(
        _pack(),
        env={
            "INITIAL_STOP_POLICY": "VOLUME_SWING_24H_LR25",
            "INITIAL_STOP_LOOKBACK_MINUTES": "1440",
            "INITIAL_STOP_LR_PERCENTILE": "25",
            "INITIAL_STOP_BUFFER": "50",
        },
    )
    assert snapshot["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert snapshot["execution_geometry"]["geometry_status"] == "VALID"
    assert snapshot["execution_geometry"]["risk_distance"] == pytest.approx(310.63)
    assert snapshot["upstream_admission"]["filter_a"]["status"] == "PASS"
    assert snapshot["upstream_admission"]["filter_b"]["condition"].startswith("oi_change_60m")
    serialized = json.dumps(snapshot).lower()
    for forbidden in ("orders", "order_id", "client_id", "outcome", "pnl", "trailing"):
        assert forbidden not in serialized


def test_missing_filter_provenance_is_unknown_and_explicit() -> None:
    snapshot = build_entry_snapshot(_pack(with_admission=False))
    assert snapshot["upstream_admission"]["decision"] == "EMITTED_WITHOUT_FILTER_PROVENANCE"
    assert snapshot["upstream_admission"]["filter_a"]["status"] == "UNKNOWN"
    assert "UPSTREAM_FILTER_PROVENANCE_MISSING" in snapshot["quality"]["gaps"]


def test_invalid_short_geometry_is_marked_instead_of_hidden() -> None:
    pack = _pack()
    pack["prices"]["sl"] = 78000.0
    snapshot = build_entry_snapshot(pack)
    assert snapshot["execution_geometry"]["geometry_status"] == "INVALID"
    assert "INVALID_ENTRY_STOP_GEOMETRY" in snapshot["quality"]["gaps"]


def test_prompt_serializes_only_entry_snapshot_and_defines_a_b() -> None:
    snapshot = build_entry_snapshot(_pack())
    prompt = build_entry_prompt(snapshot)
    lower = prompt.lower()
    assert "llm_entry_snapshot_v2" in lower
    assert "filter a rejects" in lower
    assert "filter b rejects" in lower
    assert "orders" not in lower
    assert "pnl" not in lower
    assert "trailing" not in lower
    assert "entry snapshot:" in lower
