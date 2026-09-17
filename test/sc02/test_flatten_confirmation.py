from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import executor as ex
from executor_mod import binance_api as api


def setup_flatten(h, position, side="LONG"):
    h.env.update(FAILSAFE_FLATTEN=True, FAILSAFE_EXITS_MAX_TRIES=1, FAILSAFE_EXITS_GRACE_SEC=0)
    position.update(status="OPEN_FILLED", orders={}, qty=.3, side=side)
    if side == "SHORT":
        position["prices"] = {"entry": 100., "sl": 110., "tp1": 90., "tp2": 80.}
    h.api.place_order_raw.side_effect = RuntimeError("exits unavailable")
    h.api.flatten_market.side_effect = lambda *a, **kw: {"orderId": 900, "status": "FILLED"}
    return {"position": position, "lock_until": h.now + 15}


def order(symbol, cid, side="LONG", **overrides):
    return {"symbol": symbol, "clientOrderId": cid, "orderId": 900,
            "side": "SELL" if side == "LONG" else "BUY", "type": "MARKET",
            "status": "FILLED", "origQty": ".3", "executedQty": ".3", **overrides}


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_confirmed_full_fill_saves_identity_before_post_and_finalizes_once(executor_harness, position, side):
    h = executor_harness
    st = setup_flatten(h, position, side)
    at_post = []
    def post(*a, **kw):
        at_post.append((a, kw, h.load()))
        return {"status": "FILLED", "orderId": 900}
    h.api.flatten_market.side_effect = post
    h.api.get_order_by_client_id.side_effect = lambda symbol, cid: order(symbol, cid, side)
    ex.handle_open_filled_exits_retry(st)
    args, kwargs, saved = at_post[0]
    intent = saved["position"]["failsafe_flatten"]
    assert intent["status"] == "SUBMITTING"
    assert intent["client_id"] == kwargs["client_id"] and len(intent["client_id"]) <= 36
    assert args == ("BTCUSDC", side, .3)
    assert h.load()["position"] is None
    closed = h.load()["last_closed"]
    assert closed["reason"] == "FAILSAFE_FLATTEN"
    assert closed["flatten_confirmation"]["order_id"] == 900
    assert closed["flatten_confirmation"]["executed_qty"] == "0.3"
    assert h.load()["lock_until"] == 0
    h.hooks.on_after_position_closed.assert_called_once()
    labels = [t[0] for t in h.trace]
    n = labels.index("snapshot")
    assert labels[n:n+4] == ["snapshot", "save", "archive", "after_close"]
    ex.handle_open_filled_exits_retry(h.load())
    h.api.flatten_market.assert_called_once()
    h.hooks.on_after_position_closed.assert_called_once()


@pytest.mark.parametrize("status,executed", [("NEW", "0"), ("PARTIALLY_FILLED", ".1"), ("CANCELED", ".1"), ("EXPIRED", "0"), ("REJECTED", "0"), ("FILLED", ".1")])
def test_nonfull_or_nonfilled_response_never_clears_or_resubmits(executor_harness, position, status, executed):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = lambda symbol, cid: order(symbol, cid, status=status, executedQty=executed)
    ex.handle_open_filled_exits_retry(st)
    for _ in range(3):
        h.now += 20
        st = h.load()
        ex.handle_open_filled_exits_retry(st)
        ex.manage_v15_position("BTCUSDC", st)
        h.reconcile(st)
    assert h.load()["position"]["qty"] == .3
    assert not st.get("last_closed")
    h.api.flatten_market.assert_called_once()
    h.api.place_order_raw.assert_called_once()
    h.api.open_orders.assert_not_called()
    h.hooks.on_after_position_closed.assert_not_called()
    assert not any(t[0] in ("archive", "snapshot") for t in h.trace)
    notices = [t for t in h.trace if t[0] == "webhook" and t[1]["event"] == "FAILSAFE_FLATTEN_UNCONFIRMED"]
    assert len(notices) == 1  # stable uncertainty is not a webhook flood


