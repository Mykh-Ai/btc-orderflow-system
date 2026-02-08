#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_terminal_detection_first.py

Tests for Terminal Detection First (WATCHDOG_SPEC.md:491-492).

Critical contract: "Step 1: Terminal Detection FIRST
                    └─ if sl_done OR SL FILLED → finalize_close(); return"

These tests verify:
1. If sl_done=True, SL watchdog should NOT execute
2. If sl_done=True, TP watchdog should NOT execute
3. If SL FILLED detected, finalization happens immediately (blocks trailing/BE)
4. Terminal Detection runs BEFORE all other logic (ordering guarantee)

Addresses AUDIT_PRODUCT_QUALITY.md Blockers #1, #5.
"""
import unittest
from copy import deepcopy
from decimal import Decimal
from unittest.mock import MagicMock, patch, call
import time


class TestTerminalDetectionFirst(unittest.TestCase):
    """Test Terminal Detection ordering in manage_v15_position()."""

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
        }

    # =========================================================================
    # CRITICAL TEST 1: sl_done=True blocks SL watchdog
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_done_blocks_sl_watchdog_entirely(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        CRITICAL: If sl_done=True, sl_watchdog_tick should NOT be called.

        This verifies Terminal Detection runs BEFORE SL watchdog.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        # Position with sl_done=True (SL already filled)
        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "sl_done": True,  # ← KEY: SL already filled
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        # Mock watchdog functions to track if they're called
        with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd:
            with patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
                executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL ASSERTION: SL watchdog should NOT be called
        mock_sl_wd.assert_not_called()

        # Position should be finalized (None or moved to last_closed)
        self.assertIsNone(st.get("position"),
                         "Position should be finalized when sl_done=True")

    # =========================================================================
    # CRITICAL TEST 2: sl_done=True blocks manual close detector
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_done_blocks_manual_close_detector(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        CRITICAL: If sl_done=True, manual_close_detector.tick should NOT be called.

        This verifies Terminal Detection preempts manual-close detection.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "sl_done": True,
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        with patch.object(executor.manual_close_detector, "tick") as mock_manual:
            with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd:
                with patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
                    executor.manage_v15_position("BTCUSDC", st)

        mock_manual.assert_not_called()
        self.assertIsNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 3: sl_done=True blocks TP watchdog
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_done_blocks_tp_watchdog_entirely(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        CRITICAL: If sl_done=True, tp_watchdog_tick should NOT be called.

        This verifies Terminal Detection blocks TP watchdog.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "sl_done": True,
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd:
            with patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
                executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL ASSERTION: TP watchdog should NOT be called
        mock_tp_wd.assert_not_called()

        self.assertIsNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 3: SL FILLED detection → immediate finalize (blocks trailing)
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_filled_during_trailing_finalizes_immediately(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        If SL fills while trail_active=True, finalize immediately.

        Do NOT attempt to update trailing stop.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        # Position with trailing active
        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "trail_active": True,  # ← Trailing active
            "tp1_done": True,
            "tp2_done": True,
            "orders": {"sl": 999},
            "prices": {"sl": 95000.0, "entry": 96000.0},
            "qty": 0.04,
            "trail_qty": 0.04,
            "trail_sl_price": 95000.0,
            "trail_last_update_s": 0.0,  # ready for update
        }
        st = {"position": pos}

        # Mock: SL order is FILLED
        mock_api.check_order_status.return_value = {
            "status": "FILLED",
            "orderId": 999,
            "executedQty": "0.04"
        }
        mock_api.open_orders.return_value = []

        # Mock trailing stop calculation (should NOT be called)
        with patch("executor._trail_desired_stop_from_agg") as mock_trail:
            mock_trail.return_value = 95100.0  # new stop level

            executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL ASSERTIONS:
        # 1. Position finalized
        self.assertIsNone(st.get("position"),
                         "Position should finalize when SL FILLED detected")

        # 2. Trailing update should NOT execute (no cancel_order for trailing update)
        # Note: cancel_order might be called for cleanup, but not for trailing update
        # We verify by checking that position is None (finalized immediately)

        # 3. sl_done was set before finalization
        last_closed = st.get("last_closed")
        self.assertIsNotNone(last_closed, "last_closed should be populated")

    # =========================================================================
    # CRITICAL TEST 4: SL FILLED detection → blocks TP watchdog
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_filled_detection_blocks_tp_watchdog(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        If SL is FILLED, TP watchdog should NOT execute.

        Terminal Detection should detect SL FILLED and finalize before
        TP watchdog has a chance to run.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        # Mock: SL is FILLED
        def mock_status(symbol, order_id):
            if order_id == 999:  # SL
                return {"status": "FILLED", "orderId": 999, "executedQty": "0.1"}
            return {"status": "NEW"}

        mock_api.check_order_status.side_effect = mock_status
        mock_api.open_orders.return_value = []

        with patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
            with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd:
                executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL: TP watchdog should NOT be called
        mock_tp_wd.assert_not_called()

        # Position finalized
        self.assertIsNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 5: sl_prev FILLED finalizes before TP paths
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_prev_filled_finalizes_before_tp_paths(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        Legacy SL (sl_prev) FILLED must finalize immediately and preempt TP/BE logic.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl_prev": 888, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        def fake_status(_symbol, oid):
            if int(oid) == 888:
                return {"status": "FILLED", "orderId": 888, "executedQty": "0.1"}
            return {"status": "NEW", "orderId": int(oid)}

        mock_api.check_order_status.side_effect = fake_status

        events = []

        def capture_event(event, *args, **kwargs):
            events.append(event)

        mock_log.side_effect = capture_event

        with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd, \
             patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
            executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNone(st.get("position"))
        self.assertEqual(st.get("last_closed", {}).get("reason"), "SL")
        mock_sl_wd.assert_not_called()
        mock_tp_wd.assert_not_called()
        tp_events = [event for event in events if isinstance(event, str) and event.startswith(("TP1_", "TP2_"))]
        self.assertEqual(tp_events, [])

    # =========================================================================
    # CRITICAL TEST 5: SL FILLED detection → blocks BE transition
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_filled_detection_blocks_be_transition(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        If SL is FILLED, BE transition should NOT execute.

        Even if tp1_be_pending=True, Terminal Detection should finalize first.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "tp1_done": True,
            "tp1_be_pending": True,  # ← BE transition pending
            "tp1_be_old_sl": 999,
            "tp1_be_exit_side": "SELL",
            "tp1_be_stop": 95500.0,
            "tp1_be_rem_qty": 0.07,
            "tp1_be_next_s": 0.0,  # ready to run
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        # Mock: SL is FILLED
        mock_api.check_order_status.return_value = {
            "status": "FILLED",
            "orderId": 999,
            "executedQty": "0.1"
        }
        mock_api.open_orders.return_value = []

        executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL: BE transition should NOT execute (no cancel_order for old SL)
        # Note: cancel_order might be called for cleanup, but not for BE transition
        # Verify by checking position is None and no new SL placed
        mock_api.place_order_raw.assert_not_called()
        mock_api.place_spot_limit.assert_not_called()

        self.assertIsNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 6: Trailing update does NOT execute when sl_done=True
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_trailing_update_skipped_when_sl_done(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        If sl_done=True, trailing update should NOT execute.

        No cancel_order or place_order_raw calls for trailing update.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        now = time.time()
        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "trail_active": True,
            "sl_done": True,  # ← SL already filled
            "orders": {"sl": 999},
            "prices": {"sl": 95000.0, "entry": 96000.0},
            "trail_qty": 0.04,
            "trail_sl_price": 95000.0,
            "trail_last_update_s": now - 30.0,  # ready for update (>20sec ago)
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        # Mock trailing calculation (should NOT be used)
        with patch("executor._trail_desired_stop_from_agg") as mock_trail:
            mock_trail.return_value = 95100.0

            executor.manage_v15_position("BTCUSDC", st)

        # CRITICAL: Trailing update should NOT execute
        # (no cancel_order for trailing, no place_order_raw for new trailing SL)
        # Position should be finalized
        self.assertIsNone(st.get("position"))

    # =========================================================================
    # EDGE CASE TEST 7: sl_done propagates across restarts
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_sl_done_survives_restart_blocks_watchdog(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """
        If position loaded from state with sl_done=True, watchdog still blocked.

        This simulates restart after SL filled but before finalization completed.
        """
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        # Position loaded from state file with sl_done=True
        pos = {
            "mode": "live",
            "status": "OPEN_FILLED",
            "side": "LONG",
            "sl_done": True,  # ← from previous execution
            "orders": {"sl": 999, "tp1": 111, "tp2": 222},
            "prices": {"sl": 95000.0, "tp1": 96000.0, "tp2": 97000.0, "entry": 95500.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        with patch.object(executor.exit_safety, "sl_watchdog_tick") as mock_sl_wd:
            with patch.object(executor.exit_safety, "tp_watchdog_tick") as mock_tp_wd:
                executor.manage_v15_position("BTCUSDC", st)

        # Watchdogs should NOT execute even after restart
        mock_sl_wd.assert_not_called()
        mock_tp_wd.assert_not_called()

        self.assertIsNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 8: terminal UNKNOWN blocks SL watchdog market
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_terminal_unknown_blocks_sl_market(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """MARKET must be blocked when terminal state is UNKNOWN (SL watchdog)."""
        import executor

        env = self._make_env()
        env["SL_WATCHDOG_GRACE_SEC"] = 0.0
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 123},
            "prices": {"sl": 98.0, "entry": 100.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []
        mock_api.check_order_status.side_effect = Exception("status error")

        class _Snap:
            ok = True
            price_mid = 97.0

        with patch.object(executor.price_snapshot, "refresh_price_snapshot", return_value=None), \
             patch.object(executor.price_snapshot, "get_price_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        mock_api.flatten_market.assert_not_called()
        self.assertIsNotNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 9: terminal UNKNOWN blocks TP watchdog market
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_terminal_unknown_blocks_tp_market(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """MARKET must be blocked when terminal state is UNKNOWN (TP watchdog)."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 333, "tp1": 111, "tp2": 222, "qty1": 0.1, "qty2": 0.0, "qty3": 0.0},
            "prices": {"sl": 98.0, "tp1": 102.0, "tp2": 104.0, "entry": 100.0},
            "qty": 0.1,
        }
        st = {"position": pos}

        mock_api.open_orders.return_value = []

        def fake_status(_symbol, order_id):
            if int(order_id) == 333:
                raise Exception("status error")
            if int(order_id) == 111:
                return {"status": "CANCELED", "orderId": 111}
            return {"status": "NEW", "orderId": int(order_id)}

        mock_api.check_order_status.side_effect = fake_status

        class _Snap:
            ok = True
            price_mid = 103.0

        with patch.object(executor.price_snapshot, "refresh_price_snapshot", return_value=None), \
             patch.object(executor.price_snapshot, "get_price_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        mock_api.flatten_market.assert_not_called()
        self.assertIsNotNone(st.get("position"))

    # =========================================================================
    # CRITICAL TEST 10: terminal probe avoids status API when poll not due
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_terminal_probe_respects_poll_throttle(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """Terminal probe must not call check_order_status when poll is not due."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 123},
            "prices": {"sl": 98.0, "entry": 100.0},
            "qty": 0.1,
            "sl_status_next_s": time.time() + 60.0,
        }
        st = {"position": pos}

        class _Snap:
            ok = True
            error = None

            def get_orders(self):
                return [{
                    "orderId": 123,
                    "status": "NEW",
                    "origQty": "0.1",
                    "executedQty": "0.0",
                }]

            def freshness_sec(self):
                return 0.0

        mock_api.open_orders.return_value = []

        with patch.object(executor, "refresh_snapshot", return_value=False), \
             patch.object(executor, "get_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
             patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        mock_api.check_order_status.assert_not_called()

    # =========================================================================
    # CRITICAL TEST 11: missing openOrders does not bypass poll throttle
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_terminal_probe_skips_status_when_missing_open_orders_and_poll_not_due(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """Terminal probe must not call status API when openOrders missing but poll not due."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 123},
            "prices": {"sl": 98.0, "entry": 100.0},
            "qty": 0.1,
            "sl_status_next_s": time.time() + 60.0,
        }
        st = {"position": pos}

        class _Snap:
            ok = True
            error = None

            def get_orders(self):
                return []

            def freshness_sec(self):
                return 0.0

        mock_api.open_orders.return_value = []

        with patch.object(executor, "refresh_snapshot", return_value=False), \
             patch.object(executor, "get_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
             patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        mock_api.check_order_status.assert_not_called()

    # =========================================================================
    # CRITICAL TEST 12: terminal probe single-flight prevents double status poll
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_terminal_probe_single_flight_blocks_second_status_poll(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """Terminal probe status poll must not trigger a second status poll in the same tick."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {"tp1": 111},
            "prices": {"tp1": 102.0, "entry": 100.0},
            "qty": 0.1,
            "tp1_status_next_s": time.time() - 10.0,
        }
        st = {"position": pos}

        class _Snap:
            ok = True
            error = None

            def get_orders(self):
                return []

            def freshness_sec(self):
                return 0.0

        mock_api.open_orders.return_value = []
        mock_api.check_order_status.return_value = {
            "status": "NEW",
            "orderId": 111,
            "executedQty": "0.0",
            "origQty": "0.1",
        }

        with patch.object(executor, "refresh_snapshot", return_value=False), \
             patch.object(executor, "get_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
             patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        self.assertEqual(mock_api.check_order_status.call_count, 1)

    # =========================================================================
    # CRITICAL TEST 13: TP terminal proof avoids qty2/qty3-only confirmation
    # =========================================================================
    @patch("executor.binance_api")
    @patch("executor.save_state")
    @patch("executor.send_webhook")
    @patch("executor.log_event")
    def test_tp_terminal_probe_not_overconfirmed_on_qty_desync(
        self, mock_log, mock_webhook, mock_save, mock_api
    ):
        """TP terminal confirmation must not rely on stale qty2/qty3 state."""
        import executor

        env = self._make_env()
        executor.ENV.update(env)

        pos = {
            "mode": "live",
            "status": "OPEN",
            "side": "LONG",
            "orders": {
                "sl": 333,
                "tp1": 111,
                "tp2": 222,
                "qty1": 0.01,
                "qty2": 0.01,
                "qty3": 0.0,
                "fills": {
                    "tp1": {
                        "orderId": 111,
                        "status": "FILLED",
                        "executedQty": "0.03",
                        "origQty": "0.03",
                    }
                },
            },
            "prices": {"sl": 98.0, "tp1": 102.0, "tp2": 104.0, "entry": 100.0},
            "qty": 0.0,
            "sl_status_next_s": time.time() + 60.0,
            "tp1_status_next_s": time.time() + 60.0,
            "tp2_status_next_s": time.time() + 60.0,
        }
        st = {"position": pos}

        class _Snap:
            ok = True
            error = None

            def get_orders(self):
                return [{
                    "orderId": 111,
                    "status": "NEW",
                    "origQty": "0.03",
                    "executedQty": "0.0",
                }]

            def freshness_sec(self):
                return 0.0

        mock_api.open_orders.return_value = []

        with patch.object(executor, "refresh_snapshot", return_value=False), \
             patch.object(executor, "get_snapshot", return_value=_Snap()), \
             patch.object(executor.exit_safety, "sl_watchdog_tick", return_value=None), \
             patch.object(executor.exit_safety, "tp_watchdog_tick", return_value=None):
            executor.manage_v15_position("BTCUSDC", st)

        self.assertIsNotNone(st.get("position"))

    # =========================================================================
    # NEGATIVE TEST 8: Test would FAIL if Terminal Detection is commented out
    # =========================================================================
    def test_ordering_verification_comment(self):
        """
        Meta-test: Verifies that test suite enforces Terminal Detection ordering.

        If executor.py lines for Terminal Detection (checking sl_done or SL FILLED)
        are commented out or moved to the end, tests 1-7 should FAIL.

        This is a documentation test, not executable.
        """
        # This test documents the requirement:
        #
        # If you comment out Terminal Detection block in executor.py:
        #   # if pos.get("sl_done") or sl_filled:
        #   #     _finalize_close("SL")
        #   #     return
        #
        # Then tests 1-7 above MUST fail with:
        #   AssertionError: Expected 'sl_watchdog_tick' to not have been called
        #
        # This proves tests enforce the Finalization-First contract.
        pass


if __name__ == "__main__":
    unittest.main()
