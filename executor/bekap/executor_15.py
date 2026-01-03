#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""executor.py
Executor — execution engine for DeltaScout PEAK signals.

Design goals
- Reads DeltaScout JSONL events from a shared log file (DELTASCOUT_LOG)
- Single-position mode: ignores new PEAK while a position is OPEN/PENDING
- DRY=1 (paper) now, DRY=0 (Binance) later
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
import inspect
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



def _get_str(name: str, default: str) -> str:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s != "" else default


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
"MAX_PEAK_AGE_SEC": _get_int("MAX_PEAK_AGE_SEC", 600),
"STRICT_SOURCE": _get_bool("STRICT_SOURCE", True),

# sizing
"SYMBOL": os.getenv("SYMBOL", "BTCUSDC"),
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
"SWING_MINS": _get_int("SWING_MINS", 180),
"TP_R_LIST": [float(x) for x in os.getenv("TP_R_LIST", "1,2").split(",") if x.strip()],

# polling
"POLL_SEC": _get_float("POLL_SEC", 5.0),

# webhook (n8n)
"N8N_WEBHOOK_URL": os.getenv("N8N_WEBHOOK_URL", ""),
"N8N_BASIC_AUTH_USER": os.getenv("N8N_BASIC_AUTH_USER", ""),
"N8N_BASIC_AUTH_PASSWORD": os.getenv("N8N_BASIC_AUTH_PASSWORD", ""),

# Binance (used only when DRY=0)
"BINANCE_BASE_URL": os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
"BINANCE_API_KEY": os.getenv("BINANCE_API_KEY", ""),
"BINANCE_API_SECRET": os.getenv("BINANCE_API_SECRET", ""),

# Trading account mode
"TRADE_MODE": os.getenv("TRADE_MODE", "spot"),  # spot | margin
"RECV_WINDOW": _get_int("RECV_WINDOW", 5000),

# Margin-specific (only used when TRADE_MODE=margin)
"MARGIN_ISOLATED": os.getenv("MARGIN_ISOLATED", "FALSE"),  # "TRUE" / "FALSE"
"MARGIN_SIDE_EFFECT": os.getenv("MARGIN_SIDE_EFFECT", "AUTO_BORROW_REPAY"),
"MARGIN_AUTO_REPAY_AT_CANCEL": _get_bool("MARGIN_AUTO_REPAY_AT_CANCEL", False),

# Live mode helpers
"LIVE_VALIDATE_ONLY": _get_bool("LIVE_VALIDATE_ONLY", False),
"LIVE_ENTRY_TIMEOUT_SEC": _get_int("LIVE_ENTRY_TIMEOUT_SEC", 90),
"ENTRY_MODE": _get_str("ENTRY_MODE", "LIMIT_THEN_MARKET"),  # LIMIT_ONLY | LIMIT_THEN_MARKET | MARKET_ONLY
"PLANB_MAX_DEV_R_MULT": _get_float("PLANB_MAX_DEV_R_MULT", 0.25),
"PLANB_MAX_DEV_USD": _get_float("PLANB_MAX_DEV_USD", 0.0),
"PLANB_REQUIRE_PRICE": _get_bool("PLANB_REQUIRE_PRICE", True),
"PLANB_ABORT_IF_PAST_TP1": _get_bool("PLANB_ABORT_IF_PAST_TP1", True),
"EXITS_RETRY_EVERY_SEC": _get_int("EXITS_RETRY_EVERY_SEC", 15),
"FAILSAFE_FLATTEN": _get_bool("FAILSAFE_FLATTEN", False),
"FAILSAFE_EXITS_MAX_TRIES": _get_int("FAILSAFE_EXITS_MAX_TRIES", 5),
"FAILSAFE_EXITS_GRACE_SEC": _get_int("FAILSAFE_EXITS_GRACE_SEC", 60),
"LIVE_STATUS_POLL_EVERY": _get_int("LIVE_STATUS_POLL_EVERY", 10),
"MANAGE_EVERY_SEC": _get_int("MANAGE_EVERY_SEC", 15),
"TRAIL_ACTIVATE_AFTER_TP2": _get_bool("TRAIL_ACTIVATE_AFTER_TP2", True),
"TRAIL_STEP_USD": _get_float("TRAIL_STEP_USD", 20.0),
"TRAIL_UPDATE_EVERY_SEC": _get_int("TRAIL_UPDATE_EVERY_SEC", 20),
"SL_LIMIT_GAP_TICKS": _get_int("SL_LIMIT_GAP_TICKS", 2),  # gap ticks for STOP_LOSS_LIMIT limit price vs stopPrice
# trailing source: "AGG" (aggregated.csv) or "BINANCE" (bookTicker mid)
"TRAIL_SOURCE": os.getenv("TRAIL_SOURCE", "AGG").strip().upper(),
# swing detection on ClosePrice from aggregated.csv
"TRAIL_SWING_LOOKBACK": _get_int("TRAIL_SWING_LOOKBACK", 240),   # rows
"TRAIL_SWING_LR": _get_int("TRAIL_SWING_LR", 2),                 # fractal L/R
"TRAIL_SWING_BUFFER_USD": _get_float("TRAIL_SWING_BUFFER_USD", 15.0),
}

# Binance server time offset (ms). Helps avoid timestamp drift / -1021 errors.
BINANCE_TIME_OFFSET_MS = 0

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
    """Read only the last N lines from a potentially large file.

    IMPORTANT: This must NOT iterate from the beginning of the file each loop.
    We tail from EOF in fixed-size blocks to reduce VPS IO/CPU load.
    """
    if n <= 0:
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            buf = b""
            block = 8192
            # Read blocks from the end until we have at least N newlines or reach BOF
            while end > 0 and buf.count(b"\n") <= n:
                step = block if end >= block else end
                end -= step
                f.seek(end)
                buf = f.read(step) + buf

            lines = buf.splitlines()[-n:]
            return [ln.decode("utf-8", errors="ignore") for ln in lines]
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
    """Stable dedup key for PEAK events.

    Previous version used only rounded price, which can 'glue' distinct events together (e.g. to 0.1).
    Here we include multiple fields emitted by DeltaScout (ts/kind/price/delta/vol/imb).
    """
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

    # Use quantized values (string-stable), but avoid over-rounding.
    def _q(x: Any, nd: int) -> str:
        with suppress(Exception):
            xf = float(x)
            if math.isfinite(xf):
                return f"{xf:.{nd}f}"
        return "na"

    price_q = _q(evt.get("price"), max(2, int(ENV["DEDUP_PRICE_DECIMALS"])))
    delta_q = _q(evt.get("delta"), 2)
    vol_q = _q(evt.get("vol"), 2)
    imb_q = _q(evt.get("imb"), 3)

    return f"PEAK|{ts}|{kind}|p={price_q}|d={delta_q}|v={vol_q}|i={imb_q}"

# ===================== Webhook =====================

def dedup_fingerprint() -> str:
    """Fingerprint of the current de-duplication scheme.

    If stable_event_key() logic changes, this fingerprint changes too.
    On boot we can safely rebuild seen_keys from the DeltaScout log tail.
    """
    try:
        src = inspect.getsource(stable_event_key)
    except Exception:
        src = "stable_event_key"
    base = f"{src}|DEDUP_PRICE_DECIMALS={ENV.get('DEDUP_PRICE_DECIMALS')}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def _dt_utc(ts_any: Any) -> Optional[pd.Timestamp]:
    """Parse various timestamp formats to UTC Timestamp, or None."""
    if ts_any is None:
        return None
    try:
        dt = pd.to_datetime(str(ts_any), utc=True, errors="coerce")
    except Exception:
        return None
    if dt is None or pd.isna(dt):
        return None
    return dt


def bootstrap_seen_keys_from_tail(st: Dict[str, Any], tail_lines: List[str]) -> None:
    """On boot, mark all PEAKs currently present in the DeltaScout log tail as 'seen'.

    This prevents accidental trading of historical PEAKs after container/VPS restart,
    API-key rotation, or de-dup key format changes.
    """
    meta = st.setdefault("meta", {})

    fp_now = dedup_fingerprint()
    fp_old = meta.get("dedup_fp")
    if fp_old != fp_now:
        # Reset seen_keys when scheme changed
        meta["seen_keys"] = []
        log_event("DEDUP_SCHEMA_CHANGED", old=fp_old, new=fp_now)

    seen = set(meta.get("seen_keys", []))
    added = 0

    # Watermark: newest PEAK timestamp we've already consumed/ignored
    last_peak_ts_dt = _dt_utc(meta.get("last_peak_ts"))

    for ln in tail_lines:
        try:
            evt = json.loads(ln)
        except Exception:
            continue
        if evt.get("action") != "PEAK":
            continue

        k = stable_event_key(evt)
        if k and k not in seen:
            seen.add(k)
            added += 1

        dt = _dt_utc(evt.get("ts"))
        if dt is not None and (last_peak_ts_dt is None or dt > last_peak_ts_dt):
            last_peak_ts_dt = dt

    if last_peak_ts_dt is not None:
        meta["last_peak_ts"] = last_peak_ts_dt.isoformat()

    meta["seen_keys"] = list(seen)[-int(ENV.get("SEEN_KEYS_MAX", 500)):]
    meta["dedup_fp"] = fp_now
    meta["boot_ts"] = iso_utc()

    save_state(st)

    log_event(
        "BOOTSTRAP_SEEN_KEYS",
        added=added,
        total=len(meta["seen_keys"]),
        last_peak_ts=meta.get("last_peak_ts"),
        dedup_fp=meta.get("dedup_fp"),
    )


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


def _decimals_from_step(step: Decimal) -> int:
    """Number of decimal places implied by a step (tick/lot)."""
    step = Decimal(step)
    return max(0, -step.as_tuple().exponent)


def fmt_price(p: float) -> str:
    """Format price as a string respecting TICK_SIZE."""
    dp = _decimals_from_step(ENV["TICK_SIZE"])
    return f"{p:.{dp}f}"



def _oid_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None

def _avg_fill_price(order: Dict[str, Any]) -> Optional[float]:
    """Average fill price from an order payload when possible."""
    try:
        exq = float(order.get("executedQty") or 0.0)
        cq = float(order.get("cummulativeQuoteQty") or order.get("cumulativeQuoteQty") or 0.0)
        if exq > 0 and cq > 0:
            return cq / exq
    except Exception:
        return None
    return None
def fmt_qty(q: float) -> str:
    """Format quantity as a string respecting QTY_STEP (trim trailing zeros)."""
    dp = _decimals_from_step(ENV["QTY_STEP"])
    s = f"{q:.{dp}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s

# Backward-compatible name (kept for any leftover uses)

def round_qty(x: float) -> float:
    """Round a quantity DOWN to the configured qty step."""
    return floor_to_step(x, ENV["QTY_STEP"])


