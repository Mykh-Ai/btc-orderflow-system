import unittest
from copy import deepcopy
from unittest.mock import patch

import executor


class TestReconMissingAlerts(unittest.TestCase):
    def setUp(self):
        self._env = deepcopy(executor.ENV)

    def tearDown(self):
        executor.ENV.clear()
        executor.ENV.update(self._env)

    def test_executor_recon_missing_wiring(self):
        executor.ENV.update(
            {
                "TRADE_MODE": "margin",
                "SYMBOL": "BTCUSDC",
                "RECON_THROTTLE_SEC": 600,
                "INVAR_THROTTLE_SEC": 600,
            }
        )
        st = {
            "position": {
                "status": "OPEN",
                "mode": "live",
                "order_id": 900,
                "orders": {"tp1": 111, "tp2": 222, "sl": None},
                "tp2_done": False,
            }
        }
        events = []
        webhooks = []
        saves = []

        with patch.object(executor.binance_api, "open_orders", return_value=[{"clientOrderId": "EX_TP2_X", "orderId": 222}]), \
             patch.object(executor.binance_api, "get_order", side_effect=RuntimeError("-2013 Order does not exist.")), \
             patch.object(executor, "log_event", side_effect=lambda *args, **kw: events.append((args[0], kw))), \
             patch.object(executor, "send_webhook", side_effect=lambda payload: webhooks.append(payload)), \
             patch.object(executor, "save_state", side_effect=lambda state: saves.append(deepcopy(state))), \
             patch.object(executor, "iso_utc", return_value="2026-01-01T00:00:00Z"), \
             patch.object(executor.time, "time", return_value=1000.0):
            executor.sync_from_binance(st)

        self.assertEqual(events[0][0], "RECON_ORDER_MISSING")
        self.assertEqual(webhooks[0]["event"], "RECON_ORDER_MISSING")
        self.assertNotIn("tp1", st["position"]["orders"])
        self.assertIs(st["position"]["tp2_done"], False)
        self.assertEqual(len(saves), 1)


if __name__ == "__main__":
    unittest.main()
