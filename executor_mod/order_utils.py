#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small order payload helpers shared by executor wrappers."""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
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


def validated_executed_qty(order: Any) -> Decimal:
    """A terminal order can release ownership only with explicit quantity evidence."""
    value = order.get("executedQty") if isinstance(order, dict) else None
    if value is None or isinstance(value, bool):
        raise ValueError("Unknown executedQty for terminal entry")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid executedQty for terminal entry") from exc
    if not quantity.is_finite() or quantity < 0:
        raise ValueError("Invalid executedQty for terminal entry")
    approximate = float(quantity)
    if not math.isfinite(approximate) or (quantity > 0 and approximate == 0):
        raise ValueError("Unrepresentable executedQty for terminal entry")
    return quantity
