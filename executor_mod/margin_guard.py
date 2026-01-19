# executor_mod/margin_guard.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Callable

from executor_mod import price_snapshot

ENV: Dict[str, Any] = {}
log_event: Optional[Callable[..., None]] = None
api_client: Optional[Any] = None

# Optional dependency: якщо margin_policy ще не готовий/нема — модуль не впаде.
try:
    from executor_mod import margin_policy  # type: ignore
except Exception:
    margin_policy = None  # type: ignore


def configure(env: Dict[str, Any], log_event_fn: Callable[..., None], api: Optional[Any] = None, **_kwargs) -> None:
    global ENV, log_event, api_client
    ENV = env
    log_event = log_event_fn
    api_client = api


def is_margin_mode() -> bool:
    return (ENV.get("TRADE_MODE") or "").lower() == "margin"

def _borrow_mode() -> str:
    # Explicit mutual exclusion to avoid double borrow/repay.
    return str(ENV.get("MARGIN_BORROW_MODE") or "manual").strip().lower()


def _rt(state: Dict[str, Any]) -> Dict[str, Any]:
    return state.setdefault("mg_runtime", {})


def _map(rt: Dict[str, Any], key: str) -> Dict[str, float]:
    m = rt.get(key)
    if not isinstance(m, dict):
        m = {}
        rt[key] = m
    return m  # type: ignore[return-value]


def _extract_trade_key(state: Optional[Dict[str, Any]], plan: Optional[Dict[str, Any]]) -> str:
    if isinstance(plan, dict):
        for k in ("trade_key", "trade_id", "key", "client_id", "clientOrderId", "order_id", "orderId"):
            v = plan.get(k)
            if v:
                return str(v)

    if isinstance(state, dict):
        pos = state.get("position") or {}
        if isinstance(pos, dict):
            for k in ("trade_key", "client_id", "order_id"):
                v = pos.get(k)
                if v:
                    return str(v)

    return ""


def _split_symbol(symbol: str) -> tuple[str, str]:
    s = (symbol or "").strip().upper()
    if s.endswith("USDT"):
        return s[:-4], "USDT"
    if s.endswith("USDC"):
        return s[:-4], "USDC"
    if s.endswith("BUSD"):
        return s[:-4], "BUSD"
    if s.endswith("USD"):
        return s[:-3], "USD"
    if s.endswith("BTC"):
        return s[:-3], "BTC"
    if len(s) >= 6:
        return s[:3], s[3:]
    return s, ""


def _is_long_side(side: str) -> bool:
    return str(side or "").strip().upper() in ("BUY", "LONG")


def _prepare_plan_for_borrow(
    state: Dict[str, Any], symbol: str, side: str, qty: float, plan: Dict[str, Any]
) -> tuple[str, Dict[str, Any]]:
    trade_key = _extract_trade_key(state, plan) or "trade-unknown"
    state.setdefault("margin", {})["active_trade_key"] = trade_key
    plan_use = dict(plan)
    plan_use["trade_key"] = trade_key
    plan_use.setdefault("is_isolated", ENV.get("MARGIN_ISOLATED", False))

    borrow_asset = plan_use.get("borrow_asset")
    borrow_amount = plan_use.get("borrow_amount")
    if borrow_asset is None or borrow_amount is None:
        base_asset, quote_asset = _split_symbol(symbol)
        if _is_long_side(side):
            borrow_asset = borrow_asset or quote_asset
            est_price = plan_use.get("entry", plan_use.get("price"))
            try:
                est_price_f = float(est_price or 0.0)
                qty_f = float(qty or 0.0)
                borrow_amount = float(borrow_amount or 0.0)
                if borrow_amount <= 0.0 and est_price_f > 0.0:
                    borrow_amount = qty_f * est_price_f
            except Exception:
                borrow_amount = 0.0
            if borrow_amount <= 0.0:
                try:
                    # Use price snapshot (throttled) to reduce API calls
                    min_interval = float(ENV.get("PRICE_SNAPSHOT_MIN_SEC") or 2.0)
                    if api_client and hasattr(api_client, "get_mid_price"):
                        snapshot = price_snapshot.get_price_snapshot()
                        price_snapshot.refresh_price_snapshot(symbol, "margin_borrow", api_client.get_mid_price, min_interval)
                        if snapshot.ok:
                            mid_price = float(snapshot.price_mid)
                            borrow_amount = float(qty or 0.0) * float(mid_price)
                except Exception:
                    borrow_amount = 0.0
        else:
            borrow_asset = borrow_asset or base_asset
            try:
                borrow_amount = float(borrow_amount or 0.0)
                if borrow_amount <= 0.0:
                    borrow_amount = float(qty or 0.0)
            except Exception:
                borrow_amount = 0.0

    plan_use["borrow_asset"] = borrow_asset
    plan_use["borrow_amount"] = borrow_amount or 0.0
    return trade_key, plan_use


