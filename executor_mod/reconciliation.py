from __future__ import annotations

from contextlib import suppress
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


def _split_symbol_guess(symbol: str, env: Mapping[str, Any]) -> Tuple[str, str]:
    """
    Best-effort split like BTCUSDC -> (BTC, USDC).
    Uses PREFLIGHT_EXPECT_QUOTE if set, otherwise common quote suffixes.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ("", "")
    exp = (env.get("PREFLIGHT_EXPECT_QUOTE") or "").strip().upper()
    if exp and s.endswith(exp) and len(s) > len(exp):
        return (s[:-len(exp)], exp)
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "BNB", "EUR", "TRY"):
        if s.endswith(q) and len(s) > len(q):
            return (s[:-len(q)], q)
    return (s, "")


def _as_f(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        if isinstance(x, (int, float)):
            return float(x)
        xs = str(x).strip()
        if xs == "":
            return default
        return float(xs)
    except Exception:
        return default


def exchange_position_exists(symbol: str, *, env: Mapping[str, Any], binance_api: Any) -> Optional[bool]:
    """
    Return:
      True  -> exchange shows a non-zero base exposure OR margin borrowed/interest
      False -> exchange shows clearly no exposure and no debt
      None  -> cannot determine (missing API function / unexpected payload)
    """
    mode = str(env.get("TRADE_MODE", "spot")).strip().lower()
    base, _quote = _split_symbol_guess(symbol, env)
    if not base:
        return None
    eps_qty = max(float(env.get("MIN_QTY", 0.0) or 0.0), 0.0)
    eps_qty = max(eps_qty, 1e-12)
    debt_eps = float(env.get("MARGIN_DEBT_EPS") or 0.0)

    def _asset_has_exposure_margin(a: Dict[str, Any]) -> bool:
        free = _as_f(a.get("free"), 0.0)
        locked = _as_f(a.get("locked"), 0.0)
        borrowed = _as_f(a.get("borrowed"), 0.0)
        interest = _as_f(a.get("interest"), 0.0)
        net = _as_f(a.get("netAsset"), 0.0)
        if abs(net) > eps_qty:
            return True
        if (free + locked) > eps_qty:
            return True
        if (borrowed + interest) > max(debt_eps, 0.0):
            return True
        return False

    def _asset_has_exposure_spot(a: Dict[str, Any]) -> bool:
        free = _as_f(a.get("free"), 0.0)
        locked = _as_f(a.get("locked"), 0.0)
        return (free + locked) > eps_qty

    if mode == "margin":
        for fn_name in ("margin_account", "get_margin_account", "get_margin_account_info", "get_margin_account_details"):
            fn = getattr(binance_api, fn_name, None)
            if not callable(fn):
                continue
            try:
                j = fn()
                assets = None
                if isinstance(j, dict):
                    assets = j.get("userAssets") or j.get("assets") or j.get("balances")
                if not isinstance(assets, list):
                    return None
                for a in assets:
                    if not isinstance(a, dict):
                        continue
                    if str(a.get("asset", "")).upper() == base:
                        return True if _asset_has_exposure_margin(a) else False
                return None
            except Exception:
                return None
        return None

    for fn_name in ("account", "get_account", "spot_account", "get_spot_account"):
        fn = getattr(binance_api, fn_name, None)
        if not callable(fn):
            continue
        try:
            j = fn()
            bals = None
            if isinstance(j, dict):
                bals = j.get("balances") or j.get("userAssets")
            if not isinstance(bals, list):
                return None
            for a in bals:
                if not isinstance(a, dict):
                    continue
                if str(a.get("asset", "")).upper() == base:
                    return True if _asset_has_exposure_spot(a) else False
            return None
        except Exception:
            return None
    return None


def sync_from_binance(
    st: Dict[str, Any],
    *,
    env: Mapping[str, Any],
    binance_api: Any,
    save_state_fn: Callable[[Dict[str, Any]], None],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    iso_utc_fn: Callable[[], str],
    time_module: Any,
    exchange_position_exists_fn: Callable[[str], Optional[bool]],
    record_trade_execution_snapshot_fn: Callable[..., Any],
    record_outcome_fn: Callable[..., Any],
    margin_after_position_closed_fn: Callable[..., Any],
    build_sync_last_closed_fn: Callable[..., Dict[str, Any]],
) -> None:
    """Best-effort reconciliation of executor state with Binance."""
    if str(env.get("TRADE_MODE", "spot")).strip().lower() != "margin":
        return

    try:
        orders = binance_api.open_orders(env["SYMBOL"])
    except Exception as e:
        log_event_fn("SYNC_ERR_OPENORDERS", error=str(e))
        return

    tagged = [o for o in (orders or []) if str(o.get("clientOrderId", "")).startswith("EX_")]
    pos = st.get("position") or {}

    if not tagged:
        if env.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR") and pos and pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED"):
            symbol = str(env.get("SYMBOL", "") or "").strip().upper()
            if symbol:
                recon = (pos.setdefault("recon", {}) if isinstance(pos, dict) else {})
                last_emit = recon.setdefault("last_emit", {}) if isinstance(recon, dict) else {}
                throttle_sec = int(env.get("RECON_THROTTLE_SEC") or env.get("INVAR_THROTTLE_SEC", 600) or 600)
                now_s = time_module.time()

                def _should_emit(event_key: str) -> bool:
                    try:
                        last_ts = float(last_emit.get(event_key) or 0.0)
                    except Exception:
                        last_ts = 0.0
                    if now_s - last_ts < throttle_sec:
                        return False
                    last_emit[event_key] = now_s
                    return True

                try:
                    all_open = binance_api.open_orders(symbol)
                except Exception as e:
                    all_open = None
                    if _should_emit("pos_clear:open_orders_error"):
                        log_event_fn("POSITION_CLEAR_CHECK_FAILED", mode="live", symbol=symbol, error=str(e))
                if isinstance(all_open, list) and len(all_open) == 0:
                    ex_pos = exchange_position_exists_fn(symbol)
                    if ex_pos is False:
                        if _should_emit("pos_clear:confirmed"):
                            log_event_fn("POSITION_CLEARED_BY_EXCHANGE", mode="live", symbol=symbol, prev_status=pos.get("status"))
                            with suppress(Exception):
                                send_webhook_fn({"event": "POSITION_CLEARED_BY_EXCHANGE", "mode": "live", "symbol": symbol, "prev_status": pos.get("status")})
                        if str(env.get("TRADE_MODE", "")).strip().lower() == "margin":
                            margin = st.get("margin", {})
                            if (margin.get("borrowed_assets") or margin.get("borrowed_by_trade")):
                                tk = pos.get("trade_key") or margin.get("active_trade_key")
                                with suppress(Exception):
                                    margin_after_position_closed_fn(st, trade_key=tk)
                        st["last_closed"] = build_sync_last_closed_fn(
                            pos, "SYNC_EXCHANGE_CLEAR", iso_utc_fn()
                        )
                        record_trade_execution_snapshot_fn(st, "sync_exchange_clear", enrich_exchange=False)
                        st["position"] = None
                        st["lock_until"] = 0.0
                        save_state_fn(st)
                        with suppress(Exception):
                            record_outcome_fn(st, "sync_exchange_clear", env.get("SYMBOL", ""))
                        return
                    elif ex_pos is None:
                        if _should_emit("pos_clear:unknown"):
                            log_event_fn("POSITION_CLEAR_EXCHANGE_UNKNOWN", mode="live", symbol=symbol)

        if pos.get("mode") == "live" and pos.get("status") == "OPEN_FILLED":
            log_event_fn("SYNC_SKIP_CLEAR_OPEN_FILLED_NO_ORDERS", prev_status=pos.get("status"), order_id=pos.get("order_id"))
            return

        if pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN"):
            oid = int(pos.get("order_id") or 0)
            if not oid:
                log_event_fn("SYNC_KEEP_NO_TAGGED_NO_ENTRY_ID", prev_status=pos.get("status"))
                return
            od = None
            with suppress(Exception):
                od = binance_api.check_order_status(env["SYMBOL"], oid)
            st_o = str((od or {}).get("status", "")).upper()
            exq = float((od or {}).get("executedQty") or 0.0)
            if st_o not in ("CANCELED", "REJECTED", "EXPIRED") or exq > 0.0:
                log_event_fn("SYNC_KEEP_NO_TAGGED_ENTRY_NOT_CANCELED",
                             prev_status=pos.get("status"), order_id=oid,
                             status=st_o or "UNKNOWN", executedQty=exq)
                return
            st["last_closed"] = build_sync_last_closed_fn(
                pos, "SYNC_CONFIRMED_CANCELED", iso_utc_fn(), order_status=st_o
            )
            record_trade_execution_snapshot_fn(st, "sync_confirmed_canceled", enrich_exchange=False)
            _p4_tk = (
                pos.get("trade_key")
                or pos.get("client_id")
                or (st.get("margin") or {}).get("active_trade_key")
            )
            log_event_fn("SYNC_CLEAR_NO_TAGGED_CONFIRMED_CANCELED", prev_status=pos.get("status"), order_id=oid)
            st["position"] = None
            st["lock_until"] = 0.0
            save_state_fn(st)
            with suppress(Exception):
                record_outcome_fn(st, "sync_confirmed_canceled", env.get("SYMBOL", ""))
            with suppress(Exception):
                margin_after_position_closed_fn(st, trade_key=_p4_tk)
        return

    if pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED"):
        open_ids = set()
        for o in tagged:
            with suppress(Exception):
                open_ids.add(int(o.get("orderId")))
        orders = pos.get("orders") or {}
        updated = False
        recon = pos.setdefault("recon", {})
        last_emit = recon.setdefault("last_emit", {})
        throttle_sec = int(env.get("RECON_THROTTLE_SEC") or env.get("INVAR_THROTTLE_SEC", 600) or 600)
        now_s = time_module.time()

        def _should_emit(event_key: str) -> bool:
            last_ts = float(last_emit.get(event_key) or 0.0)
            if now_s - last_ts < throttle_sec:
                return False
            last_emit[event_key] = now_s
            return True

        def _emit(event: str, payload: Dict[str, Any], emit_key: str) -> None:
            nonlocal updated
            if not _should_emit(emit_key):
                return
            updated = True
            log_event_fn(event, **payload)
            with suppress(Exception):
                send_webhook_fn(payload)

        for key in ("tp1", "tp2", "sl"):
            oid = orders.get(key)
            if not oid:
                continue
            with suppress(Exception):
                oid = int(oid)
            if oid in open_ids:
                continue

            status = ""
            executed_qty = 0.0
            try:
                od = binance_api.get_order(env["SYMBOL"], oid)
                status = str((od or {}).get("status", "")).upper()
                with suppress(Exception):
                    executed_qty = float((od or {}).get("executedQty") or 0.0)
            except Exception as e:
                err = str(e)
                err_l = err.lower()

                if ("-2013" in err_l) or ("order does not exist" in err_l) or ("unknown order" in err_l):
                    orders.pop(key, None)
                    recon.setdefault(f"{key}_missing_ts", iso_utc_fn())
                    recon[f"{key}_missing_reason"] = "NOT_FOUND"
                    updated = True
                    _emit(
                        "RECON_ORDER_MISSING",
                        {
                            "event": "RECON_ORDER_MISSING",
                            "which": key,
                            "order_id": oid,
                            "status": "NOT_FOUND",
                            "error": err,
                            "symbol": env["SYMBOL"],
                        },
                        f"recon:{key}:{oid}:not_found",
                    )
                    continue

                recon.setdefault(f"{key}_unknown_ts", iso_utc_fn())
                updated = True
                _emit(
                    "RECON_ORDER_UNKNOWN",
                    {
                        "event": "RECON_ORDER_UNKNOWN",
                        "which": key,
                        "order_id": oid,
                        "error": err,
                        "symbol": env["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if status == "FILLED":
                recon.setdefault(f"{key}_filled_seen_ts", iso_utc_fn())
                updated = True
                _emit(
                    "RECON_ORDER_FILLED_SEEN",
                    {
                        "event": "RECON_ORDER_FILLED_SEEN",
                        "which": key,
                        "order_id": oid,
                        "status": "FILLED",
                        "symbol": env["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if status in ("CANCELED", "EXPIRED", "REJECTED"):
                orders.pop(key, None)
                recon.setdefault(f"{key}_missing_ts", iso_utc_fn())
                recon[f"{key}_missing_reason"] = status
                updated = True
                _emit(
                    "RECON_ORDER_MISSING",
                    {
                        "event": "RECON_ORDER_MISSING",
                        "which": key,
                        "order_id": oid,
                        "status": status,
                        "symbol": env["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if not status:
                recon.setdefault(f"{key}_unknown_ts", iso_utc_fn())
                updated = True
                _emit(
                    "RECON_ORDER_UNKNOWN",
                    {
                        "event": "RECON_ORDER_UNKNOWN",
                        "which": key,
                        "order_id": oid,
                        "error": "status_missing",
                        "symbol": env["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            recon.setdefault(f"{key}_not_in_open_active_ts", iso_utc_fn())
            recon[f"{key}_not_in_open_active_status"] = status
            updated = True
            _emit(
                "RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE",
                {
                    "event": "RECON_EXIT_NOT_IN_OPEN_BUT_ACTIVE",
                    "which": key,
                    "order_id": oid,
                    "status": status,
                    "executedQty": executed_qty,
                    "symbol": env["SYMBOL"],
                },
                f"recon:{key}:{oid}:active:{status}",
            )
            continue

        if updated:
            pos["orders"] = orders
            save_state_fn(st)
        return

    def _find(prefix: str) -> Optional[Dict[str, Any]]:
        for o in tagged:
            if str(o.get("clientOrderId", "")).startswith(prefix):
                return o
        return None

    o_en = _find("EX_EN_")
    o_tp1 = _find("EX_TP1_")
    o_tp2 = _find("EX_TP2_")
    o_sl = _find("EX_SL_") or _find("EX_SL_BE_")

    exit_side = None
    for o in (o_tp1, o_tp2, o_sl):
        if o and o.get("side") in ("SELL", "BUY"):
            exit_side = o.get("side")
            break
    side_txt = "LONG" if exit_side == "SELL" else "SHORT" if exit_side == "BUY" else "UNKNOWN"

    prices: Dict[str, float] = {}
    with suppress(Exception):
        if o_en and o_en.get("price"):
            prices["entry"] = float(o_en["price"])
    with suppress(Exception):
        if o_sl and o_sl.get("stopPrice"):
            prices["sl"] = float(o_sl["stopPrice"])
    with suppress(Exception):
        if o_tp1 and o_tp1.get("price"):
            prices["tp1"] = float(o_tp1["price"])
    with suppress(Exception):
        if o_tp2 and o_tp2.get("price"):
            prices["tp2"] = float(o_tp2["price"])

    qty = None
    with suppress(Exception):
        if o_sl and o_sl.get("origQty"):
            qty = float(o_sl["origQty"])
    if qty is None:
        with suppress(Exception):
            if o_en and o_en.get("origQty"):
                qty = float(o_en["origQty"])

    st["position"] = {
        "status": "PENDING" if o_en else "OPEN",
        "mode": "live",
        "opened_at": iso_utc_fn(),
        "side": side_txt,
        "qty": float(qty or 0.0),
        "order_id": int(o_en["orderId"]) if o_en else None,
        "prices": prices or None,
        "orders": {
            "tp1": int(o_tp1["orderId"]) if o_tp1 else None,
            "tp2": int(o_tp2["orderId"]) if o_tp2 else None,
            "sl": int(o_sl["orderId"]) if o_sl else None,
            "qty1": None,
            "qty2": None,
        },
        "synced": True,
    }
    save_state_fn(st)
    log_event_fn("SYNC_ATTACHED", side=side_txt, tagged_orders=len(tagged))
