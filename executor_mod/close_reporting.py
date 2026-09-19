"""Best-effort close snapshot and close summary helpers."""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal
from typing import Any, Dict, Optional


def record_trade_execution_snapshot(
    st: Dict[str, Any],
    source: str,
    *,
    enrich_exchange: bool = False,
    binance_api: Optional[Any] = None,
    log_event: Optional[Any] = None,
    trade_execution_snapshot: Any,
) -> Optional[Dict[str, Any]]:
    """Best-effort execution snapshot; must never affect trading cleanup."""
    try:
        return trade_execution_snapshot.record_final_execution_snapshot(
            st,
            source=source,
            binance_api=binance_api if enrich_exchange else None,
        )
    except Exception as exc:
        with suppress(Exception):
            log_event("TRADE_EXECUTION_SNAPSHOT_ERROR", source=source, error=str(exc))
    return None


def quote_asset(symbol: str) -> str:
    symbol = str(symbol or "").upper()
    for quote in ("USDC", "USDT", "FDUSD", "BUSD", "USD"):
        if symbol.endswith(quote):
            return quote
    return ""


def commission_usdc_valuation(snapshot: Dict[str, Any], *, binance_api: Any) -> Dict[str, Any]:
    """Best-effort current-price commission valuation for Telegram UX only."""
    commissions = ((snapshot or {}).get("fees") or {}).get("commission_by_asset") or {}
    if not commissions:
        return {}

    symbol = str((snapshot or {}).get("symbol") or "")
    quote = quote_asset(symbol)
    if quote != "USDC":
        return {}

    total = Decimal("0")
    used_symbol = None
    for asset, raw_amount in commissions.items():
        amount = Decimal(str(raw_amount or "0"))
        asset = str(asset or "").upper()
        if not amount:
            continue
        if asset == "USDC":
            total += amount
        elif asset == "BNB":
            used_symbol = "BNBUSDC"
            px = Decimal(str(binance_api.get_mid_price(used_symbol)))
            total += amount * px
        else:
            return {}

    if total <= 0:
        return {}
    return {
        "commission_usdc_approx": format(total, "f"),
        "commission_valuation_source": "binance_public_mid_at_notification",
        "commission_valuation_symbol": used_symbol or "USDC",
    }


def send_trade_closed_summary(
    st: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    *,
    binance_api: Any,
    log_event: Any,
    send_webhook: Any,
    trade_execution_snapshot: Any,
    trade_close_summary: Any,
) -> None:
    """Best-effort close summary notification; must never affect cleanup."""
    try:
        if not isinstance(snapshot, dict) or not snapshot:
            last_closed = (st or {}).get("last_closed")
            if not isinstance(last_closed, dict) or not last_closed:
                return
            snapshot = trade_execution_snapshot.build_local_snapshot(st or {}, last_closed, "_close_slot")

        valuation: Dict[str, Any] = {}
        with suppress(Exception):
            valuation = commission_usdc_valuation(snapshot, binance_api=binance_api)
        payload = trade_close_summary.build_trade_closed_summary_payload(snapshot, **valuation)
        if not payload:
            return
        send_webhook(payload)
        with suppress(Exception):
            log_event(
                "TRADE_CLOSED_SUMMARY_SENT",
                trade_key=payload.get("trade_key"),
                gross_pnl_usdc=payload.get("gross_pnl_usdc"),
                net_pnl_approx_usdc=payload.get("net_pnl_approx_usdc"),
                commission_usdc_approx=payload.get("commission_usdc_approx"),
            )
    except Exception as exc:
        with suppress(Exception):
            log_event("TRADE_CLOSED_SUMMARY_ERROR", error=str(exc))
