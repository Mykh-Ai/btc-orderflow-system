import json
import os
import tempfile
import unittest

import pandas as pd

from executor_mod import llm_trade_judge as judge
from market_monitor import snapshot_builder


def _pos(**overrides):
    pos = {
        "status": "OPEN",
        "mode": "live",
        "side": "LONG",
        "qty": 0.12,
        "entry": 95000.0,
        "entry_actual": 95001.5,
        "opened_at": "2026-01-01T00:00:05Z",
        "filled_at": "2026-01-01T00:00:10Z",
        "order_id": 111,
        "client_id": "EX_EN_1",
        "trade_key": "EX_EN_1",
        "entry_mode": "LIMIT_THEN_MARKET",
        "executedQty": "0.12",
        "cummulativeQuoteQty": "11400",
        "k_entry": 1.0001,
        "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
        "orders": {"sl": 201, "tp1": 202, "tp2": 203, "qty1": 0.04, "qty2": 0.04, "qty3": 0.04},
        "src_evt": {
            "ts": "2026-01-01T00:00:00Z",
            "kind": "long",
            "price_usdt": 94990.0,
        },
    }
    pos.update(overrides)
    return pos


class TestCutoffAndEvidence(unittest.TestCase):
    def setUp(self):
        judge.configure({
            "SYMBOL": "BTCUSDC",
            "LLM_TRADE_JUDGE_ENABLED": False,
            "LLM_TRADE_JUDGE_CONTEXT_ENABLED": False,
            "LLM_TRADE_JUDGE_FEED_TIMEZONE": "Europe/Bratislava",
        })

    def test_parse_dt_safe_aware_iso_and_z(self):
        self.assertEqual(judge.isoformat_z(judge.parse_dt_safe("2026-05-15T02:52:00+00:00")), "2026-05-15T02:52:00Z")
        self.assertEqual(judge.isoformat_z(judge.parse_dt_safe("2026-05-15T02:52:00Z")), "2026-05-15T02:52:00Z")

    def test_parse_dt_safe_naive_with_feed_timezone(self):
        dt = judge.parse_dt_safe("2026-05-15 04:52:00", naive_tz="Europe/Bratislava")
        self.assertEqual(judge.isoformat_z(dt), "2026-05-15T02:52:00Z")

    def test_choose_analysis_cutoff_uses_src_evt_ts(self):
        cutoff = judge.choose_analysis_cutoff(_pos())
        self.assertEqual(cutoff["peak_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(cutoff["cutoff_source"], "position.src_evt.ts")
        self.assertEqual(cutoff["timestamp_contract"], "utc_iso8601")

    def test_choose_analysis_cutoff_normalizes_legacy_feed_local_ts(self):
        cutoff = judge.choose_analysis_cutoff(_pos(src_evt={"ts": "2026-05-15 04:52:00", "kind": "long"}))
        self.assertEqual(cutoff["peak_ts"], "2026-05-15T02:52:00Z")
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-05-15T02:52:00Z")
        self.assertEqual(cutoff["peak_ts_raw"], "2026-05-15 04:52:00")
        self.assertEqual(cutoff["ts_source_timezone"], "Europe/Bratislava")
        self.assertTrue(cutoff["ts_normalized"])
        self.assertEqual(cutoff["timestamp_contract"], "legacy_feed_local_naive")

    def test_missing_src_evt_falls_back_to_filled_at(self):
        pos = _pos(src_evt={})
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertIsNone(cutoff["peak_ts"])
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:10Z")
        self.assertEqual(cutoff["cutoff_source"], "entry_ts_fallback")
        self.assertEqual(cutoff["timestamp_contract"], "utc_iso8601")

    def test_missing_src_evt_falls_back_to_opened_at(self):
        pos = _pos(src_evt={}, filled_at=None)
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertEqual(cutoff["analysis_cutoff_ts"], "2026-01-01T00:00:05Z")
        self.assertEqual(cutoff["cutoff_source"], "entry_ts_fallback")

    def test_missing_all_timestamps_marks_gap(self):
        pos = _pos(src_evt={}, filled_at=None, opened_at=None)
        cutoff = judge.choose_analysis_cutoff(pos)
        self.assertIsNone(cutoff["analysis_cutoff_ts"])
        self.assertEqual(cutoff["cutoff_source"], "missing")
        self.assertIn("missing_analysis_cutoff_ts", cutoff["data_gaps"])

    def test_build_pretrade_evidence_pack_fields(self):
        st = {"baseline": {"active": {"trade_key": "EX_EN_1", "balances": {"quote_free": 100.0}}}}
        pack = judge.build_pretrade_evidence_pack(_pos(), st, "EXITS_PLACED_V15")
        self.assertEqual(pack["schema_version"], "llm_trade_judge_open_v1")
        self.assertEqual(pack["trade_key"], "EX_EN_1")
        self.assertEqual(pack["symbol"], "BTCUSDC")
        self.assertEqual(pack["direction"], "long")
        self.assertEqual(pack["prices"]["sl"], 94000.0)
        self.assertEqual(pack["orders"]["tp1"], 202)
        self.assertEqual(pack["src_evt"]["ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["peak_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["cutoff_source"], "position.src_evt.ts")
        self.assertEqual(pack["peak_ts_raw"], "2026-01-01T00:00:00Z")
        self.assertEqual(pack["timestamp_contract"], "utc_iso8601")
        self.assertIn("ts_normalized", pack)
        self.assertIn("baseline", pack)
        self.assertEqual(pack["market_context"]["enabled"], False)
        self.assertIn("context_disabled", pack["market_context"]["data_gaps"])
        self.assertNotIn("market_monitor_snapshot", pack)

    def test_build_pretrade_evidence_pack_can_attach_market_monitor_snapshot_gap(self):
        judge.configure({
            "SYMBOL": "BTCUSDC",
            "LLM_TRADE_JUDGE_CONTEXT_ENABLED": False,
            "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": True,
            "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": "missing-market-monitor-feed.csv",
        })
        pack = judge.build_pretrade_evidence_pack(_pos(), {}, "EXITS_PLACED_V15")
        snapshot = pack["market_monitor_snapshot"]
        self.assertTrue(snapshot["enabled"])
        self.assertEqual(snapshot["schema_version"], "market_monitor_snapshot_error_v1")
        self.assertIn("market_monitor_snapshot_current_feed_not_found", snapshot["data_gaps"])
        self.assertIn("market_monitor_snapshot_current_feed_not_found", pack["data_gaps"])

    def test_build_pretrade_evidence_pack_preserves_raw_peak_fields(self):
        src_evt = {
            "ts": "2026-01-01T00:00:00Z",
            "kind": "short",
            "source": "deltascout",
            "action": "PEAK",
            "delta": -420.5,
            "vol": 88.1,
            "imb": -0.63,
            "price": 95010.0,
            "vwap": 94980.0,
            "poc": 94950.0,
            "price_usdt": 95010.0,
        }
        pack = judge.build_pretrade_evidence_pack(_pos(src_evt=src_evt, side="SHORT"), {}, "EXITS_PLACED_V15")
        for key in ("source", "action", "delta", "vol", "imb", "price", "vwap", "poc"):
            self.assertEqual(pack["src_evt"][key], src_evt[key])


class TestMarketContextUntilCutoff(unittest.TestCase):
    def _write_deltascout_log(self, path):
        lines = [
            json.dumps({"ts": "2025-12-30T23:00:00Z", "action": "PEAK", "kind": "long", "delta": 5, "price": 94800}),
            "not-json",
            json.dumps({"ts": "2025-12-31T23:15:00Z", "action": "INFO", "kind": "long", "delta": 7, "price": 94850}),
            json.dumps({"ts": "2025-12-31T23:30:00Z", "action": "PEAK", "kind": "long", "delta": 10, "vol": 20, "imb": 0.2, "price": 94900, "vwap": 94880, "poc": 94860, "source": "ds"}),
            json.dumps({"ts": "2025-12-31T23:50:00Z", "action": "PEAK", "kind": "short", "delta": -30, "vol": 40, "imb": -0.4, "price": 95020, "vwap": 94990, "poc": 94970, "source": "ds"}),
            json.dumps({"ts": "2026-01-01T00:00:00Z", "action": "PEAK", "kind": "long", "delta": 50, "vol": 60, "imb": 0.6, "price": 95000, "vwap": 94970, "poc": 94940, "source": "ds"}),
            json.dumps({"ts": "2026-01-01T00:01:00Z", "action": "PEAK", "kind": "short", "delta": -99, "price": 95100}),
        ]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

    def _write_agg_csv(self, path):
        rows = [
            "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice",
            "2025-12-31T19:59:00Z,1,10,10,5,5,94000,94000,94010,93990",
            "2025-12-31T20:00:00Z,1,10,10,6,4,94100,94100,94110,94090",
            "2025-12-31T23:00:00Z,1,20,20,12,8,94800,94800,94850,94750",
            "2025-12-31T23:45:00Z,1,30,30,20,10,94900,94900,94950,94850",
            "2026-01-01T00:00:00Z,1,40,40,30,10,95000,95000,95050,94950",
            "2026-01-01T00:01:00Z,1,50,50,0,50,96000,96000,96050,95950",
        ]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")

    def test_read_deltascout_events_until_cutoff_filters_future_old_malformed_and_non_peak(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "deltascout.log")
            self._write_deltascout_log(path)
            result = judge.read_deltascout_events_until_cutoff(path, "2026-01-01T00:00:00Z", 24, 5000)
            self.assertEqual(result["events_total_read"], 7)
            self.assertEqual(result["events_used"], 3)
            self.assertIn("deltascout_malformed_json:1", result["data_gaps"])
            self.assertTrue(all(evt["action"] == "PEAK" for evt in result["events"]))
            self.assertTrue(all(evt["ts"] <= "2026-01-01T00:00:00Z" for evt in result["events"]))
            self.assertEqual(result["events"][-1]["delta"], 50)

    def test_read_deltascout_missing_file_no_crash(self):
        result = judge.read_deltascout_events_until_cutoff("missing.log", "2026-01-01T00:00:00Z", 24, 5000)
        self.assertEqual(result["events"], [])
        self.assertIn("deltascout_log_missing", result["data_gaps"])

    def test_read_deltascout_naive_feed_timezone_prevents_future_leak(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "deltascout.log")
            rows = [
                {"ts": "2026-05-15 04:51:00", "action": "PEAK", "kind": "long", "delta": 1, "price": 100},
                {"ts": "2026-05-15 04:52:00", "action": "PEAK", "kind": "long", "delta": 2, "price": 101},
                {"ts": "2026-05-15 04:53:00", "action": "PEAK", "kind": "short", "delta": -3, "price": 102},
            ]
            with open(path, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            result = judge.read_deltascout_events_until_cutoff(
                path,
                "2026-05-15T02:52:00Z",
                1,
                5000,
                "Europe/Bratislava",
            )
            self.assertEqual(result["events_used"], 2)
            self.assertEqual(result["events"][-1]["ts_raw"], "2026-05-15 04:52:00")
            self.assertEqual(result["events"][-1]["ts_utc"], "2026-05-15T02:52:00Z")
            self.assertEqual(result["events"][-1]["timestamp_contract"], "legacy_feed_local_naive")

    def test_build_peak_context_counts_price_location_and_recent_direction(self):
        events = [
            {"ts": "2025-12-31T23:20:00Z", "action": "PEAK", "kind": "long", "delta": 10, "price": 94900, "vwap": 94880, "poc": 94870},
            {"ts": "2025-12-31T23:40:00Z", "action": "PEAK", "kind": "short", "delta": -30, "price": 95020, "vwap": 94990, "poc": 94960},
            {"ts": "2026-01-01T00:00:00Z", "action": "PEAK", "kind": "long", "delta": 50, "price": 95000, "vwap": 94970, "poc": 94940},
        ]
        ctx = judge.build_peak_context_until_cutoff(events, "long", 95000, current_peak=events[-1])
        self.assertEqual(ctx["count_long"], 2)
        self.assertEqual(ctx["count_short"], 1)
        self.assertEqual(ctx["recent_same_direction_count_60m"], 2)
        self.assertEqual(ctx["recent_opposite_direction_count_60m"], 1)
        self.assertEqual(ctx["price_vs_vwap"], 30)
        self.assertEqual(ctx["price_vs_poc"], 60)
        self.assertEqual(ctx["current_peak_delta_percentile_24h"], 100.0)

    def test_build_peak_context_adds_gaps_when_vwap_or_poc_missing(self):
        ctx = judge.build_peak_context_until_cutoff(
            [{"ts": "2026-01-01T00:00:00Z", "action": "PEAK", "kind": "long", "delta": 1}],
            "long",
            95000,
            current_peak={"ts": "2026-01-01T00:00:00Z", "kind": "long", "delta": 1},
        )
        self.assertIn("missing_current_peak_vwap", ctx["data_gaps"])
        self.assertIn("missing_current_peak_poc", ctx["data_gaps"])

    def test_read_agg_rows_until_cutoff_ignores_future_and_parses_schema(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "aggregated.csv")
            self._write_agg_csv(path)
            result = judge.read_agg_rows_until_cutoff(path, "2026-01-01T00:00:00Z", 4)
            self.assertEqual(result["rows_used"], 4)
            self.assertEqual(result["rows"][-1]["Timestamp"], "2026-01-01T00:00:00Z")
            self.assertEqual(result["rows"][-1]["ClosePrice"], 95000.0)

    def test_read_agg_rows_naive_feed_timezone_prevents_future_leak(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "aggregated.csv")
            rows = [
                "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice",
                "2026-05-15 04:51:00,1,10,10,6,4,100,100,101,99",
                "2026-05-15 04:52:00,1,10,10,7,3,101,101,102,100",
                "2026-05-15 04:53:00,1,10,10,1,9,102,102,103,101",
            ]
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
            result = judge.read_agg_rows_until_cutoff(path, "2026-05-15T02:52:00Z", 1, "Europe/Bratislava")
            self.assertEqual(result["rows_used"], 2)
            self.assertEqual(result["rows"][-1]["Timestamp_raw"], "2026-05-15 04:52:00")
            self.assertEqual(result["rows"][-1]["Timestamp_utc"], "2026-05-15T02:52:00Z")
            self.assertEqual(result["rows"][-1]["timestamp_contract"], "legacy_feed_local_naive")

    def test_read_agg_missing_file_no_crash(self):
        result = judge.read_agg_rows_until_cutoff("missing.csv", "2026-01-01T00:00:00Z", 24)
        self.assertEqual(result["rows"], [])
        self.assertIn("agg_csv_missing", result["data_gaps"])

    def test_build_agg_context_computes_returns_orderflow_and_rolling_vwap_approx(self):
        rows = [
            {"Timestamp": "2025-12-31T20:00:00Z", "TotalQty": 10.0, "BuyQty": 6.0, "SellQty": 4.0, "AvgPrice": 94100.0, "ClosePrice": 94100.0, "HiPrice": 94110.0, "LowPrice": 94090.0},
            {"Timestamp": "2025-12-31T23:00:00Z", "TotalQty": 20.0, "BuyQty": 12.0, "SellQty": 8.0, "AvgPrice": 94800.0, "ClosePrice": 94800.0, "HiPrice": 94850.0, "LowPrice": 94750.0},
            {"Timestamp": "2025-12-31T23:45:00Z", "TotalQty": 30.0, "BuyQty": 20.0, "SellQty": 10.0, "AvgPrice": 94900.0, "ClosePrice": 94900.0, "HiPrice": 94950.0, "LowPrice": 94850.0},
            {"Timestamp": "2026-01-01T00:00:00Z", "TotalQty": 40.0, "BuyQty": 30.0, "SellQty": 10.0, "AvgPrice": 95000.0, "ClosePrice": 95000.0, "HiPrice": 95050.0, "LowPrice": 94950.0},
        ]
        ctx = judge.build_agg_context_until_cutoff(rows)
        self.assertEqual(ctx["rows_used"], 4)
        self.assertIsNotNone(ctx["return_15m_pct"])
        self.assertIsNotNone(ctx["return_60m_pct"])
        self.assertIsNotNone(ctx["return_240m_pct"])
        self.assertEqual(ctx["buy_sell_delta_60m"], 34.0)
        self.assertAlmostEqual(ctx["buy_sell_imbalance_60m"], 34.0 / 90.0)
        self.assertIn("rolling_vwap_approx", ctx)
        self.assertFalse(any("poc" in key.lower() for key in ctx.keys()))

    def test_build_market_context_uses_cutoff_and_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            delta_path = os.path.join(td, "deltascout.log")
            agg_path = os.path.join(td, "aggregated.csv")
            self._write_deltascout_log(delta_path)
            self._write_agg_csv(agg_path)
            pack = {
                "analysis_cutoff_ts": "2026-01-01T00:00:00Z",
                "direction": "long",
                "entry": 95000.0,
                "entry_actual": 95000.0,
                "src_evt": {"ts": "2026-01-01T00:00:00Z", "kind": "long", "delta": 50, "price": 95000, "vwap": 94970, "poc": 94940},
            }
            ctx = judge.build_market_context_until_cutoff(
                pack,
                {
                    "LLM_TRADE_JUDGE_CONTEXT_ENABLED": True,
                    "LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS": 24,
                    "LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS": 5000,
                    "LLM_TRADE_JUDGE_DELTASCOUT_LOG": delta_path,
                    "LLM_TRADE_JUDGE_AGG_CSV": agg_path,
                },
            )
            self.assertTrue(ctx["enabled"])
            self.assertEqual(ctx["cutoff_ts"], "2026-01-01T00:00:00Z")
            self.assertEqual(ctx["deltascout"]["events_used"], 3)
            self.assertEqual(ctx["aggregated"]["rows_used"], 5)
            disabled = judge.build_market_context_until_cutoff(pack, {"LLM_TRADE_JUDGE_CONTEXT_ENABLED": False})
            self.assertFalse(disabled["enabled"])
            self.assertIn("context_disabled", disabled["data_gaps"])

    def test_build_market_context_missing_files_adds_gaps(self):
        pack = {
            "analysis_cutoff_ts": "2026-01-01T00:00:00Z",
            "direction": "long",
            "entry": 95000.0,
            "src_evt": {"ts": "2026-01-01T00:00:00Z", "kind": "long", "delta": 1},
        }
        ctx = judge.build_market_context_until_cutoff(
            pack,
            {
                "LLM_TRADE_JUDGE_CONTEXT_ENABLED": True,
                "LLM_TRADE_JUDGE_DELTASCOUT_LOG": "missing.log",
                "LLM_TRADE_JUDGE_AGG_CSV": "missing.csv",
            },
        )
        self.assertIn("deltascout_log_missing", ctx["data_gaps"])
        self.assertIn("agg_csv_missing", ctx["data_gaps"])
        self.assertTrue(ctx["enabled"])

    def test_build_market_monitor_snapshot_disabled_and_missing_feed(self):
        disabled = judge.build_market_monitor_snapshot_until_cutoff(
            {"analysis_cutoff_ts": "2026-01-01T00:00:00Z"},
            {"LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": False},
        )
        self.assertFalse(disabled["enabled"])
        self.assertIn("market_monitor_snapshot_disabled", disabled["data_gaps"])

        missing = judge.build_market_monitor_snapshot_until_cutoff(
            {"analysis_cutoff_ts": "2026-01-01T00:00:00Z", "symbol": "BTCUSDC"},
            {"LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": True},
        )
        self.assertTrue(missing["enabled"])
        self.assertIn("market_monitor_snapshot_current_feed_missing", missing["data_gaps"])

    def test_build_market_monitor_snapshot_resolves_current_feed_dir_from_cutoff(self):
        with tempfile.TemporaryDirectory() as td:
            missing = judge.build_market_monitor_snapshot_until_cutoff(
                {"analysis_cutoff_ts": "2026-06-07T19:17:00Z", "symbol": "BTCUSDC"},
                {
                    "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": True,
                    "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": td,
                },
            )
            self.assertTrue(missing["enabled"])
            self.assertIn("market_monitor_snapshot_current_feed_not_found", missing["data_gaps"])
            self.assertEqual(
                missing["source_paths"]["resolved_current_feed"],
                os.path.join(td, "2026-06-07.csv"),
            )

    def test_market_structure_state_marks_seller_dominance_above_support_not_range(self):
        feed = pd.DataFrame(
            [
                {
                    "Timestamp": pd.Timestamp("2026-06-01T00:00:00Z"),
                    "OpenPrice": 81000.0,
                    "HiPrice": 81200.0,
                    "LowPrice": 80600.0,
                    "ClosePrice": 80950.0,
                    "TotalQty": 1000.0,
                    "BuyQty": 420.0,
                    "SellQty": 580.0,
                    "OpenInterest": 100000.0,
                },
                {
                    "Timestamp": pd.Timestamp("2026-06-01T23:59:00Z"),
                    "OpenPrice": 80950.0,
                    "HiPrice": 81150.0,
                    "LowPrice": 78500.0,
                    "ClosePrice": 78800.0,
                    "TotalQty": 3000.0,
                    "BuyQty": 900.0,
                    "SellQty": 2100.0,
                    "OpenInterest": 101500.0,
                },
            ]
        )
        zones = pd.DataFrame(
            [
                {
                    "zone_id": "support_1",
                    "price_lower": 77000.0,
                    "price_upper": 78000.0,
                    "significance_score": 92.0,
                    "confidence_tier": "HIGH",
                    "status": "ACTIVE",
                },
                {
                    "zone_id": "resistance_1",
                    "price_lower": 82000.0,
                    "price_upper": 83000.0,
                    "significance_score": 75.0,
                    "confidence_tier": "HIGH",
                    "status": "ACTIVE",
                },
            ]
        )

        state = snapshot_builder._market_structure_state(
            current=feed,
            significant_market_zones=zones,
        )

        self.assertIn(state["market_state"], {"MARKDOWN_ABOVE_SUPPORT", "EXPANSION_DOWN"})
        self.assertNotIn("RANGE", state["market_state"])
        self.assertEqual(state["candidate_bias"], "DOWN")
        self.assertIn("dominant_side=SELLER", state["evidence_summary"])
        self.assertIn("range_quality=BIASED", state["evidence_summary"])
        self.assertLessEqual(state["metrics"]["close_position"], 0.35)

    def test_prompt_mentions_market_context_and_no_hindsight(self):
        prompt = judge.build_llm_trade_judge_prompt({"analysis_cutoff_ts": "2026-01-01T00:00:00Z", "market_context": {"enabled": True}})
        self.assertIn("market_context.deltascout", prompt)
        self.assertIn("market_monitor_snapshot", prompt)
        self.assertIn("descriptive pre-cutoff Market Monitor snapshot", prompt)
        self.assertIn("market_structure_state", prompt)
        self.assertIn("avoid misreading bearish expansion as range/support", prompt)
        self.assertIn("Do not infer future outcome", prompt)
        self.assertIn("normalized UTC", prompt)
        self.assertIn("Do not use raw timestamps for filtering", prompt)
        self.assertIn("use REJECT", prompt)
        self.assertIn("Calibrate verdict strictly", prompt)
        self.assertIn("late chase", prompt)
        self.assertIn("local 60m/240m extreme", prompt)
        self.assertIn("Prefer UNCLEAR when broad 1d/3d/7d context", prompt)


class TestVerdictJournal(unittest.TestCase):
    def test_duplicate_trade_key_does_not_append_second_primary_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "state", "llm_trade_verdicts.jsonl")
            saved = []
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                },
                save_state_fn=lambda st: saved.append(dict(st)),
            )
            st = {"baseline": {"active": {"trade_key": "EX_EN_1"}}}
            first = judge.maybe_record_llm_pretrade_stub(st, _pos())
            second = judge.maybe_record_llm_pretrade_stub(st, _pos())

            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "noop")
            self.assertEqual(second["reason"], "duplicate_primary")
            with open(journal, "r", encoding="utf-8") as fh:
                records = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["is_primary"])
            self.assertEqual(st["llm"]["pretrade_done"]["EX_EN_1"], records[0]["verdict_id"])
            self.assertTrue(saved)

    def test_noop_if_position_not_open(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                }
            )
            result = judge.maybe_record_llm_pretrade_stub({}, _pos(status="OPEN_FILLED"))
            self.assertEqual(result["status"], "noop")
            self.assertEqual(result["reason"], "position_not_open")
            self.assertFalse(os.path.exists(journal))

    def test_noop_if_orders_missing(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                }
            )
            result = judge.maybe_record_llm_pretrade_stub({}, _pos(orders={}))
            self.assertEqual(result["status"], "noop")
            self.assertEqual(result["reason"], "missing_orders")
            self.assertFalse(os.path.exists(journal))


