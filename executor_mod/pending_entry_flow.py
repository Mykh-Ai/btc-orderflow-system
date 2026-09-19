#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pending entry order handling for the executor runtime loop."""
from __future__ import annotations

from executor_mod.order_utils import validated_executed_qty
from contextlib import suppress
import math
from typing import Any, Callable, Dict, Optional


def handle_pending_position(
    st: Dict[str, Any],
    *,
    env: Dict[str, Any],
    binance_api: Any,
    save_state_fn: Callable[[Dict[str, Any]], None],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    clear_position_slot_fn: Callable[..., None],
    now_fn: Callable[[], float],
    iso_utc_fn: Callable[[], str],
    time_fn: Callable[[], float],
    round_qty_fn: Callable[[Any], Any],
    fmt_price_fn: Callable[[Any], str],
    avg_fill_price_fn: Callable[[Dict[str, Any]], Any],
    oid_int_fn: Callable[[Any], Any],
    planb_market_allowed_fn: Callable[[Dict[str, Any], float], Any],
    margin_before_entry_fn: Callable[..., Any],
    margin_after_entry_opened_fn: Callable[..., Any],
    ensure_exits_fn: Callable[..., Any],
) -> bool:
    """Handle a live PENDING entry.

    Returns True when the caller must continue the main loop immediately,
    matching the old inline continue points.
    """
    posi = st.get("position") or {}
    if "failsafe_flatten" in posi:
        return False
    if posi.get("mode") != "live" or posi.get("status") != "PENDING":
        return False

    def _entry_executed_qty(order: Dict[str, Any], phase: str) -> Optional[float]:
        status = str(order.get("status", "")).upper()
        if status not in ("CANCELED", "EXPIRED", "REJECTED"):
            return float(order.get("executedQty") or 0.0)
        try:
            return float(validated_executed_qty(order))
        except ValueError as exc:
            # Terminal status is not proof of zero exposure. Reuse the existing
            # persisted reconciliation alert map, scoped to this owned order.
            event = "ENTRY_TERMINAL_QTY_UNKNOWN"
            key = f"entry_terminal_qty_unknown:{posi.get('order_id')}"
            last_emit = posi.setdefault("recon", {}).setdefault("last_emit", {})
            throttle_sec = int(env.get("RECON_THROTTLE_SEC") or env.get("INVAR_THROTTLE_SEC", 600) or 600)
            now = now_fn()
            try:
                last_ts = float(last_emit[key])
            except (KeyError, TypeError, ValueError):
                last_ts = None
            emit = last_ts is None or not math.isfinite(last_ts) or now - last_ts >= throttle_sec
            fields = {
                "severity": "CRITICAL", "mode": "live", "symbol": env["SYMBOL"],
                "order_id": posi.get("order_id"), "status": status, "phase": phase,
                "trade_key": posi.get("trade_key") or posi.get("client_id"),
                "error": str(exc), "executedQty_present": "executedQty" in order,
                "alert_suppressed": not emit, "throttle_sec": throttle_sec,
            }
            log_event_fn(event, **fields)
            if emit:
                last_emit[key] = now
            st["position"] = posi
            # Persist ownership and alert reservation before calling the webhook.
            # Repeated polls/reloads do not slide the original throttle window.
            save_state_fn(st)
            if emit:
                send_webhook_fn({"event": event, **fields})
            return None

    try:
        last_poll = float(posi.get("last_poll_s", 0.0))
        now_s = now_fn()
        if now_s - last_poll >= float(env["LIVE_STATUS_POLL_EVERY"]):
            oid = int(posi.get("order_id") or 0)
            if oid:
                od = binance_api.check_order_status(env["SYMBOL"], oid)
                posi["last_poll_s"] = now_s
                st["position"] = posi
                save_state_fn(st)

                stt = str(od.get("status", "")).upper()
                terminal_entry = stt in ("CANCELED", "REJECTED", "EXPIRED")
                terminal_exq = 0.0
                if terminal_entry:
                    # Terminal order status alone does not prove zero exposure.
                    # Unknown quantity stays PENDING for another poll.
                    terminal_exq = _entry_executed_qty(od, "poll")
                    if terminal_exq is None:
                        return False
                if stt == "FILLED" or (terminal_entry and terminal_exq > 0.0):
                    # Preserve executed exposure before hooks or exit placement.
                    posi["status"] = "OPEN_FILLED"
                    posi["filled_at"] = iso_utc_fn()
                    posi["executedQty"] = od.get("executedQty")
                    exq = float(od.get("executedQty") or 0.0)
                    if exq > 0.0:
                        posi["qty"] = float(round_qty_fn(exq))
                    avgp = avg_fill_price_fn(od)
                    if avgp:
                        posi["entry_actual"] = float(fmt_price_fn(avgp))

                    posi["cummulativeQuoteQty"] = od.get("cummulativeQuoteQty")
                    if terminal_entry and posi["cummulativeQuoteQty"] is None:
                        posi["cummulativeQuoteQty"] = od.get("cumulativeQuoteQty")
                    st["position"] = posi
                    save_state_fn(st)
                    fill_event = "ENTRY_TERMINAL_PARTIAL_FILLED" if terminal_entry else "FILLED"
                    fill_fields = {"status": stt} if terminal_entry else {}
                    log_event_fn(fill_event, mode="live", order_id=oid, executedQty=od.get("executedQty"), **fill_fields)
                    send_webhook_fn({"event": fill_event, "mode": "live", "order_id": oid, "order": od, **fill_fields})
                    with suppress(Exception):
                        margin_after_entry_opened_fn(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
                    # Place TP1/TP2/SL (no OCO) right after fill confirmation
                    if not posi.get("orders") and posi.get("prices"):
                        ensure_exits_fn(st, posi, reason="filled", best_effort=True)

                elif terminal_entry:
                    clear_position_slot_fn(st, f"ENTRY_{stt}", order_id=oid, status=stt)
                    log_event_fn("ENTRY_DONE", mode="live", status=stt, order_id=oid)
                    return True
        # Timeout cancel
        opened_s = float(posi.get("opened_s") or 0.0)
        if not opened_s:
            opened_s = now_s
            posi["opened_s"] = opened_s
            st["position"] = posi
            save_state_fn(st)
        else:
            posi["opened_s"] = opened_s
        now = now_fn()
        if now - opened_s >= float(env["LIVE_ENTRY_TIMEOUT_SEC"]):
        # throttle timeout actions to avoid spamming Binance API
            next_act_s = float(posi.get("planb_next_action_s") or 0.0)
            if next_act_s and now < next_act_s:
                return True
            oid = int(posi.get("order_id") or 0)

            if oid and posi.get("status") == "PENDING":
                # Plan B: timeout -> cancel LIMIT and fall back to MARKET (unless ENTRY_MODE=LIMIT_ONLY).
                od_t = binance_api.check_order_status(env["SYMBOL"], oid)
                exq_t = _entry_executed_qty(od_t, "timeout")
                if exq_t is None:
                    return False

                def _try_place_exits_now() -> None:
                    # Best-effort immediate exits placement (reduces naked exposure window).
                    if posi.get("orders") or not posi.get("prices"):
                        return
                    ensure_exits_fn(st, posi, reason="try_now", best_effort=True, save_on_fail=True)

                if exq_t > 0.0:
                    # Order partially/fully filled: keep the filled part and proceed to exits.
                    with suppress(Exception):
                        binance_api.cancel_order(env["SYMBOL"], oid)
                    posi["status"] = "OPEN_FILLED"
                    posi["filled_at"] = iso_utc_fn()
                    posi["executedQty"] = od_t.get("executedQty")
                    posi["cummulativeQuoteQty"] = od_t.get("cummulativeQuoteQty") or od_t.get("cumulativeQuoteQty")
                    posi["qty"] = float(round_qty_fn(exq_t))
                    avgp_t = avg_fill_price_fn(od_t)
                    if avgp_t:
                        posi["entry_actual"] = float(fmt_price_fn(avgp_t))
                    st["position"] = posi
                    save_state_fn(st)
                    log_event_fn("ENTRY_TIMEOUT_PARTIAL_FILLED", mode="live", order_id=oid, executedQty=exq_t)
                    send_webhook_fn({"event": "ENTRY_TIMEOUT_PARTIAL_FILLED", "mode": "live", "order_id": oid, "executedQty": exq_t})
                    with suppress(Exception):
                        margin_after_entry_opened_fn(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
                    _try_place_exits_now()
                else:
                    # Cancel LIMIT (best-effort)
                    with suppress(Exception):
                        binance_api.cancel_order(env["SYMBOL"], oid)

                    # Re-check once after cancel to catch a late fill (avoid double-entry).
                    od_after = None
                    with suppress(Exception):
                        od_after = binance_api.check_order_status(env["SYMBOL"], oid)
                    if od_after:
                        exq_after = _entry_executed_qty(od_after, "after_cancel")
                        if exq_after is None:
                            return False
                        st_after = str(od_after.get("status", "")).upper()
                        if st_after == "FILLED" or exq_after > 0.0:
                            posi["status"] = "OPEN_FILLED"
                            posi["filled_at"] = iso_utc_fn()
                            posi["executedQty"] = od_after.get("executedQty")
                            posi["cummulativeQuoteQty"] = od_after.get("cummulativeQuoteQty") or od_after.get("cumulativeQuoteQty")
                            posi["qty"] = float(round_qty_fn(exq_after))
                            avgp_a = avg_fill_price_fn(od_after)
                            if avgp_a:
                                posi["entry_actual"] = float(fmt_price_fn(avgp_a))
                            st["position"] = posi
                            save_state_fn(st)
                            log_event_fn("ENTRY_TIMEOUT_LATE_FILL", mode="live", order_id=oid, executedQty=exq_after, status=st_after)
                            send_webhook_fn({"event": "ENTRY_TIMEOUT_LATE_FILL", "mode": "live", "order_id": oid, "executedQty": exq_after, "status": st_after})
                            with suppress(Exception):
                                margin_after_entry_opened_fn(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
                            _try_place_exits_now()
                            return True
                    # Only place MARKET when LIMIT is confirmed canceled/expired/rejected; otherwise wait.
                    st_after = str((od_after or {}).get("status", "")).upper()
                    if st_after not in ("CANCELED", "EXPIRED", "REJECTED"):
                        posi["planb_next_action_s"] = now + float(env["LIVE_STATUS_POLL_EVERY"])
                        st["position"] = posi
                        save_state_fn(st)
                        log_event_fn("ENTRY_TIMEOUT_WAIT_CANCEL", mode="live", order_id=oid, status=st_after or "UNKNOWN")
                        return True

                    entry_mode = str(env.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper()
                    if entry_mode == "LIMIT_ONLY":
                        log_event_fn("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="NONE")
                        send_webhook_fn({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "NONE"})
                        clear_position_slot_fn(st, "ENTRY_TIMEOUT", order_id=oid, fallback="NONE")
                    else:
                        entry_side = "BUY" if posi.get("side") == "LONG" else "SELL"

                        px_exec = None
                        try:
                            px_exec = binance_api._planb_exec_price(env["SYMBOL"], entry_side)
                        except Exception as ee:
                            log_event_fn("PLANB_PRICE_ERROR", error=str(ee), order_id=oid)

                        if px_exec is None:
                            if env.get("PLANB_REQUIRE_PRICE", True):
                                log_event_fn("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="ABORT_NO_PRICE")
                                send_webhook_fn({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "ABORT_NO_PRICE"})
                                clear_position_slot_fn(st, "ENTRY_TIMEOUT_ABORT", order_id=oid, fallback="ABORT_NO_PRICE")
                                return True

                        if px_exec is not None:
                            ok, why, info = planb_market_allowed_fn(posi, float(px_exec))
                            if not ok:
                                log_event_fn("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback=f"ABORT_{why}", **info)
                                send_webhook_fn({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": f"ABORT_{why}", "info": info})
                                clear_position_slot_fn(st, "ENTRY_TIMEOUT_ABORT", order_id=oid, fallback=f"ABORT_{why}", **info)
                                return True
                        with suppress(Exception):
                            margin_before_entry_fn(st, env["SYMBOL"], entry_side, float(posi.get("qty") or 0.0), plan={
                                "trade_key": posi.get("trade_key") or posi.get("client_id") or posi.get("order_id"),
                            })
                        try:
                            mkt = binance_api.place_spot_market(env["SYMBOL"], entry_side, float(posi.get("qty") or 0.0), client_id=f"EX_EN_MKT_{int(time_fn())}")
                        except Exception as ee:
                            log_event_fn("ENTRY_TIMEOUT_MARKET_ERROR", error=str(ee), order_id=oid)
                            send_webhook_fn({"event": "ENTRY_TIMEOUT_MARKET_ERROR", "order_id": oid, "error": str(ee)})
                            clear_position_slot_fn(st, "ENTRY_TIMEOUT_MARKET_ERROR", order_id=oid, error=str(ee))
                        else:
                            oid2 = oid_int_fn(mkt.get("orderId"))
                            if not oid2:
                                log_event_fn("ENTRY_TIMEOUT_MARKET_NO_OID", order_id=oid)
                                send_webhook_fn({"event": "ENTRY_TIMEOUT_MARKET_NO_OID", "order_id": oid})
                                clear_position_slot_fn(st, "ENTRY_TIMEOUT_MARKET_NO_OID", order_id=oid)
                            else:
                                # Market should fill immediately, but confirm once.
                                od2 = binance_api.check_order_status(env["SYMBOL"], int(oid2))
                                exq2 = float(od2.get("executedQty") or 0.0)
                                posi["order_id"] = int(oid2)
                                posi["client_id"] = f"EX_EN_MKT_{int(time_fn())}"
                                posi["opened_s"] = now
                                posi["opened_at"] = iso_utc_fn()
                                posi["planb_next_action_s"] = now + float(env["LIVE_STATUS_POLL_EVERY"])
                                if exq2 > 0.0:
                                    posi["status"] = "OPEN_FILLED"
                                    posi["filled_at"] = iso_utc_fn()
                                    posi["qty"] = float(round_qty_fn(exq2))
                                    avgp2 = avg_fill_price_fn(od2) or avg_fill_price_fn(mkt)
                                    if avgp2:
                                        posi["entry_actual"] = float(fmt_price_fn(avgp2))
                                    st["position"] = posi
                                    save_state_fn(st)
                                    with suppress(Exception):
                                        margin_after_entry_opened_fn(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid2))
                                    _try_place_exits_now()
                                else:
                                    # Unexpected: market not filled. Keep pending and let poll loop handle it.
                                    posi["status"] = "PENDING"
                                    st["position"] = posi
                                    save_state_fn(st)

                                log_event_fn("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="MARKET", new_order_id=oid2)
                                send_webhook_fn({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "MARKET", "new_order_id": oid2})
    except Exception as e:
        log_event_fn("LIVE_POLL_ERROR", error=str(e))

    return False
