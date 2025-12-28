#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""executor.py

Executor — execution engine for DeltaScout PEAK signals.

Design goals
- Reads DeltaScout JSONL events from a shared log file (DELTASCOUT_LOG)
- Single-position mode: ignores new PEAK while a position is OPEN/PENDING
- DRY=1 (paper) now, DRY=0 (Binance Spot)
- Writes ONLY to its own state/log files (never appends to deltascout.log)
- Keeps executor log capped to LOG_MAX_LINES (default: 200)

Hardening (this patch)
- Strictly accepts only valid DeltaScout PEAK events
- Stable dedup key (action|ts|min|kind|rounded_price) instead of hashing raw lines
- Cooldown window after CLOSE
- Position lock right after OPEN (protects against duplicate opens on restart/race)
- Keeps last_closed in state while freeing position slot (position=None)
- Reads deltascout log by tail (TAIL_LINES) without loading full file

Paper mode behavior (DRY=1)
- On PEAK: compute entry/qty/sl/tps and open a virtual position
- Continuously monitors latest price from AGG_CSV
- Closes on SL or final TP (TP1/TP2 hits tracked)

"""

from __future__ import annotations

import os
import json
import time
import math
import hmac
import hashlib
from collections import deque
from contextlib import suppress
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import pandas as pd
import requests
from urllib.parse import urlencode


# ===================== ENV =====================

def _get_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


ENV: Dict[str, Any] = {
    # mode
    "DRY": _get_bool("DRY", True),

    # inputs
    "DELTASCOUT_LOG": os.getenv("DELTASCOUT_LOG", "/data/logs/deltascout.log"),
    "AGG_CSV": os.getenv("AGG_CSV", "/data/feed/aggregated.csv"),

    # outputs
    "STATE_FN": os.getenv("STATE_FN", "/data/state/executor_state.json"),
    "EXEC_LOG": os.getenv("EXEC_LOG", "/data/logs/executor.log"),
    "LOG_MAX_LINES": _get_int("LOG_MAX_LINES", 200),

    # safety / log reader
    "TAIL_LINES": _get_int("TAIL_LINES", 80),
    "COOLDOWN_SEC": _get_int("COOLDOWN_SEC", 180),
    "LOCK_SEC": _get_int("LOCK_SEC", 15),
    "DEDUP_PRICE_DECIMALS": _get_int("DEDUP_PRICE_DECIMALS", 1),
    "STRICT_SOURCE": _get_bool("STRICT_SOURCE", True),

    # sizing
    "SYMBOL": os.getenv("SYMBOL", "BTCUSDT"),
    "QTY_USD": _get_float("QTY_USD", 100.0),
    "QTY_STEP": Decimal(os.getenv("QTY_STEP", "0.00001")),
    "MIN_QTY": Decimal(os.getenv("MIN_QTY", "0.00001")),
    "MIN_NOTIONAL": _get_float("MIN_NOTIONAL", 5.0),

    # price formatting
    "TICK_SIZE": Decimal(os.getenv("TICK_SIZE", "0.01")),

    # entry
    "ENTRY_OFFSET_USD": _get_float("ENTRY_OFFSET_USD", 0.5),

    # risk model
    "SL_PCT": _get_float("SL_PCT", 0.002),
    "SWING_MINS": _get_int("SWING_MINS", 120),
    "TP_R_LIST": [float(x) for x in os.getenv("TP_R_LIST", "1,2").split(",") if x.strip()],

    # polling
    "POLL_SEC": _get_float("POLL_SEC", 1.0),

    # webhook (n8n)
    "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
    "N8N_BASIC_AUTH_USER": os.getenv("N8N_BASIC_AUTH_USER", ""),
    "N8N_BASIC_AUTH_PASSWORD": os.getenv("N8N_BASIC_AUTH_PASSWORD", ""),

    # Binance (used only when DRY=0)
    "BINANCE_BASE_URL": os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
    "BINANCE_API_KEY": os.getenv("BINANCE_API_KEY", ""),
    "BINANCE_API_SECRET": os.getenv("BINANCE_API_SECRET", ""),
}


# ===================== Time/IO helpers =====================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or now_utc()).isoformat()


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def append_line_with_cap(path: str, line: str, cap: int) -> None:
    """Append a line and keep only the last `cap` lines."""
    _ensure_dir(path)
    # append new line (explicit \n)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")

    # File stays small by design; safe to read/trim each time.
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > cap:
            lines = lines[-cap:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines)
    except FileNotFoundError:
        pass


def log_event(action: str, **fields: Any) -> None:
    obj = {"ts": iso_utc(), "source": "executor", "action": action}
    obj.update(fields)
    append_line_with_cap(ENV["EXEC_LOG"], json.dumps(obj, ensure_ascii=False), ENV["LOG_MAX_LINES"])


def read_tail_lines(path: str, n: int) -> List[str]:
    """Read only last N lines without loading whole file."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return list(deque(f, maxlen=n))
    except FileNotFoundError:
        return []


