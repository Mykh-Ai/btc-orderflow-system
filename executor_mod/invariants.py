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
_i13_exchange_check_fn: Optional[Callable[[Optional[str], Optional[bool]], Dict[str, Any]]] = None

# In-process throttle cache (paired with persisted st["inv_throttle"])
_last_emit: Dict[str, float] = {}

def configure(
    env: Dict[str, Any],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    save_state_fn: Callable[[Dict[str, Any]], None],
    now_fn: Callable[[], float],
    i13_exchange_check_fn: Optional[Callable[[Optional[str], Optional[bool]], Dict[str, Any]]] = None,
) -> None:
    global ENV, log_event, send_webhook, save_state, now_s, _i13_exchange_check_fn
    ENV = env
    log_event = log_event_fn
    send_webhook = send_webhook_fn
    save_state = save_state_fn
    now_s = now_fn
    _i13_exchange_check_fn = i13_exchange_check_fn


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


def _as_bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return x != 0
    if isinstance(x, str):
        val = x.strip().lower()
        if val in {"1", "true", "yes", "y", "on"}:
            return True
        if val in {"0", "false", "no", "n", "off", ""}:
            return False
        return default
    if x is None:
        return default
    return default


def _enabled() -> bool:
    try:
        return _as_bool(ENV.get("INVAR_ENABLED", False), False)
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


def _i13_escalate_sec() -> float:
    try:
        return float(ENV.get("I13_ESCALATE_SEC", 180))
    except Exception:
        return 180.0


def _i13_grace_sec() -> float:
    try:
        return float(ENV.get("I13_GRACE_SEC", 300))
    except Exception:
        return 300.0


def _i13_exchange_check_enabled() -> bool:
    try:
        return _as_bool(ENV.get("I13_EXCHANGE_CHECK", True), True)
    except Exception:
        return True


def _i13_exchange_min_interval_sec() -> float:
    try:
        return float(ENV.get("I13_EXCHANGE_MIN_INTERVAL_SEC", 60))
    except Exception:
        return 60.0


