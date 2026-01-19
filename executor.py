#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""executor.py
Executor — execution engine for DeltaScout PEAK signals.

Design goals
- Reads DeltaScout JSONL events from a shared log file (DELTASCOUT_LOG)
- Single-position mode: ignores new PEAK while a position is OPEN/PENDING
- Writes ONLY to its own state/log files (never appends to deltascout.log)
- Keeps executor log capped to LOG_MAX_LINES (default: 200)

Hardening (this patch)
- Strictly accepts only valid DeltaScout PEAK events
- Stable dedup key (action|ts|min|kind|rounded_price) instead of hashing raw lines
- Cooldown window after CLOSE
- Position lock right after OPEN (protects against duplicate opens on restart/race)
- Keeps last_closed in state while freeing position slot (position=None)
- Reads deltascout log by tail (TAIL_LINES) without loading full file

"""
from __future__ import annotations
import os
import json
import time
import math
import atexit
import signal
from collections import deque
from contextlib import suppress
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from executor_mod.state_store import load_state, save_state, has_open_position, in_cooldown, locked
from executor_mod import baseline_policy
from executor_mod.notifications import log_event, send_webhook
from executor_mod.event_dedup import stable_event_key, dedup_fingerprint, bootstrap_seen_keys_from_tail
from executor_mod import margin_guard 
import executor_mod.trail as trail
import executor_mod.invariants as invariants
import executor_mod.binance_api as binance_api
import executor_mod.event_dedup as event_dedup
import executor_mod.risk_math as risk_math
import executor_mod.market_data as market_data
import executor_mod.exits_flow as exits_flow
import executor_mod.exit_safety as exit_safety
from executor_mod.exchange_snapshot import get_snapshot, refresh_snapshot
from executor_mod import price_snapshot
from executor_mod import reporting
from executor_mod.risk_math import (
    floor_to_step,
    ceil_to_step,
    round_nearest_to_step,
    _decimals_from_step,
    fmt_price,
    fmt_qty,
    round_qty,
)
import pandas as pd


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
"SYMBOL": _get_str("SYMBOL", "BTCUSDC").strip().upper(),
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

# Binance
"BINANCE_BASE_URL": os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
"BINANCE_API_KEY": os.getenv("BINANCE_API_KEY", ""),
"BINANCE_API_SECRET": os.getenv("BINANCE_API_SECRET", ""),
"BINANCE_DEBUG_PARAMS": _get_str("BINANCE_DEBUG_PARAMS", "0"),
"BINANCE_DEBUG_BALANCE_MIN_SEC": _get_int("BINANCE_DEBUG_BALANCE_MIN_SEC", 30),

# Trading account mode
"TRADE_MODE": os.getenv("TRADE_MODE", "spot"),  # spot | margin
"RECV_WINDOW": _get_int("RECV_WINDOW", 5000),

# Margin-specific (only used when TRADE_MODE=margin)
"MARGIN_ISOLATED": os.getenv("MARGIN_ISOLATED", "FALSE"),  # "TRUE" / "FALSE"
"MARGIN_SIDE_EFFECT": os.getenv("MARGIN_SIDE_EFFECT", "AUTO_BORROW_REPAY"),
"MARGIN_AUTO_REPAY_AT_CANCEL": _get_bool("MARGIN_AUTO_REPAY_AT_CANCEL", False),
"MARGIN_BORROW_MODE": _get_str("MARGIN_BORROW_MODE", "manual"),  # manual | auto

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
"SL_WATCHDOG_GRACE_SEC": _get_int("SL_WATCHDOG_GRACE_SEC", 3),
"SL_WATCHDOG_RETRY_SEC": _get_int("SL_WATCHDOG_RETRY_SEC", 5),
"TRAIL_ACTIVATE_AFTER_TP2": _get_bool("TRAIL_ACTIVATE_AFTER_TP2", True),
"TRAIL_STEP_USD": _get_float("TRAIL_STEP_USD", 20.0),
"TRAIL_UPDATE_EVERY_SEC": _get_int("TRAIL_UPDATE_EVERY_SEC", 20),
"SL_LIMIT_GAP_TICKS": _get_int("SL_LIMIT_GAP_TICKS", 2),  # gap ticks for STOP_LOSS_LIMIT limit price vs stopPrice
# trailing source: "AGG" (aggregated.csv) or "BINANCE" (bookTicker mid)
"TRAIL_SOURCE": os.getenv("TRAIL_SOURCE", "AGG").strip().upper(),
"TRAIL_CONFIRM_BUFFER_USD": _get_float("TRAIL_CONFIRM_BUFFER_USD", 0.0),
# swing detection uses LowPrice (LONG) / HiPrice (SHORT) from aggregated.csv v2;
# trail_wait_confirm uses bar ClosePrice for confirmation.
"TRAIL_SWING_LOOKBACK": _get_int("TRAIL_SWING_LOOKBACK", 240),   # rows
"TRAIL_SWING_LR": _get_int("TRAIL_SWING_LR", 2),                 # fractal L/R
"TRAIL_SWING_BUFFER_USD": _get_float("TRAIL_SWING_BUFFER_USD", 15.0),
# invariants (detector-only)
"INVAR_ENABLED": _get_bool("INVAR_ENABLED", 1),
"INVAR_EVERY_SEC": _get_int("INVAR_EVERY_SEC", 20),
"INVAR_THROTTLE_SEC": _get_int("INVAR_THROTTLE_SEC", 600),
"INVAR_GRACE_SEC": _get_int("INVAR_GRACE_SEC", 15),
"INVAR_FEED_STALE_SEC": _get_int("INVAR_FEED_STALE_SEC", 180),
"INVAR_KILL_ON_DEBT": _get_bool("INVAR_KILL_ON_DEBT", False),
"INVAR_PERSIST": _get_bool("INVAR_PERSIST", False),
"I13_GRACE_SEC": _get_int("I13_GRACE_SEC", 300),
"I13_ESCALATE_SEC": _get_int("I13_ESCALATE_SEC", 180),
"I13_EXCHANGE_CHECK": _get_bool("I13_EXCHANGE_CHECK", True),
"I13_EXCHANGE_MIN_INTERVAL_SEC": _get_int("I13_EXCHANGE_MIN_INTERVAL_SEC", 60),
"I13_CLEAR_STATE_ON_EXCHANGE_CLEAR": _get_bool("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR", False),
"MARGIN_DEBT_EPS": _get_float("MARGIN_DEBT_EPS", 0.0),
"PREFLIGHT_EXPECT_QUOTE": os.getenv("PREFLIGHT_EXPECT_QUOTE", "").strip().upper(),
"ORPHAN_CANCEL_EVERY_SEC": _get_int("ORPHAN_CANCEL_EVERY_SEC", 30),
"SEEN_KEYS_MAX": _get_int("SEEN_KEYS_MAX", 500),
"RECON_THROTTLE_SEC": _get_int("RECON_THROTTLE_SEC", 600),
"SNAPSHOT_MIN_SEC": _get_int("SNAPSHOT_MIN_SEC", 5),  # min interval between snapshot refreshes
"PRICE_SNAPSHOT_MIN_SEC": _get_int("PRICE_SNAPSHOT_MIN_SEC", 2),  # min interval between price snapshot refreshes
"SYNC_BINANCE_THROTTLE_SEC": _get_int("SYNC_BINANCE_THROTTLE_SEC", 300),  # sync_from_binance throttle
}


# ===================== Time/IO helpers =====================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or now_utc()).isoformat()

def _split_symbol_guess(symbol: str) -> Tuple[str, str]:
    """
    Best-effort split like BTCUSDC -> (BTC, USDC).
    Uses PREFLIGHT_EXPECT_QUOTE if set, otherwise common quote suffixes.
    """
    s = (symbol or "").strip().upper()
    if not s:
        return ("", "")
    exp = (ENV.get("PREFLIGHT_EXPECT_QUOTE") or "").strip().upper()
    if exp and s.endswith(exp) and len(s) > len(exp):
        return (s[:-len(exp)], exp)
    for q in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "BNB", "EUR", "TRY"):
        if s.endswith(q) and len(s) > len(q):
            return (s[:-len(q)], q)
    # fallback: unknown quote
    return (s, "")


def _validate_trade_mode() -> str:
    mode = str(ENV.get("TRADE_MODE", "")).strip().lower()
    if mode not in ("spot", "margin"):
        raise RuntimeError("unsupported mode removed; use TRADE_MODE=spot or TRADE_MODE=margin")
    ENV["TRADE_MODE"] = mode
    return mode

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

def _exchange_position_exists(symbol: str) -> Optional[bool]:
    """
    Return:
      True  -> exchange shows a non-zero base exposure OR margin borrowed/interest
      False -> exchange shows clearly no exposure and no debt
      None  -> cannot determine (missing API function / unexpected payload)
    """
    mode = str(ENV.get("TRADE_MODE", "spot")).strip().lower()
    base, _quote = _split_symbol_guess(symbol)
    if not base:
        return None
    eps_qty = max(float(ENV.get("MIN_QTY", 0.0) or 0.0), 0.0)
    # for safety, treat tiny dust as "no position"
    eps_qty = max(eps_qty, 1e-12)
    debt_eps = float(ENV.get("MARGIN_DEBT_EPS") or 0.0)

    def _asset_has_exposure_margin(a: Dict[str, Any]) -> bool:
        # Binance margin payload often contains: free, locked, borrowed, interest, netAsset
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

    # --- margin mode ---
    if mode == "margin":
        # try common function names in our wrapper
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
                # check base exposure and/or debt on base
                for a in assets:
                    if not isinstance(a, dict):
                        continue
                    if str(a.get("asset", "")).upper() == base:
                        return True if _asset_has_exposure_margin(a) else False
                # base not present -> can't be sure
                return None
            except Exception:
                return None
        return None

    # --- spot mode ---
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

def _as_env_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "y", "on")

def _preflight_margin_cross_usdc() -> None:
    trade_mode = str(ENV.get("TRADE_MODE", "") or "").strip().lower()
    is_isolated = _as_env_bool(ENV.get("MARGIN_ISOLATED"))
    symbol = str(ENV.get("SYMBOL", "") or "").strip().upper()
    expect_quote = str(ENV.get("PREFLIGHT_EXPECT_QUOTE", "") or "").strip().upper()

    issues = []
    if trade_mode != "margin":
        issues.append("TRADE_MODE must be 'margin'")
    if is_isolated:
        issues.append("MARGIN_ISOLATED must be FALSE (cross)")
    if expect_quote and not symbol.endswith(expect_quote):
        issues.append(f"SYMBOL must end with {expect_quote} (quote asset)")

    if not issues:
        return

    details = {
        "issues": issues,
        "trade_mode": trade_mode,
        "margin_isolated": ENV.get("MARGIN_ISOLATED"),
        "symbol": symbol,
        "expect_quote": expect_quote,
    }
    log_event("PREFLIGHT_WARN", **details)
    with suppress(Exception):
        send_webhook({"event": "PREFLIGHT_WARN", **details})

# Wire runtime dependencies for event_dedup (keeps call sites unchanged).
event_dedup.configure(ENV, iso_utc=iso_utc, save_state=save_state, log_event=log_event)
market_data.configure(ENV)

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

# Configure trail helper module (inject ENV and file tail reader)
# Configure margin guard hooks (future margin support; safe no-op by default)
with suppress(Exception):
    margin_guard.configure(ENV, log_event, api=binance_api)
trail.configure(ENV, read_tail_lines, log_event)

def _now_s() -> float:
    return time.time()

# Configure invariants (detector-only; disabled by default)
with suppress(Exception):
    invariants.configure(
        ENV,
        log_event_fn=log_event,
        send_webhook_fn=send_webhook,
        now_fn=_now_s,
        save_state_fn=save_state,
    )
with suppress(Exception):
    margin_guard.configure(ENV, log_event, api=binance_api)

# ===================== DeltaScout event normalization / dedup =====================
# (moved to executor_mod.event_dedup)

# ===================== Rounding / sizing =====================

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

# Backward-compatible name (kept for any leftover uses)


# Wire runtime dependencies for binance_api (keeps call sites unchanged).

risk_math.configure(ENV)
binance_api.configure(ENV, fmt_qty=risk_math.fmt_qty, fmt_price=risk_math.fmt_price, round_qty=risk_math.round_qty)
price_snapshot.configure(log_event_fn=log_event)


def build_entry_price(kind: str, close_price: float) -> float:
    """Entry price builder used for live.

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
    return market_data.load_df_sorted()

