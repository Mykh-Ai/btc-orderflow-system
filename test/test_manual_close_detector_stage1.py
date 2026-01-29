from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

from executor_mod import manual_close_detector


def test_tick_stage1_no_side_effects() -> None:
    pos = {
        "mode": "live",
        "status": "OPEN",
        "orders": {"tp1": 1},
        "prices": {"entry": 100.0},
    }
    st = {
        "position": pos,
        "baseline": {"active": {"balances": {"base_free": 0.0}}},
    }
    st_before = deepcopy(st)
    pos_before = deepcopy(pos)
    api = Mock()
    margin_policy = Mock()
    env = {"TRADE_MODE": "spot"}

    handled = manual_close_detector.tick(st, pos, api, margin_policy, env, 123.0)

    assert handled.get("handled") is False
    assert handled.get("state_dirty") is False
    assert st == st_before
    assert pos == pos_before
    assert api.method_calls == []
    assert margin_policy.method_calls == []
