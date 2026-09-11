import json

import pytest

from deltascout.research_bundle.llm_entry_snapshot import (
    EntrySnapshotError,
    SNAPSHOT_SCHEMA_VERSION,
    build_entry_judge_prompt,
    build_entry_snapshot,
    entry_output_schema,
)


def monitor(cutoff="2026-07-26T00:26:00+00:00"):
    return {
        "schema_version": "MONITOR_SHI_CLOSE_CONTRACT_V1",
        "cutoff_utc": cutoff,
        "price_symbol": "BTCUSDT",
        "timestamp_contract": "UTC_SHI_FLUSH_CLOSE_LABEL",
        "field_units": {
            "price": "USDT_per_BTC",
            "volume": "BTC",
            "delta_fraction": "fraction_-1_to_1",
            "return_fraction": "fraction",
        },
        "latest_usable_source_close_utc": cutoff,
        "source_label_age_seconds": 0,
        "local_window_readiness": "READY",
        "gaps": [],
        "windows": {
            "60": {
                "status": "READY",
                "start_exclusive_utc": "2026-07-25T23:26:00+00:00",
                "end_inclusive_utc": cutoff,
                "metrics": {"delta_fraction": 0.2, "volume_btc": 600.0},
            },
            "240": {
                "status": "READY",
                "start_exclusive_utc": "2026-07-25T20:26:00+00:00",
                "end_inclusive_utc": cutoff,
                "metrics": {"delta_fraction": 0.0756, "volume_btc": 2400.0},
            },
        },
        "closed_bars": {
            "H1": [{"close_utc": "2026-07-26T00:00:00+00:00", "available_no_earlier_than_utc": "2026-07-26T00:00:00+00:00"}],
            "H4": [],
        },
        "data_quality": {"current": "RAW"},
    }


def evidence(symbol="BTCUSDC"):
    return {
        "trade_key": "EXAMPLE-1",
        "symbol": symbol,
        "direction": "short",
        "entry_actual": 78689.37,
        "analysis_cutoff_ts": "2026-07-26T00:26:00+00:00",
        "cutoff_source": "peak_ts",
        "src_evt": {
            "kind": "short",
            "price_usdt": 78689.37,
            "delta": -100.0,
            "volume": 500.0,
            "imbalance": -0.2,
            "timestamp": "2026-07-26T00:26:00+00:00",
        },
        "data_gaps": [],
    }


def manifest():
    return {
        "contract_version": "MONITOR_SHI_CLOSE_CONTRACT_V1",
        "cutoff_utc": "2026-07-26T00:26:00+00:00",
        "history_minutes": 43200,
        "source_files": [{"path": "2026-07-25.csv", "sha256": "a" * 64}],
        "raw_inputs_modified": False,
    }


def test_entry_payload_has_lineage_units_readiness_and_no_management_fields():
    payload = build_entry_snapshot(evidence(), monitor(), feed_manifest=manifest())
    assert payload["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert payload["snapshot_type"] == "ENTRY_ONLY"
    assert payload["decision_cutoff_utc"] == "2026-07-26T00:26:00+00:00"
    assert payload["market"]["field_units"]["delta_fraction"] == "fraction_-1_to_1"
    assert payload["market"]["price_domain"] == "BTCUSDT"
    assert payload["signal"]["entry_price_domain"] == "BTCUSDC"
    assert "PRICE_DOMAIN_CONVERSION_NOT_SUPPLIED" in payload["quality"]["gaps"]
    assert payload["lineage"]["source"]["source_hashes"]["2026-07-25.csv"] == "a" * 64
    assert payload["lineage"]["input_sha256"]
    assert payload["lineage"]["pre_cutoff_evidence_sha256"]
    assert payload["quality"]["readiness"]["live_decision_eligible"] is False
    assert payload["market"]["structure"]["status"] == "NOT_IMPLEMENTED_IN_THIS_ADAPTER"

    serialized = json.dumps(payload).lower()
    for forbidden in ("trailing", "stop", "take_profit", "tp1", "tp2", "pnl", "outcome"):
        assert forbidden not in serialized


def test_prompt_is_entry_only_and_contains_output_contract():
    payload = build_entry_snapshot(evidence("BTCUSDT"), monitor(), feed_manifest=manifest())
    prompt = build_entry_judge_prompt(payload)
    lower = prompt.lower()
    assert "trailing" not in lower
    assert "tp1" not in lower
    assert "tp2" not in lower
    assert "stop" not in lower
    assert "entry quality assessor" in lower
    assert "decision_cutoff_utc" in prompt
    assert "LLM_ENTRY_VERDICT_V2" in prompt


def test_future_monitor_suffix_or_future_bar_is_rejected():
    data = monitor()
    data["closed_bars"]["H1"].append({"close_utc": "2026-07-26T00:27:00+00:00"})
    with pytest.raises(EntrySnapshotError, match="Future timestamp"):
        build_entry_snapshot(evidence("BTCUSDT"), data, feed_manifest=manifest())


def test_full_executor_pack_with_order_management_fields_is_rejected():
    data = evidence("BTCUSDT")
    data["prices"] = {"sl": 79000.0}
    with pytest.raises(EntrySnapshotError, match="Post-entry field"):
        build_entry_snapshot(data, monitor(), feed_manifest=manifest())


def test_missing_manifest_is_explicitly_degraded():
    payload = build_entry_snapshot(evidence("BTCUSDT"), monitor())
    assert "SOURCE_MANIFEST_NOT_SUPPLIED" in payload["quality"]["gaps"]
    assert payload["lineage"]["source"]["source_hashes"] == {}
