"""Regression contracts for the sole production Market Monitor."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from executor_mod.entry_snapshot import EntrySnapshotError, validate_canonical_monitor_snapshot
from executor_mod.llm_trade_judge import build_market_monitor_snapshot_until_cutoff
from market_monitor.feed_adapter import load_feed
from market_monitor.snapshot_builder_v39a import build_market_monitor_snapshot_v39a


CUTOFF = "2026-09-14T02:12:00Z"


def _feed(periods: int = 1450) -> pd.DataFrame:
    timestamps = pd.date_range("2026-09-13T02:13:00Z", periods=periods, freq="min")
    return pd.DataFrame({
        "Timestamp": timestamps,
        "OpenPrice": 100.0,
        "HiPrice": 101.0,
        "LowPrice": 99.0,
        "ClosePrice": 100.0,
        "TotalQty": 10.0,
        "BuyQty": 6.0,
        "SellQty": 4.0,
        "OpenInterest": 1000.0,
        "FundingRate": 0.0,
        "LiqBuyQty": 0.0,
        "LiqSellQty": 0.0,
    })


def _write_daily(root: Path, feed: pd.DataFrame) -> None:
    for day, frame in feed.groupby(feed["Timestamp"].dt.date):
        frame.to_csv(root / f"{day.isoformat()}.csv", index=False)


def test_240m_crosses_midnight_with_exact_rows_and_source_files(tmp_path: Path) -> None:
    _write_daily(tmp_path, _feed())
    snapshot = build_market_monitor_snapshot_v39a(load_feed(tmp_path, deduplicate=False), cutoff_ts=CUTOFF)
    window = snapshot["windows"]["240"]
    assert (window["expected_rows"], window["rows_used"], window["complete"]) == (240, 240, True)
    assert window["start_timestamp"] == "2026-09-13T22:13:00Z"
    assert snapshot["lineage"]["source_files"] == ["2026-09-13.csv", "2026-09-14.csv"]


def test_1440m_crosses_feed_files_with_exact_rows(tmp_path: Path) -> None:
    _write_daily(tmp_path, _feed())
    snapshot = build_market_monitor_snapshot_v39a(load_feed(tmp_path, deduplicate=False), cutoff_ts=CUTOFF)
    window = snapshot["windows"]["1440"]
    assert (window["expected_rows"], window["rows_used"], window["complete"]) == (1440, 1440, True)
    assert window["start_timestamp"] == "2026-09-13T02:13:00Z"
    assert snapshot["quality"]["readiness"] == "READY"
    validate_canonical_monitor_snapshot(snapshot)


def test_missing_previous_day_is_explicitly_incomplete(tmp_path: Path) -> None:
    _write_daily(tmp_path, _feed())
    (tmp_path / "2026-09-13.csv").unlink()
    snapshot = build_market_monitor_snapshot_v39a(load_feed(tmp_path, deduplicate=False), cutoff_ts=CUTOFF)
    assert snapshot["windows"]["240"]["rows_used"] == 133
    assert snapshot["windows"]["240"]["metrics_valid"] is False
    assert snapshot["quality"]["readiness"] == "INCOMPLETE"
    with pytest.raises(EntrySnapshotError):
        validate_canonical_monitor_snapshot(snapshot)


def test_duplicate_timestamp_blocks_readiness_and_is_reported(tmp_path: Path) -> None:
    feed = _feed()
    feed = pd.concat([feed, feed.iloc[[-1]]], ignore_index=True)
    _write_daily(tmp_path, feed)
    loaded = load_feed(tmp_path)
    assert len(loaded) == len(feed)
    snapshot = build_market_monitor_snapshot_v39a(loaded, cutoff_ts=feed["Timestamp"].max())
    assert snapshot["quality"]["readiness"] == "INCOMPLETE"
    assert snapshot["quality"]["context_duplicate_rows"] == 1
    assert snapshot["windows"]["5"]["duplicate_rows"] == 1


def test_recovered_data_has_explicit_readiness() -> None:
    feed = _feed()
    feed["DataQuality"] = "RAW"
    feed.loc[100, "DataQuality"] = "RECOVERED_DEGRADED"
    snapshot = build_market_monitor_snapshot_v39a(feed, cutoff_ts=CUTOFF)
    assert snapshot["quality"]["readiness"] == "READY_WITH_DEGRADED_DATA"
    assert snapshot["windows"]["1440"]["recovered_degraded"] is True


def test_features_are_computed_directly_from_canonical_feed() -> None:
    snapshot = build_market_monitor_snapshot_v39a(_feed(), cutoff_ts=CUTOFF)
    assert snapshot["market_state"]["algorithm"] == "market_state_timeline"
    assert snapshot["market_structure_state"]["algorithm"] == "market_structure_state_classifier"
    assert snapshot["market_structure_state"]["state"]
    assert isinstance(snapshot["market_structure_state"]["support"], dict)
    assert isinstance(snapshot["market_structure_state"]["resistance"], dict)
    assert set(snapshot["liquidity_zones"]) == {"above_price", "below_price"}
    assert set(snapshot["significant_market_zones"]) == {"near_price", "above_price", "below_price"}
    assert snapshot["units"]["delta_pct"] == "fraction_of_total_qty"
    assert snapshot["windows"]["60"]["delta_pct"] == 0.2
    assert snapshot["market_structure_state"]["metrics"]["delta_pct"] == 0.2
    assert snapshot["windows"]["1440"]["poc"] is None


def test_restart_is_deterministic_at_same_cutoff(tmp_path: Path) -> None:
    feed = _feed()
    state_path = tmp_path / "state.json"
    build_market_monitor_snapshot_v39a(feed, cutoff_ts=CUTOFF, state_path=state_path)
    later = "2026-09-14T02:13:00Z"
    first = build_market_monitor_snapshot_v39a(feed, cutoff_ts=later, state_path=state_path)
    state_after_first = json.loads(state_path.read_text(encoding="utf-8"))
    second = build_market_monitor_snapshot_v39a(feed, cutoff_ts=later, state_path=state_path)
    assert json.loads(state_path.read_text(encoding="utf-8")) == state_after_first
    assert first["market_state"] == second["market_state"]
    assert first["structure"] == second["structure"]
    assert second["state_memory"]["carried_forward"] is True


def test_restart_replay_preserves_midnight_rollover_state(tmp_path: Path) -> None:
    feed = _feed(2760)
    state_path = tmp_path / "state.json"
    build_market_monitor_snapshot_v39a(feed, cutoff_ts="2026-09-14T23:59:00Z", state_path=state_path)
    first = build_market_monitor_snapshot_v39a(feed, cutoff_ts="2026-09-15T00:04:00Z", state_path=state_path)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    second = build_market_monitor_snapshot_v39a(feed, cutoff_ts="2026-09-15T00:04:00Z", state_path=state_path)
    assert first["state_memory"]["daily_boundary"]["changed"] is True
    assert first["state_memory"]["daily_boundary"]["state_carried_across_boundary"] is True
    assert json.loads(state_path.read_text(encoding="utf-8")) == persisted
    assert second["state_memory"]["daily_boundary"] == first["state_memory"]["daily_boundary"]


def test_entry_rejects_noncanonical_schema_and_missing_feature_lineage() -> None:
    with pytest.raises(EntrySnapshotError, match="canonical_market_monitor_snapshot_required"):
        validate_canonical_monitor_snapshot({"schema_version": "obsolete"})
    snapshot = build_market_monitor_snapshot_v39a(_feed(), cutoff_ts=CUTOFF)
    snapshot["lineage"].pop("feature_algorithms")
    with pytest.raises(EntrySnapshotError, match="feature_lineage_invalid"):
        validate_canonical_monitor_snapshot(snapshot)


def test_runtime_uses_one_builder_and_no_legacy_selector() -> None:
    root = Path(__file__).resolve().parents[1]
    runtime = [root / "executor.py", *sorted((root / "executor_mod").glob("*.py")), root / "market_monitor" / "snapshot_builder_v39a.py"]
    source = "\n".join(path.read_text(encoding="utf-8") for path in runtime)
    assert "market_monitor_snapshot_v1" not in source
    assert "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED" not in source
    assert "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED" not in source
    assert "base_snapshot" not in source
    assert "trader_snapshot_builder" not in source
    assert "run_market_monitor" not in source
    assert not (root / "market_monitor" / "snapshot_builder.py").exists()
    assert not (root / "executor_mod" / "market_monitor_snapshot_v39a.py").exists()


def test_judge_boundary_returns_incomplete_diagnostic_without_legacy_fallback(tmp_path: Path) -> None:
    _write_daily(tmp_path, _feed())
    (tmp_path / "2026-09-13.csv").unlink()
    result = build_market_monitor_snapshot_until_cutoff(
        {"analysis_cutoff_ts": CUTOFF, "symbol": "BTCUSDC"},
        {"LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": str(tmp_path), "LLM_TRADE_JUDGE_MARKET_MONITOR_STATE_PATH": str(tmp_path / "state.json")},
    )
    assert result["schema_version"] == "market_monitor_snapshot_v39a"
    assert result["quality"]["readiness"] == "INCOMPLETE"
    assert "market_monitor_incomplete_240m" in result["data_gaps"]
    assert not (tmp_path / "state.json").exists()


def test_judge_boundary_uses_single_canonical_builder_and_file_hashes(tmp_path: Path) -> None:
    _write_daily(tmp_path, _feed())
    state_path = tmp_path / "state.json"
    result = build_market_monitor_snapshot_until_cutoff(
        {"analysis_cutoff_ts": CUTOFF, "symbol": "BTCUSDC", "src_evt": {"kind": "long"}},
        {"LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": str(tmp_path), "LLM_TRADE_JUDGE_MARKET_MONITOR_STATE_PATH": str(state_path)},
    )
    validate_canonical_monitor_snapshot(result)
    assert result["quality"]["readiness"] == "READY"
    assert set(result["lineage"]["source_hashes"]) == {"2026-09-13.csv", "2026-09-14.csv"}
    assert state_path.exists()
