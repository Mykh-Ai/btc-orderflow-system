#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Open-entry event handling for the executor runtime loop."""
from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Dict


def handle_open_entry_event(
    st: Dict[str, Any],
    evt: Dict[str, Any],
    *,
    env: Dict[str, Any],
    binance_api: Any,
    save_state_fn: Callable[[Dict[str, Any]], None],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    sync_from_binance_fn: Callable[[Dict[str, Any]], None],
    locked_fn: Callable[[Dict[str, Any]], bool],
    in_cooldown_fn: Callable[[Dict[str, Any]], bool],
    has_open_position_fn: Callable[[Dict[str, Any]], bool],
    now_fn: Callable[[], float],
    iso_utc_fn: Callable[[], str],
    time_fn: Callable[[], float],
    dt_utc_fn: Callable[[Any], Any],
    to_datetime_fn: Callable[..., Any],
    load_df_sorted_fn: Callable[[], Any],
    locate_index_by_ts_fn: Callable[[Any, Any], int],
    build_entry_price_fn: Callable[[str, float], float],
    swing_stop_far_fn: Callable[[Any, int, str, float], float],
    compute_tps_fn: Callable[[float, float, str], Any],
    get_usdt_usdc_k_fn: Callable[[], float],
    floor_to_step_fn: Callable[[float, Any], float],
    ceil_to_step_fn: Callable[[float, Any], float],
    notional_to_qty_fn: Callable[[float, float], float],
    validate_qty_fn: Callable[[float, float], bool],
    fmt_price_fn: Callable[[Any], str],
    avg_fill_price_fn: Callable[[Dict[str, Any]], Any],
    oid_int_fn: Callable[[Any], Any],
    margin_before_entry_fn: Callable[..., Any],
    margin_after_entry_opened_fn: Callable[..., Any],
    baseline_take_snapshot_fn: Callable[..., Dict[str, Any]],
    ensure_exits_fn: Callable[..., Any],
    llm_pretrade_fn: Callable[..., Any],
) -> None:
    """Handle one fresh PEAK event and return to the caller's event loop."""
    # Safety: ignore very old PEAKs (e.g., after restarts / log replays)
    max_age = float(env.get("MAX_PEAK_AGE_SEC") or 0)
    if max_age > 0:
        dt_evt = dt_utc_fn(evt.get("ts"))
        if dt_evt is not None:
            age = now_fn() - float(dt_evt.timestamp())
            if age > max_age:
                log_event_fn("SKIP_PEAK", reason="stale_peak", age_sec=round(age, 3), evt_ts=str(evt.get("ts")))
                return
    with suppress(Exception):
        sync_from_binance_fn(st)

    if locked_fn(st):
        log_event_fn("SKIP_PEAK", reason="position_lock")
        return
    if in_cooldown_fn(st):
        log_event_fn("SKIP_PEAK", reason="cooldown")
        return
    if has_open_position_fn(st):
        log_event_fn("SKIP_PEAK", reason="position_already_open")
        return

    # Minimal live scaffold: open a LIMIT order and store as PENDING.
    # (Exit logic / SL/TP placement is added in the next step.)
    try:
        # lock immediately
        st["lock_until"] = now_fn() + float(env["LOCK_SEC"])
        save_state_fn(st)

        kind = str(evt.get("kind"))
        close_price_usdt = float(evt.get("price"))
        entry_usdt = build_entry_price_fn(kind, close_price_usdt)
        side = "BUY" if kind == "long" else "SELL"
        side_txt = "LONG" if side == "BUY" else "SHORT"                    # aggregated.csv is used ONLY here (to compute swing stop from the USDT feed)
        df_local = load_df_sorted_fn()
        if df_local.empty:
            log_event_fn("SKIP_OPEN", reason="agg_unavailable")
            return

        # locate candle index by event timestamp (in USDT feed)
        ts = evt.get("ts")
        i = len(df_local) - 1
        try:
            if ts:
                _ts = ts
                if isinstance(_ts, str) and _ts.endswith("Z"):
                    _ts = _ts[:-1] + "+00:00"
                i = locate_index_by_ts_fn(df_local, to_datetime_fn(_ts, utc=True).to_pydatetime())
        except Exception:
            i = len(df_local) - 1

        sl_usdt = swing_stop_far_fn(df_local, i, side, entry_usdt)
        tps_usdt = compute_tps_fn(entry_usdt, sl_usdt, side)
        if len(tps_usdt) < 2:
            log_event_fn("SKIP_OPEN", reason="tps_not_ready", entry_usdt=entry_usdt, sl_usdt=sl_usdt, tps=tps_usdt)
            return
        tp1_usdt, tp2_usdt = tps_usdt[0], tps_usdt[1]

        # --- USDT -> USDC conversion (k_entry fixed once per position) ---
        k_entry = get_usdt_usdc_k_fn()

        # Convert prices, then apply *directional* rounding to keep logic stable.
        tick = env["TICK_SIZE"]
        close_usdc = float(close_price_usdt) * float(k_entry)

        raw_entry = float(entry_usdt) * float(k_entry)
        raw_sl = float(sl_usdt) * float(k_entry)
        raw_tp1 = float(tp1_usdt) * float(k_entry)
        raw_tp2 = float(tp2_usdt) * float(k_entry)

        if kind == "long":
            # entry must be >= close_usdc + 1 tick
            entry = floor_to_step_fn(raw_entry, tick)
            min_entry = close_usdc + float(tick)
            if entry < min_entry:
                entry = ceil_to_step_fn(min_entry, tick)

            sl = floor_to_step_fn(raw_sl, tick)
            tp1 = floor_to_step_fn(raw_tp1, tick)
            tp2 = floor_to_step_fn(raw_tp2, tick)
        else:
            # entry must be <= close_usdc - 1 tick
            entry = ceil_to_step_fn(raw_entry, tick)
            max_entry = close_usdc - float(tick)
            if entry > max_entry:
                entry = floor_to_step_fn(max_entry, tick)

            sl = ceil_to_step_fn(raw_sl, tick)
            tp1 = ceil_to_step_fn(raw_tp1, tick)
            tp2 = ceil_to_step_fn(raw_tp2, tick)

        qty = notional_to_qty_fn(entry, env["QTY_USD"])

        if not validate_qty_fn(qty, entry):
            log_event_fn("SKIP_OPEN", reason="qty_too_small", entry=entry, qty=qty, k_entry=k_entry)
            return

        client_id = f"EX_EN_{int(time_fn())}"
        entry_mode = str(env.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper()
        if entry_mode == "MARKET_ONLY":
            with suppress(Exception):
                margin_before_entry_fn(st, env["SYMBOL"], side, float(qty), plan={
                    "trade_key": client_id,
                    "entry_price": entry,
                })
            order = binance_api.place_spot_market(env["SYMBOL"], side, qty, client_id=client_id)
            exq0 = float(order.get("executedQty") or 0.0)
            status0 = "OPEN_FILLED" if exq0 > 0.0 else "PENDING"
            avgp0 = avg_fill_price_fn(order)
            entry_actual0 = float(fmt_price_fn(avgp0)) if avgp0 else None
        else:
            with suppress(Exception):
                margin_before_entry_fn(st, env["SYMBOL"], side, float(qty), plan={
                    "trade_key": client_id,
                    "entry_price": entry,
                })
            order = binance_api.place_spot_limit(env["SYMBOL"], side, qty, entry, client_id=client_id)
            status0 = "PENDING"
            entry_actual0 = None
        st["position"] = {
            "status": status0,
            "mode": "live",
            "opened_at": iso_utc_fn(),
            "opened_s": now_fn(),
            "side": side_txt,
            "qty": qty,
            "entry": entry,
            "order_id": oid_int_fn(order.get("orderId")) or order.get("orderId"),
            "client_id": client_id,
            "trade_key": client_id,
            "entry_mode": str(env.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper(),
            "entry_actual": entry_actual0,
            "k_entry": k_entry,
            "prices": {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2},
            "src_evt": {
                "ts": evt.get("ts"),
                "kind": kind,
                "source": evt.get("source"),
                "action": evt.get("action"),
                "delta": evt.get("delta"),
                "vol": evt.get("vol"),
                "imb": evt.get("imb"),
                "price": evt.get("price"),
                "vwap": evt.get("vwap"),
                "poc": evt.get("poc"),
                "price_usdt": close_price_usdt,
                "entry_usdt": entry_usdt,
                "sl_usdt": sl_usdt,
                "tp1_usdt": tp1_usdt,
                "tp2_usdt": tp2_usdt,
            },
        }
        baseline_log = None
        baseline = st.get("baseline")
        if not isinstance(baseline, dict):
            baseline = {}
        active_snap = baseline.get("active")
        active_key = active_snap.get("trade_key") if isinstance(active_snap, dict) else None
        trade_key = st["position"].get("trade_key") or st["position"].get("client_id")
        if active_snap is None or active_key != trade_key:
            try:
                snap = baseline_take_snapshot_fn(
                    binance_api,
                    env,
                    env["SYMBOL"],
                    trade_key,
                    "pre_trade",
                )
                baseline["active"] = snap
                if baseline.get("truth") is not None and not isinstance(baseline.get("truth"), dict):
                    baseline["truth"] = None
                baseline.setdefault("truth", None)
                st["baseline"] = baseline
                baseline_log = {
                    "which": "active",
                    "trade_key": trade_key,
                    "symbol": snap.get("symbol"),
                    "trade_mode": snap.get("trade_mode"),
                }
            except Exception as e:
                log_event_fn("BASELINE_ERROR", which="active", trade_key=trade_key, error=str(e))
        if status0 == "OPEN_FILLED":
            pos0 = st.get("position") or {}
            with suppress(Exception):
                margin_after_entry_opened_fn(st, trade_key=(pos0.get("trade_key") or pos0.get("client_id") or pos0.get("order_id")))
            exits_placed_open_filled = False
            if (not pos0.get("orders")) and pos0.get("prices"):
                exits_placed_open_filled = ensure_exits_fn(st, pos0, reason="open_filled", best_effort=True, save_on_success=False)
        save_state_fn(st)
        if status0 == "OPEN_FILLED" and exits_placed_open_filled:
            with suppress(Exception):
                llm_pretrade_fn(st, st.get("position") or {}, trigger="EXITS_PLACED_V15")
        if baseline_log is not None:
            log_event_fn("BASELINE_TAKEN", **baseline_log)

        log_event_fn("OPEN", mode="live", side=st["position"]["side"], entry=entry, qty=qty, order_id=st["position"]["order_id"])
        send_webhook_fn({"event": "OPEN", "mode": "live", "symbol": env["SYMBOL"], "side": st["position"]["side"], "entry": entry, "qty": qty, "order": order})
    except Exception as e:
        log_event_fn("LIVE_OPEN_ERROR", error=str(e))