@pytest.mark.parametrize("failure", [RuntimeError("rejected"), requests.Timeout("response lost")])
def test_submission_failure_recovers_same_identity_after_reload(executor_harness, position, failure):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.flatten_market.side_effect = failure
    h.api.get_order_by_client_id.side_effect = RuntimeError("-2013 Order does not exist")
    ex.handle_open_filled_exits_retry(st)
    saved = h.load()
    assert saved["position"]["status"] == "OPEN_FILLED" and not saved.get("last_closed")
    cid = saved["position"]["failsafe_flatten"]["client_id"]
    calls = h.api.get_order_by_client_id.call_count
    h.env["FAILSAFE_FLATTEN"] = False  # in-flight confirmation must still run
    ex.handle_open_filled_exits_retry(h.load())
    assert h.api.get_order_by_client_id.call_count == calls
    h.now += 20
    h.api.get_order_by_client_id.side_effect = lambda symbol, client_id: order(symbol, client_id)
    ex.handle_open_filled_exits_retry(h.load())
    assert h.load()["position"] is None
    assert h.load()["last_closed"]["flatten_confirmation"]["client_id"] == cid
    h.api.flatten_market.assert_called_once()


@pytest.mark.parametrize("bad", [
    {"clientOrderId": "other"}, {"symbol": "BTCUSDT"}, {"side": "BUY"}, {"type": "LIMIT"},
    {"origQty": ".4"}, {"executedQty": ".4"}, {"executedQty": "nan"},
    {"executedQty": None}, {"executedQty": "bad"}, {"executedQty": "-.1"},
    {"origQty": "inf"}, {"orderId": None}, {"orderId": -1},
])
def test_untrusted_fill_evidence_cannot_confirm_closure(executor_harness, position, bad):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = lambda symbol, cid: order(symbol, cid, **bad)
    ex.handle_open_filled_exits_retry(st)
    assert h.load()["position"] is not None
    h.hooks.on_after_position_closed.assert_not_called()


@pytest.mark.parametrize("response", [None, {}, []])
def test_missing_lookup_payload_retains_position(executor_harness, position, response):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = lambda *a: response
    ex.handle_open_filled_exits_retry(st)
    assert h.load()["position"] is not None
    h.hooks.on_after_position_closed.assert_not_called()


def test_crash_after_intent_before_submit_never_replays_market(executor_harness, position, monkeypatch):
    h = executor_harness
    st = setup_flatten(h, position)
    class PowerLoss(BaseException):
        pass
    def save(st):
        h.save(st)
        if "failsafe_flatten" in (st.get("position") or {}):
            raise PowerLoss()
    monkeypatch.setattr(ex, "save_state", save)
    with pytest.raises(PowerLoss):
        ex.handle_open_filled_exits_retry(st)
    h.api.flatten_market.assert_not_called()
    monkeypatch.setattr(ex, "save_state", h.save)
    h.api.get_order_by_client_id.side_effect = RuntimeError("-2013 Order does not exist")
    ex.handle_open_filled_exits_retry(h.load())
    assert h.load()["position"] is not None
    h.api.flatten_market.assert_not_called()  # uncertainty requires operator reconciliation


def test_save_failure_prevents_market_submission(executor_harness, position, monkeypatch):
    h = executor_harness
    st = setup_flatten(h, position)
    def save(st):
        if "failsafe_flatten" in (st.get("position") or {}):
            raise OSError("disk unavailable")
        h.save(st)
    monkeypatch.setattr(ex, "save_state", save)
    with pytest.raises(OSError):
        ex.handle_open_filled_exits_retry(st)
    h.api.flatten_market.assert_not_called()
    assert "failsafe_flatten" not in h.load()["position"]


