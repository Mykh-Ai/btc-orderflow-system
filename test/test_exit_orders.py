import ast
import importlib
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import executor_mod.exit_orders as exit_orders
import executor_mod.risk_math as risk_math

executor = importlib.import_module("executor")


def _env(**overrides):
    env = {
        "TICK_SIZE": Decimal("0.01"),
        "QTY_STEP": Decimal("0.001"),
        "MIN_QTY": Decimal("0.001"),
        "MIN_NOTIONAL": 0.0,
        "SL_LIMIT_GAP_TICKS": 5,
    }
    env.update(overrides)
    risk_math.configure(env)
    return env


def _validate(env, side="LONG", qty=0.009, prices=None):
    if prices is None:
        prices = {"entry": 100.0, "sl": 99.0, "tp1": 102.0, "tp2": 104.0}
    return exit_orders.validate_exit_plan(
        "BTCUSDC",
        side,
        qty,
        prices,
        env=env,
        round_qty_fn=risk_math.round_qty,
        split_qty_3legs_validate_fn=risk_math.split_qty_3legs_validate,
    )


def _place(env, side="LONG", qty=0.009, prices=None, place_order_raw_fn=None, cancel_order_fn=None, log_event_fn=None):
    if prices is None:
        prices = {"entry": 100.0, "sl": 99.0, "tp1": 102.0, "tp2": 104.0}
    return exit_orders.place_exits_v15(
        "BTCUSDC",
        side,
        qty,
        prices,
        env=env,
        place_order_raw_fn=place_order_raw_fn or (lambda payload: {"orderId": 1}),
        cancel_order_fn=cancel_order_fn or (lambda symbol, order_id: {}),
        log_event_fn=log_event_fn or (lambda *a, **k: None),
        round_qty_fn=risk_math.round_qty,
        split_qty_3legs_place_fn=risk_math.split_qty_3legs_place,
        fmt_qty_fn=risk_math.fmt_qty,
        fmt_price_fn=risk_math.fmt_price,
        time_fn=lambda: 1700000000,
    )