def _now_s() -> float:
    return time.time()


# ===================== DeltaScout event normalization / dedup =====================

def _ts_norm(ts: Any) -> Optional[str]:
    """Normalize timestamp for stable dedup keys."""
    if ts is None:
        return None
    if isinstance(ts, str):
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        with suppress(Exception):
            return pd.to_datetime(s, utc=True).isoformat()
        return s
    with suppress(Exception):
        return pd.to_datetime(ts, utc=True).isoformat()
    return None


def stable_event_key(evt: Dict[str, Any]) -> Optional[str]:
    """Stable key based on action+ts+kind+price (rounded)."""
    if not isinstance(evt, dict):
        return None

    if evt.get("action") != "PEAK":
        return None

    if ENV["STRICT_SOURCE"] and evt.get("source") != "DeltaScout":
        return None

    kind = str(evt.get("kind") or "").strip().lower()
    if kind not in ("long", "short"):
        return None

    ts = _ts_norm(evt.get("ts"))
    if not ts:
        return None

    with suppress(Exception):
        price = float(evt.get("price"))
    if not isinstance(price, float) or not math.isfinite(price):
        return None

    price_r = round(price, int(ENV["DEDUP_PRICE_DECIMALS"]))
    return f"PEAK|{ts}|{kind}|{price_r}"


# ===================== Webhook =====================

def send_webhook(payload: Dict[str, Any]) -> None:
    url = ENV["N8N_WEBHOOK_URL"]
    if not url:
        return
    payload = dict(payload)
    payload.setdefault("source", "executor")
    try:
        auth = None
        if ENV["N8N_BASIC_AUTH_USER"] and ENV["N8N_BASIC_AUTH_PASSWORD"]:
            auth = (ENV["N8N_BASIC_AUTH_USER"], ENV["N8N_BASIC_AUTH_PASSWORD"])
        requests.post(url, json=payload, timeout=5, auth=auth)
    except Exception as e:
        log_event("WEBHOOK_ERROR", error=str(e), payload=payload)


# ===================== Rounding / sizing =====================

def floor_to_step(x: float, step: Decimal) -> float:
    step = Decimal(step)
    d = (Decimal(str(x)) / step).quantize(Decimal("1"), rounding=ROUND_FLOOR) * step
    return float(d)


def ceil_to_step(x: float, step: Decimal) -> float:
    step = Decimal(step)
    d = (Decimal(str(x)) / step).quantize(Decimal("1"), rounding=ROUND_CEILING) * step
    return float(d)