def _i13_clear_state_on_exchange_clear() -> bool:
    try:
        return _as_bool(ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", False), False)
    except Exception:
        return False


def _invar_kill_on_debt() -> bool:
    try:
        return _as_bool(ENV.get("INVAR_KILL_ON_DEBT", False), False)
    except Exception:
        return False


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
        with suppress(Exception):
            cutoff = nowv - (7 * 24 * 3600)
            for tkey, tval in list(inv_th.items()):
                if _as_float(tval, 0.0) < cutoff:
                    inv_th.pop(tkey, None)
            if len(inv_th) > 5000:
                newest = sorted(
                    inv_th.items(),
                    key=lambda item: _as_float(item[1], 0.0),
                    reverse=True,
                )[:5000]
                inv_th = {k: v for k, v in newest}
        st["inv_throttle"] = inv_th
        if save_state is not None and _as_bool(ENV.get("INVAR_PERSIST", True), True):
            with suppress(Exception):
                save_state(st)

    # Log + webhook (detector-only)
    with suppress(Exception):
        log_event("INVARIANT_FAIL", invariant_id=inv_id, severity=severity, msg=message, **details)

    prices = pos.get("prices") if isinstance(pos, dict) else None
    payload: Dict[str, Any] = {
        "event": "INVARIANT_FAIL",
        "ts_s": nowv,
        "pos_key": pkey,
        "mode": (pos.get("mode") if isinstance(pos, dict) else None) or "unknown",
        "symbol": ENV.get("SYMBOL"),
        "invariant_id": inv_id,
        "inv_id": inv_id,
        "severity": severity,
        "message": message,
        "side": pos.get("side") if isinstance(pos, dict) else None,
        "status": pos.get("status") if isinstance(pos, dict) else None,
        "qty": pos.get("qty") if isinstance(pos, dict) else None,
        "entry": pos.get("entry") if isinstance(pos, dict) else None,
        "trail_active": pos.get("trail_active") if isinstance(pos, dict) else None,
        "sl": prices.get("sl") if isinstance(prices, dict) else None,
        "tp1": prices.get("tp1") if isinstance(prices, dict) else None,
        "tp2": prices.get("tp2") if isinstance(prices, dict) else None,
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


def _check_i9_trail_active_sl_missing(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if not bool(pos.get("trail_active")):
        return

    status = str(pos.get("status", "") or "").upper()
    if status not in ("OPEN", "OPEN_FILLED"):
        return

    orders = pos.get("orders") or {}
    prices = pos.get("prices") or {}
    # Avoid double-alert with I8 (shape check)
    if not isinstance(orders, dict) or not isinstance(prices, dict):
        return
    sl_id = _as_int(orders.get("sl"), 0)
    sl_p = _as_float(prices.get("sl"), 0.0)
    if sl_id > 0 and sl_p > 0:
        return

    opened_s = _as_float(pos.get("opened_s"), 0.0)
    age = float(now_s()) - opened_s if (now_s is not None and opened_s > 0) else 999999.0
    sev = "WARN" if age < float(_grace_sec()) else "ERROR"
    _emit(
        st,
        "I9",
        sev,
        "Trail active but SL missing",
        {
            "status": pos.get("status"),
            "sl_id": sl_id,
            "sl_price": sl_p,
            "trail_active": pos.get("trail_active"),
            "age_s": age,
        },
    )


def _check_i10_repeated_trail_stop_errors(st: Dict[str, Any]) -> None:
    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    if pos.get("mode") != "live":
        return
    if not bool(pos.get("trail_active")):
        return

    last_code = _as_int(pos.get("trail_last_error_code"), 0)
    last_s = _as_float(pos.get("trail_last_error_s"), 0.0)
    if last_code != -2010 or last_s <= 0:
        return
    if now_s is None:
        return

    nowv = float(now_s())
    window_sec = 15 * 60

    inv_runtime = st.setdefault("inv_runtime", {}) if isinstance(st, dict) else {}
    if not isinstance(inv_runtime, dict):
        inv_runtime = {}
    i10_state = inv_runtime.get("I10")
    if not isinstance(i10_state, dict):
        i10_state = {}

    pkey = _pos_key(pos)
    state = i10_state.get(pkey)
    if not isinstance(state, dict):
        state = {}
    events = state.get("events")
    if not isinstance(events, list):
        events = []

    last_seen = _as_float(state.get("last_seen_s"), 0.0)
    changed = False
    if last_s > last_seen:
        events.append(last_s)
        state["last_seen_s"] = last_s
        changed = True

    events = [t for t in events if (nowv - _as_float(t, 0.0)) <= window_sec]
    if len(events) > 100:
        events = events[-100:]
    count = len(events)
    state["events"] = events
    i10_state[pkey] = state
    inv_runtime["I10"] = i10_state
    if isinstance(st, dict):
        st["inv_runtime"] = inv_runtime
        # Persist counters, otherwise load_state() will wipe them next loop
        if changed and save_state is not None and _as_bool(ENV.get("INVAR_PERSIST", True), True):
            with suppress(Exception):
                save_state(st)

    if count < 3:
        return

    sev = "ERROR" if count >= 6 else "WARN"
    _emit(
        st,
        "I10",
        sev,
        "Repeated TRAIL stop errors (-2010)",
        {"count": count, "window_sec": window_sec, "last_error_s": last_s},
    )


def _is_margin_mode() -> bool:
    return str(ENV.get("TRADE_MODE", "") or "").lower() == "margin"


def _check_i11_margin_config_sanity(st: Dict[str, Any]) -> None:
    if not _is_margin_mode():
        return

    borrow_mode = str(ENV.get("MARGIN_BORROW_MODE", "") or "")
    side_effect = str(ENV.get("MARGIN_SIDE_EFFECT", "") or "")

    if borrow_mode == "manual" and side_effect != "NO_SIDE_EFFECT":
        _emit(
            st,
            "I11",
            "WARN",
            "Manual margin mode must use NO_SIDE_EFFECT",
            {"borrow_mode": borrow_mode, "side_effect": side_effect},
        )
        return

    if borrow_mode == "auto" and side_effect != "AUTO_BORROW_REPAY":
        _emit(
            st,
            "I11",
            "WARN",
            "Auto margin mode must use AUTO_BORROW_REPAY",
            {"borrow_mode": borrow_mode, "side_effect": side_effect},
        )


def _collect_trade_keys(val: Any) -> Tuple[str, ...]:
    if val is None:
        return ()
    if isinstance(val, dict):
        return tuple(str(k) for k in val.keys() if k is not None and str(k) != "")
    if isinstance(val, (list, tuple, set)):
        return tuple(str(k) for k in val if k is not None and str(k) != "")
    if isinstance(val, str):
        return (val,) if val else ()
    return ()


def _mg_rt(st: Dict[str, Any]) -> Dict[str, Any]:
    """
    Margin guard runtime bucket.
    In production margin_guard writes into st["mg_runtime"].
    Keep fallback to legacy st["rt"] for backward compatibility.
    """
    if not isinstance(st, dict):
        return {}
    rt = st.get("mg_runtime")
    if not isinstance(rt, dict):
        rt = st.get("rt")
    return rt if isinstance(rt, dict) else {}


def _i13_exchange_snapshot(symbol: Optional[str], is_isolated: Optional[bool]) -> Tuple[Optional[bool], Dict[str, Any]]:
    snapshot: Optional[Dict[str, Any]] = None
    if _i13_exchange_check_fn is not None:
        with suppress(Exception):
            snapshot = _i13_exchange_check_fn(symbol, is_isolated)
    else:
        with suppress(Exception):
            from executor_mod import binance_api

            snapshot = binance_api.get_margin_debt_snapshot(symbol=symbol, is_isolated=is_isolated)
    if not isinstance(snapshot, dict):
        return None, {}
    has_debt = snapshot.get("has_debt")
    if isinstance(has_debt, bool):
        return has_debt, snapshot
    return None, snapshot


def _check_i12_trade_key_consistency(st: Dict[str, Any]) -> None:
    if not _is_margin_mode():
        return

    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        return
    status = str(pos.get("status", "") or "").upper()
    if status not in ("OPEN", "OPEN_FILLED"):
        return

    margin = st.get("margin") or {}
    if not isinstance(margin, dict):
        margin = {}
    active_trade_key = margin.get("active_trade_key")

    rt = _mg_rt(st)

    keys = []
    for hook_name in ("borrow_started", "borrow_done", "after_open_done"):
        keys.extend(_collect_trade_keys(rt.get(hook_name)))

    if not keys:
        return

    unique_keys = {k for k in keys if k}
    active_key = str(active_trade_key) if active_trade_key not in (None, "") else ""
    if len(unique_keys) > 1 or (unique_keys and (len(unique_keys) != 1 or active_key not in unique_keys)):
        _emit(
            st,
            "I12",
            "WARN",
            "Trade key mismatch across margin hooks",
            {"active_trade_key": active_trade_key, "hook_keys": sorted(unique_keys)},
        )


def _check_i13_no_debt_after_close(st: Dict[str, Any]) -> None:
    if not _is_margin_mode():
        return

    changed = False

    pos = st.get("position") or {}
    if not isinstance(pos, dict):
        pos = {}
    status = str(pos.get("status", "") or "").upper()
    closed = bool(st.get("last_closed")) or status not in ("OPEN", "OPEN_FILLED") or _as_float(
        pos.get("closed_s"), 0.0
    ) > 0
    if not closed:
        return

    margin = st.get("margin") or {}
    if not isinstance(margin, dict):
        margin = {}
    borrowed_assets = margin.get("borrowed_assets") or {}
    if not isinstance(borrowed_assets, dict):
        borrowed_assets = {}
    borrowed_by_trade = margin.get("borrowed_by_trade") or {}
    if not isinstance(borrowed_by_trade, dict):
        borrowed_by_trade = {}
    has_debt = any(_as_float(v, 0.0) > 0 for v in borrowed_assets.values()) or bool(borrowed_by_trade)

    inv_rt = st.get("inv_runtime") if isinstance(st, dict) else None
    if not isinstance(inv_rt, dict):
        inv_rt = {}
    if not has_debt:
        if "I13" in inv_rt:
            inv_rt.pop("I13", None)
            st["inv_runtime"] = inv_rt
            _persist_i13_runtime(st, True)
        return
    entry = inv_rt.get("I13")
    if not isinstance(entry, dict):
        entry = {}

    nowv = float(now_s()) if now_s is not None else 0.0
    close_seen_s = entry.get("close_seen_s")
    if close_seen_s is None:
        close_seen_s = nowv
        entry["close_seen_s"] = close_seen_s
        changed = True

    closed_s = _as_float(pos.get("closed_s"), 0.0)
    symbol = str(ENV.get("SYMBOL", "") or "")
    episode_id = f"{symbol}:{closed_s}" if closed_s > 0 else f"{symbol}:{close_seen_s}"
    if entry.get("episode_id") != episode_id:
        entry = {
            "episode_id": episode_id,
            "close_seen_s": close_seen_s,
            "warn_emitted": False,
            "error_emitted": False,
            "next_exchange_check_s": close_seen_s + _i13_grace_sec(),
            "last_exchange_check_s": None,
            "last_exchange_has_debt": None,
            "exchange_unavailable_emitted": False,
        }
        changed = True

    age = nowv - _as_float(entry.get("close_seen_s"), nowv)
    if nowv < (_as_float(entry.get("close_seen_s"), nowv) + _i13_grace_sec()):
        inv_rt["I13"] = entry
        st["inv_runtime"] = inv_rt
        _persist_i13_runtime(st, changed)
        return

    if not _i13_exchange_check_enabled():
        entry["last_exchange_has_debt"] = None
        inv_rt["I13"] = entry
        st["inv_runtime"] = inv_rt
        _persist_i13_runtime(st, changed)
        return

    next_check = _as_float(entry.get("next_exchange_check_s"), 0.0)
    if nowv < next_check:
        inv_rt["I13"] = entry
        st["inv_runtime"] = inv_rt
        _persist_i13_runtime(st, changed)
        return

    is_isolated = _as_bool(ENV.get("MARGIN_ISOLATED", False), False)
    check_symbol = symbol if is_isolated else None
    exchange_has_debt, exchange_snapshot = _i13_exchange_snapshot(check_symbol, is_isolated)
    entry["last_exchange_check_s"] = nowv
    entry["next_exchange_check_s"] = nowv + _i13_exchange_min_interval_sec()
    entry["last_exchange_has_debt"] = exchange_has_debt
    changed = True

    if exchange_has_debt is None:
        if not entry.get("exchange_unavailable_emitted"):
            _emit(
                st,
                "I13",
                "WARN",
                "I13 exchange check unavailable",
                {"symbol": symbol, "is_isolated": is_isolated, "exchange_snapshot": exchange_snapshot},
            )
            entry["exchange_unavailable_emitted"] = True
            changed = True
        inv_rt["I13"] = entry
        st["inv_runtime"] = inv_rt
        _persist_i13_runtime(st, changed)
        return

    if exchange_has_debt is False:
        if _i13_clear_state_on_exchange_clear() and isinstance(st.get("margin"), dict):
            margin = st["margin"]
            margin["borrowed_assets"] = {}
            margin["borrowed_by_trade"] = {}
            st["margin"] = margin
        inv_rt.pop("I13", None)
        st["inv_runtime"] = inv_rt
        _persist_i13_runtime(st, True)
        return

    if not entry.get("warn_emitted"):
        _emit(
            st,
            "I13",
            "WARN",
            "Margin debt still present after close (exchange-truth)",
            {
                "symbol": symbol,
                "is_isolated": is_isolated,
                "exchange_snapshot": exchange_snapshot,
                "close_seen_s": entry.get("close_seen_s"),
                "age_s": age,
            },
        )
        entry["warn_emitted"] = True
        changed = True

    if age >= (_i13_grace_sec() + _i13_escalate_sec()) and not entry.get("error_emitted"):
        _emit(
            st,
            "I13",
            "ERROR",
            "Margin debt stuck after close (exchange-truth escalated)",
            {
                "symbol": symbol,
                "is_isolated": is_isolated,
                "exchange_snapshot": exchange_snapshot,
                "close_seen_s": entry.get("close_seen_s"),
                "age_s": age,
            },
        )
        entry["error_emitted"] = True
        changed = True
        if _invar_kill_on_debt() and isinstance(st, dict):
            halt = st.get("halt")
            if not isinstance(halt, dict):
                halt = {}
            if "reason" not in halt:
                halt["reason"] = "I13_DEBT_STUCK"
            reasons = halt.get("reasons")
            if not isinstance(reasons, list):
                reasons = []
            if "I13_DEBT_STUCK" not in reasons:
                reasons.append("I13_DEBT_STUCK")
            halt["reasons"] = reasons
            halt["ts"] = nowv
            halt["symbol"] = symbol
            st["halt"] = halt

    inv_rt["I13"] = entry
    st["inv_runtime"] = inv_rt
    _persist_i13_runtime(st, changed)


def _clear_i13_runtime(st: Dict[str, Any], active_key: Optional[str]) -> bool:
    if not isinstance(st, dict):
        return False
    inv_rt = st.get("inv_runtime")
    if not isinstance(inv_rt, dict):
        return False
    i13_rt = inv_rt.get("I13")
    if not isinstance(i13_rt, dict):
        return False
    before = dict(i13_rt)
    if active_key:
        i13_rt.pop(active_key, None)
    else:
        i13_rt.clear()
    inv_rt["I13"] = i13_rt
    st["inv_runtime"] = inv_rt
    return before != i13_rt


def _persist_i13_runtime(st: Dict[str, Any], changed: bool) -> None:
    if not changed:
        return
    if save_state is None:
        return
    if not _as_bool(ENV.get("INVAR_PERSIST", True), True):
        return
    with suppress(Exception):
        save_state(st)


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
        _check_i9_trail_active_sl_missing(st)
        _check_i10_repeated_trail_stop_errors(st)
        _check_i11_margin_config_sanity(st)
        _check_i12_trade_key_consistency(st)
        _check_i13_no_debt_after_close(st)
    except Exception:
        # Never break executor on invariant checks
        return
