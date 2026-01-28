# test/test_emergency.py
"""
Tests for executor_mod/emergency.py — Emergency Shutdown Mode.

Tests cover:
1. Component 1: Alert on First Failure (save_state_safe)
2. Component 2: Emergency Shutdown Trigger (check_flag, check_sleep_mode)
3. Component 3: Reconciliation-First Shutdown (shutdown)
4. Component 4: Integration helpers (should_suggest_shutdown, get_status)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from executor_mod import emergency


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_state_dir():
    """Create a temporary directory for state files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_env(temp_state_dir):
    """Create mock ENV with temp state directory."""
    return {
        "SYMBOL": "BTCUSDC",
        "STATE_FN": os.path.join(temp_state_dir, "executor_state.json"),
    }


@pytest.fixture
def mock_log_event():
    """Create a mock log_event that records calls."""
    calls: List[Dict[str, Any]] = []

    def log_event(event_name: str, **kwargs):
        calls.append({"event": event_name, **kwargs})

    log_event.calls = calls  # type: ignore
    return log_event


@pytest.fixture
def mock_send_webhook():
    """Create a mock send_webhook that records calls."""
    calls: List[Dict[str, Any]] = []

    def send_webhook(payload: Dict[str, Any]):
        calls.append(payload)

    send_webhook.calls = calls  # type: ignore
    return send_webhook


@pytest.fixture
def mock_save_state():
    """Create a mock save_state that can be configured to fail."""
    mock = MagicMock()
    mock.fail = False
    mock.fail_error = IOError("No space left on device")

    def save_state(st: Dict[str, Any]):
        if mock.fail:
            raise mock.fail_error
        mock.last_state = st.copy()

    mock.side_effect = save_state
    return mock


@pytest.fixture
def mock_check_order_status():
    """Create a mock check_order_status that returns configurable responses."""
    responses: Dict[int, Dict[str, Any]] = {}

    def check_order_status(symbol: str, order_id: int) -> Dict[str, Any]:
        if order_id in responses:
            resp = responses[order_id]
            if isinstance(resp, Exception):
                raise resp
            return resp
        return {"status": "FILLED"}

    check_order_status.responses = responses  # type: ignore
    return check_order_status


@pytest.fixture
def mock_margin_after_close():
    """Create a mock margin_after_close."""
    return MagicMock()


@pytest.fixture
def configured_emergency(
    mock_env,
    mock_log_event,
    mock_send_webhook,
    mock_save_state,
    mock_check_order_status,
    mock_margin_after_close,
):
    """Configure emergency module with all mocks."""
    emergency.configure(
        env=mock_env,
        log_event_fn=mock_log_event,
        send_webhook_fn=mock_send_webhook,
        save_state_fn=mock_save_state.side_effect,
        check_order_status_fn=mock_check_order_status,
        margin_after_close_fn=mock_margin_after_close,
    )
    yield {
        "env": mock_env,
        "log_event": mock_log_event,
        "send_webhook": mock_send_webhook,
        "save_state": mock_save_state,
        "check_order_status": mock_check_order_status,
        "margin_after_close": mock_margin_after_close,
    }
    # Cleanup: reset module state
    emergency.ENV = {}
    emergency._log_event = None
    emergency._send_webhook = None
    emergency._save_state = None
    emergency._check_order_status = None
    emergency._margin_after_close = None


# ============================================================================
# Component 1: Alert on First Failure
# ============================================================================

