#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OPEN_FILLED exit retry and failsafe lifecycle."""
from __future__ import annotations

import math
from decimal import Decimal
from uuid import uuid4
from contextlib import suppress
from typing import Any, Callable, Dict


def handle_open_filled_exits_retry(
    st: dict,
    *,
    env: Dict[str, Any],
    save_state_fn: Callable[[dict], None],
    ensure_exits_fn: Callable[..., bool],
    flatten_market_fn: Callable[..., Dict[str, Any]],
    clear_position_slot_fn: Callable[..., None],
    now_fn: Callable[[], float],
    time_fn: Callable[[], float],
    get_order_by_client_id_fn: Callable[..., Dict[str, Any]],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[dict], None],
    round_qty_fn: Callable[[Any], Any],
    iso_utc_fn: Callable[[], str],
    oid_int_fn: Callable[[Any], Any],
) -> None:
    """Retry exits placement for a live position stuck in OPEN_FILLED without exits."""
    pos = st.get("position") or {}
    if "failsafe_flatten" in pos:
        confirm_failsafe_flatten(
            st, env=env, save_state_fn=save_state_fn, log_event_fn=log_event_fn,
            send_webhook_fn=send_webhook_fn, clear_position_slot_fn=clear_position_slot_fn,
            now_fn=now_fn, iso_utc_fn=iso_utc_fn, oid_int_fn=oid_int_fn,
            get_order_by_client_id_fn=get_order_by_client_id_fn,
        )
        return
    if pos.get("mode") != "live" or pos.get("status") != "OPEN_FILLED":
        return
    if pos.get("orders") or not pos.get("prices"):
        return

    now = now_fn()
    next_try = float(pos.get("exits_next_try_s") or 0.0)
    if next_try and now < next_try:
        return

    tries = int(pos.get("exits_tries") or 0) + 1
    pos["exits_tries"] = tries
    pos.setdefault("exits_first_fail_s", now)
    pos["exits_next_try_s"] = now + float(env["EXITS_RETRY_EVERY_SEC"])
    st["position"] = pos
    save_state_fn(st)

    if ensure_exits_fn(st, pos, reason="retry", best_effort=True, attempt=tries):
        return

    if not env.get("FAILSAFE_FLATTEN", False):
        return
    max_tries = int(env.get("FAILSAFE_EXITS_MAX_TRIES") or 0)
    grace = float(env.get("FAILSAFE_EXITS_GRACE_SEC") or 0.0)
    first_fail_s = float(pos.get("exits_first_fail_s") or now)
    if max_tries and tries >= max_tries and (now - first_fail_s) >= grace:
        try:
            qty = float(pos.get("qty") or 0.0)
            valid_qty = math.isfinite(qty) and qty > 0 and Decimal(str(round_qty_fn(qty))) == Decimal(str(qty))
        except (TypeError, ValueError, ArithmeticError):
            valid_qty = False
        if pos.get("side") not in ("LONG", "SHORT") or not valid_qty:
            log_event_fn("FAILSAFE_FLATTEN_UNCONFIRMED", reason="invalid_position_qty_or_side")
            with suppress(Exception):
                send_webhook_fn({"event": "FAILSAFE_FLATTEN_UNCONFIRMED", "symbol": env["SYMBOL"],
                                 "reason": "invalid_position_qty_or_side", "requires_review": True})
            return
        intent = {"client_id": "EX_FLAT_" + uuid4().hex[:28], "symbol": env["SYMBOL"],
                  "position_side": pos["side"], "qty": str(qty), "status": "SUBMITTING",
                  "trade_mode": env["TRADE_MODE"],
                  "is_isolated": str(env.get("MARGIN_ISOLATED", "FALSE")),
                  "started_at": iso_utc_fn(), "next_check_s": 0.0}
        pos["failsafe_flatten"] = intent
        save_state_fn(st)  # MUST succeed before an irreversible exchange mutation
        try:
            flatten_market_fn(env["SYMBOL"], pos["side"], qty, client_id=intent["client_id"])
        except Exception as exc:
            # Rejection/timeout is not proof of closure or permission to resubmit.
            log_event_fn("FAILSAFE_FLATTEN_SUBMIT_ERROR", client_id=intent["client_id"], error=str(exc))
        confirm_failsafe_flatten(
            st, env=env, save_state_fn=save_state_fn, log_event_fn=log_event_fn,
            send_webhook_fn=send_webhook_fn, clear_position_slot_fn=clear_position_slot_fn,
            now_fn=now_fn, iso_utc_fn=iso_utc_fn, oid_int_fn=oid_int_fn,
            get_order_by_client_id_fn=get_order_by_client_id_fn,
        )


