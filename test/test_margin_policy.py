import unittest
from decimal import Decimal

import executor_mod.margin_policy as mp


class FakeApi:
    def __init__(self, account):
        self.account = account
        self.account_calls = []
        self.borrow_calls = []
        self.repay_calls = []
        self.log_events = []

    def margin_account(self, is_isolated=False, symbols=None, symbol=None):
        self.account_calls.append({"is_isolated": is_isolated, "symbols": symbols, "symbol": symbol})
        return self.account

    def margin_borrow(self, asset, amount, is_isolated=False, symbol=None):
        self.borrow_calls.append((asset, amount, is_isolated, symbol))

    def margin_repay(self, asset, amount, is_isolated=False, symbol=None):
        self.repay_calls.append((asset, float(amount), is_isolated, symbol))

    def log_event(self, name, **payload):
        self.log_events.append((name, payload))


class TestMarginPolicy(unittest.TestCase):
    def test_isolated_assets_are_flattened(self):
        # Isolated margin-style response: assets -> [{baseAsset:{...}, quoteAsset:{...}}]
        account = {
            "assets": [{
                "baseAsset": {"asset": "BTC", "free": "0.0", "borrowed": "0.01"},
                "quoteAsset": {"asset": "USDT", "free": "5.0", "borrowed": "0.0"},
            }]
        }
        api = FakeApi(account)
        st = {}
        plan = {
            "trade_key": "T1",
            "is_isolated": True,
            "borrow_asset": "USDT",
            "borrow_amount": 10.0,
            "stepSize": "0.01",
        }

        mp.ensure_borrow_if_needed(st, api, "BTCUSDT", "BUY", 0.001, plan)

        # free=5, needed=10 => borrow 5
        self.assertEqual(len(api.borrow_calls), 1)
        asset, amt, is_iso, sym = api.borrow_calls[0]
        self.assertEqual(asset, "USDT")
        self.assertAlmostEqual(float(amt), 5.0)
        self.assertTrue(is_iso)

    def test_repay_only_tracked_amount_not_full_outstanding(self):
        account = {"userAssets": [{"asset": "USDT", "borrowed": "10.0", "free": "0.0"}]}
        api = FakeApi(account)
        st = {"margin": {
            "active_trade_key": "T1",
            "borrowed_by_trade": {"T1": {"USDT": 3.0}},
            "borrowed_assets": {"USDT": 3.0},
            "borrowed_trade_keys": ["T1"],
            "repaid_trade_keys": [],
            "is_isolated": False,
        }}

        mp.repay_if_any(st, api, "BTCUSDT")

        self.assertEqual(len(api.repay_calls), 1)
        asset, amt, is_iso, sym = api.repay_calls[0]
        self.assertEqual(asset, "USDT")
        self.assertAlmostEqual(amt, 3.0)  # IMPORTANT: tracked only

        # cleanup
        self.assertIsNone(st["margin"]["active_trade_key"])
        self.assertNotIn("T1", st["margin"]["borrowed_by_trade"])

    def test_skip_quote_borrow_without_step_size(self):
        account = {"userAssets": [{"asset": "USDC", "free": "0.0"}]}
        api = FakeApi(account)
        st = {}
        plan = {"trade_key": "T1", "is_isolated": False, "borrow_asset": "USDC", "borrow_amount": "10"}

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)

        self.assertEqual(api.borrow_calls, [])
        self.assertEqual(st["margin"]["last_borrow_skip_reason"], "missing_quote_step_size")
        events = [name for name, _ in api.log_events]
        self.assertIn("BORROW_SKIP", events)

    def test_base_borrow_fallback_step_size(self):
        account = {"userAssets": [{"asset": "BTC", "free": "0.0"}]}
        api = FakeApi(account)
        st = {}
        plan = {"trade_key": "T1", "is_isolated": False, "borrow_asset": "BTC", "borrow_amount": "0.0002912499"}

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.001, plan)

        self.assertEqual(len(api.borrow_calls), 1)
        asset, amt, is_iso, sym = api.borrow_calls[0]
        self.assertEqual(asset, "BTC")
        self.assertIsInstance(amt, Decimal)
        self.assertEqual(amt, Decimal("0.000292"))

    def test_borrow_rounds_up_to_step_size(self):
        account = {"userAssets": [{"asset": "BTC", "free": "0.00103875"}]}
        api = FakeApi(account)
        st = {}
        plan = {
            "trade_key": "T2",
            "is_isolated": False,
            "borrow_asset": "BTC",
            "borrow_amount": "0.00129",
            "stepSize": "0.00001",
        }

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "SELL", 0.00129, plan)

        self.assertEqual(len(api.borrow_calls), 1)
        asset, amt, is_iso, sym = api.borrow_calls[0]
        self.assertEqual(asset, "BTC")
        self.assertIsInstance(amt, Decimal)
        self.assertEqual(amt, Decimal("0.00026"))


if __name__ == "__main__":
    unittest.main()
