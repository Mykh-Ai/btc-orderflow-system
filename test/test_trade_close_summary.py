import unittest

import executor_mod.trade_close_summary as summary


def _snapshot(**overrides):
    data = {
        "schema": "trade_execution_snapshot_v1",
        "trade_key": "EX_EN_1779438963",
        "symbol": "BTCUSDC",
        "snapshot_status": "partial",
        "lifecycle_class": "tp1_tp2_trailing_stop",
        "local_last_closed": {
            "reason": "SL",
            "side": "SHORT",
            "trade_key": "EX_EN_1779438963",
        },
        "orders": {
            "entry": {"order_id": 9336874836},
            "tp1": {"order_id": 9336876518},
            "tp2": {"order_id": 9336876801},
            "final_sl": {"order_id": 9346238698},
        },
        "fill_summaries": {
            "entry": {
                "avg_price": "77215.81",
                "total_qty": "0.0518",
                "total_quote_qty": "3999.778958",
                "commission_by_asset": {"BNB": "0.00432724"},
            },
            "tp1": {
                "avg_price": "76798.72",
                "total_qty": "0.01726",
                "total_quote_qty": "1325.5459072",
                "commission_by_asset": {"BNB": "0.00151226"},
            },
            "tp2": {
                "avg_price": "76390.06",
                "total_qty": "0.01726",
                "total_quote_qty": "1318.4924356",
                "commission_by_asset": {"BNB": "0.0015142"},
            },
            "final_sl": {
                "avg_price": "74797.02",
                "total_qty": "0.01728",
                "total_quote_qty": "1292.4925056",
                "commission_by_asset": {"BNB": "0.0015133"},
            },
        },
        "fees": {"commission_by_asset": {"BNB": "0.00886700"}},
    }
    data.update(overrides)
    return data


class TestTradeCloseSummaryFormatter(unittest.TestCase):
    def test_short_tp1_tp2_final_sl_with_conversion(self):
        payload = summary.build_trade_closed_summary_payload(
            _snapshot(),
            commission_usdc_approx="5.7994332168",
            commission_valuation_source="test",
            commission_valuation_symbol="BNBUSDC",
        )

        self.assertEqual(payload["event"], "TRADE_CLOSED_SUMMARY")
        self.assertEqual(payload["type"], "TRADE_CLOSED_SUMMARY")
        self.assertEqual(payload["symbol"], "BTCUSDC")
        self.assertEqual(payload["trade_key"], "EX_EN_1779438963")
        self.assertEqual(payload["gross_pnl_usdc"], "63.2481096")
        self.assertEqual(payload["commission_by_asset"], {"BNB": "0.00886700"})
        self.assertEqual(payload["commission_usdc_approx"], "5.7994332168")
        self.assertEqual(payload["net_pnl_approx_usdc"], "57.4486763832")
        self.assertEqual(payload["message"], payload["text"])
        self.assertEqual(payload["telegram_text"], payload["text"])
        self.assertIn("✅ Trade closed: BTCUSDC SHORT", payload["text"])
        self.assertIn("Lifecycle: TP1 + TP2 + trailing SL", payload["text"])
        self.assertIn("- TP1: 76798.72 / 0.01726 / +7.20 USDC", payload["text"])
        self.assertIn("- TP2: 76390.06 / 0.01726 / +14.25 USDC", payload["text"])
        self.assertIn("- Final SL: 74797.02 / 0.01728 / +41.80 USDC", payload["text"])
        self.assertIn("Gross PnL: +63.25 USDC", payload["text"])
        self.assertIn("Commissions: 0.00886700 BNB", payload["text"])
        self.assertIn("Commission value: ~5.80 USDC", payload["text"])
        self.assertIn("Net PnL approx: +57.45 USDC", payload["text"])
        self.assertIn("borrow/interest ignored by operational policy", payload["text"])

    def test_commission_conversion_unavailable(self):
        payload = summary.build_trade_closed_summary_payload(_snapshot())

        self.assertIsNone(payload["commission_usdc_approx"])
        self.assertIsNone(payload["net_pnl_approx_usdc"])
        self.assertIn("Net PnL approx: not_available", payload["text"])
        self.assertIn("Reason: commission conversion unavailable.", payload["text"])

    def test_missing_optional_fields_not_blank(self):
        payload = summary.build_trade_closed_summary_payload({
            "symbol": "BTCUSDC",
            "trade_key": "T1",
            "local_last_closed": {"side": "LONG", "reason": "SL"},
            "fill_summaries": {},
            "fees": {},
        })

        self.assertTrue(payload["text"].strip())
        self.assertIn("Trade closed", payload["text"])
        self.assertIn("Gross PnL: not_available", payload["text"])

    def test_negative_gross_pnl(self):
        snap = _snapshot(
            local_last_closed={"reason": "SL", "side": "LONG", "trade_key": "LOSS"},
            lifecycle_class="plain_sl",
            fill_summaries={
                "entry": {"avg_price": "100", "total_qty": "1", "total_quote_qty": "100"},
                "tp1": {},
                "tp2": {},
                "final_sl": {"avg_price": "90", "total_qty": "1", "total_quote_qty": "90"},
            },
            fees={"commission_by_asset": {"USDC": "1"}},
        )

        payload = summary.build_trade_closed_summary_payload(snap, commission_usdc_approx="1")

        self.assertEqual(payload["gross_pnl_usdc"], "-10")
        self.assertEqual(payload["net_pnl_approx_usdc"], "-11")
        self.assertIn("Gross PnL: -10.00 USDC", payload["text"])
        self.assertIn("Net PnL approx: -11.00 USDC", payload["text"])

    def test_long_case(self):
        snap = _snapshot(
            local_last_closed={"reason": "TP2", "side": "LONG", "trade_key": "LONG1"},
            lifecycle_class="tp1_tp2",
            fill_summaries={
                "entry": {"avg_price": "100", "total_qty": "1", "total_quote_qty": "100"},
                "tp1": {"avg_price": "110", "total_qty": "0.5", "total_quote_qty": "55"},
                "tp2": {"avg_price": "120", "total_qty": "0.5", "total_quote_qty": "60"},
                "final_sl": {},
            },
            fees={"commission_by_asset": {"USDC": "1"}},
        )

        payload = summary.build_trade_closed_summary_payload(snap, commission_usdc_approx="1")

        self.assertEqual(payload["gross_pnl_usdc"], "15.0")
        self.assertEqual(payload["net_pnl_approx_usdc"], "14.0")
        self.assertIn("Lifecycle: TP1 + TP2", payload["text"])


if __name__ == "__main__":
    unittest.main()