def confirm_failsafe_flatten(
    st: dict, *, env: Dict[str, Any], save_state_fn: Callable[[dict], None],
    log_event_fn: Callable[..., None], send_webhook_fn: Callable[[dict], None],
    clear_position_slot_fn: Callable[..., None], now_fn: Callable[[], float],
    iso_utc_fn: Callable[[], str], oid_int_fn: Callable[[Any], Any],
    get_order_by_client_id_fn: Callable[..., Dict[str, Any]],
) -> None:
    """Read-only recovery of a durable flatten intent; never resubmit MARKET."""
    pos = st.get("position") or {}
    intent = pos.get("failsafe_flatten")
    if not isinstance(intent, dict):
        log_event_fn("FAILSAFE_FLATTEN_UNCONFIRMED", reason="invalid_intent")
        with suppress(Exception):
            send_webhook_fn({"event": "FAILSAFE_FLATTEN_UNCONFIRMED", "symbol": env["SYMBOL"],
                             "reason": "invalid_intent", "requires_review": True})
        return
    now = now_fn()
    try:
        next_check = float(intent.get("next_check_s") or 0.0)
        if not math.isfinite(next_check) or next_check < 0:
            raise ValueError("invalid confirmation throttle")
    except (TypeError, ValueError, ArithmeticError):
        log_event_fn("FAILSAFE_FLATTEN_UNCONFIRMED", reason="invalid_confirmation_throttle")
        with suppress(Exception):
            send_webhook_fn({"event": "FAILSAFE_FLATTEN_UNCONFIRMED", "symbol": env["SYMBOL"],
                             "reason": "invalid_confirmation_throttle", "requires_review": True})
        return
    if now < next_check:
        return
    intent["next_check_s"] = now + max(1.0, float(env["LIVE_STATUS_POLL_EVERY"]))
    save_state_fn(st)  # persist the read throttle across restarts
    reason = "order_not_fully_filled"
    try:
        qty = Decimal(str(intent["qty"]))
        if (not qty.is_finite() or qty <= 0 or qty != Decimal(str(pos.get("qty")))
                or intent["symbol"] != env["SYMBOL"]
                or intent["position_side"] not in ("LONG", "SHORT")
                or intent["position_side"] != pos.get("side")
                or intent["trade_mode"] != env["TRADE_MODE"]
                or intent["is_isolated"] != str(env.get("MARGIN_ISOLATED", "FALSE"))):
            raise ValueError("flatten intent does not match current position/config")
        od = get_order_by_client_id_fn(intent["symbol"], intent["client_id"])
        if not isinstance(od, dict):
            raise ValueError("invalid flatten order response")
        exq = Decimal(str(od.get("executedQty")))
        original = Decimal(str(od.get("origQty")))
        if (od.get("clientOrderId") != intent["client_id"]
                or od.get("symbol") != intent["symbol"]
                or od.get("side") != ("SELL" if intent["position_side"] == "LONG" else "BUY")
                or od.get("type") != "MARKET"
                or not exq.is_finite() or exq < 0 or exq > qty
                or not original.is_finite() or original != qty
                or (oid_int_fn(od.get("orderId")) or 0) <= 0):
            raise ValueError("flatten order identity or quantity mismatch")
        intent["order_id"] = oid_int_fn(od["orderId"])
        intent["order_status"] = str(od.get("status") or "").upper()
        intent["executed_qty"] = str(exq)
        confirmed = intent["order_status"] == "FILLED" and exq == qty
    except Exception as exc:
        confirmed = False
        reason = str(exc)
    if confirmed:
        intent["status"] = "CONFIRMED"
        intent["confirmed_at"] = iso_utc_fn()
        save_state_fn(st)
        clear_position_slot_fn(st, "FAILSAFE_FLATTEN", tries=pos.get("exits_tries"),
                             flatten_confirmation=dict(intent))
        log_event_fn("FAILSAFE_FLATTEN_CONFIRMED", order_id=intent["order_id"],
                  client_id=intent["client_id"], executedQty=intent["executed_qty"])
        return
    intent["status"] = "UNCONFIRMED"
    notice = f"{intent.get('order_status', 'UNKNOWN')}:{reason}"
    changed = intent.get("last_notice") != notice
    intent["last_notice"] = notice
    save_state_fn(st)
    log_event_fn("FAILSAFE_FLATTEN_UNCONFIRMED", client_id=intent.get("client_id"), reason=reason,
              status=intent.get("order_status", "UNKNOWN"))
    if changed:
        with suppress(Exception):
            send_webhook_fn({"event": "FAILSAFE_FLATTEN_UNCONFIRMED", "symbol": env["SYMBOL"],
                          "client_id": intent.get("client_id"), "reason": reason,
                          "status": intent.get("order_status", "UNKNOWN"), "requires_review": True})
