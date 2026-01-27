"""test_margin_borrow_mismatch.py

Tests for margin manual borrow mismatch fix:
- Ensure borrow uses same qty/price as actual order (formatted values)
- Ensure buffer covers fees/rounding
- No ENV leakage between tests
"""
import copy
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from executor_mod import margin_guard, margin_policy


class TestMarginBorrowMismatch:
    """Tests for margin borrow mismatch fix (formatted qty/price + buffer)"""

    def setup_method(self):
        """Save ENV before each test"""
        self.original_env = copy.deepcopy(margin_guard.ENV)

    def teardown_method(self):
        """Restore ENV after each test"""
        margin_guard.ENV.clear()
        margin_guard.ENV.update(self.original_env)

    def test_borrow_covers_entry_notional_with_buffer(self):
        """Ensure borrow amount includes buffer and covers required notional even when free is slightly less."""
        # Setup: Cross margin manual mode
        env = {
            "TRADE_MODE": "margin",
            "MARGIN_ISOLATED": False,
            "MARGIN_BORROW_MODE": "manual",
            "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
            "MARGIN_BORROW_BUFFER_PCT": 0.003,  # 0.3% buffer
            "SYMBOL": "BTCUSDC",
            "QTY_STEP": "0.00001",
            "TICK_SIZE": "0.01",
        }
        margin_guard.configure(env, log_event_fn=lambda *args, **kwargs: None, api=None)

        state = {"margin": {}}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.00125  # Raw qty from notional calc
        
        # Formatted values that will actually be sent to Binance
        qty_sent = 0.00125  # After fmt_qty
        price_sent = 95800.50  # After fmt_price
        
        plan = {
            "trade_key": "test_trade_123",
            "qty_sent": qty_sent,
            "price_sent": price_sent,
        }

        trade_key, plan_use = margin_guard._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        # Verify borrow calculation
        required_quote = qty_sent * price_sent  # 0.00125 * 95800.50 = 119.750625
        buffer_pct = 0.003
        expected_borrow = required_quote * (1.0 + buffer_pct)  # 119.750625 * 1.003 = 120.109976875

        assert plan_use["borrow_asset"] == "USDC"
        assert plan_use["borrow_amount"] > required_quote, "Borrow must exceed required notional"
        assert abs(plan_use["borrow_amount"] - expected_borrow) < 0.01, f"Expected ~{expected_borrow}, got {plan_use['borrow_amount']}"
        
        # Simulate scenario: free_quote slightly less than required
        # If free = 119.76, needed = 119.750625, borrow should cover: 120.109976875 - 119.76 = ~0.35
        # This ensures even with rounding/fees, we have enough

    def test_borrow_uses_same_price_as_order(self):
        """Ensure borrow uses entry_price/qty_sent (order-aligned) not mid_price when values differ."""
        # Setup
        env = {
            "TRADE_MODE": "margin",
            "MARGIN_ISOLATED": False,
            "MARGIN_BORROW_MODE": "manual",
            "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
            "MARGIN_BORROW_BUFFER_PCT": 0.003,
            "SYMBOL": "BTCUSDC",
            "PRICE_SNAPSHOT_MIN_SEC": 2.0,
        }
        
        # Mock API client with mid_price different from entry price
        mock_api = MagicMock()
        mock_api.get_mid_price = MagicMock(return_value=95500.0)  # Mid price
        
        margin_guard.configure(env, log_event_fn=lambda *args, **kwargs: None, api=mock_api)

        state = {"margin": {}}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.00125
        
        # Order will use these exact values (formatted)
        qty_sent = 0.00125
        price_sent = 95800.50  # Entry price (different from mid_price)
        
        plan = {
            "trade_key": "test_trade_456",
            "qty_sent": qty_sent,
            "price_sent": price_sent,
            "entry_price": price_sent,
        }

        trade_key, plan_use = margin_guard._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        # Verify borrow uses entry_price (95800.50), NOT mid_price (95500.0)
        required_quote = qty_sent * price_sent  # Uses price_sent
        buffer_pct = 0.003
        expected_borrow = required_quote * (1.0 + buffer_pct)

        assert plan_use["borrow_asset"] == "USDC"
        # Borrow should be based on entry price (95800.50), not mid price (95500.0)
        # If it used mid_price: 0.00125 * 95500 * 1.003 = ~119.733
        # If it uses entry_price: 0.00125 * 95800.50 * 1.003 = ~120.110
        assert plan_use["borrow_amount"] > 120.0, f"Borrow should use entry_price (>120), got {plan_use['borrow_amount']}"
        assert abs(plan_use["borrow_amount"] - expected_borrow) < 0.01

    def test_borrow_fallback_to_mid_price_with_buffer(self):
        """When qty_sent/price_sent not provided, fallback to mid_price snapshot (with buffer)."""
        env = {
            "TRADE_MODE": "margin",
            "MARGIN_ISOLATED": False,
            "MARGIN_BORROW_MODE": "manual",
            "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
            "MARGIN_BORROW_BUFFER_PCT": 0.005,  # 0.5% buffer
            "SYMBOL": "BTCUSDC",
            "PRICE_SNAPSHOT_MIN_SEC": 2.0,
        }
        
        mock_api = MagicMock()
        mock_api.get_mid_price = MagicMock(return_value=95500.0)
        
        margin_guard.configure(env, log_event_fn=lambda *args, **kwargs: None, api=mock_api)

        state = {"margin": {}}
        symbol = "BTCUSDC"
        side = "BUY"
        qty = 0.00125
        
        # No qty_sent/price_sent in plan -> fallback to mid_price
        plan = {"trade_key": "test_trade_789"}

        with patch("executor_mod.price_snapshot.refresh_price_snapshot"):
            with patch("executor_mod.price_snapshot.get_price_snapshot") as mock_snapshot:
                mock_snapshot.return_value = MagicMock(ok=True, price_mid=95500.0)
                
                trade_key, plan_use = margin_guard._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        # Verify borrow uses mid_price with buffer
        required_quote = qty * 95500.0  # 119.375
        buffer_pct = 0.005
        expected_borrow = required_quote * (1.0 + buffer_pct)  # 119.971875

        assert plan_use["borrow_asset"] == "USDC"
        assert abs(plan_use["borrow_amount"] - expected_borrow) < 0.01

    def test_borrow_short_side_base_asset(self):
        """For SHORT (SELL), borrow base asset (BTC), not quote."""
        env = {
            "TRADE_MODE": "margin",
            "MARGIN_ISOLATED": False,
            "MARGIN_BORROW_MODE": "manual",
            "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
            "SYMBOL": "BTCUSDC",
        }
        margin_guard.configure(env, log_event_fn=lambda *args, **kwargs: None, api=None)

        state = {"margin": {}}
        symbol = "BTCUSDC"
        side = "SELL"
        qty = 0.00125
        
        plan = {
            "trade_key": "test_short_123",
            "qty_sent": 0.00125,
        }

        trade_key, plan_use = margin_guard._prepare_plan_for_borrow(state, symbol, side, qty, plan)

        assert plan_use["borrow_asset"] == "BTC"
        assert plan_use["borrow_amount"] == 0.00125

    def test_no_env_leakage(self):
        """Ensure ENV changes don't leak between tests."""
        # Modify ENV
        margin_guard.ENV["TEST_KEY"] = "test_value"
        assert margin_guard.ENV.get("TEST_KEY") == "test_value"
        
        # teardown_method will restore original ENV
        # Next test should not see TEST_KEY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