def round_nearest_to_step(x: float, step: Decimal) -> float:
    step = Decimal(step)
    d = (Decimal(str(x)) / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
    return float(d)


# Backward-compatible name (kept for any leftover uses)
def round_to_step(x: float, step: Decimal) -> float:
    return round_nearest_to_step(x, step)


def build_entry_price(kind: str, close_price: float) -> float:
    raw = close_price + ENV["ENTRY_OFFSET_USD"] if kind == "long" else close_price - ENV["ENTRY_OFFSET_USD"]
    return floor_to_step(raw, ENV["TICK_SIZE"])


def notional_to_qty(entry: float, usd: float) -> float:
    if entry <= 0:
        return 0.0
    qty = usd / entry
    qty = floor_to_step(qty, ENV["QTY_STEP"])
    return qty


def validate_qty(qty: float, entry: float) -> bool:
    if qty <= 0:
        return False
    if Decimal(str(qty)) < ENV["MIN_QTY"]:
        return False
    if qty * entry < ENV["MIN_NOTIONAL"]:
        return False
    return True


# ===================== Market context =====================

def load_df_sorted() -> pd.DataFrame:
    # Robust loader: returns empty DF on schema issues.
    if not os.path.exists(ENV["AGG_CSV"]):
        return pd.DataFrame()

    df = pd.read_csv(ENV["AGG_CSV"])
    df.columns = [c.strip() for c in df.columns]

    if "Timestamp" not in df.columns:
        return pd.DataFrame()

    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce").dt.floor("min")

    # price
    if "ClosePrice" in df.columns:
        price = df["ClosePrice"]
    elif "AvgPrice" in df.columns:
        price = df["AvgPrice"]
    else:
        return pd.DataFrame()

    df["price"] = pd.to_numeric(price, errors="coerce").ffill()

    buy = pd.to_numeric(df.get("BuyQty", 0.0), errors="coerce").fillna(0.0)
    sell = pd.to_numeric(df.get("SellQty", 0.0), errors="coerce").fillna(0.0)
    df["buy"] = buy
    df["sell"] = sell

    df["vol1m"] = df["buy"] + df["sell"]
    df["delta"] = df["buy"] - df["sell"]

    df = df.dropna(subset=["Timestamp", "price"])

    return df.reset_index(drop=True)


def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    # normalize to minute resolution; be tolerant to tz formats
    try:
        target = pd.to_datetime(ts, utc=True).tz_convert(None).floor("min")
    except Exception:
        return len(df) - 1

    try:
        series = pd.to_datetime(df["Timestamp"], utc=True).tz_convert(None).dt.floor("min")
        m = df.index[series == target]
        return int(m[0]) if len(m) else len(df) - 1
    except Exception:
        return len(df) - 1


def latest_price(df: pd.DataFrame) -> float:
    if len(df) == 0:
        return float("nan")
    return float(df.iloc[-1]["price"])


# ===================== Stop / TP ("far" stop logic) =====================

def swing_stop_far(df: pd.DataFrame, i: int, side: str, entry: float) -> float:
    """Return a stop that is FARTHER from entry (vs near).

    side: BUY for long, SELL for short

    - BUY: choose min(pct_sl, swing_low)
    - SELL: choose max(pct_sl, swing_high)
    """
    pct_sl = entry * (1 - ENV["SL_PCT"]) if side == "BUY" else entry * (1 + ENV["SL_PCT"])

    if i < 0 or i >= len(df):
        sl = pct_sl
    else:
        lookback = df.iloc[max(0, i - ENV["SWING_MINS"]): i + 1]
        if side == "BUY":
            swing = float(lookback["price"].min())
            sl = min(pct_sl, swing)
        else:
            swing = float(lookback["price"].max())
            sl = max(pct_sl, swing)

    # Safety: enforce correct side and rounding
    if side == "BUY":
        sl = min(sl, entry - float(ENV["TICK_SIZE"]))
    else:
        sl = max(sl, entry + float(ENV["TICK_SIZE"]))

    return floor_to_step(sl, ENV["TICK_SIZE"])


def compute_tps(entry: float, sl: float, side: str) -> List[float]:
    # True R-multiples based on the REAL risk (entry -> SL)
    risk = abs(entry - sl)
    if risk <= 0:
        return []

    tps: List[float] = []
    for rmult in ENV["TP_R_LIST"]:
        if side == "BUY":
            tp = entry + rmult * risk
        else:
            tp = entry - rmult * risk
        tps.append(floor_to_step(tp, ENV["TICK_SIZE"]))
    return tps


# ===================== Binance adapter (used only when DRY=0) =====================

def _binance_signed_request(method: str, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    api_key = ENV["BINANCE_API_KEY"]
    api_secret = ENV["BINANCE_API_SECRET"]
    base_url = ENV["BINANCE_BASE_URL"]
    if not api_key or not api_secret:
        raise RuntimeError("Binance API key/secret missing")

    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)

    # Deterministic query string for signature
    params_str = {k: str(v) for k, v in sorted(params.items(), key=lambda kv: kv[0])}
    query = urlencode(params_str)
    signature = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {"X-MBX-APIKEY": api_key}
    url = base_url + endpoint

    req_params = dict(params_str)
    req_params["signature"] = signature

    if method == "POST":
        r = requests.post(url, headers=headers, params=req_params, timeout=5)
    elif method == "GET":
        r = requests.get(url, headers=headers, params=req_params, timeout=5)
    elif method == "DELETE":
        r = requests.delete(url, headers=headers, params=req_params, timeout=5)
    else:
        raise ValueError(f"Unsupported method: {method}")

    if r.status_code != 200:
        raise RuntimeError(f"Binance API error: {r.status_code} {r.text}")
    return r.json()


def place_spot_limit(symbol: str, side: str, qty: float, price: float) -> Dict[str, Any]:
    return _binance_signed_request(
        "POST",
        "/api/v3/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty,
            "price": f"{price:.2f}",
        },
    )


def check_order_status(symbol: str, order_id: int) -> Dict[str, Any]:
    return _binance_signed_request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    return _binance_signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})


# ===================== State =====================

def load_state() -> Dict[str, Any]:
    fn = ENV["STATE_FN"]
    try:
        with open(fn, "r", encoding="utf-8") as f:
            st = json.load(f)
    except FileNotFoundError:
        st = {}
    except Exception:
        st = {}

    st.setdefault("meta", {})
    st["meta"].setdefault("seen_keys", [])
    st.setdefault("position", None)
    st.setdefault("last_closed", None)
    st.setdefault("cooldown_until", 0.0)
    st.setdefault("lock_until", 0.0)
    return st


