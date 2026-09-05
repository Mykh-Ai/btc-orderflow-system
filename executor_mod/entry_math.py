"""Entry sizing and price decision helpers extracted from executor.py."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from executor_mod.risk_math import ceil_to_step, floor_to_step


ENV: Dict[str, Any] = {}


def configure(env: Dict[str, Any]) -> None:
    global ENV
    ENV = env


def build_entry_price(kind: str, close_price: float) -> float:
    """Entry price builder used for live.

    For breakout-style entries:
      - long  -> above close
      - short -> below close

    Rounding is *directional* so we don't accidentally make the trigger harder by rounding.
    """
    raw = close_price + ENV["ENTRY_OFFSET_USD"] if kind == "long" else close_price - ENV["ENTRY_OFFSET_USD"]

    if kind == "long":
        # keep it above close by at least 1 tick
        raw = max(raw, close_price + float(ENV["TICK_SIZE"]))
        return floor_to_step(raw, ENV["TICK_SIZE"])
    else:
        # keep it below close by at least 1 tick
        raw = min(raw, close_price - float(ENV["TICK_SIZE"]))
        return ceil_to_step(raw, ENV["TICK_SIZE"])


def notional_to_qty(entry: float, usd: float) -> float:
    if entry <= 0:
        return 0.0
    qty = usd / entry
    qty = floor_to_step(qty, ENV["QTY_STEP"])
    return qty


def validate_qty(qty: float, entry: float) -> bool:
    if qty <= 0:
        return False
    if Decimal(str(qty)) < ENV["MIN_QTY"]:
        return False
    if qty * entry < ENV["MIN_NOTIONAL"]:
        return False
    return True


def swing_stop_far(df: Any, i: int, side: str, entry: float) -> float:
    """Return a stop that is FARTHER from entry (vs near).

    side: BUY for long, SELL for short

    - BUY: choose min(pct_sl, swing_low)
    - SELL: choose max(pct_sl, swing_high)
    - swings are based on LowPrice/HiPrice when available (v2), else fall back to price.
    """
    pct_sl = entry * (1 - ENV["SL_PCT"]) if side == "BUY" else entry * (1 + ENV["SL_PCT"])

    if i < 0 or i >= len(df):
        sl = pct_sl
    else:
        lookback = df.iloc[max(0, i - ENV["SWING_MINS"]): i + 1]
        if side == "BUY":
            swing_col = "LowPrice" if "LowPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.min())
            sl = min(pct_sl, swing)
        else:
            swing_col = "HiPrice" if "HiPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.max())
            sl = max(pct_sl, swing)

    # Safety: enforce correct side and rounding
    if side == "BUY":
        sl = min(sl, entry - float(ENV["TICK_SIZE"]))
    else:
        sl = max(sl, entry + float(ENV["TICK_SIZE"]))

    return floor_to_step(sl, ENV["TICK_SIZE"]) if side == "BUY" else ceil_to_step(sl, ENV["TICK_SIZE"])


def compute_tps(entry: float, sl: float, side: str) -> List[float]:
    """TP list based on the *real* risk (entry <-> SL).

    Rounding is directional:
      - BUY (long): TP rounded down (slightly easier to hit)
      - SELL (short): TP rounded up (slightly easier to hit)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return []

    tps: List[float] = []
    for rmult in ENV["TP_R_LIST"]:
        if side == "BUY":
            tp_raw = entry + rmult * risk
            tp = floor_to_step(tp_raw, ENV["TICK_SIZE"])
        else:
            tp_raw = entry - rmult * risk
            tp = ceil_to_step(tp_raw, ENV["TICK_SIZE"])
        tps.append(tp)
    return tps


def _planb_market_allowed(posi: Dict[str, Any], px_exec: float) -> Tuple[bool, str, Dict[str, Any]]:
    """Guard against chasing far away from planned entry.
    Returns (allowed, reason, info).
    """
    try:
        prices = posi.get("prices") or {}
        entry = float(prices.get("entry"))
        sl = float(prices.get("sl"))
        tp1 = float(prices.get("tp1"))
    except Exception:
        return False, "bad_prices", {}
    if not (math.isfinite(entry) and math.isfinite(sl) and entry > 0 and sl > 0):
        return False, "bad_prices", {"entry": entry, "sl": sl}

    risk = abs(entry - sl)
    r_mult = float(ENV.get("PLANB_MAX_DEV_R_MULT") or 0.0)
    max_usd = float(ENV.get("PLANB_MAX_DEV_USD") or 0.0)
    max_dev = max(risk * r_mult, max_usd) if max_usd > 0 else risk * r_mult

    dev = abs(px_exec - entry)
    info = {"px_exec": px_exec, "entry": entry, "sl": sl, "risk": risk, "dev": dev, "max_dev": max_dev}

    if max_dev > 0 and dev > max_dev:
        return False, "deviation_too_large", info

    if ENV.get("PLANB_ABORT_IF_PAST_TP1", True):
        side_txt = str(posi.get("side") or "").upper()
        if math.isfinite(tp1) and tp1 > 0:
            if side_txt == "LONG" and px_exec >= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info
            if side_txt == "SHORT" and px_exec <= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info

    return True, "ok", info