def build_entry_price(kind: str, close_price: float) -> float:
    """Entry price builder used for both paper and live.

    For breakout-style entries:
      - long  -> above close
      - short -> below close

    Rounding is *directional* so we don't accidentally make the trigger harder by rounding.
    """
    raw = close_price + ENV["ENTRY_OFFSET_USD"] if kind == "long" else close_price - ENV["ENTRY_OFFSET_USD"]

    if kind == "long":
        # keep it above close by at least 1 tick
        raw = max(raw, close_price + float(ENV["TICK_SIZE"]))
        return floor_to_step(raw, ENV["TICK_SIZE"])
    else:
        # keep it below close by at least 1 tick
        raw = min(raw, close_price - float(ENV["TICK_SIZE"]))
        return ceil_to_step(raw, ENV["TICK_SIZE"])

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

    return floor_to_step(sl, ENV["TICK_SIZE"]) if side == "BUY" else ceil_to_step(sl, ENV["TICK_SIZE"])


def compute_tps(entry: float, sl: float, side: str) -> List[float]:
    """TP list based on the *real* risk (entry <-> SL).

    Rounding is directional:
      - BUY (long): TP rounded down (slightly easier to hit)
      - SELL (short): TP rounded up (slightly easier to hit)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return []

    tps: List[float] = []
    for rmult in ENV["TP_R_LIST"]:
        if side == "BUY":
            tp_raw = entry + rmult * risk
            tp = floor_to_step(tp_raw, ENV["TICK_SIZE"])
        else:
            tp_raw = entry - rmult * risk
            tp = ceil_to_step(tp_raw, ENV["TICK_SIZE"])
        tps.append(tp)
    return tps

# ===================== Binance adapter (used only when DRY=0) =====================

def _binance_signed_request(method: str, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    api_key = ENV["BINANCE_API_KEY"]
    api_secret = ENV["BINANCE_API_SECRET"]
    base_url = ENV["BINANCE_BASE_URL"]
    if not api_key or not api_secret:
        raise RuntimeError("Binance API key/secret missing")

    params = dict(params)
    params["timestamp"] = int(time.time() * 1000) + int(BINANCE_TIME_OFFSET_MS)
    params.setdefault("recvWindow", ENV.get("RECV_WINDOW", 5000))

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


def binance_public_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Public GET without signature (used for rare Plan B guards)."""
    base_url = ENV["BINANCE_BASE_URL"]
    url = base_url + endpoint
    r = requests.get(url, params=params or {}, timeout=5)
    if r.status_code != 200:
        raise RuntimeError(f"Binance API error: {r.status_code} {r.text}")
    return r.json() if r.text else {}


def _planb_exec_price(symbol: str, entry_side: str) -> Optional[float]:
    """Return a conservative executable price for Plan B checks.
    BUY  -> use ask
    SELL -> use bid
    """
    j = binance_public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    try:
        bid = float(j.get("bidPrice"))
        ask = float(j.get("askPrice"))
    except Exception:
        return None
    if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask > 0):
        return None
    return ask if entry_side.upper() == "BUY" else bid


def _planb_market_allowed(posi: Dict[str, Any], px_exec: float) -> Tuple[bool, str, Dict[str, Any]]:
    """Guard against chasing far away from planned entry.
    Returns (allowed, reason, info).
    """
    try:
        prices = posi.get("prices") or {}
        entry = float(prices.get("entry"))
        sl = float(prices.get("sl"))
        tp1 = float(prices.get("tp1"))
    except Exception:
        return False, "bad_prices", {}
    if not (math.isfinite(entry) and math.isfinite(sl) and entry > 0 and sl > 0):
        return False, "bad_prices", {"entry": entry, "sl": sl}

    risk = abs(entry - sl)
    r_mult = float(ENV.get("PLANB_MAX_DEV_R_MULT") or 0.0)
    max_usd = float(ENV.get("PLANB_MAX_DEV_USD") or 0.0)
    max_dev = max(risk * r_mult, max_usd) if max_usd > 0 else risk * r_mult

    dev = abs(px_exec - entry)
    info = {"px_exec": px_exec, "entry": entry, "sl": sl, "risk": risk, "dev": dev, "max_dev": max_dev}

    if max_dev > 0 and dev > max_dev:
        return False, "deviation_too_large", info

    if ENV.get("PLANB_ABORT_IF_PAST_TP1", True):
        side_txt = str(posi.get("side") or "").upper()
        if math.isfinite(tp1) and tp1 > 0:
            if side_txt == "LONG" and px_exec >= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info
            if side_txt == "SHORT" and px_exec <= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info

    return True, "ok", info


def _clear_position_slot(st: Dict[str, Any], reason: str, **fields: Any) -> None:
    """Fail-safe cleanup: free position slot so new PEAKs can be handled."""
    pos = st.get("position")
    st["last_closed"] = {
        "ts": iso_utc(),
        "mode": (pos or {}).get("mode"),
        "reason": reason,
        "pos_status": (pos or {}).get("status"),
        **fields,
    }
    st["position"] = None
    # unlock; avoid blocking next PEAK for no reason
    st["lock_until"] = 0.0
    save_state(st)


def place_spot_limit(symbol: str, side: str, qty: float, price: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Place a LIMIT order.

    Supports:
      - TRADE_MODE=spot   -> POST /api/v3/order
      - TRADE_MODE=margin -> POST /sapi/v1/margin/order

    For margin we pass:
      - isIsolated (TRUE/FALSE)
      - sideEffectType (e.g. AUTO_BORROW_REPAY / AUTO_REPAY / MARGIN_BUY / NO_SIDE_EFFECT)
      - autoRepayAtCancel (optional)
      - newClientOrderId (optional, recommended for reliable sync-on-restart)
    """
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()

    # Format quantity/price as strings to avoid float quirks
    qty_s = fmt_qty(qty)
    price_s = fmt_price(price)

    if mode == "margin":
        params: Dict[str, Any] = {
            "symbol": symbol,
            "isIsolated": ENV["MARGIN_ISOLATED"],
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty_s,
            "price": price_s,
            "newOrderRespType": "FULL",
            "sideEffectType": ENV["MARGIN_SIDE_EFFECT"],
        }
        if client_id:
            params["newClientOrderId"] = client_id
        params["autoRepayAtCancel"] = "TRUE" if ENV["MARGIN_AUTO_REPAY_AT_CANCEL"] else "FALSE"
        return _binance_signed_request("POST", "/sapi/v1/margin/order", params)

    # spot
    params2: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": qty_s,
        "price": price_s,
    }
    if client_id:
        params2["newClientOrderId"] = client_id
    return _binance_signed_request("POST", "/api/v3/order", params2)


def place_spot_market(symbol: str, side: str, qty: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Place a MARKET order in current TRADE_MODE (spot or margin)."""
    qty_r = round_qty(qty)
    params: Dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": fmt_qty(qty_r),
        "newOrderRespType": "FULL",
    }
    if client_id:
        params["newClientOrderId"] = client_id
    return place_order_raw(params)

