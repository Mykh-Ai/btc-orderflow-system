#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OPEN_FILLED exit retry and failsafe lifecycle."""
from __future__ import annotations

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
) -> None:
    """Retry exits placement for a live position stuck in OPEN_FILLED without exits."""
    pos = st.get("position") or {}
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
        with suppress(Exception):
            flatten_market_fn(env["SYMBOL"], pos.get("side"), float(pos.get("qty") or 0.0), client_id=f"EX_FLAT_{int(time_fn())}")
        clear_position_slot_fn(st, "FAILSAFE_FLATTEN", tries=tries)
