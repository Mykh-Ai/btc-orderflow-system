# executor_mod/emergency.py
"""
Emergency Shutdown Mode — operator-controlled graceful shutdown with reconciliation.

Principles:
1. Fail-Aware, Not Fail-Loud: Alert operator immediately, but don't halt
2. Human-in-the-Loop: Operator decides when to shutdown, bot cooperates
3. Reconciliation-First: Check order states before clearing position
4. Fail-Safe: When in doubt, surrender control to human

Usage:
    from executor_mod import emergency

    # At startup (after other configure calls)
    emergency.configure(
        env=ENV,
        log_event_fn=log_event,
        send_webhook_fn=send_webhook,
        save_state_fn=save_state,
        check_order_status_fn=binance_api.check_order_status,
        margin_after_close_fn=margin_guard.on_after_position_closed,
    )

    # In main loop
    if emergency.check_flag():
        emergency.shutdown(st, "OPERATOR_FLAG")
        continue

    if emergency.check_sleep_mode(st):
        time.sleep(30)
        continue

    # Replace _save_state_best_effort with:
    emergency.save_state_safe(st, "some_context")
"""
from __future__ import annotations

import json
import os
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

# ============================================================================
# Configuration (Dependency Injection)
# ============================================================================

ENV: Dict[str, Any] = {}
_log_event: Optional[Callable[..., None]] = None
_send_webhook: Optional[Callable[[Dict[str, Any]], None]] = None
_save_state: Optional[Callable[[Dict[str, Any]], None]] = None
_check_order_status: Optional[Callable[[str, int], Dict[str, Any]]] = None
_margin_after_close: Optional[Callable[[Dict[str, Any]], None]] = None