def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    return market_data.locate_index_by_ts(df, ts)


def latest_price(df: pd.DataFrame) -> float:
    return market_data.latest_price(df)

# ===================== Stop / TP ("far" stop logic) =====================

def swing_stop_far(df: pd.DataFrame, i: int, side: str, entry: float) -> float:
    """Return a stop that is FARTHER from entry (vs near).

    side: BUY for long, SELL for short

    - BUY: choose min(pct_sl, swing_low)
    - SELL: choose max(pct_sl, swing_high)
    - swings are based on LowPrice/HiPrice when available (v2), else fall back to price.
    """
    pct_sl = entry * (1 - ENV["SL_PCT"]) if side == "BUY" else entry * (1 + ENV["SL_PCT"])

    if i < 0 or i >= len(df):
        sl = pct_sl
    else:
        lookback = df.iloc[max(0, i - ENV["SWING_MINS"]): i + 1]
        if side == "BUY":
            swing_col = "LowPrice" if "LowPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.min())
            sl = min(pct_sl, swing)
        else:
            swing_col = "HiPrice" if "HiPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.max())
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

# ===================== Binance adapter =====================

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
        # Margin safety: if borrow happened but entry failed/canceled, repay here best-effort.
    with suppress(Exception):
        tk = (pos or {}).get("trade_key") or (pos or {}).get("client_id") or (pos or {}).get("order_id")
        margin_guard.on_after_position_closed(st, trade_key=tk)


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
    qty1, qty2, qty3 = risk_math.split_qty_3legs_validate(qty_total_r)
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
        return binance_api.place_order_raw(payload)
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
        return binance_api.place_order_raw(payload2)

