#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_sl_watchdog.py
Tests for SL watchdog functionality in exit_safety.py
"""
import unittest
from copy import deepcopy
from executor_mod import exit_safety


class TestSLWatchdog(unittest.TestCase):
    """Test SL watchdog scenarios."""

    def setUp(self):
        self.env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
            "SL_WATCHDOG_GRACE_SEC": 0.0,
        }

        self.pos_long = {
            "status": "OPEN",
            "side": "LONG",
            "mode": "live",
            "qty": 0.2,
            "prices": {
                "sl": 98.0,
            },
            "orders": {
                "sl": 123,
            },
        }

    def test_sl_watchdog_triggers_market_flatten_when_price_crosses(self):
        """SL watchdog returns MARKET_FLATTEN when price crosses stop and grace satisfied."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        sl_status = {
            "orderId": 123,
            "status": "NEW",
            "origQty": "0.2",
            "executedQty": "0.0",
            "stopPrice": "98.0",
        }

        plan = exit_safety.sl_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=97.5,
            sl_order_payload_or_status=sl_status,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["reason"], "SL_WATCHDOG")
        self.assertEqual(plan["side"], "SELL")
        self.assertAlmostEqual(plan["qty"], 0.2, places=6)


class TestTPWatchdogOpenStatus(unittest.TestCase):
    """Test TP watchdog reachability in OPEN status."""

    def setUp(self):
        self.env = {
            "MIN_QTY": 0.001,
            "MIN_NOTIONAL": 5.0,
            "QTY_STEP": 0.001,
            "TICK_SIZE": 0.1,
        }

        self.pos_long = {
            "status": "OPEN",
            "side": "LONG",
            "mode": "live",
            "qty": 0.3,
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

    def test_tp_watchdog_runs_in_open_status(self):
        """TP watchdog returns plan when status is OPEN and TP1 is missing with price crossed."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=103.0,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["reason"], "TP1_MISSING_PRICE_CROSSED")


if __name__ == "__main__":
    unittest.main()