def flatten_market(symbol: str, pos_side: str, qty: float, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Fail-safe: close a live position by MARKET (best effort)."""
    exit_side = "SELL" if str(pos_side).upper() == "LONG" else "BUY"
    if not client_id:
        client_id = f"EX_FLAT_{int(time.time())}"
    return place_spot_market(symbol, exit_side, qty, client_id=client_id)
def check_order_status(symbol: str, order_id: int) -> Dict[str, Any]:
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        return _binance_signed_request(
            "GET",
            "/sapi/v1/margin/order",
            {"symbol": symbol, "isIsolated": ENV["MARGIN_ISOLATED"], "orderId": order_id},
        )
    return _binance_signed_request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})


def cancel_order(symbol: str, order_id: int) -> Dict[str, Any]:
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        return _binance_signed_request(
            "DELETE",
            "/sapi/v1/margin/order",
            {"symbol": symbol, "isIsolated": ENV["MARGIN_ISOLATED"], "orderId": order_id},
        )
    return _binance_signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})



def open_orders(symbol: str) -> List[Dict[str, Any]]:
    """Return open orders for symbol in current TRADE_MODE."""
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        j = _binance_signed_request("GET", "/sapi/v1/margin/openOrders", {"symbol": symbol, "isIsolated": ENV["MARGIN_ISOLATED"]})
        return list(j) if isinstance(j, list) else []
    j = _binance_signed_request("GET", "/api/v3/openOrders", {"symbol": symbol})
    return list(j) if isinstance(j, list) else []


def place_order_raw(endpoint_params: Dict[str, Any]) -> Dict[str, Any]:
    """Place an order in current TRADE_MODE.

    For margin orders, required common parameters are injected:
      - isIsolated
      - sideEffectType (if not already provided)
      - autoRepayAtCancel (if not already provided)
    """
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()

    if mode == "margin":
        p = dict(endpoint_params)
        p.setdefault("symbol", ENV["SYMBOL"])
        p.setdefault("isIsolated", ENV["MARGIN_ISOLATED"])
        p.setdefault("sideEffectType", ENV["MARGIN_SIDE_EFFECT"])
        p.setdefault("autoRepayAtCancel", "TRUE" if ENV["MARGIN_AUTO_REPAY_AT_CANCEL"] else "FALSE")
        return _binance_signed_request("POST", "/sapi/v1/margin/order", p)

    # spot
    p = dict(endpoint_params)
    p.setdefault("symbol", ENV["SYMBOL"])
    return _binance_signed_request("POST", "/api/v3/order", p)



def validate_exit_plan(symbol: str, side: str, qty_total: float, prices: Dict[str, float]) -> Dict[str, Any]:
    """Validate exits inputs before placing orders.

    Goals:
      - Fail fast with a clear message BEFORE we hit Binance errors
      - Prevent silent rounding/formatting surprises
      - Guarantee qty split does not round to zero
    """
    if not isinstance(prices, dict):
        raise RuntimeError(f"prices must be dict, got {type(prices).__name__}")

    required = ("entry", "sl", "tp1", "tp2")
    missing = [k for k in required if k not in prices or prices.get(k) is None]
    if missing:
        raise RuntimeError(f"Missing price keys: {missing}")

    # Normalize to floats
    p: Dict[str, float] = {}
    for k in required:
        try:
            p[k] = float(prices[k])
        except Exception:
            raise RuntimeError(f"Invalid price for {k}: {prices.get(k)!r}")

    # Basic sanity
    for k, v in p.items():
        if not math.isfinite(v) or v <= 0:
            raise RuntimeError(f"Invalid price {k}={v}")

    side_u = str(side).upper()
    if side_u not in ("LONG", "SHORT"):
        raise RuntimeError(f"Invalid side={side!r} (expected LONG/SHORT)")

    # Enforce directional ordering (best-effort safety)
    if side_u == "LONG":
        if not (p["sl"] < p["entry"] < p["tp1"] <= p["tp2"]):
            raise RuntimeError(f"Bad LONG price ordering: sl<{p['sl']}, entry<{p['entry']}, tp1<{p['tp1']}, tp2<{p['tp2']}")
    else:  # SHORT
        if not (p["sl"] > p["entry"] > p["tp1"] >= p["tp2"]):
            raise RuntimeError(f"Bad SHORT price ordering: sl>{p['sl']}, entry>{p['entry']}, tp1>{p['tp1']}, tp2>{p['tp2']}")

    # Tick alignment check (Decimal, tolerant) + normalize to exact tick
    tick_s = str(ENV.get("TICK_SIZE", "0.01"))
    tick = Decimal(tick_s)

    # tolerance = tiny fraction of tick to ignore float noise
    # (you can tighten/loosen; 1e-6 tick is usually safe)
    tol = tick / Decimal("1000000")

    def D(x) -> Decimal:
        # IMPORTANT: never Decimal(float) directly
        return Decimal(str(x))

    def align_to_tick(v: Decimal) -> Decimal:
        # nearest tick (HALF_UP is fine for validation stage)
        steps = (v / tick).to_integral_value(rounding=ROUND_HALF_UP)
        return steps * tick

    for k, v in p.items():
        vd = D(v)
        aligned = align_to_tick(vd)

        # if truly off-tick -> fail fast
        if abs(aligned - vd) > tol:
            raise RuntimeError(
                f"Price not aligned to tick: {k}={v} tick={tick_s} (aligned={float(aligned)})"
           )

        # normalize to exact aligned value to avoid later precision surprises
        p[k] = float(aligned)


    # Qty checks & split checks (mirrors place_exits_v15 but gives clearer errors)
    try:
        qt = float(qty_total)
    except Exception:
        raise RuntimeError(f"Invalid qty_total: {qty_total!r}")
    if not math.isfinite(qt) or qt <= 0:
        raise RuntimeError(f"Invalid qty_total={qt}")

    qty_total_r = round_qty(qt)
    min_qty = float(ENV.get("MIN_QTY", 0.0))
    if qty_total_r < min_qty:
        raise RuntimeError(f"qty_total too small after rounding: qty_total={qt} -> {qty_total_r} (min_qty={min_qty})")
    # Split strictly in integer 'step units' to avoid float floor artefacts
    step_d = ENV["QTY_STEP"]  # Decimal
    total_units = int((Decimal(str(qty_total_r)) / step_d).to_integral_value(rounding=ROUND_FLOOR))
    if total_units <= 0:
        raise RuntimeError(f"Invalid qty after rounding: qty_total_r={qty_total_r} step={step_d}")

    u1 = total_units // 3
    u2 = total_units // 3
    u3 = total_units - u1 - u2

    # If any of first two legs becomes zero -> degrade to 2 legs (50/50), no trailing leg
    if u1 <= 0 or u2 <= 0:
        u1 = total_units // 2
        u2 = total_units - u1
        u3 = 0

    if (u1 + u2 + u3) != total_units:
        raise RuntimeError(f"Internal split error: units=({u1},{u2},{u3}) total_units={total_units}")

    qty1 = float(Decimal(u1) * step_d)
    qty2 = float(Decimal(u2) * step_d)
    qty3 = float(Decimal(u3) * step_d)
    if qty1 <= 0 or qty2 <= 0 or qty3 < 0:
        raise RuntimeError(f"Invalid qty split after rounding: qty_total={qty_total_r} qty1={qty1} qty2={qty2} step={ENV.get('QTY_STEP')}")

    # Min notional safety (optional but helpful)
    min_notional = float(ENV.get("MIN_NOTIONAL", 0.0))
    if min_notional > 0:
        worst_price = min(p.values())
        notional = worst_price * qty_total_r
        if notional < min_notional:
            raise RuntimeError(f"MinNotional fail (worst-case): price={worst_price} qty={qty_total_r} notional={notional} < {min_notional}")

    return {
        "qty_total_r": qty_total_r,
        "qty1": qty1,
        "qty2": qty2,
        "qty3": qty3,
        "prices": p,
    }

# === FIX 1: Helpers for safer Plan B and LIMIT_MAKER fallback ===

def _is_limit_maker_reject(exc: Exception) -> bool:
    """Detect Binance LIMIT_MAKER rejection (would immediately match)."""
    msg = str(exc).lower()
    return (
        "would immediately match" in msg
        or "immediately match and take" in msg
        or '"code":-2010' in msg
        or "code: -2010" in msg
    )


def _place_limit_maker_then_limit(payload: dict) -> dict:
    """Try LIMIT_MAKER first; if rejected, retry as LIMIT GTC."""
    try:
        return place_order_raw(payload)
    except Exception as e:
        if not _is_limit_maker_reject(e):
            raise
        # fallback
        payload2 = dict(payload)
        payload2["type"] = "LIMIT"
        payload2["timeInForce"] = "GTC"
        cid = str(payload.get("newClientOrderId") or "")
        if cid:
            payload2["newClientOrderId"] = (cid + "_GTC")[:36]
        log_event("LIMIT_MAKER_REJECT", reason=str(e))
        return place_order_raw(payload2)

def place_exits_v15(symbol: str, side: str, qty_total: float, prices: Dict[str, float]) -> Dict[str, Any]:
    """Place TP1 + TP2 + SL for V1.5 (no OCO).

    side: "LONG" | "SHORT"
    prices: {entry, sl, tp1, tp2} in *USDC* terms (already rounded)
    """
    # Ensure qty is aligned to lot step before splitting
    qty_total_r = round_qty(qty_total)

    # Split strictly in integer 'step units' to avoid float floor artefacts
    step_d = ENV["QTY_STEP"]  # Decimal
    total_units = int((Decimal(str(qty_total_r)) / step_d).to_integral_value(rounding=ROUND_FLOOR))
    if total_units <= 0:
        raise RuntimeError(f"Invalid qty split after rounding: qty_total_r={qty_total_r} step={step_d}")

    u1 = total_units // 3
    u2 = total_units // 3
    u3 = total_units - u1 - u2

    # If any of first two legs becomes zero -> degrade to 2 legs (50/50), no trailing leg
    if u1 <= 0 or u2 <= 0:
        u1 = total_units // 2
        u2 = total_units - u1
        u3 = 0

    if (u1 + u2 + u3) != total_units:
        raise RuntimeError(f"Internal split error: units=({u1},{u2},{u3}) total_units={total_units}")

    qty1 = float(Decimal(u1) * step_d)
    qty2 = float(Decimal(u2) * step_d)
    qty3 = float(Decimal(u3) * step_d)
    if qty1 <= 0 or qty2 <= 0 or qty3 < 0:
        raise RuntimeError(f"Invalid qty split: qty_total={qty_total_r} qty1={qty1} qty2={qty2} qty3={qty3}")
    # Binance expects strings for precise formatting
    qty_total_s = fmt_qty(qty_total_r)
    qty1_s = fmt_qty(qty1)
    qty2_s = fmt_qty(qty2)

    tp1_s = fmt_price(float(prices["tp1"]))
    tp2_s = fmt_price(float(prices["tp2"]))
    sl_s = fmt_price(float(prices["sl"]))

    exit_side = "SELL" if side == "LONG" else "BUY"

    tp1 = _place_limit_maker_then_limit({
        "symbol": symbol,
        "side": exit_side,
        "type": "LIMIT_MAKER",
        "quantity": qty1_s,
        "price": tp1_s,
        "newClientOrderId": f"EX_TP1_{int(time.time())}",
    })
    tp2 = _place_limit_maker_then_limit({
        "symbol": symbol,
        "side": exit_side,
        "type": "LIMIT_MAKER",
        "quantity": qty2_s,
        "price": tp2_s,
        "newClientOrderId": f"EX_TP2_{int(time.time())}",
    })
    # Stop-loss for the whole remaining position (we adjust after TP1 in manage_v15_position)
    #    # STOP_LOSS_LIMIT safety gap (limit price vs stop trigger)
    stop_p = float(prices["sl"])
    tick = float(ENV["TICK_SIZE"])
    gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
    gap = tick * float(gap_ticks)
    limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
    sl_stop_s = fmt_price(stop_p)
    sl_price_s = fmt_price(limit_p)
    # Ensure price != stopPrice even after rounding to tick size
    if sl_price_s == sl_stop_s:
        sl_price_s = fmt_price((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))
    sl = place_order_raw({
        "symbol": symbol,
        "side": exit_side,
        "type": "STOP_LOSS_LIMIT",
        "quantity": qty_total_s,
        "stopPrice": sl_stop_s,
        "price": sl_price_s,
        "timeInForce": "GTC",
        "newClientOrderId": f"EX_SL_{int(time.time())}",
    })

    return {
        "tp1": tp1["orderId"],
        "tp2": tp2["orderId"],
        "sl": sl["orderId"],
        "qty1": qty1,
        "qty2": qty2,
        "qty3": qty3,
    }
def manage_v15_position(symbol: str, st: Dict[str, Any]) -> None:
    """Live V1.5 manager: TP1 -> move SL to BE (entry), TP2 continues.

    Optimized:
      - Throttled by MANAGE_EVERY_SEC in main loop
      - Uses a single openOrders fetch
      - Verifies missing orders via order status (FILLED) before acting
    """
    pos = st.get("position") or {}
    if pos.get("mode") != "live" or pos.get("status") not in ("OPEN", "OPEN_FILLED"):
        return
    if not pos.get("orders") or not pos.get("prices"):
        return
    now_s = _now_s()
    try:
        orders = open_orders(symbol)
    except Exception as e:
        # Do not abort manage-cycle: openOrders can be empty/incomplete or fail transiently.
        # We still can verify FILLED via check_order_status and cancel siblings best-effort.
        orders = []
        now_err = _now_s()
        last_err = float(pos.get("open_orders_err_s") or 0.0)
        if now_err - last_err >= 30.0:
            pos["open_orders_err_s"] = now_err
            st["position"] = pos
            save_state(st)
            log_event("LIVE_MANAGE_ERROR", error=f"openOrders: {e}")

    open_ids: set[int] = set()
    for _o in (orders or []):
        if not isinstance(_o, dict):
            continue
        with suppress(Exception):
            open_ids.add(int(_o.get("orderId")))

    def _status_is_filled(order_id: int) -> bool:
        try:
            od = check_order_status(symbol, int(order_id))
            return str(od.get("status", "")).upper() == "FILLED"
        except Exception:
            return False

    def _close_slot(reason: str) -> None:
        st["last_closed"] = {
            "ts": iso_utc(),
            "mode": "live",
            "reason": reason,
            "side": pos.get("side"),
            "entry": (pos.get("prices") or {}).get("entry"),
        }
        st["position"] = None
        st["cooldown_until"] = _now_s() + float(ENV["COOLDOWN_SEC"])
        st["lock_until"] = 0.0
        save_state(st)

    tp1_id = int(pos["orders"].get("tp1") or 0)
    tp2_id = int(pos["orders"].get("tp2") or 0)
    sl_id = int(pos["orders"].get("sl") or 0)
    sl_prev = int(pos["orders"].get("sl_prev") or 0)

    # Якщо після TP1 ми замінили SL на BE, але старий SL не скасувався (або cancel впав),
    # то треба повторювати cancel best-effort раз на N секунд (без перевірки openOrders).
    if sl_prev and pos.get("tp1_done"):
        now_s = _now_s()
        next_s = float(pos.get("sl_prev_next_cancel_s") or 0.0)
        if now_s >= next_s:
            pos["sl_prev_next_cancel_s"] = now_s + float(ENV.get("ORPHAN_CANCEL_EVERY_SEC", 30))
            st["position"] = pos
            save_state(st)
            with suppress(Exception):
                cancel_order(symbol, sl_prev)

    # TP1 filled -> move SL to BE (entry) for remaining qty2+qty3
    if tp1_id and not pos.get("tp1_done"):
        poll_due = now_s >= float(pos.get("tp1_status_next_s") or 0.0)
        # Do not gate FILLED detection on openOrders/open_ids; throttle via tp1_status_next_s
        if poll_due or (not orders):
            pos["tp1_status_next_s"] = now_s + float(ENV["LIVE_STATUS_POLL_EVERY"])

            if _status_is_filled(tp1_id):
                exit_side = "SELL" if pos["side"] == "LONG" else "BUY"
                be_stop = float(pos.get("entry_actual") or (pos.get("prices") or {}).get("entry") or 0.0)

                qty2 = float((pos.get("orders") or {}).get("qty2") or 0.0)
                qty3 = float((pos.get("orders") or {}).get("qty3") or 0.0)
                rem_qty = float(round_qty(qty2 + qty3))

                tick = float(ENV["TICK_SIZE"])
                gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
                gap = tick * float(gap_ticks)
                be_limit = (be_stop - gap) if exit_side == "SELL" else (be_stop + gap)
                be_stop_s = fmt_price(be_stop)
                be_limit_s = fmt_price(be_limit)
                # Ensure price != stopPrice even after rounding
                if be_limit_s == be_stop_s:
                    be_limit_s = fmt_price((be_stop - tick) if exit_side == "SELL" else (be_stop + tick))
                try:
                    sl_new = place_order_raw({
                        "symbol": symbol,
                        "side": exit_side,
                        "type": "STOP_LOSS_LIMIT",
                        "quantity": fmt_qty(rem_qty),
                        "price": be_limit_s,
                        "stopPrice": be_stop_s,
                        "timeInForce": "GTC",
                        "newClientOrderId": f"EX_SL_BE_{int(time.time())}",
                    })
                except Exception as e:
                    log_event("TP1_SL_TO_BE_ERROR", error=str(e), mode="live", order_id_tp1=tp1_id)
                    send_webhook({"event": "TP1_SL_TO_BE_ERROR", "mode": "live", "symbol": symbol, "order_id_tp1": tp1_id, "error": str(e)})
                else:
                    sl_id = int((pos.get("orders") or {}).get("sl") or 0)
                    # Keep old SL id for best-effort cleanup even if cancel fails.
                    if sl_id:
                        pos["orders"]["sl_prev"] = sl_id
                        pos["sl_prev_next_cancel_s"] = _now_s()
                    pos["orders"]["sl"] = _oid_int(sl_new.get("orderId"))
                    pos["tp1_done"] = True
                    st["position"] = pos
                    save_state(st)
                    log_event("TP1_DONE_SL_TO_BE", mode="live", order_id_tp1=tp1_id, new_sl_order_id=sl_new.get("orderId"))
                    send_webhook({"event": "TP1_DONE_SL_TO_BE", "mode": "live", "symbol": symbol, "new_sl_order_id": sl_new.get("orderId"), "entry": be_stop})
                    # Best-effort cancel of old SL (do not depend on openOrders).
                    if sl_id:
                        with suppress(Exception):
                            cancel_order(symbol, sl_id)
            else:
                # Log once to avoid spam; can happen if order exists but is not filled yet.
                miss = pos.setdefault("missing_not_filled", {})
                key = f"tp1:{tp1_id}"
                if poll_due and not miss.get(key):
                    miss[key] = iso_utc()
                    st["position"] = pos
                    save_state(st)
                    log_event("TP1_NOT_FILLED", mode="live", order_id_tp1=tp1_id)

    # TP2 filled -> activate trailing SL for remaining qty3 (if configured)
    if tp2_id and not pos.get("tp2_done"):    
        if _status_is_filled(tp2_id):
            pos["tp2_done"] = True
            st["position"] = pos
            save_state(st)
            log_event("TP2_DONE", mode="live", order_id_tp2=tp2_id)
            send_webhook({"event": "TP2_DONE", "mode": "live", "symbol": symbol})

            qty3 = float((pos.get("orders") or {}).get("qty3") or 0.0)
            qty1 = float((pos.get("orders") or {}).get("qty1") or 0.0)
            tp1_filled_now = bool(pos.get("tp1_done"))
            if (not tp1_filled_now) and tp1_id:
                with suppress(Exception):
                    tp1_filled_now = _status_is_filled(tp1_id)
            open_qty = qty3 if tp1_filled_now else (qty1 + qty3)
            if ENV.get("TRAIL_ACTIVATE_AFTER_TP2", True) and open_qty > 0.0:

                # cancel TP1 best-effort (should already be filled, but do not assume)
                if tp1_id:
                    with suppress(Exception):
                        cancel_order(symbol, tp1_id)

                # replace current SL with trailing SL for remaining qty (qty3, or qty1+qty3 if TP2 filled first)
                sl_now = int((pos.get("orders") or {}).get("sl") or 0)

               # Primary: trailing stop from aggregated.csv swings (low API usage).
                desired = _trail_desired_stop_from_agg(pos)
                if desired is None:
                    # Fallback (only if CSV unavailable): public mid-price +/- buffer
                    mid = 0.0
                    with suppress(Exception):
                        mid = float(get_mid_price(symbol))
                    if mid > 0.0:
                        off = float(ENV.get("TRAIL_SWING_BUFFER_USD") or 15.0)
                        desired = (mid - off) if pos["side"] == "LONG" else (mid + off)

                if desired is not None:
                    desired_f = float(fmt_price(desired))
                    if desired_f <= 0.0:
                        desired = None

                if desired is not None:
                    exit_side = "SELL" if pos["side"] == "LONG" else "BUY"
                    # Optional gap between stopPrice and limit price for STOP_LOSS_LIMIT (reduces rejections).
                    tick = float(ENV["TICK_SIZE"])
                    gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
                    gap = tick * float(gap_ticks)
                    stop_p = desired_f
                    limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
                    sl_stop_s = fmt_price(stop_p)
                    sl_price_s = fmt_price(limit_p)
                    # Ensure price != stopPrice even after rounding
                    if sl_price_s == sl_stop_s:
                        sl_price_s = fmt_price((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))

                    # Safety: do NOT place a new trailing SL unless previous SL cancel is confirmed.
                    sl_canceled_ok = True
                    if sl_now:
                        sl_canceled_ok = False
                        with suppress(Exception):
                            cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = check_order_status(symbol, sl_now)
                        st_c = str((od_c or {}).get("status", "")).upper()
                        if st_c in ("CANCELED", "REJECTED", "EXPIRED"):
                            sl_canceled_ok = True
                            pos.setdefault("orders", {})["sl"] = 0
                            pos["trail_pending_cancel_sl"] = 0
                        else:
                            pos["trail_pending_cancel_sl"] = sl_now
                            pos["trail_active"] = True
                            pos["trail_qty"] = open_qty
                            # Force quick retry via trailing maintenance (still rate-limited).
                            pos["trail_last_update_s"] = 0.0
                            st["position"] = pos
                            save_state(st)
                            log_event("TRAIL_ACTIVATE_WAIT_CANCEL", mode="live", order_id_sl=sl_now, status=st_c or "UNKNOWN")
                            return
                    else:
                        pos["trail_pending_cancel_sl"] = 0
                    try:
                        sl_new = place_order_raw({
                            "symbol": symbol,
                            "side": exit_side,
                            "type": "STOP_LOSS_LIMIT",
                            "quantity": fmt_qty(open_qty),
                            "price": sl_price_s,
                            "stopPrice": sl_stop_s,
                            "timeInForce": "GTC",
                            "newClientOrderId": f"EX_SL_TR_{int(time.time())}",
                        })
                    except Exception as e:
                        log_event("TRAIL_SL_PLACE_ERROR", error=str(e), mode="live")
                        # Fallback: immediately restore a protective SL (BE if TP1 filled, else original SL)
                        fb_stop = float(pos.get("entry_actual") or (pos.get("prices") or {}).get("entry") or 0.0) if tp1_filled_now else float((pos.get("prices") or {}).get("sl") or 0.0)
                        if fb_stop > 0.0:
                            gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
                            gap = tick * float(gap_ticks)
                            fb_limit = (fb_stop - gap) if exit_side == "SELL" else (fb_stop + gap)
                            fb_stop_s = fmt_price(fb_stop)
                            fb_limit_s = fmt_price(fb_limit)
                            if fb_limit_s == fb_stop_s:
                                fb_limit_s = fmt_price((fb_stop - tick) if exit_side == "SELL" else (fb_stop + tick))
                            try:
                                fb = place_order_raw({
                                    "symbol": symbol,
                                    "side": exit_side,
                                    "type": "STOP_LOSS_LIMIT",
                                    "quantity": fmt_qty(open_qty),
                                    "price": fb_limit_s,
                                    "stopPrice": fb_stop_s,
                                    "timeInForce": "GTC",
                                    "newClientOrderId": f"EX_SL_FB_{int(time.time())}",
                                })
                            except Exception as e2:
                                log_event("TRAIL_SL_FALLBACK_ERROR", error=str(e2), mode="live")
                            else:
                                if fb.get("orderId"):
                                    pos["orders"]["sl"] = _oid_int(fb.get("orderId"))
                                pos["trail_sl_price"] = float(fmt_price(fb_stop))
                                log_event("TRAIL_SL_FALLBACK_PLACED", mode="live", new_sl_order_id=fb.get("orderId"), trail_stop=pos.get("trail_sl_price"))
                        # Keep trail flags so we retry on next manage tick
                        pos["trail_active"] = True
                        pos["trail_qty"] = open_qty
                        pos["trail_last_update_s"] = now_s
                        st["position"] = pos
                        save_state(st)
                        return
                    else:
                        pos["orders"]["sl"] = _oid_int(sl_new.get("orderId"))
                        pos["trail_active"] = True
                        pos["trail_qty"] = open_qty
                        pos["trail_sl_price"] = float(fmt_price(stop_p))
                        pos["trail_last_update_s"] = now_s
                        pos["status"] = "OPEN"
                        st["position"] = pos
                        save_state(st)
                        log_event("TRAIL_ACTIVATED_AFTER_TP2", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])
                        send_webhook({"event": "TRAIL_ACTIVATED_AFTER_TP2", "mode": "live", "symbol": symbol, "new_sl_order_id": sl_new.get("orderId"), "trail_stop": pos["trail_sl_price"]})
                        return

                # No price right now -> mark trailing active and retry next tick
                pos["trail_active"] = True
                pos["trail_qty"] = open_qty
                pos["trail_last_update_s"] = now_s
                st["position"] = pos
                save_state(st)
                log_event("TRAIL_ACTIVATED_AFTER_TP2", mode="live", new_sl_order_id=None, trail_stop=None)
                return

            # No trailing configured -> close slot only if nothing remains
            if open_qty > 0.0:
                # Remaining exposure but trailing disabled: do NOT clear slot here
                pos["tp2_done"] = True
                st["position"] = pos
                save_state(st)
                log_event("TP2_DONE_REMAINING_QTY_NO_TRAIL",
                          mode="live", order_id_tp2=tp2_id, open_qty=open_qty)
                return

            # No remaining qty -> close slot like before

            sl_now = int((pos.get("orders") or {}).get("sl") or 0)
            if sl_now:
                with suppress(Exception):
                    cancel_order(symbol, sl_now)
            if tp1_id:
                with suppress(Exception):
                    cancel_order(symbol, tp1_id)
            sl_prev2 = int((pos.get("orders") or {}).get("sl_prev") or 0)
            if sl_prev2:
                with suppress(Exception):
                    cancel_order(symbol, sl_prev2)
            _close_slot("TP2")
            return
        else:
            miss = pos.setdefault("missing_not_filled", {})
            key = f"tp2:{tp2_id}"
            if not miss.get(key):
                miss[key] = iso_utc()
                st["position"] = pos
                save_state(st)
                log_event("TP2_NOT_FILLED", mode="live", order_id_tp2=tp2_id)

    # Trailing SL maintenance (after TP2) — emulate trailing by cancel/replace, prefer aggregated.csv swings
    if pos.get("trail_active"):
        last_u = float(pos.get("trail_last_update_s") or 0.0)
        every = float(ENV.get("TRAIL_UPDATE_EVERY_SEC") or 20)
        if now_s - last_u >= every:
            # Primary: aggregated.csv swings (no Binance polling).
            desired = _trail_desired_stop_from_agg(pos)
            if desired is None and str(ENV.get("TRAIL_SOURCE") or "AGG").upper() != "AGG":
                # Optional fallback if user forces BINANCE source and CSV is unavailable.
                mid = 0.0
                with suppress(Exception):
                    mid = float(get_mid_price(symbol))
                if mid > 0.0:
                    off = float(ENV.get("TRAIL_SWING_BUFFER_USD") or 15.0)
                    desired = (mid - off) if pos["side"] == "LONG" else (mid + off)
            if desired is not None:
                step = float(ENV.get("TRAIL_STEP_USD") or 20.0)
                desired_f = float(fmt_price(desired))
                current_f = float(pos.get("trail_sl_price") or 0.0)

                sl_now = int((pos.get("orders") or {}).get("sl") or 0)
                exit_side = "SELL" if pos["side"] == "LONG" else "BUY"

                # If activation asked to cancel an old SL, wait for cancel confirmation before placing a new one.
                pend_sl = int(pos.get("trail_pending_cancel_sl") or 0)
                if pend_sl:
                    od_p = None
                    with suppress(Exception):
                        od_p = check_order_status(symbol, pend_sl)
                    st_p = str((od_p or {}).get("status", "")).upper()
                    if st_p not in ("CANCELED", "REJECTED", "EXPIRED"):
                        pos["trail_last_update_s"] = now_s
                        st["position"] = pos
                        save_state(st)
                        log_event("TRAIL_WAIT_CANCEL", mode="live", order_id_sl=pend_sl, status=st_p or "UNKNOWN")
                        return
                    pos["trail_pending_cancel_sl"] = 0
                    pos.setdefault("orders", {})["sl"] = 0
                    sl_now = 0

                # If stored SL is already not active -> treat as missing (restore path will handle).
                if sl_now:
                    od_s = None
                    with suppress(Exception):
                        od_s = check_order_status(symbol, sl_now)
                    st_s = str((od_s or {}).get("status", "")).upper()
                    if st_s in ("CANCELED", "REJECTED", "EXPIRED"):
                        pos.setdefault("orders", {})["sl"] = 0
                        sl_now = 0

                tick = float(ENV["TICK_SIZE"])
                gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
                gap = tick * float(gap_ticks)
                stop_p = desired_f
                limit_p = (stop_p - gap) if exit_side == "SELL" else (stop_p + gap)
                sl_stop_s = fmt_price(stop_p)
                sl_price_s = fmt_price(limit_p)
                if sl_price_s == sl_stop_s:
                    sl_price_s = fmt_price((stop_p - tick) if exit_side == "SELL" else (stop_p + tick))

                trail_qty = float(pos.get("trail_qty") or 0.0)
                if trail_qty <= 0.0:
                    log_event("TRAIL_SL_SKIP_ZERO_QTY", mode="live")
                else:
                    improve = (desired_f - current_f) if pos["side"] == "LONG" else (current_f - desired_f)

                    # If SL disappeared while trailing is active -> restore immediately (best-effort).
                    if not sl_now:
                        try:
                            sl_new = place_order_raw({
                                "symbol": symbol,
                                "side": exit_side,
                                "type": "STOP_LOSS_LIMIT",
                                "quantity": fmt_qty(trail_qty),
                                "price": sl_price_s,
                                "stopPrice": sl_stop_s,
                                "timeInForce": "GTC",
                                "newClientOrderId": f"EX_SL_TR_RESTORE_{int(time.time())}",
                            })
                        except Exception as e:
                            log_event("TRAIL_SL_RESTORE_ERROR", error=str(e), mode="live")
                        else:
                            pos["orders"]["sl"] = _oid_int(sl_new.get("orderId"))
                            pos["trail_sl_price"] = float(sl_stop_s)
                            pos["trail_last_update_s"] = now_s
                            st["position"] = pos
                            save_state(st)
                            log_event("TRAIL_SL_RESTORED", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])

                    elif improve >= step:
                        # Cancel/replace. Do NOT place a new SL unless cancel is confirmed.
                        with suppress(Exception):
                            cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = check_order_status(symbol, sl_now)
                        st_c = str((od_c or {}).get("status", "")).upper()
                        if st_c not in ("CANCELED", "REJECTED", "EXPIRED"):
                            pos["trail_last_update_s"] = now_s
                            st["position"] = pos
                            save_state(st)
                            log_event("TRAIL_SL_CANCEL_NOT_CONFIRMED", mode="live", order_id_sl=sl_now, status=st_c or "UNKNOWN")
                        else:
                            try:
                                sl_new = place_order_raw({
                                    "symbol": symbol,
                                    "side": exit_side,
                                    "type": "STOP_LOSS_LIMIT",
                                    "quantity": fmt_qty(trail_qty),
                                    "price": sl_price_s,
                                    "stopPrice": sl_stop_s,
                                    "timeInForce": "GTC",
                                    "newClientOrderId": f"EX_SL_TR_{int(time.time())}",
                                })
                            except Exception as e:
                                log_event("TRAIL_SL_UPDATE_ERROR", error=str(e), mode="live")
                            else:
                                pos["orders"]["sl"] = _oid_int(sl_new.get("orderId"))
                                pos["trail_sl_price"] = float(sl_stop_s)
                                pos["trail_last_update_s"] = now_s
                                st["position"] = pos
                                save_state(st)
                                log_event("TRAIL_SL_UPDATED", mode="live", new_sl_order_id=sl_new.get("orderId"), trail_stop=pos["trail_sl_price"])

            # advance last_update even if no price, to avoid tight loop
            pos["trail_last_update_s"] = now_s
            st["position"] = pos
            save_state(st)

    # SL filled -> close slot
    sl_id2 = int((pos.get("orders") or {}).get("sl") or 0)
    if sl_id2 and not pos.get("sl_done"):
        poll_due = now_s >= float(pos.get("sl_status_next_s") or 0.0)

        # Do not gate FILLED detection on openOrders/open_ids; throttle via sl_status_next_s
        if poll_due or (not orders):
            pos["sl_status_next_s"] = now_s + float(ENV["LIVE_STATUS_POLL_EVERY"])

            if _status_is_filled(sl_id2):
                pos["sl_done"] = True
                st["position"] = pos
                save_state(st)
                log_event("SL_DONE", mode="live", order_id_sl=sl_id2)
                send_webhook({"event": "SL_DONE", "mode": "live", "symbol": symbol})

                # cancel any remaining exits (best-effort) to avoid orphan orders
                if tp1_id:
                    with suppress(Exception):
                        cancel_order(symbol, tp1_id)
                if tp2_id:
                    with suppress(Exception):
                        cancel_order(symbol, tp2_id)

                sl_prev3 = int((pos.get("orders") or {}).get("sl_prev") or 0)
                if sl_prev3:
                    with suppress(Exception):
                        cancel_order(symbol, sl_prev3)

                _close_slot("SL")
            else:
                miss = pos.setdefault("missing_not_filled", {})
                key = f"sl:{sl_id2}"
                if not miss.get(key):
                    miss[key] = iso_utc()
                    st["position"] = pos
                    save_state(st)
                    log_event("SL_NOT_FILLED", mode="live", order_id_sl=sl_id2)


# ===================== State =====================

def get_mid_price(symbol: str) -> float:
    j = binance_public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    bid = float(j["bidPrice"])
    ask = float(j["askPrice"])
    return (bid + ask) / 2.0

def _read_last_close_prices_from_agg_csv(path: str, n_rows: int) -> list[float]:
    """
    Read last N rows from aggregated.csv and extract ClosePrice (fallback to AvgPrice).
    CSV header expected (example): Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice
    """
    if n_rows <= 0:
        return []
    # Read tail lines (avoid loading full file)
    lines = read_tail_lines(path, n_rows + 5)  # header + a few extra
    if not lines:
        return []
    # Find header
    header_idx = None
    for i, ln in enumerate(lines):
        if "Timestamp" in ln and "ClosePrice" in ln:
            header_idx = i
            break
    # If no header in tail, assume fixed order and parse from all lines
    data_lines = lines[header_idx + 1:] if header_idx is not None else lines
    closes: list[float] = []
    for ln in data_lines:
        ln = ln.strip()
        if not ln or ln.startswith("Timestamp"):
            continue
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 7:
            continue
        # try ClosePrice last col (idx 7) if present
        v = None
        if len(parts) >= 8:
            v = parts[7]
        else:
            v = parts[6]  # AvgPrice
        try:
            closes.append(float(v))
        except Exception:
            continue
    return closes


def _find_last_fractal_swing(series: list[float], lr: int, kind: str) -> Optional[float]:
    """
    Find last swing point in series using simple fractal:
      low:  x[i] < x[i-1..i-lr] and x[i] < x[i+1..i+lr]
      high: x[i] > x[i-1..i-lr] and x[i] > x[i+1..i+lr]
    Returns swing price or None.
    """
    if lr < 1:
        lr = 1
    if len(series) < (2 * lr + 1):
        return None
    # scan from right to left so we get the most recent confirmed swing
    # last index we can test is len(series)-lr-1
    for i in range(len(series) - lr - 1, lr - 1, -1):
        x = series[i]
        left = series[i - lr:i]
        right = series[i + 1:i + 1 + lr]
        if len(left) < lr or len(right) < lr:
            continue
        if kind == "low":
            if all(x < v for v in left) and all(x < v for v in right):
                return x
        else:
            if all(x > v for v in left) and all(x > v for v in right):
                return x
    return None


def _trail_desired_stop_from_agg(pos: dict) -> Optional[float]:
    """
    Compute desired trailing stop based on last swing from aggregated.csv ClosePrice.
    LONG: stop = swing_low - buffer
    SHORT: stop = swing_high + buffer
    """
    path = ENV.get("AGG_CSV") or ""
    if not path:
        return None
    lookback = int(ENV.get("TRAIL_SWING_LOOKBACK") or 0)
    lr = int(ENV.get("TRAIL_SWING_LR") or 2)
    buf = float(ENV.get("TRAIL_SWING_BUFFER_USD") or 0.0)
    closes = _read_last_close_prices_from_agg_csv(path, lookback)
    if not closes:
        return None
    kind = "low" if pos.get("side") == "LONG" else "high"
    swing = _find_last_fractal_swing(closes, lr=lr, kind=kind)
    if swing is None:
        return None
    if pos.get("side") == "LONG":
        return float(swing - buf)
    else:
        return float(swing + buf)

def get_usdt_usdc_k() -> float:
    mid_usdt = get_mid_price("BTCUSDT")
    mid_usdc = get_mid_price("BTCUSDC")
    return mid_usdc / mid_usdt

def binance_sanity_check() -> None:
    """Fast connectivity + auth check.

    - public ping/time via /api/v3
    - signed check:
        - spot  : GET /api/v3/account
        - margin: GET /sapi/v1/margin/account
    """
    # public
    binance_public_get("/api/v3/ping")
    srv_time = binance_public_get("/api/v3/time")
    global BINANCE_TIME_OFFSET_MS
    try:
        server_ms = int(srv_time.get("serverTime", 0) or 0)
        local_ms = int(time.time() * 1000)
        BINANCE_TIME_OFFSET_MS = (server_ms - local_ms) if server_ms else 0
    except Exception:
        BINANCE_TIME_OFFSET_MS = 0
    log_event("BINANCE_PUBLIC_OK", server_time=srv_time.get("serverTime"), time_offset_ms=BINANCE_TIME_OFFSET_MS)

    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()
    if mode == "margin":
        acc = _binance_signed_request("GET", "/sapi/v1/margin/account", {"recvWindow": ENV["RECV_WINDOW"]})
        # Small, stable fields to log (avoid dumping huge balances)
        log_event("BINANCE_SIGNED_OK", mode="margin", userAssets=len(acc.get("userAssets", [])))
    else:
        acc = _binance_signed_request("GET", "/api/v3/account", {"recvWindow": ENV["RECV_WINDOW"]})
        log_event("BINANCE_SIGNED_OK", mode="spot", balances=len(acc.get("balances", [])))



def sync_from_binance(st: Dict[str, Any]) -> None:
    """Best-effort reconciliation of executor state with Binance.

    Why:
      - container/VPS restart with state mismatch
      - manual SL/TP placement/cancel in UI
      - key rotation / partial state reset

    Strategy (minimal, safe):
      - Look at *tagged* openOrders (clientOrderId starts with 'EX_')
      - If we see tagged orders and local state is empty -> create/attach a live position shell
      - If local state says OPEN/PENDING but Binance has no tagged orders -> clear slot (assume closed/canceled)

    This avoids accidental double-opening after restarts.
    """
    if ENV["DRY"]:
        return
    if str(ENV.get("TRADE_MODE", "spot")).strip().lower() != "margin":
        return

    try:
        orders = open_orders(ENV["SYMBOL"])
    except Exception as e:
        log_event("SYNC_ERR_OPENORDERS", error=str(e))
        return

    tagged = [o for o in (orders or []) if str(o.get("clientOrderId", "")).startswith("EX_")]
    pos = st.get("position") or {}

    if not tagged:
        # IMPORTANT: OPEN_FILLED може легітимно мати 0 openOrders:
        # entry вже FILLED, а exits ще не поставились/впали і чекають retry.
        # Не можна чистити слот лише через openOrders==0, інакше "забудемо" реальну позицію.
        if pos.get("mode") == "live" and pos.get("status") == "OPEN_FILLED":
            log_event("SYNC_SKIP_CLEAR_OPEN_FILLED_NO_ORDERS", prev_status=pos.get("status"), order_id=pos.get("order_id"))
            return

        # For PENDING/OPEN: do NOT clear slot unless entry is confirmed canceled/unfilled.
        if pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN"):
            oid = int(pos.get("order_id") or 0)
            if not oid:
                log_event("SYNC_KEEP_NO_TAGGED_NO_ENTRY_ID", prev_status=pos.get("status"))
                return
            od = None
            with suppress(Exception):
                od = check_order_status(ENV["SYMBOL"], oid)
            st_o = str((od or {}).get("status", "")).upper()
            exq = float((od or {}).get("executedQty") or 0.0)
            if st_o not in ("CANCELED", "REJECTED", "EXPIRED") or exq > 0.0:
                log_event("SYNC_KEEP_NO_TAGGED_ENTRY_NOT_CANCELED",
                          prev_status=pos.get("status"), order_id=oid,
                          status=st_o or "UNKNOWN", executedQty=exq)
                return
            log_event("SYNC_CLEAR_NO_TAGGED_CONFIRMED_CANCELED", prev_status=pos.get("status"), order_id=oid)
            st["position"] = None
            st["lock_until"] = 0.0
            save_state(st)
        return

    # We have tagged orders. If we already have a live position, keep it (but you can extend later).
    if pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED"):
        return

    # Rebuild a minimal position shell from open orders
    def _find(prefix: str) -> Optional[Dict[str, Any]]:
        for o in tagged:
            if str(o.get("clientOrderId", "")).startswith(prefix):
                return o
        return None

    o_en = _find("EX_EN_")
    o_tp1 = _find("EX_TP1_")
    o_tp2 = _find("EX_TP2_")
    o_sl = _find("EX_SL_") or _find("EX_SL_BE_")

    # Infer side from exit orders (SELL exits => LONG, BUY exits => SHORT)
    exit_side = None
    for o in (o_tp1, o_tp2, o_sl):
        if o and o.get("side") in ("SELL", "BUY"):
            exit_side = o.get("side")
            break
    side_txt = "LONG" if exit_side == "SELL" else "SHORT" if exit_side == "BUY" else "UNKNOWN"

    # Basic prices if available
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
        "opened_at": iso_utc(),
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
    save_state(st)
    log_event("SYNC_ATTACHED", side=side_txt, tagged_orders=len(tagged))

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
def handle_open_filled_exits_retry(st: dict) -> None:
    """Retry exits placement for a live position stuck in OPEN_FILLED without exits."""
    pos = st.get("position") or {}
    if pos.get("mode") != "live" or pos.get("status") != "OPEN_FILLED":
        return
    if pos.get("orders") or not pos.get("prices"):
        return

    now = _now_s()
    next_try = float(pos.get("exits_next_try_s") or 0.0)
    if next_try and now < next_try:
        return

    tries = int(pos.get("exits_tries") or 0) + 1
    pos["exits_tries"] = tries
    pos.setdefault("exits_first_fail_s", now)
    pos["exits_next_try_s"] = now + float(ENV["EXITS_RETRY_EVERY_SEC"])
    st["position"] = pos
    save_state(st)

    try:
        validated = validate_exit_plan(ENV["SYMBOL"], pos["side"], float(pos["qty"]), pos["prices"])
        pos["qty"] = float(validated["qty_total_r"])
        pos["prices"] = validated["prices"]
        pos["orders"] = place_exits_v15(ENV["SYMBOL"], pos["side"], float(pos["qty"]), pos["prices"])
        pos["status"] = "OPEN"
        st["position"] = pos
        save_state(st)
        log_event("EXITS_PLACED_V15", mode="live", orders=pos["orders"], attempt=tries)
        send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": pos["orders"], "prices": pos["prices"], "attempt": tries})
        return
    except Exception as ee:
        log_event("EXITS_RETRY_FAIL", error=str(ee), attempt=tries, symbol=ENV["SYMBOL"])

    if not ENV.get("FAILSAFE_FLATTEN", False):
        return
    max_tries = int(ENV.get("FAILSAFE_EXITS_MAX_TRIES") or 0)
    grace = float(ENV.get("FAILSAFE_EXITS_GRACE_SEC") or 0.0)
    first_fail_s = float(pos.get("exits_first_fail_s") or now)
    if max_tries and tries >= max_tries and (now - first_fail_s) >= grace:
        with suppress(Exception):
            flatten_market(ENV["SYMBOL"], pos.get("side"), float(pos.get("qty") or 0.0), client_id=f"EX_FLAT_{int(time.time())}")
        _clear_position_slot(st, "FAILSAFE_FLATTEN", tries=tries)
def main() -> None:
    st = load_state()

    # Seed dedup keys with tail so we don't replay old PEAKs after fresh install

    # Always bootstrap seen_keys on start (safe by default)
    tail = read_tail_lines(ENV["DELTASCOUT_LOG"], ENV["TAIL_LINES"])
    bootstrap_seen_keys_from_tail(st, tail)


    log_event("BOOT", dry=ENV["DRY"], symbol=ENV["SYMBOL"])
    if not ENV["DRY"]:
        with suppress(Exception):
            sync_from_binance(st)

    # Optional: one-shot connectivity/auth check (useful before going live)
    if not ENV["DRY"] and ENV.get("LIVE_VALIDATE_ONLY"):
        try:
            binance_sanity_check()
            log_event("LIVE_VALIDATE_ONLY_DONE")
        except Exception as e:
            log_event("LIVE_VALIDATE_ONLY_FAIL", error=str(e))
            raise
        return

    last_manage_s = 0.0
    agg_ok_prev: Optional[bool] = None



    while True:
        time.sleep(ENV["POLL_SEC"])
        st = load_state()  # <-- critical: pick up external state changes
        posi = st.get("position") or {}
        if posi and posi.get("mode") == "live" and (not ENV["DRY"]) and str(posi.get("status", "")).upper() in (
            "ENTRY_TIMEOUT_CANCELED",
            "ENTRY_TIMEOUT",
            "ENTRY_CANCELED",
            "ENTRY_REJECTED",
            "ENTRY_REJECT",
            "ENTRY_EXPIRED",
        ):
            st["last_entry_abort_ts"] = iso_utc()
            st["position"] = None
            save_state(st)
            log_event("ENTRY_SLOT_CLEARED", prev_status=posi.get("status"))
            continue
        if posi.get("mode") == "live" and posi.get("status") == "PENDING" and not ENV["DRY"]:
            try:
                last_poll = float(posi.get("last_poll_s", 0.0))
                now_s = _now_s()
                if now_s - last_poll >= float(ENV["LIVE_STATUS_POLL_EVERY"]):
                    oid = int(posi.get("order_id") or 0)
                    if oid:
                        od = check_order_status(ENV["SYMBOL"], oid)
                        posi["last_poll_s"] = now_s
                        st["position"] = posi
                        save_state(st)

                        stt = str(od.get("status", "")).upper()
                        if stt in ("FILLED",):
                            # ENTRY filled -> place exits V1.5 once
                            posi["status"] = "OPEN_FILLED"
                            posi["filled_at"] = iso_utc()
                            posi["executedQty"] = od.get("executedQty")
                            exq = float(od.get("executedQty") or 0.0)
                            if exq > 0.0:
                                posi["qty"] = float(round_qty(exq))
                            avgp = _avg_fill_price(od)
                            if avgp:
                                posi["entry_actual"] = float(fmt_price(avgp))

                            posi["cummulativeQuoteQty"] = od.get("cummulativeQuoteQty")
                            st["position"] = posi
                            save_state(st)
                            log_event("FILLED", mode="live", order_id=oid, executedQty=od.get("executedQty"))
                            send_webhook({"event": "FILLED", "mode": "live", "order_id": oid, "order": od})

                            # Place TP1/TP2/SL (no OCO) right after fill confirmation
                            if not posi.get("orders") and posi.get("prices"):
                                try:
                                    validated = validate_exit_plan(ENV["SYMBOL"], posi["side"], float(posi["qty"]), posi["prices"])
                                    # Ensure we persist rounded qty/prices for consistency and clearer post-mortem
                                    posi["qty"] = float(validated["qty_total_r"])
                                    posi["prices"] = validated["prices"]
                                    posi["orders"] = place_exits_v15(ENV["SYMBOL"], posi["side"], float(posi["qty"]), posi["prices"])
                                    posi["status"] = "OPEN"
                                    st["position"] = posi
                                    save_state(st)
                                    log_event("EXITS_PLACED_V15", mode="live", orders=posi["orders"])
                                    send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": posi["orders"], "prices": posi["prices"]})
                                except Exception as ee:
                                    log_event("EXITS_PLACE_ERROR", error=str(ee), symbol=ENV["SYMBOL"], side=posi.get("side"), qty=posi.get("qty"), prices=posi.get("prices"))

                        elif stt in ("CANCELED", "REJECTED", "EXPIRED"):
                            _clear_position_slot(st, f"ENTRY_{stt}", order_id=oid, status=stt)
                            log_event("ENTRY_DONE", mode="live", status=stt, order_id=oid)
                            continue
                # Timeout cancel
                opened_s = float(posi.get("opened_s") or 0.0)
                if not opened_s:
                    opened_s = now_s
                    posi["opened_s"] = opened_s
                    st["position"] = posi
                    save_state(st)   
                else:
                    posi["opened_s"] = opened_s
                now = _now_s()
                if now - opened_s >= float(ENV["LIVE_ENTRY_TIMEOUT_SEC"]):
                # throttle timeout actions to avoid spamming Binance API
                    next_act_s = float(posi.get("planb_next_action_s") or 0.0)
                    if next_act_s and now < next_act_s:
                        continue
                    oid = int(posi.get("order_id") or 0)

                    if oid and posi.get("status") == "PENDING":
                        # Plan B: timeout -> cancel LIMIT and fall back to MARKET (unless ENTRY_MODE=LIMIT_ONLY).
                        od_t = check_order_status(ENV["SYMBOL"], oid)
                        exq_t = float(od_t.get("executedQty") or 0.0)

                        def _try_place_exits_now() -> None:
                            # Best-effort immediate exits placement (reduces naked exposure window).
                            if posi.get("orders") or not posi.get("prices"):
                                return
                            try:
                                validated = validate_exit_plan(ENV["SYMBOL"], posi["side"], float(posi["qty"]), posi["prices"])
                                posi["qty"] = float(validated["qty_total_r"])
                                posi["prices"] = validated["prices"]
                                posi["orders"] = place_exits_v15(ENV["SYMBOL"], posi["side"], float(posi["qty"]), posi["prices"])
                                posi["status"] = "OPEN"
                                st["position"] = posi
                                save_state(st)
                                log_event("EXITS_PLACED_V15", mode="live", orders=posi["orders"])
                                send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": posi["orders"], "prices": posi["prices"]})
                            except Exception as ee:
                                # Keep OPEN_FILLED; retry logic in main loop will handle.
                                st["position"] = posi
                                save_state(st)
                                log_event("EXITS_PLACE_ERROR", error=str(ee), symbol=ENV["SYMBOL"], side=posi.get("side"), qty=posi.get("qty"))

                        if exq_t > 0.0:
                            # Order partially/fully filled: keep the filled part and proceed to exits.
                            with suppress(Exception):
                                cancel_order(ENV["SYMBOL"], oid)
                            posi["status"] = "OPEN_FILLED"
                            posi["filled_at"] = iso_utc()
                            posi["executedQty"] = od_t.get("executedQty")
                            posi["cummulativeQuoteQty"] = od_t.get("cummulativeQuoteQty") or od_t.get("cumulativeQuoteQty")
                            posi["qty"] = float(round_qty(exq_t))
                            avgp_t = _avg_fill_price(od_t)
                            if avgp_t:
                                posi["entry_actual"] = float(fmt_price(avgp_t))
                            st["position"] = posi
                            save_state(st)
                            log_event("ENTRY_TIMEOUT_PARTIAL_FILLED", mode="live", order_id=oid, executedQty=exq_t)
                            send_webhook({"event": "ENTRY_TIMEOUT_PARTIAL_FILLED", "mode": "live", "order_id": oid, "executedQty": exq_t})
                            _try_place_exits_now()
                        else:
                            # Cancel LIMIT (best-effort)
                            with suppress(Exception):
                                cancel_order(ENV["SYMBOL"], oid)

                            # Re-check once after cancel to catch a late fill (avoid double-entry).
                            od_after = None
                            with suppress(Exception):
                                od_after = check_order_status(ENV["SYMBOL"], oid)
                            if od_after:
                                exq_after = float(od_after.get("executedQty") or 0.0)
                                st_after = str(od_after.get("status", "")).upper()
                                if st_after == "FILLED" or exq_after > 0.0:
                                    posi["status"] = "OPEN_FILLED"
                                    posi["filled_at"] = iso_utc()
                                    posi["executedQty"] = od_after.get("executedQty")
                                    posi["cummulativeQuoteQty"] = od_after.get("cummulativeQuoteQty") or od_after.get("cumulativeQuoteQty")
                                    posi["qty"] = float(round_qty(exq_after))
                                    avgp_a = _avg_fill_price(od_after)
                                    if avgp_a:
                                        posi["entry_actual"] = float(fmt_price(avgp_a))
                                    st["position"] = posi
                                    save_state(st)
                                    log_event("ENTRY_TIMEOUT_LATE_FILL", mode="live", order_id=oid, executedQty=exq_after, status=st_after)
                                    send_webhook({"event": "ENTRY_TIMEOUT_LATE_FILL", "mode": "live", "order_id": oid, "executedQty": exq_after, "status": st_after})
                                    _try_place_exits_now()
                                    continue
                            # Only place MARKET when LIMIT is confirmed canceled/expired/rejected; otherwise wait.
                            st_after = str((od_after or {}).get("status", "")).upper()
                            if st_after not in ("CANCELED", "EXPIRED", "REJECTED"):
                                posi["planb_next_action_s"] = now + float(ENV["LIVE_STATUS_POLL_EVERY"])
                                st["position"] = posi
                                save_state(st)
                                log_event("ENTRY_TIMEOUT_WAIT_CANCEL", mode="live", order_id=oid, status=st_after or "UNKNOWN")
                                continue

                            entry_mode = str(ENV.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper()
                            if entry_mode == "LIMIT_ONLY":
                                log_event("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="NONE")
                                send_webhook({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "NONE"})
                                _clear_position_slot(st, "ENTRY_TIMEOUT", order_id=oid, fallback="NONE")
                            else:
                                entry_side = "BUY" if posi.get("side") == "LONG" else "SELL"

                                px_exec = None
                                try:
                                    px_exec = _planb_exec_price(ENV["SYMBOL"], entry_side)
                                except Exception as ee:
                                    log_event("PLANB_PRICE_ERROR", error=str(ee), order_id=oid)

                                if px_exec is None:
                                    if ENV.get("PLANB_REQUIRE_PRICE", True):
                                        log_event("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="ABORT_NO_PRICE")
                                        send_webhook({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "ABORT_NO_PRICE"})
                                        _clear_position_slot(st, "ENTRY_TIMEOUT_ABORT", order_id=oid, fallback="ABORT_NO_PRICE")
                                        continue

                                if px_exec is not None:
                                    ok, why, info = _planb_market_allowed(posi, float(px_exec))
                                    if not ok:
                                        log_event("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback=f"ABORT_{why}", **info)
                                        send_webhook({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": f"ABORT_{why}", "info": info})
                                        _clear_position_slot(st, "ENTRY_TIMEOUT_ABORT", order_id=oid, fallback=f"ABORT_{why}", **info)
                                        continue

                                try:
                                    mkt = place_spot_market(ENV["SYMBOL"], entry_side, float(posi.get("qty") or 0.0), client_id=f"EX_EN_MKT_{int(time.time())}")
                                except Exception as ee:
                                    log_event("ENTRY_TIMEOUT_MARKET_ERROR", error=str(ee), order_id=oid)
                                    send_webhook({"event": "ENTRY_TIMEOUT_MARKET_ERROR", "order_id": oid, "error": str(ee)})
                                    _clear_position_slot(st, "ENTRY_TIMEOUT_MARKET_ERROR", order_id=oid, error=str(ee))
                                else:
                                    oid2 = _oid_int(mkt.get("orderId"))
                                    if not oid2:
                                        log_event("ENTRY_TIMEOUT_MARKET_NO_OID", order_id=oid)
                                        send_webhook({"event": "ENTRY_TIMEOUT_MARKET_NO_OID", "order_id": oid})
                                        _clear_position_slot(st, "ENTRY_TIMEOUT_MARKET_NO_OID", order_id=oid)
                                    else:
                                        # Market should fill immediately, but confirm once.
                                        od2 = check_order_status(ENV["SYMBOL"], int(oid2))
                                        exq2 = float(od2.get("executedQty") or 0.0)
                                        posi["order_id"] = int(oid2)
                                        posi["client_id"] = f"EX_EN_MKT_{int(time.time())}"
                                        posi["opened_s"] = now
                                        posi["opened_at"] = iso_utc()
                                        posi["planb_next_action_s"] = now + float(ENV["LIVE_STATUS_POLL_EVERY"])
                                        if exq2 > 0.0:
                                            posi["status"] = "OPEN_FILLED"
                                            posi["filled_at"] = iso_utc()
                                            posi["qty"] = float(round_qty(exq2))
                                            avgp2 = _avg_fill_price(od2) or _avg_fill_price(mkt)
                                            if avgp2:
                                                posi["entry_actual"] = float(fmt_price(avgp2))
                                            st["position"] = posi
                                            save_state(st)
                                            _try_place_exits_now()
                                        else:
                                            # Unexpected: market not filled. Keep pending and let poll loop handle it.
                                            posi["status"] = "PENDING"
                                            st["position"] = posi
                                            save_state(st)

                                        log_event("ENTRY_TIMEOUT", mode="live", order_id=oid, fallback="MARKET", new_order_id=oid2)
                                        send_webhook({"event": "ENTRY_TIMEOUT", "mode": "live", "order_id": oid, "fallback": "MARKET", "new_order_id": oid2})
            except Exception as e:
                log_event("LIVE_POLL_ERROR", error=str(e))
        # 1) Always ingest new DeltaScout lines (so seen_keys advances even if other parts fail)
        tail = read_tail_lines(ENV["DELTASCOUT_LOG"], n=ENV["TAIL_LINES"])

        new_events: List[Tuple[str, Dict[str, Any]]] = []
        meta = st.setdefault("meta", {})
        seen_keys = meta.get("seen_keys", [])
        last_peak_ts_dt = _dt_utc(meta.get("last_peak_ts"))

        changed = False

        for ln in tail:
            ln = (ln or "").strip()
            if not ln:
                continue
            try:
                evt = json.loads(ln)
            except Exception:
                continue

            if evt.get("action") != "PEAK":
                continue

            k = stable_event_key(evt)
            if not k or k in seen_keys:
                continue

            dt = _dt_utc(evt.get("ts"))

            # Watermark filter: if this PEAK is not newer than what we've already seen,
            # mark it as seen but do NOT act on it.
            if dt is not None and last_peak_ts_dt is not None and dt <= last_peak_ts_dt:
                seen_keys.append(k)
                changed = True
                continue

            # Fresh PEAK
            new_events.append((k, evt))
            seen_keys.append(k)
            changed = True

            if dt is not None and (last_peak_ts_dt is None or dt > last_peak_ts_dt):
                last_peak_ts_dt = dt
                meta["last_peak_ts"] = dt.isoformat()

        if changed:
            meta["seen_keys"] = seen_keys[-int(ENV.get("SEEN_KEYS_MAX", 500)) :]
            save_state(st)


                # 2) Market data
        # Paper mode: keep monitoring aggregated.csv.
        # Live mode : do NOT read aggregated.csv in the main loop (only on PEAK for swing stop).
        df: Optional[pd.DataFrame] = None
        if ENV["DRY"]:
            df = load_df_sorted()
            ok = bool(df is not None and not df.empty)
            if ok:
                if agg_ok_prev is not True:
                    log_event("AGG_OK")
                    agg_ok_prev = True
                monitor_paper_position(st, df)
            else:
                if agg_ok_prev is not False:
                    log_event("AGG_READ_ERROR", error="empty_or_invalid_agg_csv")
                    agg_ok_prev = False

        # Live V1.5 management (TP1 -> SL to BE) — throttled
        if not ENV["DRY"]:
            pos_live = st.get("position") or {}
            if pos_live.get("mode") == "live" and pos_live.get("status") in ("OPEN", "OPEN_FILLED"):
                now_s = _now_s()
                if now_s - last_manage_s >= float(ENV["MANAGE_EVERY_SEC"]):
                    last_manage_s = now_s
                    # If entry filled but exits were not placed (or placement failed), retry.
                    with suppress(Exception):
                        handle_open_filled_exits_retry(st)             
                    try:
                        manage_v15_position(ENV["SYMBOL"], st)
                    except Exception as e:
                        log_event("LIVE_MANAGE_ERROR", error=str(e))

        if not new_events:
            continue

        # 3) Process new PEAK events
        for _, evt in new_events:
            # Safety: ignore very old PEAKs (e.g., after restarts / log replays)
            max_age = float(ENV.get("MAX_PEAK_AGE_SEC") or 0)
            if max_age > 0:
                dt_evt = _dt_utc(evt.get("ts"))
                if dt_evt is not None:
                    age = _now_s() - float(dt_evt.timestamp())
                    if age > max_age:
                        log_event("SKIP_PEAK", reason="stale_peak", age_sec=round(age, 3), evt_ts=str(evt.get("ts")))
                        continue
            if not ENV["DRY"]:
                with suppress(Exception):
                    sync_from_binance(st)

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
                    close_price_usdt = float(evt.get("price"))
                    entry_usdt = build_entry_price(kind, close_price_usdt)
                    side = "BUY" if kind == "long" else "SELL"
                    side_txt = "LONG" if side == "BUY" else "SHORT"                    # aggregated.csv is used ONLY here (to compute swing stop from the USDT feed)
                    df_local = load_df_sorted()
                    if df_local.empty:
                        log_event("SKIP_OPEN", reason="agg_unavailable")
                        continue

                    # locate candle index by event timestamp (in USDT feed)
                    ts = evt.get("ts")
                    i = len(df_local) - 1
                    try:
                        if ts:
                            _ts = ts
                            if isinstance(_ts, str) and _ts.endswith("Z"):
                                _ts = _ts[:-1] + "+00:00"
                            i = locate_index_by_ts(df_local, pd.to_datetime(_ts, utc=True).to_pydatetime())
                    except Exception:
                        i = len(df_local) - 1

                    sl_usdt = swing_stop_far(df_local, i, side, entry_usdt)
                    tps_usdt = compute_tps(entry_usdt, sl_usdt, side)
                    if len(tps_usdt) < 2:
                        log_event("SKIP_OPEN", reason="tps_not_ready", entry_usdt=entry_usdt, sl_usdt=sl_usdt, tps=tps_usdt)
                        continue
                    tp1_usdt, tp2_usdt = tps_usdt[0], tps_usdt[1]

                    
# --- USDT -> USDC conversion (k_entry fixed once per position) ---
                    k_entry = get_usdt_usdc_k()

                    # Convert prices, then apply *directional* rounding to keep logic stable.
                    tick = ENV["TICK_SIZE"]
                    close_usdc = float(close_price_usdt) * float(k_entry)

                    raw_entry = float(entry_usdt) * float(k_entry)
                    raw_sl = float(sl_usdt) * float(k_entry)
                    raw_tp1 = float(tp1_usdt) * float(k_entry)
                    raw_tp2 = float(tp2_usdt) * float(k_entry)

                    if kind == "long":
                        # entry must be >= close_usdc + 1 tick
                        entry = floor_to_step(raw_entry, tick)
                        min_entry = close_usdc + float(tick)
                        if entry < min_entry:
                            entry = ceil_to_step(min_entry, tick)

                        sl = floor_to_step(raw_sl, tick)
                        tp1 = floor_to_step(raw_tp1, tick)
                        tp2 = floor_to_step(raw_tp2, tick)
                    else:
                        # entry must be <= close_usdc - 1 tick
                        entry = ceil_to_step(raw_entry, tick)
                        max_entry = close_usdc - float(tick)
                        if entry > max_entry:
                            entry = floor_to_step(max_entry, tick)

                        sl = ceil_to_step(raw_sl, tick)
                        tp1 = ceil_to_step(raw_tp1, tick)
                        tp2 = ceil_to_step(raw_tp2, tick)

                    qty = notional_to_qty(entry, ENV["QTY_USD"])

                    if not validate_qty(qty, entry):
                        log_event("SKIP_OPEN", reason="qty_too_small", entry=entry, qty=qty, k_entry=k_entry)
                        continue

                    client_id = f"EX_EN_{int(time.time())}"
                    entry_mode = str(ENV.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper()
                    if entry_mode == "MARKET_ONLY":
                        order = place_spot_market(ENV["SYMBOL"], side, qty, client_id=client_id)
                        exq0 = float(order.get("executedQty") or 0.0)
                        status0 = "OPEN_FILLED" if exq0 > 0.0 else "PENDING"
                        avgp0 = _avg_fill_price(order)
                        entry_actual0 = float(fmt_price(avgp0)) if avgp0 else None
                    else:
                        order = place_spot_limit(ENV["SYMBOL"], side, qty, entry, client_id=client_id)
                        status0 = "PENDING"
                        entry_actual0 = None
                    st["position"] = {
                        "status": status0,
                        "mode": "live",
                        "opened_at": iso_utc(),
                        "opened_s": _now_s(),
                        "side": side_txt,
                        "qty": qty,
                        "entry": entry,
                        "order_id": _oid_int(order.get("orderId")) or order.get("orderId"),
                        "client_id": client_id,
                        "entry_mode": str(ENV.get("ENTRY_MODE", "LIMIT_THEN_MARKET")).strip().upper(),
                        "entry_actual": entry_actual0,
                        "k_entry": k_entry,
                        "prices": {"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2},
                        "src_evt": {
                            "ts": evt.get("ts"),
                            "kind": kind,
                            "price_usdt": close_price_usdt,
                            "entry_usdt": entry_usdt,
                            "sl_usdt": sl_usdt,
                            "tp1_usdt": tp1_usdt,
                            "tp2_usdt": tp2_usdt,
                        },
                    }
                    if status0 == "OPEN_FILLED":
                        pos0 = st.get("position") or {}
                        if (not pos0.get("orders")) and pos0.get("prices"):
                            try:
                                validated = validate_exit_plan(ENV["SYMBOL"], pos0["side"], float(pos0["qty"]), pos0["prices"])
                                pos0["qty"] = float(validated["qty_total_r"])
                                pos0["prices"] = validated["prices"]
                                pos0["orders"] = place_exits_v15(ENV["SYMBOL"], pos0["side"], float(pos0["qty"]), pos0["prices"])
                                pos0["status"] = "OPEN"
                                st["position"] = pos0
                                log_event("EXITS_PLACED_V15", mode="live", orders=pos0["orders"])
                                send_webhook({"event": "EXITS_PLACED_V15", "mode": "live", "symbol": ENV["SYMBOL"], "orders": pos0["orders"], "prices": pos0["prices"]})
                            except Exception as ee:
                                log_event("EXITS_PLACE_ERROR", error=str(ee), symbol=ENV["SYMBOL"], side=pos0.get("side"), qty=pos0.get("qty"), prices=pos0.get("prices"))
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