class TestSaveStateSafe:
    """Tests for save_state_safe function."""

    def test_save_success_returns_true(self, configured_emergency):
        """Successful save returns True."""
        st = {"position": None}
        result = emergency.save_state_safe(st, "test_context")
        assert result is True

    def test_save_success_clears_fail_count(self, configured_emergency):
        """Successful save clears failure tracking."""
        st = {"_emergency_runtime": {"save_fail_count": 5}}
        emergency.save_state_safe(st, "test_context")
        assert emergency.get_save_fail_count(st) == 0

    def test_save_failure_returns_false(self, configured_emergency):
        """Failed save returns False."""
        configured_emergency["save_state"].fail = True
        st = {"position": None}
        result = emergency.save_state_safe(st, "test_context")
        assert result is False

    def test_save_failure_increments_fail_count(self, configured_emergency):
        """Failed save increments failure count."""
        configured_emergency["save_state"].fail = True
        st = {}

        emergency.save_state_safe(st, "context1")
        assert emergency.get_save_fail_count(st) == 1

        emergency.save_state_safe(st, "context2")
        assert emergency.get_save_fail_count(st) == 2

        emergency.save_state_safe(st, "context3")
        assert emergency.get_save_fail_count(st) == 3

    def test_first_failure_sends_alert(self, configured_emergency):
        """First failure sends webhook alert."""
        configured_emergency["save_state"].fail = True
        st = {}

        emergency.save_state_safe(st, "test_context")

        calls = configured_emergency["send_webhook"].calls
        assert len(calls) == 1
        assert "SAVE_STATE_FAILURE" in calls[0]["event"]
        assert calls[0]["fail_count"] == 1

    def test_alert_throttled(self, configured_emergency):
        """Repeated failures don't spam alerts (throttled)."""
        configured_emergency["save_state"].fail = True
        st = {}

        # First failure → alert
        emergency.save_state_safe(st, "context1")
        # Second failure immediately → NO new alert (throttled)
        emergency.save_state_safe(st, "context2")

        calls = configured_emergency["send_webhook"].calls
        assert len(calls) == 1  # Only one alert

    def test_alert_after_throttle_expires(self, configured_emergency):
        """Alert sent again after throttle expires."""
        configured_emergency["save_state"].fail = True
        st = {}

        # First failure
        emergency.save_state_safe(st, "context1")

        # Simulate throttle expiry
        rt = st.get("_emergency_runtime", {})
        rt["last_alert_ts"] = time.time() - 400  # 400 sec ago (> 300 sec throttle)

        # Another failure → should alert again
        emergency.save_state_safe(st, "context2")

        calls = configured_emergency["send_webhook"].calls
        assert len(calls) == 2

    def test_suggest_shutdown_after_n_failures(self, configured_emergency):
        """After N failures, alert suggests shutdown."""
        configured_emergency["save_state"].fail = True
        st = {}

        # Simulate already having 2 failures + expired throttle
        st["_emergency_runtime"] = {
            "save_fail_count": 2,
            "last_alert_ts": 0,  # Expired
        }

        emergency.save_state_safe(st, "context3")

        calls = configured_emergency["send_webhook"].calls
        assert len(calls) == 1
        assert "CRITICAL" in calls[0]["event"]
        assert "suggestion" in calls[0]

    def test_log_event_called_on_failure(self, configured_emergency):
        """Log event called on every failure."""
        configured_emergency["save_state"].fail = True
        st = {}

        emergency.save_state_safe(st, "my_context")

        log_calls = configured_emergency["log_event"].calls
        assert len(log_calls) == 1
        assert log_calls[0]["event"] == "SAVE_STATE_FAILURE"
        assert log_calls[0]["where"] == "my_context"


# ============================================================================
# Component 2: Emergency Shutdown Trigger
# ============================================================================

class TestCheckFlag:
    """Tests for check_flag and remove_flag functions."""

    def test_no_flag_returns_false(self, configured_emergency):
        """No flag file → returns False."""
        assert emergency.check_flag() is False

    def test_flag_exists_returns_true(self, configured_emergency, temp_state_dir):
        """Flag file exists → returns True."""
        flag_path = os.path.join(temp_state_dir, "emergency_shutdown.flag")
        with open(flag_path, "w") as f:
            f.write("")

        assert emergency.check_flag() is True

    def test_remove_flag_success(self, configured_emergency, temp_state_dir):
        """Remove flag returns True on success."""
        flag_path = os.path.join(temp_state_dir, "emergency_shutdown.flag")
        with open(flag_path, "w") as f:
            f.write("")

        assert emergency.remove_flag() is True
        assert not os.path.exists(flag_path)

    def test_remove_flag_not_exists(self, configured_emergency):
        """Remove flag returns False if not exists."""
        assert emergency.remove_flag() is False


