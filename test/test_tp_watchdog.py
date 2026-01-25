#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_tp_watchdog.py
Tests for TP watchdog functionality in exit_safety.py
"""
import unittest
from copy import deepcopy
from executor_mod import exit_safety


class TestTPWatchdog(unittest.TestCase):
    """Test TP watchdog scenarios."""

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

        self.pos_short = {
            "status": "OPEN_FILLED",
            "side": "SHORT",
            "mode": "live",
            "qty": 0.3,
            "entry_actual": 100.0,
            "prices": {
                "entry": 100.0,
                "tp1": 98.0,
                "tp2": 96.0,
                "sl": 102.0,
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

    def test_tp1_partial_triggers_cancel_and_market_remaining(self):
        """Test TP1 partial fill detection triggers cancel + market close of remainder."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

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

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["reason"], "TP1_PARTIAL_FALLBACK")
        self.assertAlmostEqual(plan["qty"], 0.055, places=5)  # 0.1 - 0.045 = 0.055
        self.assertEqual(plan["side"], "SELL")
        self.assertEqual(plan["cancel_order_ids"], [111])
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

        # Check events
        event_names = [e["name"] for e in plan["events"]]
        self.assertIn("TP1_PARTIAL_DETECTED", event_names)
        self.assertIn("TP1_MARKET_FALLBACK_PARTIAL", event_names)

    def test_tp1_partial_dust_does_not_market_close(self):
        """Test TP1 partial with dust remainder doesn't attempt market close."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        # Very small remaining qty (dust)
        tp1_status = {
            "orderId": 111,
            "status": "PARTIALLY_FILLED",
            "origQty": "0.1",
            "executedQty": "0.0999",  # Only 0.0001 remaining (dust)
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

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "TP1_PARTIAL_DUST")
        self.assertEqual(plan["qty"], 0.0)  # No market close
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

    def test_tp1_missing_price_crossed_triggers_market_qty1_and_sets_tp1_done(self):
        """Test TP1 missing + price crossed triggers market close of qty1 and sets tp1_done."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Price crossed TP1 (102.0) - now at 103.0
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
        self.assertAlmostEqual(plan["qty"], 0.1, places=5)  # qty1
        self.assertEqual(plan["side"], "SELL")
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

        # Check events
        event_names = [e["name"] for e in plan["events"]]
        self.assertIn("TP1_MISSING_PRICE_CROSSED", event_names)
        self.assertIn("TP1_MARKET_FALLBACK", event_names)

    def test_tp1_missing_price_not_crossed_no_action(self):
        """Test TP1 missing but price NOT crossed does nothing."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Price did NOT cross TP1 (102.0) - still at 101.0
        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=101.0,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        self.assertIsNone(plan)

    def test_tp1_missing_dust_does_not_market_close(self):
        """Test TP1 missing + price crossed with dust qty1 doesn't attempt market close."""
        pos = deepcopy(self.pos_long)
        # Set very small qty1 (dust)
        pos["orders"]["qty1"] = 0.0001
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Price crossed TP1
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
        self.assertEqual(plan["action"], "TP1_MISSING_DUST")
        self.assertEqual(plan["qty"], 0.0)  # No market close
        self.assertTrue(plan["set_tp1_done"])
        self.assertTrue(plan.get("init_be_state_machine"))

    def test_tp2_missing_gate_not_crossed_returns_not_in_zone(self):
        """Test TP2 missing without price cross returns not-in-zone plan."""
        pos = deepcopy(self.pos_long)
        pos["tp1_done"] = True  # TP1 already done
        st = {"position": pos}

        tp2_status = {
            "orderId": 222,
            "status": "MISSING",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=103.0,
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "TP2_MISSING_NOT_IN_ZONE")
        self.assertEqual(plan["reason"], "TP2_MISSING_NOT_IN_ZONE")
        self.assertEqual(plan["tp2_status"], "MISSING")
        self.assertEqual(plan["tp2_price"], 104.0)
        self.assertEqual(plan["price_now"], 103.0)

    def test_tp2_missing_activates_synthetic_trailing_q2q3_and_sets_flag(self):
        """Test TP2 missing activates synthetic trailing on q2+q3 and sets tp2_synthetic=True."""
        pos = deepcopy(self.pos_long)
        pos["tp1_done"] = True  # TP1 already done
        st = {"position": pos}

        tp2_status = {
            "orderId": 222,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=104.5,
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "ACTIVATE_SYNTHETIC_TRAILING")
        self.assertEqual(plan["reason"], "TP2_MISSING")
        self.assertEqual(plan["qty"], 0.0)  # No immediate market action
        self.assertEqual(plan["cancel_order_ids"], [222])
        self.assertTrue(plan["set_tp2_synthetic"])
        self.assertTrue(plan["activate_trail"])
        self.assertAlmostEqual(plan["trail_qty"], 0.2, places=5)  # qty2 + qty3 = 0.1 + 0.1
        self.assertTrue(plan["require_price_gate"])
        self.assertEqual(plan["tp2_status"], "CANCELED")
        self.assertEqual(plan["tp2_price"], 104.0)
        self.assertEqual(plan["price_now"], 104.5)

        # Check events
        event_names = [e["name"] for e in plan["events"]]
        self.assertIn("TP2_MISSING_SYNTHETIC_TRAILING", event_names)

    def test_tp2_missing_before_tp1_done_trails_q2q3_only(self):
        """Test TP2 missing activates trailing ONLY on q2+q3 (per spec)."""
        pos = deepcopy(self.pos_long)
        pos["tp1_done"] = False  # TP1 not done yet
        st = {"position": pos}

        tp2_status = {
            "orderId": 222,
            "status": "EXPIRED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=105.0,
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "ACTIVATE_SYNTHETIC_TRAILING")
        self.assertTrue(plan["set_tp2_synthetic"])
        self.assertTrue(plan["activate_trail"])
        self.assertAlmostEqual(plan["trail_qty"], 0.2, places=5)  # qty2 + qty3 ONLY (not qty1)

    def test_tp2_synthetic_already_set_no_duplicate(self):
        """Test TP2 missing when tp2_synthetic already True doesn't trigger again."""
        pos = deepcopy(self.pos_long)
        pos["tp1_done"] = True
        pos["tp2_synthetic"] = True  # Already set
        st = {"position": pos}

        tp2_status = {
            "orderId": 222,
            "status": "CANCELED",
        }

        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=103.0,
            tp1_status_payload=None,
            tp2_status_payload=tp2_status,
        )

        self.assertIsNone(plan)

    def test_short_position_tp1_partial(self):
        """Test TP1 partial for SHORT position."""
        pos = deepcopy(self.pos_short)
        st = {"position": pos}

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
            price_now=97.5,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["side"], "BUY")  # SHORT closes with BUY
        self.assertAlmostEqual(plan["qty"], 0.055, places=5)

    def test_short_position_tp1_missing_price_crossed(self):
        """Test TP1 missing + price crossed for SHORT position."""
        pos = deepcopy(self.pos_short)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Price crossed TP1 (98.0) - now at 97.0 (below TP1 for SHORT)
        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=97.0,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan["action"], "MARKET_FLATTEN")
        self.assertEqual(plan["side"], "BUY")
        self.assertAlmostEqual(plan["qty"], 0.1, places=5)

    def test_short_position_tp1_missing_price_not_crossed(self):
        """Test TP1 missing but price NOT crossed for SHORT position."""
        pos = deepcopy(self.pos_short)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Price did NOT cross TP1 (98.0) - still at 99.0 (above TP1 for SHORT)
        plan = exit_safety.tp_watchdog_tick(
            st=st,
            pos=pos,
            env=self.env,
            now_s=1000.0,
            price_now=99.0,
            tp1_status_payload=tp1_status,
            tp2_status_payload=None,
        )

        self.assertIsNone(plan)

    def test_no_action_when_status_not_open_or_open_filled(self):
        """Test no action when position status is neither OPEN nor OPEN_FILLED."""
        pos = deepcopy(self.pos_long)
        pos["status"] = "PENDING"  # not OPEN / OPEN_FILLED
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "PARTIALLY_FILLED",
            "origQty": "0.033",
            "executedQty": "0.020",
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

        self.assertIsNone(plan)


    def test_no_action_when_tp1_already_done(self):
        """Test no action when TP1 already marked done."""
        pos = deepcopy(self.pos_long)
        pos["tp1_done"] = True
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "PARTIALLY_FILLED",
            "origQty": "0.033",
            "executedQty": "0.020",
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

        self.assertIsNone(plan)

    def test_no_action_when_tp1_filled(self):
        """Test no action when TP1 status is FILLED."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "FILLED",
            "origQty": "0.033",
            "executedQty": "0.033",
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

        self.assertIsNone(plan)

    def test_no_action_when_price_invalid(self):
        """Test no action when price is invalid (NaN, 0, negative)."""
        pos = deepcopy(self.pos_long)
        st = {"position": pos}

        tp1_status = {
            "orderId": 111,
            "status": "CANCELED",
        }

        # Invalid prices
        for invalid_price in [float("nan"), 0.0, -100.0]:
            plan = exit_safety.tp_watchdog_tick(
                st=st,
                pos=pos,
                env=self.env,
                now_s=1000.0,
                price_now=invalid_price,
                tp1_status_payload=tp1_status,
                tp2_status_payload=None,
            )

            self.assertIsNone(plan)


if __name__ == "__main__":
    unittest.main()
