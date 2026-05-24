import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import executor


def _base_open_filled_pos(**overrides):
    pos = {
        "mode": "live",
        "status": "OPEN_FILLED",
        "side": "LONG",
        "qty": 0.25,
        "prices": {"entry": 100.0, "tp1": 101.0, "tp2": 102.0, "sl": 99.0},
        "orders": {},
    }
    pos.update(overrides)
    return pos


class TestOrderUtilityHelpers(unittest.TestCase):
    def test_oid_int_returns_int_for_numeric_string_and_int_values(self):
        self.assertEqual(executor._oid_int("123"), 123)
        self.assertEqual(executor._oid_int(456), 456)

    def test_oid_int_returns_none_for_none(self):
        self.assertIsNone(executor._oid_int(None))

    def test_oid_int_returns_none_for_invalid_values(self):
        self.assertIsNone(executor._oid_int("not-an-order-id"))

    def test_oid_int_preserves_broad_exception_behavior(self):
        class RaisesOnInt:
            def __int__(self):
                raise RuntimeError("boom")

        self.assertIsNone(executor._oid_int(RaisesOnInt()))

    def test_avg_fill_price_uses_cummulative_quote_qty_spelling(self):
        order = {"executedQty": "2", "cummulativeQuoteQty": "10"}

        self.assertEqual(executor._avg_fill_price(order), 5.0)

    def test_avg_fill_price_uses_cumulative_quote_qty_fallback_spelling(self):
        order = {"executedQty": "4", "cumulativeQuoteQty": "12"}

        self.assertEqual(executor._avg_fill_price(order), 3.0)

    def test_avg_fill_price_returns_none_if_executed_qty_is_zero(self):
        order = {"executedQty": "0", "cummulativeQuoteQty": "10"}

        self.assertIsNone(executor._avg_fill_price(order))

    def test_avg_fill_price_returns_none_if_quote_qty_is_zero_or_missing(self):
        self.assertIsNone(executor._avg_fill_price({"executedQty": "2", "cummulativeQuoteQty": "0"}))
        self.assertIsNone(executor._avg_fill_price({"executedQty": "2"}))

    def test_avg_fill_price_returns_none_on_malformed_payload_without_raising(self):
        self.assertIsNone(executor._avg_fill_price({"executedQty": "bad", "cummulativeQuoteQty": "10"}))
        self.assertIsNone(executor._avg_fill_price(None))


