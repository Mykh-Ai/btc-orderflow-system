"""SC-04: missing/invalid account evidence must never certify clean debt."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from executor_mod import margin_guard as guard, margin_policy as policy, state_store


def asset(name="BTC", borrowed="0", interest="0", free="1"):
    return {"asset": name, "borrowed": borrowed, "interest": interest, "free": free}


def cross(*rows):
    return {"userAssets": list(rows) if rows else [asset(n) for n in ("BTC", "USDC", "BNB")]}


def isolated(symbol="BTCUSDC"):
    return {"assets": [{"symbol": symbol, "baseAsset": asset("BTC"), "quoteAsset": asset("USDC")}]}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    h = SimpleNamespace(now=1000., env={"TRADE_MODE": "margin", "SYMBOL": "BTCUSDC",
        "MARGIN_ISOLATED": "FALSE", "MARGIN_BORROW_MODE": "manual", "MARGIN_SIDE_EFFECT": "NO_SIDE_EFFECT",
        "MARGIN_POST_CLOSE_CLEANUP_TTL_SEC": 30, "MARGIN_POST_CLOSE_CLEANUP_ASSETS": "BTC,USDC,BNB"})
    h.api = SimpleNamespace(_env=lambda: h.env, margin_account=Mock(), margin_repay=Mock())
    h.log, h.alert = Mock(), Mock()
    monkeypatch.setenv("STATE_FN", str(tmp_path / "state.json"))
    monkeypatch.setattr(policy, "time", SimpleNamespace(time=lambda: h.now))
    for name, value in {"ENV": h.env, "api_client": h.api, "margin_policy": policy,
                        "log_event": h.log, "send_webhook_fn": h.alert,
                        "save_state_fn": state_store.save_state,
                        "time": SimpleNamespace(time=lambda: h.now)}.items():
        monkeypatch.setattr(guard, name, value)
    return h


@pytest.mark.parametrize("account", [None, [], {}, {"userAssets": None}, {"userAssets": {}},
    {"userAssets": []}, {"userAssets": [None]}, {"userAssets": [{}]},
    {"userAssets": [asset("BTC"), asset("BTC")]}, {"assets": [asset("BTC")]},
    cross(asset("USDC")),
])
def test_missing_or_malformed_account_is_error_without_repay(harness, account):
    h = harness
    h.api.margin_account.return_value = account
    st = {}
    result = policy.cleanup_post_close_margin_debt(st, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert result["cleanup_status"] == "error"
    assert result["binance_errors"][0]["stage"] == "pre_account_validation"
    assert result["checked_assets"] == []
    h.api.margin_repay.assert_not_called()
    assert st["margin"]["post_close_debt_cleanup"]["by_trade"]["T1"] == result


@pytest.mark.parametrize("field", ["borrowed", "interest", "free"])
@pytest.mark.parametrize("bad", [None, "", "bad", "NaN", "Infinity", "-0.01", True])
def test_invalid_numeric_field_is_not_zero(harness, field, bad):
    h = harness
    row = asset(borrowed=".1")
    row[field] = bad
    h.api.margin_account.return_value = cross(row)
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert result["cleanup_status"] == "error"
    h.api.margin_repay.assert_not_called()


@pytest.mark.parametrize("field", ["borrowed", "interest", "free"])
def test_missing_numeric_field_is_not_zero(harness, field):
    h = harness
    row = asset()
    del row[field]
    h.api.margin_account.return_value = cross(row)
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert result["cleanup_status"] == "error"


def test_validate_all_requested_assets_before_any_cleanup_repayment(harness):
    h = harness
    h.api.margin_account.return_value = cross(asset("BTC", borrowed=".1"), asset("USDC", interest="bad"), asset("BNB"))
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1")
    assert result["cleanup_status"] == "error"
    h.api.margin_repay.assert_not_called()


def test_missing_allowlisted_asset_prevents_clean(harness):
    h = harness
    h.api.margin_account.return_value = cross(asset("BTC"), asset("USDC"))
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1")
    assert result["cleanup_status"] == "error"
    assert "BNB" in result["binance_errors"][0]["error"]


@pytest.mark.parametrize("post", [{}, cross(asset(borrowed="bad")), cross(asset(interest=None)), cross(asset(free="NaN"))])
def test_invalid_post_repay_snapshot_never_certifies_clean(harness, post):
    h = harness
    h.api.margin_account.side_effect = [cross(asset(borrowed=".1", interest=".01")), post]
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert result["cleanup_status"] == "error"
    assert result["binance_errors"][0]["stage"] == "post_account_validation"
    assert result["repaid_amounts"] == {"BTC": "0.11"}
    h.api.margin_repay.assert_called_once()


def test_explicit_valid_zero_debt_is_clean_and_persistently_deduplicated(harness):
    h = harness
    h.api.margin_account.return_value = cross()
    st = {}
    result = policy.cleanup_post_close_margin_debt(st, h.api, "BTCUSDC", trade_key="T1")
    assert result["cleanup_status"] == "clean"
    assert result["validated_phases"] == ["pre", "post"]
    assert result["version"] == 2
    state_store.save_state(st)
    h.now += 100
    again = policy.cleanup_post_close_margin_debt(state_store.load_state(), h.api, "BTCUSDC", trade_key="T1")
    assert again["cleanup_status"] == "skipped_clean"
    assert h.api.margin_account.call_count == 2
    h.api.margin_repay.assert_not_called()


def test_guard_persists_and_alerts_uncertainty_then_retries_after_ttl(harness):
    h = harness
    h.api.margin_account.return_value = {}
    st = {"last_closed": {"trade_key": "T1"}}
    guard.on_after_position_closed(st, "T1")
    saved = state_store.load_state()
    assert saved["margin"]["post_close_debt_cleanup"]["last_result"]["cleanup_status"] == "error"
    assert h.alert.call_args.args[0]["event"] == "POST_CLOSE_MARGIN_DEBT_CLEANUP_FAIL"
    assert h.alert.call_args.args[0]["binance_errors"][0]["stage"] == "pre_account_validation"
    h.api.margin_account.return_value = cross()
    guard.on_after_position_closed(saved, "T1")
    assert h.api.margin_account.call_count == 1
    assert state_store.load_state()["margin"]["post_close_debt_cleanup"]["last_result"]["cleanup_status"] == "skipped_recent"
    h.now += 31
    guard.on_after_position_closed(state_store.load_state(), "T1")
    assert h.api.margin_account.call_count == 3
    assert state_store.load_state()["margin"]["post_close_debt_cleanup"]["last_result"]["cleanup_status"] == "clean"
    h.api.margin_repay.assert_not_called()


def test_post_error_retry_refetches_current_debt_not_previous_repayment(harness):
    h = harness
    h.api.margin_account.side_effect = [cross(asset(borrowed=".1", interest=".01")), {}, cross(asset(borrowed=".02")), cross(asset())]
    st = {}
    first = policy.cleanup_post_close_margin_debt(st, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert first["cleanup_status"] == "error"
    state_store.save_state(st)
    h.now += 31
    second = policy.cleanup_post_close_margin_debt(state_store.load_state(), h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC"])
    assert second["cleanup_status"] == "clean"
    assert [Decimal(c.args[1]) for c in h.api.margin_repay.call_args_list] == [Decimal(".11"), Decimal(".02")]


@pytest.mark.parametrize("legacy", [{"version": 1}, {"version": 2}, {"version": 2, "validated_phases": ["pre"]}])
def test_uncertified_clean_cache_revalidated_even_inside_ttl(harness, legacy):
    h = harness
    old = {"cleanup_status": "clean", "started_at_s": h.now, "symbol": "BTCUSDC",
           "is_isolated": False, "allowlist": ["BTC", "USDC", "BNB"], **legacy}
    st = {"margin": {"post_close_debt_cleanup": {"by_trade": {"T1": old}}}}
    h.api.margin_account.return_value = {}
    result = policy.cleanup_post_close_margin_debt(st, h.api, "BTCUSDC", trade_key="T1")
    assert result["cleanup_status"] == "error"
    assert h.api.margin_account.call_count == 1


@pytest.mark.parametrize("change", ["symbol", "assets", "isolation"])
def test_changed_scope_invalidates_clean_cache(harness, change):
    h = harness
    st = {}
    h.api.margin_account.return_value = cross()
    policy.cleanup_post_close_margin_debt(st, h.api, "BTCUSDC", trade_key="T1")
    symbol, assets = "BTCUSDC", None
    if change == "symbol":
        symbol = "ETHUSDC"
    elif change == "assets":
        assets = ["BTC"]
    else:
        h.env["MARGIN_ISOLATED"] = "TRUE"
    h.api.margin_account.return_value = {}
    result = policy.cleanup_post_close_margin_debt(st, h.api, symbol, trade_key="T1", allowlist=assets)
    assert result["cleanup_status"] == "error"
    assert h.api.margin_account.call_count == 3


def test_valid_isolated_pair_with_explicit_scope(harness):
    h = harness
    h.env["MARGIN_ISOLATED"] = "TRUE"
    h.api.margin_account.return_value = isolated()
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=["BTC", "USDC"])
    assert result["cleanup_status"] == "clean"
    assert result["checked_assets"] == ["BTC", "USDC"]


@pytest.mark.parametrize("wrong", ["pair", "duplicate_pair", "missing_quote", "wrong_asset", "cross_shape", "extra_allowlist"])
def test_isolated_wrong_or_incomplete_scope_is_unknown(harness, wrong):
    h = harness
    h.env["MARGIN_ISOLATED"] = "TRUE"
    response = isolated()
    allowlist = ["BTC", "USDC"]
    if wrong == "pair":
        response["assets"][0]["symbol"] = "ETHUSDC"
    elif wrong == "duplicate_pair":
        response["assets"].append(deepcopy(response["assets"][0]))
    elif wrong == "missing_quote":
        del response["assets"][0]["quoteAsset"]
    elif wrong == "wrong_asset":
        response["assets"][0]["quoteAsset"]["asset"] = "USDT"
    elif wrong == "cross_shape":
        response = cross()
    else:
        allowlist.append("BNB")
    h.api.margin_account.return_value = response
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=allowlist)
    assert result["cleanup_status"] == "error"
    h.api.margin_repay.assert_not_called()


def test_empty_allowlist_cannot_certify_clean(harness):
    h = harness
    h.api.margin_account.return_value = cross()
    result = policy.cleanup_post_close_margin_debt({}, h.api, "BTCUSDC", trade_key="T1", allowlist=[])
    assert result["cleanup_status"] == "error"
    h.api.margin_repay.assert_not_called()
