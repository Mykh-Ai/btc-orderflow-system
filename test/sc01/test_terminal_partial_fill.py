"""SC-01 behavior repair: terminal entry with fills remains managed exposure."""
from copy import deepcopy
from decimal import Decimal

import pytest

import executor as ex


def script_entry(h, position, terminal="CANCELED", side="LONG", quote_key="cummulativeQuoteQty"):
    position.update(status="PENDING", orders={}, side=side, qty=.6, entry_actual=None)
    if side == "SHORT":
        position["prices"] = {"entry": 100., "sl": 110., "tp1": 90., "tp2": 80.}
    h.api.open_orders.side_effect = lambda *a: []
    h.api.check_order_status.side_effect = lambda symbol, oid: (
        {"status": terminal, "executedQty": ".3", quote_key: "30.3"}
        if oid == 100 else {"status": "NEW", "executedQty": "0"}
    )


@pytest.mark.parametrize("terminal", ["CANCELED", "EXPIRED", "REJECTED"])
@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("quote_key", ["cummulativeQuoteQty", "cumulativeQuoteQty"])
def test_terminal_partial_fill_saves_then_protects_actual_qty(executor_harness, position, terminal, side, quote_key):
    h = executor_harness
    script_entry(h, position, terminal, side, quote_key)
    at_placement = []
    def place(payload):
        at_placement.append((deepcopy(payload), h.load()))
        return {"orderId": 300 + len(at_placement)}
    h.api.place_order_raw.side_effect = place
    st = h.run_ticks({"position": position, "lock_until": h.now + 100})
    assert len(at_placement) == 3
    sl_payload, before_sl = at_placement[0]
    assert before_sl["position"]["status"] == "OPEN_FILLED"
    assert before_sl["position"]["qty"] == .3
    assert before_sl["position"]["executedQty"] == ".3"
    assert before_sl["position"]["entry_actual"] == 101.
    assert before_sl["position"]["cummulativeQuoteQty"] == "30.3"
    assert sl_payload["type"] == "STOP_LOSS_LIMIT"
    assert sl_payload["side"] == ("SELL" if side == "LONG" else "BUY")
    assert Decimal(sl_payload["quantity"]) == Decimal(".3")
    assert sum(Decimal(str(st["position"]["orders"][k])) for k in ("qty1", "qty2", "qty3")) == Decimal(".3")
    assert st["position"]["status"] == "OPEN"
    assert st["position"]["order_id"] == 100
    assert not st.get("last_closed") and st["lock_until"] == h.now + 100
    h.hooks.on_after_entry_opened.assert_called_once()
    h.hooks.on_after_position_closed.assert_not_called()
    h.api.place_spot_market.assert_not_called()
    h.api.cancel_order.assert_not_called()
    assert any(t[:2] == ("log", "ENTRY_TERMINAL_PARTIAL_FILLED") and t[2]["status"] == terminal for t in h.trace)
    assert not any(t[0] in ("snapshot", "archive", "after_close") for t in h.trace)

    # Restart with persisted OPEN and replay of the old terminal entry: no new entry or exits.
    h.now += 20
    again = h.run_ticks(st)
    assert again["position"]["orders"] == st["position"]["orders"]
    assert len(at_placement) == 3
    assert sum(c.args[1] == 100 for c in h.api.check_order_status.call_args_list) == 1
    h.hooks.on_after_entry_opened.assert_called_once()


