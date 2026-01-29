from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock, patch

from executor_mod import manual_close_detector


def test_tick_no_baseline_no_api_calls() -> None:
    pos = {
        "mode": "live",
        "status": "OPEN",
        "orders": {"tp1": 1},
        "prices": {"entry": 100.0},
    }
    st = {"position": pos}
    st_before = deepcopy(st)
    pos_before = deepcopy(pos)
    api = Mock()
    margin_policy = Mock()
    env = {"TRADE_MODE": "spot", "MANUAL_CLOSE_CHECK_SEC": 120.0}

    with patch("executor_mod.manual_close_detector.log_event"):
        handled = manual_close_detector.tick(st, pos, api, margin_policy, env, 123.0)

    assert handled.get("handled") is False
    assert handled.get("state_dirty") is False
    assert st == st_before
    assert pos == pos_before
    assert api.method_calls == []
    assert margin_policy.method_calls == []


def test_tick_no_position_no_api_calls() -> None:
    st = {"baseline": {"active": {"balances": {"base_free": 0.0}}}}
    api = Mock()
    margin_policy = Mock()
    env = {"TRADE_MODE": "spot", "MANUAL_CLOSE_CHECK_SEC": 120.0}

    with patch("executor_mod.manual_close_detector.log_event"):
        handled = manual_close_detector.tick(st, None, api, margin_policy, env, 123.0)

    assert handled.get("handled") is False
    assert handled.get("state_dirty") is False
    assert api.method_calls == []
    assert margin_policy.method_calls == []
