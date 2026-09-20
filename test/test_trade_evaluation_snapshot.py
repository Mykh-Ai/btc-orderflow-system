"""Research-only post-fill model input and no-hindsight contracts."""
from __future__ import annotations

import json
import csv
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from executor_mod.trade_evaluation_snapshot import (
    HORIZONS, TradeEvaluationSnapshotError, build_trade_evaluation_snapshot,
)
from market_monitor.snapshot_builder_v39a import _window_metrics


def _pack() -> dict:
    return {
        "trade_key": "EX_EN_TEST", "direction": "long", "peak_ts": "2026-09-19T23:59:00Z",
        "filled_at": "2026-09-20T00:01:20Z", "entry_actual": 101.0,
        "qty": 2.0, "executedQty": "2", "entry_mode": "LIMIT_THEN_MARKET",
        "prices": {"entry": 100.0, "sl": 99.0, "tp1": 103.0, "tp2": 105.0},
        "src_evt": {"kind": "long", "ts": "2026-09-19T23:59:00Z", "price_usdt": 100.0, "delta": 4.0, "vol": 10.0, "imb": 0.4, "vwap": 99.5, "poc": 99.0},
        "k_entry": 1.0,
        "outcome": "SL", "realized_pnl": -50, "trailing": {"moved_to_be": True},
    }


def _monitor() -> dict:
    end = "2026-09-20T00:01:00+00:00"
    horizon = {
        "start_timestamp": "2026-09-19T23:57:00+00:00", "end_timestamp": end,
        "expected_rows": 5, "rows_used": 5, "complete": True, "metrics_valid": True,
        "status": "COMPLETE_RAW", "missing_timestamps": [], "missing_timestamp_count": 0,
        "duplicate_rows": 0, "data_quality_counts": {"RAW": 5}, "recovered_degraded": False,
        "open": 100.0, "close": 101.0, "high": 102.0, "low": 98.0,
        "price_change": 1.0, "price_change_pct": 1.0, "range_position": 0.75,
        "delta": 4.0, "delta_pct": 0.4, "total_qty": 10.0,
        "open_interest_change": 3.0, "vwap_approx": 100.5,
        "price_minus_vwap_approx": 0.5, "price_minus_vwap_approx_pct": 0.49751244,
        "poc": None, "poc_status": "UNAVAILABLE_PRICE_VOLUME_DISTRIBUTION_MISSING",
    }
    return {
        "schema_version": "market_monitor_snapshot_v39a", "cutoff_ts": end,
        "current": {"price": 101.0}, "horizons": {key: horizon.copy() for key in HORIZONS},
        "quality": {"readiness": "READY", "future_rows_excluded": 0, "recovered_degraded_present": False},
        "market_state": {"state": "RANGE", "algorithm": "market_state_timeline"},
        "market_structure_state": {
            "state": "RANGE", "algorithm": "market_structure_state_classifier", "candidate_bias": "LONG",
            "support": {"zone_id": "support", "price_lower": 98.5, "price_upper": 99.5, "status": "QUALIFIED"},
            "resistance": {"zone_id": "resistance", "price_lower": 102.0, "price_upper": 104.0, "status": "QUALIFIED"},
        },
        "significant_market_zones": {"near_price": [{"zone_id": "r1", "price_lower": 102.0, "price_upper": 104.0, "status": "QUALIFIED"}], "above_price": [], "below_price": []},
        "liquidity_zones": {"above_price": [{"zone_id": "l1", "zone_type": "LIQUIDITY", "price_lower": 104.0, "price_upper": 104.5}], "below_price": []},
        "context_conflicts": [],
    }


def _build(pack: dict | None = None, monitor: dict | None = None, cutoff: str | None = "2026-09-20T00:03:00Z") -> dict:
    return build_trade_evaluation_snapshot(pack or _pack(), monitor or _monitor(),
        assessment_cutoff_utc=cutoff, assessment_cutoff_source="judge_call_start",
        market_quote_currency="USDT", execution_quote_currency="USDC")


def test_actual_fill_entry_and_stop_target_geometry_are_factual() -> None:
    snapshot = _build()
    execution = snapshot["execution"]
    assert snapshot["signal"]["signal_price"] == 100.0
    assert execution["actual_entry_price"] == 101.0
    assert execution["actual_fill_timestamp_utc"] < snapshot["assessment_cutoff_utc"]
    assert execution["entry_minus_signal_usd_approx"] == 1.0
    assert execution["entry_minus_signal_pct_approx"] == 1.0
    assert execution["risk_entry_to_sl_usd"] == 2.0
    assert execution["risk_entry_to_sl_pct"] == round(2 / 101 * 100, 10)
    assert execution["reward_entry_to_tp1_usd"] == 2.0
    assert execution["tp1_R"] == 1.0
    assert execution["reward_entry_to_tp2_usd"] == 4.0
    assert execution["tp2_R"] == 2.0


