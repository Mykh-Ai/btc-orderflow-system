#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exits_flow.py
Single point for "ensure exits placed" (validate_exit_plan + place_exits_v15 + state/log/webhook).

Hard rule: preserve behavior; only centralize repeated blocks from executor.py.
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Callable

ENV: Dict[str, Any] = {}
# injected dependencies from executor.py
save_state: Optional[Callable[[dict], None]] = None
log_event: Optional[Callable[..., None]] = None
send_webhook: Optional[Callable[[dict], None]] = None
validate_exit_plan: Optional[Callable[[str, str, float, Dict[str, float]], Dict[str, Any]]] = None
place_exits_v15: Optional[Callable[[str, str, float, Dict[str, float]], Dict[str, Any]]] = None


def configure(
    env: Dict[str, Any],
    *,
    save_state_fn=lambda st: save_state(st),
    log_event_fn=lambda *a, **k: log_event(*a, **k),
    send_webhook_fn=lambda payload: send_webhook(payload),
    validate_exit_plan_fn=lambda *a, **k: validate_exit_plan(*a, **k),
    place_exits_v15_fn=lambda *a, **k: place_exits_v15(*a, **k),
) -> None:
    global ENV, save_state, log_event, send_webhook, validate_exit_plan, place_exits_v15
    ENV = env
    save_state = save_state_fn
    log_event = log_event_fn
    send_webhook = send_webhook_fn
    validate_exit_plan = validate_exit_plan_fn
    place_exits_v15 = place_exits_v15_fn


def ensure_exits(
    st: dict,
    pos: dict,
    reason: str,
    best_effort: bool = True,
    attempt: Optional[int] = None,
    save_on_success: bool = True,
    save_on_fail: bool = False,
) -> bool:
    """Ensure exits are placed for a live position.

    reason is used only to preserve original logging variations.
    """
    try:
        validated = validate_exit_plan(ENV["SYMBOL"], pos["side"], float(pos["qty"]), pos["prices"])
        pos["qty"] = float(validated["qty_total_r"])
        pos["prices"] = validated["prices"]
        pos["orders"] = place_exits_v15(ENV["SYMBOL"], pos["side"], float(pos["qty"]), pos["prices"])
        pos["status"] = "OPEN"
        st["position"] = pos
        if save_on_success:
            save_state(st)
        if reason == "retry":
            log_event("EXITS_PLACED_V15", mode="live", orders=pos["orders"], attempt=attempt)
            send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": pos["orders"], "prices": pos["prices"], "attempt": attempt})
        else:
            log_event("EXITS_PLACED_V15", mode="live", orders=pos["orders"])
            send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": pos["orders"], "prices": pos["prices"]})
        return True
    except Exception as ee:
        if save_on_fail:
            st["position"] = pos
            save_state(st)
        if reason == "retry":
            log_event("EXITS_RETRY_FAIL", error=str(ee), attempt=attempt, symbol=ENV["SYMBOL"])
        elif reason == "try_now":
            log_event("EXITS_PLACE_ERROR", error=str(ee), symbol=ENV["SYMBOL"], side=pos.get("side"), qty=pos.get("qty"))
        else:
            log_event("EXITS_PLACE_ERROR", error=str(ee), symbol=ENV["SYMBOL"], side=pos.get("side"), qty=pos.get("qty"), prices=pos.get("prices"))
        return False