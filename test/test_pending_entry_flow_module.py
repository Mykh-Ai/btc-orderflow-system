import ast
import importlib
import inspect
import unittest
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch


executor = importlib.import_module("executor")
pending_entry_flow = importlib.import_module("executor_mod.pending_entry_flow")


def _position(**overrides):
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


class TestPendingEntryFlowModule(unittest.TestCase):
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

    def test_module_has_no_forbidden_imports(self):
        tree = ast.parse(inspect.getsource(pending_entry_flow))
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
        self.assertNotIn("load" + "_state", inspect.getsource(pending_entry_flow))

    def _run_cycle(self, st, *, now=1000.0, status_side_effect=None, extra_patches=None):
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

        with ExitStack() as stack:
            stack.enter_context(patch.object(executor, "_validate_trade_mode", return_value="spot"))
            stack.enter_context(patch.object(executor, "load" + "_state", return_value=st))
            stack.enter_context(patch.object(executor, "read_tail_lines", side_effect=fake_tail))
            stack.enter_context(patch.object(executor, "bootstrap_seen_keys_from_tail", return_value=None))
            stack.enter_context(patch.object(executor, "_preflight_margin_cross_usdc", return_value=None))
            stack.enter_context(patch.object(executor, "sync_from_binance", return_value=None))
            stack.enter_context(patch.object(executor.atexit, "register", return_value=None))
            stack.enter_context(patch.object(executor.signal, "signal", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_startup", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_shutdown", return_value=None))
            stack.enter_context(patch.object(executor.invariants, "run", return_value=None))
            stack.enter_context(patch.object(executor.time, "sleep", side_effect=fake_sleep))
            stack.enter_context(patch.object(executor, "_now_s", return_value=now))
            stack.enter_context(patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"))
            check_order_status = stack.enter_context(patch.object(executor.binance_api, "check_order_status", side_effect=status_side_effect or (lambda *_: {"status": "NEW", "executedQty": "0"})))
            save_state = stack.enter_context(patch.object(executor, "save_state"))
            log_event = stack.enter_context(patch.object(executor, "log_event"))
            send_webhook = stack.enter_context(patch.object(executor, "send_webhook"))
            clear_position_slot = stack.enter_context(patch.object(executor, "_clear_position_slot"))
            cancel_order = stack.enter_context(patch.object(executor.binance_api, "cancel_order", return_value={"status": "CANCELED"}))
            stack.enter_context(patch.object(executor.binance_api, "_planb_exec_price", return_value=50000.0))
            planb_allowed = stack.enter_context(patch.object(executor, "_planb_market_allowed", return_value=(True, "OK", {})))
            place_spot_market = stack.enter_context(patch.object(executor.binance_api, "place_spot_market", return_value={"orderId": 200}))
            margin_before = stack.enter_context(patch.object(executor.margin_guard, "on_before_entry"))
            margin_after = stack.enter_context(patch.object(executor.margin_guard, "on_after_entry_opened"))
            ensure_exits = stack.enter_context(patch.object(executor.exits_flow, "ensure_exits", return_value=True))
            stack.enter_context(patch.object(executor.time, "time", return_value=1234.0))
            if extra_patches:
                for patcher in extra_patches:
                    stack.enter_context(patcher)
            try:
                executor.main()
            except StopIteration:
                pass
        return SimpleNamespace(
            tail_calls=tail_calls,
            check_order_status=check_order_status,
            save_state=save_state,
            log_event=log_event,
            send_webhook=send_webhook,
            clear_position_slot=clear_position_slot,
            cancel_order=cancel_order,
            planb_allowed=planb_allowed,
            place_spot_market=place_spot_market,
            margin_before=margin_before,
            margin_after=margin_after,
            ensure_exits=ensure_exits,
        )

    def test_call_site_uses_patched_status_save_log_webhook_and_exits(self):
        st = {"position": _position(orders={})}

        h = self._run_cycle(
            st,
            status_side_effect=lambda *_: {"status": "FILLED", "executedQty": "0.1", "cummulativeQuoteQty": "5000"},
        )

        h.check_order_status.assert_called_once_with("BTCUSDC", 100)
        h.save_state.assert_called()
        h.log_event.assert_any_call("FILLED", mode="live", order_id=100, executedQty="0.1")
        self.assertEqual(h.send_webhook.call_args_list[-1].args[0]["event"], "FILLED")
        h.ensure_exits.assert_called_once_with(st, st["position"], reason="filled", best_effort=True)

    def test_call_site_uses_patched_cancel_market_planb_and_margin_hooks(self):
        st = {"position": _position(opened_s=1.0, last_poll_s=2000.0, orders={})}
        statuses = iter([
            {"status": "NEW", "executedQty": "0"},
            {"status": "CANCELED", "executedQty": "0"},
            {"status": "FILLED", "executedQty": "0.1", "cummulativeQuoteQty": "5000"},
        ])

        h = self._run_cycle(st, status_side_effect=lambda *_: next(statuses))

        h.cancel_order.assert_called_once_with("BTCUSDC", 100)
        h.planb_allowed.assert_called_once()
        h.margin_before.assert_called_once()
        h.place_spot_market.assert_called_once_with("BTCUSDC", "BUY", 0.1, client_id="EX_EN_MKT_1234")
        h.margin_after.assert_called_once()
        h.ensure_exits.assert_called_once()

    def test_call_site_uses_patched_clear_position_slot(self):
        st = {"position": _position()}

        h = self._run_cycle(
            st,
            status_side_effect=lambda *_: {"status": "CANCELED", "executedQty": "0"},
        )

        h.clear_position_slot.assert_called_once_with(st, "ENTRY_CANCELED", order_id=100, status="CANCELED")

    def test_continue_signal_skips_event_ingestion_for_that_cycle(self):
        st = {"position": _position()}
        tail_calls = []
        sleep_calls = {"n": 0}

        def fake_sleep(_sec):
            sleep_calls["n"] += 1
            if sleep_calls["n"] > 1:
                raise StopIteration

        def fake_tail(*args, **kwargs):
            tail_calls.append((args, kwargs))
            if len(tail_calls) > 1:
                raise AssertionError("event ingestion should be skipped")
            return []

        with patch.object(executor, "_validate_trade_mode", return_value="spot"), \
             patch.object(executor, "load" + "_state", return_value=st), \
             patch.object(executor, "read_tail_lines", side_effect=fake_tail), \
             patch.object(executor, "bootstrap_seen_keys_from_tail", return_value=None), \
             patch.object(executor, "_preflight_margin_cross_usdc", return_value=None), \
             patch.object(executor, "sync_from_binance", return_value=None), \
             patch.object(executor.atexit, "register", return_value=None), \
             patch.object(executor.signal, "signal", return_value=None), \
             patch.object(executor.margin_guard, "on_startup", return_value=None), \
             patch.object(executor.time, "sleep", side_effect=fake_sleep), \
             patch.object(executor, "_now_s", return_value=1000.0), \
             patch.object(executor, "log_event"), \
             patch.object(executor.pending_entry_flow, "handle_pending_position", return_value=True) as handle_pending:
            try:
                executor.main()
            except StopIteration:
                pass

        handle_pending.assert_called_once()
        self.assertEqual(len(tail_calls), 1)
        self.assertEqual(sleep_calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
