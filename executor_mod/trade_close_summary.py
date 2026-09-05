"""Human-readable trade close summary notifications.

This module is formatting/accounting-only. It does not mutate trading state and
does not fetch exchange data.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional


EVENT = "TRADE_CLOSED_SUMMARY"
ORDER_ROLES = ("tp1", "tp2", "final_sl")


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _dec_str(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(value, "f")


def _money(value: Optional[Decimal]) -> str:
    if value is None:
        return "not_available"
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "+" if rounded > 0 else ""
    return f"{sign}{format(rounded, 'f')}"


def _qty(value: Optional[Decimal]) -> str:
    if value is None:
        return "not_available"
    return format(value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP), "f")


def _price(value: Optional[Decimal]) -> str:
    if value is None:
        return "not_available"
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _role_label(role: str) -> str:
    return {
        "tp1": "TP1",
        "tp2": "TP2",
        "final_sl": "Final SL",
    }.get(role, role)


def _lifecycle_label(value: Any) -> str:
    text = str(value or "").strip()
    return {
        "plain_sl": "Plain SL",
        "tp1_sl": "TP1 + SL",
        "tp1_tp2": "TP1 + TP2",
        "tp1_tp2_trailing_stop": "TP1 + TP2 + trailing SL",
        "manual_or_unknown": "Manual / unknown",
    }.get(text, text or "not_available")


def _commission_by_asset(snapshot: Dict[str, Any]) -> Dict[str, Decimal]:
    fees = snapshot.get("fees") if isinstance(snapshot, dict) else {}
    raw = (fees or {}).get("commission_by_asset") or {}
    out: Dict[str, Decimal] = {}
    for asset, amount in raw.items():
        dec = _dec(amount)
        if asset and dec:
            out[str(asset).upper()] = out.get(str(asset).upper(), Decimal("0")) + dec
    if out:
        return out

    for summary in ((snapshot.get("fill_summaries") or {}).values()):
        if not isinstance(summary, dict):
            continue
        for asset, amount in (summary.get("commission_by_asset") or {}).items():
            dec = _dec(amount)
            if asset and dec:
                out[str(asset).upper()] = out.get(str(asset).upper(), Decimal("0")) + dec
    return out


def _commission_text(commissions: Dict[str, Decimal]) -> str:
    if not commissions:
        return "not_available"
    return ", ".join(f"{_dec_str(amount)} {asset}" for asset, amount in sorted(commissions.items()))


def _gross_for_leg(side: str, entry_price: Decimal, exit_price: Decimal, qty: Decimal) -> Decimal:
    if side == "SHORT":
        return qty * (entry_price - exit_price)
    return qty * (exit_price - entry_price)


def calculate_operational_pnl(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate notification-grade gross PnL from snapshot fill summaries."""
    summaries = snapshot.get("fill_summaries") or {}
    entry_summary = summaries.get("entry") or {}
    entry_price = _dec(entry_summary.get("avg_price"))
    side = str(((snapshot.get("local_last_closed") or {}).get("side") or "")).strip().upper()
    if side not in ("LONG", "SHORT"):
        side = ""

    legs: List[Dict[str, Any]] = []
    gross_total = Decimal("0")
    total_closed_qty = Decimal("0")
    total_exit_quote_qty = Decimal("0")

    for role in ORDER_ROLES:
        summary = summaries.get(role) or {}
        qty = _dec(summary.get("total_qty"))
        price = _dec(summary.get("avg_price"))
        quote_qty = _dec(summary.get("total_quote_qty"))
        if quote_qty is not None:
            total_exit_quote_qty += quote_qty
        if qty is not None:
            total_closed_qty += qty

        gross = None
        if side and entry_price is not None and price is not None and qty is not None:
            gross = _gross_for_leg(side, entry_price, price, qty)
            gross_total += gross

        legs.append({
            "role": role,
            "label": _role_label(role),
            "order_id": ((snapshot.get("orders") or {}).get(role) or {}).get("order_id"),
            "price": _dec_str(price),
            "qty": _dec_str(qty),
            "quote_qty": _dec_str(quote_qty),
            "gross_pnl_usdc": _dec_str(gross),
        })

    gross_available = any(_dec(leg.get("gross_pnl_usdc")) is not None for leg in legs)
    commissions = _commission_by_asset(snapshot)
    return {
        "side": side or None,
        "entry_avg_price": _dec_str(entry_price),
        "position_qty": entry_summary.get("total_qty"),
        "entry_quote_qty": entry_summary.get("total_quote_qty"),
        "legs": legs,
        "total_closed_qty": _dec_str(total_closed_qty) if total_closed_qty > 0 else None,
        "total_exit_quote_qty": _dec_str(total_exit_quote_qty) if total_exit_quote_qty > 0 else None,
        "gross_pnl_usdc": _dec_str(gross_total) if gross_available else None,
        "commission_by_asset": {asset: _dec_str(amount) for asset, amount in sorted(commissions.items())},
    }


