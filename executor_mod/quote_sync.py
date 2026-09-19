"""USDT feed to USDC execution quote safety, with injected runtime readers."""
from __future__ import annotations
import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict
from executor_mod.risk_math import ceil_to_step, floor_to_step


class QuoteSyncError(RuntimeError):
    """BTCUSDT structural price could not be safely synchronized to BTCUSDC."""


@dataclass(frozen=True)

class UsdtUsdcQuoteSnapshot:
    mid_usdt: float
    mid_usdc: float
    ratio: float
    observed_at_utc: str


@dataclass(frozen=True)

class TrailingStopQuote:
    stop_usdt: float
    stop_usdc: float
    snapshot: UsdtUsdcQuoteSnapshot


def get_usdt_usdc_quote_snapshot(
    *, env: Dict[str, Any], get_mid_price_fn: Callable[[str], float],
    iso_utc_fn: Callable[[], str],
) -> UsdtUsdcQuoteSnapshot:
    """Read a same-cycle BTCUSDT/BTCUSDC ratio and enforce a sanity band."""

    try:
        mid_usdt = float(get_mid_price_fn("BTCUSDT"))
        mid_usdc = float(get_mid_price_fn("BTCUSDC"))
    except Exception as exc:
        raise QuoteSyncError(f"quote lookup failed: {exc}") from exc
    if not math.isfinite(mid_usdt) or not math.isfinite(mid_usdc) or mid_usdt <= 0 or mid_usdc <= 0:
        raise QuoteSyncError(f"invalid mids: BTCUSDT={mid_usdt} BTCUSDC={mid_usdc}")
    ratio = float(Decimal(str(mid_usdc)) / Decimal(str(mid_usdt)))
    ratio_min = float(env.get("USDT_USDC_RATIO_MIN") or 0.95)
    ratio_max = float(env.get("USDT_USDC_RATIO_MAX") or 1.05)
    if not (math.isfinite(ratio_min) and math.isfinite(ratio_max) and 0 < ratio_min <= ratio_max):
        raise QuoteSyncError("invalid USDT/USDC ratio sanity band")
    if not math.isfinite(ratio) or ratio < ratio_min or ratio > ratio_max:
        raise QuoteSyncError(
            f"ratio outside sanity band: ratio={ratio} band=[{ratio_min},{ratio_max}]"
        )
    return UsdtUsdcQuoteSnapshot(
        mid_usdt=mid_usdt,
        mid_usdc=mid_usdc,
        ratio=ratio,
        observed_at_utc=iso_utc_fn(),
    )


def convert_stop_usdt_to_usdc(stop_usdt: float, side: str, ratio: float, *, env: Dict[str, Any]) -> float:
    """Convert a structural stop and round outward in the BTCUSDC quote space."""

    try:
        stop = Decimal(str(stop_usdt))
        conversion = Decimal(str(ratio))
        if not stop.is_finite() or stop <= 0 or not conversion.is_finite() or conversion <= 0:
            raise ValueError("invalid source stop or ratio")
        raw = float(stop * conversion)
    except (ValueError, ArithmeticError) as exc:
        raise QuoteSyncError(str(exc)) from exc
    if not math.isfinite(raw) or raw <= 0:
        raise QuoteSyncError(f"invalid converted stop: stop_usdt={stop_usdt} ratio={ratio}")
    if side == "LONG":
        return floor_to_step(raw, env["TICK_SIZE"])
    if side == "SHORT":
        return ceil_to_step(raw, env["TICK_SIZE"])
    raise QuoteSyncError(f"invalid side={side}")


def validate_stop_against_usdc_mid(side: str, stop_usdc: float, mid_usdc: float, *, env: Dict[str, Any]) -> None:
    if not math.isfinite(stop_usdc) or stop_usdc <= 0 or not math.isfinite(mid_usdc) or mid_usdc <= 0:
        raise QuoteSyncError("invalid stop or BTCUSDC mid")
    tick = float(env["TICK_SIZE"])
    if side == "LONG" and stop_usdc > mid_usdc - tick:
        raise QuoteSyncError(
            f"LONG stop not below BTCUSDC mid: stop={stop_usdc} mid={mid_usdc}"
        )
    if side == "SHORT" and stop_usdc < mid_usdc + tick:
        raise QuoteSyncError(
            f"SHORT stop not above BTCUSDC mid: stop={stop_usdc} mid={mid_usdc}"
        )
    if side not in ("LONG", "SHORT"):
        raise QuoteSyncError(f"invalid side={side}")