class TestExitOrders(unittest.TestCase):
    def setUp(self):
        self._prev_risk_env = risk_math.ENV

    def tearDown(self):
        risk_math.configure(self._prev_risk_env)

    def test_validate_exit_plan_valid_long_returns_normalized_prices_and_split(self):
        env = _env()

        out = _validate(env)

        self.assertEqual(out, {
            "qty_total_r": 0.009,
            "qty1": 0.003,
            "qty2": 0.003,
            "qty3": 0.003,
            "prices": {"entry": 100.0, "sl": 99.0, "tp1": 102.0, "tp2": 104.0},
        })

    def test_validate_exit_plan_valid_short_returns_normalized_prices_and_split(self):
        env = _env()

        out = _validate(
            env,
            side="SHORT",
            prices={"entry": 100.0, "sl": 101.0, "tp1": 98.0, "tp2": 96.0},
        )

        self.assertEqual(out, {
            "qty_total_r": 0.009,
            "qty1": 0.003,
            "qty2": 0.003,
            "qty3": 0.003,
            "prices": {"entry": 100.0, "sl": 101.0, "tp1": 98.0, "tp2": 96.0},
        })

    def test_validate_exit_plan_missing_required_keys_raises(self):
        env = _env()

        with self.assertRaisesRegex(RuntimeError, "Missing price keys"):
            _validate(env, prices={"entry": 100.0, "sl": 99.0, "tp1": 102.0})

    def test_validate_exit_plan_bad_long_ordering_raises(self):
        env = _env()

        with self.assertRaisesRegex(RuntimeError, "Bad LONG price ordering"):
            _validate(env, prices={"entry": 100.0, "sl": 101.0, "tp1": 102.0, "tp2": 104.0})

    def test_validate_exit_plan_bad_short_ordering_raises(self):
        env = _env()

        with self.assertRaisesRegex(RuntimeError, "Bad SHORT price ordering"):
            _validate(env, side="SHORT", prices={"entry": 100.0, "sl": 99.0, "tp1": 98.0, "tp2": 96.0})

    def test_validate_exit_plan_off_tick_price_raises(self):
        env = _env()

        with self.assertRaisesRegex(RuntimeError, "Price not aligned to tick"):
            _validate(env, prices={"entry": 100.0, "sl": 99.005, "tp1": 102.0, "tp2": 104.0})

    def test_validate_exit_plan_min_qty_failure_raises(self):
        env = _env(MIN_QTY=Decimal("0.010"))

        with self.assertRaisesRegex(RuntimeError, "qty_total too small"):
            _validate(env)

    def test_validate_exit_plan_min_notional_failure_raises(self):
        env = _env(MIN_NOTIONAL=10.0)

        with self.assertRaisesRegex(RuntimeError, "MinNotional fail"):
            _validate(env)

    def test_place_exits_v15_emits_exact_payloads_and_split_outputs(self):
        env = _env()
        calls = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            return {"orderId": len(calls)}

        out = _place(env, place_order_raw_fn=place_order_raw)

        self.assertEqual(calls[0], {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "quantity": "0.009",
            "stopPrice": "99.00",
            "price": "98.95",
            "timeInForce": "GTC",
            "newClientOrderId": "EX_SL_1700000000",
        })
        self.assertEqual(calls[1], {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "quantity": "0.003",
            "price": "102.00",
            "newClientOrderId": "EX_TP1_1700000000",
        })
        self.assertEqual(calls[2], {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "quantity": "0.003",
            "price": "104.00",
            "newClientOrderId": "EX_TP2_1700000000",
        })
        self.assertEqual(out, {"tp1": 2, "tp2": 3, "sl": 1, "qty1": 0.003, "qty2": 0.003, "qty3": 0.003})

    def test_place_exits_v15_short_sl_limit_price_uses_buy_side_gap(self):
        env = _env()
        calls = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            return {"orderId": len(calls)}

        _place(
            env,
            side="SHORT",
            prices={"entry": 100.0, "sl": 101.0, "tp1": 98.0, "tp2": 96.0},
            place_order_raw_fn=place_order_raw,
        )

        self.assertEqual(calls[0]["side"], "BUY")
        self.assertEqual(calls[0]["stopPrice"], "101.00")
        self.assertEqual(calls[0]["price"], "101.05")

    def test_limit_maker_reject_on_tp1_creates_limit_fallback_and_logs(self):
        env = _env()
        calls = []
        events = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            if payload["type"] == "LIMIT_MAKER" and payload["newClientOrderId"].startswith("EX_TP1"):
                raise RuntimeError("Order would immediately match and take")
            return {"orderId": len(calls)}

        out = _place(env, place_order_raw_fn=place_order_raw, log_event_fn=lambda *a, **k: events.append((a, k)))

        self.assertEqual(out["tp1"], 3)
        self.assertEqual(calls[2], {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "LIMIT",
            "quantity": "0.003",
            "price": "102.00",
            "newClientOrderId": "EX_TP1_1700000000_GTC",
            "timeInForce": "GTC",
        })
        self.assertEqual(events, [(('LIMIT_MAKER_REJECT',), {"reason": "Order would immediately match and take"})])

    def test_limit_maker_reject_on_tp2_creates_limit_fallback_and_logs(self):
        env = _env()
        calls = []
        events = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            if payload["type"] == "LIMIT_MAKER" and payload["newClientOrderId"].startswith("EX_TP2"):
                raise RuntimeError('{"code":-2010,"msg":"would immediately match"}')
            return {"orderId": len(calls)}

        out = _place(env, place_order_raw_fn=place_order_raw, log_event_fn=lambda *a, **k: events.append((a, k)))

        self.assertEqual(out["tp2"], 4)
        self.assertEqual(calls[3], {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "LIMIT",
            "quantity": "0.003",
            "price": "104.00",
            "newClientOrderId": "EX_TP2_1700000000_GTC",
            "timeInForce": "GTC",
        })
        self.assertEqual(events, [(('LIMIT_MAKER_REJECT',), {"reason": '{"code":-2010,"msg":"would immediately match"}'})])

    def test_limit_maker_fallback_client_id_is_truncated_to_36_chars(self):
        calls = []
        events = []
        payload = {
            "symbol": "BTCUSDC",
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "quantity": "0.003",
            "price": "102.00",
            "newClientOrderId": "EX_TP1_123456789012345678901234567890",
        }

        def place_order_raw(payload):
            calls.append(dict(payload))
            if len(calls) == 1:
                raise RuntimeError("code: -2010")
            return {"orderId": 99}

        out = exit_orders.place_limit_maker_then_limit(
            payload,
            place_order_raw_fn=place_order_raw,
            log_event_fn=lambda *a, **k: events.append((a, k)),
        )

        self.assertEqual(out, {"orderId": 99})
        self.assertEqual(calls[1]["type"], "LIMIT")
        self.assertEqual(calls[1]["timeInForce"], "GTC")
        self.assertEqual(calls[1]["newClientOrderId"], "EX_TP1_12345678901234567890123456789")
        self.assertEqual(len(calls[1]["newClientOrderId"]), 36)

    def test_rollback_cancels_sl_when_tp1_placement_fails(self):
        env = _env()
        canceled = []

        def place_order_raw(payload):
            if payload["type"] == "STOP_LOSS_LIMIT":
                return {"orderId": 11}
            raise RuntimeError("tp1 down")

        with self.assertRaisesRegex(RuntimeError, "tp1 down"):
            _place(env, place_order_raw_fn=place_order_raw, cancel_order_fn=lambda symbol, oid: canceled.append((symbol, oid)))

        self.assertEqual(canceled, [("BTCUSDC", 11)])

    def test_rollback_cancels_sl_and_tp1_when_tp2_placement_fails(self):
        env = _env()
        canceled = []

        def place_order_raw(payload):
            if payload["type"] == "STOP_LOSS_LIMIT":
                return {"orderId": 11}
            if payload["newClientOrderId"].startswith("EX_TP1"):
                return {"orderId": 22}
            raise RuntimeError("tp2 down")

        with self.assertRaisesRegex(RuntimeError, "tp2 down"):
            _place(env, place_order_raw_fn=place_order_raw, cancel_order_fn=lambda symbol, oid: canceled.append((symbol, oid)))

        self.assertEqual(canceled, [("BTCUSDC", 11), ("BTCUSDC", 22)])

    def test_rollback_cancel_failures_are_swallowed(self):
        env = _env()
        cancel_calls = []

        def place_order_raw(payload):
            if payload["type"] == "STOP_LOSS_LIMIT":
                return {"orderId": 11}
            raise RuntimeError("tp1 down")

        def cancel_order(symbol, oid):
            cancel_calls.append((symbol, oid))
            raise RuntimeError("cancel down")

        with self.assertRaisesRegex(RuntimeError, "tp1 down"):
            _place(env, place_order_raw_fn=place_order_raw, cancel_order_fn=cancel_order)

        self.assertEqual(cancel_calls, [("BTCUSDC", 11)])

    def test_executor_place_exits_wrapper_uses_live_patched_dependency(self):
        calls = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            return {"orderId": len(calls)}

        with (
            patch.object(executor.binance_api, "place_order_raw", side_effect=place_order_raw),
            patch.object(executor.binance_api, "cancel_order", return_value={}),
            patch.object(executor, "log_event", lambda *a, **k: None),
            patch.object(executor.time, "time", return_value=1700000000),
        ):
            out = executor.place_exits_v15(
                "BTCUSDC",
                "LONG",
                0.009,
                {"entry": 100.0, "sl": 99.0, "tp1": 102.0, "tp2": 104.0},
            )

        self.assertEqual(out["sl"], 1)
        self.assertEqual(calls[0]["newClientOrderId"], "EX_SL_1700000000")

    def test_executor_limit_maker_wrapper_logs_through_live_patched_log_event(self):
        events = []
        calls = []

        def place_order_raw(payload):
            calls.append(dict(payload))
            if len(calls) == 1:
                raise RuntimeError("would immediately match")
            return {"orderId": 7}

        with (
            patch.object(executor.binance_api, "place_order_raw", side_effect=place_order_raw),
            patch.object(executor, "log_event", lambda *a, **k: events.append((a, k))),
        ):
            out = executor._place_limit_maker_then_limit({
                "symbol": "BTCUSDC",
                "side": "SELL",
                "type": "LIMIT_MAKER",
                "quantity": "0.003",
                "price": "102.00",
                "newClientOrderId": "EX_TP1_1700000000",
            })

        self.assertEqual(out, {"orderId": 7})
        self.assertEqual(events, [(('LIMIT_MAKER_REJECT',), {"reason": "would immediately match"})])

    def test_module_purity(self):
        source = Path(exit_orders.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")

        forbidden_imports = [
            "executor",
            "executor_mod." + "binance_api",
            "executor_mod." + "notifications",
            "executor_mod." + "state_store",
            "executor_mod." + "margin_guard",
            "executor_mod." + "trade_execution_snapshot",
            "executor_mod." + "trade_close_summary",
            "executor_mod." + "trade_outcome_archive",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, imported)
            self.assertNotIn(f"import {forbidden}", source)

        forbidden_terms = [
            "".join(("watch", "dog")),
            "".join(("WATCH", "DOG")),
            "".join(("Price", "Snapshot")),
            "".join(("price", "_snapshot")),
            "".join(("direct", " price")),
            "".join(("partial", " fill")),
            "".join(("PART", "IAL")),
            "".join(("sl", "ippage")),
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, source)


if __name__ == "__main__":
    unittest.main()
