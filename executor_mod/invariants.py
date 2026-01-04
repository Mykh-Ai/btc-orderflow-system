#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invariants.py
Detector-only invariants for executor state. No trading actions by default.
Throttles repeated alerts per invariant+position key.
"""

from __future__ import annotations

import os
from contextlib import suppress
from typing import Any, Callable, Dict, Optional, Tuple


ENV: Dict[str, Any] = {}
log_event: Optional[Callable[..., None]] = None
send_webhook: Optional[Callable[[Dict[str, Any]], None]] = None
save_state: Optional[Callable[[Dict[str, Any]], None]] = None
now_s: Optional[Callable[[], float]] = None

# In-process throttle cache (paired with persisted st["inv_throttle"])
_last_emit: Dict[str, float] = {}

def configure(
    env: Dict[str, Any],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    save_state_fn: Callable[[Dict[str, Any]], None],
    now_fn: Callable[[], float],
) -> None:
    global ENV, log_event, send_webhook, save_state, now_s
    ENV = env
    log_event = log_event_fn
    send_webhook = send_webhook_fn
    save_state = save_state_fn
    now_s = now_fn


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _enabled() -> bool:
    try:
        return bool(ENV.get("INVAR_ENABLED", False))
    except Exception:
        return False


def _throttle_sec() -> float:
    try:
        return float(ENV.get("INVAR_THROTTLE_SEC", 60))
    except Exception:
        return 60.0


def _grace_sec() -> float:
    try:
        return float(ENV.get("INVAR_GRACE_SEC", 10))
    except Exception:
        return 10.0


def _feed_stale_sec() -> float:
    try:
        return float(ENV.get("INVAR_FEED_STALE_SEC", 180))
    except Exception:
        return 180.0


def _tick_size() -> float:
    # ENV["TICK_SIZE"] in executor is Decimal; float() works.
    try:
        return float(ENV.get("TICK_SIZE", 0.0))
    except Exception:
        return 0.0


def _qty_step() -> float:
    try:
        return float(ENV.get("QTY_STEP", 0.0))
    except Exception:
        return 0.0


def _min_qty() -> float:
    try:
        return float(ENV.get("MIN_QTY", 0.0))
    except Exception:
        return 0.0


def _pos_key(pos: Dict[str, Any]) -> str:
    # Stable enough for throttling; do NOT assume every field exists.
    sym = str(ENV.get("SYMBOL", "") or "")
    side = str(pos.get("side", "") or "")
    oid = str(pos.get("order_id", "") or "")
    cid = str(pos.get("client_id", "") or "")
    opened = str(pos.get("opened_at", "") or "")
    return f"{sym}:{side}:{oid or cid or opened or 'NA'}"


def _emit(st: Dict[str, Any], inv_id: str, severity: str, message: str, details: Dict[str, Any]) -> None:
    if not _enabled():
        return
    if log_event is None or send_webhook is None or now_s is None:
        return

    pos = st.get("position") or {}
    pkey = _pos_key(pos) if isinstance(pos, dict) else str(ENV.get("SYMBOL", ""))

    nowv = float(now_s())
    thr = float(_throttle_sec())

    # Persist throttle in state (best-effort).
    key = f"{inv_id}:{pkey}"
    inv_th = st.get("inv_throttle") if isinstance(st, dict) else None
    if not isinstance(inv_th, dict):
        inv_th = {}
    last = max(_last_emit.get(key, 0.0), _as_float(inv_th.get(key), 0.0))
    if thr > 0 and (nowv - last) < thr:
        return
    _last_emit[key] = nowv
    inv_th[key] = nowv
    if isinstance(st, dict):
        st["inv_throttle"] = inv_th
        if save_state is not None and bool(ENV.get("INVAR_PERSIST", True)):
            with suppress(Exception):
                save_state(st)

    # Log + webhook (detector-only)
    with suppress(Exception):
        log_event("INVARIANT_FAIL", invariant_id=inv_id, severity=severity, msg=message, **details)

    payload: Dict[str, Any] = {
        "event": "INVARIANT_FAIL",
        "mode": (pos.get("mode") if isinstance(pos, dict) else None) or "unknown",
        "symbol": ENV.get("SYMBOL"),
        "invariant_id": inv_id,
        "severity": severity,
        "message": message,
        "position": {
            "side": pos.get("side") if isinstance(pos, dict) else None,
            "status": pos.get("status") if isinstance(pos, dict) else None,
            "qty": pos.get("qty") if isinstance(pos, dict) else None,
            "entry": pos.get("entry") if isinstance(pos, dict) else None,
            "order_id": pos.get("order_id") if isinstance(pos, dict) else None,
            "client_id": pos.get("client_id") if isinstance(pos, dict) else None,
            "synced": pos.get("synced") if isinstance(pos, dict) else None,
        },
        "details": details,
        "throttle_sec": thr,
        "action": "RECOMMEND_ONLY",
    }
    with suppress(Exception):
        send_webhook(payload)


def _check_i1_protection_present(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if str(pos.get("status", "")).upper() != "OPEN_FILLED":
        return

    orders = pos.get("orders") or {}
    prices = pos.get("prices") or {}
    sl_id = _as_int(orders.get("sl"), 0) if isinstance(orders, dict) else 0
    sl_p = _as_float(prices.get("sl"), 0.0) if isinstance(prices, dict) else 0.0

    if sl_id > 0 and sl_p > 0:
        return

    opened_s = _as_float(pos.get("opened_s"), 0.0)
    age = float(now_s()) - opened_s if (now_s is not None and opened_s > 0) else 999999.0
    sev = "WARN" if age < float(_grace_sec()) else "ERROR"
    _emit(
        st,
        "I1",
        sev,
        "OPEN_FILLED but SL missing",
        {
            "status": pos.get("status"),
            "sl_id": sl_id,
            "sl_price": sl_p,
            "exits_tries": pos.get("exits_tries"),
            "age_s": age,
        },
    )


def _check_i2_exit_price_sanity(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return

    prices = pos.get("prices") or {}
    if not isinstance(prices, dict):
        return

    side = str(pos.get("side", "") or "").upper()
    entry = _as_float(prices.get("entry"), 0.0)
    sl = _as_float(prices.get("sl"), 0.0)
    tp1 = _as_float(prices.get("tp1"), 0.0)
    tp2 = _as_float(prices.get("tp2"), 0.0)

    # If incomplete, only warn when position is already OPEN_FILLED.
    if not (entry > 0 and sl > 0 and tp1 > 0 and tp2 > 0):
        if str(pos.get("status", "")).upper() == "OPEN_FILLED":
            _emit(
                st,
                "I2",
                "WARN",
                "Exit prices incomplete in state",
                {"prices": {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2}},
            )
        return

    ok = True
    if side == "LONG":
        ok = (sl < entry < tp1 < tp2)
    elif side == "SHORT":
        ok = (tp2 < tp1 < entry < sl)
    else:
        return

    tick = float(_tick_size())
    if tick > 0:
        ok = ok and (abs(entry - sl) >= tick) and (abs(tp1 - entry) >= tick) and (abs(tp2 - tp1) >= tick)

    if ok:
        return

    _emit(
        st,
        "I2",
        "ERROR",
        "Exit price hierarchy invalid",
        {"side": side, "prices": {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2}, "tick": tick},
    )


def _check_i3_quantity_accounting(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return

    orders = pos.get("orders") or {}
    if not isinstance(orders, dict):
        return

    qty_total = _as_float(pos.get("qty"), 0.0)
    q1 = _as_float(orders.get("qty1"), 0.0)
    q2 = _as_float(orders.get("qty2"), 0.0)
    q3 = _as_float(orders.get("qty3"), 0.0)

    # If not present (e.g., synced attach or exits not placed yet), skip.
    if not (qty_total > 0 and q1 > 0 and q2 > 0 and q3 > 0):
        return

    step = float(_qty_step())
    minq = float(_min_qty())

    if minq > 0 and (q1 < minq or q2 < minq or q3 < minq):
        _emit(
            st,
            "I3",
            "ERROR",
            "Exit leg qty below MIN_QTY",
            {"qty_total": qty_total, "qty1": q1, "qty2": q2, "qty3": q3, "min_qty": minq},
        )
        return

    s = q1 + q2 + q3
    tol = step if step > 0 else 0.0
    if tol > 0 and abs(s - qty_total) <= tol:
        return
    if tol == 0 and abs(s - qty_total) < 1e-12:
        return

    _emit(
        st,
        "I3",
        "ERROR",
        "Exit leg qty sum mismatch",
        {"qty_total": qty_total, "qty1": q1, "qty2": q2, "qty3": q3, "sum": s, "qty_step": step},
    )


def _check_i4_entry_state_consistency(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return

    status = str(pos.get("status", "") or "").upper()
    if status not in ("PENDING", "OPEN"):
        return

    # Rehydrated "synced" positions can have partial entry metadata – do not hard-fail.
    if bool(pos.get("synced")) is True:
        return

    missing = []
    if pos.get("order_id") in (None, 0, "0", ""):
        missing.append("order_id")
    if not pos.get("client_id"):
        missing.append("client_id")
    if not pos.get("entry_mode"):
        missing.append("entry_mode")
    if _as_float(pos.get("entry"), 0.0) <= 0:
        missing.append("entry")
    if _as_float(pos.get("qty"), 0.0) <= 0:
        missing.append("qty")

    if not missing:
        return

    _emit(
        st,
        "I4",
        "ERROR",
        "Entry state missing required fields",
        {"status": status, "missing": missing},
    )


def _check_i5_trail_state_sane(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if not bool(pos.get("trail_active")):
        return

    status = str(pos.get("status", "") or "").upper()
    trail_qty = _as_float(pos.get("trail_qty"), 0.0)
    if trail_qty <= 0:
        _emit(
            st,
            "I5",
            "ERROR",
            "Trail qty not positive",
            {"trail_qty": trail_qty},
        )
        return

    if status not in ("OPEN", "OPEN_FILLED"):
        _emit(
            st,
            "I5",
            "WARN",
            "Trail active with unexpected status",
            {"status": status},
        )
        return

    trail_last_update_s = _as_float(pos.get("trail_last_update_s"), 0.0)
    if trail_last_update_s <= 0:
        _emit(
            st,
            "I5",
            "WARN",
            "Trail last update timestamp missing",
            {"trail_last_update_s": trail_last_update_s},
        )
        return

    pending_cancel_sl = _as_int(pos.get("trail_pending_cancel_sl"), 0)
    trail_sl_price = _as_float(pos.get("trail_sl_price"), 0.0)
    if pending_cancel_sl <= 0 and trail_sl_price <= 0:
        _emit(
            st,
            "I5",
            "WARN",
            "Trail missing pending cancel and SL price",
            {"trail_pending_cancel_sl": pending_cancel_sl, "trail_sl_price": trail_sl_price},
        )
        return


def _check_i6_feed_freshness_for_trail(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if not bool(pos.get("trail_active")):
        return
    if str(ENV.get("TRAIL_SOURCE", "") or "") != "AGG":
        return

    agg_csv = str(ENV.get("AGG_CSV", "") or "")
    if not agg_csv:
        _emit(
            st,
            "I6",
            "WARN",
            "AGG feed file path missing",
            {"agg_csv": agg_csv},
        )
        return

    try:
        mtime = float(os.path.getmtime(agg_csv))
    except Exception as exc:
        _emit(
            st,
            "I6",
            "WARN",
            "AGG feed file not accessible",
            {"agg_csv": agg_csv, "error": str(exc)},
        )
        return

    age_s = float(now_s()) - mtime if now_s is not None else 0.0
    stale = float(_feed_stale_sec())
    if age_s > stale:
        _emit(
            st,
            "I6",
            "WARN",
            "AGG feed file stale",
            {"agg_csv": agg_csv, "age_s": age_s, "stale_sec": stale},
        )


def _check_i7_tp_orders_after_fill(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if str(pos.get("status", "")).upper() != "OPEN_FILLED":
        return
    if bool(pos.get("trail_active")):
        return

    orders = pos.get("orders")
    tp1_id = _as_int(orders.get("tp1"), 0) if isinstance(orders, dict) else 0
    tp2_id = _as_int(orders.get("tp2"), 0) if isinstance(orders, dict) else 0
    if isinstance(orders, dict) and tp1_id > 0 and tp2_id > 0:
        return

    opened_s = _as_float(pos.get("opened_s"), 0.0)
    age = float(now_s()) - opened_s if (now_s is not None and opened_s > 0) else 0.0
    sev = "WARN" if age < float(_grace_sec()) else "ERROR"
    _emit(
        st,
        "I7",
        sev,
        "OPEN_FILLED without TP orders",
        {"tp1_id": tp1_id, "tp2_id": tp2_id, "age_s": age},
    )


def _check_i8_state_shape_live_position(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return

    status = str(pos.get("status", "")).upper()
    if status not in ("OPEN", "OPEN_FILLED"):
        return

    orders = pos.get("orders")
    prices = pos.get("prices")
    issues = []
    if not isinstance(orders, dict):
        issues.append("orders_not_dict")
    if not isinstance(prices, dict):
        issues.append("prices_not_dict")

    if not issues:
        return

    opened_s = _as_float(pos.get("opened_s"), 0.0)
    age = float(now_s()) - opened_s if (now_s is not None and opened_s > 0) else 0.0
    sev = "WARN" if age < float(_grace_sec()) else "ERROR"
    _emit(
        st,
        "I8",
        sev,
        "Live position missing required state shape",
        {"issues": issues, "age_s": age},
    )


def run(st: Dict[str, Any]) -> None:
    """
    Run detector-only invariants against current state.
    """
    if not _enabled():
        return
    if now_s is None or log_event is None or send_webhook is None:
        return
    try:
        _check_i1_protection_present(st)
        _check_i2_exit_price_sanity(st)
        _check_i3_quantity_accounting(st)
        _check_i4_entry_state_consistency(st)
        _check_i5_trail_state_sane(st)
        _check_i6_feed_freshness_for_trail(st)
        _check_i7_tp_orders_after_fill(st)
        _check_i8_state_shape_live_position(st)
    except Exception:
        # Never break executor on invariant checks
        return
