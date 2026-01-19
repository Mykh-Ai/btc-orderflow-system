import unittest
from decimal import Decimal
from unittest.mock import patch, MagicMock

# Import the module under test
import executor_mod.binance_api as binance_api


def _reset_binance_api_globals():
    """Reset module globals so tests are isolated."""
    binance_api._ENV = None
    binance_api._BINANCE_TIME_OFFSET_MS = 0
    binance_api._fmt_qty = None
    binance_api._fmt_price = None
    binance_api._round_qty = None


def _spot_env():
    return {
        "BINANCE_API_KEY": "k",
        "BINANCE_API_SECRET": "s",
        "BINANCE_BASE_URL": "https://api.binance.test",
        "RECV_WINDOW": 5000,
        "SYMBOL": "BTCUSDC",
        "TRADE_MODE": "spot",
        # margin keys still present but unused in spot mode
        "MARGIN_ISOLATED": "TRUE",
        "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
        "MARGIN_AUTO_REPAY_AT_CANCEL": False,
    }


def _margin_env():
    e = _spot_env()
    e["TRADE_MODE"] = "margin"
    e["MARGIN_ISOLATED"] = "TRUE"
    e["MARGIN_SIDE_EFFECT"] = "AUTO_BORROW_REPAY"
    e["MARGIN_AUTO_REPAY_AT_CANCEL"] = True
    e["MARGIN_BORROW_MODE"] = "auto"

    return e


