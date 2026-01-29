from __future__ import annotations

from unittest.mock import Mock, patch

from executor_mod import manual_close_detector, margin_policy


def _make_env() -> dict:
    return {
        "TRADE_MODE": "margin",
        "SYMBOL": "BTCUSDC",
        "MARGIN_ISOLATED": "FALSE",
        "MANUAL_CLOSE_CHECK_SEC": 120.0,
    }


def _make_margin_account(base_free: float, base_locked: float, quote_free: float, quote_locked: float) -> dict:
    return {
        "userAssets": [
            {"asset": "BTC", "free": str(base_free), "locked": str(base_locked)},
            {"asset": "USDC", "free": str(quote_free), "locked": str(quote_locked)},
        ]
    }


def test_manual_close_snapshot_throttle_skips_api() -> None:
    pos = {
        "mode": "live",
        "status": "OPEN",
        "side": "LONG",
        "manual_close_next_check_s": 500.0,
    }
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

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert result["handled"] is False
    assert result["state_dirty"] is False
    assert api.margin_account.call_count == 0
    assert api.get_margin_debt_snapshot.call_count == 0


def test_manual_close_snapshot_writes_diag_read_only() -> None:
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
    api._close_slot = Mock()
    api.margin_account.return_value = _make_margin_account(1.0, 0.0, 150.0, 0.0)
    api.get_margin_debt_snapshot.return_value = {"has_debt": False}
    env = _make_env()

    with patch("executor_mod.manual_close_detector.log_event"):
        result = manual_close_detector.tick(st, pos, api, margin_policy, env, 100.0)

    assert result["handled"] is False
    assert pos.get("manual_close_candidate_s") == 100.0
    assert pos.get("manual_close_notified") is None
    assert api._close_slot.call_count == 0
    assert api.margin_account.call_count == 1
    assert api.get_margin_debt_snapshot.call_count == 1
    assert pos.get("manual_close_next_check_s") == 220.0
    diag = pos.get("manual_close_diag")
    assert diag is not None
    assert diag["base_total"] == 1.0
    assert diag["quote_total"] == 150.0
    assert diag["base_baseline"] == 1.0
    assert diag["quote_baseline"] == 100.0
    assert diag["delta_base"] == 0.0
    assert diag["delta_quote"] == 50.0
    assert diag["has_debt"] is False
