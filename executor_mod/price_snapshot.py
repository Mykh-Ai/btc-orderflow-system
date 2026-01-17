#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""price_snapshot.py
In-memory mid-price snapshot to reduce redundant Binance bookTicker API calls.

Goals:
- Single source of truth for mid-price within executor process
- Throttled refresh: only call get_mid_price if snapshot is stale
- Consumers (SL watchdog, trailing fallback, margin_guard) read from snapshot

Pattern follows exchange_snapshot.py design (singleton, throttled refresh).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

# Optional log callback (configured by executor.py)
_log_event_fn: Optional[Callable] = None


def configure(log_event_fn: Optional[Callable] = None) -> None:
    """Configure module dependencies.

    Args:
        log_event_fn: Optional function to log events (e.g., notifications.log_event)
    """
    global _log_event_fn
    _log_event_fn = log_event_fn


class PriceSnapshot:
    """In-memory snapshot of mid-price from bookTicker."""

    def __init__(self) -> None:
        self.ts_updated: float = 0.0
        self.ok: bool = False
        self.error: Optional[str] = None
        self.price_mid: float = 0.0
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

    def to_dict(self) -> Dict[str, Any]:
        """Export snapshot as dict for logging/debugging."""
        return {
            "ts_updated": self.ts_updated,
            "freshness_sec": self.freshness_sec(),
            "ok": self.ok,
            "error": self.error,
            "source": self.source,
            "symbol": self.symbol,
            "price_mid": self.price_mid,
        }


# Global singleton instance
_snapshot = PriceSnapshot()


def get_price_snapshot() -> PriceSnapshot:
    """Return the global PriceSnapshot instance."""
    return _snapshot


def reset_snapshot_for_tests() -> None:
    """Tests only: reset the global PriceSnapshot to a pristine state."""
    global _snapshot
    _snapshot.ts_updated = 0.0
    _snapshot.ok = False
    _snapshot.error = None
    _snapshot.source = ""
    _snapshot.symbol = ""
    _snapshot.price_mid = 0.0


def refresh_price_snapshot(
    symbol: str,
    source: str,
    get_mid_price_fn: Callable[[str], float],
    min_interval_sec: float = 0.0,
) -> bool:
    """Refresh global snapshot if not fresh.

    Args:
        symbol: Trading symbol (e.g., "BTCUSDC")
        source: Source identifier (e.g., "watchdog", "trailing", "margin")
        get_mid_price_fn: Callable that returns mid-price float (e.g., binance_api.get_mid_price)
        min_interval_sec: Minimum seconds between refreshes (throttle)

    Returns:
        True if snapshot was refreshed, False if skipped (still fresh)
    """
    global _snapshot

    # Throttle: skip refresh if snapshot is still fresh
    if min_interval_sec > 0 and _snapshot.is_fresh(min_interval_sec):
        return False

    # Update timestamp first to avoid hammering on repeated errors
    _snapshot.ts_updated = time.time()
    _snapshot.symbol = symbol
    _snapshot.source = source

    try:
        mid_price = get_mid_price_fn(symbol)
        _snapshot.price_mid = float(mid_price)
        _snapshot.ok = True
        _snapshot.error = None

        # Log successful refresh (optional, only if configured)
        if _log_event_fn:
            _log_event_fn("PRICE_SNAPSHOT_REFRESH", symbol=symbol, source=source, ok=True, price_mid=float(mid_price))
    except Exception as e:
        _snapshot.price_mid = 0.0
        _snapshot.ok = False
        _snapshot.error = str(e)

        # Log failed refresh (optional, only if configured)
        if _log_event_fn:
            _log_event_fn("PRICE_SNAPSHOT_REFRESH", symbol=symbol, source=source, ok=False, error=str(e))

    return True