class TestBinanceApiSmoke(unittest.TestCase):
    def setUp(self):
        _reset_binance_api_globals()

    def test_requires_configure(self):
        # Not configured => any function that needs env should raise.
        with self.assertRaises(RuntimeError):
            binance_api.binance_public_get("/api/v3/ping")

        with self.assertRaises(RuntimeError):
            binance_api.place_order_raw({"symbol": "BTCUSDC"})

    def test_requires_fmt_injection_for_order_helpers(self):
        # Configure env only, but no fmt/round injection => order helpers should raise
        binance_api.configure(_spot_env())
        with self.assertRaises(RuntimeError):
            binance_api.place_spot_limit("BTCUSDC", "BUY", 0.001, 42000)

        with self.assertRaises(RuntimeError):
            binance_api.place_spot_market("BTCUSDC", "BUY", 0.001)

    def test_fmt_amount_no_sci(self):
        self.assertEqual(binance_api._fmt_amount_no_sci(1e-7), "0.0000001")
        self.assertEqual(binance_api._fmt_amount_no_sci(Decimal("1E-8")), "0.00000001")
        self.assertEqual(binance_api._fmt_amount_no_sci(" 0.0100 "), "0.01")
        self.assertEqual(binance_api._fmt_amount_no_sci(Decimal("0E-8")), "0")
        with self.assertRaises(ValueError):
            binance_api._fmt_amount_no_sci(None)
        with self.assertRaises(ValueError):
            binance_api._fmt_amount_no_sci("abc")

    def test_place_order_raw_spot_endpoint_and_symbol_default(self):
        env = _spot_env()
        binance_api.configure(env)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = {"ok": True}

            # No symbol in params -> should default to ENV["SYMBOL"]
            res = binance_api.place_order_raw({"side": "BUY", "type": "MARKET", "quantity": "1"})
            self.assertEqual(res, {"ok": True})

            signed.assert_called_once()
            method, endpoint, params = signed.call_args[0]
            self.assertEqual(method, "POST")
            self.assertEqual(endpoint, "/api/v3/order")
            self.assertEqual(params["symbol"], env["SYMBOL"])
            self.assertEqual(params["side"], "BUY")

    def test_place_order_raw_margin_injects_margin_params(self):
        env = _margin_env()
        binance_api.configure(env)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = {"ok": True}

            res = binance_api.place_order_raw({"side": "BUY", "type": "MARKET", "quantity": "1"})
            self.assertEqual(res, {"ok": True})

            method, endpoint, params = signed.call_args[0]
            self.assertEqual(method, "POST")
            self.assertEqual(endpoint, "/sapi/v1/margin/order")
            self.assertEqual(params["symbol"], env["SYMBOL"])
            self.assertEqual(params["isIsolated"], env["MARGIN_ISOLATED"])
            self.assertEqual(params["sideEffectType"], env["MARGIN_SIDE_EFFECT"])
            self.assertEqual(params["autoRepayAtCancel"], "TRUE")

    def test_open_orders_spot_vs_margin(self):
        # spot
        binance_api.configure(_spot_env())
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = [{"id": 1}]
            res = binance_api.open_orders("BTCUSDC")
            self.assertEqual(res, [{"id": 1}])
            method, endpoint, params = signed.call_args[0]
            self.assertEqual(method, "GET")
            self.assertEqual(endpoint, "/api/v3/openOrders")
            self.assertEqual(params["symbol"], "BTCUSDC")

        # margin
        _reset_binance_api_globals()
        binance_api.configure(_margin_env())
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = [{"id": 2}]
            res = binance_api.open_orders("BTCUSDC")
            self.assertEqual(res, [{"id": 2}])
            method, endpoint, params = signed.call_args[0]
            self.assertEqual(method, "GET")
            self.assertEqual(endpoint, "/sapi/v1/margin/openOrders")
            self.assertEqual(params["symbol"], "BTCUSDC")
            self.assertIn("isIsolated", params)

    def test_open_orders_margin_cross_symbol_rules(self):
        env = _margin_env()
        env["MARGIN_ISOLATED"] = "FALSE"
        binance_api.configure(env)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = []
            binance_api.open_orders(None)
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/sapi/v1/margin/openOrders"))
            self.assertNotIn("symbol", params)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = []
            binance_api.open_orders("")
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/sapi/v1/margin/openOrders"))
            self.assertNotIn("symbol", params)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = []
            binance_api.open_orders(" BTCUSDC ")
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/sapi/v1/margin/openOrders"))
            self.assertEqual(params.get("symbol"), "BTCUSDC")

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = []
            binance_api.open_orders(" ethusdc ")
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/sapi/v1/margin/openOrders"))
            self.assertEqual(params.get("symbol"), "ETHUSDC")

    def test_check_and_cancel_order_endpoints(self):
        binance_api.configure(_spot_env())
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = {"status": "NEW"}
            _ = binance_api.check_order_status("BTCUSDC", 123)
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/api/v3/order"))
            self.assertEqual(params["orderId"], 123)

        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = {"status": "CANCELED"}
            _ = binance_api.cancel_order("BTCUSDC", 123)
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("DELETE", "/api/v3/order"))
            self.assertEqual(params["orderId"], 123)

    def test_planb_exec_price_uses_bid_or_ask(self):
        binance_api.configure(_spot_env())
        with patch.object(binance_api, "binance_public_get") as pub:
            pub.return_value = {"bidPrice": "100", "askPrice": "110"}
            self.assertEqual(binance_api._planb_exec_price("BTCUSDC", "BUY"), 110.0)
            self.assertEqual(binance_api._planb_exec_price("BTCUSDC", "SELL"), 100.0)

    def test_binance_sanity_check_calls_public_and_signed(self):
        env = _spot_env()
        binance_api.configure(env)

        with patch.object(binance_api, "binance_public_get") as pub, \
             patch.object(binance_api, "_binance_signed_request") as signed, \
             patch.object(binance_api, "log_event") as log_event:

            pub.side_effect = [{}, {"serverTime": 1700000000000}]
            signed.return_value = {"balances": [1, 2, 3]}

            binance_api.binance_sanity_check()

            # public endpoints
            self.assertEqual(pub.call_args_list[0][0][0], "/api/v3/ping")
            self.assertEqual(pub.call_args_list[1][0][0], "/api/v3/time")

            # signed endpoint depends on mode
            method, endpoint, params = signed.call_args[0]
            self.assertEqual((method, endpoint), ("GET", "/api/v3/account"))
            self.assertIn("recvWindow", params)

            # should log public + signed ok
            self.assertTrue(any(c.args and c.args[0] == "BINANCE_PUBLIC_OK" for c in log_event.call_args_list))
            self.assertTrue(any(c.args and c.args[0] == "BINANCE_SIGNED_OK" for c in log_event.call_args_list))

    def test_margin_debt_snapshot_spot_mode_guard(self):
        binance_api.configure(_spot_env())
        with self.assertRaises(RuntimeError):
            binance_api.get_margin_debt_snapshot()

    def test_margin_debt_snapshot_isolated_defaults_env_symbol(self):
        env = _margin_env()
        env["MARGIN_ISOLATED"] = "TRUE"
        env["SYMBOL"] = "BTCUSDC"
        binance_api.configure(env)
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = {"assets": []}
            _ = binance_api.get_margin_debt_snapshot()
            method, endpoint, params = signed.call_args[0]
            self.assertEqual(method, "GET")
            self.assertEqual(endpoint, "/sapi/v1/margin/isolated/account")
            self.assertEqual(params.get("symbols"), "BTCUSDC")

    def test_margin_debt_snapshot_isolated_requires_symbol(self):
        env = _margin_env()
        env["MARGIN_ISOLATED"] = "TRUE"
        env["SYMBOL"] = ""
        binance_api.configure(env)
        with self.assertRaises(RuntimeError):
            binance_api.get_margin_debt_snapshot()

    def test_margin_debt_snapshot_isolated_asset_keys(self):
        env = _margin_env()
        env["MARGIN_ISOLATED"] = "TRUE"
        env["SYMBOL"] = "BTCUSDC"
        binance_api.configure(env)
        payload = {
            "assets": [
                {
                    "symbol": "BTCUSDC",
                    "baseAsset": {"asset": "BTC", "borrowed": "0.1", "interest": "0.0"},
                    "quoteAsset": {"asset": "USDC", "borrowed": "0", "interest": "0"},
                }
            ]
        }
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = payload
            snapshot = binance_api.get_margin_debt_snapshot()
        self.assertIn("BTCUSDC:BTC", snapshot["details"])
        self.assertNotIn("BTCUSDC:baseAsset", snapshot["details"])

    def test_margin_debt_snapshot_epsilon_filters_dust(self):
        env = _margin_env()
        env["MARGIN_ISOLATED"] = "TRUE"
        env["SYMBOL"] = "BTCUSDC"
        env["MARGIN_DEBT_EPS"] = 1e-12
        binance_api.configure(env)
        payload = {
            "assets": [
                {
                    "symbol": "BTCUSDC",
                    "baseAsset": {"asset": "BTC", "borrowed": "1e-18", "interest": "0"},
                    "quoteAsset": {"asset": "USDC", "borrowed": "0", "interest": "0"},
                }
            ]
        }
        with patch.object(binance_api, "_binance_signed_request") as signed:
            signed.return_value = payload
            snapshot = binance_api.get_margin_debt_snapshot()
        self.assertFalse(snapshot["has_debt"])
        self.assertEqual(snapshot["details"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