def save_state(st: Dict[str, Any]) -> None:
    fn = ENV["STATE_FN"]
    _ensure_dir(fn)
    tmp = fn + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, fn)


def has_open_position(st: Dict[str, Any]) -> bool:
    pos = st.get("position")
    if not pos:
        return False
    return pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED")


def in_cooldown(st: Dict[str, Any]) -> bool:
    with suppress(Exception):
        return _now_s() < float(st.get("cooldown_until") or 0.0)
    return False


def locked(st: Dict[str, Any]) -> bool:
    with suppress(Exception):
        return _now_s() < float(st.get("lock_until") or 0.0)
    return False


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


# ===================== Main loop =====================

def main() -> None:
    st = load_state()

    # Seed dedup keys with tail so we don't replay old PEAKs after fresh install
    if not st["meta"].get("seen_keys"):
        seeded: List[str] = []
        for ln in read_tail_lines(ENV["DELTASCOUT_LOG"], n=min(ENV["TAIL_LINES"], 120)):
            with suppress(Exception):
                evt = json.loads(ln)
                k = stable_event_key(evt)
                if k:
                    seeded.append(k)
        st["meta"]["seen_keys"] = seeded[-500:]
        save_state(st)

    log_event("BOOT", dry=ENV["DRY"], symbol=ENV["SYMBOL"])

    while True:
        time.sleep(ENV["POLL_SEC"])

        # 1) Always ingest new DeltaScout lines (so seen_keys advances even if AGG_CSV is temporarily broken)
        tail = read_tail_lines(ENV["DELTASCOUT_LOG"], n=ENV["TAIL_LINES"])

        new_events: List[Tuple[str, Dict[str, Any]]] = []
        seen_keys = st["meta"].get("seen_keys", [])

        for ln in tail:
            ln = ln.strip()
            if not ln:
                continue
            with suppress(Exception):
                evt = json.loads(ln)
            if not isinstance(evt, dict):
                continue
            k = stable_event_key(evt)
            if not k:
                continue
            if k in seen_keys:
                continue
            new_events.append((k, evt))
            seen_keys.append(k)

        if new_events:
            st["meta"]["seen_keys"] = seen_keys[-500:]
            save_state(st)

        # 2) Load market data (may be empty) and monitor open paper position when possible
        df = load_df_sorted()
        if not df.empty:
            monitor_paper_position(st, df)
        else:
            log_event("AGG_READ_ERROR", error="empty_or_invalid_agg_csv")

        if not new_events:
            continue

        # 3) Process new PEAK events
        for _, evt in new_events:
            if locked(st):
                log_event("SKIP_PEAK", reason="position_lock")
                continue
            if in_cooldown(st):
                log_event("SKIP_PEAK", reason="cooldown")
                continue
            if has_open_position(st):
                log_event("SKIP_PEAK", reason="position_already_open")
                continue

            # Paper for now (DRY=1). When DRY=0 we will switch to Binance entry.
            if ENV["DRY"]:
                open_paper_position(st, evt, df)
            else:
                # Minimal live scaffold: open a LIMIT order and store as PENDING.
                # (Exit logic / SL/TP placement is added in the next step.)
                try:
                    # lock immediately
                    st["lock_until"] = _now_s() + float(ENV["LOCK_SEC"])
                    save_state(st)

                    kind = str(evt.get("kind"))
                    close_price = float(evt.get("price"))
                    entry = build_entry_price(kind, close_price)
                    qty = notional_to_qty(entry, ENV["QTY_USD"])
                    side = "BUY" if kind == "long" else "SELL"

                    if not validate_qty(qty, entry):
                        log_event("SKIP_OPEN", reason="qty_too_small", entry=entry, qty=qty)
                        continue

                    order = place_spot_limit(ENV["SYMBOL"], side, qty, entry)
                    st["position"] = {
                        "status": "PENDING",
                        "mode": "live",
                        "opened_at": iso_utc(),
                        "side": "LONG" if side == "BUY" else "SHORT",
                        "qty": qty,
                        "entry": entry,
                        "order_id": order.get("orderId"),
                        "src_evt": {"ts": evt.get("ts"), "kind": kind, "price": close_price},
                    }
                    save_state(st)

                    log_event("OPEN", mode="live", side=st["position"]["side"], entry=entry, qty=qty, order_id=st["position"]["order_id"])
                    send_webhook({"event": "OPEN", "mode": "live", "symbol": ENV["SYMBOL"], "side": st["position"]["side"], "entry": entry, "qty": qty, "order": order})
                except Exception as e:
                    log_event("LIVE_OPEN_ERROR", error=str(e))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_event("STOP")
        raise