def test_zone_geometry_uses_actual_entry_and_targets() -> None:
    zones = _build()["market"]["zones"]
    resistance = next(z for z in zones if z["zone_id"] == "resistance")
    assert resistance["signed_distance_from_actual_entry_usd_approx"] == 1.0
    assert resistance["signed_distance_from_actual_entry_R_approx"] == 0.5
    assert resistance["intersects_entry_to_tp1"] is True
    assert resistance["intersects_entry_to_tp2"] is True
    assert resistance["signed_distance_from_tp1_usd_approx"] == 0.0
    liquidity = next(z for z in zones if z["zone_id"] == "l1")
    assert liquidity["intersects_entry_to_tp1"] is False
    assert liquidity["intersects_entry_to_tp2"] is True


def test_horizons_use_single_shape_and_one_day_alias() -> None:
    market = _build()["market"]
    assert tuple(market["horizons"]) == HORIZONS
    assert market["horizon_aliases"] == {"1d": "1440m"}
    assert all(set(row) == set(market["horizons"]["5m"]) for row in market["horizons"].values())
    assert all(row["current_price_position_in_range"] == 0.75 for row in market["horizons"].values())
    assert all(row["poc"] is None for row in market["horizons"].values())


def test_broad_rolling_window_has_geometry_and_explicit_incompleteness() -> None:
    cutoff = pd.Timestamp("2026-09-20T00:01:00Z")
    frame = pd.DataFrame({
        "Timestamp": pd.date_range(end=cutoff, periods=43200, freq="min", tz="UTC"),
        "OpenPrice": 100.0, "HiPrice": 102.0, "LowPrice": 98.0, "ClosePrice": 101.0,
        "TotalQty": 10.0, "BuyQty": 6.0, "SellQty": 4.0, "OpenInterest": 1000.0,
        "FundingRate": 0.0, "DataQuality": "RAW",
    })
    for days in (3, 7, 30):
        row = _window_metrics(frame, minutes=days * 1440, cutoff=cutoff)
        assert row["complete"] is True
        assert row["rows_used"] == days * 1440
        assert (row["high"], row["low"], row["range_position"]) == (102.0, 98.0, 0.75)
        assert row["vwap_approx"] is not None
        assert row["price_minus_vwap_approx"] is not None
        assert row["delta_pct"] == 0.2
    incomplete = _window_metrics(frame.iloc[1:], minutes=30 * 1440, cutoff=cutoff)
    assert incomplete["complete"] is False
    assert incomplete["missing_timestamp_count"] == 1
    monitor = _monitor()
    monitor["horizons"]["30d"]["complete"] = False
    monitor["quality"]["readiness"] = "READY_WITH_PARTIAL_CONTEXT"
    result = _build(monitor=monitor)
    assert "30d" in result["quality"]["incomplete_horizons"]
    assert result["quality"]["status"] == "PARTIAL"


def test_no_future_market_or_outcome_leaks_and_rebuild_is_deterministic() -> None:
    first = _build()
    second = _build()
    assert first == second
    text = json.dumps(first, sort_keys=True).lower()
    for forbidden in ('"outcome"', '"realized_pnl"', '"trailing"', '"verdict"'):
        assert forbidden not in text
    monitor = _monitor()
    monitor["horizons"]["30d"]["end_timestamp"] = "2026-09-20T00:04:00Z"
    with pytest.raises(TradeEvaluationSnapshotError, match="future or mismatched"):
        _build(monitor=monitor)
    monitor = _monitor()
    monitor["quality"]["cutoff_is_latest_used_row"] = False
    with pytest.raises(TradeEvaluationSnapshotError, match="beyond cutoff"):
        _build(monitor=monitor)


def test_unknown_historical_invocation_time_is_visible_not_guessed() -> None:
    result = _build(cutoff=None)
    assert result["assessment_cutoff_utc"] is None
    assert result["quality"]["exact_assessment_cutoff"] is False
    assert result["quality"]["status"] == "PARTIAL"
    pack = _pack()
    pack["filled_at"] = "2026-09-20T00:04:00Z"
    with pytest.raises(TradeEvaluationSnapshotError, match="chronology"):
        _build(pack=pack)


def test_frozen_research_artifacts_keep_outcomes_separate_and_hashes_valid() -> None:
    root = Path(__file__).resolve().parents[1] / "docs" / "research" / "canonical_trade_evaluation_snapshot"
    rows = list(csv.DictReader((root / "case_ledger.csv").open(encoding="utf-8", newline="")))
    lines = (root / "frozen_trade_evaluation_snapshots.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 26
    assert len(lines) == 24
    ledger = {row["trade_key"]: row for row in rows}
    for line in lines:
        snapshot = json.loads(line)
        key = snapshot["signal"]["trade_key"]
        assert ledger[key]["snapshot_sha256"] == hashlib.sha256(line.encode("utf-8")).hexdigest()
        assert snapshot["assessment_cutoff_utc"] is None
        assert pd.Timestamp(snapshot["market_cutoff_utc"]) <= pd.Timestamp(snapshot["execution"]["actual_fill_timestamp_utc"])
        assert snapshot["quality"]["status"] == "PARTIAL"
        assert not any(token in line.lower() for token in ('"outcome"', '"realized_pnl"', '"trailing"', '"verdict"'))