def place_exits_v15(symbol: str, side: str, qty_total: float, prices: Dict[str, float]) -> Dict[str, Any]:
    """Place TP1 + TP2 + SL for V1.5 (no OCO).

    side: "LONG" | "SHORT"
    prices: {entry, sl, tp1, tp2} in *USDC* terms (already rounded)
    """
    # Ensure qty is aligned to lot step before splitting
    qty_total_r = round_qty(qty_total)

    # Split strictly in integer 'step units' to avoid float floor artefacts
    qty1, qty2, qty3 = risk_math.split_qty_3legs_place(qty_total_r)
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
    sl = binance_api.place_order_raw({
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
# Wire runtime dependencies for exits placement flow (keeps call sites unchanged).
exits_flow.configure(
    ENV,
    save_state_fn=lambda st: save_state(st),
    log_event_fn=lambda *a, **k: log_event(*a, **k),
    send_webhook_fn=lambda payload: send_webhook(payload),
    validate_exit_plan_fn=lambda *a, **k: validate_exit_plan(*a, **k),
    place_exits_v15_fn=lambda *a, **k: place_exits_v15(*a, **k),
)
def manage_v15_position(symbol: str, st: Dict[str, Any]) -> None:
    """Live V1.5 manager: TP1 -> move SL to BE (entry), TP2 continues.

    Optimized:
      - Throttled by MANAGE_EVERY_SEC in main loop
      - openOrders polling GATED to OPEN status only (not OPEN_FILLED)
      - Verifies missing orders via order status (FILLED) before acting
    """
    pos = st.get("position") or {}
    if pos.get("mode") != "live" or pos.get("status") not in ("OPEN", "OPEN_FILLED"):
        return
    if not pos.get("orders") or not pos.get("prices"):
        return
    now_s = _now_s()
    
    # GATE: Only poll openOrders when status == OPEN (not OPEN_FILLED)
    # During OPEN_FILLED, rely on place_order responses + retries, not polling
    orders = []
    if pos.get("status") == "OPEN":
        pos.pop("openorders_skip_logged", None)
        snapshot = get_snapshot()
        refreshed = refresh_snapshot(
            symbol=symbol,
            source="manage",
            open_orders_fn=binance_api.open_orders,
            min_interval_sec=float(ENV.get("SNAPSHOT_MIN_SEC", 5)),
        )
        if refreshed:
            log_event(
                "SNAPSHOT_REFRESH",
                source="manage",
                ok=snapshot.ok,
                error=snapshot.error,
                age_sec=snapshot.freshness_sec(),
                order_count=len(snapshot.get_orders()),
            )
        orders = snapshot.get_orders()
        if not snapshot.ok and snapshot.error:
            # Throttle error logging
            last_err = float(pos.get("open_orders_err_s") or 0.0)
            if now_s - last_err >= 30.0:
                pos["open_orders_err_s"] = now_s
                st["position"] = pos
                save_state(st)
                log_event("LIVE_MANAGE_ERROR", error=f"openOrders: {snapshot.error}")
    else:
        # OPEN_FILLED: skip openOrders polling (log once per position to avoid spam)
        if not pos.get("openorders_skip_logged"):
            pos["openorders_skip_logged"] = iso_utc()
            st["position"] = pos
            save_state(st)
            log_event("MANAGE_SKIP_OPENORDERS", status=pos.get("status"), reason="OPEN_FILLED_gate")

    open_ids: set[int] = set()
    for _o in (orders or []):
        if not isinstance(_o, dict):
            continue
        with suppress(Exception):
            open_ids.add(int(_o.get("orderId")))

    def _update_order_fill(pos: Dict[str, Any], leg: str, payload: Dict[str, Any]) -> bool:
        """Reporting Spec v1: persist execution data from existing status calls."""
        if not isinstance(payload, dict) or not leg:
            return False
        orders = pos.get("orders")
        if not isinstance(orders, dict):
            return False
        fills = orders.setdefault("fills", {})
        if not isinstance(fills, dict):
            fills = {}
            orders["fills"] = fills
        leg_data = fills.setdefault(leg, {})
        if not isinstance(leg_data, dict):
            leg_data = {}
            fills[leg] = leg_data

        changed = False
        order_id = payload.get("orderId") or orders.get(leg)
        if order_id is not None and leg_data.get("orderId") != order_id:
            leg_data["orderId"] = order_id
            changed = True

        status = payload.get("status")
        if status and leg_data.get("status") != status:
            leg_data["status"] = status
            changed = True

        for key in ("executedQty", "cummulativeQuoteQty"):
            val = payload.get(key)
            try:
                val_f = float(val)
            except Exception:
                continue
            prev = leg_data.get(key)
            try:
                prev_f = float(prev) if prev is not None else None
            except Exception:
                prev_f = None
            if prev_f is None or val_f > prev_f:
                leg_data[key] = val_f
                changed = True

        executed = leg_data.get("executedQty")
        cum_quote = leg_data.get("cummulativeQuoteQty")
        try:
            if executed is not None and cum_quote is not None and float(executed) > 0:
                avg = float(cum_quote) / float(executed)
                if leg_data.get("avgFillPrice") != avg:
                    leg_data["avgFillPrice"] = avg
                    changed = True
        except Exception:
            pass

        last_update = payload.get("updateTime")
        if last_update is not None and leg_data.get("lastUpdateTs") != last_update:
            leg_data["lastUpdateTs"] = last_update
            changed = True

        if changed:
            pos["orders"] = orders
        return changed

    def _save_state_best_effort(where: str) -> None:
        """Watchdog-only persistence: never crash the loop; throttle noise."""
        try:
            save_state(st)
        except Exception as e:
            next_s = 0.0
            with suppress(Exception):
                next_s = float(pos.get("sl_watchdog_save_error_next_s") or 0.0)
            if now_s >= next_s:
                pos["sl_watchdog_save_error_next_s"] = now_s + 60.0
                # best-effort only; do not re-try save_state() here
                log_event(
                    "SL_WATCHDOG_SAVE_ERROR",
                    mode="live",
                    where=where,
                    error=str(e),
                )

    def _cancel_ignore_unknown(order_id: int) -> Optional[Exception]:
        try:
            binance_api.cancel_order(symbol, int(order_id))
            return None
        except Exception as e:
            err_code = None
            with suppress(Exception):
                if getattr(e, "code", None) is not None:
                    err_code = int(getattr(e, "code"))
            if err_code is None:
                msg = str(e)
                if '"code":-2011' in msg or '"code": -2011' in msg:
                    err_code = -2011
                elif '"code":-2013' in msg or '"code": -2013' in msg:
                    err_code = -2013
            if err_code in (-2011, -2013):
                return None
            return e

    def _status_is_filled(order_id: int) -> bool:
        try:
            od = binance_api.check_order_status(symbol, int(order_id))
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
        with suppress(Exception):
            reporting.report_trade_close(st, pos, reason)
        st["position"] = None
        st["cooldown_until"] = _now_s() + float(ENV["COOLDOWN_SEC"])
        st["lock_until"] = 0.0
        save_state(st)
        with suppress(Exception):
            margin_guard.on_after_position_closed(st)

    tp1_id = int(pos["orders"].get("tp1") or 0)
    tp2_id = int(pos["orders"].get("tp2") or 0)
    sl_id = int(pos["orders"].get("sl") or 0)
    sl_prev = int(pos["orders"].get("sl_prev") or 0)

    if pos.get("exit_cleanup_pending"):
        next_cleanup = float(pos.get("exit_cleanup_next_s") or 0.0)
        if now_s < next_cleanup:
            return
        if now_s >= next_cleanup:
            retry_ids = pos.get("exit_cleanup_order_ids") or []
            failed_ids: List[int] = []
            for oid in retry_ids:
                err = _cancel_ignore_unknown(oid)
                if err is not None:
                    failed_ids.append(int(oid))
                    pos["exit_cleanup_last_error"] = str(err)
            if not failed_ids:
                reason = str(pos.get("exit_cleanup_reason") or "EXIT_CLEANUP_DONE")
                pos["exit_cleanup_pending"] = False
                pos["exit_cleanup_order_ids"] = []
                pos["exit_cleanup_next_s"] = 0.0
                pos.pop("exit_cleanup_reason", None)
                st["position"] = pos
                _save_state_best_effort("exit_cleanup_done")
                log_event("EXIT_CLEANUP_DONE", mode="live", reason=reason)
                _close_slot(reason)
                return
            pos["exit_cleanup_order_ids"] = failed_ids
            pos["exit_cleanup_next_s"] = now_s + float(ENV.get("SL_WATCHDOG_RETRY_SEC") or 0.0)
            st["position"] = pos
            _save_state_best_effort("exit_cleanup_retry_schedule")
            log_event(
                "EXIT_CLEANUP_RETRY_FAILED",
                mode="live",
                reason=pos.get("exit_cleanup_reason"),
                failed_ids=failed_ids,
                error=pos.get("exit_cleanup_last_error"),
            )
            return

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
                binance_api.cancel_order(symbol, sl_prev)

    # TP1 filled -> move SL to BE (entry) for remaining qty2+qty3
    if tp1_id and not pos.get("tp1_done"):
        poll_due = now_s >= float(pos.get("tp1_status_next_s") or 0.0)
        # Do not gate FILLED detection on openOrders/open_ids; throttle via tp1_status_next_s
        if poll_due or (not orders):
            pos["tp1_status_next_s"] = now_s + float(ENV["LIVE_STATUS_POLL_EVERY"])
            tp1_status_payload = None
            with suppress(Exception):
                tp1_status_payload = binance_api.check_order_status(symbol, tp1_id)
            if isinstance(tp1_status_payload, dict):
                if _update_order_fill(pos, "tp1", tp1_status_payload):
                    st["position"] = pos
                    _save_state_best_effort("tp1_fill_update")
            tp1_filled = False
            if isinstance(tp1_status_payload, dict):
                tp1_filled = str(tp1_status_payload.get("status", "")).upper() == "FILLED"
            if tp1_filled:
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
                    sl_new = binance_api.place_order_raw({
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
                            binance_api.cancel_order(symbol, sl_id)
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
        tp2_status_payload = None
        with suppress(Exception):
            tp2_status_payload = binance_api.check_order_status(symbol, tp2_id)
        if isinstance(tp2_status_payload, dict):
            if _update_order_fill(pos, "tp2", tp2_status_payload):
                st["position"] = pos
                _save_state_best_effort("tp2_fill_update")
        tp2_filled = False
        if isinstance(tp2_status_payload, dict):
            tp2_filled = str(tp2_status_payload.get("status", "")).upper() == "FILLED"
        if tp2_filled:
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
                        binance_api.cancel_order(symbol, tp1_id)

                # replace current SL with trailing SL for remaining qty (qty3, or qty1+qty3 if TP2 filled first)
                sl_now = int((pos.get("orders") or {}).get("sl") or 0)

               # Primary: trailing stop from aggregated.csv swings (low API usage).
                desired = _trail_desired_stop_from_agg(pos)
                if desired is None:
                    # Fallback (only if CSV unavailable): public mid-price +/- buffer
                    snapshot = price_snapshot.get_price_snapshot()
                    min_interval = float(ENV.get("PRICE_SNAPSHOT_MIN_SEC") or 2.0)
                    price_snapshot.refresh_price_snapshot(symbol, "trailing_activate", binance_api.get_mid_price, min_interval)
                    mid = 0.0
                    if snapshot.ok:
                        mid = float(snapshot.price_mid)
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
                            binance_api.cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = binance_api.check_order_status(symbol, sl_now)
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
                        sl_new = binance_api.place_order_raw({
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
                                fb = binance_api.place_order_raw({
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
                    binance_api.cancel_order(symbol, sl_now)
            if tp1_id:
                with suppress(Exception):
                    binance_api.cancel_order(symbol, tp1_id)
            sl_prev2 = int((pos.get("orders") or {}).get("sl_prev") or 0)
            if sl_prev2:
                with suppress(Exception):
                    binance_api.cancel_order(symbol, sl_prev2)
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
                snapshot = price_snapshot.get_price_snapshot()
                min_interval = float(ENV.get("PRICE_SNAPSHOT_MIN_SEC") or 2.0)
                price_snapshot.refresh_price_snapshot(symbol, "trailing_update", binance_api.get_mid_price, min_interval)
                mid = 0.0
                if snapshot.ok:
                    mid = float(snapshot.price_mid)
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
                        od_p = binance_api.check_order_status(symbol, pend_sl)
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
                        od_s = binance_api.check_order_status(symbol, sl_now)
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
                            sl_new = binance_api.place_order_raw({
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
                            err_msg = str(e)
                            err_code = None
                            with suppress(Exception):
                                if getattr(e, "code", None) is not None:
                                    err_code = int(getattr(e, "code"))
                            if err_code is None and ('"code":-2010' in err_msg or '"code": -2010' in err_msg):
                                err_code = -2010
                            if err_code is None:
                                err_code = 0
                            pos["trail_last_error_code"] = err_code
                            pos["trail_last_error_s"] = now_s
                            pos["trail_error_count"] = int(pos.get("trail_error_count") or 0) + 1
                            st["position"] = pos
                            with suppress(Exception):
                                save_state(st)
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
                            binance_api.cancel_order(symbol, sl_now)
                        od_c = None
                        with suppress(Exception):
                            od_c = binance_api.check_order_status(symbol, sl_now)
                        st_c = str((od_c or {}).get("status", "")).upper()
                        if st_c not in ("CANCELED", "REJECTED", "EXPIRED"):
                            pos["trail_last_update_s"] = now_s
                            st["position"] = pos
                            save_state(st)
                            log_event("TRAIL_SL_CANCEL_NOT_CONFIRMED", mode="live", order_id_sl=sl_now, status=st_c or "UNKNOWN")
                        else:
                            try:
                                sl_new = binance_api.place_order_raw({
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
                                err_msg = str(e)
                                err_code = None
                                with suppress(Exception):
                                    if getattr(e, "code", None) is not None:
                                        err_code = int(getattr(e, "code"))
                                if err_code is None and ('"code":-2010' in err_msg or '"code": -2010' in err_msg):
                                    err_code = -2010
                                if err_code is None:
                                    err_code = 0
                                pos["trail_last_error_code"] = err_code
                                pos["trail_last_error_s"] = now_s
                                pos["trail_error_count"] = int(pos.get("trail_error_count") or 0) + 1
                                st["position"] = pos
                                with suppress(Exception):
                                    save_state(st)
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

    sl_order_payload = None
    if sl_id:
        for _o in (orders or []):
            if not isinstance(_o, dict):
                continue
            with suppress(Exception):
                if int(_o.get("orderId")) == sl_id:
                    sl_order_payload = _o
                    break

    sl_status_payload = sl_order_payload
    if sl_id:
        needs_status = (
            (not isinstance(sl_order_payload, dict))
            or ("status" not in sl_order_payload)
            or ("executedQty" not in sl_order_payload)
            or ("origQty" not in sl_order_payload)   # important for watchdog qty correctness
        )
        # Reuse main status throttle, and don't add extra polling.
        next_status = float(pos.get("sl_status_next_s") or 0.0)
        status_poll_due = now_s >= next_status
        if needs_status and (status_poll_due or (not orders)) and now_s >= next_status:
            pos["sl_status_next_s"] = now_s + float(ENV.get("LIVE_STATUS_POLL_EVERY") or 0.0)
            st["position"] = pos
            _save_state_best_effort("sl_status_next_s_watchdog")
            with suppress(Exception):
                sl_status_payload = binance_api.check_order_status(symbol, sl_id)
            if isinstance(sl_status_payload, dict):
                if _update_order_fill(pos, "sl", sl_status_payload):
                    st["position"] = pos
                    _save_state_best_effort("sl_fill_update")

    # SL watchdog only active when status == "OPEN" (entry filled, exits not yet tracked as filled)
    status = str(pos.get("status") or "").strip().upper()
    plan = None
    if status == "OPEN":
        # Watchdog must use only live exchange price (no aggregated.csv to avoid stale triggers).
        min_interval = float(ENV.get("PRICE_SNAPSHOT_MIN_SEC") or 2.0)
        price_snapshot.refresh_price_snapshot(symbol, "sl_watchdog", binance_api.get_mid_price, min_interval)
        snapshot = price_snapshot.get_price_snapshot()
        price_now = float("nan")
        if snapshot.ok:
            price_now = float(snapshot.price_mid)
        else:
            next_direct_s = float(pos.get("sl_watchdog_direct_next_s") or 0.0)
            if now_s >= next_direct_s:
                pos["sl_watchdog_direct_next_s"] = now_s + min_interval
                # Persist throttle across ticks (state is reloaded every loop).
                st["position"] = pos
                _save_state_best_effort("sl_watchdog_direct_throttle")
                with suppress(Exception):
                    price_now = float(binance_api.get_mid_price(symbol))

        prev_trigger_s = pos.get("sl_watchdog_first_trigger_s")
        prev_fired = bool(pos.get("sl_watchdog_fired"))
        next_err_s = float(pos.get("sl_watchdog_error_next_s") or 0.0)
        try:
            plan = exit_safety.sl_watchdog_tick(
                st,
                pos,
                ENV,
                now_s,
                price_now,
                sl_status_payload,
            )
        except Exception as e:
            if now_s >= next_err_s:
                pos["sl_watchdog_error_next_s"] = now_s + 60.0
                st["position"] = pos
                _save_state_best_effort("sl_watchdog_tick_error")
                log_event("SL_WATCHDOG_ERROR", error=str(e), mode="live")

        if prev_trigger_s is None and pos.get("sl_watchdog_first_trigger_s") is not None:
            log_event("SL_WATCHDOG_TRIGGER", mode="live", order_id_sl=sl_id, price_now=price_now)

        if prev_trigger_s != pos.get("sl_watchdog_first_trigger_s") or prev_fired != bool(pos.get("sl_watchdog_fired")):
            st["position"] = pos
            _save_state_best_effort("sl_watchdog_state_change")

    if plan:
        post_market_events: List[Dict[str, Any]] = []
        for event in plan.get("events", []):
            if not isinstance(event, dict):
                continue
            name = event.get("name")
            if not name:
                continue
            if name == "SL_PARTIAL_DETECTED":
                payload = {k: v for k, v in event.items() if k != "name"}
                log_event(name, mode="live", **payload)
            elif name == "SL_MARKET_FALLBACK":
                post_market_events.append(event)
        plan_qty = float(plan.get("qty") or 0.0)
        skip_market = plan_qty <= 0.0
        market_attempted = False
        market_ok = False
        if skip_market:
            is_dust = str(plan.get("action") or "").upper() == "DUST_REMAINDER" or str(plan.get("reason") or "") == "SL_DUST_REMAINDER"
            # If planner classified it as dust remainder, persist it so exchange-truth reconciliation / alerts can see it.
            if is_dust:
                dust_payload = {
                    "qty_raw": plan.get("dust_qty_raw"),
                    "qty_quantized": plan.get("dust_qty_quantized"),
                    "notional_raw": plan.get("dust_notional_raw"),
                    "min_notional": plan.get("min_notional"),
                    "min_qty": plan.get("min_qty"),
                    "price_now": plan.get("price_now"),
                }
                log_event("SL_DUST_REMAINDER", mode="live", **{k: v for k, v in dust_payload.items() if v is not None})
                pos["dust_remainder"] = True
                pos["dust_reason"] = str(plan.get("reason") or "SL_DUST_REMAINDER")
                with suppress(Exception):
                    pos["dust_qty_raw"] = float(plan.get("dust_qty_raw") or 0.0)
                with suppress(Exception):
                    pos["dust_qty_q"] = float(plan.get("dust_qty_quantized") or 0.0)
                with suppress(Exception):
                    pos["dust_notional_raw"] = float(plan.get("dust_notional_raw") or 0.0)
                with suppress(Exception):
                    pos["dust_min_notional"] = float(plan.get("min_notional") or 0.0)
                with suppress(Exception):
                    pos["dust_min_qty"] = float(plan.get("min_qty") or 0.0)
                with suppress(Exception):
                    pos["dust_price_now"] = float(plan.get("price_now") or 0.0)
                pos["dust_ts"] = now_s
                st["position"] = pos
                _save_state_best_effort("sl_watchdog_dust_remainder")

            next_noqty = float(pos.get("sl_watchdog_noqty_next_s") or 0.0)
            if now_s >= next_noqty and not is_dust:
                pos["sl_watchdog_noqty_next_s"] = now_s + 60.0
                st["position"] = pos
                _save_state_best_effort("sl_watchdog_no_qty")
                log_event(
                    "SL_WATCHDOG_NO_QTY",
                    mode="live",
                    reason=str(plan.get("reason") or ""),
                    qty=plan_qty,
                )
            market_ok = True  # qty==0 -> safe to proceed with cleanup + close-slot
        now_attempt = now_s
        last_attempt = float(pos.get("sl_watchdog_last_market_attempt_s") or 0.0)
        if (not skip_market) and plan_qty > 0.0:
            close_side = str(plan.get("side") or "").upper()
            if close_side in ("BUY", "SELL"):
                retry_sec = float(ENV.get("SL_WATCHDOG_RETRY_SEC") or 0.0)
                if now_attempt - last_attempt >= retry_sec:
                    market_attempted = True
                    pos["sl_watchdog_last_market_attempt_s"] = now_attempt
                    pos["sl_watchdog_last_market_ok"] = None
                    pos.pop("sl_watchdog_last_market_error", None)
                    st["position"] = pos
                    _save_state_best_effort("sl_watchdog_pre_market")
                    try:
                        pos_side = str(pos.get("side") or "").upper()
                        if pos_side not in ("LONG", "SHORT"):
                            pos_side = "SHORT" if close_side == "BUY" else "LONG"
                        binance_api.flatten_market(symbol, pos_side, plan_qty, client_id=f"EX_SL_WD_{int(time.time())}")
                        market_ok = True
                        pos["sl_watchdog_last_market_ok"] = True
                        pos.pop("sl_watchdog_last_market_error", None)
                        st["position"] = pos
                        _save_state_best_effort("sl_watchdog_market_ok")
                    except Exception as e:
                        market_ok = False
                        pos["sl_watchdog_last_market_ok"] = False
                        pos["sl_watchdog_last_market_error"] = str(e)
                        st["position"] = pos
                        _save_state_best_effort("sl_watchdog_market_err")
                        log_event("SL_WATCHDOG_MARKET_ERROR", error=str(e), mode="live", qty=plan_qty)
                else:
                    # Optional observability: record skip without spamming disk writes.
                    last_skip = float(pos.get("sl_watchdog_last_skip_s") or 0.0)
                    if (not last_skip) or (now_s - last_skip) >= 60.0:
                        pos["sl_watchdog_last_skip_s"] = now_s
                        pos["sl_watchdog_last_skip_reason"] = "RETRY_WINDOW"
                        st["position"] = pos
                        _save_state_best_effort("sl_watchdog_skip_retry_window")
                    # IMPORTANT: do not cancel/close-slot until MARKET is actually attempted.
                    return
            else:
                # If close_side is invalid, do nothing (planner bug / bad data).
                return
        if not market_ok:
            return
        if (not skip_market) and plan_qty > 0.0 and market_attempted and market_ok:
            if post_market_events:
                for event in post_market_events:
                    payload = {k: v for k, v in event.items() if k != "name"}
                    log_event("SL_MARKET_FALLBACK", mode="live", **payload)
            else:
                log_event("SL_MARKET_FALLBACK", mode="live")
        if plan.get("set_fired_on_success"):
            pos["sl_watchdog_fired"] = True
            st["position"] = pos
            _save_state_best_effort("sl_watchdog_set_fired")
        cancel_ids = plan.get("cancel_order_ids") or []
        failed_ids: List[int] = []
        for oid in cancel_ids:
            err = _cancel_ignore_unknown(oid)
            if err is not None:
                failed_ids.append(int(oid))
                log_event("SL_WATCHDOG_CANCEL_ERROR", error=str(err), mode="live", order_id=oid)
        if failed_ids:
            pos["exit_cleanup_pending"] = True
            pos["exit_cleanup_order_ids"] = failed_ids
            pos["exit_cleanup_next_s"] = now_s + float(ENV.get("SL_WATCHDOG_RETRY_SEC") or 0.0)
            pos["exit_cleanup_reason"] = str(plan.get("reason") or "SL_WATCHDOG")
            st["position"] = pos
            _save_state_best_effort("exit_cleanup_pending_schedule")
            log_event("EXIT_CLEANUP_PENDING", mode="live", reason=pos["exit_cleanup_reason"], failed_ids=failed_ids)
            return
        _close_slot(str(plan.get("reason") or "SL_WATCHDOG"))
        return

    def _is_unknown_order_error(e: Exception) -> bool:
        # Binance "unknown order" can surface with various strings; keep heuristic minimal.
        msg = str(e or "")
        msg_u = msg.upper()
        return (
            "UNKNOWN ORDER" in msg_u
            or "UNKNOWN_ORDER" in msg_u
            or "ORDER DOES NOT EXIST" in msg_u
            or "ORDER_NOT_FOUND" in msg_u
            or "NO SUCH ORDER" in msg_u
        )

    # TP watchdog: handle TP1/TP2 partial fills, missing orders, and synthetic trailing
    tp1_status_payload = None
    tp2_status_payload = None
    if tp1_id or tp2_id:
        # Reuse existing openOrders data from snapshot for TP status
        for _o in (orders or []):
            if not isinstance(_o, dict):
                continue
            with suppress(Exception):
                oid = int(_o.get("orderId"))
                if tp1_id and oid == tp1_id:
                    tp1_status_payload = _o
                if tp2_id and oid == tp2_id:
                    tp2_status_payload = _o

        # Throttled status polling if needed (reuse LIVE_STATUS_POLL_EVERY pattern)
        if tp1_id and not pos.get("tp1_done"):
            needs_tp1_status = (
                (not isinstance(tp1_status_payload, dict))
                or ("status" not in tp1_status_payload)
                or ("executedQty" not in tp1_status_payload)
                or ("origQty" not in tp1_status_payload)
            )
            next_tp1_status = float(pos.get("tp1_watchdog_status_next_s") or 0.0)
            if needs_tp1_status and (now_s >= next_tp1_status or (not orders)):
                pos["tp1_watchdog_status_next_s"] = now_s + float(ENV.get("LIVE_STATUS_POLL_EVERY") or 0.0)
                st["position"] = pos
                _save_state_best_effort("tp1_watchdog_status_poll")
                try:
                    tp1_status_payload = binance_api.check_order_status(symbol, tp1_id)
                    if isinstance(tp1_status_payload, dict):
                        if _update_order_fill(pos, "tp1", tp1_status_payload):
                            st["position"] = pos
                            _save_state_best_effort("tp1_watchdog_fill_update")
                except Exception as e:
                    # If order is missing on exchange, inject synthetic status for planner.
                    if _is_unknown_order_error(e):
                        tp1_status_payload = {"status": "MISSING"}

        if tp2_id and not pos.get("tp2_done") and not pos.get("tp2_synthetic"):
            needs_tp2_status = (
                (not isinstance(tp2_status_payload, dict))
                or ("status" not in tp2_status_payload)
            )
            next_tp2_status = float(pos.get("tp2_watchdog_status_next_s") or 0.0)
            if needs_tp2_status and (now_s >= next_tp2_status or (not orders)):
                pos["tp2_watchdog_status_next_s"] = now_s + float(ENV.get("LIVE_STATUS_POLL_EVERY") or 0.0)
                st["position"] = pos
                _save_state_best_effort("tp2_watchdog_status_poll")
                try:
                    tp2_status_payload = binance_api.check_order_status(symbol, tp2_id)
                    if isinstance(tp2_status_payload, dict):
                        if _update_order_fill(pos, "tp2", tp2_status_payload):
                            st["position"] = pos
                            _save_state_best_effort("tp2_watchdog_fill_update")
                except Exception as e:
                    if _is_unknown_order_error(e):
                        tp2_status_payload = {"status": "MISSING"}

    # Execute TP watchdog (OPEN or OPEN_FILLED status)
    tp_plan = None
    if status in ("OPEN", "OPEN_FILLED"):
        min_interval = float(ENV.get("PRICE_SNAPSHOT_MIN_SEC") or 2.0)
        price_snapshot.refresh_price_snapshot(symbol, "tp_watchdog", binance_api.get_mid_price, min_interval)
        snapshot = price_snapshot.get_price_snapshot()
        price_now_tp = float("nan")
        if snapshot.ok:
            price_now_tp = float(snapshot.price_mid)
        else:
            next_direct_s = float(pos.get("tp_watchdog_direct_next_s") or 0.0)
            if now_s >= next_direct_s:
                pos["tp_watchdog_direct_next_s"] = now_s + min_interval
                # Persist throttle across ticks (state is reloaded every loop).
                st["position"] = pos
                _save_state_best_effort("tp_watchdog_direct_throttle")
                with suppress(Exception):
                    price_now_tp = float(binance_api.get_mid_price(symbol))

        next_err_s = float(pos.get("tp_watchdog_error_next_s") or 0.0)
        try:
            tp_plan = exit_safety.tp_watchdog_tick(
                st,
                pos,
                ENV,
                now_s,
                price_now_tp,
                tp1_status_payload,
                tp2_status_payload,
            )
        except Exception as e:
            if now_s >= next_err_s:
                pos["tp_watchdog_error_next_s"] = now_s + 60.0
                st["position"] = pos
                _save_state_best_effort("tp_watchdog_tick_error")
                log_event("TP_WATCHDOG_ERROR", error=str(e), mode="live")

    if tp_plan:
        action = str(tp_plan.get("action") or "").upper()
        reason = str(tp_plan.get("reason") or "")

        # Log events from plan
        post_market_events: List[Dict[str, Any]] = []
        for event in tp_plan.get("events", []):
            if not isinstance(event, dict):
                continue
            name = event.get("name")
            if not name:
                continue
            if name in ("TP1_PARTIAL_DETECTED", "TP1_MISSING_PRICE_CROSSED", "TP2_MISSING_SYNTHETIC_TRAILING"):
                # One-shot detection events (no log spam)
                flag_key = None
                if name == "TP1_PARTIAL_DETECTED":
                    flag_key = "tp1_wd_partial_logged"
                elif name == "TP1_MISSING_PRICE_CROSSED":
                    flag_key = "tp1_wd_missing_logged"
                elif name == "TP2_MISSING_SYNTHETIC_TRAILING":
                    flag_key = "tp2_wd_missing_logged"

                already = bool(pos.get(flag_key)) if flag_key else False
                if not already:
                    payload = {k: v for k, v in event.items() if k != "name"}
                    log_event(name, mode="live", **payload)
                    if flag_key:
                        pos[flag_key] = True
                        st["position"] = pos
                        _save_state_best_effort("tp_watchdog_event_flag_set")
            elif name in ("TP1_MARKET_FALLBACK", "TP1_MARKET_FALLBACK_PARTIAL", "TP1_PARTIAL_DUST", "TP1_MISSING_DUST"):
                post_market_events.append(event)

        # Handle MARKET_FLATTEN actions
        if action == "MARKET_FLATTEN":
            plan_qty = float(tp_plan.get("qty") or 0.0)
            close_side = str(tp_plan.get("side") or "").upper()

            if plan_qty > 0.0 and close_side in ("BUY", "SELL"):
                retry_sec = float(ENV.get("SL_WATCHDOG_RETRY_SEC") or 0.0)
                last_attempt = float(pos.get("tp_watchdog_last_market_attempt_s") or 0.0)

                if (now_s - last_attempt) >= retry_sec:
                    pos["tp_watchdog_last_market_attempt_s"] = now_s
                    st["position"] = pos
                    _save_state_best_effort("tp_watchdog_pre_market")

                    market_ok = False
                    try:
                        pos_side = str(pos.get("side") or "").upper()
                        if pos_side not in ("LONG", "SHORT"):
                            pos_side = "SHORT" if close_side == "BUY" else "LONG"
                        binance_api.flatten_market(symbol, pos_side, plan_qty, client_id=f"EX_TP_WD_{int(time.time())}")
                        market_ok = True
                        st["position"] = pos
                        _save_state_best_effort("tp_watchdog_market_ok")

                        # Log post-market events
                        if post_market_events:
                            for event in post_market_events:
                                payload = {k: v for k, v in event.items() if k != "name"}
                                log_event(event.get("name"), mode="live", **payload)
                    except Exception as e:
                        pos["tp_watchdog_last_market_error"] = str(e)
                        st["position"] = pos
                        _save_state_best_effort("tp_watchdog_market_err")
                        log_event("TP_WATCHDOG_MARKET_ERROR", error=str(e), mode="live", qty=plan_qty)
                        return

                    if not market_ok:
                        return
                else:
                    # Still in retry window
                    return

        # Handle dust cases (TP1_PARTIAL_DUST, TP1_MISSING_DUST)
        elif action in ("TP1_PARTIAL_DUST", "TP1_MISSING_DUST"):
            dust_payload = {
                "qty_raw": tp_plan.get("dust_qty_raw"),
                "qty_quantized": tp_plan.get("dust_qty_quantized"),
                "notional_raw": tp_plan.get("dust_notional_raw"),
                "min_notional": tp_plan.get("min_notional"),
                "min_qty": tp_plan.get("min_qty"),
                "price_now": tp_plan.get("price_now"),
            }
            log_event(action, mode="live", **{k: v for k, v in dust_payload.items() if v is not None})

        # Handle ACTIVATE_SYNTHETIC_TRAILING
        elif action == "ACTIVATE_SYNTHETIC_TRAILING":
            if tp_plan.get("set_tp2_synthetic"):
                pos["tp2_synthetic"] = True
            if tp_plan.get("activate_trail"):
                pos["trail_active"] = True
                pos["trail_qty"] = float(tp_plan.get("trail_qty") or 0.0)
            st["position"] = pos
            _save_state_best_effort("tp2_synthetic_trailing")
            log_event("TP2_SYNTHETIC_TRAILING_ACTIVATED", mode="live", trail_qty=pos.get("trail_qty"))

        # Apply state transitions
        if tp_plan.get("set_tp1_done"):
            pos["tp1_done"] = True

            # Move SL to BE for remaining qty2+qty3
            if tp_plan.get("move_sl_to_be"):
                exit_side = "SELL" if pos["side"] == "LONG" else "BUY"
                be_stop = float(pos.get("entry_actual") or (pos.get("prices") or {}).get("entry") or 0.0)

                qty2 = float((pos.get("orders") or {}).get("qty2") or 0.0)
                qty3 = float((pos.get("orders") or {}).get("qty3") or 0.0)
                rem_qty = float(round_qty(qty2 + qty3))

                if be_stop > 0.0 and rem_qty > 0.0:
                    tick = float(ENV["TICK_SIZE"])
                    gap_ticks = max(1, int(ENV.get("SL_LIMIT_GAP_TICKS") or 0))
                    gap = tick * float(gap_ticks)
                    be_limit = (be_stop - gap) if exit_side == "SELL" else (be_stop + gap)
                    be_stop_s = fmt_price(be_stop)
                    be_limit_s = fmt_price(be_limit)
                    if be_limit_s == be_stop_s:
                        be_limit_s = fmt_price((be_stop - tick) if exit_side == "SELL" else (be_stop + tick))

                    try:
                        sl_new = binance_api.place_order_raw({
                            "symbol": symbol,
                            "side": exit_side,
                            "type": "STOP_LOSS_LIMIT",
                            "quantity": fmt_qty(rem_qty),
                            "price": be_limit_s,
                            "stopPrice": be_stop_s,
                            "timeInForce": "GTC",
                            "newClientOrderId": f"EX_SL_BE_TP1WD_{int(time.time())}",
                        })
                        sl_id = int((pos.get("orders") or {}).get("sl") or 0)
                        if sl_id:
                            pos["orders"]["sl_prev"] = sl_id
                            pos["sl_prev_next_cancel_s"] = _now_s()
                        pos["orders"]["sl"] = _oid_int(sl_new.get("orderId"))
                        log_event("TP1_WATCHDOG_SL_TO_BE", mode="live", new_sl_order_id=sl_new.get("orderId"))
                        send_webhook({"event": "TP1_WATCHDOG_SL_TO_BE", "mode": "live", "symbol": symbol, "new_sl_order_id": sl_new.get("orderId"), "entry": be_stop})
                        if sl_id:
                            with suppress(Exception):
                                binance_api.cancel_order(symbol, sl_id)
                    except Exception as e:
                        log_event("TP1_WATCHDOG_SL_TO_BE_ERROR", error=str(e), mode="live")

            st["position"] = pos
            _save_state_best_effort("tp1_watchdog_done")

        # Cancel orders from plan
        cancel_ids = tp_plan.get("cancel_order_ids") or []
        failed_ids: List[int] = []
        for oid in cancel_ids:
            err = _cancel_ignore_unknown(oid)
            if err is not None:
                failed_ids.append(int(oid))
                log_event("TP_WATCHDOG_CANCEL_ERROR", error=str(err), mode="live", order_id=oid)

        if failed_ids:
            pos["exit_cleanup_pending"] = True
            pos["exit_cleanup_order_ids"] = failed_ids
            pos["exit_cleanup_next_s"] = now_s + float(ENV.get("SL_WATCHDOG_RETRY_SEC") or 0.0)
            pos["exit_cleanup_reason"] = reason or "TP_WATCHDOG"
            st["position"] = pos
            _save_state_best_effort("exit_cleanup_pending_schedule_tp")
            log_event("EXIT_CLEANUP_PENDING", mode="live", reason=pos["exit_cleanup_reason"], failed_ids=failed_ids)

        st["position"] = pos
        _save_state_best_effort("tp_watchdog_complete")

    # SL filled -> close slot
    sl_id2 = int((pos.get("orders") or {}).get("sl") or 0)
    if sl_id2 and not pos.get("sl_done"):
        poll_due = now_s >= float(pos.get("sl_status_next_s") or 0.0)

        # Do not gate FILLED detection on openOrders/open_ids; throttle via sl_status_next_s
        if poll_due or (not orders):
            pos["sl_status_next_s"] = now_s + float(ENV["LIVE_STATUS_POLL_EVERY"])
            sl_status = ""
            if isinstance(sl_status_payload, dict):
                sl_status = str(sl_status_payload.get("status", "")).upper()
            sl_filled = sl_status == "FILLED" if sl_status else _status_is_filled(sl_id2)

            if sl_filled:
                pos["sl_done"] = True
                st["position"] = pos
                save_state(st)
                log_event("SL_DONE", mode="live", order_id_sl=sl_id2)
                send_webhook({"event": "SL_DONE", "mode": "live", "symbol": symbol})

                # cancel any remaining exits (best-effort) to avoid orphan orders
                if tp1_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, tp1_id)
                if tp2_id:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, tp2_id)

                sl_prev3 = int((pos.get("orders") or {}).get("sl_prev") or 0)
                if sl_prev3:
                    with suppress(Exception):
                        binance_api.cancel_order(symbol, sl_prev3)

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

def _trail_desired_stop_from_agg(pos: dict) -> Optional[float]:
    """
    Compute desired trailing stop based on last swing from aggregated.csv v2:
    LONG uses LowPrice swings; SHORT uses HiPrice swings.
    trail_wait_confirm uses ClosePrice (bar close) for confirmation only.
    LONG: stop = swing_low - buffer
    SHORT: stop = swing_high + buffer
    """
    return trail._trail_desired_stop_from_agg(pos)

def get_usdt_usdc_k() -> float:
    """Get USDC/USDT conversion ratio.

    Note: Uses direct API calls (not PriceSnapshot) because we need two different
    symbols simultaneously and PriceSnapshot is a singleton holding one symbol.
    This is called only during signal processing, not in tight loops.
    """
    mid_usdt = binance_api.get_mid_price("BTCUSDT")
    mid_usdc = binance_api.get_mid_price("BTCUSDC")
    return mid_usdc / mid_usdt

def sync_from_binance(st: Dict[str, Any], reason: str = "unknown") -> None:
    """Best-effort reconciliation of executor state with Binance.

    Why:
      - container/VPS restart with state mismatch
      - manual SL/TP placement/cancel in UI
      - key rotation / partial state reset

    Strategy (minimal, safe):
      - Look at *tagged* openOrders (clientOrderId starts with 'EX_')
      - If we see tagged orders and local state is empty -> create/attach a live position shell
      - If local state says OPEN/PENDING but Binance has no tagged orders -> clear slot (assume closed/canceled)
      
    GATED: Only run on BOOT/MANUAL/RECOVERY or at most once per SYNC_BINANCE_THROTTLE_SEC.
    Prefer using snapshot if fresh to avoid duplicate openOrders calls.

    This avoids accidental double-opening after restarts.
    """
    if str(ENV.get("TRADE_MODE", "spot")).strip().lower() != "margin":
        return
    
    # GATE: Throttle sync_from_binance unless reason is BOOT/MANUAL/RECOVERY
    pos = st.get("position") or {}
    now_s = time.time()
    
    if reason not in ("BOOT", "MANUAL", "RECOVERY"):
        # Check if we have a live position - if yes, throttle sync
        if pos and pos.get("mode") == "live":
            last_sync = float(st.get("last_sync_from_binance_s") or 0.0)
            throttle_sec = float(ENV.get("SYNC_BINANCE_THROTTLE_SEC", 300))
            if now_s - last_sync < throttle_sec:
                log_event("SYNC_SKIP_THROTTLED", reason=reason, throttle_sec=throttle_sec, age_sec=now_s - last_sync)
                return
    
    st["last_sync_from_binance_s"] = now_s
    
    # Try to use fresh snapshot first to avoid duplicate openOrders call
    snapshot = get_snapshot()
    if snapshot.is_fresh(float(ENV.get("SNAPSHOT_MIN_SEC", 5))) and snapshot.ok:
        orders = snapshot.get_orders()
        log_event("SYNC_USE_SNAPSHOT", reason=reason, age_sec=snapshot.freshness_sec(), order_count=len(orders))
    else:
        try:
            orders = binance_api.open_orders(ENV["SYMBOL"])
            # Update snapshot while we're here
            snapshot.ts_updated = now_s
            snapshot.ok = True
            snapshot.error = None
            snapshot.open_orders = orders
            snapshot.source = f"sync:{reason}"
            snapshot.symbol = ENV["SYMBOL"]
            log_event("SYNC_FETCH_OPENORDERS", reason=reason, order_count=len(orders or []))
        except Exception as e:
            log_event("SYNC_ERR_OPENORDERS", reason=reason, error=str(e))
            return

    tagged = [o for o in (orders or []) if str(o.get("clientOrderId", "")).startswith("EX_")]
    pos = st.get("position") or {}

    if not tagged:
        # EXCHANGE-TRUTH CLEANUP:
        # If state says we are OPEN, but the exchange has:
        #   - no open orders for this symbol
        #   - no position / no margin exposure for base asset
        # then clear state + alert, instead of keeping a ghost OPEN.
        if ENV.get("I13_CLEAR_STATE_ON_EXCHANGE_CLEAR") and pos and pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED"):
            symbol = str(ENV.get("SYMBOL", "") or "").strip().upper()
            if symbol:
                # throttle the alert via pos["recon"]["last_emit"]
                recon = (pos.setdefault("recon", {}) if isinstance(pos, dict) else {})
                last_emit = recon.setdefault("last_emit", {}) if isinstance(recon, dict) else {}
                throttle_sec = int(ENV.get("RECON_THROTTLE_SEC") or ENV.get("INVAR_THROTTLE_SEC", 600) or 600)
                now_s = time.time()

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
                    # we don't clear state if we can't confirm exchange empty
                    if _should_emit("pos_clear:open_orders_error"):
                        log_event("POSITION_CLEAR_CHECK_FAILED", mode="live", symbol=symbol, error=str(e))
                if isinstance(all_open, list) and len(all_open) == 0:
                    ex_pos = _exchange_position_exists(symbol)
                    if ex_pos is False:
                        # confirmed empty -> clear state + alert
                        if _should_emit("pos_clear:confirmed"):
                            log_event("POSITION_CLEARED_BY_EXCHANGE", mode="live", symbol=symbol, prev_status=pos.get("status"))
                            with suppress(Exception):
                                send_webhook({"event": "POSITION_CLEARED_BY_EXCHANGE", "mode": "live", "symbol": symbol, "prev_status": pos.get("status")})
                        if str(ENV.get("TRADE_MODE", "")).strip().lower() == "margin":
                            margin = st.get("margin", {})
                            if (margin.get("borrowed_assets") or margin.get("borrowed_by_trade")):
                                tk = pos.get("trade_key") or margin.get("active_trade_key") or (st.get("last_closed") or {}).get("trade_key")
                                with suppress(Exception):
                                    margin_guard.on_after_position_closed(st, trade_key=tk)
                        st["position"] = None
                        st["lock_until"] = 0.0
                        save_state(st)
                        return
                    elif ex_pos is None:
                        # unknown -> do nothing, but leave trace (throttled)
                        if _should_emit("pos_clear:unknown"):
                            log_event("POSITION_CLEAR_EXCHANGE_UNKNOWN", mode="live", symbol=symbol)

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
                od = binance_api.check_order_status(ENV["SYMBOL"], oid)
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

    # We have tagged orders. If we already have a live position, reconcile exits.
    if pos.get("mode") == "live" and pos.get("status") in ("PENDING", "OPEN", "OPEN_FILLED"):
        open_ids = set()
        for o in tagged:
            with suppress(Exception):
                open_ids.add(int(o.get("orderId")))
        orders = pos.get("orders") or {}
        updated = False
        recon = pos.setdefault("recon", {})
        last_emit = recon.setdefault("last_emit", {})
        throttle_sec = int(ENV.get("RECON_THROTTLE_SEC") or ENV.get("INVAR_THROTTLE_SEC", 600) or 600)
        now_s = time.time()

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
            log_event(event, **payload)
            with suppress(Exception):
                send_webhook(payload)

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
                od = binance_api.get_order(ENV["SYMBOL"], oid)
                status = str((od or {}).get("status", "")).upper()
                with suppress(Exception):
                    executed_qty = float((od or {}).get("executedQty") or 0.0)
            except Exception as e:
                err = str(e)
                err_l = err.lower()

                # Binance often returns -2013 "Order does not exist." / "Unknown order"
                if ("-2013" in err_l) or ("order does not exist" in err_l) or ("unknown order" in err_l):
                    orders.pop(key, None)
                    recon.setdefault(f"{key}_missing_ts", iso_utc())
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
                            "symbol": ENV["SYMBOL"],
                        },
                        f"recon:{key}:{oid}:not_found",
                    )
                    continue

                recon.setdefault(f"{key}_unknown_ts", iso_utc())
                updated = True
                _emit(
                    "RECON_ORDER_UNKNOWN",
                    {
                        "event": "RECON_ORDER_UNKNOWN",
                        "which": key,
                        "order_id": oid,
                        "error": err,
                        "symbol": ENV["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if status == "FILLED":
                recon.setdefault(f"{key}_filled_seen_ts", iso_utc())
                updated = True
                _emit(
                    "RECON_ORDER_FILLED_SEEN",
                    {
                        "event": "RECON_ORDER_FILLED_SEEN",
                        "which": key,
                        "order_id": oid,
                        "status": "FILLED",
                        "symbol": ENV["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if status in ("CANCELED", "EXPIRED", "REJECTED"):
                orders.pop(key, None)
                recon.setdefault(f"{key}_missing_ts", iso_utc())
                recon[f"{key}_missing_reason"] = status
                updated = True
                _emit(
                    "RECON_ORDER_MISSING",
                    {
                        "event": "RECON_ORDER_MISSING",
                        "which": key,
                        "order_id": oid,
                        "status": status,
                        "symbol": ENV["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            if not status:
                recon.setdefault(f"{key}_unknown_ts", iso_utc())
                updated = True
                _emit(
                    "RECON_ORDER_UNKNOWN",
                    {
                        "event": "RECON_ORDER_UNKNOWN",
                        "which": key,
                        "order_id": oid,
                        "error": "status_missing",
                        "symbol": ENV["SYMBOL"],
                    },
                    f"recon:{key}:{oid}",
                )
                continue

            # Not in open_orders, but exchange says it's still "active-ish"
            # => visibility for operator, but no auto-repair.
            recon.setdefault(f"{key}_not_in_open_active_ts", iso_utc())
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
                    "symbol": ENV["SYMBOL"],
                },
                f"recon:{key}:{oid}:active:{status}",
            )
            continue

        if updated:
            pos["orders"] = orders
            save_state(st)
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

    if exits_flow.ensure_exits(st, pos, reason="retry", best_effort=True, attempt=tries):
        return


    if not ENV.get("FAILSAFE_FLATTEN", False):
        return
    max_tries = int(ENV.get("FAILSAFE_EXITS_MAX_TRIES") or 0)
    grace = float(ENV.get("FAILSAFE_EXITS_GRACE_SEC") or 0.0)
    first_fail_s = float(pos.get("exits_first_fail_s") or now)
    if max_tries and tries >= max_tries and (now - first_fail_s) >= grace:
        with suppress(Exception):
            binance_api.flatten_market(ENV["SYMBOL"], pos.get("side"), float(pos.get("qty") or 0.0), client_id=f"EX_FLAT_{int(time.time())}")
        _clear_position_slot(st, "FAILSAFE_FLATTEN", tries=tries)
def main() -> None:
    _validate_trade_mode()
    st = load_state()
    # Margin-guard startup hook (safe no-op unless TRADE_MODE=margin)
    # Best-effort shutdown hook for margin_guard (runs on SIGTERM and normal exit).
    # Must never affect trading logic.
    _shutdown_ran = False

    def _shutdown_hook() -> None:
        nonlocal _shutdown_ran
        if _shutdown_ran:
            return
        _shutdown_ran = True
        with suppress(Exception):
            st2 = load_state()
            margin_guard.on_shutdown(st2)

    with suppress(Exception):
        atexit.register(_shutdown_hook)

    # Docker stop => SIGTERM. Don't touch SIGINT (KeyboardInterrupt already handled elsewhere).
    with suppress(Exception):
        def _sigterm_handler(signum, frame) -> None:
            with suppress(Exception):
                log_event("SIGTERM", signum=signum)
            _shutdown_hook()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, _sigterm_handler)
    with suppress(Exception):
        margin_guard.on_startup(st)
    # Seed dedup keys with tail so we don't replay old PEAKs after fresh install

    # Always bootstrap seen_keys on start (safe by default)
    tail = read_tail_lines(ENV["DELTASCOUT_LOG"], ENV["TAIL_LINES"])
    bootstrap_seen_keys_from_tail(st, tail)

    pos = st.get("position") if isinstance(st, dict) else None
    pos_exists = isinstance(pos, dict) and bool(pos)
    orders = pos.get("orders") if pos_exists and isinstance(pos.get("orders"), dict) else {}
    log_event(
        "BOOT_REHYDRATE",
        position_exists=pos_exists,
        status=pos.get("status") if pos_exists else None,
        trail_active=pos.get("trail_active") if pos_exists else None,
        order_sl=orders.get("sl") if pos_exists else None,
        order_tp1=orders.get("tp1") if pos_exists else None,
        order_tp2=orders.get("tp2") if pos_exists else None,
    )

    log_event("BOOT", trade_mode=ENV["TRADE_MODE"], symbol=ENV["SYMBOL"])
    with suppress(Exception):
        _preflight_margin_cross_usdc()
    with suppress(Exception):
        sync_from_binance(st, reason="BOOT")

    # Optional: one-shot connectivity/auth check (useful before going live)
    if ENV.get("LIVE_VALIDATE_ONLY"):
        try:
            binance_api.binance_sanity_check()
            log_event("LIVE_VALIDATE_ONLY_DONE")
        except Exception as e:
            log_event("LIVE_VALIDATE_ONLY_FAIL", error=str(e))
            raise
        return

    last_manage_s = 0.0
    next_invar_s = 0.0



    while True:
        time.sleep(ENV["POLL_SEC"])
        st = load_state()  # <-- critical: pick up external state changes
        loop_now_s = _now_s()
        if ENV.get("INVAR_ENABLED") and loop_now_s >= float(next_invar_s):
            with suppress(Exception):
                invariants.run(st)
            next_invar_s = loop_now_s + float(ENV.get("INVAR_EVERY_SEC") or 20)
        posi = st.get("position") or {}
        if posi and posi.get("mode") == "live" and str(posi.get("status", "")).upper() in (
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
        if posi.get("mode") == "live" and posi.get("status") == "PENDING":
            try:
                last_poll = float(posi.get("last_poll_s", 0.0))
                now_s = _now_s()
                if now_s - last_poll >= float(ENV["LIVE_STATUS_POLL_EVERY"]):
                    oid = int(posi.get("order_id") or 0)
                    if oid:
                        od = binance_api.check_order_status(ENV["SYMBOL"], oid)
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
                            with suppress(Exception):
                                margin_guard.on_after_entry_opened(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
                            # Place TP1/TP2/SL (no OCO) right after fill confirmation
                            if not posi.get("orders") and posi.get("prices"):
                                exits_flow.ensure_exits(st, posi, reason="filled", best_effort=True)

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
                        od_t = binance_api.check_order_status(ENV["SYMBOL"], oid)
                        exq_t = float(od_t.get("executedQty") or 0.0)

                        def _try_place_exits_now() -> None:
                            # Best-effort immediate exits placement (reduces naked exposure window).
                            if posi.get("orders") or not posi.get("prices"):
                                return
                            exits_flow.ensure_exits(st, posi, reason="try_now", best_effort=True, save_on_fail=True)

                        if exq_t > 0.0:
                            # Order partially/fully filled: keep the filled part and proceed to exits.
                            with suppress(Exception):
                                binance_api.cancel_order(ENV["SYMBOL"], oid)
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
                            with suppress(Exception):
                                margin_guard.on_after_entry_opened(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
                            _try_place_exits_now()
                        else:
                            # Cancel LIMIT (best-effort)
                            with suppress(Exception):
                                binance_api.cancel_order(ENV["SYMBOL"], oid)

                            # Re-check once after cancel to catch a late fill (avoid double-entry).
                            od_after = None
                            with suppress(Exception):
                                od_after = binance_api.check_order_status(ENV["SYMBOL"], oid)
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
                                    with suppress(Exception):
                                        margin_guard.on_after_entry_opened(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid))
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
                                    px_exec = binance_api._planb_exec_price(ENV["SYMBOL"], entry_side)
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
                                with suppress(Exception):
                                    margin_guard.on_before_entry(st, ENV["SYMBOL"], entry_side, float(posi.get("qty") or 0.0), plan={
                                        "trade_key": posi.get("trade_key") or posi.get("client_id") or posi.get("order_id"),
                                    })
                                try:
                                    mkt = binance_api.place_spot_market(ENV["SYMBOL"], entry_side, float(posi.get("qty") or 0.0), client_id=f"EX_EN_MKT_{int(time.time())}")
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
                                        od2 = binance_api.check_order_status(ENV["SYMBOL"], int(oid2))
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
                                            with suppress(Exception):
                                                margin_guard.on_after_entry_opened(st, trade_key=str(posi.get("trade_key") or posi.get("client_id") or posi.get("order_id") or oid2))
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
        last_peak_ts_dt = event_dedup._dt_utc(meta.get("last_peak_ts"))

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

            dt = event_dedup._dt_utc(evt.get("ts"))

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


        # 2) Live V1.5 management (TP1 -> SL to BE) — throttled
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
                dt_evt = event_dedup._dt_utc(evt.get("ts"))
                if dt_evt is not None:
                    age = _now_s() - float(dt_evt.timestamp())
                    if age > max_age:
                        log_event("SKIP_PEAK", reason="stale_peak", age_sec=round(age, 3), evt_ts=str(evt.get("ts")))
                        continue
            with suppress(Exception):
                sync_from_binance(st, reason="PEAK_EVENT")

            if locked(st):
                log_event("SKIP_PEAK", reason="position_lock")
                continue
            if in_cooldown(st):
                log_event("SKIP_PEAK", reason="cooldown")
                continue
            if has_open_position(st):
                log_event("SKIP_PEAK", reason="position_already_open")
                continue

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
                    with suppress(Exception):
                        margin_guard.on_before_entry(st, ENV["SYMBOL"], side, float(qty), plan={
                            "trade_key": client_id,
                            "entry_price": entry,
                        })
                    order = binance_api.place_spot_market(ENV["SYMBOL"], side, qty, client_id=client_id)
                    exq0 = float(order.get("executedQty") or 0.0)
                    status0 = "OPEN_FILLED" if exq0 > 0.0 else "PENDING"
                    avgp0 = _avg_fill_price(order)
                    entry_actual0 = float(fmt_price(avgp0)) if avgp0 else None
                else:
                    with suppress(Exception):
                        margin_guard.on_before_entry(st, ENV["SYMBOL"], side, float(qty), plan={
                            "trade_key": client_id,
                            "entry_price": entry,
                        })
                    order = binance_api.place_spot_limit(ENV["SYMBOL"], side, qty, entry, client_id=client_id)
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
                    "trade_key": client_id,
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
                baseline_log = None
                baseline = st.get("baseline")
                if not isinstance(baseline, dict):
                    baseline = {}
                active_snap = baseline.get("active")
                active_key = active_snap.get("trade_key") if isinstance(active_snap, dict) else None
                trade_key = st["position"].get("trade_key") or st["position"].get("client_id")
                if active_snap is None or active_key != trade_key:
                    try:
                        snap = baseline_policy.take_snapshot(
                            binance_api,
                            ENV,
                            ENV["SYMBOL"],
                            trade_key,
                            "pre_trade",
                        )
                        baseline["active"] = snap
                        if baseline.get("truth") is not None and not isinstance(baseline.get("truth"), dict):
                            baseline["truth"] = None
                        baseline.setdefault("truth", None)
                        st["baseline"] = baseline
                        baseline_log = {
                            "which": "active",
                            "trade_key": trade_key,
                            "symbol": snap.get("symbol"),
                            "trade_mode": snap.get("trade_mode"),
                        }
                    except Exception as e:
                        log_event("BASELINE_ERROR", which="active", trade_key=trade_key, error=str(e))
                if status0 == "OPEN_FILLED":
                    pos0 = st.get("position") or {}
                    with suppress(Exception):
                        margin_guard.on_after_entry_opened(st, trade_key=(pos0.get("trade_key") or pos0.get("client_id") or pos0.get("order_id")))
                    if (not pos0.get("orders")) and pos0.get("prices"):
                        exits_flow.ensure_exits(st, pos0, reason="open_filled", best_effort=True, save_on_success=False)
                save_state(st)
                if baseline_log is not None:
                    log_event("BASELINE_TAKEN", **baseline_log)

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