def configure(
    env: Dict[str, Any],
    log_event_fn: Callable[..., None],
    send_webhook_fn: Callable[[Dict[str, Any]], None],
    save_state_fn: Callable[[Dict[str, Any]], None],
    check_order_status_fn: Optional[Callable[[str, int], Dict[str, Any]]] = None,
    margin_after_close_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """
    Configure emergency module with dependencies.

    Args:
        env: Environment config dict (needs SYMBOL, STATE_FN)
        log_event_fn: Function to log events (from notifications)
        send_webhook_fn: Function to send webhook alerts (from notifications)
        save_state_fn: Function to persist state (from state_store)
        check_order_status_fn: Function to check order status on exchange (from binance_api)
        margin_after_close_fn: Function to handle margin repay after close (from margin_guard)
    """
    global ENV, _log_event, _send_webhook, _save_state, _check_order_status, _margin_after_close
    ENV = env
    _log_event = log_event_fn
    _send_webhook = send_webhook_fn
    _save_state = save_state_fn
    _check_order_status = check_order_status_fn
    _margin_after_close = margin_after_close_fn


# ============================================================================
# Constants
# ============================================================================

def _state_dir() -> str:
    """Get state directory from ENV or default."""
    state_fn = ENV.get("STATE_FN", "/data/state/executor_state.json")
    return os.path.dirname(state_fn) or "/data/state"


def _emergency_flag_path() -> str:
    return os.path.join(_state_dir(), "emergency_shutdown.flag")


def _wake_up_flag_path() -> str:
    return os.path.join(_state_dir(), "wake_up.flag")


def _backup_state_path() -> str:
    return os.path.join(_state_dir(), "emergency_backup.json")


# Alert throttling
_ALERT_THROTTLE_SEC = 300.0  # 5 minutes between repeated alerts
_SUGGEST_SHUTDOWN_AFTER_N_FAILS = 3

# Terminal order statuses (order is done, no further action needed)
_TERMINAL_STATUSES = frozenset({
    "FILLED", "CANCELED", "EXPIRED", "REJECTED",
    "CANCELED_OR_FILLED",  # synthetic status for unknown orders
    "INVALID_ID",  # synthetic status for unparseable order IDs
})


# ============================================================================
# Helpers
# ============================================================================

def _iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_s() -> float:
    return time.time()


def _runtime(st: Dict[str, Any]) -> Dict[str, Any]:
    """Get or create emergency runtime state (not persisted)."""
    return st.setdefault("_emergency_runtime", {})


# ============================================================================
# Component 1: Alert on First Failure
# ============================================================================

def save_state_safe(st: Dict[str, Any], where: str) -> bool:
    """
    Attempt to save state. On failure, alert operator (throttled).

    Args:
        st: State dict to save
        where: Context string for logging (e.g., "sl_watchdog_market_ok")

    Returns:
        True if save succeeded, False if failed
    """
    if _save_state is None:
        return False

    try:
        _save_state(st)
        # Clear failure tracking on success
        rt = _runtime(st)
        rt.pop("save_fail_count", None)
        rt.pop("last_alert_ts", None)
        return True

    except Exception as e:
        rt = _runtime(st)
        fail_count = rt.get("save_fail_count", 0) + 1
        rt["save_fail_count"] = fail_count
        rt["last_save_error"] = str(e)
        rt["last_save_error_where"] = where

        # Log always (throttled by log_event internally if needed)
        # Wrapped in suppress to avoid cascading failures if logging also fails
        if _log_event:
            with suppress(Exception):
                _log_event(
                    "SAVE_STATE_FAILURE",
                    where=where,
                    error=str(e),
                    fail_count=fail_count,
                )

        # Alert via webhook (throttled)
        with suppress(Exception):
            _maybe_send_alert(st, where, str(e), fail_count)

        return False


def _maybe_send_alert(
    st: Dict[str, Any],
    where: str,
    error: str,
    fail_count: int,
) -> None:
    """Send webhook alert if not recently sent."""
    if _send_webhook is None:
        return

    rt = _runtime(st)
    now = _now_s()
    last_alert_ts = rt.get("last_alert_ts", 0.0)

    # First failure OR throttle expired → send alert
    if fail_count == 1 or (now - last_alert_ts) >= _ALERT_THROTTLE_SEC:
        rt["last_alert_ts"] = now

        payload: Dict[str, Any] = {
            "event": "🚨 SAVE_STATE_FAILURE",
            "where": where,
            "error": error,
            "fail_count": fail_count,
            "action": f"touch {_emergency_flag_path()}",
        }

        # Suggest shutdown after N failures
        if fail_count >= _SUGGEST_SHUTDOWN_AFTER_N_FAILS:
            payload["suggestion"] = "Consider emergency shutdown"
            payload["event"] = "🚨 CRITICAL: Multiple save failures"

        with suppress(Exception):
            _send_webhook(payload)


def get_save_fail_count(st: Dict[str, Any]) -> int:
    """Get current consecutive save failure count."""
    return _runtime(st).get("save_fail_count", 0)


# ============================================================================
# Component 2: Emergency Shutdown Trigger
# ============================================================================

def check_flag() -> bool:
    """
    Check if emergency shutdown flag exists.

    Operator creates this file to trigger graceful shutdown:
        touch /data/state/emergency_shutdown.flag

    Returns:
        True if flag exists
    """
    return os.path.exists(_emergency_flag_path())


def remove_flag() -> bool:
    """
    Remove emergency shutdown flag after processing.

    Returns:
        True if removed successfully, False if not exists or error
    """
    try:
        os.remove(_emergency_flag_path())
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def check_sleep_mode(st: Dict[str, Any]) -> bool:
    """
    Check if bot is in sleep mode.

    If wake_up.flag exists, exit sleep mode and resume.

    Returns:
        True if still in sleep mode (caller should continue/skip tick)
        False if not in sleep mode or just woke up
    """
    sleep_mode = st.get("sleep_mode")
    if not isinstance(sleep_mode, dict):
        return False

    if not sleep_mode.get("active"):
        return False

    # Check for wake up signal
    wake_path = _wake_up_flag_path()
    if os.path.exists(wake_path):
        # Wake up!
        sleep_mode["active"] = False
        sleep_mode["woke_up_at"] = _iso_utc()

        if _log_event:
            _log_event(
                "WAKE_UP",
                slept_since=sleep_mode.get("since"),
                reason=sleep_mode.get("reason"),
            )

        if _send_webhook:
            with suppress(Exception):
                _send_webhook({
                    "event": "✅ WAKE_UP",
                    "slept_since": sleep_mode.get("since"),
                    "reason": sleep_mode.get("reason"),
                })

        # Remove wake up flag
        with suppress(Exception):
            os.remove(wake_path)

        # Try to save (best effort)
        if _save_state:
            with suppress(Exception):
                _save_state(st)

        return False  # No longer in sleep mode

    # Still sleeping
    return True


# ============================================================================
# Component 3: Reconciliation-First Shutdown
# ============================================================================

def shutdown(st: Dict[str, Any], reason: str) -> bool:
    """
    Emergency shutdown procedure:
    1. Reconcile orders (check exchange status)
    2. Verify all terminal (FILLED/CANCELED/EXPIRED)
    3. Force finalize (best-effort margin repay)
    4. Backup state to emergency file
    5. Enter sleep mode

    Args:
        st: State dict
        reason: Shutdown reason (e.g., "OPERATOR_FLAG", "SAVE_FAILURE")

    Returns:
        True if shutdown completed, False if blocked (active orders)
    """
    if _log_event:
        _log_event("EMERGENCY_SHUTDOWN_START", reason=reason)

    if _send_webhook:
        with suppress(Exception):
            _send_webhook({
                "event": "🛑 EMERGENCY_SHUTDOWN_START",
                "reason": reason,
            })

    pos = st.get("position")
    symbol = ENV.get("SYMBOL", "BTCUSDC")

    # Step 1: Reconcile orders
    reconciled = _reconcile_orders(pos, symbol)

    if _log_event:
        _log_event("EMERGENCY_RECONCILE", reconciled=reconciled)

    # Step 2: Verify all terminal
    if reconciled:
        non_terminal = {
            k: v for k, v in reconciled.items()
            if v not in _TERMINAL_STATUSES and v != "ERROR"
        }

        if non_terminal:
            # Active orders still exist — cannot shutdown safely
            if _log_event:
                _log_event(
                    "EMERGENCY_BLOCKED_ACTIVE_ORDERS",
                    active_orders=non_terminal,
                )

            if _send_webhook:
                with suppress(Exception):
                    _send_webhook({
                        "event": "⚠️ EMERGENCY_BLOCKED",
                        "reason": "Active orders on exchange",
                        "active_orders": non_terminal,
                        "action": "Cancel orders manually on Binance, then retry",
                    })

            return False  # Blocked

    # Step 3: Force finalize (margin repay)
    if _margin_after_close:
        with suppress(Exception):
            _margin_after_close(st)

    # Build last_closed record
    st["last_closed"] = {
        "ts": _iso_utc(),
        "mode": "emergency",
        "reason": f"EMERGENCY_SHUTDOWN: {reason}",
        "reconciled": reconciled,
    }
    st["position"] = None
    st["cooldown_until"] = _now_s() + 3600.0  # 1 hour cooldown

    if _log_event:
        _log_event("EMERGENCY_SHUTDOWN_FORCE_FINALIZE", reason=reason)

    # Step 4: Backup state
    _backup_state(st, reason)

    # Step 5: Enter sleep mode
    st["sleep_mode"] = {
        "active": True,
        "since": _iso_utc(),
        "reason": reason,
        "wake_file": _wake_up_flag_path(),
    }

    # Try normal save (may fail, that's why we have backup)
    if _save_state:
        with suppress(Exception):
            _save_state(st)

    if _log_event:
        _log_event("SLEEP_MODE_ACTIVE", wake_file=_wake_up_flag_path())

    if _send_webhook:
        with suppress(Exception):
            _send_webhook({
                "event": "💤 SLEEP_MODE_ACTIVE",
                "reason": reason,
                "wake_file": _wake_up_flag_path(),
                "action": f"To resume: touch {_wake_up_flag_path()}",
            })

    return True


def _reconcile_orders(
    pos: Optional[Dict[str, Any]],
    symbol: str,
) -> Dict[str, str]:
    """
    Check status of tracked orders on exchange.

    Returns:
        Dict mapping order key (sl/tp1/tp2) to status string
    """
    if not pos or not isinstance(pos, dict):
        return {}

    orders = pos.get("orders")
    if not isinstance(orders, dict):
        return {}

    result: Dict[str, str] = {}

    for key in ("sl", "tp1", "tp2"):
        order_id = orders.get(key)
        if not order_id:
            continue

        try:
            order_id_int = int(order_id)
        except (TypeError, ValueError):
            result[key] = "INVALID_ID"
            continue

        if _check_order_status is None:
            result[key] = "NO_API"
            continue

        try:
            status_resp = _check_order_status(symbol, order_id_int)
            result[key] = status_resp.get("status", "UNKNOWN")
        except Exception as e:
            err_str = str(e)
            # Binance error -2013: Order does not exist
            if "-2013" in err_str or "UNKNOWN_ORDER" in err_str.upper():
                result[key] = "CANCELED_OR_FILLED"
            else:
                result[key] = "ERROR"

    return result


def _backup_state(st: Dict[str, Any], reason: str) -> bool:
    """
    Write state to emergency backup file.

    Uses default=str to handle non-serializable objects.

    Returns:
        True if backup succeeded
    """
    backup_path = _backup_state_path()

    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)

        backup_data = {
            "backup_ts": _iso_utc(),
            "backup_reason": reason,
            "state": st,
        }

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)

        if _log_event:
            _log_event("EMERGENCY_BACKUP_SAVED", path=backup_path)

        return True

    except Exception as e:
        if _log_event:
            _log_event("EMERGENCY_BACKUP_FAILED", path=backup_path, error=str(e))
        return False


# ============================================================================
# Component 4: Main Loop Integration Helpers
# ============================================================================

def should_suggest_shutdown(st: Dict[str, Any]) -> bool:
    """
    Check if we should suggest emergency shutdown to operator.

    Returns:
        True if fail_count >= threshold
    """
    return get_save_fail_count(st) >= _SUGGEST_SHUTDOWN_AFTER_N_FAILS


def get_status(st: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get emergency module status for diagnostics.

    Returns:
        Dict with current status info
    """
    rt = _runtime(st)
    sleep_mode = st.get("sleep_mode") or {}

    return {
        "flag_exists": check_flag(),
        "sleep_mode_active": sleep_mode.get("active", False),
        "save_fail_count": rt.get("save_fail_count", 0),
        "last_save_error": rt.get("last_save_error"),
        "last_save_error_where": rt.get("last_save_error_where"),
        "wake_file": _wake_up_flag_path(),
        "emergency_flag": _emergency_flag_path(),
    }
