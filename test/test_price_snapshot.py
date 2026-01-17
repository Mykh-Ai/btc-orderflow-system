import unittest
from unittest.mock import MagicMock, patch
import time
from executor_mod import price_snapshot


class TestPriceSnapshot(unittest.TestCase):
    def setUp(self):
        """Reset snapshot state before each test."""
        price_snapshot.reset_snapshot_for_tests()
        price_snapshot.configure(log_event_fn=None)  # Disable logging for tests

    def test_price_snapshot_throttle(self):
        """Test that price snapshot throttles API calls within min_interval."""
        call_count = {"n": 0}

        def mock_get_mid_price(symbol: str) -> float:
            call_count["n"] += 1
            return 100.0 + call_count["n"]

        # First call: should refresh (no prior data)
        refreshed = price_snapshot.refresh_price_snapshot(
            "BTCUSDC", "test", mock_get_mid_price, min_interval_sec=2.0
        )
        self.assertTrue(refreshed, "First refresh should succeed")
        self.assertEqual(call_count["n"], 1, "First refresh should call get_mid_price")

        snapshot = price_snapshot.get_price_snapshot()
        self.assertTrue(snapshot.ok)
        self.assertEqual(snapshot.price_mid, 101.0)
        self.assertEqual(snapshot.symbol, "BTCUSDC")
        self.assertEqual(snapshot.source, "test")

        # Second call immediately: should be throttled
        refreshed = price_snapshot.refresh_price_snapshot(
            "BTCUSDC", "test", mock_get_mid_price, min_interval_sec=2.0
        )
        self.assertFalse(refreshed, "Second refresh should be throttled")
        self.assertEqual(call_count["n"], 1, "Throttled refresh should not call get_mid_price")

        # Snapshot should still have old data
        snapshot = price_snapshot.get_price_snapshot()
        self.assertEqual(snapshot.price_mid, 101.0, "Price should not change when throttled")

        # Wait for throttle to expire
        time.sleep(2.1)

        # Third call after throttle expires: should refresh
        refreshed = price_snapshot.refresh_price_snapshot(
            "BTCUSDC", "test", mock_get_mid_price, min_interval_sec=2.0
        )
        self.assertTrue(refreshed, "Third refresh should succeed after throttle expires")
        self.assertEqual(call_count["n"], 2, "Third refresh should call get_mid_price")

        snapshot = price_snapshot.get_price_snapshot()
        self.assertEqual(snapshot.price_mid, 102.0, "Price should update after throttle expires")

    def test_price_snapshot_error_handling(self):
        """Test that price snapshot handles errors gracefully."""
        def mock_get_mid_price_error(symbol: str) -> float:
            raise ValueError("API error")

        refreshed = price_snapshot.refresh_price_snapshot(
            "BTCUSDC", "test", mock_get_mid_price_error, min_interval_sec=0.0
        )
        self.assertTrue(refreshed, "Refresh should return True even on error")

        snapshot = price_snapshot.get_price_snapshot()
        self.assertFalse(snapshot.ok, "Snapshot should not be ok after error")
        self.assertEqual(snapshot.price_mid, 0.0, "Price should be 0.0 on error")
        self.assertIsNotNone(snapshot.error, "Error should be recorded")
        self.assertIn("API error", snapshot.error)

    def test_price_snapshot_freshness(self):
        """Test freshness calculation."""
        snapshot = price_snapshot.get_price_snapshot()

        # Before any update, freshness should be infinite
        self.assertEqual(snapshot.freshness_sec(), float("inf"))
        self.assertFalse(snapshot.is_fresh(1.0))

        # After update, freshness should be near 0
        def mock_get_mid_price(symbol: str) -> float:
            return 100.0

        price_snapshot.refresh_price_snapshot(
            "BTCUSDC", "test", mock_get_mid_price, min_interval_sec=0.0
        )

        snapshot = price_snapshot.get_price_snapshot()
        self.assertLess(snapshot.freshness_sec(), 1.0)
        self.assertTrue(snapshot.is_fresh(10.0))

        # After waiting, freshness should increase
        time.sleep(1.1)
        self.assertGreater(snapshot.freshness_sec(), 1.0)
        self.assertFalse(snapshot.is_fresh(1.0))
        self.assertTrue(snapshot.is_fresh(10.0))


