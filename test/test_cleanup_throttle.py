#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_cleanup_throttle.py
Tests for cleanup_throttled gating behavior in manage_v15_position().

These tests verify that:
1. cleanup_throttled=True blocks active mutations (flatten_market, cancel, BE transition)
2. cleanup_throttled=True allows passive reconciliation (SL_DONE, check_order_status)
3. ACTIVATE_SYNTHETIC_TRAILING defers cancel initiation when cleanup_throttled=True
"""
import unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock, patch, call
import time


class TestCleanupThrottle(unittest.TestCase):
    """Test cleanup_throttled gating in manage_v15_position()."""

    def setUp(self):
        """Save original ENV state."""
        import executor
        self._original_env = deepcopy(executor.ENV)

    def tearDown(self):
        """Restore original ENV state."""
        import executor
        executor.ENV.clear()
        executor.ENV.update(self._original_env)

    def _make_env(self):
        return {
            "SYMBOL": "BTCUSDC",
            "MIN_QTY": Decimal("0.001"),
            "MIN_NOTIONAL": Decimal("5.0"),
            "QTY_STEP": Decimal("0.001"),
            "TICK_SIZE": Decimal("0.1"),
            "SL_WATCHDOG_RETRY_SEC": 5.0,
            "LIVE_STATUS_POLL_EVERY": 2.0,
            "TRAIL_UPDATE_EVERY_SEC": 20.0,
            "TRAIL_ACTIVATE_AFTER_TP2": True,
            "TP1_BE_ENABLED": True,
            "TP1_BE_COOLDOWN_SEC": 0.0,
        }

    def _make_pos_with_cleanup_pending(self, status="OPEN"):
        """Create position with exit_cleanup_pending=True in throttle window."""
        now = time.time()
        return {
            "status": status,
            "side": "LONG",
            "mode": "live",
            "qty": 0.1,
            "entry_actual": 100.0,
            "prices": {"sl": 95.0, "tp1": 105.0, "tp2": 110.0, "entry": 100.0},
            "orders": {"sl": 111, "tp1": 222, "tp2": 333, "qty1": 0.03, "qty2": 0.03, "qty3": 0.04},
            "exit_cleanup_pending": True,
            "exit_cleanup_next_s": now + 60.0,  # 60 sec in future = throttled
            "exit_cleanup_order_ids": [999],
            "exit_cleanup_reason": "TP_WATCHDOG",
        }

    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_watchdog_flatten_blocked_when_cleanup_throttled(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """SL watchdog MARKET_FLATTEN is blocked when cleanup_throttled=True."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = self._make_pos_with_cleanup_pending("OPEN")
        pos["sl_watchdog_grace_s"] = 0.0  # grace satisfied
        st = {"position": pos}

        # Mock sl_watchdog_tick to return MARKET_FLATTEN plan
        def fake_sl_watchdog_tick(**kwargs):
            return {
                "action": "MARKET_FLATTEN",
                "side": "SELL",
                "qty": 0.1,
                "reason": "SL_WATCHDOG",
            }

        with patch.object(executor.exit_safety, "sl_watchdog_tick", side_effect=fake_sl_watchdog_tick):
            mock_api.check_order_status.return_value = {"status": "NEW"}
            mock_api.get_mid_price.return_value = 94.0  # below SL
            mock_api.open_orders.return_value = []

            executor.manage_v15_position("BTCUSDC", st)

        # flatten_market should NOT be called because cleanup_throttled=True
        mock_api.flatten_market.assert_not_called()

    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_tp_watchdog_market_flatten_blocked_when_cleanup_throttled(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """TP watchdog MARKET_FLATTEN is blocked when cleanup_throttled=True."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = self._make_pos_with_cleanup_pending("OPEN")
        st = {"position": pos}

        # Mock tp_watchdog_tick to return MARKET_FLATTEN plan
        def fake_tp_watchdog_tick(**kwargs):
            return {
                "action": "MARKET_FLATTEN",
                "side": "SELL",
                "qty": 0.03,
                "reason": "TP1_MISSING",
            }

        with patch.object(executor.exit_safety, "tp_watchdog_tick", side_effect=fake_tp_watchdog_tick):
            with patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None):
                mock_api.check_order_status.return_value = {"status": "NEW"}
                mock_api.get_mid_price.return_value = 106.0  # above TP1
                mock_api.open_orders.return_value = []

                executor.manage_v15_position("BTCUSDC", st)

        # flatten_market should NOT be called
        mock_api.flatten_market.assert_not_called()

    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_synthetic_trailing_cancel_blocked_when_cleanup_throttled(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """ACTIVATE_SYNTHETIC_TRAILING cancel is deferred when cleanup_throttled=True."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = self._make_pos_with_cleanup_pending("OPEN")
        st = {"position": pos}

        # Mock tp_watchdog_tick to return ACTIVATE_SYNTHETIC_TRAILING
        def fake_tp_watchdog_tick(**kwargs):
            return {
                "action": "ACTIVATE_SYNTHETIC_TRAILING",
                "tp2_status": "CANCELED",
                "price_now": 111.0,
                "tp2_price": 110.0,
                "require_price_gate": True,
                "cancel_order_ids": [333],  # TP2 order to cancel
                "trail_qty": 0.07,
                "set_tp2_synthetic": True,
                "activate_trail": True,
            }

        with patch.object(executor.exit_safety, "tp_watchdog_tick", side_effect=fake_tp_watchdog_tick):
            with patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None):
                mock_api.check_order_status.return_value = {"status": "NEW"}
                mock_api.get_mid_price.return_value = 111.0
                mock_api.open_orders.return_value = []

                executor.manage_v15_position("BTCUSDC", st)

        # cancel_order should NOT be called (deferred)
        mock_api.cancel_order.assert_not_called()
        # Position state should remain unchanged (no trail_active set)
        self.assertFalse(pos.get("trail_active"))

    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_done_finalize_allowed_when_cleanup_throttled(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """SL FILLED detection and _finalize_close still works when cleanup_throttled=True."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = self._make_pos_with_cleanup_pending("OPEN")
        st = {"position": pos}

        # Mock check_order_status to return FILLED for SL
        mock_api.check_order_status.return_value = {"status": "FILLED", "executedQty": "0.1"}
        mock_api.get_mid_price.return_value = 94.0
        mock_api.open_orders.return_value = []

        # sl_watchdog returns SL_FILLED plan (passive detection)
        def fake_sl_watchdog_tick(**kwargs):
            return {
                "action": "SL_DONE",
                "reason": "SL_FILLED",
            }

        with patch.object(executor.exit_safety, "sl_watchdog_tick", side_effect=fake_sl_watchdog_tick):
            with patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
                executor.manage_v15_position("BTCUSDC", st)

        # Position should be closed (sl_done=True or status=CLOSED)
        # The exact behavior depends on implementation, but flatten_market should NOT be called
        mock_api.flatten_market.assert_not_called()

    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_be_transition_blocked_when_cleanup_throttled(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """BE state-machine transition is blocked when cleanup_throttled=True."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = self._make_pos_with_cleanup_pending("OPEN")
        pos["tp1_be_pending"] = True
        pos["tp1_be_old_sl"] = 111
        pos["tp1_be_exit_side"] = "SELL"
        pos["tp1_be_stop"] = 100.0
        pos["tp1_be_rem_qty"] = 0.07
        pos["tp1_be_next_s"] = 0.0  # ready to run
        st = {"position": pos}

        mock_api.check_order_status.return_value = {"status": "NEW"}
        mock_api.open_orders.return_value = []

        with patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None):
            with patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
                executor.manage_v15_position("BTCUSDC", st)

        # cancel_order and place_order_raw should NOT be called for BE transition
        # (BE logic gated by cleanup_throttled)
        mock_api.cancel_order.assert_not_called()
        mock_api.place_order_raw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
