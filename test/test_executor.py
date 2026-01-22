import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pandas as pd
import executor
from executor_mod import notifications
from executor_mod import exit_safety
from executor_mod.exchange_snapshot import reset_snapshot_for_tests
from copy import deepcopy


def _stop_after_n_sleeps(n: int):
    calls = {"n": 0}
    def _sleep(_sec):
        calls["n"] += 1
        if calls["n"] > n:
            raise StopIteration
    return _sleep


class TestExecutorV15(unittest.TestCase):
    def setUp(self):
        super().setUp()
        reset_snapshot_for_tests()

    def test_swing_stop_far_uses_agg_high_low(self):
        df = pd.DataFrame({
            "Timestamp": [1, 2, 3, 4, 5],
            "price": [100.0, 100.0, 100.0, 100.0, 100.0],
            "LowPrice": [90.0, 90.0, 90.0, 90.0, 90.0],
            "HiPrice": [110.0, 110.0, 110.0, 110.0, 110.0],
        })

        prev_sl_pct = executor.ENV["SL_PCT"]
        prev_swing = executor.ENV["SWING_MINS"]
        prev_tick = executor.ENV["TICK_SIZE"]
        try:
            executor.ENV["SL_PCT"] = 0.01
            executor.ENV["SWING_MINS"] = 50
            executor.ENV["TICK_SIZE"] = 0.1
            entry = 100.0
            sl_buy = executor.swing_stop_far(df, 4, "BUY", entry)
            sl_sell = executor.swing_stop_far(df, 4, "SELL", entry)
        finally:
            executor.ENV["SL_PCT"] = prev_sl_pct
            executor.ENV["SWING_MINS"] = prev_swing
            executor.ENV["TICK_SIZE"] = prev_tick

        self.assertEqual(sl_buy, 90.0)
        self.assertEqual(sl_sell, 110.0)

    def test_swing_stop_far_nan_fallbacks_to_price(self):
        df = pd.DataFrame({
            "Timestamp": [1, 2, 3, 4, 5],
            "price": [100.0, 100.0, 100.0, 100.0, 100.0],
            "LowPrice": [float("nan")] * 5,
            "HiPrice": [float("nan")] * 5,
        })

        prev_sl_pct = executor.ENV["SL_PCT"]
        prev_swing = executor.ENV["SWING_MINS"]
        prev_tick = executor.ENV["TICK_SIZE"]
        try:
            executor.ENV["SL_PCT"] = 0.01
            executor.ENV["SWING_MINS"] = 50
            executor.ENV["TICK_SIZE"] = 0.1
            entry = 100.0
            sl_buy = executor.swing_stop_far(df, 4, "BUY", entry)
            sl_sell = executor.swing_stop_far(df, 4, "SELL", entry)
        finally:
            executor.ENV["SL_PCT"] = prev_sl_pct
            executor.ENV["SWING_MINS"] = prev_swing
            executor.ENV["TICK_SIZE"] = prev_tick

        self.assertEqual(sl_buy, 99.0)
        self.assertEqual(sl_sell, 101.0)

    def test_sl_filled_cancels_tp1_tp2_even_if_openorders_fail(self):
        st = {"position": {"mode": "live", "status": "OPEN", "side": "LONG",
                           "qty": 0.1,
                           "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333}}}

        with patch.object(executor.binance_api, "open_orders", side_effect=Exception("boom")), \
             patch.object(executor.binance_api, "check_order_status", side_effect=lambda s, oid: {"status": "FILLED"} if int(oid)==333 else {"status": "NEW"}), \
             patch.object(executor.binance_api, "cancel_order", MagicMock(return_value={"status": "CANCELED"})) as m_cancel, \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda *_: None), \
             patch.object(executor, "log_event", lambda *_ , **__: None):

            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNone(st["position"])
        called = [c.args[1] for c in m_cancel.call_args_list]
        self.assertIn(111, called)
        self.assertIn(222, called)

    def test_tp2_filled_activates_trailing_and_cancels_sl_tp1_best_effort(self):
        # After TP2 FILLED we keep the remaining qty3 open and manage it via trailing SL.
        canceled = {"sl333": False}
        def fake_cancel(_sym, oid):
            if int(oid) == 333:
                canceled["sl333"] = True
            return {"status": "CANCELED"}

        def fake_status(symbol, oid):
            oid = int(oid)
            if oid == 222:
                return {"status": "FILLED"}
            if oid == 333 and canceled["sl333"]:
                return {"status": "CANCELED"}
            return {"status": "NEW"}
        st = {"position": {"mode": "live", "status": "OPEN", "side": "LONG",
                           "qty": 0.1,
                           "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333,
                                      "qty1": 0.03, "qty2": 0.03, "qty3": 0.04}}}

        executor.ENV["TRAIL_ACTIVATE_AFTER_TP2"] = True
        executor.ENV["TRAIL_OFFSET_USD"] = 10.0
        executor.ENV["TRAIL_STEP_USD"] = 1.0
        executor.ENV["TRAIL_UPDATE_EVERY_SEC"] = 20

        with patch.object(executor, "_now_s", return_value=1000.0), \
            patch.object(executor.binance_api, "open_orders", side_effect=Exception("boom")), \
            patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
            patch.object(executor.binance_api, "get_mid_price", return_value=200.0), \
            patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 444}) as m_place, \
            patch.object(executor.binance_api, "cancel_order", side_effect=fake_cancel) as m_cancel, \
            patch.object(executor, "save_state", lambda *_: None), \
            patch.object(executor, "send_webhook", lambda *_: None), \
            patch.object(executor, "log_event", lambda *_ , **__: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)


            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNotNone(st["position"])
        self.assertTrue(st["position"].get("tp2_done"))
        self.assertTrue(st["position"].get("trail_active"))
        self.assertEqual(int(st["position"]["orders"]["sl"]), 444)
        called = [c.args[1] for c in m_cancel.call_args_list]
        self.assertIn(333, called)
        self.assertIn(111, called)
        self.assertGreaterEqual(m_place.call_count, 1)

    def test_recon_preserves_exit_ids_open(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                "orders": {"tp1": 111, "tp2": 222, "sl": 333},
            }
        }

        snapshot = SimpleNamespace(
            ok=False,
            error="stale",
            is_fresh=lambda *_: False,
            get_orders=lambda: [],
            freshness_sec=lambda: 999.0,
        )

        def fake_get_order(_symbol, _oid):
            raise Exception('{"code":-2013, "msg":"Order does not exist."}')

        prev_mode = executor.ENV["TRADE_MODE"]
        executor.ENV["TRADE_MODE"] = "margin"
        try:
            with patch.object(executor, "get_snapshot", return_value=snapshot), \
                patch.object(executor.binance_api, "open_orders", return_value=[{"orderId": 999, "clientOrderId": "EX_EN_1"}]), \
                patch.object(executor.binance_api, "get_order", side_effect=fake_get_order), \
                patch.object(executor, "save_state", lambda *_: None), \
                patch.object(executor, "send_webhook", lambda *_: None), \
                patch.object(executor, "log_event", lambda *_ , **__: None):
                executor.sync_from_binance(st, reason="MANUAL")
        finally:
            executor.ENV["TRADE_MODE"] = prev_mode

        orders = st["position"]["orders"]
        recon = st["position"]["recon"]
        self.assertEqual(orders["tp1"], 111)
        self.assertEqual(orders["tp2"], 222)
        self.assertEqual(orders["sl"], 333)
        self.assertEqual(recon["sl_status"], "NOT_FOUND")

    def test_sl_filled_missing_id_fallback_closes(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.1,
                "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                "orders": {"tp1": 111, "tp2": 222},
                "tp1_done": True,
                "tp2_done": True,
                "recon": {"sl_status": "FILLED"},
            }
        }

        with patch.object(executor.binance_api, "open_orders", return_value=[]), \
            patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}), \
            patch.object(executor.binance_api, "cancel_order", MagicMock(return_value={"status": "CANCELED"})) as m_cancel, \
            patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
            patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None), \
            patch.object(executor.price_snapshot, "refresh_price_snapshot", lambda *_a, **_k: None), \
            patch.object(executor.price_snapshot, "get_price_snapshot", return_value=SimpleNamespace(ok=False, price_mid=0.0)), \
            patch.object(executor, "save_state", lambda *_: None), \
            patch.object(executor, "send_webhook", lambda *_: None), \
            patch.object(executor, "log_event", lambda *_ , **__: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNone(st["position"])
        called = [c.args[1] for c in m_cancel.call_args_list]
        self.assertIn(111, called)
        self.assertIn(222, called)

    def test_tp1_be_cancel_first_then_place(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.1,
                "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                "orders": {"tp1": 111, "tp2": 222, "sl": 333, "qty2": 0.05, "qty3": 0.05},
            }
        }

        sl_calls = {"n": 0}
        def fake_status(_symbol, oid):
            oid = int(oid)
            if oid == 111:
                return {"status": "FILLED"}
            if oid == 333:
                sl_calls["n"] += 1
                return {"status": "NEW"} if sl_calls["n"] <= 2 else {"status": "CANCELED"}
            return {"status": "NEW"}

        prev_retry = executor.ENV["SL_WATCHDOG_RETRY_SEC"]
        executor.ENV["SL_WATCHDOG_RETRY_SEC"] = 0
        try:
            now = {"t": 1000.0}
            with patch.object(executor, "_now_s", side_effect=lambda: now["t"]), \
                patch.object(executor.binance_api, "open_orders", return_value=[]), \
                patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
                patch.object(executor.binance_api, "cancel_order", MagicMock(return_value={"status": "CANCELED"})) as m_cancel, \
                patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 444}) as m_place, \
                patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
                patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None), \
                patch.object(executor.price_snapshot, "refresh_price_snapshot", lambda *_a, **_k: None), \
                patch.object(executor.price_snapshot, "get_price_snapshot", return_value=SimpleNamespace(ok=False, price_mid=0.0)), \
                patch.object(executor, "save_state", lambda *_: None), \
                patch.object(executor, "send_webhook", lambda *_: None), \
                patch.object(executor, "log_event", lambda *_ , **__: None):
                now["t"] = 1000.0
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
                self.assertEqual(m_place.call_count, 0)
                now["t"] = 1003.0
                executor.manage_v15_position(executor.ENV["SYMBOL"], st)
        finally:
            executor.ENV["SL_WATCHDOG_RETRY_SEC"] = prev_retry

        self.assertEqual(m_place.call_count, 1)
        called = [c.args[1] for c in m_cancel.call_args_list]
        self.assertIn(333, called)
        self.assertEqual(int(st["position"]["orders"]["sl"]), 444)

    def test_limit_timeout_market_fallback_updates_opened_s_opened_at(self):
        # run 1 iteration of main loop
        canceled = {"limit100": False}
        def fake_cancel(_sym, oid):
            if int(oid) == 100:
                canceled["limit100"] = True
            return None
        st = {"position": {"mode": "live", "status": "PENDING",
                           "opened_at": "2025-01-01T00:00:00Z",
                           "opened_s": 1.0,
                           "order_id": 100, "side": "LONG", "qty": 0.1,
                           "entry": 50000.0,
                           "prices": {"entry": 50000, "tp1": 51000, "tp2": 52000, "sl": 49000}},
              "last_poll_s": 0.0}

        now = {"t": 1000.0}
        def fake_now():
            return now["t"]

        # entry order stays unfilled; timeout triggers planB; market fills
        def fake_status(symbol, oid):
            oid = int(oid)
            if oid == 100:
                if canceled["limit100"]:
                    return {"status": "CANCELED", "executedQty": "0"}
                return {"status": "NEW", "executedQty": "0"}
            if oid == 200:
                return {"status": "FILLED", "executedQty": "0.1", "cummulativeQuoteQty": "5000"}
            return {"status": "NEW", "executedQty": "0"}

        with patch.object(executor, "load_state", return_value=st), \
             patch.object(executor, "read_tail_lines", return_value=[]), \
             patch.object(executor, "bootstrap_seen_keys_from_tail", lambda *_: None), \
             patch.object(executor.binance_api, "_planb_exec_price", return_value=50000.0), \
             patch.object(executor, "_planb_market_allowed", return_value=(True, "OK", {})), \
             patch.object(executor, "_now_s", side_effect=fake_now), \
             patch.object(executor.binance_api, "check_order_status", side_effect=fake_status), \
             patch.object(executor.binance_api, "cancel_order", side_effect=fake_cancel), \
             patch.object(executor.binance_api, "place_spot_market", return_value={"orderId": 200}), \
             patch.object(executor, "place_exits_v15", return_value={"tp1": 101, "tp2": 102, "sl": 103, "qty2": 0.05}), \
             patch.object(executor, "validate_exit_plan", return_value={"qty_total_r": 0.1, "prices": st["position"]["prices"]}), \
             patch.object(executor, "manage_v15_position", lambda *_: None), \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda *_: None), \
             patch.object(executor, "log_event", lambda *_ , **__: None), \
             patch.object(executor.time, "sleep", _stop_after_n_sleeps(10)):

            executor.ENV["LIVE_ENTRY_TIMEOUT_SEC"] = 10
            executor.ENV["ENTRY_MODE"] = "LIMIT_THEN_MARKET"
            executor.ENV["LIVE_STATUS_POLL_EVERY"] = 2
            try:
                executor.main()
            except StopIteration:
                pass
        # IMPORTANT: this test is about Plan-B state update, so position must still exist
        self.assertIsNotNone(st["position"])
        self.assertEqual(st["position"]["order_id"], 200)
        self.assertGreater(st["position"]["opened_s"], 0.0)
        self.assertNotEqual(st["position"]["opened_at"], "2025-01-01T00:00:00Z")

    def test_sl_watchdog_market_close_emits_trade_closed_once(self):
        st = {
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.1,
                "trade_key": "TK-1",
                "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                "orders": {"tp1": 111, "tp2": 222, "sl": 333},
            }
        }

        snapshot = SimpleNamespace(
            ok=True,
            error=None,
            get_orders=lambda: [],
            freshness_sec=lambda: 0.0,
        )
        plan = {
            "action": "MARKET_FLATTEN",
            "qty": 0.1,
            "side": "SELL",
            "reason": "SL_WATCHDOG",
            "cancel_order_ids": [],
            "set_fired_on_success": True,
            "events": [],
        }

        with patch.object(executor, "_now_s", return_value=1000.0), \
            patch.object(executor, "refresh_snapshot", return_value=False), \
            patch.object(executor, "get_snapshot", return_value=snapshot), \
            patch.object(executor.price_snapshot, "refresh_price_snapshot", lambda *_a, **_k: None), \
            patch.object(executor.price_snapshot, "get_price_snapshot", return_value=SimpleNamespace(ok=True, price_mid=100.0)), \
            patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=plan), \
            patch.object(executor.binance_api, "flatten_market", return_value=None), \
            patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW", "executedQty": "0", "origQty": "0.1"}), \
            patch.object(executor.margin_guard, "on_after_position_closed", lambda *_a, **_k: None), \
            patch.object(executor.reporting, "report_trade_close", lambda *_a, **_k: None), \
            patch.object(executor, "save_state", lambda *_: None), \
            patch.object(executor, "log_event", lambda *_a, **_k: None), \
            patch.object(notifications, "send_webhook") as m_webhook, \
            patch.object(notifications, "log_event", lambda *_a, **_k: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNone(st["position"])
        self.assertEqual(m_webhook.call_count, 1)
        payload = m_webhook.call_args[0][0]
        self.assertEqual(payload.get("event"), "TRADE_CLOSED")

    def test_trade_closed_dedup_same_trade_key(self):
        def make_state():
            return {
                "position": {
                    "mode": "live",
                    "status": "OPEN",
                    "side": "LONG",
                    "qty": 0.1,
                    "trade_key": "TK-DEDUP",
                    "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                    "orders": {"tp1": 111, "tp2": 222, "sl": 333},
                }
            }

        st = make_state()
        snapshot = SimpleNamespace(
            ok=True,
            error=None,
            get_orders=lambda: [],
            freshness_sec=lambda: 0.0,
        )
        plan = {
            "action": "MARKET_FLATTEN",
            "qty": 0.1,
            "side": "SELL",
            "reason": "SL_WATCHDOG",
            "cancel_order_ids": [],
            "set_fired_on_success": True,
            "events": [],
        }

        with patch.object(executor, "_now_s", return_value=1000.0), \
            patch.object(executor, "refresh_snapshot", return_value=False), \
            patch.object(executor, "get_snapshot", return_value=snapshot), \
            patch.object(executor.price_snapshot, "refresh_price_snapshot", lambda *_a, **_k: None), \
            patch.object(executor.price_snapshot, "get_price_snapshot", return_value=SimpleNamespace(ok=True, price_mid=100.0)), \
            patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=plan), \
            patch.object(executor.binance_api, "flatten_market", return_value=None), \
            patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW", "executedQty": "0", "origQty": "0.1"}), \
            patch.object(executor.margin_guard, "on_after_position_closed", lambda *_a, **_k: None), \
            patch.object(executor.reporting, "report_trade_close", lambda *_a, **_k: None), \
            patch.object(executor, "save_state", lambda *_: None), \
            patch.object(executor, "log_event", lambda *_a, **_k: None), \
            patch.object(notifications, "send_webhook") as m_webhook, \
            patch.object(notifications, "log_event", lambda *_a, **_k: None):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)
            st["position"] = make_state()["position"]
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertIsNone(st["position"])
        self.assertEqual(m_webhook.call_count, 1)

    def test_place_exits_retry_after_single_failure(self):
        st = {"position": {"mode": "live", "status": "OPEN_FILLED",
                           "side": "LONG", "qty": 0.1,
                           "prices": {"entry": 100, "tp1": 101, "tp2": 102, "sl": 99},
                           "orders": {}},
              "last_poll_s": 0.0}

        now = {"t": 1000.0}
        def fake_now():
            now["t"] += 100.0
            return now["t"]

        calls = {"n": 0}
        def flaky_place(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("temporary")
            return {"tp1": 101, "tp2": 102, "sl": 103, "qty2": 0.05}

        with patch.object(executor, "load_state", return_value=st), \
             patch.object(executor, "read_tail_lines", return_value=[]), \
             patch.object(executor, "bootstrap_seen_keys_from_tail", lambda *_: None), \
             patch.object(executor, "_now_s", side_effect=fake_now), \
             patch.object(executor, "place_exits_v15", side_effect=flaky_place), \
             patch.object(executor, "validate_exit_plan", return_value={"qty_total_r": 0.1, "prices": st["position"]["prices"]}), \
             patch.object(executor, "manage_v15_position", lambda *_: None), \
             patch.object(executor, "save_state", lambda *_: None), \
             patch.object(executor, "send_webhook", lambda *_: None), \
             patch.object(executor, "log_event", lambda *_ , **__: None), \
             patch.object(executor.time, "sleep", _stop_after_n_sleeps(2)):
            executor.ENV["EXITS_RETRY_EVERY_SEC"] = 0
            try:
                executor.main()
            except StopIteration:
                pass

        self.assertGreaterEqual(calls["n"], 2)
        self.assertEqual(st["position"]["status"], "OPEN")
        self.assertTrue(st["position"]["orders"].get("sl"))

    def test_sync_preserves_tp1_before_done_and_watchdog_short(self):
        env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
        }
        st = {"position": {"mode": "live", "status": "OPEN", "side": "SHORT",
                           "qty": 0.3,
                           "prices": {"entry": 100.0, "tp1": 98.0, "tp2": 96.0, "sl": 102.0},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333, "qty1": 0.1, "qty2": 0.1, "qty3": 0.1}}}
        open_orders = [
            {"orderId": 222, "clientOrderId": "EX_TP2_1"},
            {"orderId": 333, "clientOrderId": "EX_SL_1"},
        ]
        prev_mode = executor.ENV.get("TRADE_MODE")
        prev_symbol = executor.ENV.get("SYMBOL")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["SYMBOL"] = "BTCUSDT"
            with patch.object(executor.binance_api, "open_orders", return_value=open_orders), \
                 patch.object(executor.binance_api, "get_order", return_value={"status": "CANCELED"}), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_ , **__: None):
                executor.sync_from_binance(st, reason="MANUAL")
        finally:
            executor.ENV["TRADE_MODE"] = prev_mode
            executor.ENV["SYMBOL"] = prev_symbol

        self.assertEqual(st["position"]["orders"]["tp1"], 111)
        self.assertEqual(st["position"]["recon"]["tp1_status"], "CANCELED")

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=st["position"],
            env=env,
            now_s=1000.0,
            price_now=97.0,
            tp1_status_payload={"status": "CANCELED"},
            tp2_status_payload=None,
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["side"], "BUY")
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

    def test_sync_preserves_tp1_before_done_and_watchdog_long(self):
        env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
        }
        st = {"position": {"mode": "live", "status": "OPEN", "side": "LONG",
                           "qty": 0.3,
                           "prices": {"entry": 100.0, "tp1": 102.0, "tp2": 104.0, "sl": 98.0},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333, "qty1": 0.1, "qty2": 0.1, "qty3": 0.1}}}
        open_orders = [
            {"orderId": 222, "clientOrderId": "EX_TP2_1"},
            {"orderId": 333, "clientOrderId": "EX_SL_1"},
        ]
        prev_mode = executor.ENV.get("TRADE_MODE")
        prev_symbol = executor.ENV.get("SYMBOL")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["SYMBOL"] = "BTCUSDT"
            with patch.object(executor.binance_api, "open_orders", return_value=open_orders), \
                 patch.object(executor.binance_api, "get_order", return_value={"status": "CANCELED"}), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_ , **__: None):
                executor.sync_from_binance(st, reason="MANUAL")
        finally:
            executor.ENV["TRADE_MODE"] = prev_mode
            executor.ENV["SYMBOL"] = prev_symbol

        self.assertEqual(st["position"]["orders"]["tp1"], 111)
        self.assertEqual(st["position"]["recon"]["tp1_status"], "CANCELED")

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=st["position"],
            env=env,
            now_s=1000.0,
            price_now=103.0,
            tp1_status_payload={"status": "CANCELED"},
            tp2_status_payload=None,
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["side"], "SELL")
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

    def test_sync_keeps_tp1_for_dust_and_watchdog_marks_done(self):
        env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
        }
        st = {"position": {"mode": "live", "status": "OPEN", "side": "LONG",
                           "qty": 0.3,
                           "prices": {"entry": 100.0, "tp1": 102.0, "tp2": 104.0, "sl": 98.0},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333, "qty1": 0.0001, "qty2": 0.1, "qty3": 0.1}}}
        open_orders = [
            {"orderId": 222, "clientOrderId": "EX_TP2_1"},
            {"orderId": 333, "clientOrderId": "EX_SL_1"},
        ]
        prev_mode = executor.ENV.get("TRADE_MODE")
        prev_symbol = executor.ENV.get("SYMBOL")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["SYMBOL"] = "BTCUSDT"
            with patch.object(executor.binance_api, "open_orders", return_value=open_orders), \
                 patch.object(executor.binance_api, "get_order", return_value={"status": "CANCELED"}), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_ , **__: None):
                executor.sync_from_binance(st, reason="MANUAL")
        finally:
            executor.ENV["TRADE_MODE"] = prev_mode
            executor.ENV["SYMBOL"] = prev_symbol

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=st["position"],
            env=env,
            now_s=1000.0,
            price_now=103.0,
            tp1_status_payload={"status": "CANCELED"},
            tp2_status_payload=None,
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "TP1_MISSING_DUST")
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))


    def test_sync_allows_tp1_pop_after_done(self):
        st = {"position": {"mode": "live", "status": "OPEN", "side": "LONG",
                           "qty": 0.3,
                           "tp1_done": True,
                           "prices": {"entry": 100.0, "tp1": 102.0, "tp2": 104.0, "sl": 98.0},
                           "orders": {"tp1": 111, "tp2": 222, "sl": 333, "qty1": 0.1, "qty2": 0.1, "qty3": 0.1}}}
        open_orders = [
            {"orderId": 222, "clientOrderId": "EX_TP2_1"},
            {"orderId": 333, "clientOrderId": "EX_SL_1"},
        ]
        prev_mode = executor.ENV.get("TRADE_MODE")
        prev_symbol = executor.ENV.get("SYMBOL")
        try:
            executor.ENV["TRADE_MODE"] = "margin"
            executor.ENV["SYMBOL"] = "BTCUSDT"
            with patch.object(executor.binance_api, "open_orders", return_value=open_orders), \
                 patch.object(executor.binance_api, "get_order", return_value={"status": "CANCELED"}), \
                 patch.object(executor, "save_state", lambda *_: None), \
                 patch.object(executor, "send_webhook", lambda *_: None), \
                 patch.object(executor, "log_event", lambda *_ , **__: None):
                executor.sync_from_binance(st, reason="MANUAL")
        finally:
            executor.ENV["TRADE_MODE"] = prev_mode
            executor.ENV["SYMBOL"] = prev_symbol

        self.assertNotIn("tp1", st["position"]["orders"])