def on_startup(state: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    mode = _borrow_mode()
    if mode == "auto":
        if log_event:
            log_event("MARGIN_HOOK_NOOP", note="auto_mode_noop", hook="startup")
        return
    if mode == "manual" and str(ENV.get("MARGIN_SIDE_EFFECT") or "").upper() != "NO_SIDE_EFFECT":
        if log_event:
            log_event(
                "MARGIN_CONFIG_WARN",
                note="manual_mode_requires_no_side_effect",
                mode=mode,
                side_effect=ENV.get("MARGIN_SIDE_EFFECT"),
            )
    if log_event:
        note = "ok" if api_client else "no_api"
        if margin_policy is None:
            note = f"{note},no_policy"
        log_event("MARGIN_HOOK_STARTUP", note=note, mode=mode)


def on_before_entry(state: Dict[str, Any], symbol: str, side: str, qty: float, plan: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    mode = _borrow_mode()
    if mode == "auto":
        if log_event:
            log_event("MARGIN_HOOK_NOOP", note="auto_mode_noop", hook="before_entry")
        return
    if not api_client:
        if log_event:
            log_event("MARGIN_HOOK_BEFORE_ENTRY", note="no_api")
        return
    if margin_policy is None:
        if log_event:
            log_event("MARGIN_HOOK_BEFORE_ENTRY", note="no_policy")
        return
    trade_key, plan_use = _prepare_plan_for_borrow(state, symbol, side, qty, plan)
    rt = _rt(state)
    started = _map(rt, "borrow_started")
    done = _map(rt, "borrow_done")
    after_open_done = _map(rt, "after_open_done")
    if trade_key:
        started = started if isinstance(started, dict) else {}
        done = done if isinstance(done, dict) else {}
        after_open_done = after_open_done if isinstance(after_open_done, dict) else {}
        started = {trade_key: started[trade_key]} if trade_key in started else {}
        done = {trade_key: done[trade_key]} if trade_key in done else {}
        after_open_done = {trade_key: after_open_done[trade_key]} if trade_key in after_open_done else {}
        rt["borrow_started"] = started
        rt["borrow_done"] = done
        rt["after_open_done"] = after_open_done
    if trade_key in done or trade_key in started:
        if log_event:
            log_event("MARGIN_HOOK_BEFORE_ENTRY", trade_key=trade_key, dedup=True)
        return
    started[trade_key] = time.time()
    try:
        margin_policy.ensure_borrow_if_needed(state, api_client, symbol, side, qty, plan_use)  # type: ignore[attr-defined]
        done[trade_key] = time.time()
        if log_event:
            log_event("MARGIN_HOOK_BEFORE_ENTRY", trade_key=trade_key, borrowed=True)
    except Exception as exc:
        if log_event:
            log_event("MARGIN_HOOK_BEFORE_ENTRY_ERROR", trade_key=trade_key, error=str(exc))
    return


def on_after_entry_opened(state: Dict[str, Any], trade_key: Optional[str] = None) -> None:
    if not is_margin_mode():
        return
    mode = _borrow_mode()
    if mode == "auto":
        if log_event:
            log_event("MARGIN_HOOK_NOOP", note="auto_mode_noop", hook="after_entry_opened")
        return
    rt = _rt(state)
    after_open_done = _map(rt, "after_open_done")
    tk = (
        trade_key
        or _extract_trade_key(state, state.get("position") or state.get("last_closed") or {})
        or state.get("margin", {}).get("active_trade_key")
    )
    if not tk:
        if log_event:
            log_event("MARGIN_HOOK_AFTER_ENTRY", note="no_trade_key")
        return
    if tk in after_open_done:
        return
    after_open_done[tk] = time.time()
    if log_event:
        log_event("MARGIN_HOOK_AFTER_ENTRY", trade_key=tk)
    return


def on_after_position_closed(state: Dict[str, Any], trade_key: Optional[str] = None) -> None:
    if not is_margin_mode():
        return
    mode = _borrow_mode()
    if mode == "auto":
        if log_event:
            log_event("MARGIN_HOOK_NOOP", note="auto_mode_noop", hook="after_position_closed")
        return
    if not api_client or margin_policy is None:
        if log_event:
            log_event("MARGIN_HOOK_AFTER_CLOSE", note="no_api_or_policy")
        return
    tk = (
        trade_key
        or _extract_trade_key(state, state.get("position") or state.get("last_closed") or {})
        or state.get("margin", {}).get("active_trade_key")
    )
    if not tk:
        if log_event:
            log_event("MARGIN_HOOK_AFTER_CLOSE", note="no_trade_key")
        return
    rt = _rt(state)
    repay_started = _map(rt, "repay_started")
    repay_done = _map(rt, "repay_done")
    if tk in repay_done or tk in repay_started:
        if log_event:
            log_event("MARGIN_HOOK_AFTER_CLOSE", trade_key=tk, dedup=True)
        return
    repay_started[tk] = time.time()
    try:
        margin_policy.repay_if_any(state, api_client, ENV.get("SYMBOL", ""))  # type: ignore[attr-defined]
        repay_done[tk] = time.time()
        if log_event:
            log_event("MARGIN_HOOK_AFTER_CLOSE", trade_key=tk, repaid=True)
    except Exception as exc:
        if log_event:
            log_event("MARGIN_HOOK_AFTER_CLOSE_ERROR", trade_key=tk, error=str(exc))
    rt["borrow_started"] = {}
    rt["borrow_done"] = {}
    rt["after_open_done"] = {}
    margin = state.get("margin")
    if isinstance(margin, dict):
        margin["active_trade_key"] = None
        state["margin"] = margin
    return


def on_shutdown(state: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    mode = _borrow_mode()
    if mode == "auto":
        if log_event:
            log_event("MARGIN_HOOK_NOOP", note="auto_mode_noop", hook="shutdown")
        return
    try:
        on_after_position_closed(state, trade_key=None)
        if log_event:
            log_event("MARGIN_HOOK_SHUTDOWN", note="ok")
    except Exception as exc:
        if log_event:
            log_event("MARGIN_HOOK_SHUTDOWN_ERROR", error=str(exc))
    return
