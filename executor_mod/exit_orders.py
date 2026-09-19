"""Exit order validation and placement helpers extracted from executor.py."""

from __future__ import annotations

import math
import time
from contextlib import suppress
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, Mapping


def validate_exit_plan(
    symbol: str,
    side: str,
    qty_total: float,
    prices: Dict[str, float],
    *,
    env: Mapping[str, Any],
    round_qty_fn: Callable[[float], float],
    split_qty_3legs_validate_fn: Callable[[float], tuple[float, float, float]],
) -> Dict[str, Any]:
    """Validate exits inputs before placing orders.

    Goals:
      - Fail fast with a clear message BEFORE we hit Binance errors
      - Prevent silent rounding/formatting surprises
      - Guarantee qty split does not round to zero
    """
    _ = symbol
    if not isinstance(prices, dict):
        raise RuntimeError(f"prices must be dict, got {type(prices).__name__}")

    required = ("entry", "sl", "tp1", "tp2")
    missing = [k for k in required if k not in prices or prices.get(k) is None]
    if missing:
        raise RuntimeError(f"Missing price keys: {missing}")

    # Normalize to floats
    p: Dict[str, float] = {}
    for k in required:
        try:
            p[k] = float(prices[k])
        except Exception:
            raise RuntimeError(f"Invalid price for {k}: {prices.get(k)!r}")

    # Basic sanity
    for k, v in p.items():
        if not math.isfinite(v) or v <= 0:
            raise RuntimeError(f"Invalid price {k}={v}")

    side_u = str(side).upper()
    if side_u not in ("LONG", "SHORT"):
        raise RuntimeError(f"Invalid side={side!r} (expected LONG/SHORT)")

    # Enforce directional ordering (best-effort safety)
    if side_u == "LONG":
        if not (p["sl"] < p["entry"] < p["tp1"] <= p["tp2"]):
            raise RuntimeError(f"Bad LONG price ordering: sl<{p['sl']}, entry<{p['entry']}, tp1<{p['tp1']}, tp2<{p['tp2']}")
    else:  # SHORT
        if not (p["sl"] > p["entry"] > p["tp1"] >= p["tp2"]):
            raise RuntimeError(f"Bad SHORT price ordering: sl>{p['sl']}, entry>{p['entry']}, tp1>{p['tp1']}, tp2>{p['tp2']}")

    # Tick alignment check (Decimal, tolerant) + normalize to exact tick
    tick_s = str(env.get("TICK_SIZE", "0.01"))
    tick = Decimal(tick_s)

    # tolerance = tiny fraction of tick to ignore float noise
    # (you can tighten/loosen; 1e-6 tick is usually safe)
    tol = tick / Decimal("1000000")

    def D(x) -> Decimal:
        # IMPORTANT: never Decimal(float) directly
        return Decimal(str(x))

    def align_to_tick(v: Decimal) -> Decimal:
        # nearest tick (HALF_UP is fine for validation stage)
        steps = (v / tick).to_integral_value(rounding=ROUND_HALF_UP)
        return steps * tick

    for k, v in p.items():
        vd = D(v)
        aligned = align_to_tick(vd)

        # if truly off-tick -> fail fast
        if abs(aligned - vd) > tol:
            raise RuntimeError(
                f"Price not aligned to tick: {k}={v} tick={tick_s} (aligned={float(aligned)})"
           )

        # normalize to exact aligned value to avoid later precision surprises
        p[k] = float(aligned)


    # Qty checks & split checks (mirrors place_exits_v15 but gives clearer errors)
    try:
        qt = float(qty_total)
    except Exception:
        raise RuntimeError(f"Invalid qty_total: {qty_total!r}")
    if not math.isfinite(qt) or qt <= 0:
        raise RuntimeError(f"Invalid qty_total={qt}")

    qty_total_r = round_qty_fn(qt)
    min_qty = float(env.get("MIN_QTY", 0.0))
    if qty_total_r < min_qty:
        raise RuntimeError(f"qty_total too small after rounding: qty_total={qt} -> {qty_total_r} (min_qty={min_qty})")
    # Split strictly in integer 'step units' to avoid float floor artefacts
    qty1, qty2, qty3 = split_qty_3legs_validate_fn(qty_total_r)
    # Min notional safety (optional but helpful)
    min_notional = float(env.get("MIN_NOTIONAL", 0.0))
    if min_notional > 0:
        worst_price = min(p.values())
        notional = worst_price * qty_total_r
        if notional < min_notional:
            raise RuntimeError(f"MinNotional fail (worst-case): price={worst_price} qty={qty_total_r} notional={notional} < {min_notional}")

    return {
        "qty_total_r": qty_total_r,
        "qty1": qty1,
        "qty2": qty2,
        "qty3": qty3,
        "prices": p,
    }


