# test/test_margin_policy_isolated.py
import unittest
from unittest.mock import MagicMock
from decimal import Decimal

import executor_mod.margin_policy as mp


class TestMarginPolicyIsolated(unittest.TestCase):
    def _isolated_account(
        self,
        base_free="0.0",
        quote_free="0.0",
        base_borrowed="0.0",
        quote_borrowed="0.0",
    ):
        # Binance isolated endpoint-style shape:
        # account["assets"] = [{"baseAsset": {...}, "quoteAsset": {...}}]
        return {
            "assets": [
                {
                    "baseAsset": {"asset": "BTC", "free": base_free, "borrowed": base_borrowed},
                    "quoteAsset": {"asset": "USDC", "free": quote_free, "borrowed": quote_borrowed},
                }
            ]
        }

    def test_account_assets_flattens_isolated_shape(self):
        account = self._isolated_account(base_free="0.5", quote_free="100")
        assets = mp._account_assets(account)  # intentional (private helper)
        self.assertIsInstance(assets, list)
        self.assertEqual(len(assets), 2)
        self.assertEqual({a.get("asset") for a in assets}, {"BTC", "USDC"})

    def test_ensure_borrow_uses_isolated_free_balance_no_false_borrow(self):
        st = {}
        api = MagicMock()
        api.margin_account.return_value = self._isolated_account(quote_free="200")

        plan = {
            "trade_key": "t1",
            "is_isolated": True,
            "borrow_asset": "USDC",
            "borrow_amount": 150.0,
        }

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.01, plan)

        api.margin_borrow.assert_not_called()
        self.assertIn("margin", st)
        self.assertEqual(st["margin"].get("is_isolated"), True)

    def test_ensure_borrow_borrows_only_missing_amount_isolated(self):
        st = {}
        api = MagicMock()
        api.margin_account.return_value = self._isolated_account(quote_free="100")

        # Quote-asset borrow requires stepSize now; otherwise policy skips borrow with missing_quote_step_size.
        plan = {
            "trade_key": "t2",
            "is_isolated": True,
            "borrow_asset": "USDC",
            "borrow_amount": Decimal("150"),
            "stepSize": "0.01",
        }

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.01, plan)

        api.margin_borrow.assert_called_once()
        args, kwargs = api.margin_borrow.call_args
        self.assertEqual(args[0], "USDC")
        self.assertAlmostEqual(float(args[1]), 50.0, places=8)
        self.assertEqual(kwargs.get("is_isolated"), True)
        self.assertEqual(kwargs.get("symbol"), "BTCUSDC")

        # state updates
        margin = st["margin"]
        self.assertEqual(margin["active_trade_key"], "t2")
        self.assertIn("USDC", margin["borrowed_assets"])
        self.assertAlmostEqual(margin["borrowed_assets"]["USDC"], 50.0, places=8)
        self.assertIn("t2", margin["borrowed_by_trade"])
        self.assertAlmostEqual(margin["borrowed_by_trade"]["t2"]["USDC"], 50.0, places=8)

    def test_repay_repays_tracked_amount_not_full_outstanding_isolated(self):
        st = {}
        api = MagicMock()

        # 1) ensure_borrow sees free=100, needed=150 -> borrows 50
        # 2) repay sees outstanding borrowed=60 -> should repay only tracked(50), not 60
        api.margin_account.side_effect = [
            self._isolated_account(quote_free="100", quote_borrowed="0"),
            self._isolated_account(quote_free="0", quote_borrowed="60"),
        ]

        # Keep test stable: quote repay will call margin_repay with tracked amount.
        # No stepSize required for repay path in current code; this test should pass once borrow test passes.
        plan = {
            "trade_key": "t3",
            "is_isolated": True,
            "borrow_asset": "USDC",
            "borrow_amount": 150.0,
            "stepSize": "0.01",
        }

        mp.ensure_borrow_if_needed(st, api, "BTCUSDC", "BUY", 0.01, plan)
        mp.repay_if_any(st, api, "BTCUSDC")

        api.margin_repay.assert_called_once()
        args, kwargs = api.margin_repay.call_args
        self.assertEqual(args[0], "USDC")
        self.assertAlmostEqual(float(args[1]), 50.0, places=8)  # tracked only
        self.assertEqual(kwargs.get("is_isolated"), True)
        self.assertEqual(kwargs.get("symbol"), "BTCUSDC")

        # state cleanup
        margin = st["margin"]
        self.assertIn("t3", margin["repaid_trade_keys"])
        self.assertIsNone(margin["active_trade_key"])
        self.assertNotIn("t3", margin["borrowed_by_trade"])
        self.assertAlmostEqual(float(margin["borrowed_assets"].get("USDC", 0.0)), 0.0, places=8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
