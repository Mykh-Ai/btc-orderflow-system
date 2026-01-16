#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exit_safety.py
Planner-only exit safety logic (no API calls, no state persistence).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, List

from decimal import Decimal, ROUND_FLOOR


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _is_finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(float(x))


def _min_qty(env: Dict[str, Any]) -> float:
    try:
        return float(env.get("MIN_QTY") or 0.0)
    except Exception:
        return 0.0


def _min_notional(env: Dict[str, Any]) -> float:
    # Project uses MIN_NOTIONAL in env for Binance NOTIONAL (e.g. 5 USDC)
    try:
        return float(env.get("MIN_NOTIONAL") or 0.0)
    except Exception:
        return 0.0


def _notional(qty: float, price_now: float) -> float:
    try:
        if qty <= 0.0:
            return 0.0
        if not _is_finite(price_now) or price_now <= 0.0:
            return 0.0
        return float(qty) * float(price_now)
    except Exception:
        return 0.0


def _quantize_qty_floor(qty: float, env: Dict[str, Any]) -> float:
    try:
        step = env.get("QTY_STEP")
        if step is None:
            return 0.0
        step_d = Decimal(str(step))
        if step_d <= 0:
            return 0.0
        units = (Decimal(str(qty)) / step_d).to_integral_value(rounding=ROUND_FLOOR)
        return float(units * step_d)
    except Exception:
        return 0.0


def _collect_cancel_ids(pos: Dict[str, Any]) -> List[int]:
    orders = pos.get("orders") or {}
    ids: List[int] = []
    for key in ("sl", "sl_prev"):
        oid = orders.get(key)
        if oid:
            try:
                ids.append(int(oid))
            except Exception:
                continue
    for key, oid in (orders or {}).items():
        if not key or not str(key).lower().startswith("tp"):
            continue
        if not oid:
            continue
        try:
            ids.append(int(oid))
        except Exception:
            continue
    # de-dup while preserving order
    seen = set()
    uniq: List[int] = []
    for oid in ids:
        if oid in seen:
            continue
        seen.add(oid)
        uniq.append(oid)
    return uniq


def _sl_stop_price(pos: Dict[str, Any], sl_order_payload: Optional[Dict[str, Any]]) -> Optional[float]:
    if isinstance(sl_order_payload, dict):
        sp = sl_order_payload.get("stopPrice")
        sp_f = _as_float(sp, default=0.0)
        if sp_f > 0.0:
            return sp_f
    trail_sl = _as_float(pos.get("trail_sl_price"), default=0.0)
    if trail_sl > 0.0:
        return trail_sl
    prices = pos.get("prices") or {}
    sl = _as_float(prices.get("sl"), default=0.0)
    if sl > 0.0:
        return sl
    return None


def _position_qty(pos: Dict[str, Any], sl_order_payload: Optional[Dict[str, Any]]) -> float:
    if isinstance(sl_order_payload, dict):
        oq = _as_float(sl_order_payload.get("origQty"), default=0.0)
        if oq > 0.0:
            return oq
    # Fallback: derive remaining qty from the executor’s own split logic
    orders = pos.get("orders") or {}
    if pos.get("tp2_done"):
        q3 = _as_float(orders.get("qty3"), default=0.0)
        if q3 > 0.0:
            return q3
    if pos.get("tp1_done"):
        q2 = _as_float(orders.get("qty2"), default=0.0)
        q3 = _as_float(orders.get("qty3"), default=0.0)
        if (q2 + q3) > 0.0:
            return q2 + q3
    qty = _as_float(pos.get("qty"), default=0.0)
    return qty


