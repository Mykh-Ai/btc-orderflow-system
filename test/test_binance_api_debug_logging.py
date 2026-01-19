import json
import unittest
from unittest.mock import patch, MagicMock

import executor_mod.binance_api as binance_api


def _reset_binance_api_globals():
    binance_api._ENV = None
    binance_api._BINANCE_TIME_OFFSET_MS = 0
    binance_api._fmt_qty = None
    binance_api._fmt_price = None
    binance_api._round_qty = None


def _spot_env(debug: bool = False):
    return {
        "BINANCE_API_KEY": "k",
        "BINANCE_API_SECRET": "s",
        "BINANCE_BASE_URL": "https://api.binance.test",
        "RECV_WINDOW": 5000,
        "SYMBOL": "BTCUSDC",
        "TRADE_MODE": "spot",
        "MARGIN_ISOLATED": "TRUE",
        "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
        "MARGIN_AUTO_REPAY_AT_CANCEL": False,
        "BINANCE_DEBUG_PARAMS": "1" if debug else "",
    }


class TestBinanceApiDebugLogging(unittest.TestCase):
    def setUp(self):
        _reset_binance_api_globals()

    def test_logs_binance_req_fail_on_1100_when_debug_enabled(self):
        binance_api.configure(_spot_env(debug=True))
        response = MagicMock()
        response.status_code = 400
        response.text = json.dumps({"code": -1100, "msg": "Illegal characters found in a parameter."})

        with patch.object(binance_api, "_do_request", return_value=response), \
             patch.object(binance_api, "log_event") as log_event:
            with self.assertRaises(RuntimeError):
                binance_api._binance_signed_request("GET", "/api/v3/openOrders", {"symbol": "BTCUSDC"})

            self.assertTrue(any(call.args and call.args[0] == "BINANCE_REQ_FAIL" for call in log_event.call_args_list))
            for call in log_event.call_args_list:
                if call.args and call.args[0] == "BINANCE_REQ_FAIL":
                    payload = call.kwargs
                    self.assertEqual(payload.get("endpoint"), "/api/v3/openOrders")
                    self.assertEqual(payload.get("method"), "GET")
                    params = payload.get("params") or {}
                    self.assertNotIn("signature", params)
                    self.assertNotIn("X-MBX-APIKEY", params)
                    self.assertEqual(params.get("symbol"), "BTCUSDC")

    def test_no_log_when_debug_disabled(self):
        binance_api.configure(_spot_env(debug=False))
        response = MagicMock()
        response.status_code = 400
        response.text = json.dumps({"code": -1100, "msg": "Illegal characters found in a parameter."})

        with patch.object(binance_api, "_do_request", return_value=response), \
             patch.object(binance_api, "log_event") as log_event:
            with self.assertRaises(RuntimeError):
                binance_api._binance_signed_request("GET", "/api/v3/openOrders", {"symbol": "BTCUSDC"})

            self.assertFalse(any(call.args and call.args[0] == "BINANCE_REQ_FAIL" for call in log_event.call_args_list))
