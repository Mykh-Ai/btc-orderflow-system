from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

from executor_mod import llm_trade_judge as judge  # noqa: E402


def _write_feed(root: Path) -> None:
    (root / "2026-01-01.csv").write_text("placeholder\n", encoding="utf-8")


def _feed_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=20, freq="min")
    close = pd.Series([100_000.0 + minute for minute in range(20)], dtype=float)
    return pd.DataFrame(
        {
            "Timestamp": timestamps,
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": 100.0,
            "AggTrades": 10,
            "BuyQty": 60.0,
            "SellQty": 40.0,
            "OpenInterest": 10_000.0,
            "FundingRate": 0.00001,
            "IsSynthetic": 0,
        }
    )


def _install_monitor_modules(monkeypatch, base_snapshot):
    package = types.ModuleType("market_monitor")
    package.__path__ = []
    feed_module = types.ModuleType("market_monitor.feed_adapter")
    feed_module.load_feed = lambda _path: _feed_frame()
    snapshot_module = types.ModuleType("market_monitor.snapshot_builder")
    snapshot_module.build_market_monitor_snapshot = lambda *args, **kwargs: base_snapshot
    monkeypatch.setitem(sys.modules, "market_monitor", package)
    monkeypatch.setitem(sys.modules, "market_monitor.feed_adapter", feed_module)
    monkeypatch.setitem(sys.modules, "market_monitor.snapshot_builder", snapshot_module)


def _base_snapshot():
    return {
        "schema_version": "market_monitor_snapshot_v1",
        "significant_market_zones": {"above_price": [], "below_price": [], "near_price": []},
        "liquidity_zones": {"above_price": [], "below_price": []},
        "market_structure_state": {"market_state": "TEST_STATE"},
    }


def _evidence():
    return {
        "analysis_cutoff_ts": "2026-01-01T00:19:00Z",
        "symbol": "BTCUSDT",
        "entry_actual": 100_019.0,
    }


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


def test_v39a_hook_off_preserves_v1_snapshot(tmp_path: Path, monkeypatch):
    _write_feed(tmp_path)
    _install_monitor_modules(monkeypatch, _base_snapshot())
    cfg = {
        "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": True,
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED": False,
    }
    snapshot = judge.build_market_monitor_snapshot_until_cutoff(_evidence(), cfg)
    assert snapshot["schema_version"] == "market_monitor_snapshot_v1"
    assert "runtime_mode" not in snapshot
    assert "state_memory" not in snapshot


def test_v39a_hook_on_uses_state_path_and_keeps_management_fields_out(tmp_path: Path, monkeypatch):
    _write_feed(tmp_path)
    _install_monitor_modules(monkeypatch, _base_snapshot())
    state_path = tmp_path / "state" / "market_monitor_state_v39a.json"
    cfg = {
        "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": True,
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED": True,
        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_STATE_PATH": str(state_path),
    }
    snapshot = judge.build_market_monitor_snapshot_until_cutoff(_evidence(), cfg)
    assert snapshot["schema_version"] == "market_monitor_snapshot_v39a"
    assert snapshot["runtime_mode"] == "v39a_opt_in"
    assert snapshot["lineage"]["state_file"] == str(state_path)
    assert state_path.exists()
    assert snapshot["quality"]["future_rows_excluded"] == 0
    assert _forbidden_keys(snapshot) == []


def test_v39a_flag_is_independent_opt_in_gate(tmp_path: Path, monkeypatch):
    _write_feed(tmp_path)
    _install_monitor_modules(monkeypatch, _base_snapshot())
    cfg = {
        "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": False,
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": str(tmp_path),
        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED": True,
        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_STATE_PATH": str(tmp_path / "state.json"),
    }
    snapshot = judge.build_market_monitor_snapshot_until_cutoff(_evidence(), cfg)
    assert snapshot["schema_version"] == "market_monitor_snapshot_v39a"
