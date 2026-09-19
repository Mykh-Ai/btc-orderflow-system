"""Pure builders for position finalization snapshots."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _prices(pos: Mapping[str, Any]) -> Mapping[str, Any]:
    prices = pos.get("prices")
    return prices if isinstance(prices, Mapping) else {}


def _orders(pos: Mapping[str, Any]) -> Mapping[str, Any]:
    orders = pos.get("orders")
    return orders if isinstance(orders, Mapping) else {}


def close_enrichment_from_pos(pos: Mapping[str, Any]) -> Dict[str, Any]:
    orders = _orders(pos)
    prices = _prices(pos)
    return {
        "opened_at": pos.get("opened_at"),
        "trade_key": pos.get("trade_key") or pos.get("client_id"),
        "order_id": pos.get("order_id"),
        "qty": pos.get("qty"),
        "entry_ref": prices.get("entry"),
        "entry_actual": pos.get("entry_actual"),
        "order_id_sl": orders.get("sl"),
        "order_id_tp1": orders.get("tp1"),
        "order_id_tp2": orders.get("tp2"),
        "qty1": orders.get("qty1"),
        "qty2": orders.get("qty2"),
        "qty3": orders.get("qty3"),
        "tp1_done": bool(pos.get("tp1_done")),
        "tp2_done": bool(pos.get("tp2_done")),
        "sl_done": bool(pos.get("sl_done")),
        "trail_active": bool(pos.get("trail_active")),
        "trail_sl_price": pos.get("trail_sl_price"),
        "prices": pos.get("prices"),
    }


def build_clear_position_last_closed(
    pos: Mapping[str, Any],
    reason: str,
    iso_ts: str,
    extra_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    out = {
        "ts": iso_ts,
        "mode": pos.get("mode"),
        "reason": reason,
        "pos_status": pos.get("status"),
    }
    out.update(close_enrichment_from_pos(pos))
    if extra_fields:
        out.update(extra_fields)
    return out


def build_live_close_last_closed(pos: Mapping[str, Any], reason: str, iso_ts: str) -> Dict[str, Any]:
    prices = _prices(pos)
    out = {
        "ts": iso_ts,
        "mode": "live",
        "reason": reason,
        "side": pos.get("side"),
        "entry": prices.get("entry"),
    }
    out.update(close_enrichment_from_pos(pos))
    return out


def build_sync_last_closed(
    pos: Mapping[str, Any],
    reason: str,
    iso_ts: str,
    order_status: Optional[str] = None,
) -> Dict[str, Any]:
    prices = _prices(pos)
    out = {
        "ts": iso_ts,
        "mode": pos.get("mode"),
        "reason": reason,
        "pos_status": pos.get("status"),
        "trade_key": pos.get("trade_key") or pos.get("client_id"),
        "order_id": pos.get("order_id"),
        "side": pos.get("side"),
        "qty": pos.get("qty"),
        "entry_ref": prices.get("entry"),
        "entry_actual": pos.get("entry_actual"),
        "opened_at": pos.get("opened_at"),
    }
    if order_status is not None:
        out["order_status"] = order_status
    return out
