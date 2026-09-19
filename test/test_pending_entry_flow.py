import unittest
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import executor


def _pending_position(**overrides):
    pos = {
        "mode": "live",
        "status": "PENDING",
        "opened_at": "2025-01-01T00:00:00Z",
        "opened_s": 900.0,
        "last_poll_s": 0.0,
        "order_id": 100,
        "client_id": "EX_EN_ORIGINAL",
        "trade_key": "EX_EN_ORIGINAL",
        "side": "LONG",
        "qty": 0.1,
        "entry": 50000.0,
        "prices": {"entry": 50000.0, "tp1": 51000.0, "tp2": 52000.0, "sl": 49000.0},
    }
    pos.update(overrides)
    return pos


class TestPendingEntryFlow(unittest.TestCase):
    def setUp(self):
        self.env_snapshot = deepcopy(executor.ENV)
        executor.ENV["SYMBOL"] = "BTCUSDC"
        executor.ENV["POLL_SEC"] = 0
        executor.ENV["INVAR_ENABLED"] = False
        executor.ENV["LIVE_STATUS_POLL_EVERY"] = 10
        executor.ENV["LIVE_ENTRY_TIMEOUT_SEC"] = 90
        executor.ENV["ENTRY_MODE"] = "LIMIT_THEN_MARKET"
        executor.ENV["PLANB_REQUIRE_PRICE"] = True
        executor.ENV["TICK_SIZE"] = Decimal("0.1")
        executor.ENV["QTY_STEP"] = Decimal("0.001")

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self.env_snapshot)

    def _run_one_pending_cycle(
        self,
        st,
        *,
        now=1000.0,
        check_status=None,
        cancel_order=None,
        market_order=None,
        market_error=None,
        planb_price=50000.0,
        planb_price_error=None,
        planb_allowed=(True, "OK", {}),
        entry_mode=None,
        planb_require_price=None,
    ):
        order = []
        saves = []
        events = []
        webhooks = []
        tail_calls = []
        sleep_calls = {"n": 0}

        def fake_sleep(_sec):
            sleep_calls["n"] += 1
            if sleep_calls["n"] > 1:
                raise StopIteration

        def fake_tail(*args, **kwargs):
            tail_calls.append((args, kwargs))
            if len(tail_calls) == 1:
                return []
            raise StopIteration

        def fake_save(state):
            snap = deepcopy(state)
            saves.append(snap)
            order.append(("save", snap))

        def fake_log(event, **kwargs):
            events.append((event, deepcopy(kwargs)))
            order.append(("log", event, deepcopy(kwargs)))

        def fake_webhook(payload):
            webhooks.append(deepcopy(payload))
            order.append(("webhook", deepcopy(payload)))

        def fake_margin_before(*args, **kwargs):
            order.append(("margin_before", args, deepcopy(kwargs)))

        def fake_margin_after(*args, **kwargs):
            order.append(("margin_after", args, deepcopy(kwargs)))

        def fake_ensure(*args, **kwargs):
            order.append(("ensure_exits", args, deepcopy(kwargs)))
            return True

        def fake_market(*args, **kwargs):
            order.append(("place_market", args, deepcopy(kwargs)))
            if market_error is not None:
                raise market_error
            return market_order if market_order is not None else {"orderId": 200}

        def fake_planb_price(*args, **kwargs):
            if planb_price_error is not None:
                raise planb_price_error
            return planb_price

        status_mock = Mock(return_value={"status": "NEW", "executedQty": "0"})
        if check_status is not None:
            if isinstance(check_status, BaseException):
                status_mock = Mock(side_effect=check_status)
            else:
                status_mock = Mock(side_effect=check_status) if callable(check_status) else Mock(return_value=check_status)
        cancel_mock = Mock(return_value={"status": "CANCELED"})
        if cancel_order is not None:
            cancel_mock = Mock(side_effect=cancel_order) if callable(cancel_order) else Mock(return_value=cancel_order)

        if entry_mode is not None:
            executor.ENV["ENTRY_MODE"] = entry_mode
        if planb_require_price is not None:
            executor.ENV["PLANB_REQUIRE_PRICE"] = planb_require_price

        with ExitStack() as stack:
            stack.enter_context(patch.object(executor, "_validate_trade_mode", return_value="spot"))
            stack.enter_context(patch.object(executor, "load_state", return_value=st))
            stack.enter_context(patch.object(executor, "read_tail_lines", side_effect=fake_tail))
            stack.enter_context(patch.object(executor, "bootstrap_seen_keys_from_tail", return_value=None))
            stack.enter_context(patch.object(executor, "_preflight_margin_cross_usdc", return_value=None))
            stack.enter_context(patch.object(executor, "sync_from_binance", return_value=None))
            stack.enter_context(patch.object(executor.atexit, "register", return_value=None))
            stack.enter_context(patch.object(executor.signal, "signal", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_startup", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_shutdown", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_before_entry", side_effect=fake_margin_before))
            stack.enter_context(patch.object(executor.margin_guard, "on_after_entry_opened", side_effect=fake_margin_after))
            stack.enter_context(patch.object(executor.invariants, "run", return_value=None))
            stack.enter_context(patch.object(executor.time, "sleep", side_effect=fake_sleep))
            stack.enter_context(patch.object(executor, "_now_s", return_value=now))
            stack.enter_context(patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"))
            stack.enter_context(patch.object(executor, "save_state", side_effect=fake_save))
            stack.enter_context(patch.object(executor, "log_event", side_effect=fake_log))
            stack.enter_context(patch.object(executor, "send_webhook", side_effect=fake_webhook))
            stack.enter_context(patch.object(executor, "load_df_sorted", return_value=Mock()))
            clear_position_slot = stack.enter_context(patch.object(executor, "_clear_position_slot"))
            stack.enter_context(patch.object(executor.exits_flow, "ensure_exits", side_effect=fake_ensure))
            stack.enter_context(patch.object(executor.binance_api, "check_order_status", status_mock))
            stack.enter_context(patch.object(executor.binance_api, "cancel_order", cancel_mock))
            stack.enter_context(patch.object(executor.binance_api, "_planb_exec_price", side_effect=fake_planb_price))
            stack.enter_context(patch.object(executor, "_planb_market_allowed", return_value=planb_allowed))
            stack.enter_context(patch.object(executor.binance_api, "place_spot_market", side_effect=fake_market))
            try:
                executor.main()
            except StopIteration:
                pass

        return SimpleNamespace(
            order=order,
            saves=saves,
            events=events,
            webhooks=webhooks,
            tail_calls=tail_calls,
            sleep_calls=sleep_calls["n"],
            check_order_status=status_mock,
            cancel_order=cancel_mock,
            clear_position_slot=clear_position_slot,
        )

    def _event_names(self, harness):
        return [event for event, _ in harness.events]

    def _order_names(self, harness):
        return [item[0] for item in harness.order]

    def test_poll_throttle_noop_does_not_poll_or_save(self):
        st = {"position": _pending_position(last_poll_s=2000.0, opened_s=950.0)}

        h = self._run_one_pending_cycle(st)

        h.check_order_status.assert_not_called()
        self.assertEqual(h.saves, [])
        self.assertEqual(len(h.tail_calls), 2)
        self.assertNotIn("LIVE_POLL_ERROR", self._event_names(h))

    def test_due_poll_saves_last_poll_before_status_handling(self):
        st = {"position": _pending_position(opened_s=950.0)}

        h = self._run_one_pending_cycle(st, check_status={"status": "NEW", "executedQty": "0"})

        h.check_order_status.assert_called_once_with("BTCUSDC", 100)
        self.assertEqual(h.saves[0]["position"]["last_poll_s"], 1000.0)
        self.assertEqual(h.saves[0]["position"]["status"], "PENDING")
        self.assertEqual(len(h.saves), 1)

    def test_filled_path_saves_logs_margin_and_places_exits(self):
        st = {"position": _pending_position(opened_s=950.0, orders={})}

        h = self._run_one_pending_cycle(
            st,
            check_status={"status": "FILLED", "executedQty": "0.1", "cummulativeQuoteQty": "5000"},
        )

        self.assertEqual(st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(st["position"]["entry_actual"], 50000.0)
        self.assertEqual(st["position"]["order_id"], 100)
        self.assertEqual(h.saves[0]["position"]["status"], "PENDING")
        self.assertEqual(h.saves[1]["position"]["status"], "OPEN_FILLED")
        self.assertIn("FILLED", self._event_names(h))
        self.assertEqual(h.webhooks[-1]["event"], "FILLED")
        self.assertIn("margin_after", self._order_names(h))
        ensure = [item for item in h.order if item[0] == "ensure_exits"][0]
        self.assertIs(ensure[1][0], st)
        self.assertIs(ensure[1][1], st["position"])
        self.assertEqual(ensure[2], {"reason": "filled", "best_effort": True})
        self.assertLess(self._order_names(h).index("save"), self._order_names(h).index("ensure_exits"))
        self.assertEqual(len(h.tail_calls), 2)

    def test_terminal_entry_status_clears_slot_and_logs_entry_done(self):
        for status in ("CANCELED", "REJECTED", "EXPIRED"):
            with self.subTest(status=status):
                st = {"position": _pending_position(opened_s=950.0)}
                h = self._run_one_pending_cycle(st, check_status={"status": status, "executedQty": "0"})

                h.clear_position_slot.assert_called_once_with(
                    st,
                    f"ENTRY_{status}",
                    order_id=100,
                    status=status,
                )
                self.assertIn("ENTRY_DONE", self._event_names(h))
                self.assertNotIn("place_market", self._order_names(h))

    def test_opened_s_initialization_saves_without_timeout_actions(self):
        st = {"position": _pending_position(opened_s=0.0, last_poll_s=2000.0)}

        h = self._run_one_pending_cycle(st)

        self.assertEqual(st["position"]["opened_s"], 1000.0)
        self.assertEqual(h.saves[0]["position"]["opened_s"], 1000.0)
        h.cancel_order.assert_not_called()
        self.assertNotIn("place_market", self._order_names(h))
        h.clear_position_slot.assert_not_called()

    def test_timeout_not_reached_does_not_cancel_market_or_clear(self):
        st = {"position": _pending_position(opened_s=950.0, last_poll_s=2000.0)}

        h = self._run_one_pending_cycle(st)

        h.cancel_order.assert_not_called()
        self.assertNotIn("place_market", self._order_names(h))
        h.clear_position_slot.assert_not_called()

    def test_timeout_throttle_continues_without_plan_b_actions(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0, planb_next_action_s=2000.0)}

        h = self._run_one_pending_cycle(st)

        h.cancel_order.assert_not_called()
        self.assertNotIn("place_market", self._order_names(h))
        h.clear_position_slot.assert_not_called()
        self.assertEqual(len(h.tail_calls), 1)
        self.assertEqual(h.sleep_calls, 2)

    def test_timeout_partial_fill_transitions_and_uses_try_now_exits(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0, orders={})}

        h = self._run_one_pending_cycle(
            st,
            check_status={"status": "PARTIALLY_FILLED", "executedQty": "0.04", "cummulativeQuoteQty": "2000"},
        )

        h.cancel_order.assert_called_once_with("BTCUSDC", 100)
        self.assertEqual(st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(st["position"]["entry_actual"], 50000.0)
        self.assertIn("ENTRY_TIMEOUT_PARTIAL_FILLED", self._event_names(h))
        self.assertEqual(h.webhooks[-1]["event"], "ENTRY_TIMEOUT_PARTIAL_FILLED")
        self.assertIn("margin_after", self._order_names(h))
        ensure = [item for item in h.order if item[0] == "ensure_exits"][0]
        self.assertEqual(ensure[2], {"reason": "try_now", "best_effort": True, "save_on_fail": True})

    def test_late_fill_after_cancel_transitions_and_does_not_clear(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0, orders={})}
        calls = {"n": 0}

        def fake_status(_symbol, _oid):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "NEW", "executedQty": "0"}
            return {"status": "FILLED", "executedQty": "0.05", "cummulativeQuoteQty": "2500"}

        h = self._run_one_pending_cycle(st, check_status=fake_status)

        h.cancel_order.assert_called_once_with("BTCUSDC", 100)
        self.assertEqual(st["position"]["status"], "OPEN_FILLED")
        self.assertIn("ENTRY_TIMEOUT_LATE_FILL", self._event_names(h))
        self.assertIn("margin_after", self._order_names(h))
        self.assertIn("ensure_exits", self._order_names(h))
        h.clear_position_slot.assert_not_called()

    def test_wait_cancel_sets_next_action_and_skips_market(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}

        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "NEW", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses))

        self.assertEqual(st["position"]["planb_next_action_s"], 1010.0)
        self.assertIn("ENTRY_TIMEOUT_WAIT_CANCEL", self._event_names(h))
        self.assertNotIn("place_market", self._order_names(h))
        self.assertEqual(len(h.tail_calls), 1)

    def test_limit_only_timeout_clears_without_market_fallback(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses), entry_mode="LIMIT_ONLY")

        h.clear_position_slot.assert_called_once_with(st, "ENTRY_TIMEOUT", order_id=100, fallback="NONE")
        self.assertNotIn("place_market", self._order_names(h))
        self.assertIn("ENTRY_TIMEOUT", self._event_names(h))

    def test_plan_b_price_error_with_required_price_aborts_without_market(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(
            st,
            check_status=lambda *_: next(statuses),
            planb_price=None,
            planb_price_error=RuntimeError("book down"),
        )

        self.assertIn("PLANB_PRICE_ERROR", self._event_names(h))
        h.clear_position_slot.assert_called_once_with(
            st,
            "ENTRY_TIMEOUT_ABORT",
            order_id=100,
            fallback="ABORT_NO_PRICE",
        )
        self.assertNotIn("place_market", self._order_names(h))

    def test_plan_b_price_not_required_proceeds_to_market(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
            {"status": "NEW", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(
            st,
            check_status=lambda *_: next(statuses),
            planb_price=None,
            planb_require_price=False,
            market_order={"orderId": 200},
        )

        self.assertIn("place_market", self._order_names(h))
        h.clear_position_slot.assert_not_called()
        self.assertEqual(st["position"]["order_id"], 200)
        self.assertEqual(st["position"]["status"], "PENDING")

    def test_plan_b_denied_aborts_without_market(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(
            st,
            check_status=lambda *_: next(statuses),
            planb_allowed=(False, "TOO_FAR", {"dev": 1.23}),
        )

        h.clear_position_slot.assert_called_once_with(
            st,
            "ENTRY_TIMEOUT_ABORT",
            order_id=100,
            fallback="ABORT_TOO_FAR",
            dev=1.23,
        )
        self.assertNotIn("place_market", self._order_names(h))

    def test_plan_b_allowed_calls_margin_before_before_market_order(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
            {"status": "NEW", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses))

        names = self._order_names(h)
        self.assertLess(names.index("margin_before"), names.index("place_market"))
        margin_before = [item for item in h.order if item[0] == "margin_before"][0]
        self.assertEqual(margin_before[1][1:4], ("BTCUSDC", "BUY", 0.1))
        self.assertEqual(margin_before[2], {"plan": {"trade_key": "EX_EN_ORIGINAL"}})

    def test_market_fallback_error_clears_position(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(
            st,
            check_status=lambda *_: next(statuses),
            market_error=RuntimeError("market failed"),
        )

        h.clear_position_slot.assert_called_once_with(
            st,
            "ENTRY_TIMEOUT_MARKET_ERROR",
            order_id=100,
            error="market failed",
        )
        self.assertIn("ENTRY_TIMEOUT_MARKET_ERROR", self._event_names(h))

    def test_market_fallback_no_order_id_clears_position(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0)}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses), market_order={})

        h.clear_position_slot.assert_called_once_with(st, "ENTRY_TIMEOUT_MARKET_NO_OID", order_id=100)
        self.assertIn("ENTRY_TIMEOUT_MARKET_NO_OID", self._event_names(h))

    def test_market_fallback_filled_rewrites_order_and_places_exits(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0, orders={})}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
            {"status": "FILLED", "executedQty": "0.1", "cummulativeQuoteQty": "5000"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses), market_order={"orderId": 200})

        self.assertEqual(st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(st["position"]["order_id"], 200)
        self.assertEqual(st["position"]["entry_actual"], 50000.0)
        self.assertEqual(st["position"]["opened_s"], 1000.0)
        self.assertIn("margin_after", self._order_names(h))
        self.assertIn("ensure_exits", self._order_names(h))
        self.assertIn("ENTRY_TIMEOUT", self._event_names(h))

    def test_market_fallback_not_filled_keeps_pending_without_exits(self):
        st = {"position": _pending_position(opened_s=1.0, last_poll_s=2000.0, orders={})}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
            {"status": "NEW", "executedQty": "0"},
        ])

        h = self._run_one_pending_cycle(st, check_status=lambda *_: next(statuses), market_order={"orderId": 200})

        self.assertEqual(st["position"]["status"], "PENDING")
        self.assertEqual(st["position"]["order_id"], 200)
        self.assertIn("save", self._order_names(h))
        self.assertNotIn("ensure_exits", self._order_names(h))

    def test_outer_exception_logs_live_poll_error_and_loop_continues(self):
        st = {"position": _pending_position(opened_s=950.0)}

        h = self._run_one_pending_cycle(st, check_status=RuntimeError("status down"))

        self.assertIn("LIVE_POLL_ERROR", self._event_names(h))
        self.assertEqual(len(h.tail_calls), 2)


if __name__ == "__main__":
    unittest.main()
