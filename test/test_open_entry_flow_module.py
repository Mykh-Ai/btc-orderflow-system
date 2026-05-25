import ast
import importlib
import inspect
import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch


executor = importlib.import_module("executor")
open_entry_flow = importlib.import_module("executor_mod.open_entry_flow")


class _Frame:
    empty = False

    def __init__(self, rows=3):
        self._rows = rows

    def __len__(self):
        return self._rows


def _env(entry_mode="LIMIT_THEN_MARKET"):
    return {
        "MAX_PEAK_AGE_SEC": 0,
        "LOCK_SEC": 15,
        "SYMBOL": "BTCUSDC",
        "TICK_SIZE": Decimal("0.1"),
        "QTY_USD": 50.0,
        "ENTRY_MODE": entry_mode,
    }


def _evt(**overrides):
    evt = {
        "ts": None,
        "kind": "long",
        "source": "DeltaScout",
        "action": "PEAK",
        "delta": 50,
        "vol": 60,
        "imb": 0.6,
        "price": 100.0,
        "vwap": 99.5,
        "poc": 99.0,
    }
    evt.update(overrides)
    return evt


class _Api:
    def __init__(self, *, calls=None, market_order=None, limit_order=None):
        self.calls = calls if calls is not None else []
        self.market_order = market_order if market_order is not None else {"orderId": 200, "executedQty": "0.5"}
        self.limit_order = limit_order if limit_order is not None else {"orderId": "100"}

    def place_spot_market(self, *args, **kwargs):
        self.calls.append(("place_market", args, deepcopy(kwargs)))
        return self.market_order

    def place_spot_limit(self, *args, **kwargs):
        self.calls.append(("place_limit", args, deepcopy(kwargs)))
        return self.limit_order


