import unittest

import executor_mod.margin_policy as mp


class FakeApi:
    def __init__(self, account):
        self.account = account
        self.account_calls = []
        self.borrow_calls = []
        self.repay_calls = []

    def margin_account(self, is_isolated=False, symbols=None, symbol=None):
        self.account_calls.append({"is_isolated": is_isolated, "symbols": symbols, "symbol": symbol})
        return self.account

    def margin_borrow(self, asset, amount, is_isolated=False, symbol=None):
        self.borrow_calls.append((asset, float(amount), is_isolated, symbol))

    def margin_repay(self, asset, amount, is_isolated=False, symbol=None):
        self.repay_calls.append((asset, float(amount), is_isolated, symbol))


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
        plan = {"trade_key": "T1", "is_isolated": True, "borrow_asset": "USDT", "borrow_amount": 10.0}

        mp.ensure_borrow_if_needed(st, api, "BTCUSDT", "BUY", 0.001, plan)

        # free=5, needed=10 => borrow 5
        self.assertEqual(len(api.borrow_calls), 1)
        asset, amt, is_iso, sym = api.borrow_calls[0]
        self.assertEqual(asset, "USDT")
        self.assertAlmostEqual(amt, 5.0)
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


if __name__ == "__main__":
    unittest.main()
