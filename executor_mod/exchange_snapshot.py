#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exchange_snapshot.py
In-memory exchange state snapshot to gate openOrders polling.

Goals:
- Single source of truth for openOrders within executor process
- Refresh only when position.status == "OPEN" in manage loop
- Consumers (baseline_policy, invariants) read from snapshot instead of calling API

IMPORTANT: This module caches ONLY openOrders API calls.
It does NOT cache or gate:
- margin_account / get_margin_debt_snapshot (used by I13 invariant)
- spot account balance queries
- order status checks (check_order_status)
- Any other Binance API endpoints

I13 invariant checks are EXEMPT from this caching - they use direct
API calls for margin debt verification with their own rate-limiting.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


class ExchangeSnapshot:
    """In-memory snapshot of exchange state (primarily openOrders)."""

    def __init__(self) -> None:
        self.ts_updated: float = 0.0
        self.ok: bool = False
        self.error: Optional[str] = None
        self.open_orders: Optional[List[Dict[str, Any]]] = None
        self.source: str = ""
        self.symbol: str = ""

    def freshness_sec(self) -> float:
        """Return age of snapshot in seconds."""
        if self.ts_updated <= 0:
            return float("inf")
        return time.time() - self.ts_updated

    def is_fresh(self, max_age_sec: float) -> bool:
        """Check if snapshot is fresh enough."""
        return self.freshness_sec() < max_age_sec

    def refresh(
        self,
        symbol: str,
        source: str,
        open_orders_fn: Any,
    ) -> None:
        """Refresh snapshot by calling openOrders API.
        
        Args:
            symbol: Trading symbol
            source: Source identifier (e.g., "manage", "sync")
            open_orders_fn: Callable that returns list of open orders
        """
        self.ts_updated = time.time()
        self.symbol = symbol
        self.source = source
        
        try:
            self.open_orders = open_orders_fn(symbol)
            self.ok = True
            self.error = None
        except Exception as e:
            self.open_orders = None
            self.ok = False
            self.error = str(e)

    def get_orders(self) -> List[Dict[str, Any]]:
        """Return open orders list (empty if not available)."""
        if self.open_orders is None:
            return []
        return self.open_orders

    def to_dict(self) -> Dict[str, Any]:
        """Export snapshot as dict for logging/debugging."""
        return {
            "ts_updated": self.ts_updated,
            "freshness_sec": self.freshness_sec(),
            "ok": self.ok,
            "error": self.error,
            "source": self.source,
            "symbol": self.symbol,
            "order_count": len(self.open_orders) if self.open_orders else 0,
        }


# Global singleton instance
_snapshot = ExchangeSnapshot()


def get_snapshot() -> ExchangeSnapshot:
    """Return the global ExchangeSnapshot instance."""
    return _snapshot


def reset_snapshot_for_tests() -> None:
    """Tests only: reset the global ExchangeSnapshot to a pristine state."""
    global _snapshot
    _snapshot.ts_updated = 0.0
    _snapshot.ok = False
    _snapshot.error = None
    _snapshot.source = ""
    _snapshot.symbol = ""
    _snapshot.open_orders = None


def refresh_snapshot(
    symbol: str,
    source: str,
    open_orders_fn: Any,
    min_interval_sec: float = 0.0,
) -> bool:
    """Refresh global snapshot if not fresh.
    
    Returns:
        True if snapshot was refreshed, False if skipped (still fresh)
    """
    global _snapshot
    
    if min_interval_sec > 0 and _snapshot.is_fresh(min_interval_sec):
        return False
    
    _snapshot.refresh(symbol, source, open_orders_fn)
    return True
