#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trade reporting (Reporting Spec v1).

Best-effort, read-only, deterministic reporting. Never blocks execution.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

REPORTS_PATH = "/data/reports/trades.jsonl"


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _iso_date(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    except Exception:
        return None


def _exit_type(reason: str) -> str:
    r = str(reason or "").strip().upper()
    if "FAILSAFE_FLATTEN" in r:
        return "FAILSAFE_FLATTEN"
    if "EXIT_CLEANUP" in r or "CLEANUP" in r:
        return "EXIT_CLEANUP"
    if "MISSING" in r:
        return "MISSING"
    if "ABORT" in r:
        return "ABORTED"
    if "TRAIL" in r:
        return "NORMAL_TRAIL"
    if r == "TP1":
        return "NORMAL_TP1"
    if r == "TP2":
        return "NORMAL_TP2"
    if r == "SL":
        return "NORMAL_SL"
    return "ABORTED"


def _entry_price(pos: Dict[str, Any]) -> Optional[float]:
    for key in ("entry_actual", "entry"):
        try:
            v = pos.get(key)
            if v is not None:
                return float(v)
        except Exception:
            continue
    prices = pos.get("prices") or {}
    try:
        v = prices.get("entry")
        if v is not None:
            return float(v)
    except Exception:
        return None
    return None


def _sum_leg_field(exit_leg_orders: Dict[str, Any], field: str) -> Optional[float]:
    total = 0.0
    seen = False
    for leg in ("tp1", "tp2", "sl", "trail"):
        leg_data = exit_leg_orders.get(leg)
        if not isinstance(leg_data, dict):
            continue
        try:
            val = leg_data.get(field)
            if val is None:
                continue
            total += float(val)
            seen = True
        except Exception:
            continue
    return total if seen else None


def _all_leg_fields_present(exit_leg_orders: Dict[str, Any], fields: list[str]) -> bool:
    for leg in ("tp1", "tp2", "sl", "trail"):
        leg_data = exit_leg_orders.get(leg)
        if not isinstance(leg_data, dict):
            continue
        for field in fields:
            if leg_data.get(field) in (None, ""):
                return False
    return True


def build_trade_report_internal(st: Dict[str, Any], pos: Dict[str, Any], close_reason: str) -> Dict[str, Any]:
    last_closed = st.get("last_closed") or {}
    closed_at = last_closed.get("ts")
    trade_key = pos.get("trade_key") or pos.get("client_id") or pos.get("order_id")
    exit_leg_orders = (pos.get("orders") or {}).get("fills") or {}

    entry_price = _entry_price(pos)
    qty_base_total = None
    try:
        qty_base_total = float(pos.get("qty"))
    except Exception:
        qty_base_total = None

    exit_qty_total = _sum_leg_field(exit_leg_orders, "executedQty")
    exit_quote_total = _sum_leg_field(exit_leg_orders, "cummulativeQuoteQty")
    avg_exit_price = None
    if exit_qty_total and exit_quote_total and exit_qty_total > 0:
        avg_exit_price = float(exit_quote_total) / float(exit_qty_total)

    fees_total_quote = _sum_leg_field(exit_leg_orders, "feeQuote")
    pnl_quote = None
    roi_pct = None
    if (
        entry_price is not None
        and qty_base_total is not None
        and exit_qty_total is not None
        and exit_quote_total is not None
        and fees_total_quote is not None
        and _all_leg_fields_present(exit_leg_orders, ["executedQty", "cummulativeQuoteQty", "feeQuote"])
    ):
        entry_cost = float(entry_price) * float(qty_base_total)
        side = str(pos.get("side") or "").upper()
        if side == "SHORT":
            gross = entry_cost - float(exit_quote_total)
        else:
            gross = float(exit_quote_total) - entry_cost
        pnl_quote = gross - float(fees_total_quote)
        if entry_cost > 0:
            roi_pct = (pnl_quote / entry_cost) * 100.0

    report_id = f"{trade_key}:{closed_at}"

    return {
        "report_id": report_id,
        "trade_key": trade_key,
        "symbol": st.get("meta", {}).get("symbol") or os.getenv("SYMBOL"),
        "side": pos.get("side"),
        "opened_at": pos.get("opened_at"),
        "closed_at": closed_at,
        "close_reason": close_reason,
        "exit_type": _exit_type(close_reason),
        "status_at_close": pos.get("status"),
        "qty_base_total": qty_base_total,
        "entry_price": entry_price,
        "exit_leg_orders": exit_leg_orders,
        "exit_qty_total": exit_qty_total,
        "exit_quote_total": exit_quote_total,
        "avg_exit_price": avg_exit_price,
        "fees_total_quote": fees_total_quote,
        "pnl_quote": pnl_quote,
        "roi_pct": roi_pct,
        "tp1_hit": bool(pos.get("tp1_done")),
        "tp2_hit": bool(pos.get("tp2_done")),
        "sl_hit": bool(pos.get("sl_done")),
        "trail_active_at_close": bool(pos.get("trail_active")),
        "reconciliation_notes": pos.get("reconciliation_notes"),
    }


def build_trade_report_public(internal: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": _iso_date(internal.get("closed_at")),
        "symbol": internal.get("symbol"),
        "side": internal.get("side"),
        "qty_base_total": internal.get("qty_base_total"),
        "entry_price": internal.get("entry_price"),
        "exit_qty_total": internal.get("exit_qty_total"),
        "avg_exit_price": internal.get("avg_exit_price"),
        "fees_total_quote": internal.get("fees_total_quote"),
        "pnl_quote": internal.get("pnl_quote"),
        "roi_pct": internal.get("roi_pct"),
        "exit_type": internal.get("exit_type"),
        "tp1_hit": internal.get("tp1_hit"),
        "tp2_hit": internal.get("tp2_hit"),
    }


def _append_jsonl(path: str, payload: Dict[str, Any]) -> None:
    _ensure_dir(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def report_trade_close(st: Dict[str, Any], pos: Dict[str, Any], close_reason: str) -> None:
    """Best-effort report writer. Never raises."""
    try:
        internal = build_trade_report_internal(st, pos, close_reason)
        report_id = internal.get("report_id")
        if report_id and st.get("last_reported_report_id") == report_id:
            return
        _append_jsonl(REPORTS_PATH, internal)
        st["last_reported_report_id"] = report_id
    except Exception:
        return
