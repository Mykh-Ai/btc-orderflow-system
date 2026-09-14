from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Mapping, Optional


EVENT = "OPEN"


def _dec(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _plain(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _ratio(distance: Optional[Decimal], risk: Optional[Decimal]) -> Optional[Decimal]:
    if distance is None or risk is None or risk <= 0:
        return None
    return distance / risk


def build_trade_open_payload(
    position: Mapping[str, Any],
    *,
    symbol: str,
    order: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the OPEN webhook payload and human-readable Telegram text."""
    prices = position.get("prices")
    prices = prices if isinstance(prices, Mapping) else {}

    entry = _dec(prices.get("entry", position.get("entry")))
    sl = _dec(prices.get("sl"))
    tp1 = _dec(prices.get("tp1"))
    tp2 = _dec(prices.get("tp2"))

    risk = abs(entry - sl) if entry is not None and sl is not None else None
    tp1_distance = abs(tp1 - entry) if entry is not None and tp1 is not None else None
    tp2_distance = abs(tp2 - entry) if entry is not None and tp2 is not None else None
    risk_percent = (risk / entry * Decimal("100")) if risk is not None and entry and entry > 0 else None
    tp1_r = _ratio(tp1_distance, risk)
    tp2_r = _ratio(tp2_distance, risk)

    entry_text = _plain(entry) or "not_available"
    sl_text = _plain(sl) or "not_available"
    tp1_text = _plain(tp1) or "not_available"
    tp2_text = _plain(tp2) or "not_available"
    risk_text = _plain(risk) or "not_available"
    risk_pct_text = f"{risk_percent:.2f}%" if risk_percent is not None else "not_available"
    tp1_r_text = f"{tp1_r:.2f}R" if tp1_r is not None else "not_available"
    tp2_r_text = f"{tp2_r:.2f}R" if tp2_r is not None else "not_available"

    side = str(position.get("side") or "")
    qty = position.get("qty")
    lines = [
        "Executor Alert",
        f"Type: {EVENT}",
        f"Symbol: {symbol}",
        f"Side: {side}",
        f"Volume: {qty}",
        f"Entry: {entry_text}",
        f"Stop-loss: {sl_text}",
        f"R (entry to SL): {risk_text} ({risk_pct_text})",
        f"Take profit 1: {tp1_text} ({tp1_r_text})",
        f"Take profit 2: {tp2_text} ({tp2_r_text})",
    ]
    text = "\n".join(lines)

    return {
        "event": EVENT,
        "type": EVENT,
        "mode": position.get("mode", "live"),
        "symbol": symbol,
        "side": side,
        "entry": float(entry) if entry is not None else None,
        "qty": qty,
        "sl": float(sl) if sl is not None else None,
        "tp1": float(tp1) if tp1 is not None else None,
        "tp2": float(tp2) if tp2 is not None else None,
        "r": float(risk) if risk is not None else None,
        "risk_distance": float(risk) if risk is not None else None,
        "risk_percent": float(risk_percent) if risk_percent is not None else None,
        "tp1_distance": float(tp1_distance) if tp1_distance is not None else None,
        "tp2_distance": float(tp2_distance) if tp2_distance is not None else None,
        "tp1_r": float(tp1_r) if tp1_r is not None else None,
        "tp2_r": float(tp2_r) if tp2_r is not None else None,
        "order": dict(order) if isinstance(order, Mapping) else order,
        "telegram_text": text,
        "message": text,
        "text": text,
    }


__all__ = ["build_trade_open_payload"]