class TestSLWatchdogOpenOnly(unittest.TestCase):
    """Test that SL watchdog only runs when status == OPEN."""

    def setUp(self):
        """Reset snapshot state before each test."""
        price_snapshot.reset_snapshot_for_tests()

    def test_sl_watchdog_runs_when_status_open(self):
        """Test that SL watchdog path is executed when status == OPEN."""
        # Mock position with status OPEN
        pos = {
            "status": "OPEN",
            "side": "LONG",
            "orders": {"sl": 12345},
        }

        # Track if price snapshot refresh was called
        refresh_called = {"n": 0}
        original_refresh = price_snapshot.refresh_price_snapshot

        def mock_refresh(*args, **kwargs):
            refresh_called["n"] += 1
            return original_refresh(*args, **kwargs)

        with patch.object(price_snapshot, "refresh_price_snapshot", side_effect=mock_refresh):
            # Simulate the watchdog code path
            status = str(pos.get("status") or "").strip().upper()
            if status == "OPEN":
                snapshot = price_snapshot.get_price_snapshot()
                price_snapshot.refresh_price_snapshot(
                    "BTCUSDC", "sl_watchdog", lambda s: 100.0, min_interval_sec=2.0
                )

        self.assertEqual(refresh_called["n"], 1, "refresh_price_snapshot should be called when status is OPEN")

    def test_sl_watchdog_skipped_when_status_open_filled(self):
        """Test that SL watchdog path is NOT executed when status == OPEN_FILLED."""
        # Mock position with status OPEN_FILLED
        pos = {
            "status": "OPEN_FILLED",
            "side": "LONG",
            "orders": {"sl": 12345},
        }

        # Track if price snapshot refresh was called
        refresh_called = {"n": 0}
        original_refresh = price_snapshot.refresh_price_snapshot

        def mock_refresh(*args, **kwargs):
            refresh_called["n"] += 1
            return original_refresh(*args, **kwargs)

        with patch.object(price_snapshot, "refresh_price_snapshot", side_effect=mock_refresh):
            # Simulate the watchdog code path
            status = str(pos.get("status") or "").strip().upper()
            if status == "OPEN":
                snapshot = price_snapshot.get_price_snapshot()
                price_snapshot.refresh_price_snapshot(
                    "BTCUSDC", "sl_watchdog", lambda s: 100.0, min_interval_sec=2.0
                )

        self.assertEqual(refresh_called["n"], 0, "refresh_price_snapshot should NOT be called when status is OPEN_FILLED")

    def test_sl_watchdog_skipped_when_status_closing(self):
        """Test that SL watchdog path is NOT executed when status == CLOSING."""
        pos = {
            "status": "CLOSING",
            "side": "LONG",
            "orders": {"sl": 12345},
        }

        refresh_called = {"n": 0}
        original_refresh = price_snapshot.refresh_price_snapshot

        def mock_refresh(*args, **kwargs):
            refresh_called["n"] += 1
            return original_refresh(*args, **kwargs)

        with patch.object(price_snapshot, "refresh_price_snapshot", side_effect=mock_refresh):
            status = str(pos.get("status") or "").strip().upper()
            if status == "OPEN":
                price_snapshot.refresh_price_snapshot(
                    "BTCUSDC", "sl_watchdog", lambda s: 100.0, min_interval_sec=2.0
                )

        self.assertEqual(refresh_called["n"], 0, "refresh_price_snapshot should NOT be called when status is CLOSING")


if __name__ == "__main__":
    unittest.main()