class TestCheckSleepMode:
    """Tests for check_sleep_mode function."""

    def test_no_sleep_mode_returns_false(self, configured_emergency):
        """No sleep_mode in state → returns False."""
        st = {}
        assert emergency.check_sleep_mode(st) is False

    def test_sleep_mode_inactive_returns_false(self, configured_emergency):
        """sleep_mode.active=False → returns False."""
        st = {"sleep_mode": {"active": False}}
        assert emergency.check_sleep_mode(st) is False

    def test_sleep_mode_active_returns_true(self, configured_emergency):
        """sleep_mode.active=True without wake_up.flag → returns True."""
        st = {"sleep_mode": {"active": True, "since": "2026-01-28T10:00:00"}}
        assert emergency.check_sleep_mode(st) is True

    def test_wake_up_flag_exits_sleep_mode(self, configured_emergency, temp_state_dir):
        """wake_up.flag exists → exits sleep mode, returns False."""
        wake_path = os.path.join(temp_state_dir, "wake_up.flag")
        with open(wake_path, "w") as f:
            f.write("")

        st = {"sleep_mode": {"active": True, "since": "2026-01-28T10:00:00"}}
        result = emergency.check_sleep_mode(st)

        assert result is False
        assert st["sleep_mode"]["active"] is False
        assert "woke_up_at" in st["sleep_mode"]

    def test_wake_up_removes_flag(self, configured_emergency, temp_state_dir):
        """Wake up removes the wake_up.flag file."""
        wake_path = os.path.join(temp_state_dir, "wake_up.flag")
        with open(wake_path, "w") as f:
            f.write("")

        st = {"sleep_mode": {"active": True}}
        emergency.check_sleep_mode(st)

        assert not os.path.exists(wake_path)

    def test_wake_up_logs_and_webhooks(self, configured_emergency, temp_state_dir):
        """Wake up sends log event and webhook."""
        wake_path = os.path.join(temp_state_dir, "wake_up.flag")
        with open(wake_path, "w") as f:
            f.write("")

        st = {"sleep_mode": {"active": True, "reason": "TEST"}}
        emergency.check_sleep_mode(st)

        log_calls = configured_emergency["log_event"].calls
        assert any(c["event"] == "WAKE_UP" for c in log_calls)

        webhook_calls = configured_emergency["send_webhook"].calls
        assert any("WAKE_UP" in c.get("event", "") for c in webhook_calls)


# ============================================================================
# Component 3: Reconciliation-First Shutdown
# ============================================================================

class TestShutdown:
    """Tests for shutdown function."""

    def test_shutdown_with_no_position(self, configured_emergency):
        """Shutdown with no position succeeds."""
        st = {"position": None}
        result = emergency.shutdown(st, "TEST_REASON")

        assert result is True
        assert st["position"] is None
        assert st["sleep_mode"]["active"] is True
        assert "last_closed" in st

    def test_shutdown_clears_position(self, configured_emergency):
        """Shutdown clears position."""
        st = {
            "position": {
                "status": "OPEN_FILLED",
                "side": "BUY",
                "orders": {},
            }
        }
        result = emergency.shutdown(st, "TEST")

        assert result is True
        assert st["position"] is None

    def test_shutdown_sets_cooldown(self, configured_emergency):
        """Shutdown sets 1 hour cooldown."""
        st = {"position": None}
        before = time.time()
        emergency.shutdown(st, "TEST")
        after = time.time()

        # Cooldown should be ~1 hour from now
        assert st["cooldown_until"] >= before + 3600
        assert st["cooldown_until"] <= after + 3600 + 1

    def test_shutdown_reconciles_orders(self, configured_emergency):
        """Shutdown reconciles order statuses."""
        # Setup order responses
        configured_emergency["check_order_status"].responses[12345] = {"status": "FILLED"}
        configured_emergency["check_order_status"].responses[12346] = {"status": "CANCELED"}

        st = {
            "position": {
                "status": "OPEN_FILLED",
                "orders": {"sl": 12345, "tp1": 12346},
            }
        }
        result = emergency.shutdown(st, "TEST")

        assert result is True
        assert st["last_closed"]["reconciled"] == {"sl": "FILLED", "tp1": "CANCELED"}

    def test_shutdown_blocked_by_active_orders(self, configured_emergency):
        """Shutdown blocked if orders still active."""
        # Order is still NEW (not terminal)
        configured_emergency["check_order_status"].responses[12345] = {"status": "NEW"}

        st = {
            "position": {
                "status": "OPEN_FILLED",
                "orders": {"sl": 12345},
            }
        }
        result = emergency.shutdown(st, "TEST")

        assert result is False  # Blocked!
        assert st["position"] is not None  # Position NOT cleared

    def test_shutdown_calls_margin_repay(self, configured_emergency):
        """Shutdown calls margin_after_close hook."""
        st = {"position": None}
        emergency.shutdown(st, "TEST")

        configured_emergency["margin_after_close"].assert_called_once_with(st)

    def test_shutdown_creates_backup(self, configured_emergency, temp_state_dir):
        """Shutdown creates backup file."""
        st = {"position": None, "some_data": "test"}
        emergency.shutdown(st, "TEST_REASON")

        backup_path = os.path.join(temp_state_dir, "emergency_backup.json")
        assert os.path.exists(backup_path)

        with open(backup_path) as f:
            backup = json.load(f)

        assert backup["backup_reason"] == "TEST_REASON"
        assert "state" in backup

    def test_shutdown_enters_sleep_mode(self, configured_emergency):
        """Shutdown enters sleep mode."""
        st = {"position": None}
        emergency.shutdown(st, "MY_REASON")

        assert st["sleep_mode"]["active"] is True
        assert st["sleep_mode"]["reason"] == "MY_REASON"
        assert "wake_file" in st["sleep_mode"]

    def test_shutdown_unknown_order_treated_as_terminal(self, configured_emergency):
        """Unknown order (-2013 error) treated as terminal."""
        # Simulate Binance error for unknown order
        configured_emergency["check_order_status"].responses[99999] = \
            Exception('{"code":-2013,"msg":"Order does not exist."}')

        st = {
            "position": {
                "status": "OPEN_FILLED",
                "orders": {"sl": 99999},
            }
        }
        result = emergency.shutdown(st, "TEST")

        assert result is True  # Should succeed (order is terminal)
        assert st["last_closed"]["reconciled"]["sl"] == "CANCELED_OR_FILLED"

    def test_shutdown_logs_events(self, configured_emergency):
        """Shutdown logs appropriate events."""
        st = {"position": None}
        emergency.shutdown(st, "TEST")

        log_calls = configured_emergency["log_event"].calls
        events = [c["event"] for c in log_calls]

        assert "EMERGENCY_SHUTDOWN_START" in events
        assert "EMERGENCY_RECONCILE" in events
        assert "EMERGENCY_SHUTDOWN_FORCE_FINALIZE" in events
        assert "SLEEP_MODE_ACTIVE" in events


