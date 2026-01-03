#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""paper_mode.py
Paper execution logic extracted from executor.py.

Hard rule: moved functions below are verbatim copies from executor.py.
"""
import math
from typing import Dict, Any, Optional, Callable

import pandas as pd
from executor_mod.state_store import save_state
from executor_mod.notifications import log_event, send_webhook

ENV: Dict[str, Any] = {}

_now_s: Optional[Callable[[], float]] = None
build_entry_price: Optional[Callable[[str, float], float]] = None
notional_to_qty: Optional[Callable[[float, float], float]] = None
validate_qty: Optional[Callable[[float, float], bool]] = None
locate_index_by_ts: Optional[Callable[[pd.DataFrame, Any], int]] = None
swing_stop_far: Optional[Callable[[pd.DataFrame, int, str, float], float]] = None
compute_tps: Optional[Callable[[float, float, str], Any]] = None
latest_price: Optional[Callable[[pd.DataFrame], float]] = None
iso_utc: Optional[Callable[..., str]] = None
round_nearest_to_step: Optional[Callable[..., float]] = None
floor_to_step: Optional[Callable[..., float]] = None
ceil_to_step: Optional[Callable[..., float]] = None

def configure(
    env: Dict[str, Any],
    _now_s: Callable[[], float],
    build_entry_price: Callable[[str, float], float],
    notional_to_qty: Callable[[float, float], float],
    validate_qty: Callable[[float, float], bool],
    locate_index_by_ts: Callable[[pd.DataFrame, Any], int],
    swing_stop_far: Callable[[pd.DataFrame, int, str, float], float],
    compute_tps: Callable[..., Any],
    latest_price: Callable[[pd.DataFrame], float],
    iso_utc: Callable[..., str],
    round_nearest_to_step: Callable[..., float],
    floor_to_step: Callable[..., float],
    ceil_to_step: Callable[..., float],
) -> None:
    globals()["ENV"] = env
    globals()["_now_s"] = _now_s
    globals()["build_entry_price"] = build_entry_price
    globals()["notional_to_qty"] = notional_to_qty
    globals()["validate_qty"] = validate_qty
    globals()["locate_index_by_ts"] = locate_index_by_ts
    globals()["swing_stop_far"] = swing_stop_far
    globals()["compute_tps"] = compute_tps
    globals()["latest_price"] = latest_price
    globals()["iso_utc"] = iso_utc
    globals()["round_nearest_to_step"] = round_nearest_to_step
    globals()["floor_to_step"] = floor_to_step
    globals()["ceil_to_step"] = ceil_to_step

# ===================== Paper execution =====================

def open_paper_position(st: Dict[str, Any], evt: Dict[str, Any], df: pd.DataFrame) -> None:
    # Lock immediately to prevent duplicate opens in race/restart scenarios
    st["lock_until"] = _now_s() + float(ENV["LOCK_SEC"])
    save_state(st)

    kind = str(evt.get("kind"))
    close_price = float(evt.get("price"))
    entry = build_entry_price(kind, close_price)
    qty = notional_to_qty(entry, ENV["QTY_USD"])

    side = "BUY" if kind == "long" else "SELL"
    side_txt = "LONG" if side == "BUY" else "SHORT"

    if not validate_qty(qty, entry):
        log_event("SKIP_OPEN", reason="qty_too_small", entry=entry, qty=qty)
        return

    # locate candle index by event timestamp
    ts = evt.get("ts")
    i = len(df) - 1
    try:
        if ts:
            _ts = ts
            if isinstance(_ts, str) and _ts.endswith("Z"):
                _ts = _ts[:-1] + "+00:00"
            i = locate_index_by_ts(df, pd.to_datetime(_ts, utc=True).to_pydatetime())
    except Exception:
        i = len(df) - 1

    sl = swing_stop_far(df, i, side, entry)
    tps = compute_tps(entry, sl, side)

    pos = {
        "status": "OPEN",
        "mode": "paper",
        "opened_at": iso_utc(),
        "side": side_txt,
        "qty": qty,
        "entry": entry,
        "sl": sl,
        "tps": ([{"level": tps[0], "hit": False}, {"level": tps[1], "hit": False}] if len(tps) >= 2
                else [{"level": tps[0], "hit": False}] if len(tps) == 1
                else []),
        "last_price": close_price,
        "src_evt": {
            "ts": evt.get("ts"),
            "kind": kind,
            "price": close_price,
            "delta": evt.get("delta"),
            "imb": evt.get("imb"),
            "vol": evt.get("vol"),
        },
    }

    st["position"] = pos
    save_state(st)

    log_event("OPEN", mode="paper", side=side_txt, entry=entry, sl=sl, qty=qty, tps=[x["level"] for x in pos["tps"]])

    send_webhook(
        {
            "event": "OPEN",
            "mode": "paper",
            "symbol": ENV["SYMBOL"],
            "side": side_txt,
            "entry": entry,
            "sl": sl,
            "tps": [x["level"] for x in pos["tps"]],
            "qty": qty,
            "src": pos["src_evt"],
        }
    )


def monitor_paper_position(st: Dict[str, Any], df: pd.DataFrame) -> None:
    pos = st.get("position")
    if not pos or pos.get("status") != "OPEN" or pos.get("mode") != "paper":
        return

    px = latest_price(df)
    if not math.isfinite(px):
        return

    pos["last_price"] = px

    side_txt = pos.get("side")
    entry = float(pos.get("entry"))
    sl = float(pos.get("sl"))
    tps = pos.get("tps", [])

    def _close(reason: str, level: float) -> None:
        pos["status"] = "CLOSED"
        pos["closed_at"] = iso_utc()
        pos["close_reason"] = reason
        pos["close_price"] = level
        save_state(st)

        log_event("CLOSE", mode="paper", reason=reason, close_price=level, last_price=px, side=side_txt)
        send_webhook({"event": "CLOSE", "mode": "paper", "symbol": ENV["SYMBOL"], "side": side_txt, "reason": reason, "close_price": level, "entry": entry, "sl": sl})

        # persist last_closed but free slot for next trade
        st["last_closed"] = {
            "ts": iso_utc(),
            "mode": "paper",
            "reason": reason,
            "side": side_txt,
            "entry": entry,
            "sl": sl,
            "close_price": level,
            "last_price": px,
            "tps": pos.get("tps", []),
            "src_evt": pos.get("src_evt"),
        }
        st["position"] = None
        st["cooldown_until"] = _now_s() + float(ENV["COOLDOWN_SEC"])
        st["lock_until"] = 0.0
        save_state(st)

    # SL check
    if side_txt == "LONG":
        if px <= sl:
            _close("SL", sl)
            return
    else:
        if px >= sl:
            _close("SL", sl)
            return

    # TP progression
    for idx, tp in enumerate(tps):
        if tp.get("hit"):
            continue
        lvl = float(tp.get("level"))

        hit = (side_txt == "LONG" and px >= lvl) or (side_txt == "SHORT" and px <= lvl)
        if not hit:
            continue

        tp["hit"] = True
        log_event("TP_HIT", tp_index=idx + 1, level=lvl, last_price=px)
        send_webhook({"event": "TP_HIT", "mode": "paper", "symbol": ENV["SYMBOL"], "side": side_txt, "tp_index": idx + 1, "level": lvl, "last_price": px})

        # After TP1: move SL to breakeven (entry) once
        if idx == 0 and not pos.get("be_moved", False):
            be = float(pos.get("entry"))
            new_sl = round_nearest_to_step(be, ENV["TICK_SIZE"])

            if side_txt == "LONG" and new_sl > be:
                new_sl = floor_to_step(be, ENV["TICK_SIZE"])
            if side_txt == "SHORT" and new_sl < be:
                new_sl = ceil_to_step(be, ENV["TICK_SIZE"])

            pos["sl"] = new_sl
            pos["be_moved"] = True
            log_event("SL_TO_BE", new_sl=new_sl, entry=be)
            send_webhook({"event": "SL_TO_BE", "mode": "paper", "symbol": ENV["SYMBOL"], "side": side_txt, "new_sl": new_sl, "entry": be})

        save_state(st)

    # Close on final TP
    if tps and all(x.get("hit") for x in tps):
        _close("TP", float(tps[-1]["level"]))