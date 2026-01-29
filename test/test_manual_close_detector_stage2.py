from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock, patch

from executor_mod import manual_close_detector, margin_policy


def _make_env() -> dict:
    return {
        "TRADE_MODE": "margin",
        "SYMBOL": "BTCUSDC",
        "MARGIN_ISOLATED": "FALSE",
        "MANUAL_CLOSE_CHECK_SEC": 120.0,
        "BASE_EPS": 0.00001,
        "QUOTE_EPS": 2.0,
    }


def _make_margin_account(base_free: float, base_locked: float, quote_free: float, quote_locked: float) -> dict:
    return {
        "userAssets": [
            {"asset": "BTC", "free": str(base_free), "locked": str(base_locked)},
            {"asset": "USDC", "free": str(quote_free), "locked": str(quote_locked)},
        ]
    }


def test_manual_close_long_guard_two_step_confirm() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 1.0,
                    "base_locked": 0.0,
                    "quote_free": 100.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 150.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    env["MANUAL_CLOSE_CONFIRM_SEC"] = 1.0
    result_1 = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    assert result_1["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0

    result_2 = manual_close_detector.tick(st, pos, api, margin_policy, env, 102.0)
    assert result_2["handled"] is True
    assert result_2["reason"] == "MANUAL_CLOSE_DETECTED"


def test_manual_close_short_requires_debt_gate() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "SHORT"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 0.5,
                    "base_locked": 0.0,
                    "quote_free": 250.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(0.5, 0.0, 300.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": True}
    env = _make_env()

    result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") is None


def test_manual_close_long_requires_debt_gate() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 0.5,
                    "base_locked": 0.0,
                    "quote_free": 250.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(0.5, 0.0, 300.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": True}
    env = _make_env()

    result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") is None


def test_manual_close_throttle_persistence() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 1.0,
                    "base_locked": 0.0,
                    "quote_free": 100.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 140.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    next_check = pos.get("manual_close_next_check_s")
    assert next_check == 220.0
    assert api.margin_account.call_count == 1

    manual_close_detector.tick(st, pos, api, margin_policy, env, 200.0)
    assert api.margin_account.call_count == 1


def test_manual_close_no_finalize_on_first_confirm_tick() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 1.0,
                    "base_locked": 0.0,
                    "quote_free": 100.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 140.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    env["MANUAL_CLOSE_CONFIRM_SEC"] = 1.0
    result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0


def test_manual_close_confirm_requires_age_window() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 1.0,
                    "base_locked": 0.0,
                    "quote_free": 100.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 140.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()
    env["MANUAL_CLOSE_CONFIRM_SEC"] = 200.0

    manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    result = manual_close_detector.tick(st, pos, api, margin_policy, env, 221.0)
    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0


@patch("executor.manual_close_detector.tick")
@patch("executor.report_take_profit")
@patch("executor.reporting.report_trade_close")
@patch("executor.margin_guard.on_after_position_closed")
@patch("executor.save_state")
@patch("executor.send_trade_closed")
@patch("executor.log_event")
@patch("executor.binance_api")
def test_manual_close_confirm_triggers_finalize(
    mock_api,
    mock_log,
    mock_send_closed,
    mock_save_state,
    mock_margin_after_close,
    mock_report_trade_close,
    mock_report_tp,
    mock_tick,
) -> None:
    import executor

    env_before = deepcopy(executor.ENV)
    env = {
        "SYMBOL": "BTCUSDC",
        "COOLDOWN_SEC": 10,
        "TRADE_MODE": "spot",
    }
    executor.ENV.update(env)

    pos = {
        "mode": "live",
        "status": "OPEN",
        "side": "LONG",
        "orders": {"tp1": 1, "tp2": 2, "sl": 3},
        "prices": {"entry": 100.0},
    }
    st = {"position": deepcopy(pos), "baseline": {"active": {"balances": {"base_free": 0.0}}}}

    mock_tick.return_value = {
        "handled": True,
        "reason": "MANUAL_CLOSE_DETECTED",
        "tag": "MANUAL_CLOSE_DETECTED_OK",
        "details": {"base_delta": 0.0, "quote_delta": 0.0},
    }

    try:
        executor.manage_v15_position("BTCUSDC", st)
    finally:
        executor.ENV.clear()
        executor.ENV.update(env_before)

    assert mock_report_trade_close.called
    assert mock_send_closed.called
    assert mock_save_state.called
    assert mock_margin_after_close.called
    assert st.get("position") is None


def test_manual_close_quote_delta_not_guard() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = {
        "position": pos,
        "baseline": {
            "active": {
                "balances": {
                    "base_free": 1.0,
                    "base_locked": 0.0,
                    "quote_free": 100.0,
                    "quote_locked": 0.0,
                }
            }
        },
    }
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 180.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()
    env["MANUAL_CLOSE_CONFIRM_SEC"] = 1.0

    manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)
    result = manual_close_detector.tick(st, pos, api, margin_policy, env, 102.0)
    assert result["handled"] is True
