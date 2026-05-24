# test/test_margin_guard.py
import unittest
from unittest.mock import Mock, patch

import executor_mod.margin_guard as mg


class FakeMarginPolicy:
    def __init__(self):
        self.borrow_calls = []
        self.repay_calls = []
        self.cleanup_calls = []
        self.cleanup_result = {
            "cleanup_status": "clean",
            "attempted_assets": [],
            "repaid_amounts": {},
            "failed_assets": [],
            "residual_debt": [],
            "binance_errors": [],
        }
        self.cleanup_error = None

    def ensure_borrow_if_needed(self, state, api, symbol, side, qty, plan):
        # record the plan passed from margin_guard
        self.borrow_calls.append(
            {
                "state": state,
                "api": api,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "plan": dict(plan),
            }
        )

    def repay_if_any(self, state, api, symbol):
        self.repay_calls.append(
            {
                "state": state,
                "api": api,
                "symbol": symbol,
            }
        )

    def cleanup_post_close_margin_debt(self, state, api, symbol, trade_key=None):
        self.cleanup_calls.append(
            {
                "state": state,
                "api": api,
                "symbol": symbol,
                "trade_key": trade_key,
            }
        )
        if self.cleanup_error:
            raise self.cleanup_error
        result = dict(self.cleanup_result)
        result["trade_key"] = trade_key
        state.setdefault("margin", {}).setdefault("post_close_debt_cleanup", {})["last_result"] = result
        return result


class FakeApi:
    def __init__(self, mid_price=100.0):
        self._mid = mid_price

    def get_mid_price(self, symbol: str) -> float:
        return float(self._mid)


def _base_env(symbol="BTCUSDC"):
    return {
        "TRADE_MODE": "margin",
        "SYMBOL": symbol,
        # your guard uses this as default for plan_use["is_isolated"]
        "MARGIN_ISOLATED": "TRUE",
        # manual mode expects NO_SIDE_EFFECT (guard logs warn otherwise)
        "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
        # optional, but nice to be explicit if your _borrow_mode reads it
        "MARGIN_BORROW_MODE": "manual",
    }


