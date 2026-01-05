# executor_mod/margin_guard.py
from __future__ import annotations
from typing import Any, Dict, Optional, Callable

ENV: Dict[str, Any] = {}
log_event: Optional[Callable[..., None]] = None

def configure(env: Dict[str, Any], log_event_fn: Callable[..., None]) -> None:
    global ENV, log_event
    ENV = env
    log_event = log_event_fn

def is_margin_mode() -> bool:
    return (ENV.get("TRADE_MODE") or "").lower() == "margin"

def on_startup(state: Dict[str, Any]) -> None:
    # Spot: no-op
    if not is_margin_mode():
        return
    # Margin: placeholder for future checks
    if log_event:
        log_event("MARGIN_HOOK_STARTUP", note="stub")

def on_before_entry(symbol: str, side: str, qty: float, plan: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    if log_event:
        log_event("MARGIN_HOOK_BEFORE_ENTRY", symbol=symbol, side=side, qty=qty)

def on_after_entry_opened(state: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    if log_event:
        log_event("MARGIN_HOOK_AFTER_ENTRY", note="stub")

def on_shutdown(state: Dict[str, Any]) -> None:
    if not is_margin_mode():
        return
    if log_event:
        log_event("MARGIN_HOOK_SHUTDOWN", note="stub")

def on_after_position_closed(st: dict) -> None:
    """
    Best-effort hook after the executor considers the position closed.
    Safe no-op unless TRADE_MODE=margin.
    """
    if not is_margin_mode():
        return
    # TODO(Task14): repay/cleanup policy (idempotent via trade_key)
    return