def test_crash_after_accepted_post_recovers_by_get_without_second_post(executor_harness, position):
    h = executor_harness
    st = setup_flatten(h, position)
    class PowerLoss(BaseException):
        pass
    h.api.flatten_market.side_effect = PowerLoss()
    with pytest.raises(PowerLoss):
        ex.handle_open_filled_exits_retry(st)
    assert h.load()["position"]["failsafe_flatten"]["status"] == "SUBMITTING"
    h.api.get_order_by_client_id.side_effect = lambda symbol, cid: order(symbol, cid)
    ex.handle_open_filled_exits_retry(h.load())
    assert h.load()["position"] is None
    h.api.flatten_market.assert_called_once()


@pytest.mark.parametrize("setting,value", [("FAILSAFE_FLATTEN", False), ("FAILSAFE_EXITS_MAX_TRIES", 0), ("FAILSAFE_EXITS_MAX_TRIES", 5), ("FAILSAFE_EXITS_GRACE_SEC", 60)])
def test_existing_failsafe_enable_threshold_and_grace_gates(executor_harness, position, setting, value):
    h = executor_harness
    st = setup_flatten(h, position)
    h.env[setting] = value
    ex.handle_open_filled_exits_retry(st)
    assert st["position"] is not None and "failsafe_flatten" not in st["position"]
    h.api.flatten_market.assert_not_called()
    h.api.get_order_by_client_id.assert_not_called()


def test_successful_exit_retry_does_not_flatten(executor_harness, position):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.place_order_raw.side_effect = [{"orderId": 333}, {"orderId": 111}, {"orderId": 222}]
    ex.handle_open_filled_exits_retry(st)
    assert h.load()["position"]["status"] == "OPEN"
    h.api.flatten_market.assert_not_called()


def test_changed_account_config_keeps_intent_without_query_or_resubmit(executor_harness, position):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = RuntimeError("unknown")
    ex.handle_open_filled_exits_retry(st)
    query_count = h.api.get_order_by_client_id.call_count
    h.now += 20
    h.env["MARGIN_ISOLATED"] = "TRUE"
    ex.handle_open_filled_exits_retry(h.load())
    assert h.api.get_order_by_client_id.call_count == query_count
    assert h.load()["position"] is not None
    h.api.flatten_market.assert_called_once()


def test_final_state_save_failure_preserves_confirmed_intent_for_restart(executor_harness, position, monkeypatch):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = lambda symbol, cid: order(symbol, cid)
    def save(st):
        if st.get("position") is None:
            raise OSError("cannot persist closure")
        h.save(st)
    monkeypatch.setattr(ex, "save_state", save)
    with pytest.raises(OSError):
        ex.handle_open_filled_exits_retry(st)
    assert h.load()["position"]["failsafe_flatten"]["status"] == "CONFIRMED"
    h.hooks.on_after_position_closed.assert_not_called()
    monkeypatch.setattr(ex, "save_state", h.save)
    h.now += 20
    ex.handle_open_filled_exits_retry(h.load())
    assert h.load()["position"] is None
    h.hooks.on_after_position_closed.assert_called_once()
    h.api.flatten_market.assert_called_once()


def test_main_restart_blocks_new_entry_exits_and_shutdown_repay(executor_harness, position, monkeypatch):
    h = executor_harness
    st = setup_flatten(h, position)
    h.api.get_order_by_client_id.side_effect = RuntimeError("lookup unavailable")
    ex.handle_open_filled_exits_retry(st)
    h.now += 20
    shutdown = []
    monkeypatch.setattr(ex.atexit, "register", shutdown.append)
    monkeypatch.setattr(ex, "sync_from_binance", h.reconcile)
    peak = {"action": "PEAK", "source": "DeltaScout", "kind": "long", "ts": ex.iso_utc(), "price": 100.}
    result = h.run_ticks(h.load(), events=[peak])
    shutdown[0]()
    assert result["position"] is not None
    h.api.flatten_market.assert_called_once()
    h.api.place_order_raw.assert_called_once()
    h.api.place_spot_market.assert_not_called()
    h.api.place_spot_limit.assert_not_called()
    h.api.open_orders.assert_not_called()
    h.hooks.on_shutdown.assert_not_called()
    h.hooks.on_after_position_closed.assert_not_called()


