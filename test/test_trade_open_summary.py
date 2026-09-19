from decimal import Decimal
import unittest

from executor_mod.trade_open_summary import build_trade_open_payload


class TestTradeOpenSummary(unittest.TestCase):
    def test_long_payload_contains_levels_and_risk_distances(self):
        payload = build_trade_open_payload(
            {
                "mode": "live",
                "side": "LONG",
                "qty": 0.002,
                "entry": 95000.0,
                "prices": {"entry": 95000.0, "sl": 94000.0, "tp1": 96000.0, "tp2": 97000.0},
            },
            symbol="BTCUSDC",
            order={"orderId": 123},
        )

        self.assertEqual(payload["sl"], 94000.0)
        self.assertEqual(payload["tp1"], 96000.0)
        self.assertEqual(payload["tp2"], 97000.0)
        self.assertEqual(payload["r"], 1000.0)
        self.assertAlmostEqual(payload["risk_percent"], 1000 / 95000 * 100)
        self.assertEqual(payload["tp1_r"], 1.0)
        self.assertEqual(payload["tp2_r"], 2.0)
        self.assertIn("Stop-loss: 94000", payload["telegram_text"])
        self.assertIn("R (entry to SL): 1000 (1.05%)", payload["telegram_text"])
        self.assertIn("Take profit 2: 97000", payload["telegram_text"])
        for key in ("telegram_text", "message", "text"):
            self.assertNotRegex(payload[key], r"Take profit [12]:.*[0-9]R")
        self.assertIn("Entry: 95000", payload["text"])
        self.assertIn("Take profit 1: 96000", payload["text"])
        self.assertEqual(payload["telegram_text"], payload["message"])
        self.assertEqual(payload["telegram_text"], payload["text"])

    def test_short_uses_absolute_distances_and_decimal_math(self):
        payload = build_trade_open_payload(
            {
                "side": "SHORT",
                "qty": "0.01",
                "prices": {
                    "entry": Decimal("100.10"),
                    "sl": Decimal("101.35"),
                    "tp1": Decimal("98.225"),
                    "tp2": Decimal("97.60"),
                },
            },
            symbol="BTCUSDC",
        )

        self.assertEqual(payload["r"], 1.25)
        self.assertEqual(payload["tp1_distance"], 1.875)
        self.assertEqual(payload["tp2_distance"], 2.5)
        self.assertEqual(payload["tp1_r"], 1.5)
        self.assertEqual(payload["tp2_r"], 2.0)

    def test_missing_levels_still_builds_compatible_payload(self):
        payload = build_trade_open_payload(
            {"side": "LONG", "qty": 1, "entry": 10},
            symbol="TESTUSDC",
        )

        self.assertEqual(payload["entry"], 10.0)
        self.assertIsNone(payload["sl"])
        self.assertIsNone(payload["r"])
        self.assertIn("Stop-loss: not_available", payload["text"])


if __name__ == "__main__":
    unittest.main()
