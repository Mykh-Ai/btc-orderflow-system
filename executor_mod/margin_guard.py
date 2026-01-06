# executor_mod/margin_guard.py
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Callable

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


def on_startup(state: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    if log_event:
        note = "ok" if api_client else "no_api"
        if margin_policy is None:
            note = f"{note},no_policy"
        log_event("MARGIN_HOOK_STARTUP", note=note)


def on_before_entry(state: Dict[str, Any], symbol: str, side: str, qty: float, plan: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    # TODO: borrow logic here
    return

