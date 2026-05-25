#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""executor.py
Executor — execution engine for DeltaScout PEAK signals.

Design goals
- Reads DeltaScout JSONL events from a shared log file (DELTASCOUT_LOG)
- Single-position mode: ignores new PEAK while a position is OPEN/PENDING
- Writes ONLY to its own state/log files (never appends to deltascout.log)
- Keeps executor log capped to LOG_MAX_LINES (default: 5000)

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
import executor_mod.trade_outcome_archive as trade_outcome_archive
import executor_mod.trade_execution_snapshot as trade_execution_snapshot
import executor_mod.trade_close_summary as trade_close_summary
import executor_mod.market_data as market_data
import executor_mod.exits_flow as exits_flow
import executor_mod.llm_trade_judge as llm_trade_judge
import executor_mod.position_finalization as position_finalization
import executor_mod.entry_math as entry_math
import executor_mod.close_reporting as close_reporting
import executor_mod.exit_orders as exit_orders
import executor_mod.reconciliation as reconciliation
from executor_mod.risk_math import (
    floor_to_step,
    ceil_to_step,
    round_nearest_to_step,
    _decimals_from_step,
    fmt_price,
    fmt_qty,
    round_qty,
)
from executor_mod import order_utils, open_filled_retry, live_position_manager
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
"LOG_MAX_LINES": _get_int("LOG_MAX_LINES", 5000),
"LLM_TRADE_JUDGE_ENABLED": _get_bool("LLM_TRADE_JUDGE_ENABLED", False),
"LLM_TRADE_JUDGE_VERDICTS_FN": os.getenv("LLM_TRADE_JUDGE_VERDICTS_FN", "/data/state/llm_trade_verdicts.jsonl"),
"TRADE_EXECUTION_SNAPSHOTS_FN": os.getenv("TRADE_EXECUTION_SNAPSHOTS_FN", "/data/state/trade_execution_snapshots.jsonl"),
"LLM_TRADE_JUDGE_SCORE_EXCLUDE_KEYS": _get_str("LLM_TRADE_JUDGE_SCORE_EXCLUDE_KEYS", "EX_EN_1778689753"),
"LLM_TRADE_JUDGE_MODE": _get_str("LLM_TRADE_JUDGE_MODE", "stub"),
"LLM_TRADE_JUDGE_MODEL": _get_str("LLM_TRADE_JUDGE_MODEL", "gpt-5.5"),
"LLM_TRADE_JUDGE_TIMEOUT_SEC": _get_float("LLM_TRADE_JUDGE_TIMEOUT_SEC", 20.0),
"LLM_TRADE_JUDGE_MAX_RETRIES": _get_int("LLM_TRADE_JUDGE_MAX_RETRIES", 1),
"LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": _get_bool("LLM_TRADE_JUDGE_NOTIFY_TELEGRAM", True),
"LLM_TRADE_JUDGE_CONTEXT_ENABLED": _get_bool("LLM_TRADE_JUDGE_CONTEXT_ENABLED", True),
"LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS": _get_float("LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS", 24.0),
"LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS": _get_int("LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS", 5000),
"LLM_TRADE_JUDGE_DELTASCOUT_LOG": os.getenv("LLM_TRADE_JUDGE_DELTASCOUT_LOG", os.getenv("DELTASCOUT_LOG", "/data/logs/deltascout.log")),
"LLM_TRADE_JUDGE_AGG_CSV": os.getenv("LLM_TRADE_JUDGE_AGG_CSV", os.getenv("AGG_CSV", "/data/feed/aggregated.csv")),
"LLM_TRADE_JUDGE_FEED_TIMEZONE": os.getenv("LLM_TRADE_JUDGE_FEED_TIMEZONE", os.getenv("FEED_SOURCE_TIMEZONE", "Europe/Bratislava")),

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

# Binance
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
}


# ===================== Time/IO helpers =====================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: Optional[datetime] = None) -> str:
    return (dt or now_utc()).isoformat()

def _validate_trade_mode() -> str:
    mode = str(ENV.get("TRADE_MODE", "")).strip().lower()
    if mode not in ("spot", "margin"):
        raise RuntimeError("unsupported mode removed; use TRADE_MODE=spot or TRADE_MODE=margin")
    ENV["TRADE_MODE"] = mode
    return mode

def _exchange_position_exists(symbol: str) -> Optional[bool]:
    return reconciliation.exchange_position_exists(symbol, env=ENV, binance_api=binance_api)

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
    margin_guard.configure(
        ENV,
        log_event,
        api=binance_api,
        save_state_fn=save_state,
        send_webhook_fn=send_webhook,
    )
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
    margin_guard.configure(
        ENV,
        log_event,
        api=binance_api,
        save_state_fn=save_state,
        send_webhook_fn=send_webhook,
    )