class TestMarginGuard(unittest.TestCase):
    def setUp(self):
        # fresh globals each test
        self.log = Mock()
        self.api = FakeApi(mid_price=123.45)
        self.policy = FakeMarginPolicy()

        # configure guard
        mg.configure(_base_env(), self.log, api=self.api)

        # inject policy (guard checks `margin_policy is None`)
        mg.margin_policy = self.policy

    def tearDown(self):
        # best-effort cleanup
        mg.margin_policy = None

    def test_prepare_plan_for_borrow_long_derives_quote_asset_and_amount_from_entry(self):
        """
        BUY BTCUSDC:
          borrow_asset should become USDC
          borrow_amount should become qty * entry (if entry provided)
        """
        state = {}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.01
        plan = {"trade_key": "T1", "entry": 50000}

        tk, plan_use = mg._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        self.assertEqual(tk, "T1")
        self.assertEqual(state["margin"]["active_trade_key"], "T1")
        self.assertEqual(plan_use["trade_key"], "T1")
        self.assertEqual(plan_use["borrow_asset"], "USDC")
        self.assertAlmostEqual(float(plan_use["borrow_amount"]), 0.01 * 50000.0, places=8)
        self.assertIn("is_isolated", plan_use)  # defaulted from ENV if not provided

    def test_prepare_plan_for_borrow_long_falls_back_to_mid_price_when_no_entry(self):
        """
        If plan has no entry/price and borrow_amount not set,
        _prepare_plan_for_borrow may use api_client.get_mid_price(symbol).
        """
        state = {}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.02
        plan = {"trade_key": "T2"}  # no entry/price

        tk, plan_use = mg._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        self.assertEqual(tk, "T2")
        self.assertEqual(plan_use["borrow_asset"], "USDC")
        self.assertAlmostEqual(float(plan_use["borrow_amount"]), 0.02 * 123.45, places=8)

    def test_prepare_plan_for_borrow_short_derives_base_asset_and_amount_from_qty(self):
        """
        SELL BTCUSDC:
          borrow_asset should become BTC
          borrow_amount should become qty (if not provided)
        """
        state = {}
        symbol = "BTCUSDC"
        side = "SELL"
        qty = 0.005
        plan = {"trade_key": "T3"}

        tk, plan_use = mg._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        self.assertEqual(tk, "T3")
        self.assertEqual(plan_use["borrow_asset"], "BTC")
        self.assertAlmostEqual(float(plan_use["borrow_amount"]), 0.005, places=12)

    def test_on_before_entry_passes_prepared_plan_to_policy(self):
        state = {}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.01
        plan = {"trade_key": "T10", "entry": 40000}

        # force guard to take "manual" branch no matter how _borrow_mode is implemented
        with patch.object(mg, "_borrow_mode", return_value="manual"):
            with patch.object(mg, "is_margin_mode", return_value=True):
                mg.on_before_entry(state, symbol, side, qty, plan)

        self.assertEqual(len(self.policy.borrow_calls), 1)
        call = self.policy.borrow_calls[0]
        self.assertEqual(call["symbol"], symbol)
        self.assertEqual(call["side"], side)
        self.assertAlmostEqual(float(call["qty"]), qty, places=12)

        plan_use = call["plan"]
        self.assertEqual(plan_use["trade_key"], "T10")
        self.assertEqual(plan_use["borrow_asset"], "USDC")
        self.assertAlmostEqual(float(plan_use["borrow_amount"]), 0.01 * 40000.0, places=8)

        # ensure trade_key stored for reuse by later hooks
        self.assertEqual(state["margin"]["active_trade_key"], "T10")

    def test_after_hooks_reuse_trade_key_from_state_when_not_passed(self):
        state = {}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.01
        plan = {"trade_key": "T20", "entry": 30000}

        with patch.object(mg, "_borrow_mode", return_value="manual"):
            with patch.object(mg, "is_margin_mode", return_value=True):
                mg.on_before_entry(state, symbol, side, qty, plan)

                # simulate: executor calls after_entry_opened without explicit trade_key
                mg.on_after_entry_opened(state, trade_key=None)

                # simulate: executor calls after_position_closed without explicit trade_key
                mg.on_after_position_closed(state, trade_key=None)

        # repay should be called once
        self.assertEqual(len(self.policy.repay_calls), 1)
        self.assertEqual(self.policy.repay_calls[0]["symbol"], symbol)
        self.assertEqual(len(self.policy.cleanup_calls), 1)
        self.assertEqual(self.policy.cleanup_calls[0]["trade_key"], "T20")

        # and logs should contain our trade_key at least once
        logged_trade_keys = []
        for c in self.log.call_args_list:
            kwargs = c.kwargs or {}
            if "trade_key" in kwargs:
                logged_trade_keys.append(kwargs["trade_key"])
        self.assertIn("T20", logged_trade_keys)

    def test_auto_mode_is_noop(self):
        state = {}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.01
        plan = {"trade_key": "T99", "entry": 25000}

        with patch.object(mg, "_borrow_mode", return_value="auto"):
            with patch.object(mg, "is_margin_mode", return_value=True):
                mg.on_before_entry(state, symbol, side, qty, plan)
                mg.on_after_position_closed(state, trade_key=None)

        self.assertEqual(len(self.policy.borrow_calls), 0)
        self.assertEqual(len(self.policy.repay_calls), 0)
        self.assertEqual(len(self.policy.cleanup_calls), 0)

    def test_post_close_cleanup_residual_alerts_and_saves_state(self):
        saved = []
        alerts = []
        self.policy.cleanup_result = {
            "cleanup_status": "residual_debt",
            "attempted_assets": ["USDC"],
            "repaid_amounts": {"USDC": "0.5"},
            "failed_assets": [],
            "residual_debt": [{"asset": "USDC", "liability": "1.5", "free": "0"}],
            "binance_errors": [],
        }
        mg.configure(
            _base_env(),
            self.log,
            api=self.api,
            save_state_fn=lambda st: saved.append(st),
            send_webhook_fn=lambda payload: alerts.append(payload),
        )
        mg.margin_policy = self.policy
        state = {"margin": {"active_trade_key": "T30"}}

        with patch.object(mg, "_borrow_mode", return_value="manual"):
            with patch.object(mg, "is_margin_mode", return_value=True):
                mg.on_after_position_closed(state, trade_key="T30")

        self.assertEqual(len(self.policy.repay_calls), 1)
        self.assertEqual(len(self.policy.cleanup_calls), 1)
        self.assertTrue(saved)
        self.assertEqual(alerts[0]["event"], "POST_CLOSE_MARGIN_DEBT_CLEANUP_FAIL")
        self.assertEqual(alerts[0]["cleanup_status"], "residual_debt")

    def test_post_close_cleanup_failure_does_not_escape_hook(self):
        self.policy.cleanup_error = RuntimeError("cleanup boom")
        state = {"margin": {"active_trade_key": "T40"}}

        with patch.object(mg, "_borrow_mode", return_value="manual"):
            with patch.object(mg, "is_margin_mode", return_value=True):
                mg.on_after_position_closed(state, trade_key="T40")

        self.assertEqual(len(self.policy.repay_calls), 1)
        self.assertEqual(len(self.policy.cleanup_calls), 1)
        event_names = [c.args[0] for c in self.log.call_args_list if c.args]
        self.assertIn("POST_CLOSE_MARGIN_DEBT_CLEANUP_ERROR", event_names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