@pytest.mark.parametrize("mode,endpoint", [("margin", "/sapi/v1/margin/order"), ("spot", "/api/v3/order")])
def test_lookup_uses_existing_order_endpoint_with_client_identity(monkeypatch, mode, endpoint):
    monkeypatch.setattr(api, "_ENV", {"TRADE_MODE": mode, "MARGIN_ISOLATED": "TRUE"})
    signed = Mock(return_value={"status": "NEW"})
    monkeypatch.setattr(api, "_binance_signed_request", signed)
    assert api.get_order_by_client_id("BTCUSDC", "EX_FLAT_test") == {"status": "NEW"}
    params = {"symbol": "BTCUSDC", "origClientOrderId": "EX_FLAT_test"}
    if mode == "margin":
        params["isIsolated"] = "TRUE"
    signed.assert_called_once_with("GET", endpoint, params)


@pytest.mark.parametrize("failure", [requests.Timeout("lost"), requests.ConnectionError("lost"), 503, 429])
@pytest.mark.parametrize("endpoint", ["/sapi/v1/margin/order", "/api/v3/order"])
def test_failsafe_http_post_never_retries_or_fails_over(monkeypatch, failure, endpoint):
    monkeypatch.setattr(api, "_ENV", {"BINANCE_API_BASES": "https://one.test,https://two.test"})
    post = Mock(side_effect=failure if isinstance(failure, Exception) else None)
    post.return_value = SimpleNamespace(status_code=failure, text="temporary error")
    monkeypatch.setattr(api.requests, "post", post)
    monkeypatch.setattr(api.time, "sleep", lambda s: pytest.fail("failsafe POST must not retry"))
    with pytest.raises((RuntimeError, requests.Timeout, requests.ConnectionError)):
        api._do_request("POST", "https://one.test" + endpoint, headers={},
                        req_params={"type": "MARKET", "newClientOrderId": "EX_FLAT_test"})
    assert post.call_count == 1


def test_ordinary_order_transport_retains_existing_retry_behavior(monkeypatch):
    monkeypatch.setattr(api, "_ENV", {"BINANCE_API_BASES": "https://one.test"})
    response = SimpleNamespace(status_code=200)
    post = Mock(side_effect=[requests.Timeout("lost"), response])
    monkeypatch.setattr(api.requests, "post", post)
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    assert api._do_request("POST", "https://one.test/api/v3/order", headers={},
                           req_params={"type": "MARKET", "newClientOrderId": "EX_EN_test"}) is response
    assert post.call_count == 2


@pytest.mark.parametrize("mode", ["margin", "spot"])
def test_real_flatten_adapter_reaches_single_attempt_transport(monkeypatch, mode):
    monkeypatch.setattr(api, "_ENV", {
        "TRADE_MODE": mode, "SYMBOL": "BTCUSDC", "MARGIN_ISOLATED": "FALSE",
        "MARGIN_BORROW_MODE": "manual", "BINANCE_API_BASES": "https://one.test,https://two.test",
        "BINANCE_BASE_URL": "https://one.test", "BINANCE_API_KEY": "test-only",
        "BINANCE_API_SECRET": "test-only",
    })
    monkeypatch.setattr(api, "_round_qty", lambda q: q)
    monkeypatch.setattr(api, "_fmt_qty", str)
    monkeypatch.setattr(api, "_fmt_price", str)
    post = Mock(side_effect=requests.Timeout("lost"))
    monkeypatch.setattr(api.requests, "post", post)
    with pytest.raises(requests.Timeout):
        api.flatten_market("BTCUSDC", "LONG", .3, client_id="EX_FLAT_persisted")
    post.assert_called_once()
    assert post.call_args.kwargs["params"]["newClientOrderId"] == "EX_FLAT_persisted"
    assert post.call_args.kwargs["params"]["quantity"] == "0.3"
    assert post.call_args.kwargs["params"]["side"] == "SELL"