class TestOpenFilledExitsRetry(unittest.TestCase):
    def setUp(self):
        self.env_snapshot = deepcopy(executor.ENV)

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self.env_snapshot)

    def _set_retry_env(
        self,
        *,
        retry_every=15,
        failsafe=False,
        max_tries=5,
        grace=60,
        symbol="BTCUSDC",
    ):
        executor.ENV["EXITS_RETRY_EVERY_SEC"] = retry_every
        executor.ENV["FAILSAFE_FLATTEN"] = failsafe
        executor.ENV["FAILSAFE_EXITS_MAX_TRIES"] = max_tries
        executor.ENV["FAILSAFE_EXITS_GRACE_SEC"] = grace
        executor.ENV["SYMBOL"] = symbol

    def _assert_no_lifecycle_calls(self, save_state, ensure_exits, flatten_market, clear_position_slot):
        save_state.assert_not_called()
        ensure_exits.assert_not_called()
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_guard_noop_cases_do_not_call_lifecycle_dependencies(self):
        cases = [
            ("no position", {}),
            ("mode is not live", {"position": _base_open_filled_pos(mode="paper")}),
            ("status is not OPEN_FILLED", {"position": _base_open_filled_pos(status="OPEN")}),
            ("orders already exist", {"position": _base_open_filled_pos(orders={"sl": 1001})}),
            ("prices missing", {"position": _base_open_filled_pos(prices=None)}),
            ("next try is in the future", {"position": _base_open_filled_pos(exits_next_try_s=2000.0)}),
        ]

        self._set_retry_env()
        for name, st in cases:
            with self.subTest(name=name):
                with patch.object(executor, "save_state") as save_state, \
                     patch.object(executor.exits_flow, "ensure_exits") as ensure_exits, \
                     patch.object(executor.binance_api, "flatten_market") as flatten_market, \
                     patch.object(executor, "_clear_position_slot") as clear_position_slot, \
                     patch.object(executor, "_now_s", return_value=1000.0):
                    executor.handle_open_filled_exits_retry(st)

                self._assert_no_lifecycle_calls(
                    save_state,
                    ensure_exits,
                    flatten_market,
                    clear_position_slot,
                )

    def test_retry_sets_fields_saves_before_ensure_and_returns_on_success(self):
        self._set_retry_env(retry_every=15, failsafe=True, max_tries=1, grace=0)
        pos = _base_open_filled_pos(exits_tries=2)
        st = {"position": pos}
        events = []

        def fake_save_state(saved_st):
            events.append(("save", deepcopy(saved_st["position"])))
            self.assertIs(saved_st["position"], pos)

        def fake_ensure_exits(*_args, **_kwargs):
            events.append(("ensure", deepcopy(st["position"])))
            return True

        ensure_exits = Mock(side_effect=fake_ensure_exits)
        with patch.object(executor, "save_state", side_effect=fake_save_state) as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", ensure_exits), \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        self.assertIs(st["position"], pos)
        self.assertEqual(pos["exits_tries"], 3)
        self.assertEqual(pos["exits_first_fail_s"], 1000.0)
        self.assertEqual(pos["exits_next_try_s"], 1015.0)
        self.assertEqual([event[0] for event in events], ["save", "ensure"])
        self.assertEqual(events[0][1]["exits_tries"], 3)
        self.assertEqual(events[0][1]["exits_first_fail_s"], 1000.0)
        self.assertEqual(events[0][1]["exits_next_try_s"], 1015.0)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=3)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_retry_preserves_existing_first_fail_s(self):
        self._set_retry_env(retry_every=15)
        pos = _base_open_filled_pos(exits_tries=1, exits_first_fail_s=750.0)
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=True) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        self.assertEqual(pos["exits_tries"], 2)
        self.assertEqual(pos["exits_first_fail_s"], 750.0)
        self.assertEqual(pos["exits_next_try_s"], 1015.0)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=2)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_retry_failure_without_failsafe_keeps_open_filled_and_does_not_clear(self):
        self._set_retry_env(retry_every=15, failsafe=False)
        pos = _base_open_filled_pos()
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        self.assertEqual(st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(st["position"]["exits_tries"], 1)
        self.assertEqual(st["position"]["exits_first_fail_s"], 1000.0)
        self.assertEqual(st["position"]["exits_next_try_s"], 1015.0)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=1)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_failsafe_enabled_but_max_tries_not_reached_does_not_flatten_or_clear(self):
        self._set_retry_env(retry_every=15, failsafe=True, max_tries=3, grace=60)
        pos = _base_open_filled_pos(exits_tries=1, exits_first_fail_s=900.0)
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        self.assertEqual(pos["exits_tries"], 2)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=2)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_failsafe_enabled_but_grace_not_elapsed_does_not_flatten_or_clear(self):
        self._set_retry_env(retry_every=15, failsafe=True, max_tries=3, grace=60)
        pos = _base_open_filled_pos(exits_tries=2, exits_first_fail_s=990.0)
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        self.assertEqual(pos["exits_tries"], 3)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=3)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_failsafe_flatten_path_calls_flatten_and_clear_position_slot(self):
        self._set_retry_env(
            retry_every=15,
            failsafe=True,
            max_tries=3,
            grace=60,
            symbol="ETHUSDC",
        )
        pos = _base_open_filled_pos(exits_tries=2, exits_first_fail_s=900.0, side="SHORT", qty="0.75")
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0), \
             patch.object(executor.time, "time", return_value=1234.9):
            executor.handle_open_filled_exits_retry(st)

        self.assertEqual(pos["exits_tries"], 3)
        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=3)
        flatten_market.assert_called_once_with("ETHUSDC", "SHORT", 0.75, client_id="EX_FLAT_1234")
        clear_position_slot.assert_called_once_with(st, "FAILSAFE_FLATTEN", tries=3)

    def test_flatten_exception_is_suppressed_and_clear_position_slot_still_runs(self):
        self._set_retry_env(retry_every=15, failsafe=True, max_tries=3, grace=60)
        pos = _base_open_filled_pos(exits_tries=2, exits_first_fail_s=900.0)
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market", side_effect=RuntimeError("network")) as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0), \
             patch.object(executor.time, "time", return_value=5678.0):
            executor.handle_open_filled_exits_retry(st)

        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=3)
        flatten_market.assert_called_once_with("BTCUSDC", "LONG", 0.25, client_id="EX_FLAT_5678")
        clear_position_slot.assert_called_once_with(st, "FAILSAFE_FLATTEN", tries=3)


if __name__ == "__main__":
    unittest.main()