def test_exit_failure_retains_exposure_and_retry_recovers_after_reload(executor_harness, position):
    h = executor_harness
    script_entry(h, position)
    h.api.place_order_raw.side_effect = RuntimeError("SL unavailable")
    st = h.run_ticks({"position": position})
    assert st["position"]["status"] == "OPEN_FILLED"
    assert st["position"]["qty"] == .3 and not st.get("last_closed")
    assert st["position"]["exits_next_try_s"] > h.now
    h.hooks.on_after_position_closed.assert_not_called()
    # Retry is throttled across an immediate restart.
    before = h.api.place_order_raw.call_count
    st = h.run_ticks(st)
    assert h.api.place_order_raw.call_count == before
    h.now = st["position"]["exits_next_try_s"]
    h.api.place_order_raw.side_effect = [{"orderId": 333}, {"orderId": 111}, {"orderId": 222}]
    recovered = h.run_ticks(st)
    assert recovered["position"]["status"] == "OPEN"
    assert recovered["position"]["qty"] == .3
    assert h.api.place_order_raw.call_count == before + 3
    h.hooks.on_after_entry_opened.assert_called_once()
    h.api.place_spot_market.assert_not_called()


def test_interruption_after_promotion_reloads_and_places_exits(executor_harness, position):
    h = executor_harness
    script_entry(h, position)
    class Interrupted(BaseException):
        pass
    h.hooks.on_after_entry_opened.side_effect = Interrupted()
    with pytest.raises(Interrupted):
        h.run_ticks({"position": position})
    saved = h.load()
    assert saved["position"]["status"] == "OPEN_FILLED"
    assert saved["position"]["qty"] == .3
    h.api.place_order_raw.assert_not_called()
    h.hooks.on_after_entry_opened.side_effect = None
    h.api.place_order_raw.side_effect = [{"orderId": 333}, {"orderId": 111}, {"orderId": 222}]
    recovered = h.run_ticks(saved)
    assert recovered["position"]["status"] == "OPEN"
    assert h.api.place_order_raw.call_count == 3
    assert not recovered.get("last_closed")


@pytest.mark.parametrize("payload", [{}, {"executedQty": None}, {"executedQty": ""}, {"executedQty": "bad"}, {"executedQty": "nan"}, {"executedQty": "inf"}, {"executedQty": "-.1"}])
def test_terminal_unknown_qty_is_not_treated_as_zero(executor_harness, position, payload):
    h = executor_harness
    position.update(status="PENDING", orders={})
    h.api.check_order_status.side_effect = lambda *a: {"status": "CANCELED", **payload}
    result = h.run_ticks({"position": position})
    assert result["position"]["status"] == "PENDING"
    assert not result.get("last_closed")
    h.hooks.on_after_position_closed.assert_not_called()
    h.api.place_spot_market.assert_not_called()
    h.api.place_order_raw.assert_not_called()


def test_nonterminal_partial_entry_waits_for_fill_or_timeout(executor_harness, position):
    h = executor_harness
    script_entry(h, position, terminal="PARTIALLY_FILLED")
    position["opened_s"] = h.now
    result = h.run_ticks({"position": position})
    assert result["position"]["status"] == "PENDING"
    h.api.cancel_order.assert_not_called()
    h.api.place_order_raw.assert_not_called()
    h.hooks.on_after_entry_opened.assert_not_called()


@pytest.mark.parametrize("terminal", ["CANCELED", "EXPIRED", "REJECTED"])
def test_sc01_terminal_entry_with_fills_retains_exposure(executor_harness, position, terminal):
    h = executor_harness
    position.update(status="PENDING", orders={})
    h.api.check_order_status.side_effect = lambda symbol, oid: (
        {"status": terminal, "executedQty": ".06", "cummulativeQuoteQty": "6"}
        if oid == 100 else {"status": "NEW"}
    )
    h.api.open_orders.side_effect = lambda *a: []
    h.api.place_order_raw.side_effect = RuntimeError("exchange rejected exits")
    result = h.run_ticks({"position": position})
    assert result["position"] is not None, "SC-01: terminal order status cannot erase executed exposure"
    assert result["position"]["qty"] == .06
    assert not result.get("last_closed"), "SC-01: a partial entry is not a closed position"
    assert result["position"]["status"] == "OPEN_FILLED"  # exit failure must retain exposure
    assert result["position"]["executedQty"] == ".06"
    assert h.api.place_order_raw.called
    h.hooks.on_after_position_closed.assert_not_called()


