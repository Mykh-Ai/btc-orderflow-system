#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live position manager for V1.5 exit lifecycle."""
from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Dict


def manage_v15_position(
    symbol: str,
    st: Dict[str, Any],
    *,
    env: Dict[str, Any],
    binance_api: Any,
    save_state_fn: Callable[[Dict[str, Any]], None],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    now_fn: Callable[[], float],
    iso_utc_fn: Callable[[], str],
    time_module: Any,
    round_qty_fn: Callable[[Any], Any],
    fmt_qty_fn: Callable[[Any], str],
    fmt_price_fn: Callable[[Any], str],
    oid_int_fn: Callable[[Any], Any],
    trail_desired_stop_fn: Callable[[dict], Any],
    record_trade_execution_snapshot_fn: Callable[..., Any],
    send_trade_closed_summary_fn: Callable[..., None],
    build_live_close_last_closed_fn: Callable[..., Dict[str, Any]],
    record_outcome_fn: Callable[..., Any],
    margin_after_position_closed_fn: Callable[..., Any],
) -> None:
    """Live V1.5 manager: TP1 -> move SL to BE (entry), TP2 continues.

    Optimized:
      - Throttled by MANAGE_EVERY_SEC in main loop
      - Uses a single openOrders fetch
      - Verifies missing orders via order status (FILLED) before acting
    """
    pos = st.get("position") or {}
    if pos.get("mode") != "live" or pos.get("status") not in ("OPEN", "OPEN_FILLED"):
        return
    if not pos.get("orders") or not pos.get("prices"):
        return
    now_s = now_fn()
    try:
        orders = binance_api.open_orders(symbol)
    except Exception as e:
        # Do not abort manage-cycle: openOrders can be empty/incomplete or fail transiently.
        # We still can verify FILLED via check_order_status and cancel siblings best-effort.
        orders = []
        now_err = now_fn()
        last_err = float(pos.get("open_orders_err_s") or 0.0)
        if now_err - last_err >= 30.0:
            pos["open_orders_err_s"] = now_err
            st["position"] = pos
            save_state_fn(st)
            log_event_fn("LIVE_MANAGE_ERROR", error=f"openOrders: {e}")

    open_ids: set[int] = set()
    for _o in (orders or []):
        if not isinstance(_o, dict):
            continue
        with suppress(Exception):
            open_ids.add(int(_o.get("orderId")))

    def _status_is_filled(order_id: int) -> bool:
        try:
            od = binance_api.check_order_status(symbol, int(order_id))
            return str(od.get("status", "")).upper() == "FILLED"
        except Exception:
            return False

    def _close_slot(reason: str) -> None:
        st["last_closed"] = build_live_close_last_closed_fn(pos, reason, iso_utc_fn())
        execution_snapshot = record_trade_execution_snapshot_fn(st, "_close_slot", enrich_exchange=True)
        st["position"] = None
        st["cooldown_until"] = now_fn() + float(env["COOLDOWN_SEC"])
        st["lock_until"] = 0.0
        save_state_fn(st)
        with suppress(Exception):
            record_outcome_fn(st, "_close_slot", env.get("SYMBOL", ""))
        with suppress(Exception):
            margin_after_position_closed_fn(st)
        send_trade_closed_summary_fn(st, execution_snapshot)

    tp1_id = int(pos["orders"].get("tp1") or 0)
    tp2_id = int(pos["orders"].get("tp2") or 0)
    sl_id = int(pos["orders"].get("sl") or 0)
    sl_prev = int(pos["orders"].get("sl_prev") or 0)

    # Якщо після TP1 ми замінили SL на BE, але старий SL не скасувався (або cancel впав),
    # то треба повторювати cancel best-effort раз на N секунд (без перевірки openOrders).
    if sl_prev and pos.get("tp1_done"):
        now_s = now_fn()
        next_s = float(pos.get("sl_prev_next_cancel_s") or 0.0)
        if now_s >= next_s:
            pos["sl_prev_next_cancel_s"] = now_s + float(env.get("ORPHAN_CANCEL_EVERY_SEC", 30))
            st["position"] = pos
            save_state_fn(st)
            with suppress(Exception):
                binance_api.cancel_order(symbol, sl_prev)

    # TP1 filled -> move SL to BE (entry) for remaining qty2+qty3
    if tp1_id and not pos.get("tp1_done"):
        poll_due = now_s >= float(pos.get("tp1_status_next_s") or 0.0)
        # Do not gate FILLED detection on openOrders/open_ids; throttle via tp1_status_next_s
        if poll_due or (not orders):
            pos["tp1_status_next_s"] = now_s + float(env["LIVE_STATUS_POLL_EVERY"])

            if _status_is_filled(tp1_id):
                exit_side = "SELL" if pos["side"] == "LONG" else "BUY"
                be_stop = float(pos.get("entry_actual") or (pos.get("prices") or {}).get("entry") or 0.0)

                qty2 = float((pos.get("orders") or {}).get("qty2") or 0.0)
                qty3 = float((pos.get("orders") or {}).get("qty3") or 0.0)
                rem_qty = float(round_qty_fn(qty2 + qty3))

                tick = float(env["TICK_SIZE"])
                gap_ticks = max(1, int(env.get("SL_LIMIT_GAP_TICKS") or 0))
                gap = tick * float(gap_ticks)
                be_limit = (be_stop - gap) if exit_side == "SELL" else (be_stop + gap)
                be_stop_s = fmt_price_fn(be_stop)
                be_limit_s = fmt_price_fn(be_limit)
                # Ensure price != stopPrice even after rounding
                if be_limit_s == be_stop_s:
                    be_limit_s = fmt_price_fn((be_stop - tick) if exit_side == "SELL" else (be_stop + tick))
                # Cancel old SL FIRST (and confirm), then place new BE SL.
                old_sl_id = int((pos.get("orders") or {}).get("sl") or 0)
                if old_sl_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, old_sl_id)
                    od_c = None
                    with suppress(Exception):
                        od_c = binance_api.check_order_status(symbol, old_sl_id)
                    st_c = str((od_c or {}).get("status", "")).upper()
                    if st_c not in ("CANCELED", "REJECTED", "EXPIRED"):
                        log_event_fn(
                            "TP1_SL_TO_BE_WAIT_CANCEL",
                            mode="live",
                            order_id_tp1=tp1_id,
                            order_id_sl=old_sl_id,
                            status=st_c or "UNKNOWN",
                        )
                        return

                try:
                    sl_new = binance_api.place_order_raw({
                        "symbol": symbol,
                        "side": exit_side,
                        "type": "STOP_LOSS_LIMIT",
                        "quantity": fmt_qty_fn(rem_qty),
                        "price": be_limit_s,
                        "stopPrice": be_stop_s,
                        "timeInForce": "GTC",
                        "newClientOrderId": f"EX_SL_BE_{int(time_module.time())}",
                    })
                except Exception as e:
                    log_event_fn("TP1_SL_TO_BE_ERROR", error=str(e), mode="live", order_id_tp1=tp1_id)
                    send_webhook_fn({"event": "TP1_SL_TO_BE_ERROR", "mode": "live", "symbol": symbol, "order_id_tp1": tp1_id, "error": str(e)})
                else:
                    # Keep old SL id for best-effort orphan cleanup (if needed).
                    if old_sl_id:
                        pos["orders"]["sl_prev"] = old_sl_id
                        pos["sl_prev_next_cancel_s"] = now_fn()
                    pos["orders"]["sl"] = oid_int_fn(sl_new.get("orderId"))
                    pos["prices"]["sl"] = be_stop
                    pos["tp1_done"] = True
                    st["position"] = pos
                    save_state_fn(st)
                    log_event_fn("TP1_DONE_SL_TO_BE", mode="live", order_id_tp1=tp1_id, new_sl_order_id=sl_new.get("orderId"))
                    send_webhook_fn({"event": "TP1_DONE_SL_TO_BE", "mode": "live", "symbol": symbol, "new_sl_order_id": sl_new.get("orderId"), "entry": be_stop})
            else:
                # Log once to avoid spam; can happen if order exists but is not filled yet.
                miss = pos.setdefault("missing_not_filled", {})
                key = f"tp1:{tp1_id}"
                if poll_due and not miss.get(key):
                    miss[key] = iso_utc_fn()
                    st["position"] = pos
                    save_state_fn(st)
                    log_event_fn("TP1_NOT_FILLED", mode="live", order_id_tp1=tp1_id)

    # TP2 filled -> activate trailing SL for remaining qty3 (if configured)
    if tp2_id and not pos.get("tp2_done"):
        if _status_is_filled(tp2_id):
            pos["tp2_done"] = True
            st["position"] = pos
            save_state_fn(st)
            log_event_fn("TP2_DONE", mode="live", order_id_tp2=tp2_id)
            send_webhook_fn({"event": "TP2_DONE", "mode": "live", "symbol": symbol})

            qty3 = float((pos.get("orders") or {}).get("qty3") or 0.0)
            qty1 = float((pos.get("orders") or {}).get("qty1") or 0.0)
            tp1_filled_now = bool(pos.get("tp1_done"))
            if (not tp1_filled_now) and tp1_id:
                with suppress(Exception):
                    tp1_filled_now = _status_is_filled(tp1_id)
            open_qty = qty3 if tp1_filled_now else (qty1 + qty3)
            if env.get("TRAIL_ACTIVATE_AFTER_TP2", True) and open_qty > 0.0:

                # cancel TP1 best-effort (should already be filled, but do not assume)
                if tp1_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, tp1_id)

                # replace current SL with trailing SL for remaining qty (qty3, or qty1+qty3 if TP2 filled first)
                sl_now = int((pos.get("orders") or {}).get("sl") or 0)

               # Primary: trailing stop from aggregated.csv swings (low API usage).
                desired = trail_desired_stop_fn(pos)
                if desired is None:
                    # Fallback (only if CSV unavailable): public mid-price +/- buffer
                    mid = 0.0
                    with suppress(Exception):
                        mid = float(binance_api.get_mid_price(symbol))
                    if mid > 0.0:
                        off = float(env.get("TRAIL_SWING_BUFFER_USD") or 15.0)
                        desired = (mid - off) if pos["side"] == "LONG" else (mid + off)

                if desired is not None:
                    desired_f = float(fmt_price_fn(desired))
                    if desired_f <= 0.0:
                        desired = None

                if desired is not None:
                    exit_side = "SELL" if pos["side"] == "LONG" else "BUY"
                    # Optional gap between stopPrice and limit price for STOP_LOSS_LIMIT (reduces rejections).
                    tick = float(env["TICK_SIZE"])
                    gap_ticks = max(1, int(env.get("SL_LIMIT_GAP_TICKS") or 0))
                    gap = tick * float(gap_ticks)
                    stop_p = desired_f
                    limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
                    sl_stop_s = fmt_price_fn(stop_p)
                    sl_price_s = fmt_price_fn(limit_p)
                    # Ensure price != stopPrice even after rounding
                    if sl_price_s == sl_stop_s:
                        sl_price_s = fmt_price_fn((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))

                    # Safety: do NOT place a new trailing SL unless previous SL cancel is confirmed.
                    sl_canceled_ok = True
                    if sl_now:
                        sl_canceled_ok = False
                        with suppress(Exception):
                            binance_api.cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = binance_api.check_order_status(symbol, sl_now)
                        st_c = str((od_c or {}).get("status", "")).upper()
                        if st_c in ("CANCELED", "REJECTED", "EXPIRED"):
                            sl_canceled_ok = True
                            pos.setdefault("orders", {})["sl"] = 0
                            pos["trail_pending_cancel_sl"] = 0
                        else:
                            pos["trail_pending_cancel_sl"] = sl_now
                            pos["trail_active"] = True
                            pos["trail_qty"] = open_qty
                            # Force quick retry via trailing maintenance (still rate-limited).
                            pos["trail_last_update_s"] = 0.0
                            st["position"] = pos
                            save_state_fn(st)
                            log_event_fn("TRAIL_ACTIVATE_WAIT_CANCEL", mode="live", order_id_sl=sl_now, status=st_c or "UNKNOWN")
                            return
                    else:
                        pos["trail_pending_cancel_sl"] = 0
                    try:
                        sl_new = binance_api.place_order_raw({
                            "symbol": symbol,
                            "side": exit_side,
                            "type": "STOP_LOSS_LIMIT",
                            "quantity": fmt_qty_fn(open_qty),
                            "price": sl_price_s,
                            "stopPrice": sl_stop_s,
                            "timeInForce": "GTC",
                            "newClientOrderId": f"EX_SL_TR_{int(time_module.time())}",
                        })
                    except Exception as e:
                        log_event_fn("TRAIL_SL_PLACE_ERROR", error=str(e), mode="live")
                        # Fallback: immediately restore a protective SL (BE if TP1 filled, else original SL)
                        fb_stop = float(pos.get("entry_actual") or (pos.get("prices") or {}).get("entry") or 0.0) if tp1_filled_now else float((pos.get("prices") or {}).get("sl") or 0.0)
                        if fb_stop > 0.0:
                            gap_ticks = max(1, int(env.get("SL_LIMIT_GAP_TICKS") or 0))
                            gap = tick * float(gap_ticks)
                            fb_limit = (fb_stop - gap) if exit_side == "SELL" else (fb_stop + gap)
                            fb_stop_s = fmt_price_fn(fb_stop)
                            fb_limit_s = fmt_price_fn(fb_limit)
                            if fb_limit_s == fb_stop_s:
                                fb_limit_s = fmt_price_fn((fb_stop - tick) if exit_side == "SELL" else (fb_stop + tick))
                            try:
                                fb = binance_api.place_order_raw({
                                    "symbol": symbol,
                                    "side": exit_side,
                                    "type": "STOP_LOSS_LIMIT",
                                    "quantity": fmt_qty_fn(open_qty),
                                    "price": fb_limit_s,
                                    "stopPrice": fb_stop_s,
                                    "timeInForce": "GTC",
                                    "newClientOrderId": f"EX_SL_FB_{int(time_module.time())}",
                                })
                            except Exception as e2:
                                log_event_fn("TRAIL_SL_FALLBACK_ERROR", error=str(e2), mode="live")
                            else:
                                if fb.get("orderId"):
                                    pos["orders"]["sl"] = oid_int_fn(fb.get("orderId"))
                                pos["trail_sl_price"] = float(fmt_price_fn(fb_stop))
                                log_event_fn("TRAIL_SL_FALLBACK_PLACED", mode="live", new_sl_order_id=fb.get("orderId"), trail_stop=pos.get("trail_sl_price"))
                        # Keep trail flags so we retry on next manage tick
                        pos["trail_active"] = True
                        pos["trail_qty"] = open_qty
                        pos["trail_last_update_s"] = now_s
                        st["position"] = pos
                        save_state_fn(st)
                        return
                    else:
                        pos["orders"]["sl"] = oid_int_fn(sl_new.get("orderId"))
                        pos["trail_active"] = True
                        pos["trail_qty"] = open_qty
                        pos["trail_sl_price"] = float(fmt_price_fn(stop_p))
                        pos["trail_last_update_s"] = now_s
                        pos["status"] = "OPEN"
                        st["position"] = pos
                        save_state_fn(st)
                        log_event_fn("TRAIL_ACTIVATED_AFTER_TP2", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])
                        send_webhook_fn({"event": "TRAIL_ACTIVATED_AFTER_TP2", "mode": "live", "symbol": symbol, "new_sl_order_id": sl_new.get("orderId"), "trail_stop": pos["trail_sl_price"]})
                        return

                # No price right now -> mark trailing active and retry next tick
                pos["trail_active"] = True
                pos["trail_qty"] = open_qty
                pos["trail_last_update_s"] = now_s
                st["position"] = pos
                save_state_fn(st)
                log_event_fn("TRAIL_ACTIVATED_AFTER_TP2", mode="live", new_sl_order_id=None, trail_stop=None)
                return

            # No trailing configured -> close slot only if nothing remains
            if open_qty > 0.0:
                # Remaining exposure but trailing disabled: do NOT clear slot here
                pos["tp2_done"] = True
                st["position"] = pos
                save_state_fn(st)
                log_event_fn("TP2_DONE_REMAINING_QTY_NO_TRAIL",
                          mode="live", order_id_tp2=tp2_id, open_qty=open_qty)
                return

            # No remaining qty -> close slot like before

            sl_now = int((pos.get("orders") or {}).get("sl") or 0)
            if sl_now:
                with suppress(Exception):
                    binance_api.cancel_order(symbol, sl_now)
            if tp1_id:
                with suppress(Exception):
                    binance_api.cancel_order(symbol, tp1_id)
            sl_prev2 = int((pos.get("orders") or {}).get("sl_prev") or 0)
            if sl_prev2:
                with suppress(Exception):
                    binance_api.cancel_order(symbol, sl_prev2)
            _close_slot("TP2")
            return
        else:
            miss = pos.setdefault("missing_not_filled", {})
            key = f"tp2:{tp2_id}"
            if not miss.get(key):
                miss[key] = iso_utc_fn()
                st["position"] = pos
                save_state_fn(st)
                log_event_fn("TP2_NOT_FILLED", mode="live", order_id_tp2=tp2_id)

    # Trailing SL maintenance (after TP2) — emulate trailing by cancel/replace, prefer aggregated.csv swings
    if pos.get("trail_active"):
        last_u = float(pos.get("trail_last_update_s") or 0.0)
        every = float(env.get("TRAIL_UPDATE_EVERY_SEC") or 20)
        if now_s - last_u >= every:
            # Primary: aggregated.csv swings (no Binance polling).
            desired = trail_desired_stop_fn(pos)
            if desired is None and str(env.get("TRAIL_SOURCE") or "AGG").upper() != "AGG":
                # Optional fallback if user forces BINANCE source and CSV is unavailable.
                mid = 0.0
                with suppress(Exception):
                    mid = float(binance_api.get_mid_price(symbol))
                if mid > 0.0:
                    off = float(env.get("TRAIL_SWING_BUFFER_USD") or 15.0)
                    desired = (mid - off) if pos["side"] == "LONG" else (mid + off)
            if desired is not None:
                step = float(env.get("TRAIL_STEP_USD") or 20.0)
                desired_f = float(fmt_price_fn(desired))
                current_f = float(pos.get("trail_sl_price") or 0.0)

                sl_now = int((pos.get("orders") or {}).get("sl") or 0)
                exit_side = "SELL" if pos["side"] == "LONG" else "BUY"

                # If activation asked to cancel an old SL, wait for cancel confirmation before placing a new one.
                pend_sl = int(pos.get("trail_pending_cancel_sl") or 0)
                if pend_sl:
                    od_p = None
                    with suppress(Exception):
                        od_p = binance_api.check_order_status(symbol, pend_sl)
                    st_p = str((od_p or {}).get("status", "")).upper()
                    if st_p not in ("CANCELED", "REJECTED", "EXPIRED"):
                        pos["trail_last_update_s"] = now_s
                        st["position"] = pos
                        save_state_fn(st)
                        log_event_fn("TRAIL_WAIT_CANCEL", mode="live", order_id_sl=pend_sl, status=st_p or "UNKNOWN")
                        return
                    pos["trail_pending_cancel_sl"] = 0
                    pos.setdefault("orders", {})["sl"] = 0
                    sl_now = 0

                # If stored SL is already not active -> treat as missing (restore path will handle).
                if sl_now:
                    od_s = None
                    with suppress(Exception):
                        od_s = binance_api.check_order_status(symbol, sl_now)
                    st_s = str((od_s or {}).get("status", "")).upper()
                    if st_s in ("CANCELED", "REJECTED", "EXPIRED"):
                        pos.setdefault("orders", {})["sl"] = 0
                        sl_now = 0

                tick = float(env["TICK_SIZE"])
                gap_ticks = max(1, int(env.get("SL_LIMIT_GAP_TICKS") or 0))
                gap = tick * float(gap_ticks)
                stop_p = desired_f
                limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
                sl_stop_s = fmt_price_fn(stop_p)
                sl_price_s = fmt_price_fn(limit_p)
                if sl_price_s == sl_stop_s:
                    sl_price_s = fmt_price_fn((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))

                trail_qty = float(pos.get("trail_qty") or 0.0)
                if trail_qty <= 0.0:
                    log_event_fn("TRAIL_SL_SKIP_ZERO_QTY", mode="live")
                else:
                    improve = (desired_f - current_f) if pos["side"] == "LONG" else (current_f - desired_f)

                    # If SL disappeared while trailing is active -> restore immediately (best-effort).
                    if not sl_now:
                        try:
                            sl_new = binance_api.place_order_raw({
                                "symbol": symbol,
                                "side": exit_side,
                                "type": "STOP_LOSS_LIMIT",
                                "quantity": fmt_qty_fn(trail_qty),
                                "price": sl_price_s,
                                "stopPrice": sl_stop_s,
                                "timeInForce": "GTC",
                                "newClientOrderId": f"EX_SL_TR_RESTORE_{int(time_module.time())}",
                            })
                        except Exception as e:
                            err_msg = str(e)
                            err_code = None
                            with suppress(Exception):
                                if getattr(e, "code", None) is not None:
                                    err_code = int(getattr(e, "code"))
                            if err_code is None and ('"code":-2010' in err_msg or '"code": -2010' in err_msg):
                                err_code = -2010
                            if err_code is None:
                                err_code = 0
                            pos["trail_last_error_code"] = err_code
                            pos["trail_last_error_s"] = now_s
                            pos["trail_error_count"] = int(pos.get("trail_error_count") or 0) + 1
                            st["position"] = pos
                            with suppress(Exception):
                                save_state_fn(st)
                            log_event_fn("TRAIL_SL_RESTORE_ERROR", error=str(e), mode="live")
                        else:
                            pos["orders"]["sl"] = oid_int_fn(sl_new.get("orderId"))
                            pos["trail_sl_price"] = float(sl_stop_s)
                            pos["trail_last_update_s"] = now_s
                            st["position"] = pos
                            save_state_fn(st)
                            log_event_fn("TRAIL_SL_RESTORED", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])

                    elif improve >= step:
                        # Cancel/replace. Do NOT place a new SL unless cancel is confirmed.
                        with suppress(Exception):
                            binance_api.cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = binance_api.check_order_status(symbol, sl_now)
                        st_c = str((od_c or {}).get("status", "")).upper()
                        if st_c not in ("CANCELED", "REJECTED", "EXPIRED"):
                            pos["trail_last_update_s"] = now_s
                            st["position"] = pos
                            save_state_fn(st)
                            log_event_fn("TRAIL_SL_CANCEL_NOT_CONFIRMED", mode="live", order_id_sl=sl_now, status=st_c or "UNKNOWN")
                        else:
                            try:
                                sl_new = binance_api.place_order_raw({
                                    "symbol": symbol,
                                    "side": exit_side,
                                    "type": "STOP_LOSS_LIMIT",
                                    "quantity": fmt_qty_fn(trail_qty),
                                    "price": sl_price_s,
                                    "stopPrice": sl_stop_s,
                                    "timeInForce": "GTC",
                                    "newClientOrderId": f"EX_SL_TR_{int(time_module.time())}",
                                })
                            except Exception as e:
                                err_msg = str(e)
                                err_code = None
                                with suppress(Exception):
                                    if getattr(e, "code", None) is not None:
                                        err_code = int(getattr(e, "code"))
                                if err_code is None and ('"code":-2010' in err_msg or '"code": -2010' in err_msg):
                                    err_code = -2010
                                if err_code is None:
                                    err_code = 0
                                pos["trail_last_error_code"] = err_code
                                pos["trail_last_error_s"] = now_s
                                pos["trail_error_count"] = int(pos.get("trail_error_count") or 0) + 1
                                st["position"] = pos
                                with suppress(Exception):
                                    save_state_fn(st)
                                log_event_fn("TRAIL_SL_UPDATE_ERROR", error=str(e), mode="live")
                            else:
                                pos["orders"]["sl"] = oid_int_fn(sl_new.get("orderId"))
                                pos["trail_sl_price"] = float(sl_stop_s)
                                pos["trail_last_update_s"] = now_s
                                st["position"] = pos
                                save_state_fn(st)
                                log_event_fn("TRAIL_SL_UPDATED", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])

            # advance last_update even if no price, to avoid tight loop
            pos["trail_last_update_s"] = now_s
            st["position"] = pos
            save_state_fn(st)

    # SL filled -> close slot
    sl_id2 = int((pos.get("orders") or {}).get("sl") or 0)
    if sl_id2 and not pos.get("sl_done"):
        poll_due = now_s >= float(pos.get("sl_status_next_s") or 0.0)

        # Do not gate FILLED detection on openOrders/open_ids; throttle via sl_status_next_s
        if poll_due or (not orders):
            pos["sl_status_next_s"] = now_s + float(env["LIVE_STATUS_POLL_EVERY"])

            if _status_is_filled(sl_id2):
                pos["sl_done"] = True
                st["position"] = pos
                save_state_fn(st)
                log_event_fn("SL_DONE", mode="live", order_id_sl=sl_id2)
                send_webhook_fn({"event": "SL_DONE", "mode": "live", "symbol": symbol})

                # cancel any remaining exits (best-effort) to avoid orphan orders
                if tp1_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, tp1_id)
                if tp2_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, tp2_id)

                sl_prev3 = int((pos.get("orders") or {}).get("sl_prev") or 0)
                if sl_prev3:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, sl_prev3)

                _close_slot("SL")
            else:
                miss = pos.setdefault("missing_not_filled", {})
                key = f"sl:{sl_id2}"
                if not miss.get(key):
                    miss[key] = iso_utc_fn()
                    st["position"] = pos
                    save_state_fn(st)
                    log_event_fn("SL_NOT_FILLED", mode="live", order_id_sl=sl_id2)