def sl_watchdog_tick(
    st: Dict[str, Any],
    pos: Dict[str, Any],
    env: Dict[str, Any],
    now_s: float,
    price_now: float,
    sl_order_payload_or_status: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return an action plan for SL fallback or None."""
    if not pos:
        return None
    status = str(pos.get("status") or "").upper()
    if status not in ("OPEN_FILLED",):
        return None

    orders = pos.get("orders") or {}
    sl_id = orders.get("sl")
    if not sl_id:
        return None

    pos_qty = _position_qty(pos, sl_order_payload_or_status)
    if pos_qty <= 0.0:
        return None

    min_qty_f = _min_qty(env)
    if pos_qty <= max(min_qty_f, 0.0):
        return None

    sl_stop = _sl_stop_price(pos, sl_order_payload_or_status)
    if sl_stop is None:
        return None

    if not _is_finite(price_now) or price_now <= 0.0:
        return None

    status = ""
    executed_qty = 0.0
    if isinstance(sl_order_payload_or_status, dict):
        status = str(sl_order_payload_or_status.get("status", "")).upper()
        executed_qty = _as_float(sl_order_payload_or_status.get("executedQty"), default=0.0)

    if status == "FILLED":
        pos["sl_watchdog_first_trigger_s"] = None
        return None

    if executed_qty > 0.0 and status != "FILLED" and not pos.get("sl_watchdog_fired"):
        qty_remaining_raw = max(pos_qty - executed_qty, 0.0)
        qty_remaining = max(_quantize_qty_floor(qty_remaining_raw, env), 0.0)
        qty_quantized = qty_remaining
        qty_step = env.get("QTY_STEP")
        try:
            qty_step_f = float(qty_step)
        except Exception:
            qty_step_f = 0.0
        if qty_remaining <= max(min_qty_f, qty_step_f):
            qty_remaining = 0.0

        # Dust policy: if remaining exists but MARKET close is impossible (qty quantized to 0
        # OR notional < MIN_NOTIONAL), we accept leaving dust and closing slot after cleanup.
        min_notional_f = _min_notional(env)
        remaining_notional_raw = _notional(qty_remaining_raw, price_now)
        remaining_notional_plan = _notional(qty_remaining, price_now)
        if qty_remaining_raw > 0.0 and (
            qty_quantized <= 0.0
            or (qty_quantized > 0.0 and qty_quantized < min_qty_f)
            or (min_notional_f > 0.0 and remaining_notional_raw > 0.0 and remaining_notional_raw < min_notional_f)
        ):
            return {
                "action": "DUST_REMAINDER",
                "reason": "SL_DUST_REMAINDER",
                "qty": 0.0,
                "dust_qty_raw": qty_remaining_raw,
                "dust_qty_quantized": qty_quantized,
                "dust_notional_raw": remaining_notional_raw,
                "min_notional": min_notional_f,
                "min_qty": min_qty_f,
                "price_now": price_now,
                "cancel_order_ids": _collect_cancel_ids(pos),
                "set_fired_on_success": True,
                "events": [
                    {"name": "SL_PARTIAL_DETECTED", "executedQty": executed_qty, "order_id": sl_id},
                    {
                        "name": "SL_DUST_REMAINDER",
                        "qty_raw": qty_remaining_raw,
                        "qty_quantized": qty_quantized,
                        "notional_raw": remaining_notional_raw,
                        "min_notional": min_notional_f,
                        "min_qty": min_qty_f,
                        "price_now": price_now,
                    },
                ],
            }
        return {
            "action": "MARKET_FLATTEN",
            "reason": "SL_PARTIAL_FALLBACK",
            "qty": qty_remaining,
            "side": "SELL" if pos.get("side") == "LONG" else "BUY",
            "cancel_order_ids": _collect_cancel_ids(pos),
            "set_fired_on_success": True,
            "events": [
                {"name": "SL_PARTIAL_DETECTED", "executedQty": executed_qty, "order_id": sl_id},
                {"name": "SL_MARKET_FALLBACK"},
            ],
        }

    is_long = str(pos.get("side")).upper() == "LONG"
    triggered = price_now <= sl_stop if is_long else price_now >= sl_stop

    first_trigger_s = pos.get("sl_watchdog_first_trigger_s")
    if triggered:
        if not first_trigger_s:
            pos["sl_watchdog_first_trigger_s"] = now_s
            first_trigger_s = now_s
        grace = float(env.get("SL_WATCHDOG_GRACE_SEC") or 0.0)
        if (now_s - float(first_trigger_s)) >= grace and not pos.get("sl_watchdog_fired"):
            qty_remaining_raw = pos_qty
            qty_remaining = max(_quantize_qty_floor(qty_remaining_raw, env), 0.0)
            qty_quantized = qty_remaining
            min_notional_f = _min_notional(env)
            rem_notional_raw = _notional(qty_remaining_raw, price_now)
            rem_notional_plan = _notional(qty_remaining, price_now)

            # Dust policy for full-position close: if MARKET is impossible (qty==0 or notional below min),
            # accept leaving dust and close slot after cleanup.
            if qty_remaining_raw > 0.0 and (
                qty_quantized <= 0.0
                or (qty_quantized > 0.0 and qty_quantized < min_qty_f)
                or (min_notional_f > 0.0 and rem_notional_raw > 0.0 and rem_notional_raw < min_notional_f)
            ):
                return {
                    "action": "DUST_REMAINDER",
                    "reason": "SL_DUST_REMAINDER",
                    "qty": 0.0,
                    "dust_qty_raw": qty_remaining_raw,
                    "dust_qty_quantized": qty_quantized,
                    "dust_notional_raw": rem_notional_raw,
                    "min_notional": min_notional_f,
                    "min_qty": min_qty_f,
                    "price_now": price_now,
                    "cancel_order_ids": _collect_cancel_ids(pos),
                    "set_fired_on_success": True,
                    "events": [
                        {
                            "name": "SL_DUST_REMAINDER",
                            "qty_raw": qty_remaining_raw,
                            "qty_quantized": qty_quantized,
                            "notional_raw": rem_notional_raw,
                            "min_notional": min_notional_f,
                            "min_qty": min_qty_f,
                            "price_now": price_now,
                        },
                    ],
                }
            return {
                "action": "MARKET_FLATTEN",
                "reason": "SL_WATCHDOG",
                "qty": qty_remaining,
                "side": "SELL" if is_long else "BUY",
                "cancel_order_ids": _collect_cancel_ids(pos),
                "set_fired_on_success": True,
                "events": [{"name": "SL_MARKET_FALLBACK"}],
            }
    else:
        if first_trigger_s:
            pos["sl_watchdog_first_trigger_s"] = None

    return None


def tp_safety_tick(*args: Any, **kwargs: Any) -> Optional[Dict[str, Any]]:
    """TP safety stub (PR-TP1 will implement)."""
    return None
