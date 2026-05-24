import ast
import importlib
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from executor_mod import open_filled_retry, order_utils


executor = importlib.import_module("executor")


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


def _import_references(module):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    refs = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            refs.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                refs.add(node.module)
                refs.update(f"{node.module}.{alias.name}" for alias in node.names)
            refs.update(alias.name for alias in node.names)
    return refs


class TestExtractedModulePurity(unittest.TestCase):
    def _forbidden_runtime_imports(self):
        prefix = "executor" + "_mod."
        return {
            "executor",
            prefix + "binance" + "_api",
            prefix + "notifications",
            prefix + "state" + "_store",
            prefix + "margin" + "_guard",
            prefix + "trade" + "_execution" + "_snapshot",
            prefix + "trade" + "_close" + "_summary",
            prefix + "trade" + "_outcome" + "_archive",
            "load" + "_state",
        }

    def test_order_utils_has_no_runtime_imports(self):
        refs = _import_references(order_utils)

        self.assertFalse(refs & self._forbidden_runtime_imports())

    def test_open_filled_retry_has_no_runtime_imports_or_captured_state(self):
        refs = _import_references(open_filled_retry)

        self.assertFalse(refs & self._forbidden_runtime_imports())
        self.assertFalse(hasattr(open_filled_retry, "ENV"))
        self.assertFalse(hasattr(open_filled_retry, "save_state"))

    def test_open_filled_retry_uses_explicit_dependencies(self):
        env = {
            "EXITS_RETRY_EVERY_SEC": 15,
            "FAILSAFE_FLATTEN": True,
            "FAILSAFE_EXITS_MAX_TRIES": 1,
            "FAILSAFE_EXITS_GRACE_SEC": 0,
            "SYMBOL": "BTCUSDC",
        }
        pos = _base_open_filled_pos()
        st = {"position": pos}
        calls = []

        def save_state_fn(saved_st):
            calls.append(("save", saved_st))

        def ensure_exits_fn(*args, **kwargs):
            calls.append(("ensure", args, kwargs))
            return False

        def flatten_market_fn(*args, **kwargs):
            calls.append(("flatten", args, kwargs))
            return {"ok": True}

        def clear_position_slot_fn(*args, **kwargs):
            calls.append(("clear", args, kwargs))

        open_filled_retry.handle_open_filled_exits_retry(
            st,
            env=env,
            save_state_fn=save_state_fn,
            ensure_exits_fn=ensure_exits_fn,
            flatten_market_fn=flatten_market_fn,
            clear_position_slot_fn=clear_position_slot_fn,
            now_fn=lambda: 1000.0,
            time_fn=lambda: 1234.0,
        )

        self.assertEqual([call[0] for call in calls], ["save", "ensure", "flatten", "clear"])
        self.assertEqual(calls[2][1], ("BTCUSDC", "LONG", 0.25))
        self.assertEqual(calls[2][2], {"client_id": "EX_FLAT_1234"})
        self.assertEqual(calls[3][1], (st, "FAILSAFE_FLATTEN"))
        self.assertEqual(calls[3][2], {"tries": 1})


class TestExecutorWrapperCompatibility(unittest.TestCase):
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

    def test_wrapper_uses_patched_save_state_and_ensure_exits(self):
        self._set_retry_env(retry_every=15, failsafe=True, max_tries=1, grace=0)
        pos = _base_open_filled_pos()
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=True) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0):
            executor.handle_open_filled_exits_retry(st)

        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=1)
        flatten_market.assert_not_called()
        clear_position_slot.assert_not_called()

    def test_wrapper_uses_patched_flatten_market_and_clear_position_slot(self):
        self._set_retry_env(
            retry_every=15,
            failsafe=True,
            max_tries=1,
            grace=0,
            symbol="ETHUSDC",
        )
        pos = _base_open_filled_pos(side="SHORT", qty="0.75")
        st = {"position": pos}

        with patch.object(executor, "save_state") as save_state, \
             patch.object(executor.exits_flow, "ensure_exits", return_value=False) as ensure_exits, \
             patch.object(executor.binance_api, "flatten_market") as flatten_market, \
             patch.object(executor, "_clear_position_slot") as clear_position_slot, \
             patch.object(executor, "_now_s", return_value=1000.0), \
             patch.object(executor.time, "time", return_value=1234.0):
            executor.handle_open_filled_exits_retry(st)

        save_state.assert_called_once_with(st)
        ensure_exits.assert_called_once_with(st, pos, reason="retry", best_effort=True, attempt=1)
        flatten_market.assert_called_once_with("ETHUSDC", "SHORT", 0.75, client_id="EX_FLAT_1234")
        clear_position_slot.assert_called_once_with(st, "FAILSAFE_FLATTEN", tries=1)


if __name__ == "__main__":
    unittest.main()
