#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tp_watchdog_sl_gating.py
Tests for TP watchdog gating when SL is filled.

Verifies that TP watchdog does NOT activate synthetic trailing or other actions
when SL is already filled (sl_done=True).
"""
import unittest
from copy import deepcopy
from executor_mod import exit_safety


class TestTPWatchdogSLGating(unittest.TestCase):
    """Test TP watchdog behavior when SL is filled."""

    def setUp(self):
        """Set up test fixtures."""
        self.env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
        }

        self.st = {
            "position": None,
        }

        self.pos_long = {
            "status": "OPEN_FILLED",
            "side": "LONG",
            "mode": "live",
            "qty": 0.3,
            "entry_actual": 100.0,
            "prices": {
                "entry": 100.0,
                "tp1": 102.0,
                "tp2": 104.0,
                "sl": 98.0,
            },
            "orders": {
                "tp1": 111,
                "tp2": 222,
                "sl": 333,
                "qty1": 0.1,
                "qty2": 0.1,
                "qty3": 0.1,
            },
        }

    def test_tp_watchdog_blocks_when_sl_done_true(self):
        """Test TP watchdog returns None when sl_done=True.
        
        This is the EXPECTED behavior to fix the bug described:
        "TP watchdog can activate synthetic trailing after SL is filled"
        
        Currently FAILS because exit_safety.py doesn't check sl_done.
        """
        pos = deepcopy(self.pos_long)
        pos["sl_done"] = True  # SL already filled
        st = {"position": pos}

        # TP2 is missing/canceled, price crossed
        tp2_status = {
            "orderId": 222,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=105.0,  # Price beyond TP2 (104.0)
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        # EXPECTED: TP watchdog should NOT activate synthetic trailing when SL is done
        # Position is effectively closed, no further TP actions should be taken
        self.assertIsNone(
            plan,
            "TP watchdog should return None when sl_done=True (position is closed)",
        )

    def test_tp_watchdog_blocks_tp1_when_sl_done_true(self):
        """Test TP watchdog blocks TP1 actions when sl_done=True."""
        pos = deepcopy(self.pos_long)
        pos["sl_done"] = True  # SL already filled
        st = {"position": pos}

        # TP1 is missing/canceled, price crossed
        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=103.0,  # Price beyond TP1 (102.0)
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        # EXPECTED: TP watchdog should NOT flatten when SL is done
        self.assertIsNone(
            plan,
            "TP watchdog should return None when sl_done=True (position is closed)",
        )

    def test_tp_watchdog_blocks_tp1_partial_when_sl_done_true(self):
        """Test TP watchdog blocks TP1 partial handling when sl_done=True."""
        pos = deepcopy(self.pos_long)
        pos["sl_done"] = True  # SL already filled
        st = {"position": pos}

        # TP1 is partially filled
        tp1_status = {
            "orderId": 111,
            "status": "PARTIALLY_FILLED",
            "origQty": "0.1",
            "executedQty": "0.045",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=102.5,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        # EXPECTED: TP watchdog should NOT handle partial fill when SL is done
        self.assertIsNone(
            plan,
            "TP watchdog should return None when sl_done=True (position is closed)",
        )

    def test_tp_watchdog_works_normally_when_sl_done_false(self):
        """Test TP watchdog works normally when sl_done=False.
        
        This verifies we're not breaking existing behavior.
        """
        pos = deepcopy(self.pos_long)
        # sl_done is NOT set (defaults to False)
        st = {"position": pos}

        # TP2 is missing/canceled, price crossed
        tp2_status = {
            "orderId": 222,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=105.0,  # Price beyond TP2 (104.0)
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        # When SL is NOT done, TP watchdog should activate synthetic trailing
        self.assertIsNotNone(plan, "TP watchdog should work normally when sl_done=False")
        self.assertEqual(plan["action"], "ACTIVATE_SYNTHETIC_TRAILING")

    def test_boot_scenario_sl_filled_tp2_missing_no_open_orders(self):
        """Test BOOT scenario: status=OPEN, openOrders=0, SL filled, TP2 missing.
        
        This is the exact scenario from the bug report:
        "On BOOT/rehydrate with status=OPEN and openOrders=0, bot activates 
        TP2_MISSING_SYNTHETIC_TRAILING before recognizing SL_DONE."
        """
        pos = deepcopy(self.pos_long)
        pos["status"] = "OPEN"  # Status not yet updated to CLOSING
        pos["sl_done"] = True  # SL is filled (should be detected on boot)
        st = {"position": pos}

        # TP2 status shows MISSING (because it was canceled or never existed)
        tp2_status = {
            "status": "MISSING",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=105.0,  # Price beyond TP2
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        # EXPECTED: No action because SL is done (position should be finalizing)
        self.assertIsNone(
            plan,
            "BOOT scenario: TP watchdog should NOT activate when sl_done=True",
        )


if __name__ == "__main__":
    unittest.main()
