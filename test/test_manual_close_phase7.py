import os
import unittest
from copy import deepcopy
from unittest.mock import patch

import executor
from executor_mod import notifications


class TestManualClosePhase7(unittest.TestCase):
    def test_manual_close_trade_closed_includes_details_and_persists_dedup(self):
        # Arrange
        symbol = str(executor.ENV.get("SYMBOL", "BTCUSDC") or "BTCUSDC")

        st = {
            "symbol": symbol,
            "lock_until": 0.0,
            "cooldown_until": 0.0,
            "baseline": {"active": {"signal": "seed"}},
            "position": {
                "symbol": symbol,
                "mode": "live",
                "status": "OPEN",
                "side": "LONG",
                "qty": 0.01,
                "prices": {"entry": 100.0},
                # IMPORTANT: must be truthy, otherwise manage_v15_position returns before tick()
                "orders": {"dummy": 1},
                "trade_key": "TK1",
                "manual_close_diag": {"why": "exchange_empty"},
            },
        }

        manual_signal = {
            "handled": True,
            "reason": "MANUAL",
            "tag": "MANUAL",
            "details": {"k": "v"},
        }

        sent_payloads = []
        saved_states = []

        def capture_save_state(state):
            saved_states.append(deepcopy(state))

        def capture_webhook(payload, *a, **k):
            sent_payloads.append(payload)
            return True  # simulate successful webhook delivery

        # Act
        with patch.object(executor.manual_close_detector, "tick", return_value=manual_signal) as tick_mock, \
             patch.object(executor, "save_state", side_effect=capture_save_state), \
             patch.object(executor.reporting, "report_trade_close", side_effect=lambda *a, **k: None), \
             patch.object(executor.margin_guard, "on_after_position_closed", side_effect=lambda *a, **k: None), \
             patch.object(executor, "log_event", side_effect=lambda *a, **k: None), \
             patch.object(notifications, "log_event", side_effect=lambda *a, **k: None), \
             patch.object(notifications, "send_webhook", side_effect=capture_webhook):

            executor.manage_v15_position(symbol, st)

        # Assert: tick reached
        self.assertEqual(tick_mock.call_count, 1, "Expected manual_close_detector.tick() to be called once.")

        # Assert: TRADE_CLOSED emitted once
        self.assertEqual(len(sent_payloads), 1, "Expected exactly one webhook payload.")
        payload = sent_payloads[0]
        self.assertEqual(payload.get("event"), "TRADE_CLOSED")
        self.assertEqual(payload.get("trade_key"), "TK1")

        # Assert: details attached
        self.assertEqual(payload.get("details", {}).get("manual_close"), {"k": "v"})

        # Assert: state saved (via _close_slot)
        self.assertTrue(saved_states, "Expected save_state() to be called during close slot.")
        last_saved = saved_states[-1]

        # last_closed should contain details
        self.assertEqual(
            (last_saved.get("last_closed") or {}).get("details", {}).get("manual_close"),
            {"k": "v"},
        )

        # dedupe key must be persisted in state
        self.assertEqual(last_saved.get("last_notified_close_trade_key"), "TK1")

    def test_phase6_no_legacy_flags(self):
        # Guard: no legacy flags/logging referenced in executor.py
        root = os.path.dirname(os.path.dirname(__file__))
        executor_path = os.path.join(root, "executor.py")
        with open(executor_path, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()

        self.assertNotIn("manual_close_notified", src)
        self.assertNotIn('log_event("MANUAL_CLOSE_DETECTED_OK"', src)
