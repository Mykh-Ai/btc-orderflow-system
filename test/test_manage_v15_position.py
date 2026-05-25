import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import executor


def _position(**overrides):
    pos = {
        "mode": "live",
        "status": "OPEN",
        "side": "LONG",
        "qty": 0.12,
        "entry_actual": 100.0,
        "prices": {"entry": 100.0, "tp1": 101.0, "tp2": 102.0, "sl": 99.0},
        "orders": {
            "tp1": 111,
            "tp2": 222,
            "sl": 333,
            "qty1": 0.04,
            "qty2": 0.04,
            "qty3": 0.04,
        },
        "trade_key": "TK_CURRENT",
        "client_id": "TK_CURRENT",
        "order_id": 999,
    }
    pos.update(overrides)
    return pos


class TestManageV15Position(unittest.TestCase):
    def setUp(self):
        self.env_snapshot = deepcopy(executor.ENV)
        executor.ENV["SYMBOL"] = "BTCUSDC"
        executor.ENV["COOLDOWN_SEC"] = 180
        executor.ENV["LIVE_STATUS_POLL_EVERY"] = 10
        executor.ENV["ORPHAN_CANCEL_EVERY_SEC"] = 30
        executor.ENV["TICK_SIZE"] = 0.1
        executor.ENV["QTY_STEP"] = 0.001
        executor.ENV["SL_LIMIT_GAP_TICKS"] = 2
        executor.ENV["TRAIL_ACTIVATE_AFTER_TP2"] = True
        executor.ENV["TRAIL_STEP_USD"] = 1.0
        executor.ENV["TRAIL_UPDATE_EVERY_SEC"] = 20
        executor.ENV["TRAIL_SOURCE"] = "AGG"
        executor.ENV["TRAIL_SWING_BUFFER_USD"] = 15.0

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self.env_snapshot)

    def _patch_common(self, **overrides):
        patchers = {
            "open_orders": patch.object(executor.binance_api, "open_orders", return_value=[]),
            "check_order_status": patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
            "cancel_order": patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}),
            "place_order_raw": patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 444}),
            "get_mid_price": patch.object(executor.binance_api, "get_mid_price", return_value=120.0),
            "save_state": patch.object(executor, "save_state"),
            "log_event": patch.object(executor, "log_event"),
            "send_webhook": patch.object(executor, "send_webhook"),
            "record_snapshot": patch.object(executor, "_record_trade_execution_snapshot", return_value=None),
            "archive": patch.object(executor.trade_outcome_archive, "record_outcome"),
            "margin": patch.object(executor.margin_guard, "on_after_position_closed"),
            "summary": patch.object(executor, "_send_trade_closed_summary"),
            "now": patch.object(executor, "_now_s", return_value=1000.0),
            "clock": patch.object(executor.time, "time", return_value=1234.0),
            "trail_desired": patch.object(executor, "_trail_desired_stop_from_agg", return_value=95.0),
        }
        patchers.update(overrides)
        started = {}
        for name, patcher in patchers.items():
            started[name] = patcher.start()
            self.addCleanup(patcher.stop)
        return started

    def _event_names(self, log_event):
        return [call.args[0] for call in log_event.call_args_list if call.args]

    def test_guard_noop_cases_do_not_call_api_save_or_log(self):
        cases = [
            ("no position", {}),
            ("mode not live", {"position": _position(mode="paper")}),
            ("status not managed", {"position": _position(status="PENDING")}),
            ("missing orders", {"position": _position(orders={})}),
            ("missing prices", {"position": _position(prices=None)}),
        ]

        for name, st in cases:
            with self.subTest(name=name):
                mocks = self._patch_common()
                executor.manage_v15_position("BTCUSDC", st)

                mocks["open_orders"].assert_not_called()
                mocks["check_order_status"].assert_not_called()
                mocks["cancel_order"].assert_not_called()
                mocks["place_order_raw"].assert_not_called()
                mocks["get_mid_price"].assert_not_called()
                mocks["save_state"].assert_not_called()
                mocks["log_event"].assert_not_called()

    def test_open_orders_error_updates_throttle_and_logs(self):
        st = {"position": _position(orders={"marker": 1})}
        mocks = self._patch_common(
            open_orders=patch.object(executor.binance_api, "open_orders", side_effect=RuntimeError("boom")),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(st["position"]["open_orders_err_s"], 1000.0)
        mocks["save_state"].assert_called_once_with(st)
        mocks["log_event"].assert_called_once()
        self.assertEqual(mocks["log_event"].call_args.args[0], "LIVE_MANAGE_ERROR")
        self.assertTrue(mocks["log_event"].call_args.kwargs["error"].startswith("openOrders:"))

    def test_open_orders_error_throttle_suppresses_repeated_save_and_log(self):
        st = {"position": _position(orders={"marker": 1}, open_orders_err_s=990.0)}
        mocks = self._patch_common(
            open_orders=patch.object(executor.binance_api, "open_orders", side_effect=RuntimeError("boom")),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["save_state"].assert_not_called()
        mocks["log_event"].assert_not_called()

    def test_open_orders_error_still_allows_due_status_checks(self):
        st = {"position": _position(orders={"tp1": 111})}
        mocks = self._patch_common(
            open_orders=patch.object(executor.binance_api, "open_orders", side_effect=RuntimeError("boom")),
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["check_order_status"].assert_called_once_with("BTCUSDC", 111)
        self.assertIn("TP1_NOT_FILLED", self._event_names(mocks["log_event"]))

    def test_status_check_exception_is_treated_as_not_filled(self):
        st = {"position": _position(orders={"sl": 333})}
        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=RuntimeError("status down")),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNotNone(st["position"])
        self.assertNotIn("last_closed", st)
        mocks["record_snapshot"].assert_not_called()
        mocks["archive"].assert_not_called()
        mocks["margin"].assert_not_called()
        mocks["summary"].assert_not_called()
        self.assertIn("SL_NOT_FILLED", self._event_names(mocks["log_event"]))

    def test_close_slot_ordering_uses_current_position_and_runs_summary_last(self):
        pos = _position(orders={"sl": 333}, trade_key="TK_CURRENT", client_id="TK_CURRENT", sl_done=False)
        st = {
            "position": pos,
            "last_closed": {"trade_key": "TK_STALE"},
            "cooldown_until": 0.0,
            "lock_until": 123.0,
        }
        events = []

        def fake_status(_symbol, order_id):
            return {"status": "FILLED"} if int(order_id) == 333 else {"status": "NEW"}

        def fake_save(state):
            if state.get("position") is None:
                self.assertEqual(state["cooldown_until"], 1180.0)
                self.assertEqual(state["lock_until"], 0.0)
                events.append("save_closed")
            else:
                self.assertTrue(state["position"]["sl_done"])
                events.append("save_sl_done")

        def fake_snapshot(state, source, enrich_exchange=False):
            self.assertEqual(source, "_close_slot")
            self.assertTrue(enrich_exchange)
            self.assertEqual(state["last_closed"]["trade_key"], "TK_CURRENT")
            self.assertIs(state["position"], pos)
            events.append("snapshot")
            return {"snapshot": "ok"}

        def fake_archive(state, source, symbol):
            self.assertIsNone(state["position"])
            self.assertEqual(state["last_closed"]["trade_key"], "TK_CURRENT")
            self.assertEqual(source, "_close_slot")
            self.assertEqual(symbol, "BTCUSDC")
            events.append("archive")

        def fake_margin(state, *args, **kwargs):
            self.assertIsNone(state["position"])
            events.append("margin")

        def fake_summary(state, snapshot):
            self.assertIsNone(state["position"])
            self.assertEqual(snapshot, {"snapshot": "ok"})
            events.append("summary")

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            save_state=patch.object(executor, "save_state", side_effect=fake_save),
            record_snapshot=patch.object(executor, "_record_trade_execution_snapshot", side_effect=fake_snapshot),
            archive=patch.object(executor.trade_outcome_archive, "record_outcome", side_effect=fake_archive),
            margin=patch.object(executor.margin_guard, "on_after_position_closed", side_effect=fake_margin),
            summary=patch.object(executor, "_send_trade_closed_summary", side_effect=fake_summary),
            now=patch.object(executor, "_now_s", return_value=1000.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(events, ["save_sl_done", "snapshot", "save_closed", "archive", "margin", "summary"])
        self.assertIsNone(st["position"])
        self.assertEqual(st["last_closed"]["trade_key"], "TK_CURRENT")
        mocks["summary"].assert_called_once()

    def test_tp1_filled_moves_sl_to_be_with_expected_payload(self):
        pos = _position(orders={"tp1": 111, "sl": 333, "qty2": 0.04, "qty3": 0.03})
        st = {"position": pos}

        def fake_status(_symbol, order_id):
            oid = int(order_id)
            if oid == 111:
                return {"status": "FILLED"}
            if oid == 333:
                return {"status": "CANCELED"}
            return {"status": "NEW"}

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            place_order_raw=patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 444}),
            now=patch.object(executor, "_now_s", return_value=1000.0),
            clock=patch.object(executor.time, "time", return_value=1234.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_any_call("BTCUSDC", 333)
        payload = mocks["place_order_raw"].call_args.args[0]
        self.assertEqual(payload["symbol"], "BTCUSDC")
        self.assertEqual(payload["side"], "SELL")
        self.assertEqual(payload["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(payload["quantity"], executor.fmt_qty(0.07))
        self.assertEqual(payload["stopPrice"], executor.fmt_price(100.0))
        self.assertEqual(payload["price"], executor.fmt_price(99.8))
        self.assertEqual(payload["timeInForce"], "GTC")
        self.assertEqual(payload["newClientOrderId"], "EX_SL_BE_1234")
        self.assertTrue(pos["tp1_done"])
        self.assertEqual(pos["orders"]["sl_prev"], 333)
        self.assertEqual(pos["orders"]["sl"], 444)
        self.assertEqual(pos["sl_prev_next_cancel_s"], 1000.0)
        self.assertIn("TP1_DONE_SL_TO_BE", self._event_names(mocks["log_event"]))

    def test_tp1_waits_when_old_sl_cancel_is_not_confirmed(self):
        st = {"position": _position(orders={"tp1": 111, "sl": 333})}

        def fake_status(_symbol, order_id):
            return {"status": "FILLED"} if int(order_id) == 111 else {"status": "NEW"}

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_called_once_with("BTCUSDC", 333)
        mocks["place_order_raw"].assert_not_called()
        mocks["save_state"].assert_not_called()
        self.assertIn("TP1_SL_TO_BE_WAIT_CANCEL", self._event_names(mocks["log_event"]))
        self.assertFalse(st["position"].get("tp1_done"))

    def test_tp1_be_place_failure_does_not_mark_done(self):
        st = {"position": _position(orders={"tp1": 111, "sl": 333}, sl_done=True)}

        def fake_status(_symbol, order_id):
            return {"status": "FILLED"} if int(order_id) == 111 else {"status": "CANCELED"}

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            place_order_raw=patch.object(executor.binance_api, "place_order_raw", side_effect=RuntimeError("place failed")),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertFalse(st["position"].get("tp1_done"))
        self.assertIn("TP1_SL_TO_BE_ERROR", self._event_names(mocks["log_event"]))

    def test_tp1_not_filled_updates_poll_timestamp_and_logs_once(self):
        st = {"position": _position(orders={"tp1": 111})}
        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(st["position"]["tp1_status_next_s"], 1010.0)
        self.assertIn("TP1_NOT_FILLED", self._event_names(mocks["log_event"]))
        mocks["save_state"].assert_called_once_with(st)

    def test_orphan_sl_prev_cancel_retry_sets_next_timestamp_and_cancels(self):
        st = {"position": _position(orders={"sl_prev": 333}, tp1_done=True)}
        mocks = self._patch_common()

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(st["position"]["sl_prev_next_cancel_s"], 1030.0)
        mocks["save_state"].assert_called_once_with(st)
        mocks["cancel_order"].assert_called_once_with("BTCUSDC", 333)

    def test_orphan_sl_prev_cancel_retry_waits_until_due(self):
        st = {"position": _position(orders={"sl_prev": 333}, tp1_done=True, sl_prev_next_cancel_s=1100.0)}
        mocks = self._patch_common()

        executor.manage_v15_position("BTCUSDC", st)

        mocks["save_state"].assert_not_called()
        mocks["cancel_order"].assert_not_called()

    def test_tp2_filled_with_no_remaining_qty_closes_slot(self):
        executor.ENV["TRAIL_ACTIVATE_AFTER_TP2"] = False
        pos = _position(orders={"tp2": 222, "sl": 333, "qty1": 0.0, "qty3": 0.0})
        st = {"position": pos}
        events = []

        def fake_status(_symbol, order_id):
            return {"status": "FILLED"} if int(order_id) == 222 else {"status": "NEW"}

        def fake_summary(_state, _snapshot):
            events.append("summary")

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            summary=patch.object(executor, "_send_trade_closed_summary", side_effect=fake_summary),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNone(st["position"])
        self.assertIn("TP2_DONE", self._event_names(mocks["log_event"]))
        mocks["cancel_order"].assert_any_call("BTCUSDC", 333)
        mocks["summary"].assert_called_once()

    def test_tp2_not_filled_records_missing_without_status_timestamp(self):
        st = {"position": _position(orders={"tp2": 222})}
        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertNotIn("tp2_status_next_s", st["position"])
        self.assertIn("tp2:222", st["position"]["missing_not_filled"])
        self.assertIn("TP2_NOT_FILLED", self._event_names(mocks["log_event"]))
        mocks["save_state"].assert_called_once_with(st)

    def test_trailing_activation_after_tp2_places_trailing_sl(self):
        pos = _position(tp1_done=True)
        st = {"position": pos}

        def fake_status(_symbol, order_id):
            oid = int(order_id)
            if oid == 222:
                return {"status": "FILLED"}
            if oid == 333:
                return {"status": "CANCELED"}
            return {"status": "NEW"}

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            place_order_raw=patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 555}),
            trail_desired=patch.object(executor, "_trail_desired_stop_from_agg", return_value=95.0),
            clock=patch.object(executor.time, "time", return_value=1234.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_any_call("BTCUSDC", 111)
        mocks["cancel_order"].assert_any_call("BTCUSDC", 333)
        payload = mocks["place_order_raw"].call_args.args[0]
        self.assertEqual(payload["symbol"], "BTCUSDC")
        self.assertEqual(payload["side"], "SELL")
        self.assertEqual(payload["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(payload["quantity"], executor.fmt_qty(0.04))
        self.assertEqual(payload["stopPrice"], executor.fmt_price(95.0))
        self.assertEqual(payload["price"], executor.fmt_price(94.8))
        self.assertEqual(payload["timeInForce"], "GTC")
        self.assertEqual(payload["newClientOrderId"], "EX_SL_TR_1234")
        self.assertTrue(pos["trail_active"])
        self.assertEqual(pos["trail_sl_price"], 95.0)
        self.assertIn("TRAIL_ACTIVATED_AFTER_TP2", self._event_names(mocks["log_event"]))

    def test_trailing_active_update_interval_guard_does_not_cancel_or_place(self):
        st = {
            "position": _position(
                orders={"sl": 333},
                trail_active=True,
                trail_last_update_s=990.0,
                trail_qty=0.04,
                trail_sl_price=90.0,
                sl_done=True,
            )
        }
        mocks = self._patch_common()

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_not_called()
        mocks["place_order_raw"].assert_not_called()
        mocks["save_state"].assert_not_called()

    def test_trailing_active_missing_sl_restore_places_new_sl(self):
        pos = _position(
            orders={"sl": 0},
            trail_active=True,
            trail_last_update_s=0.0,
            trail_qty=0.04,
            trail_sl_price=90.0,
            sl_done=True,
        )
        st = {"position": pos}
        mocks = self._patch_common(
            place_order_raw=patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 556}),
            trail_desired=patch.object(executor, "_trail_desired_stop_from_agg", return_value=95.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(pos["orders"]["sl"], 556)
        self.assertEqual(pos["trail_sl_price"], 95.0)
        self.assertIn("TRAIL_SL_RESTORED", self._event_names(mocks["log_event"]))

    def test_trailing_update_success_cancels_old_sl_and_places_new_sl(self):
        pos = _position(
            orders={"sl": 333},
            trail_active=True,
            trail_last_update_s=0.0,
            trail_qty=0.04,
            trail_sl_price=90.0,
            sl_done=True,
        )
        st = {"position": pos}

        status_calls = {"sl": 0}

        def fake_status(_symbol, order_id):
            if int(order_id) == 333:
                status_calls["sl"] += 1
                return {"status": "CANCELED"} if status_calls["sl"] >= 2 else {"status": "NEW"}
            return {"status": "NEW"}


        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            place_order_raw=patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 557}),
            trail_desired=patch.object(executor, "_trail_desired_stop_from_agg", return_value=95.0),
            clock=patch.object(executor.time, "time", return_value=1234.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_called_once_with("BTCUSDC", 333)
        payload = mocks["place_order_raw"].call_args.args[0]
        self.assertEqual(payload["newClientOrderId"], "EX_SL_TR_1234")
        self.assertEqual(payload["stopPrice"], executor.fmt_price(95.0))
        self.assertEqual(pos["orders"]["sl"], 557)
        self.assertEqual(pos["trail_sl_price"], 95.0)
        self.assertIn("TRAIL_SL_UPDATED", self._event_names(mocks["log_event"]))

    def test_trailing_update_cancel_not_confirmed_does_not_place_new_sl(self):
        pos = _position(
            orders={"sl": 333},
            trail_active=True,
            trail_last_update_s=0.0,
            trail_qty=0.04,
            trail_sl_price=90.0,
            sl_done=True,
        )
        st = {"position": pos}

        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
            trail_desired=patch.object(executor, "_trail_desired_stop_from_agg", return_value=95.0),
        )

        executor.manage_v15_position("BTCUSDC", st)

        mocks["cancel_order"].assert_called_once_with("BTCUSDC", 333)
        mocks["place_order_raw"].assert_not_called()
        self.assertIn("TRAIL_SL_CANCEL_NOT_CONFIRMED", self._event_names(mocks["log_event"]))

    def test_sl_filled_sets_done_cancels_siblings_and_closes_slot(self):
        pos = _position(tp1_done=True, tp2_done=True)
        st = {"position": pos}
        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "FILLED"}),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNone(st["position"])
        self.assertTrue(st["last_closed"]["sl_done"])
        mocks["cancel_order"].assert_any_call("BTCUSDC", 111)
        mocks["cancel_order"].assert_any_call("BTCUSDC", 222)
        self.assertIn("SL_DONE", self._event_names(mocks["log_event"]))
        mocks["summary"].assert_called_once()

    def test_sl_not_filled_updates_poll_timestamp_and_logs_once(self):
        st = {"position": _position(orders={"sl": 333})}
        mocks = self._patch_common(
            check_order_status=patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}),
        )

        executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(st["position"]["sl_status_next_s"], 1010.0)
        self.assertIn("SL_NOT_FILLED", self._event_names(mocks["log_event"]))
        mocks["save_state"].assert_called_once_with(st)


if __name__ == "__main__":
    unittest.main()
