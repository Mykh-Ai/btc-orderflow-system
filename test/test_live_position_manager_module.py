import ast
import importlib
import inspect
import unittest
from copy import deepcopy
from unittest.mock import patch


executor = importlib.import_module("executor")
lpm = importlib.import_module("executor_mod.live_position_manager")


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


class TestLivePositionManagerModule(unittest.TestCase):
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

    def test_module_has_no_forbidden_imports(self):
        tree = ast.parse(inspect.getsource(lpm))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")

        prefix = "executor" + "_mod."
        forbidden = {
            "executor",
            prefix + "binance" + "_api",
            prefix + "notifications",
            prefix + "state" + "_store",
            prefix + "margin" + "_guard",
            prefix + "trade" + "_execution" + "_snapshot",
            prefix + "trade" + "_close" + "_summary",
            prefix + "trade" + "_outcome" + "_archive",
        }
        self.assertTrue(forbidden.isdisjoint(imported))
        self.assertNotIn("load" + "_state", inspect.getsource(lpm))

    def test_wrapper_uses_patched_open_orders_status_save_and_log(self):
        st = {"position": _position(orders={"tp1": 111})}

        with (
            patch.object(executor.binance_api, "open_orders", return_value=[]) as open_orders,
            patch.object(executor.binance_api, "check_order_status", return_value={"status": "NEW"}) as status,
            patch.object(executor, "save_state") as save_state,
            patch.object(executor, "log_event") as log_event,
            patch.object(executor, "_now_s", return_value=1000.0),
        ):
            executor.manage_v15_position("BTCUSDC", st)

        open_orders.assert_called_once_with("BTCUSDC")
        status.assert_called_once_with("BTCUSDC", 111)
        save_state.assert_called_once_with(st)
        log_event.assert_called_once()
        self.assertEqual(log_event.call_args.args[0], "TP1_NOT_FILLED")

    def test_wrapper_uses_patched_cancel_place_mid_price_and_trail(self):
        pos = _position(tp1_done=True)
        st = {"position": pos}

        def fake_status(_symbol, order_id):
            oid = int(order_id)
            if oid == 222:
                return {"status": "FILLED"}
            if oid == 333:
                return {"status": "CANCELED"}
            return {"status": "NEW"}

        with (
            patch.object(executor.binance_api, "open_orders", return_value=[]),
            patch.object(executor.binance_api, "check_order_status", side_effect=fake_status),
            patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}) as cancel_order,
            patch.object(executor.binance_api, "place_order_raw", return_value={"orderId": 555}) as place_order,
            patch.object(executor.binance_api, "get_mid_price", return_value=120.0) as mid_price,
            patch.object(executor, "_trail_desired_stop_from_agg", return_value=None) as trail_stop,
            patch.object(executor, "save_state"),
            patch.object(executor, "log_event"),
            patch.object(executor, "send_webhook"),
            patch.object(executor, "_now_s", return_value=1000.0),
            patch.object(executor.time, "time", return_value=1234.0),
        ):
            executor.manage_v15_position("BTCUSDC", st)

        trail_stop.assert_called_once_with(pos)
        mid_price.assert_called_once_with("BTCUSDC")
        cancel_order.assert_any_call("BTCUSDC", 111)
        cancel_order.assert_any_call("BTCUSDC", 333)
        payload = place_order.call_args.args[0]
        self.assertEqual(payload["symbol"], "BTCUSDC")
        self.assertEqual(payload["type"], "STOP_LOSS_LIMIT")
        self.assertEqual(payload["stopPrice"], executor.fmt_price(105.0))
        self.assertEqual(payload["newClientOrderId"], "EX_SL_TR_1234")
        self.assertEqual(pos["orders"]["sl"], 555)

    def test_wrapper_uses_patched_close_path_dependencies(self):
        pos = _position(tp1_done=True, tp2_done=True)
        st = {"position": pos, "cooldown_until": 0.0, "lock_until": 42.0}
        snapshot = {"snapshot": "patched"}

        with (
            patch.object(executor.binance_api, "open_orders", return_value=[]),
            patch.object(executor.binance_api, "check_order_status", return_value={"status": "FILLED"}),
            patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}),
            patch.object(executor, "save_state") as save_state,
            patch.object(executor, "log_event"),
            patch.object(executor, "send_webhook"),
            patch.object(executor, "_record_trade_execution_snapshot", return_value=snapshot) as record_snapshot,
            patch.object(executor.trade_outcome_archive, "record_outcome") as archive,
            patch.object(executor.margin_guard, "on_after_position_closed") as margin_hook,
            patch.object(executor, "_send_trade_closed_summary") as summary,
            patch.object(executor, "_now_s", return_value=1000.0),
        ):
            executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNone(st["position"])
        record_snapshot.assert_called_once_with(st, "_close_slot", enrich_exchange=True)
        save_state.assert_any_call(st)
        archive.assert_called_once_with(st, "_close_slot", "BTCUSDC")
        margin_hook.assert_called_once_with(st)
        summary.assert_called_once_with(st, snapshot)


if __name__ == "__main__":
    unittest.main()