def build_trade_closed_summary_payload(
    snapshot: Dict[str, Any],
    *,
    commission_usdc_approx: Optional[Any] = None,
    commission_valuation_source: Optional[str] = None,
    commission_valuation_symbol: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(snapshot, dict) or not snapshot:
        return None

    pnl = calculate_operational_pnl(snapshot)
    last_closed = snapshot.get("local_last_closed") or {}
    symbol = str(snapshot.get("symbol") or last_closed.get("symbol") or "")
    side = pnl.get("side") or str(last_closed.get("side") or "")
    trade_key = str(snapshot.get("trade_key") or last_closed.get("trade_key") or "")
    lifecycle_class = str(snapshot.get("lifecycle_class") or "")
    close_reason = str(last_closed.get("reason") or "")

    commission_usdc = _dec(commission_usdc_approx)
    gross = _dec(pnl.get("gross_pnl_usdc"))
    net = (gross - commission_usdc) if gross is not None and commission_usdc is not None else None

    lines = [
        f"✅ Trade closed: {symbol} {side}".rstrip(),
        f"trade_key: {trade_key}" if trade_key else "",
        "",
        f"Lifecycle: {_lifecycle_label(lifecycle_class)}",
        f"Close reason: {close_reason or 'not_available'}",
        "",
        f"Entry avg: {pnl.get('entry_avg_price') or 'not_available'}",
        f"Position qty: {_qty(_dec(pnl.get('position_qty')))}",
        "",
        "Exits:",
    ]

    any_leg = False
    for leg in pnl.get("legs") or []:
        if not leg.get("price") and not leg.get("qty"):
            continue
        any_leg = True
        lines.append(
            f"- {leg['label']}: {_price(_dec(leg.get('price')))} / "
            f"{_qty(_dec(leg.get('qty')))} / {_money(_dec(leg.get('gross_pnl_usdc')))} USDC"
        )
    if not any_leg:
        lines.append("- not_available")

    lines.extend([
        "",
        f"Gross PnL: {_money(gross)} USDC" if gross is not None else "Gross PnL: not_available",
        f"Commissions: {_commission_text({k: _dec(v) or Decimal('0') for k, v in pnl.get('commission_by_asset', {}).items()})}",
    ])

    if commission_usdc is not None:
        lines.append(f"Commission value: ~{_money(commission_usdc).lstrip('+')} USDC")
        lines.append(f"Net PnL approx: {_money(net)} USDC")
    else:
        lines.append("Net PnL approx: not_available")
        lines.append("Reason: commission conversion unavailable.")

    lines.append("")
    lines.append("Note: borrow/interest ignored by operational policy.")

    if snapshot.get("snapshot_status") and snapshot.get("snapshot_status") != "complete":
        lines.append(f"Snapshot status: {snapshot.get('snapshot_status')}")

    text = "\n".join(line for line in lines if line is not None).strip()
    if not text:
        return None

    payload = {
        "event": EVENT,
        "type": EVENT,
        "symbol": symbol,
        "trade_key": trade_key,
        "side": side,
        "lifecycle_class": lifecycle_class,
        "close_reason": close_reason,
        "gross_pnl_usdc": pnl.get("gross_pnl_usdc"),
        "commission_by_asset": pnl.get("commission_by_asset"),
        "commission_usdc_approx": _dec_str(commission_usdc),
        "net_pnl_approx_usdc": _dec_str(net),
        "borrow_interest_policy": "ignored",
        "snapshot_status": snapshot.get("snapshot_status"),
        "telegram_text": text,
        "message": text,
        "text": text,
    }
    if commission_valuation_source:
        payload["commission_valuation_source"] = commission_valuation_source
    if commission_valuation_symbol:
        payload["commission_valuation_symbol"] = commission_valuation_symbol
    return payload