def is_limit_maker_reject(exc: Exception) -> bool:
    """Detect Binance LIMIT_MAKER rejection (would immediately match)."""
    msg = str(exc).lower()
    return (
        "would immediately match" in msg
        or "immediately match and take" in msg
        or '"code":-2010' in msg
        or "code: -2010" in msg
    )


def place_limit_maker_then_limit(payload: dict, *, place_order_raw_fn: Callable[[dict], dict], log_event_fn: Callable[..., None]) -> dict:
    """Try LIMIT_MAKER first; if rejected, retry as LIMIT GTC."""
    try:
        return place_order_raw_fn(payload)
    except Exception as e:
        if not is_limit_maker_reject(e):
            raise
        # fallback
        payload2 = dict(payload)
        payload2["type"] = "LIMIT"
        payload2["timeInForce"] = "GTC"
        cid = str(payload.get("newClientOrderId") or "")
        if cid:
            payload2["newClientOrderId"] = (cid + "_GTC")[:36]
        log_event_fn("LIMIT_MAKER_REJECT", reason=str(e))
        return place_order_raw_fn(payload2)


def place_exits_v15(
    symbol: str,
    side: str,
    qty_total: float,
    prices: Dict[str, float],
    *,
    env: Mapping[str, Any],
    place_order_raw_fn: Callable[[dict], dict],
    cancel_order_fn: Callable[[str, int], dict],
    log_event_fn: Callable[..., None],
    round_qty_fn: Callable[[float], float],
    split_qty_3legs_place_fn: Callable[[float], tuple[float, float, float]],
    fmt_qty_fn: Callable[[float], str],
    fmt_price_fn: Callable[[float], str],
    time_fn: Callable[[], float] = time.time,
) -> Dict[str, Any]:
    """Place TP1 + TP2 + SL for V1.5 (no OCO)."""
    # Ensure qty is aligned to lot step before splitting
    qty_total_r = round_qty_fn(qty_total)

    # Split strictly in integer 'step units' to avoid float floor artefacts
    qty1, qty2, qty3 = split_qty_3legs_place_fn(qty_total_r)
    # Binance expects strings for precise formatting
    qty_total_s = fmt_qty_fn(qty_total_r)
    qty1_s = fmt_qty_fn(qty1)
    qty2_s = fmt_qty_fn(qty2)

    tp1_s = fmt_price_fn(float(prices["tp1"]))
    tp2_s = fmt_price_fn(float(prices["tp2"]))

    exit_side = "SELL" if side == "LONG" else "BUY"

    # --- SL first (locks full qty, avoids insufficient balance for LONG exits) ---
    stop_p = float(prices["sl"])
    tick = float(env["TICK_SIZE"])
    gap_ticks = max(1, int(env.get("SL_LIMIT_GAP_TICKS") or 0))
    gap = tick * float(gap_ticks)
    limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
    sl_stop_s = fmt_price_fn(stop_p)
    sl_price_s = fmt_price_fn(limit_p)
    if sl_price_s == sl_stop_s:
        sl_price_s = fmt_price_fn((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))

    placed: Dict[str, int] = {}
    try:
        sl = place_order_raw_fn({
            "symbol": symbol,
            "side": exit_side,
            "type": "STOP_LOSS_LIMIT",
            "quantity": qty_total_s,
            "stopPrice": sl_stop_s,
            "price": sl_price_s,
            "timeInForce": "GTC",
            "newClientOrderId": f"EX_SL_{int(time_fn())}",
        })
        placed["sl"] = sl["orderId"]

        tp1 = place_limit_maker_then_limit({
            "symbol": symbol,
            "side": exit_side,
            "type": "LIMIT_MAKER",
            "quantity": qty1_s,
            "price": tp1_s,
            "newClientOrderId": f"EX_TP1_{int(time_fn())}",
        }, place_order_raw_fn=place_order_raw_fn, log_event_fn=log_event_fn)
        placed["tp1"] = tp1["orderId"]

        tp2 = place_limit_maker_then_limit({
            "symbol": symbol,
            "side": exit_side,
            "type": "LIMIT_MAKER",
            "quantity": qty2_s,
            "price": tp2_s,
            "newClientOrderId": f"EX_TP2_{int(time_fn())}",
        }, place_order_raw_fn=place_order_raw_fn, log_event_fn=log_event_fn)
        placed["tp2"] = tp2["orderId"]

    except Exception:
        # Rollback: cancel any already placed orders to prevent orphans/duplicates on retry
        for oid in placed.values():
            with suppress(Exception):
                cancel_order_fn(symbol, oid)
        raise

    return {
        "tp1": tp1["orderId"],
        "tp2": tp2["orderId"],
        "sl": sl["orderId"],
        "qty1": qty1,
        "qty2": qty2,
        "qty3": qty3,
    }
