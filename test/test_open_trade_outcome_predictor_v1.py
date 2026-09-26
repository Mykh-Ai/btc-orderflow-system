"""Characterization gates for the research-only open-trade predictor."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from docs.research.open_trade_outcome_predictor_v1 import snapshot_v2 as s
from docs.research.open_trade_outcome_predictor_v1 import predictor_prompt as p
from docs.research.open_trade_outcome_predictor_v1.prepare_blind import verify_old_artifacts
from docs.research.open_trade_outcome_predictor_v1.run_blind import _verify_bundle

REAL_STRUCTURE_VIEW = s._structure_view


@pytest.fixture
def inputs(monkeypatch):
    cutoff = pd.Timestamp("2026-09-10T12:00:00Z")
    times = pd.date_range(cutoff - pd.Timedelta(minutes=1439), cutoff, freq="min")
    feed = pd.DataFrame({
        "Timestamp": times, "OpenPrice": [100.0] * len(times),
        "ClosePrice": [101.0] * len(times), "HiPrice": [102.0] * len(times),
        "LowPrice": [99.0] * len(times), "TotalQty": [10.0] * len(times),
        "BuyQty": [6.0] * len(times), "SellQty": [4.0] * len(times),
        "OpenInterest": list(range(len(times))), "DataQuality": ["RAW"] * len(times),
        "SourceFile": ["2026-09-10.csv"] * len(times),
    })
    columns = {"2026-09-10.csv": set(s.RAW_COLUMNS)}
    seed = {
        "signal": {"trade_key": "TEST", "side": "long", "signal_time_utc": "2026-09-10T11:59:40Z", "signal_price": 100.0, "signal_quote_currency": "USDT", "measurements": {"delta": 2.0}, "raw_signal_plan_usdt": {}},
        "execution": {"actual_fill_timestamp_utc": "2026-09-10T12:00:20Z", "actual_entry_price": 100.0, "filled_qty": 1.0, "initial_stop_price": 99.0, "tp1_price": 101.0, "tp2_price": 102.0, "risk_entry_to_sl_usd": 1.0, "reward_entry_to_tp1_usd": 1.0, "reward_entry_to_tp2_usd": 2.0, "tp1_R": 1.0, "tp2_R": 2.0, "entry_minus_signal_usd_approx": 0.0, "entry_minus_signal_pct_approx": 0.0, "quote_conversion_at_entry_approx": 1.0, "execution_quote_currency": "USDC"},
    }
    monkeypatch.setattr(s, "_structure_view", lambda *args: ({"current_price_market_quote": 101.0}, []))
    return seed, feed, columns


def test_fixed_target_schema_and_five_blocks(inputs):
    seed, feed, columns = inputs
    view = s.build_snapshot(seed, feed, columns)
    assert set(view) == set(s.MODEL_BLOCKS)
    assert p.OUTPUT_SCHEMA["properties"]["predicted_outcome_class"]["enum"] == list(p.CLASSES)
    assert view["execution"]["actual_entry_price"] == 100.0
    assert view["execution"]["initial_sl"] == 99.0
    assert view["execution"]["initial_tp1"] == 101.0
    assert view["execution"]["initial_tp2"] == 102.0
    assert view["quality"]["prediction_cutoff_source"] == "historical_executor_fill_proxy"


@pytest.mark.parametrize("field", ["tp1_done", "tp2_done", "sl_done", "trailing", "pnl", "historical_verdict", "last_closed"])
def test_future_lifecycle_fields_rejected(inputs, field):
    seed, feed, columns = inputs
    view = s.build_snapshot(seed, feed, columns)
    view["quality"][field] = "future"
    with pytest.raises(s.SnapshotContractError, match="forbidden future field"):
        s.assert_model_view(view)


def test_post_prediction_row_rejected(inputs):
    seed, feed, columns = inputs
    future = feed.iloc[-1:].copy()
    future.loc[:, "Timestamp"] += pd.Timedelta(minutes=1)
    with pytest.raises(s.SnapshotContractError, match="post-prediction"):
        s.build_snapshot(seed, pd.concat([feed, future]), columns)


def test_segments_cover_1440_nonoverlapping_minutes_with_direct_arithmetic(inputs):
    seed, feed, columns = inputs
    view = s.build_snapshot(seed, feed, columns)
    segments = view["temporal_market"]["segments"]
    assert [item["segment"] for item in segments] == [item[0] for item in s.SEGMENTS]
    assert [item["rows_expected"] for item in segments] == [1200, 180, 45, 10, 5]
    assert sum(item["rows_used"] for item in segments) == 1440
    assert all(item["complete"] for item in segments)
    covered = set()
    for item in segments:
        timestamps = set(pd.date_range(item["start_timestamp"], item["end_timestamp"], freq="min"))
        assert not covered.intersection(timestamps)
        covered.update(timestamps)
    assert covered == set(feed["Timestamp"])
    assert sum(item["delta"] for item in segments) == 1440 * (6 - 4)
    assert sum(item["total_qty"] for item in segments) == 1440 * 10
    assert all(item["delta_pct"] == 0.2 for item in segments)
    assert segments[0]["open_interest_change"] == 1199
    assert segments[1]["open_interest_change"] == 179
    assert sum(item["open_interest_change"] for item in segments) != 1439


def test_duplicate_minute_fails_loud(inputs):
    seed, feed, columns = inputs
    with pytest.raises(s.SnapshotContractError, match="duplicate source minute"):
        s.build_snapshot(seed, pd.concat([feed, feed.iloc[-1:]]), columns)


def test_missing_oi_null_and_open_fallback_provenance(inputs):
    seed, feed, columns = inputs
    columns = deepcopy(columns)
    columns["2026-09-10.csv"].remove("OpenInterest")
    columns["2026-09-10.csv"].remove("OpenPrice")
    view = s.build_snapshot(seed, feed, columns)
    assert all(item["open_interest_change"] is None for item in view["temporal_market"]["segments"])
    assert view["quality"]["open_price_close_fallback"] is True
    assert "OpenInterest" in view["quality"]["missing_source_columns"]


def test_raw_header_provenance_precedes_adapter_fallback(tmp_path):
    path = tmp_path / "2026-09-10.csv"
    path.write_text("Timestamp,High,Low,Close,Volume,BuyQty,SellQty\n2026-09-10 12:00:00,102,99,101,10,6,4\n", encoding="utf-8")
    feed, columns = s.load_verified_feed([path], pd.Timestamp("2026-09-10T12:00:00Z"))
    assert feed.iloc[0]["OpenPrice"] == 101
    assert feed.iloc[0]["OpenInterest"] == 0
    assert "OpenPrice" not in columns[path.name]
    assert "OpenInterest" not in columns[path.name]
    segment = s._window(feed, feed.iloc[0]["Timestamp"], 0, 0, columns)
    assert segment["open_interest_change"] is None


def test_qualification_precedes_nearest_selection():
    frame = pd.DataFrame([
        {"zone_id": "tracking", "status": "TRACKING_ONLY", "price_lower": 102, "price_upper": 103},
        {"zone_id": "qualified", "status": "QUALIFIED", "price_lower": 104, "price_upper": 105},
    ])
    assert s._nearest_qualified(frame, 100, "long")["zone_id"] == "qualified"


def test_active_liquidity_distinct_from_structure(inputs, monkeypatch):
    seed, feed, columns = inputs
    registry = pd.DataFrame([{
        "zone_id": "zone_1", "side": "BUY_SIDE", "price_lower": 104.0, "price_upper": 105.0,
        "price_mid": 104.5, "first_seen_at": "2026-09-10T11:00:00Z", "status": "ACTIVE",
        "active_forward": "true", "consumption_status": "FRESH", "active_forward_role": "REACTION_ZONE",
    }])
    active = registry.copy()
    significant = pd.DataFrame([{"zone_id": "sig_1", "status": "QUALIFIED", "price_lower": 103.0,
                                 "price_upper": 103.5, "first_seen_at": "2026-09-10T11:00:00Z"}])
    monkeypatch.setattr(s, "_structure_frames", lambda *args: (registry, active, significant))
    structure, _ = REAL_STRUCTURE_VIEW(feed, feed, feed["Timestamp"].iloc[-1], seed["execution"], "long")
    assert structure["nearest_qualified_opposing_zone"]["zone_id"] == "sig_1"
    assert structure["nearest_active_liquidity_in_trade_direction"]["side"] == "BUY_SIDE"
    assert structure["nearest_active_liquidity_in_trade_direction"]["zone_id"] == "zone_1"


def test_selected_zone_retains_matched_registry_lifecycle(inputs, monkeypatch):
    seed, feed, _ = inputs
    registry = pd.DataFrame([{
        "zone_id": "registry_zone", "side": "BUY_SIDE", "price_lower": 103.0,
        "price_upper": 104.0, "price_mid": 103.5,
        "first_seen_at": "2026-09-10T11:00:00Z",
        "accepted_above_at": "2026-09-10T11:20:00Z", "status": "ACTIVE",
    }])
    significant = pd.DataFrame([{
        "zone_id": "significant_zone", "status": "QUALIFIED", "price_lower": 103.2,
        "price_upper": 103.8, "first_seen_at": "2026-09-09T12:00:00Z",
    }])
    monkeypatch.setattr(s, "_structure_frames", lambda *args: (registry, pd.DataFrame(), significant))
    prior = feed.iloc[:1].copy()
    prior.loc[:, "Timestamp"] = pd.Timestamp("2026-09-09T12:00:00Z")
    prior.loc[:, "HiPrice"] = 104.0
    prior.loc[:, "LowPrice"] = 102.0
    context = pd.concat([prior, feed], ignore_index=True)
    structure, _ = REAL_STRUCTURE_VIEW(feed, context, feed["Timestamp"].iloc[-1], seed["execution"], "long")
    zone = structure["nearest_qualified_opposing_zone"]
    assert zone["zone_id"] == "significant_zone"
    assert zone["lower"] == 103.2
    assert zone["distance_from_current_price_market_quote"] == 2.2
    assert zone["interaction_count"] == 1
    assert zone["matched_registry_lifecycle"]["zone_id"] == "registry_zone"
    assert zone["matched_registry_lifecycle"]["accepted_above_timestamp"] == "2026-09-10T11:20:00Z"


def test_accepted_beyond_lifecycle_and_recent_cleared_determinism(inputs):
    _, feed, _ = inputs
    cutoff = feed["Timestamp"].iloc[-1]
    registry = pd.DataFrame([
        {"zone_id": "old", "side": "BUY_SIDE", "price_lower": 90, "price_upper": 92,
         "first_seen_at": "2026-09-10T00:00:00Z", "accepted_above_at": "2026-09-10T10:00:00Z"},
        {"zone_id": "recent", "side": "BUY_SIDE", "price_lower": 95, "price_upper": 97,
         "first_seen_at": "2026-09-10T00:00:00Z", "accepted_above_at": "2026-09-10T11:00:00Z"},
    ])
    selected = s._recent_cleared(registry, feed, cutoff, 101.0, "long")
    assert selected["zone_id"] == "recent"
    assert selected["accepted_beyond_timestamp"] == "2026-09-10T11:00:00Z"
    assert selected["minutes_since_acceptance"] == 60
    assert s._recent_cleared(registry.iloc[::-1], feed, cutoff, 101.0, "long")["zone_id"] == "recent"


def test_zone_lifecycle_cannot_read_after_cutoff(inputs):
    _, feed, _ = inputs
    zone = {"zone_id": "bad", "price_lower": 100, "price_upper": 101,
            "first_seen_at": "2026-09-10T11:00:00Z", "accepted_above_at": "2026-09-10T12:01:00Z"}
    with pytest.raises(s.SnapshotContractError, match="after prediction cutoff"):
        s._zone_fact(zone, cutoff=feed["Timestamp"].iloc[-1], current=feed)


def test_identical_evidence_builds_byte_identical_input_and_prompt(inputs):
    seed, feed, columns = inputs
    one = s.build_snapshot(seed, feed, columns)
    two = s.build_snapshot(deepcopy(seed), feed.copy(), deepcopy(columns))
    assert s.canonical_json(one) == s.canonical_json(two)
    assert p.prompt_record(one) == p.prompt_record(two)


def test_prior_overlapping_horizon_dump_cannot_drive_segments(inputs):
    seed, feed, columns = inputs
    one = s.build_snapshot(seed, feed, columns)
    with_old_horizons = deepcopy(seed)
    with_old_horizons["market"] = {"horizons": {"1440m": {"delta": 999999, "open_interest_change": -999999}}}
    two = s.build_snapshot(with_old_horizons, feed, columns)
    assert s.canonical_json(one) == s.canonical_json(two)


def test_unclear_contract_requires_specific_absent_fact(inputs):
    seed, feed, columns = inputs
    view = s.build_snapshot(seed, feed, columns)
    prediction = {"predicted_outcome_class": "UNCLEAR", "confidence": 0.4,
                  "primary_evidence_for": [], "primary_evidence_against": [],
                  "uncertainty_reason": "OpenInterest is absent", "missing_evidence": ["open_interest_source_column_unavailable"]}
    with pytest.raises(ValueError, match="INVALID_UNCLEAR_CONTRACT"):
        p.validate_prediction(prediction, view)
    view["quality"]["missing_evidence"] = ["open_interest_source_column_unavailable"]
    assert p.validate_prediction(prediction, view)["predicted_outcome_class"] == "UNCLEAR"
    prediction["missing_evidence"] = []
    with pytest.raises(ValueError, match="INVALID_UNCLEAR_CONTRACT"):
        p.validate_prediction(prediction, view)


def test_prior_frozen_research_artifacts_unchanged():
    verify_old_artifacts()


def test_prepared_blind_bundle_integrity():
    bundle = Path(__file__).resolve().parents[1] / "docs/research/open_trade_outcome_predictor_v1/blind_run_v3"
    pairs = _verify_bundle(bundle)
    assert len(pairs) == 20
    for row, snapshot, prompt in pairs:
        assert row["trade_key"] == snapshot["signal"]["trade_key"] == prompt["trade_key"]
        assert len(snapshot["temporal_market"]["segments"]) == 5
        assert [item["segment"] for item in snapshot["temporal_market"]["segments"]] == [item[0] for item in s.SEGMENTS]
        assert all(item["complete"] for item in snapshot["temporal_market"]["segments"])
