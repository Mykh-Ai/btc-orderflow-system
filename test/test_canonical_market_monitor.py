"""Regression coverage for the single model-facing Market Monitor path."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from executor_mod import llm_trade_judge as judge
from executor_mod.entry_snapshot import EntrySnapshotError, build_entry_snapshot
from executor_mod.market_monitor_snapshot_v39a import build_market_monitor_snapshot_v39a


def _feed():
    stamps = pd.date_range("2026-09-13T00:00:00Z", "2026-09-14T02:12:00Z", freq="min")
    rows = []
    for i, ts in enumerate(stamps):
        rows.append({
            "Timestamp": ts,
            "OpenPrice": 77000.0 + i * 0.1,
            "HiPrice": 77001.0 + i * 0.1,
            "LowPrice": 76999.0 + i * 0.1,
            "ClosePrice": 77000.5 + i * 0.1,
            "TotalQty": 10.0,
            "Trades": 10,
            "BuyQty": 6.0,
            "SellQty": 4.0,
            "OpenInterest": 100000.0 + i,
            "FundingRate": 0.0001,
            "LiqBuyQty": 0.0,
            "LiqSellQty": 0.0,
            "IsSynthetic": 0,
        })
    return pd.DataFrame(rows)


def _write_days(frame, root):
    for day, rows in frame.groupby(frame["Timestamp"].dt.strftime("%Y-%m-%d")):
        rows.to_csv(Path(root) / f"{day}.csv", index=False)


def _pos():
    return {
        "status": "OPEN", "mode": "live", "side": "LONG", "qty": 0.1,
        "entry": 77000.0, "entry_actual": 77000.0,
        "opened_at": "2026-09-14T02:12:05Z", "filled_at": "2026-09-14T02:12:10Z",
        "trade_key": "CANONICAL_TEST", "client_id": "CANONICAL_TEST",
        "orders": {"sl": 1, "tp1": 2, "tp2": 3},
        "prices": {"entry": 77000.0, "sl": 76000.0, "tp1": 78000.0, "tp2": 79000.0},
        "src_evt": {"ts": "2026-09-14T02:12:00Z", "kind": "long", "price": 77000.0},
    }


class CanonicalWindowTests(unittest.TestCase):
    def test_0004_all_six_windows_cross_midnight(self):
        snapshot = build_market_monitor_snapshot_v39a(_feed(), cutoff_ts="2026-09-14T00:04:00Z")
        for minutes in (5, 15, 30, 60, 240, 1440):
            window = snapshot["windows"][str(minutes)]
            self.assertEqual(window["expected_rows"], minutes)
            self.assertEqual(window["rows_used"], minutes)
            self.assertTrue(window["complete"])
            self.assertEqual(window["missing_timestamps"], [])
            self.assertEqual(window["duplicate_rows"], 0)
            self.assertEqual(window["data_quality_counts"], {"RAW": minutes})
        self.assertEqual(snapshot["windows"]["240"]["start_timestamp"], "2026-09-13T20:05:00Z")

    def test_0212_historical_boundary_shape_and_missing_day(self):
        frame = _feed()
        full = build_market_monitor_snapshot_v39a(frame, cutoff_ts="2026-09-14T02:12:00Z")
        window = full["windows"]["240"]
        self.assertEqual((window["expected_rows"], window["rows_used"]), (240, 240))
        self.assertEqual(window["start_timestamp"], "2026-09-13T22:13:00Z")
        self.assertEqual((window["delta"], window["delta_pct"], window["open_interest_change"]), (480.0, 0.2, 239.0))

        day_only = frame[frame["Timestamp"] >= pd.Timestamp("2026-09-14T00:00:00Z")]
        partial = build_market_monitor_snapshot_v39a(day_only, cutoff_ts="2026-09-14T02:12:00Z")
        bad = partial["windows"]["240"]
        self.assertEqual(bad["rows_used"], 133)
        self.assertEqual(bad["status"], "PARTIAL")
        self.assertFalse(bad["metrics_valid"])
        self.assertIsNone(bad["delta"])
        self.assertEqual(len(bad["missing_timestamps"]), 107)
        self.assertIn("240", partial["quality"]["incomplete_windows"])
        self.assertEqual(partial["quality"]["readiness"], "PARTIAL")

    def test_duplicate_is_explicit_and_does_not_advance_state(self):
        frame = _feed()
        duplicate = frame[frame["Timestamp"] == pd.Timestamp("2026-09-14T02:12:00Z")]
        frame = pd.concat([frame, duplicate], ignore_index=True)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            snapshot = build_market_monitor_snapshot_v39a(frame, cutoff_ts="2026-09-14T02:12:00Z", state_path=path)
            self.assertEqual(snapshot["windows"]["5"]["duplicate_rows"], 1)
            self.assertEqual(snapshot["windows"]["5"]["status"], "PARTIAL")
            self.assertFalse(path.exists())

    def test_restart_preserves_cross_midnight_continuity(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            frame = _feed()
            build_market_monitor_snapshot_v39a(frame, cutoff_ts="2026-09-13T23:59:00Z", state_path=state)
            resumed = build_market_monitor_snapshot_v39a(frame, cutoff_ts="2026-09-14T00:04:00Z", state_path=state)
            memory = resumed["state_memory"]
            self.assertEqual(memory["continuity"], "CONTINUOUS_CARRY_FORWARD")
            self.assertTrue(memory["daily_boundary"]["state_carried_across_boundary"])
            self.assertEqual(memory["previous_cutoff_ts"], "2026-09-13T23:59:00Z")
            self.assertEqual(json.loads(state.read_text())["last_cutoff_ts"], "2026-09-14T00:04:00Z")


class CanonicalRoutingTests(unittest.TestCase):
    def test_both_obsolete_flags_false_still_canonical_with_continuous_base(self):
        with tempfile.TemporaryDirectory() as td:
            _write_days(_feed(), td)
            seen = []

            def base_builder(current, **kwargs):
                seen.append(current.copy())
                return {
                    "schema_version": "market_monitor_snapshot_v1",
                    "market_state": {"state": "TEST_STATE"},
                    "market_structure_state": {"candidate_bias": "UP"},
                    "significant_market_zones": {}, "liquidity_zones": {},
                }

            with patch("market_monitor.snapshot_builder.build_market_monitor_snapshot", side_effect=base_builder):
                result = judge.build_market_monitor_snapshot_until_cutoff(
                    {"analysis_cutoff_ts": "2026-09-14T02:12:00Z", "symbol": "BTCUSDC"},
                    {
                        "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": td,
                        "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": str(Path(td) / "2026-09-14.csv"),
                        "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": False,
                        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED": False,
                        "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_STATE_PATH": str(Path(td) / "state.json"),
                    },
                )
            self.assertEqual(result["schema_version"], "market_monitor_snapshot_v39a")
            self.assertEqual(result["windows"]["240"]["rows_used"], 240)
            self.assertEqual(len(seen), 1)
            self.assertEqual(len(seen[0]), 1440)
            self.assertEqual(seen[0]["Timestamp"].iloc[0], pd.Timestamp("2026-09-13T02:13:00Z"))
            self.assertEqual(result["market_state"]["source"], "base_monitor_v1_continuous_1440m")
            self.assertEqual(result["market_structure_state"]["value"]["candidate_bias"], "UP")
            self.assertEqual(result["lineage"]["base_scope"], "continuous_1440_closed_minutes")

    def test_real_base_builder_produces_valid_model_facing_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            _write_days(_feed(), td)
            snapshot = judge.build_market_monitor_snapshot_until_cutoff(
                {"analysis_cutoff_ts": "2026-09-14T02:12:00Z", "symbol": "BTCUSDC"},
                {
                    "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": td,
                    "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_STATE_PATH": str(Path(td) / "state.json"),
                },
            )
            self.assertEqual(snapshot["schema_version"], "market_monitor_snapshot_v39a")
            self.assertEqual(snapshot["windows"]["1440"]["rows_used"], 1440)
            self.assertEqual(snapshot["market_state"]["source"], "base_monitor_v1_continuous_1440m")
            self.assertEqual(snapshot["market_structure_state"]["source"], "base_monitor_v1_continuous_1440m")
            self.assertEqual(snapshot["market_structure_state"]["value"]["classification_scope"],
                             "continuous_1440_closed_minutes_with_snapshot_zones")
            from executor_mod.entry_snapshot import validate_canonical_monitor_snapshot
            validate_canonical_monitor_snapshot(snapshot)

    def test_missing_previous_day_prevents_real_model_call_and_alerts(self):
        with tempfile.TemporaryDirectory() as td:
            day_only = _feed()
            day_only = day_only[day_only["Timestamp"] >= pd.Timestamp("2026-09-14T00:00:00Z")]
            _write_days(day_only, td)
            journal = str(Path(td) / "verdicts.jsonl")
            calls, events, alerts = [], [], []
            judge.configure({
                "SYMBOL": "BTCUSDC",
                "LLM_TRADE_JUDGE_ENABLED": True,
                "LLM_TRADE_JUDGE_MODE": "openai",
                "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": td,
                "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": False,
                "LLM_TRADE_JUDGE_MARKET_MONITOR_V39A_ENABLED": False,
                "LLM_TRADE_JUDGE_CONTEXT_ENABLED": False,
                "LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": True,
            }, openai_client_fn=lambda **kwargs: calls.append(kwargs),
                log_event_fn=lambda *args, **kwargs: events.append((args, kwargs)),
                send_webhook_fn=lambda payload: alerts.append(payload))
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(calls, [])
            record = json.loads(Path(journal).read_text().splitlines()[0])
            self.assertEqual(record["error_type"], "monitor_input_error")
            self.assertEqual(record["llm_call_status"], "error")
            window = record["evidence_pack"]["market_monitor_snapshot"]["window_diagnostics"]["240"]
            self.assertEqual(window["rows_used"], 133)
            self.assertFalse(window["complete"])
            self.assertTrue(any(args[0] == "LLM_TRADE_JUDGE_ERROR" for args, _ in events))
            self.assertEqual(len(alerts), 1)

    def test_noncanonical_entry_snapshot_rejected_when_judge_enabled(self):
        with self.assertRaisesRegex(EntrySnapshotError, "canonical_market_monitor_snapshot_required"):
            build_entry_snapshot({
                "analysis_cutoff_ts": "2026-09-14T02:12:00Z",
                "market_monitor_snapshot": {"schema_version": "market_monitor_snapshot_v1"},
            }, env={"LLM_TRADE_JUDGE_ENABLED": True})


if __name__ == "__main__":
    unittest.main()
