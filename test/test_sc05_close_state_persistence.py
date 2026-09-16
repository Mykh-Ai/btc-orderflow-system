"""SC-05: reload real JSON to verify the completed after-close state."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from executor_mod import margin_guard as guard, state_store


@pytest.fixture
def harness(monkeypatch, tmp_path):
    h = SimpleNamespace()
    h.state = {
        "position": None,
        "last_closed": {"trade_key": "T1", "reason": "SL_DONE"},
        "cooldown_until": 1800,
        "lock_until": 0,
        "mg_runtime": {
            "borrow_started": {"T1": 1}, "borrow_done": {"T1": 2},
            "after_open_done": {"T1": 3},
            "repay_started": {"older": 4}, "repay_done": {"older": 5},
        },
        "margin": {"active_trade_key": "T1", "borrowed_assets": {"BTC": "0.1"}},
    }
    h.result = {"trade_key": "T1", "cleanup_status": "clean"}
    h.cleanup_error = None
    h.events = []

    def repay(*args):
        h.events.append("repay")

    def cleanup(state, *args, **kwargs):
        h.events.append("cleanup")
        state["margin"]["post_close_debt_cleanup"] = {"last_result": deepcopy(h.result)}
        if h.cleanup_error:
            raise h.cleanup_error
        return deepcopy(h.result)

    def save(state):
        h.events.append("save")
        state_store.save_state(state)

    h.policy = SimpleNamespace(repay_if_any=Mock(side_effect=repay),
                               cleanup_post_close_margin_debt=Mock(side_effect=cleanup))
    h.save, h.log, h.alert = Mock(side_effect=save), Mock(), Mock()
    monkeypatch.setenv("STATE_FN", str(tmp_path / "executor_state.json"))
    for name, value in {
        "ENV": {"TRADE_MODE": "margin", "MARGIN_BORROW_MODE": "manual", "SYMBOL": "BTCUSDC"},
        "api_client": object(), "margin_policy": h.policy,
        "save_state_fn": h.save, "log_event": h.log, "send_webhook_fn": h.alert,
    }.items():
        monkeypatch.setattr(guard, name, value)
    state_store.save_state(h.state)
    return h


def assert_persisted_close(h):
    loaded = state_store.load_state()
    for key in ("borrow_started", "borrow_done", "after_open_done"):
        assert loaded["mg_runtime"][key] == {}
    assert loaded["margin"]["active_trade_key"] is None
    assert loaded["mg_runtime"] == h.state["mg_runtime"]
    assert loaded["margin"] == h.state["margin"]
    # A cleared lifecycle flag is not evidence that exchange debt disappeared.
    assert loaded["margin"]["borrowed_assets"] == {"BTC": "0.1"}
    assert loaded["mg_runtime"]["repay_done"]["older"] == 5
    for key in ("position", "last_closed", "cooldown_until", "lock_until"):
        assert loaded[key] == h.state[key]
    h.save.assert_called_once()
    return loaded


@pytest.mark.parametrize("status", ["clean", "error", "residual_debt", "skipped_clean", "skipped_recent"])
@pytest.mark.parametrize("dedup", [False, True])
def test_close_flags_and_audit_survive_reload(harness, status, dedup):
    h = harness
    h.result["cleanup_status"] = status
    if dedup:
        h.state["mg_runtime"]["repay_done"]["T1"] = 6
    guard.on_after_position_closed(h.state, "T1")
    loaded = assert_persisted_close(h)
    assert h.events == (["cleanup", "save"] if dedup else ["repay", "cleanup", "save"])
    assert loaded["margin"]["post_close_debt_cleanup"]["last_result"] == h.result
    if status in ("error", "residual_debt"):
        assert h.alert.call_args.args[0]["event"] == "POST_CLOSE_MARGIN_DEBT_CLEANUP_FAIL"
    # A restart must preserve repayment dedup, while still invoking cleanup.
    guard.on_after_position_closed(loaded, "T1")
    assert h.policy.repay_if_any.call_count == (0 if dedup else 1)
    assert h.policy.cleanup_post_close_margin_debt.call_count == 2


def test_cleanup_exception_still_persists_final_flags_and_existing_audit(harness):
    h = harness
    h.cleanup_error = RuntimeError("cleanup unavailable")
    guard.on_after_position_closed(h.state, "T1")
    assert_persisted_close(h)
    assert h.alert.call_args.args[0]["event"] == "POST_CLOSE_MARGIN_DEBT_CLEANUP_ERROR"


def test_repay_exception_preserves_started_marker_and_saves_final_flags(harness):
    h = harness
    h.policy.repay_if_any.side_effect = RuntimeError("repay uncertain")
    guard.on_after_position_closed(h.state, "T1")
    loaded = assert_persisted_close(h)
    assert "T1" in loaded["mg_runtime"]["repay_started"]
    assert "T1" not in loaded["mg_runtime"]["repay_done"]
    assert "MARGIN_HOOK_AFTER_CLOSE_ERROR" in [c.args[0] for c in h.log.call_args_list]


def test_optional_cleanup_absent_still_saves_final_flags(harness):
    h = harness
    h.policy.cleanup_post_close_margin_debt = None
    guard.on_after_position_closed(h.state, "T1")
    assert_persisted_close(h)
    assert h.events == ["repay", "save"]


def test_save_failure_reports_error_after_flags_are_cleared(harness):
    h = harness
    observed = []

    def fail_save(state):
        observed.append(deepcopy(state))
        raise OSError("disk unavailable")

    h.save.side_effect = fail_save
    guard.on_after_position_closed(h.state, "T1")
    assert observed[0]["margin"]["active_trade_key"] is None
    assert observed[0]["mg_runtime"]["borrow_done"] == {}
    h.log.assert_any_call("POST_CLOSE_MARGIN_DEBT_CLEANUP_SAVE_ERROR", trade_key="T1", error="disk unavailable")
    # Existing failure policy logs and returns; it cannot promise persistence.
    assert state_store.load_state()["margin"]["active_trade_key"] == "T1"
    h.save.assert_called_once()


@pytest.mark.parametrize("setting", [{"TRADE_MODE": "spot"}, {"MARGIN_BORROW_MODE": "auto"}])
def test_noop_modes_do_not_clear_or_save(harness, setting, monkeypatch):
    h = harness
    monkeypatch.setattr(guard, "ENV", {**guard.ENV, **setting})
    before = deepcopy(h.state)
    guard.on_after_position_closed(h.state, "T1")
    assert h.state == before
    h.save.assert_not_called()
    h.policy.repay_if_any.assert_not_called()
    h.policy.cleanup_post_close_margin_debt.assert_not_called()
