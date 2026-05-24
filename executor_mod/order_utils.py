#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small order payload helpers shared by executor wrappers."""
from __future__ import annotations

from typing import Any, Optional


def oid_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def avg_fill_price(order: Any) -> Optional[float]:
    """Average fill price from an order payload when possible."""
    try:
        exq = float(order.get("executedQty") or 0.0)
        cq = float(order.get("cummulativeQuoteQty") or order.get("cumulativeQuoteQty") or 0.0)
        if exq > 0 and cq > 0:
            return cq / exq
    except Exception:
        return None
    return None