class TestRealOpenAIMode(unittest.TestCase):
    def _configure(self, journal, *, client=None, webhook=None, notify=True, saved=None):
        judge.configure(
            {
                "SYMBOL": "BTCUSDC",
                "LLM_TRADE_JUDGE_ENABLED": True,
                "LLM_TRADE_JUDGE_MODE": "openai",
                "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                "LLM_TRADE_JUDGE_MODEL": "gpt-5.5",
                "LLM_TRADE_JUDGE_TIMEOUT_SEC": 20,
                "LLM_TRADE_JUDGE_MAX_RETRIES": 1,
                "LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": notify,
                "LLM_TRADE_JUDGE_CONTEXT_ENABLED": False,
            },
            save_state_fn=(lambda st: saved.append(dict(st))) if saved is not None else None,
            send_webhook_fn=webhook,
            openai_client_fn=client,
        )

    def _records(self, journal):
        with open(journal, "r", encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_disabled_mode_does_not_call_client_or_append(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": False,
                    "LLM_TRADE_JUDGE_MODE": "openai",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                },
                openai_client_fn=lambda **kw: calls.append(kw),
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "noop")
            self.assertEqual(calls, [])
            self.assertFalse(os.path.exists(journal))

    def test_stub_mode_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            judge.configure(
                {
                    "SYMBOL": "BTCUSDC",
                    "LLM_TRADE_JUDGE_ENABLED": True,
                    "LLM_TRADE_JUDGE_MODE": "stub",
                    "LLM_TRADE_JUDGE_VERDICTS_FN": journal,
                }
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["verdict"], "STUB_NOT_CALLED")

    def test_openai_mode_calls_fake_client_once_and_appends_real_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []

            def fake_client(**kwargs):
                calls.append(kwargs)
                return json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "WRONG",
                    "confidence": 0.72,
                    "setup_class": "continuation_pressure",
                    "reason_codes": ["price_confirms_direction"],
                    "risk_flags": ["late_after_impulse"],
                    "summary_ua": "Погоджуюсь з ботом.",
                })

            self._configure(journal, client=fake_client, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(calls), 1)
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "success")
            self.assertEqual(record["model"], "gpt-5.5")
            self.assertEqual(record["verdict"], "SUPPORT")
            self.assertEqual(record["competitive_side"], "BOT")
            self.assertEqual(record["evidence_pack"]["analysis_cutoff_ts"], "2026-01-01T00:00:00Z")

    def test_duplicate_trade_key_does_not_call_fake_client(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            calls = []

            def fake_client(**_kwargs):
                calls.append(1)
                return json.dumps({
                    "verdict": "REJECT",
                    "competitive_side": "BOT",
                    "confidence": 0.74,
                    "setup_class": "exhaustion",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                })

            self._configure(journal, client=fake_client, notify=False)
            first = judge.maybe_record_llm_pretrade_judge({}, _pos())
            second = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["reason"], "duplicate_primary")
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(self._records(journal)), 1)

    def test_reject_and_unclear_normalize_to_llm_reject(self):
        for verdict in ("REJECT", "UNCLEAR"):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as td:
                journal = os.path.join(td, "v.jsonl")
                self._configure(
                    journal,
                    client=lambda **_kw: json.dumps({
                        "verdict": verdict,
                        "competitive_side": "BOT",
                        "confidence": 0.5,
                        "setup_class": "noisy_peak",
                        "reason_codes": [],
                        "risk_flags": [],
                        "summary_ua": None,
                    }),
                    notify=False,
                )
                judge.maybe_record_llm_pretrade_judge({}, _pos(trade_key=f"TK_{verdict}", client_id=f"TK_{verdict}"))
                record = self._records(journal)[0]
                self.assertEqual(record["competitive_side"], "LLM_REJECT")

    def test_invalid_json_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(journal, client=lambda **_kw: "not-json", notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "json_validation_error")
            self.assertEqual(record["verdict"], "ERROR_NOT_SCORED")

    def test_api_exception_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")

            def boom(**_kwargs):
                raise RuntimeError("api down")

            self._configure(journal, client=boom, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "api_error")

    def test_timeout_appends_error_record_no_raise(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")

            def timeout(**_kwargs):
                raise judge.requests.exceptions.Timeout("slow")

            self._configure(journal, client=timeout, notify=False)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["llm_call_status"], "error")
            self.assertEqual(record["error_type"], "timeout")

    def test_telegram_notification_sent_only_after_successful_append(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "UNCLEAR",
                    "competitive_side": "BOT",
                    "confidence": 0.51,
                    "setup_class": "unknown",
                    "reason_codes": [],
                    "risk_flags": ["late_entry"],
                    "summary_ua": "Перевага неясна.",
                }),
                webhook=lambda payload: sent.append(payload),
                notify=True,
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(sent), 1)
            payload = sent[0]
            self.assertEqual(payload["event"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["type"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["symbol"], "BTCUSDC")
            self.assertEqual(payload["mode"], "live")
            self.assertEqual(payload["verdict"], "UNCLEAR")
            self.assertEqual(payload["competitive_side"], "LLM_REJECT")
            self.assertEqual(payload["confidence"], 0.51)
            self.assertEqual(payload["setup_class"], "unknown")
            self.assertEqual(payload["cutoff"], "2026-01-01T00:00:00Z")
            self.assertEqual(payload["cutoff_source"], "position.src_evt.ts")
            self.assertIn("message", payload)
            self.assertIn("telegram_text", payload)
            self.assertEqual(payload["message"], payload["text"])
            self.assertEqual(payload["telegram_text"], payload["text"])
            self.assertIn("LLM Trade Judge", payload["text"])
            self.assertIn("Game rule: UNCLEAR counts as reject-side.", payload["text"])

    def test_error_notification_payload_contains_execution_not_affected(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []

            def boom(**_kwargs):
                raise RuntimeError("api down")

            self._configure(journal, client=boom, webhook=lambda payload: sent.append(payload), notify=True)
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(sent), 1)
            payload = sent[0]
            self.assertEqual(payload["event"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["type"], "LLM_TRADE_JUDGE_VERDICT")
            self.assertEqual(payload["symbol"], "BTCUSDC")
            self.assertEqual(payload["llm_call_status"], "error")
            self.assertEqual(payload["verdict"], "ERROR_NOT_SCORED")
            self.assertIn("Execution was not affected.", payload["text"])
            self.assertEqual(payload["message"], payload["text"])
            self.assertEqual(payload["telegram_text"], payload["text"])

    def test_telegram_disabled_does_not_send(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "honest_directional_flow",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                webhook=lambda payload: sent.append(payload),
                notify=False,
            )
            judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(sent, [])

    def test_append_failure_prevents_telegram_notification(self):
        with tempfile.TemporaryDirectory() as td:
            journal_dir = os.path.join(td, "as_file")
            with open(journal_dir, "w", encoding="utf-8") as fh:
                fh.write("not a dir")
            journal = os.path.join(journal_dir, "v.jsonl")
            sent = []
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "honest_directional_flow",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                webhook=lambda payload: sent.append(payload),
                notify=True,
            )
            result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            self.assertEqual(result["status"], "error")
            self.assertEqual(sent, [])

    def test_unknown_setup_class_becomes_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(
                journal,
                client=lambda **_kw: json.dumps({
                    "verdict": "SUPPORT",
                    "competitive_side": "BOT",
                    "confidence": 0.7,
                    "setup_class": "custom_new_class",
                    "reason_codes": [],
                    "risk_flags": [],
                    "summary_ua": None,
                }),
                notify=False,
            )
            judge.maybe_record_llm_pretrade_judge({}, _pos())
            record = self._records(journal)[0]
            self.assertEqual(record["setup_class"], "unknown")
            self.assertIn("unknown_setup_class:custom_new_class", record["validation_errors"])

    def test_missing_api_key_records_error_without_crash(self):
        with tempfile.TemporaryDirectory() as td:
            journal = os.path.join(td, "v.jsonl")
            self._configure(journal, client=None, notify=False)
            old_key = os.environ.pop("OPENAI_API_KEY", None)
            try:
                result = judge.maybe_record_llm_pretrade_judge({}, _pos())
            finally:
                if old_key is not None:
                    os.environ["OPENAI_API_KEY"] = old_key
            self.assertEqual(result["status"], "ok")
            record = self._records(journal)[0]
            self.assertEqual(record["error_type"], "missing_api_key")


class TestLifecycleAndScoring(unittest.TestCase):
    def test_lifecycle_classes(self):
        self.assertEqual(judge.classify_lifecycle(False, False, True, False, "SL"), "plain_sl")
        self.assertEqual(judge.classify_lifecycle(True, False, True, False, "SL"), "tp1_sl")
        self.assertEqual(judge.classify_lifecycle(True, True, True, True, "SL"), "tp1_tp2_trailing_stop")
        self.assertEqual(judge.classify_lifecycle(False, True, False, False, "TP2"), "manual_or_unknown")

    def test_scoring_matrix_reject(self):
        self.assertEqual(judge.score_llm_vs_bot("REJECT", "plain_sl")["llm_points"], 2)
        self.assertEqual(judge.score_llm_vs_bot("REJECT", "tp1_sl")["llm_points"], 1)
        score = judge.score_llm_vs_bot("REJECT", "tp1_tp2_trailing_stop")
        self.assertEqual(score["llm_points"], 0)
        self.assertEqual(score["bot_points"], 2)

    def test_scoring_matrix_unclear(self):
        self.assertEqual(judge.score_llm_vs_bot("UNCLEAR", "plain_sl")["llm_points"], 1)
        score = judge.score_llm_vs_bot("UNCLEAR", "tp1_sl")
        self.assertEqual(score["llm_points"], 0)
        self.assertEqual(score["bot_points"], 1)
        score = judge.score_llm_vs_bot("UNCLEAR", "tp1_tp2_trailing_stop")
        self.assertEqual(score["bot_points"], 2)

    def test_scoring_matrix_support_alignment(self):
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "plain_sl")["alignment_score"], -2)
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "tp1_sl")["alignment_score"], 1)
        self.assertEqual(judge.score_llm_vs_bot("SUPPORT", "tp1_tp2_trailing_stop")["alignment_score"], 2)

    def test_stub_not_called_not_scored(self):
        score = judge.score_llm_vs_bot("STUB_NOT_CALLED", "plain_sl")
        self.assertFalse(score["applies"])
