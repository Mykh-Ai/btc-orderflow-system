"""Risk math utilities extracted from executor.py.

IMPORTANT: This module is a mechanical extraction. Do not change logic without tests.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from typing import Any, Dict, Tuple

ENV: Dict[str, Any] = {}

def configure(env: Dict[str, Any]) -> None:
    global ENV
    ENV = env

def floor_to_step(x: float, step: Decimal) -> float:
    step_d = Decimal(str(step))
    units = (Decimal(str(x)) / step_d).to_integral_value(rounding=ROUND_FLOOR)
    return float(units * step_d)

def ceil_to_step(x: float, step: Decimal) -> float:
    step_d = Decimal(str(step))
    units = (Decimal(str(x)) / step_d).to_integral_value(rounding=ROUND_CEILING)
    return float(units * step_d)

def round_nearest_to_step(x: float, step: Decimal) -> float:
    step_d = Decimal(str(step))
    units = (Decimal(str(x)) / step_d).to_integral_value(rounding=ROUND_HALF_UP)
    return float(units * step_d)

def _decimals_from_step(step: Decimal) -> int:
    """Number of decimal places implied by a step (tick/lot)."""
    step = Decimal(step)
    return max(0, -step.as_tuple().exponent)

def fmt_price(p: float) -> str:
    """Format price as a string respecting TICK_SIZE."""
    dp = _decimals_from_step(ENV["TICK_SIZE"])
    return f"{p:.{dp}f}"

def fmt_qty(q: float) -> str:
    """Format quantity as a string respecting QTY_STEP (trim trailing zeros)."""
    dp = _decimals_from_step(ENV["QTY_STEP"])
    s = f"{q:.{dp}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s

def round_qty(x: float) -> float:
    """Round a quantity DOWN to the configured qty step."""
    return floor_to_step(x, ENV["QTY_STEP"])


def split_qty_3legs_validate(qty_total_r: float) -> Tuple[float, float, float]:
       # Split strictly in integer 'step units' to avoid float floor artefacts
    step_d = ENV["QTY_STEP"]  # Decimal
    total_units = int((Decimal(str(qty_total_r)) / step_d).to_integral_value(rounding=ROUND_FLOOR))
    if total_units <= 0:
        raise RuntimeError(f"Invalid qty after rounding: qty_total_r={qty_total_r} step={step_d}")

    u1 = total_units // 3
    u2 = total_units // 3
    u3 = total_units - u1 - u2

    # If any of first two legs becomes zero -> degrade to 2 legs (50/50), no trailing leg
    if u1 <= 0 or u2 <= 0:
        u1 = total_units // 2
        u2 = total_units - u1
        u3 = 0

    if (u1 + u2 + u3) != total_units:
        raise RuntimeError(f"Internal split error: units=({u1},{u2},{u3}) total_units={total_units}")

    qty1 = float(Decimal(u1) * step_d)
    qty2 = float(Decimal(u2) * step_d)
    qty3 = float(Decimal(u3) * step_d)
    if qty1 <= 0 or qty2 <= 0 or qty3 < 0:
        raise RuntimeError(f"Invalid qty split after rounding: qty_total={qty_total_r} qty1={qty1} qty2={qty2} step={ENV.get('QTY_STEP')}")
    return qty1, qty2, qty3


def split_qty_3legs_place(qty_total_r: float) -> Tuple[float, float, float]:
       # Split strictly in integer 'step units' to avoid float floor artefacts
    step_d = ENV["QTY_STEP"]  # Decimal
    total_units = int((Decimal(str(qty_total_r)) / step_d).to_integral_value(rounding=ROUND_FLOOR))
    if total_units <= 0:
        raise RuntimeError(f"Invalid qty split after rounding: qty_total_r={qty_total_r} step={step_d}")

    u1 = total_units // 3
    u2 = total_units // 3
    u3 = total_units - u1 - u2

    # If any of first two legs becomes zero -> degrade to 2 legs (50/50), no trailing leg
    if u1 <= 0 or u2 <= 0:
        u1 = total_units // 2
        u2 = total_units - u1
        u3 = 0

    if (u1 + u2 + u3) != total_units:
        raise RuntimeError(f"Internal split error: units=({u1},{u2},{u3}) total_units={total_units}")

    qty1 = float(Decimal(u1) * step_d)
    qty2 = float(Decimal(u2) * step_d)
    qty3 = float(Decimal(u3) * step_d)
    if qty1 <= 0 or qty2 <= 0 or qty3 < 0:
        raise RuntimeError(f"Invalid qty split: qty_total={qty_total_r} qty1={qty1} qty2={qty2} qty3={qty3}")
    return qty1, qty2, qty3
