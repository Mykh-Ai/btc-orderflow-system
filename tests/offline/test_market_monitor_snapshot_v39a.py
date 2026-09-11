from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from executor_mod.market_monitor_snapshot_v39a import (
    LOCAL_WINDOWS_MINUTES,
    SNAPSHOT_SCHEMA_VERSION,
    STATE_SCHEMA_VERSION,
    MonitorSnapshotV39AError,
    build_market_monitor_snapshot_v39a,
)


def _feed(periods: int = 2_880) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=periods, freq="min")
    close = 100_000.0 + pd.Series(range(periods), dtype=float) * 0.5
    return pd.DataFrame(
        {
            "Timestamp": timestamps,
            "OpenPrice": close,
            "HiPrice": close + 10.0,
            "LowPrice": close - 10.0,
            "ClosePrice": close + 1.0,
            "TotalQty": 100.0,
            "Trades": 10,
            "BuyQty": 60.0,
            "SellQty": 40.0,
            "OpenInterest": 10_000.0,
            "FundingRate": 0.00001,
            "DataQuality": "RAW",
            "SourceFile": "2026-01-01.csv",
        }
    )


def _forbidden_keys(value):
    forbidden = {"orders", "order_id", "client_id", "outcome", "pnl", "trailing"}
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                found.append(str(key))
            found.extend(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_forbidden_keys(child))
    return found


def test_v39a_uses_exact_closed_windows_and_excludes_future_rows(tmp_path: Path):
    frame = _feed()
    cutoff = pd.Timestamp("2026-01-02T00:04:00Z")
    snapshot = build_market_monitor_snapshot_v39a(
        frame,
        cutoff_ts=cutoff,
        state_path=tmp_path / "state.json",
        symbol="BTCUSDT",
    )

    assert snapshot["schema_version"] == SNAPSHOT_SCHEMA_VERSION
    assert snapshot["cutoff_ts"] == "2026-01-02T00:04:00Z"
    assert snapshot["bar_contract"]["closed_rows_only"] is True
    assert tuple(int(key) for key in snapshot["windows"]) == LOCAL_WINDOWS_MINUTES
    for minutes in LOCAL_WINDOWS_MINUTES:
        window = snapshot["windows"][str(minutes)]
        assert window["expected_rows"] == minutes
        assert window["rows_used"] == minutes
        assert window["complete"] is True
    assert snapshot["quality"]["future_rows_excluded"] == 1_435
    assert snapshot["quality"]["cutoff_is_latest_used_row"] is True


def test_v39a_carries_state_across_utc_midnight(tmp_path: Path):
    frame = _feed()
    state_path = tmp_path / "runtime_state.json"
    base = {
        "schema_version": "market_monitor_snapshot_v1",
        "significant_market_zones": {"above_price": [{"zone_id": "z1"}]},
        "liquidity_zones": {"above_price": [{"zone_id": "z1"}]},
    }
    first = build_market_monitor_snapshot_v39a(
        frame,
        cutoff_ts="2026-01-01T23:59:00Z",
        state_path=state_path,
        base_snapshot=base,
        persist_state=True,
    )
    second = build_market_monitor_snapshot_v39a(
        frame,
        cutoff_ts="2026-01-02T00:04:00Z",
        state_path=state_path,
        base_snapshot=None,
        persist_state=True,
    )

    assert first["state_memory"]["continuity"] == "INITIALIZED"
    memory = second["state_memory"]
    assert memory["continuity"] == "CONTINUOUS_CARRY_FORWARD"
    assert memory["carried_forward"] is True
    assert memory["daily_boundary"]["changed"] is True
    assert memory["daily_boundary"]["state_carried_across_boundary"] is True
    assert second["liquidity_zones"]["available"] is True
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["state_schema_version"] == STATE_SCHEMA_VERSION
    assert persisted["market_day_utc"] == "2026-01-02"


def test_v39a_marks_recovered_quality_and_keeps_lineage(tmp_path: Path):
    frame = _feed()
    frame.loc[frame["Timestamp"] >= pd.Timestamp("2026-01-02T00:00:00Z"), "DataQuality"] = "RECOVERED_DEGRADED"
    snapshot = build_market_monitor_snapshot_v39a(
        frame,
        cutoff_ts="2026-01-02T00:04:00Z",
        state_path=tmp_path / "state.json",
        lineage={"feed_identity": "server-feed-2026-09-11", "source_hashes": {"2026-01-01.csv": "abc"}},
    )

    assert snapshot["quality"]["recovered_degraded_present"] is True
    assert snapshot["quality"]["readiness"] == "READY_WITH_RECOVERED_DATA"
    assert snapshot["windows"]["5"]["status"] == "COMPLETE_RECOVERED_DEGRADED"
    assert snapshot["lineage"]["source_hashes"] == {"2026-01-01.csv": "abc"}
    assert _forbidden_keys(snapshot) == []


def test_v39a_marks_missing_closed_rows_as_partial(tmp_path: Path):
    frame = _feed()
    missing_ts = pd.Timestamp("2026-01-02T00:00:00Z")
    frame = frame[frame["Timestamp"] != missing_ts].copy()
    snapshot = build_market_monitor_snapshot_v39a(
        frame,
        cutoff_ts="2026-01-02T00:04:00Z",
        state_path=tmp_path / "state.json",
    )

    assert snapshot["windows"]["5"]["complete"] is False
    assert snapshot["windows"]["5"]["status"] == "PARTIAL"
    assert snapshot["windows"]["5"]["rows_used"] == 4
    assert "2026-01-02T00:00:00Z" in snapshot["windows"]["5"]["missing_timestamps"]
    assert "5" in snapshot["quality"]["incomplete_windows"]


def test_v39a_rejects_cutoff_after_available_feed():
    with pytest.raises(MonitorSnapshotV39AError, match="later than the available feed"):
        build_market_monitor_snapshot_v39a(_feed(), cutoff_ts="2026-01-03T00:00:00Z")