class TestOpenEntryFlowModule(unittest.TestCase):
    def test_module_has_no_forbidden_imports(self):
        tree = ast.parse(inspect.getsource(open_entry_flow))
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
        self.assertNotIn("load" + "_state", inspect.getsource(open_entry_flow))

    def _direct_call(self, *, entry_mode="LIMIT_THEN_MARKET", market_order=None, limit_order=None, exits_return=True):
        st = {"position": None, "meta": {}}
        calls = []
        api = _Api(calls=calls, market_order=market_order, limit_order=limit_order)
        saves = []
        logs = []
        webhooks = []

        def save(state):
            saves.append(deepcopy(state))
            calls.append(("save", deepcopy(state)))

        def log_event(event, **kwargs):
            logs.append((event, deepcopy(kwargs)))
            calls.append(("log", event, deepcopy(kwargs)))

        def send_webhook(payload):
            webhooks.append(deepcopy(payload))
            calls.append(("webhook", deepcopy(payload)))

        def margin_before(*args, **kwargs):
            calls.append(("margin_before", args, deepcopy(kwargs)))

        def margin_after(*args, **kwargs):
            calls.append(("margin_after", args, deepcopy(kwargs)))

        def baseline(*args, **kwargs):
            calls.append(("baseline", args, deepcopy(kwargs)))
            return {"trade_key": "EX_EN_1234", "symbol": "BTCUSDC", "trade_mode": "spot"}

        def ensure(*args, **kwargs):
            calls.append(("ensure_exits", args, deepcopy(kwargs)))
            args[1]["orders"] = {"sl": 501}
            return exits_return

        def llm(*args, **kwargs):
            calls.append(("llm", args, deepcopy(kwargs)))

        open_entry_flow.handle_open_entry_event(
            st,
            _evt(),
            env=_env(entry_mode),
            binance_api=api,
            save_state_fn=save,
            log_event_fn=log_event,
            send_webhook_fn=send_webhook,
            sync_from_binance_fn=lambda state: calls.append(("sync", deepcopy(state))),
            locked_fn=lambda _state: False,
            in_cooldown_fn=lambda _state: False,
            has_open_position_fn=lambda _state: False,
            now_fn=lambda: 1000.0,
            iso_utc_fn=lambda: "2026-01-01T00:00:05Z",
            time_fn=lambda: 1234.0,
            dt_utc_fn=lambda _value: None,
            to_datetime_fn=lambda *_args, **_kwargs: None,
            load_df_sorted_fn=lambda: _Frame(),
            locate_index_by_ts_fn=lambda *_args: 0,
            build_entry_price_fn=lambda kind, price: 101.0,
            swing_stop_far_fn=lambda frame, idx, side, entry: 90.0,
            compute_tps_fn=lambda entry, sl, side: [111.0, 121.0],
            get_usdt_usdc_k_fn=lambda: 1.0,
            floor_to_step_fn=lambda value, step: float(value),
            ceil_to_step_fn=lambda value, step: float(value),
            notional_to_qty_fn=lambda entry, usd: 0.5,
            validate_qty_fn=lambda qty, entry: True,
            fmt_price_fn=lambda value: str(value),
            avg_fill_price_fn=lambda order: 100.0,
            oid_int_fn=lambda value: int(value),
            margin_before_entry_fn=margin_before,
            margin_after_entry_opened_fn=margin_after,
            baseline_take_snapshot_fn=baseline,
            ensure_exits_fn=ensure,
            llm_pretrade_fn=llm,
        )
        return SimpleNamespace(st=st, api=api, calls=calls, saves=saves, logs=logs, webhooks=webhooks)

    def test_direct_market_only_open_filled_path(self):
        h = self._direct_call(entry_mode="MARKET_ONLY", market_order={"orderId": 200, "executedQty": "0.5"})
        names = [call[0] for call in h.calls]

        self.assertLess(names.index("margin_before"), names.index("place_market"))
        self.assertEqual(h.st["position"]["status"], "OPEN_FILLED")
        self.assertEqual(h.st["position"]["entry_actual"], 100.0)
        self.assertIn("margin_after", names)
        self.assertIn("ensure_exits", names)
        self.assertIn("llm", names)
        self.assertEqual(h.webhooks[-1]["event"], "OPEN")

    def test_direct_limit_path_keeps_pending_without_immediate_exits(self):
        h = self._direct_call(entry_mode="LIMIT_THEN_MARKET", limit_order={"orderId": "100"})
        names = [call[0] for call in h.calls]

        self.assertLess(names.index("margin_before"), names.index("place_limit"))
        self.assertEqual(h.st["position"]["status"], "PENDING")
        self.assertIsNone(h.st["position"]["entry_actual"])
        self.assertNotIn("margin_after", names)
        self.assertNotIn("ensure_exits", names)
        self.assertNotIn("llm", names)

    def test_executor_call_site_uses_live_patched_dependencies(self):
        st = {"position": None, "meta": {}}
        captured = {}
        tail_calls = []

        def fake_tail(*args, **kwargs):
            tail_calls.append((args, kwargs))
            if len(tail_calls) == 1:
                return []
            return [json.dumps({"ts": "2026-01-01T00:00:00Z", "action": "PEAK", "kind": "long", "source": "DeltaScout", "price": 100.0})]

        def fake_handler(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            captured["market_is_live"] = kwargs["binance_api"].place_spot_market is market
            captured["limit_is_live"] = kwargs["binance_api"].place_spot_limit is limit
            raise StopIteration

        with ExitStack() as stack:
            stack.enter_context(patch.object(executor, "_validate_trade_mode", return_value="spot"))
            stack.enter_context(patch.object(executor, "load" + "_state", return_value=st))
            stack.enter_context(patch.object(executor, "read_tail_lines", side_effect=fake_tail))
            stack.enter_context(patch.object(executor, "bootstrap_seen_keys_from_tail", return_value=None))
            stack.enter_context(patch.object(executor, "_preflight_margin_cross_usdc", return_value=None))
            sync = stack.enter_context(patch.object(executor, "sync_from_binance"))
            stack.enter_context(patch.object(executor.atexit, "register", return_value=None))
            stack.enter_context(patch.object(executor.signal, "signal", return_value=None))
            stack.enter_context(patch.object(executor.margin_guard, "on_startup", return_value=None))
            stack.enter_context(patch.object(executor.invariants, "run", return_value=None))
            stack.enter_context(patch.object(executor.time, "sleep", return_value=None))
            now = stack.enter_context(patch.object(executor, "_now_s", return_value=1000.0))
            iso = stack.enter_context(patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:05Z"))
            time_fn = stack.enter_context(patch.object(executor.time, "time", return_value=1234.0))
            save = stack.enter_context(patch.object(executor, "save_state"))
            log = stack.enter_context(patch.object(executor, "log_event"))
            webhook = stack.enter_context(patch.object(executor, "send_webhook"))
            locked = stack.enter_context(patch.object(executor, "locked", return_value=False))
            cooldown = stack.enter_context(patch.object(executor, "in_cooldown", return_value=False))
            has_open = stack.enter_context(patch.object(executor, "has_open_position", return_value=False))
            dt_utc = stack.enter_context(patch.object(executor.event_dedup, "_dt_utc", return_value=None))
            to_datetime = stack.enter_context(patch.object(executor.pd, "to_datetime"))
            load_df = stack.enter_context(patch.object(executor, "load_df_sorted"))
            locate = stack.enter_context(patch.object(executor, "locate_index_by_ts"))
            build = stack.enter_context(patch.object(executor, "build_entry_price"))
            swing = stack.enter_context(patch.object(executor, "swing_stop_far"))
            tps = stack.enter_context(patch.object(executor, "compute_tps"))
            k = stack.enter_context(patch.object(executor, "get_usdt_usdc_k"))
            floor = stack.enter_context(patch.object(executor, "floor_to_step"))
            ceil = stack.enter_context(patch.object(executor, "ceil_to_step"))
            notional = stack.enter_context(patch.object(executor, "notional_to_qty"))
            validate = stack.enter_context(patch.object(executor, "validate_qty"))
            fmt_price = stack.enter_context(patch.object(executor, "fmt_price"))
            avg = stack.enter_context(patch.object(executor, "_avg_fill_price"))
            oid = stack.enter_context(patch.object(executor, "_oid_int"))
            market = stack.enter_context(patch.object(executor.binance_api, "place_spot_market"))
            limit = stack.enter_context(patch.object(executor.binance_api, "place_spot_limit"))
            margin_before = stack.enter_context(patch.object(executor.margin_guard, "on_before_entry"))
            margin_after = stack.enter_context(patch.object(executor.margin_guard, "on_after_entry_opened"))
            baseline = stack.enter_context(patch.object(executor.baseline_policy, "take_snapshot"))
            ensure = stack.enter_context(patch.object(executor.exits_flow, "ensure_exits"))
            llm = stack.enter_context(patch.object(executor.llm_trade_judge, "maybe_record_llm_pretrade_judge"))
            stack.enter_context(patch.object(executor.open_entry_flow, "handle_open_entry_event", side_effect=fake_handler))

            try:
                executor.main()
            except StopIteration:
                pass

        kwargs = captured["kwargs"]
        self.assertIs(captured["args"][0], st)
        self.assertEqual(captured["args"][1]["action"], "PEAK")
        expected = {
            "save_state_fn": save,
            "log_event_fn": log,
            "send_webhook_fn": webhook,
            "sync_from_binance_fn": sync,
            "locked_fn": locked,
            "in_cooldown_fn": cooldown,
            "has_open_position_fn": has_open,
            "now_fn": now,
            "iso_utc_fn": iso,
            "time_fn": time_fn,
            "dt_utc_fn": dt_utc,
            "to_datetime_fn": to_datetime,
            "load_df_sorted_fn": load_df,
            "locate_index_by_ts_fn": locate,
            "build_entry_price_fn": build,
            "swing_stop_far_fn": swing,
            "compute_tps_fn": tps,
            "get_usdt_usdc_k_fn": k,
            "floor_to_step_fn": floor,
            "ceil_to_step_fn": ceil,
            "notional_to_qty_fn": notional,
            "validate_qty_fn": validate,
            "fmt_price_fn": fmt_price,
            "avg_fill_price_fn": avg,
            "oid_int_fn": oid,
            "margin_before_entry_fn": margin_before,
            "margin_after_entry_opened_fn": margin_after,
            "baseline_take_snapshot_fn": baseline,
            "ensure_exits_fn": ensure,
            "llm_pretrade_fn": llm,
        }
        for key, value in expected.items():
            self.assertIs(kwargs[key], value)
        self.assertIs(kwargs["env"], executor.ENV)
        self.assertIs(kwargs["binance_api"], executor.binance_api)
        self.assertTrue(captured["market_is_live"])
        self.assertTrue(captured["limit_is_live"])

    def test_main_still_owns_event_iteration_and_tail_dedup(self):
        src = inspect.getsource(executor.main)

        self.assertIn("for _, evt in new_events:", src)
        self.assertIn("read_tail_lines", src)
        self.assertIn("stable_event_key", src)
        self.assertIn("seen_keys", src)
        self.assertIn("open_entry_flow.handle_open_entry_event", src)
        self.assertNotIn("runtime_loop", src)


if __name__ == "__main__":
    unittest.main()
