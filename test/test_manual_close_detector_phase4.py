from __future__ import annotations

from unittest.mock import Mock, patch

from executor_mod import manual_close_detector, margin_policy


def _make_env() -> dict:
    return {
        "TRADE_MODE": "margin",
        "SYMBOL": "BTCUSDC",
        "MARGIN_ISOLATED": "FALSE",
        "MANUAL_CLOSE_CHECK_SEC": 120.0,
        "MANUAL_CLOSE_CONFIRM_SEC": 10.0,
    }


def _make_margin_account(base_free: float, base_locked: float, quote_free: float, quote_locked: float) -> dict:
    return {
        "userAssets": [
            {"asset": "BTC", "free": str(base_free), "locked": str(base_locked)},
            {"asset": "USDC", "free": str(quote_free), "locked": str(quote_locked)},
        ]
    }


def _make_state(pos: dict) -> dict:
    return {
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


def test_confirm_not_possible_in_one_tick() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0


def test_candidate_reset_when_guard_false() -> None:
    pos = {
        "mode": "live",
        "status": "OPEN",
        "side": "LONG",
        "manual_close_candidate_s": 50.0,
    }
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(0.5, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 200.0)

    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") is None


def test_long_guard_requires_no_debt() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": True}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") is None


def test_short_guard_requires_no_debt() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "SHORT"}
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": True}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") is None


def test_confirm_triggers_handled_on_second_tick() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        r1 = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert r1["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0

    # Second tick after confirm + throttle window -> handled=True
    with patch("executor_mod.manual_close_detector.log_event"):
        r2 = manual_close_detector.tick(
            st,
            pos,
            api,
            margin_policy,
            env,
            100.0 + env["MANUAL_CLOSE_CHECK_SEC"] + 0.1,
        )

    assert r2["handled"] is True
    assert r2.get("reason") == "MANUAL_CLOSE_DETECTED"
    assert r2.get("tag") == "MANUAL_CLOSE_DETECTED_OK"
    details = r2.get("details") or {}
    assert details.get("side") == "LONG"
    assert details.get("has_debt") is False


def test_base_eps_zero_allows_exact_match_confirmation() -> None:
    pos = {"mode": "live", "status": "OPEN", "side": "LONG"}
    st = _make_state(pos)
    api = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 120.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()
    env["BASE_EPS"] = 0.0

    with patch("executor_mod.manual_close_detector.log_event"):
        r1 = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert r1["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0

    with patch("executor_mod.manual_close_detector.log_event"):
        r2 = manual_close_detector.tick(
            st,
            pos,
            api,
            margin_policy,
            env,
            100.0 + env["MANUAL_CLOSE_CHECK_SEC"] + 0.1,
        )

    assert r2["handled"] is True
    assert r2.get("reason") == "MANUAL_CLOSE_DETECTED"
    assert r2.get("tag") == "MANUAL_CLOSE_DETECTED_OK"
    details = r2.get("details") or {}
    assert details.get("has_debt") is False
