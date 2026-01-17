#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_exchange_snapshot.py
Tests for exchange_snapshot module.
"""

import unittest
import time
from executor_mod.exchange_snapshot import ExchangeSnapshot, get_snapshot, refresh_snapshot, reset_snapshot


class TestExchangeSnapshot(unittest.TestCase):
    def setUp(self):
        reset_snapshot()

    def test_snapshot_creation(self):
        """Test basic snapshot creation and freshness."""
        snap = ExchangeSnapshot()
        self.assertEqual(snap.ts_updated, 0.0)
        self.assertFalse(snap.ok)
        self.assertIsNone(snap.error)
        self.assertIsNone(snap.open_orders)
        self.assertEqual(snap.source, "")
        self.assertEqual(snap.symbol, "")
        
        # Fresh snapshot should report infinite freshness
        self.assertEqual(snap.freshness_sec(), float("inf"))
        self.assertFalse(snap.is_fresh(10.0))

    def test_snapshot_refresh_success(self):
        """Test successful snapshot refresh."""
        snap = ExchangeSnapshot()
        
        # Mock openOrders function
        def mock_open_orders(symbol):
            return [{"orderId": 123, "symbol": symbol}]
        
        snap.refresh("BTCUSDC", "test", mock_open_orders)
        
        self.assertTrue(snap.ok)
        self.assertIsNone(snap.error)
        self.assertEqual(snap.symbol, "BTCUSDC")
        self.assertEqual(snap.source, "test")
        self.assertEqual(len(snap.open_orders), 1)
        self.assertEqual(snap.open_orders[0]["orderId"], 123)
        
        # Should be fresh
        self.assertTrue(snap.is_fresh(10.0))
        self.assertLess(snap.freshness_sec(), 1.0)

    def test_snapshot_refresh_error(self):
        """Test snapshot refresh with error."""
        snap = ExchangeSnapshot()
        
        def mock_open_orders_error(symbol):
            raise Exception("API error")
        
        snap.refresh("BTCUSDC", "test", mock_open_orders_error)
        
        self.assertFalse(snap.ok)
        self.assertEqual(snap.error, "API error")
        self.assertIsNone(snap.open_orders)
        self.assertEqual(snap.get_orders(), [])

    def test_snapshot_get_orders(self):
        """Test get_orders returns empty list on None."""
        snap = ExchangeSnapshot()
        self.assertEqual(snap.get_orders(), [])
        
        snap.open_orders = [{"orderId": 1}]
        self.assertEqual(len(snap.get_orders()), 1)

    def test_snapshot_to_dict(self):
        """Test snapshot serialization."""
        snap = ExchangeSnapshot()
        
        def mock_open_orders(symbol):
            return [{"orderId": 1}, {"orderId": 2}]
        
        snap.refresh("BTCUSDC", "manage", mock_open_orders)
        
        d = snap.to_dict()
        self.assertIn("ts_updated", d)
        self.assertIn("freshness_sec", d)
        self.assertIn("ok", d)
        self.assertIn("error", d)
        self.assertIn("source", d)
        self.assertIn("symbol", d)
        self.assertIn("order_count", d)
        
        self.assertTrue(d["ok"])
        self.assertEqual(d["source"], "manage")
        self.assertEqual(d["symbol"], "BTCUSDC")
        self.assertEqual(d["order_count"], 2)

    def test_global_snapshot(self):
        """Test global singleton snapshot."""
        snap1 = get_snapshot()
        snap2 = get_snapshot()
        self.assertIs(snap1, snap2)  # Same instance

    def test_refresh_snapshot_throttling(self):
        """Test refresh_snapshot throttling."""
        def mock_open_orders(symbol):
            return [{"orderId": int(time.time())}]
        
        # First refresh should succeed
        refreshed = refresh_snapshot("BTCUSDC", "test1", mock_open_orders, min_interval_sec=2.0)
        self.assertTrue(refreshed)
        
        snap = get_snapshot()
        first_ts = snap.ts_updated
        
        # Immediate second refresh should be skipped
        refreshed = refresh_snapshot("BTCUSDC", "test2", mock_open_orders, min_interval_sec=2.0)
        self.assertFalse(refreshed)
        self.assertEqual(snap.ts_updated, first_ts)  # Not updated
        
        # After waiting, refresh should succeed
        time.sleep(2.1)
        refreshed = refresh_snapshot("BTCUSDC", "test3", mock_open_orders, min_interval_sec=2.0)
        self.assertTrue(refreshed)
        self.assertGreater(snap.ts_updated, first_ts)


if __name__ == "__main__":
    unittest.main()