# ============================================================================
# Component 4: Integration Helpers
# ============================================================================

class TestIntegrationHelpers:
    """Tests for integration helper functions."""

    def test_should_suggest_shutdown_false_initially(self, configured_emergency):
        """should_suggest_shutdown returns False with no failures."""
        st = {}
        assert emergency.should_suggest_shutdown(st) is False

    def test_should_suggest_shutdown_true_after_n_fails(self, configured_emergency):
        """should_suggest_shutdown returns True after N failures."""
        st = {"_emergency_runtime": {"save_fail_count": 3}}
        assert emergency.should_suggest_shutdown(st) is True

    def test_get_status_returns_all_info(self, configured_emergency, temp_state_dir):
        """get_status returns comprehensive status dict."""
        st = {
            "_emergency_runtime": {
                "save_fail_count": 2,
                "last_save_error": "Test error",
            },
            "sleep_mode": {"active": False},
        }

        status = emergency.get_status(st)

        assert "flag_exists" in status
        assert "sleep_mode_active" in status
        assert status["save_fail_count"] == 2
        assert status["last_save_error"] == "Test error"
        assert "wake_file" in status
        assert "emergency_flag" in status


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_configure_with_none_optionals(self, mock_env, mock_log_event, mock_send_webhook):
        """Configure works with None for optional dependencies."""
        emergency.configure(
            env=mock_env,
            log_event_fn=mock_log_event,
            send_webhook_fn=mock_send_webhook,
            save_state_fn=lambda st: None,
            check_order_status_fn=None,  # Optional
            margin_after_close_fn=None,  # Optional
        )

        st = {"position": None}
        # Should not crash
        result = emergency.shutdown(st, "TEST")
        assert result is True

    def test_save_state_safe_without_configure(self):
        """save_state_safe returns False if not configured."""
        # Reset module
        emergency._save_state = None

        st = {}
        result = emergency.save_state_safe(st, "test")
        assert result is False

    def test_reconcile_with_invalid_order_id(self, configured_emergency):
        """Reconcile handles invalid order IDs gracefully."""
        st = {
            "position": {
                "orders": {"sl": "not_a_number"},
            }
        }
        result = emergency.shutdown(st, "TEST")

        assert result is True
        assert st["last_closed"]["reconciled"]["sl"] == "INVALID_ID"

    def test_backup_handles_non_serializable(self, configured_emergency, temp_state_dir):
        """Backup handles non-JSON-serializable objects via default=str."""
        st = {
            "position": None,
            "weird_object": MagicMock(),  # Not JSON serializable
        }

        result = emergency.shutdown(st, "TEST")
        assert result is True

        # Backup should exist and be valid JSON
        backup_path = os.path.join(temp_state_dir, "emergency_backup.json")
        assert os.path.exists(backup_path)

        with open(backup_path) as f:
            backup = json.load(f)  # Should not raise

        assert "state" in backup
