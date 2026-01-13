#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Buyer — position calculator + notifier for DeltaScout PEAK signals.

✓ Tails DeltaScout JSONL log and processes only NEW lines (sha1 dedup)
✓ Computes entry / stop / take-profit levels from an already-confirmed PEAK
✓ Sends a formatted notification via webhook (n8n/Telegram pipeline)

This module does NOT make trading decisions (no tier/trigger logic).
It also does NOT place real exchange orders in the public repository version.

DeltaScout writes JSON events, therefore legacy text/CSV parsing is removed.
"""
from __future__ import annotations
import os, sys, json, time, hashlib
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

import pandas as pd
import requests

# NOTE:
# The original internal version may contain execution (Binance REST) and stop-limit nuances.
# Those parts are intentionally excluded from the public repo version to avoid strategy leakage.

# Strict 10-col schema for aggregated.csv
EXPECTED_HEADER = ["Timestamp","Trades","TotalQty","AvgSize","BuyQty","SellQty","AvgPrice","ClosePrice","HiPrice","LowPrice"]

# Default feed dir (compatible with docker volume layout); AGG_CSV can still override.
FEED_DIR = os.getenv("FEED_DIR", "/data/feed")

# ===================== ENV =====================
def require_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v
ENV = {
    # files
    "DELTASCOUT_LOG": os.getenv("DELTASCOUT_LOG", "/root/volume-alert/data/logs/deltascout.log"),
    "AGG_CSV":        os.getenv("AGG_CSV") or os.path.join(FEED_DIR, "aggregated.csv"),
    "STATE_FN":       os.getenv("STATE_FN",       "/root/volume-alert/buyer_state.json"),

    # base parameters
    "SYMBOL": os.getenv("SYMBOL", "BTCUSDC"),
    "TICK_SIZE": Decimal(os.getenv("TICK_SIZE", "0.01")),
    "QTY_STEP":  Decimal(os.getenv("QTY_STEP",  "0.0001")),
    # Money/risk parameters are intentionally required (no defaults) for repo-safety.
    "QTY_USD":   float(require_env("QTY_USD")),
    "ENTRY_OFFSET_USD": float(require_env("ENTRY_OFFSET_USD")),
    "TTL_MIN": int(os.getenv("TTL_MIN", "30")),

    # cooldown
    "COOLDOWN_MIN": int(os.getenv("COOLDOWN_MIN", "5")),
    "COOLDOWN_DURING_ARM": int(os.getenv("COOLDOWN_DURING_ARM", "1")),

    # notifications
    "N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
    "N8N_BASIC_AUTH_USER": os.getenv("N8N_BASIC_AUTH_USER", ""),
    "N8N_BASIC_AUTH_PASSWORD": os.getenv("N8N_BASIC_AUTH_PASSWORD", ""),

    # mode
    "DRY_RUN": bool(int(os.getenv("DRY_RUN", "1"))),

    # рrisk management
    "SL_PCT": float(require_env("SL_PCT")),
    "TP_SPLIT": [float(x) for x in require_env("TP_SPLIT").split(",") if x],
    # These are kept only for calculating context metrics (not execution).
    "TRAIL_SIGMA": float(os.getenv("TRAIL_SIGMA", "0.7")),
    "TRAIL_WIN": int(os.getenv("TRAIL_WIN", "60")),
}

# Fixed execution-first risk settings (match executor semantics)
SWING_LOOKBACK = 240
TP_R_MULTIPLES = (1.0, 2.0)

# ===================== Utils =====================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def round_to_step(x: float, step: Decimal) -> float:
    d = (Decimal(str(x)) / step).quantize(0, ROUND_HALF_UP) * step
    return float(d)

def line_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()

def read_last_lines(path: str, n: int = 20) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()[-n:]
    except FileNotFoundError:
        return []

def send_webhook(payload: Dict[str, Any]):
    if not ENV["N8N_WEBHOOK_URL"]:
        print(f"[WEBHOOK SKIP] {payload}", flush=True)
        return
    payload = dict(payload)
    payload.setdefault("source", "buyer")
    try:
        auth = None
        if ENV["N8N_BASIC_AUTH_USER"] and ENV["N8N_BASIC_AUTH_PASSWORD"]:
            auth = (ENV["N8N_BASIC_AUTH_USER"], ENV["N8N_BASIC_AUTH_PASSWORD"])
        requests.post(ENV["N8N_WEBHOOK_URL"], json=payload, timeout=5, auth=auth)
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e} | {payload}", flush=True)

def build_message(entry: float, sl: float, tp1: float, tp2: float, side: str) -> str:
    """
    Build a human-readable START message for notifications.
    """
    ts_str = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"🚀 START {side}",
        f"🕒 Time: {ts_str}",
        f"📍 Entry: {entry:.0f}",
        f"⛔ SL: {sl:.0f}",
        f"🎯 TP1: {tp1:.0f}",
        f"🎯 TP2: {tp2:.0f}",
    ]
    return "\n".join(lines)


# -------------------- Order sizing helpers --------------------
def build_entry_price(kind: str, close_price: float) -> float:
    raw = close_price + ENV["ENTRY_OFFSET_USD"] if kind == "long" else close_price - ENV["ENTRY_OFFSET_USD"]
    return round_to_step(raw, ENV["TICK_SIZE"])

def notional_to_qty(entry: float, usd: float) -> float:
    if entry <= 0:
        return 0.0
    qty = usd / entry
    return round_to_step(qty, ENV["QTY_STEP"])

# ===================== Market context =====================
def load_df_sorted() -> pd.DataFrame:
    df = pd.read_csv(ENV["AGG_CSV"], encoding="utf-8-sig")
    # Normalize header: strip UTF-8 BOM and whitespace
    df.columns = [str(c).lstrip("\ufeff").strip() for c in df.columns]

    # Enforce strict schema (ordered, 10 columns)
    got = list(df.columns)
    if got != EXPECTED_HEADER:
        print(
            "CSV schema mismatch for aggregated.csv.\n"
            f"Expected: {EXPECTED_HEADER}\n"
            f"Got:      {got}\n"
            f"Path:     {ENV['AGG_CSV']}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(2)
    missing_cols = {"HiPrice", "LowPrice"} - set(df.columns)
    if missing_cols:
        raise RuntimeError(f"aggregated.csv missing required columns: {sorted(missing_cols)}")
    df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.floor("min")
    price = df["ClosePrice"] if "ClosePrice" in df.columns else df.get("AvgPrice")
    df["price"] = pd.to_numeric(price, errors="coerce").ffill()
    df["hi"] = pd.to_numeric(df["HiPrice"], errors="coerce")
    df["low"] = pd.to_numeric(df["LowPrice"], errors="coerce")
    df["buy"]   = pd.to_numeric(df.get("BuyQty", 0.0), errors="coerce").fillna(0.0)
    df["sell"]  = pd.to_numeric(df.get("SellQty", 0.0), errors="coerce").fillna(0.0)

    df["vol1m"] = df["buy"] + df["sell"]
    df["delta"] = df["buy"] - df["sell"]
    df["ema50"] = df["price"].ewm(span=50, adjust=False).mean()
    df["sigma60"] = df["price"].rolling(ENV["TRAIL_WIN"], min_periods=2).std(ddof=0)
    w = ENV["TRAIL_WIN"]
    df["vwap_w"] = df["price"].rolling(w, min_periods=1).mean()
    return df.reset_index(drop=True)

def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    m = df.index[df["Timestamp"] == ts]
    if len(m) == 0:
        m = df.index[df["Timestamp"].dt.floor("T") == ts]
    return int(m[0]) if len(m) else len(df)-1

# -------------------- Stop Loss helpers --------------------
def _swing_stop(df: pd.DataFrame, i: int, side: str, entry: float) -> float:
    pct_sl = entry * (1 - ENV["SL_PCT"]) if side == "BUY" else entry * (1 + ENV["SL_PCT"])
    if i < 0 or i >= len(df):
        sl = pct_sl
    else:
        lookback = df.iloc[max(0, i - (SWING_LOOKBACK - 1)):i + 1]
        if lookback.empty:
            sl = pct_sl
        elif side == "BUY":
            swing = float(lookback["low"].min())
            sl = min(pct_sl, swing)
        else:
            swing = float(lookback["hi"].max())
            sl = max(pct_sl, swing)
    return round_to_step(sl, ENV["TICK_SIZE"])
def _compute_tps(entry: float, sl: float, side: str) -> List[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return []
    tps: List[float] = []
    for r in TP_R_MULTIPLES:
        if side == "BUY":
            tp_raw = entry + r * risk
        else:
            tp_raw = entry - r * risk
        tps.append(round_to_step(tp_raw, ENV["TICK_SIZE"]))
    return tps

# ===================== State =====================
STATE_FN = ENV["STATE_FN"]

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FN):
        try:
            st = json.load(open(STATE_FN, "r"))
        except Exception:
            st = {}
    else:
        st = {}
    st.setdefault("meta", {"seen_hashes": [], "last_any": None})
    st.setdefault("arms", {})
    st.setdefault("cooldown_until", 0)
    st.setdefault("position", None)
    return st

def save_state(st: Dict[str, Any]):
    tmp = STATE_FN + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, separators=(",", ":"), default=str)
    os.replace(tmp, STATE_FN)

# -------------------- Cooldown helpers --------------------
def _epoch_from_iso(s: str) -> float:
    if not s:
        return 0.0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()

def _arm_is_active(arm: dict, now: float, ttl_min: int) -> bool:
    t0_iso = arm.get("armed_at") or arm.get("ts") or ""
    t0 = _epoch_from_iso(t0_iso) or time.time()
    return arm.get("status") == "ARMED" and now < (t0 + ttl_min * 60)

# ===================== Main =====================
def main():
    st = load_state()
    if "arms" in st and isinstance(st["arms"], dict):
        st["arms"] = {oid: a for oid, a in st["arms"].items() if a.get("status") == "ARMED"}
        save_state(st)
    if not st["meta"].get("seen_hashes"):
        tail = read_last_lines(ENV["DELTASCOUT_LOG"], n=10)
        for ln in tail:
            if ln.strip():
                st["meta"]["seen_hashes"].append(line_hash(ln))
        st["meta"]["seen_hashes"] = st["meta"]["seen_hashes"][-100:]
        save_state(st)

    print(f"buyer: started (dry_run={ENV['DRY_RUN']})", flush=True)

    while True:
        time.sleep(1.0)
        now = time.time()

        lines = read_last_lines(ENV["DELTASCOUT_LOG"], n=20)
        new_items: List[tuple[str,str]] = []
        for ln in lines:
            if not ln.strip():
                continue
            h = line_hash(ln)
            if h not in st["meta"]["seen_hashes"]:
                new_items.append((h, ln))
        if not new_items:
            continue

        df = load_df_sorted()

        for h, line in new_items:
            st["meta"]["seen_hashes"] = (st["meta"]["seen_hashes"] + [h])[-100:]
            try:
                evt = json.loads(line)
            except Exception:
                continue

            if evt.get("action") == "PEAK":
                close_price = float(evt.get("price"))
                entry = build_entry_price(evt.get("kind"), close_price)
                qty = notional_to_qty(entry, ENV["QTY_USD"])
                side = "BUY" if evt.get("kind") == "long" else "SELL"
                side_txt = "LONG" if side=="BUY" else "SHORT"
                i = locate_index_by_ts(df, datetime.fromisoformat(evt.get("ts")))
                sl = _swing_stop(df, i, side, entry)
                tps = _compute_tps(entry, sl, side)
                if len(tps) < 2:
                    raise RuntimeError(f"TPs not computed: entry={entry} sl={sl} side={side}")
                tp1, tp2 = tps[0], tps[1]

                st["position"] = {
                    "status": "OPEN",
                    "side": side_txt,
                    "qty": qty,
                    "entry_price": entry,
                    "sl": sl,
                    "tp2": tp2,
                    "tp1": tp1,
                }
                save_state(st)


                msg = build_message(entry, sl, tp1, tp2, side_txt)
                send_webhook({"event": "START", "symbol": ENV["SYMBOL"], "message": msg})
                # Public repo version: close immediately (demo behavior).
                # Internal execution version may keep position lifecycle and emit CLOSE/STOPPED, etc.


                with open(ENV["DELTASCOUT_LOG"], "a") as f:
                    f.write(json.dumps({"source":"Buyer","action":"CLOSED","ts": now_utc().isoformat()})+"\n")
                st["position"] = None
                save_state(st)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("buyer: stopped")