# ===================== DeltaScout event normalization / dedup =====================
# (moved to executor_mod.event_dedup)

# ===================== Rounding / sizing =====================

def _oid_int(v: Any) -> Optional[int]:
    return order_utils.oid_int(v)

def _avg_fill_price(order: Dict[str, Any]) -> Optional[float]:
    return order_utils.avg_fill_price(order)

# Backward-compatible name (kept for any leftover uses)


def _record_trade_execution_snapshot(st: Dict[str, Any], source: str, *, enrich_exchange: bool = False) -> Optional[Dict[str, Any]]:
    return close_reporting.record_trade_execution_snapshot(
        st,
        source,
        enrich_exchange=enrich_exchange,
        binance_api=binance_api,
        log_event=log_event,
        trade_execution_snapshot=trade_execution_snapshot,
    )


def _quote_asset(symbol: str) -> str:
    return close_reporting.quote_asset(symbol)


def _commission_usdc_valuation(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return close_reporting.commission_usdc_valuation(snapshot, binance_api=binance_api)


def _send_trade_closed_summary(st: Dict[str, Any], snapshot: Optional[Dict[str, Any]]) -> None:
    close_reporting.send_trade_closed_summary(
        st,
        snapshot,
        binance_api=binance_api,
        log_event=log_event,
        send_webhook=send_webhook,
        trade_execution_snapshot=trade_execution_snapshot,
        trade_close_summary=trade_close_summary,
    )

# Wire runtime dependencies for binance_api (keeps call sites unchanged).

risk_math.configure(ENV)
entry_math.configure(ENV)
binance_api.configure(ENV, fmt_qty=risk_math.fmt_qty, fmt_price=risk_math.fmt_price, round_qty=risk_math.round_qty)


def build_entry_price(kind: str, close_price: float) -> float:
    return entry_math.build_entry_price(kind, close_price)

def notional_to_qty(entry: float, usd: float) -> float:
    return entry_math.notional_to_qty(entry, usd)


def validate_qty(qty: float, entry: float) -> bool:
    return entry_math.validate_qty(qty, entry)

# ===================== Market context =====================

def load_df_sorted() -> pd.DataFrame:
    return market_data.load_df_sorted()

def locate_index_by_ts(df: pd.DataFrame, ts: datetime) -> int:
    return market_data.locate_index_by_ts(df, ts)


def latest_price(df: pd.DataFrame) -> float:
    return market_data.latest_price(df)

# ===================== Stop / TP ("far" stop logic) =====================

def swing_stop_far(df: pd.DataFrame, i: int, side: str, entry: float) -> float:
    return entry_math.swing_stop_far(df, i, side, entry)


def compute_tps(entry: float, sl: float, side: str) -> List[float]:
    return entry_math.compute_tps(entry, sl, side)

# ===================== Binance adapter =====================

def _planb_market_allowed(posi: Dict[str, Any], px_exec: float) -> Tuple[bool, str, Dict[str, Any]]:
    return entry_math._planb_market_allowed(posi, px_exec)


def _clear_position_slot(st: Dict[str, Any], reason: str, **fields: Any) -> None:
    """Fail-safe cleanup: free position slot so new PEAKs can be handled."""
    pos = st.get("position")
    st["last_closed"] = position_finalization.build_clear_position_last_closed(
        pos or {}, reason, iso_utc(), fields
    )
    _record_trade_execution_snapshot(st, "_clear_position_slot", enrich_exchange=False)
    st["position"] = None

    # unlock; avoid blocking next PEAK for no reason
    st["lock_until"] = 0.0
    save_state(st)
    with suppress(Exception):
        trade_outcome_archive.record_outcome(st, "_clear_position_slot", ENV.get("SYMBOL", ""))
        # Margin safety: if borrow happened but entry failed/canceled, repay here best-effort.
    with suppress(Exception):
        tk = (pos or {}).get("trade_key") or (pos or {}).get("client_id") or (pos or {}).get("order_id")
        margin_guard.on_after_position_closed(st, trade_key=tk)


def validate_exit_plan(symbol: str, side: str, qty_total: float, prices: Dict[str, float]) -> Dict[str, Any]:
    return exit_orders.validate_exit_plan(
        symbol,
        side,
        qty_total,
        prices,
        env=ENV,
        round_qty_fn=round_qty,
        split_qty_3legs_validate_fn=risk_math.split_qty_3legs_validate,
    )

# === FIX 1: Helpers for safer Plan B and LIMIT_MAKER fallback ===

def _is_limit_maker_reject(exc: Exception) -> bool:
    return exit_orders.is_limit_maker_reject(exc)


def _place_limit_maker_then_limit(payload: dict) -> dict:
    return exit_orders.place_limit_maker_then_limit(
        payload,
        place_order_raw_fn=binance_api.place_order_raw,
        log_event_fn=log_event,
    )

def place_exits_v15(symbol: str, side: str, qty_total: float, prices: Dict[str, float]) -> Dict[str, Any]:
    return exit_orders.place_exits_v15(
        symbol,
        side,
        qty_total,
        prices,
        env=ENV,
        place_order_raw_fn=binance_api.place_order_raw,
        cancel_order_fn=binance_api.cancel_order,
        log_event_fn=log_event,
        round_qty_fn=round_qty,
        split_qty_3legs_place_fn=risk_math.split_qty_3legs_place,
        fmt_qty_fn=fmt_qty,
        fmt_price_fn=fmt_price,
        time_fn=time.time,
    )
# Wire runtime dependencies for exits placement flow (keeps call sites unchanged).
exits_flow.configure(
    ENV,
    save_state_fn=lambda st: save_state(st),
    log_event_fn=lambda *a, **k: log_event(*a, **k),
    send_webhook_fn=lambda payload: send_webhook(payload),
    validate_exit_plan_fn=lambda *a, **k: validate_exit_plan(*a, **k),
    place_exits_v15_fn=lambda *a, **k: place_exits_v15(*a, **k),
    post_exits_success_hook_fn=lambda st, pos, trigger="EXITS_PLACED_V15": llm_trade_judge.maybe_record_llm_pretrade_judge(st, pos, trigger=trigger),
)
llm_trade_judge.configure(
    ENV,
    save_state_fn=lambda st: save_state(st),
    log_event_fn=lambda *a, **k: log_event(*a, **k),
    send_webhook_fn=lambda payload: send_webhook(payload),
)

def manage_v15_position(symbol: str, st: Dict[str, Any]) -> None:
    return live_position_manager.manage_v15_position(
        symbol,
        st,
        env=ENV,
        binance_api=binance_api,
        save_state_fn=save_state,
        log_event_fn=log_event,
        send_webhook_fn=send_webhook,
        now_fn=_now_s,
        iso_utc_fn=iso_utc,
        time_module=time,
        round_qty_fn=round_qty,
        fmt_qty_fn=fmt_qty,
        fmt_price_fn=fmt_price,
        oid_int_fn=_oid_int,
        trail_desired_stop_fn=_trail_desired_stop_from_agg,
        record_trade_execution_snapshot_fn=_record_trade_execution_snapshot,
        send_trade_closed_summary_fn=_send_trade_closed_summary,
        build_live_close_last_closed_fn=position_finalization.build_live_close_last_closed,
        record_outcome_fn=trade_outcome_archive.record_outcome,
        margin_after_position_closed_fn=margin_guard.on_after_position_closed,
    )


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
    mid_usdt = binance_api.get_mid_price("BTCUSDT")
    mid_usdc = binance_api.get_mid_price("BTCUSDC")
    return mid_usdc / mid_usdt

def sync_from_binance(st: Dict[str, Any]) -> None:
    reconciliation.sync_from_binance(
        st,
        env=ENV,
        binance_api=binance_api,
        save_state_fn=save_state,
        log_event_fn=log_event,
        send_webhook_fn=send_webhook,
        iso_utc_fn=iso_utc,
        time_module=time,
        exchange_position_exists_fn=_exchange_position_exists,
        record_trade_execution_snapshot_fn=_record_trade_execution_snapshot,
        record_outcome_fn=trade_outcome_archive.record_outcome,
        margin_after_position_closed_fn=margin_guard.on_after_position_closed,
        build_sync_last_closed_fn=position_finalization.build_sync_last_closed,
    )

# ===================== Main loop =====================
def handle_open_filled_exits_retry(st: dict) -> None:
    open_filled_retry.handle_open_filled_exits_retry(
        st,
        env=ENV,
        save_state_fn=save_state,
        ensure_exits_fn=exits_flow.ensure_exits,
        flatten_market_fn=binance_api.flatten_market,
        clear_position_slot_fn=_clear_position_slot,
        now_fn=_now_s,
        time_fn=time.time,
    )

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
        sync_from_binance(st)

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
                        "source": evt.get("source"),
                        "action": evt.get("action"),
                        "delta": evt.get("delta"),
                        "vol": evt.get("vol"),
                        "imb": evt.get("imb"),
                        "price": evt.get("price"),
                        "vwap": evt.get("vwap"),
                        "poc": evt.get("poc"),
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
                    exits_placed_open_filled = False
                    if (not pos0.get("orders")) and pos0.get("prices"):
                        exits_placed_open_filled = exits_flow.ensure_exits(st, pos0, reason="open_filled", best_effort=True, save_on_success=False)
                save_state(st)
                if status0 == "OPEN_FILLED" and exits_placed_open_filled:
                    with suppress(Exception):
                        llm_trade_judge.maybe_record_llm_pretrade_judge(st, st.get("position") or {}, trigger="EXITS_PLACED_V15")
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