@pytest.mark.parametrize("terminal", ["CANCELED", "REJECTED", "EXPIRED"])
def test_pending_terminal_zero_fill_persists_close(executor_harness, position, terminal):
    h = executor_harness
    position.update(status="PENDING", orders={})
    h.api.check_order_status.side_effect = lambda *a: {"status": terminal, "executedQty": "0"}
    result = h.run_ticks({"position": position, "lock_until": h.now + 15})
    assert result["position"] is None
    assert result["last_closed"]["reason"] == "ENTRY_" + terminal
    assert result["lock_until"] == 0
    h.api.place_spot_market.assert_not_called()


@pytest.mark.parametrize("cancel_status", ["NEW", "PARTIALLY_FILLED", "UNKNOWN"])
def test_timeout_without_confirmed_cancel_never_places_planb(executor_harness, position, cancel_status):
    h = executor_harness
    position.update(status="PENDING", orders={}, opened_s=h.now - 200)
    h.api.check_order_status.side_effect = [
        {"status": "NEW", "executedQty": "0"},
        {"status": "NEW", "executedQty": "0"},
        {"status": cancel_status, "executedQty": "0"},
    ]
    h.api.cancel_order.side_effect = lambda *a: {}
    result = h.run_ticks({"position": position})
    assert result["position"]["order_id"] == 100
    assert result["position"]["status"] == "PENDING"
    assert result["position"]["planb_next_action_s"] == h.now + 10
    h.api.place_spot_market.assert_not_called()
    h.hooks.on_before_entry.assert_not_called()


def test_pending_fill_persists_actual_fill_before_hooks_and_exits(executor_harness, position):
    h = executor_harness
    position.update(status="PENDING", orders={}, qty=.4, opened_s=h.now)
    h.api.check_order_status.side_effect = lambda symbol, oid: (
        {"status": "FILLED", "executedQty": ".3", "cummulativeQuoteQty": "30.3"}
        if oid == 100 else {"status": "NEW"}
    )
    h.api.open_orders.side_effect = lambda *a: []
    def place(payload):
        durable = h.load()["position"]
        assert durable["status"] == "OPEN_FILLED"
        assert durable["qty"] == .3 and durable["entry_actual"] == 101.
        h.trace.append(("exit_order",))
        return {"orderId": {"STOP_LOSS_LIMIT": 333}.get(payload["type"], 111 if payload["price"] == "110" else 222)}
    h.api.place_order_raw.side_effect = place
    result = h.run_ticks({"position": position})
    assert result["position"]["status"] == "OPEN"
    assert result["position"]["qty"] == .3
    labels = [t[0] for t in h.trace]
    assert labels.index("after_open") < labels.index("exit_order")
    h.api.place_spot_market.assert_not_called()


def test_timeout_late_fill_after_cancel_prevents_second_entry(executor_harness, position):
    h = executor_harness
    position.update(status="PENDING", orders={}, qty=.3, opened_s=h.now - 200)
    h.api.check_order_status.side_effect = [
        {"status": "NEW", "executedQty": "0"},
        {"status": "NEW", "executedQty": "0"},
        {"status": "CANCELED", "executedQty": ".15", "cumulativeQuoteQty": "15.15"},
    ]
    h.api.cancel_order.side_effect = lambda *a: {"status": "CANCELED"}
    h.api.place_order_raw.side_effect = [{"orderId": 333}, {"orderId": 111}, {"orderId": 222}]
    result = h.run_ticks({"position": position})
    assert result["position"]["status"] == "OPEN"
    assert result["position"]["qty"] == .15
    assert result["position"]["entry_actual"] == 101.
    assert result["position"]["order_id"] == 100
    h.api.place_spot_market.assert_not_called()
    h.hooks.on_after_entry_opened.assert_called_once()
