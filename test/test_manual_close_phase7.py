import os
import unittest
from copy import deepcopy
from unittest.mock import patch

import executor
from executor_mod import notifications


class TestManualClosePhase7(unittest.TestCase):
    def test_manual_close_trade_closed_includes_details(self):
        st = {
            "baseline": {"active": {"signal": "seed"}},
            "position": {
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "prices": {"entry": 100.0},
                "orders": {},
                "trade_key": "TK1",
                "manual_close_diag": {"why": "exchange_empty"},
            },
        }
        pos = st["position"]
        manual_signal = {
            "handled": True,
            "reason": "MANUAL",
            "tag": "MANUAL",
            "details": {"k": "v"},
        }
        closed_calls = []
        saved = []

        def capture_save_state(state):
            saved.append(deepcopy(state))

        def capture_send_trade_closed(st_arg, pos_arg, reason_arg, mode="live"):
            closed_calls.append(
                {
                    "st": deepcopy(st_arg),
                    "pos": deepcopy(pos_arg),
                    "reason": reason_arg,
                    "mode": mode,
                }
            )

        with patch.object(executor.manual_close_detector, "tick", return_value=manual_signal), \
             patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}), \
             patch.object(executor, "save_state", side_effect=capture_save_state), \
             patch.object(executor.reporting, "report_trade_close", side_effect=lambda *a, **k: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", side_effect=lambda *a, **k: None), \
             patch.object(executor, "log_event", side_effect=lambda *a, **k: None), \
             patch.object(notifications, "log_event", side_effect=lambda *a, **k: None), \
             patch.object(executor, "send_trade_closed", side_effect=capture_send_trade_closed):
            executor.manage_v15_position(executor.ENV["SYMBOL"], st)

        self.assertEqual(len(closed_calls), 1, "Expected send_trade_closed to be called exactly once.")
        call = closed_calls[0]
        self.assertEqual(call["mode"], "live")
        self.assertEqual(call["pos"].get("trade_key"), "TK1")
        self.assertEqual(
            (call["st"].get("last_closed") or {}).get("details", {}).get("manual_close"),
            {"k": "v"},
        )

        self.assertTrue(saved, "Expected state to be saved after close.")
        last_saved = saved[-1]
        self.assertEqual(
            last_saved.get("last_closed", {}).get("details", {}).get("manual_close"),
            {"k": "v"},
        )
        self.assertEqual(last_saved.get("last_notified_close_trade_key"), "TK1")

    def test_phase6_no_legacy_flags(self):
        root = os.path.dirname(os.path.dirname(__file__))
        executor_path = os.path.join(root, "executor.py")
        with open(executor_path, "r", encoding="utf-8") as f:
            executor_src = f.read()

        self.assertNotIn("manual_close_notified", executor_src)
        self.assertNotIn('log_event("MANUAL_CLOSE_DETECTED_OK"', executor_src)
