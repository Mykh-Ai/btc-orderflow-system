from __future__ import annotations

from .contracts import TradeLeg


def gross_for_leg(side: str, qty: float, entry: float, exit_price: float) -> float:
    return qty * (exit_price - entry) if side == "LONG" else qty * (entry - exit_price)


def calculate_costs(
    *,
    qty_total: float,
    entry_price: float,
    legs: list[TradeLeg],
    commission_rate: float,
    entry_slippage_bps: float,
    exit_slippage_bps: float,
    stop_slippage_bps: float,
) -> tuple[float, float, float]:
    entry_turnover = qty_total * entry_price
    exit_turnover = sum(leg.qty * leg.exit_price for leg in legs)
    turnover = entry_turnover + exit_turnover
    commission = turnover * commission_rate
    slippage = entry_turnover * entry_slippage_bps / 10_000.0
    for leg in legs:
        rate = stop_slippage_bps if leg.leg_type in {"INITIAL_STOP", "BREAKEVEN_STOP", "TRAILING_STOP"} else exit_slippage_bps
        slippage += leg.qty * leg.exit_price * rate / 10_000.0
    return turnover, commission, slippage
