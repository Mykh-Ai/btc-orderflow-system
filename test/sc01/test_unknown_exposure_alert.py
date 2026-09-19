"""SC-01 unknown exposure: critical alerts survive real state save/reload."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

import executor as ex


EVENT = "ENTRY_TERMINAL_QTY_UNKNOWN"
KEY = "entry_terminal_qty_unknown:100"
INVALID = [
    {}, {"executedQty": None}, {"executedQty": ""}, {"executedQty": "bad"},
    {"executedQty": "NaN"}, {"executedQty": "Inf"}, {"executedQty": "-Inf"},
    {"executedQty": "-.1"}, {"executedQty": False}, {"executedQty": True},
    {"executedQty": "1e-1000"}, {"executedQty": "1e1000"},
]


def setup_unknown(h, position, phase, payload, terminal="CANCELED"):
    position.update(status="PENDING", orders={})
    unknown = {"status": terminal, **payload}
    if phase == "poll":
        position.update(opened_s=h.now, last_poll_s=0.)
        h.api.check_order_status.side_effect = lambda *a: unknown
    elif phase == "timeout":
        position.update(opened_s=h.now - 200, last_poll_s=h.now + 1000)
        h.api.check_order_status.side_effect = lambda *a: unknown
    else:
        position.update(opened_s=h.now - 200, last_poll_s=h.now + 1000)
        calls = 0
        def lookup(*args):
            nonlocal calls
            calls += 1
            return {"status": "NEW", "executedQty": "0"} if calls % 2 else unknown
        h.api.check_order_status.side_effect = lookup
        h.api.cancel_order.side_effect = lambda *a: {}


def alerts(h):
    return [t[1] for t in h.trace if t[0] == "webhook" and t[1]["event"] == EVENT]


def assert_owned(h, result, original, clear):
    pos = result["position"]
    assert pos["status"] == "PENDING"
    for field in ("order_id", "client_id", "trade_key", "qty", "prices", "orders"):
        assert pos[field] == original[field]
    assert not result.get("last_closed")
    clear.assert_not_called()
    h.hooks.on_after_position_closed.assert_not_called()
    h.hooks.on_before_entry.assert_not_called()
    h.hooks.on_after_entry_opened.assert_not_called()
    for name in ("place_spot_market", "place_spot_limit", "place_order_raw", "flatten_market"):
        getattr(h.api, name).assert_not_called()
    assert not any(t[0] in ("snapshot", "archive", "after_close") for t in h.trace)


@pytest.mark.parametrize("terminal", ["CANCELED", "EXPIRED", "REJECTED"])
@pytest.mark.parametrize("phase", ["poll", "timeout", "after_cancel"])
@pytest.mark.parametrize("payload", INVALID)
def test_unreliable_terminal_qty_alerts_and_retains_ownership(
        executor_harness, position, monkeypatch, terminal, phase, payload):
    h = executor_harness
    setup_unknown(h, position, phase, payload, terminal)
    original = deepcopy(position)
    clear = Mock()
    monkeypatch.setattr(ex, "_clear_position_slot", clear)
    # A competing signal is processed through the existing PENDING ownership guard.
    event = {"ts": ex.iso_utc(), "action": "PEAK", "source": "DeltaScout",
             "kind": "long", "price": 100.}
    durable_at_alert = []
    def webhook(data):
        durable_at_alert.append(h.load())
        h.trace.append(("webhook", deepcopy(data)))
    monkeypatch.setattr(ex, "send_webhook", webhook)
    result = h.run_ticks({"position": position}, events=(event,))
    assert_owned(h, result, original, clear)
    assert len(alerts(h)) == 1
    alert = alerts(h)[0]
    assert alert["severity"] == "CRITICAL" and alert["status"] == terminal
    assert alert["phase"] == phase and alert["order_id"] == 100
    assert alert["executedQty_present"] == ("executedQty" in payload)
    assert not alert["alert_suppressed"]
    assert any(t[:2] == ("log", EVENT) for t in h.trace)
    assert not any(t[:2] == ("log", "LIVE_POLL_ERROR") for t in h.trace)
    assert result["position"]["recon"]["last_emit"][KEY] == h.now
    assert durable_at_alert[0]["position"]["status"] == "PENDING"
    assert durable_at_alert[0]["position"]["recon"]["last_emit"][KEY] == h.now
    if phase != "after_cancel":
        h.api.cancel_order.assert_not_called()


@pytest.mark.parametrize("phase", ["poll", "timeout", "after_cancel"])
def test_repeated_poll_and_reload_throttle_expires_without_sliding(
        executor_harness, position, monkeypatch, phase):
    h = executor_harness
    h.env["RECON_THROTTLE_SEC"] = 60
    setup_unknown(h, position, phase, {})
    original = deepcopy(position)
    clear = Mock()
    monkeypatch.setattr(ex, "_clear_position_slot", clear)
    emitted_at = h.now
    result = h.run_ticks({"position": position})
    assert len(alerts(h)) == 1
    # Same-process repeated polls also use the saved throttle.
    h.now += 10
    ex.pending_entry_flow.handle_pending_position(
        result, env=h.env, binance_api=h.api, save_state_fn=h.save,
        log_event_fn=ex.log_event, send_webhook_fn=ex.send_webhook,
        clear_position_slot_fn=clear, now_fn=lambda: h.now, iso_utc_fn=ex.iso_utc,
        time_fn=lambda: h.now, round_qty_fn=ex.round_qty, fmt_price_fn=ex.fmt_price,
        avg_fill_price_fn=ex._avg_fill_price, oid_int_fn=ex._oid_int,
        planb_market_allowed_fn=ex._planb_market_allowed,
        margin_before_entry_fn=h.hooks.on_before_entry,
        margin_after_entry_opened_fn=h.hooks.on_after_entry_opened,
        ensure_exits_fn=ex.exits_flow.ensure_exits)
    assert len(alerts(h)) == 1
    # Simulated restart: main() re-reads the actual persisted JSON each time.
    for elapsed in (10, 20, 50, 59):
        h.now = emitted_at + elapsed
        result = h.run_ticks(h.load())
        assert not alerts(h)
        assert result["position"]["recon"]["last_emit"][KEY] == emitted_at
        assert_owned(h, result, original, clear)
    h.now = emitted_at + 60
    result = h.run_ticks(h.load())
    assert len(alerts(h)) == 1
    assert result["position"]["recon"]["last_emit"][KEY] == h.now
    assert_owned(h, result, original, clear)


def test_changed_terminal_status_or_bad_value_shares_order_throttle(
        executor_harness, position):
    h = executor_harness
    h.env["RECON_THROTTLE_SEC"] = 60
    setup_unknown(h, position, "poll", {})
    first = h.run_ticks({"position": position})
    assert len(alerts(h)) == 1
    h.now += 10
    h.api.check_order_status.side_effect = lambda *a: {"status": "REJECTED", "executedQty": "NaN"}
    result = h.run_ticks(h.load())
    assert not alerts(h)
    assert result["position"]["recon"]["last_emit"] == first["position"]["recon"]["last_emit"]
    assert any(t[:2] == ("log", EVENT) and t[2]["alert_suppressed"] for t in h.trace)


def test_invariant_throttle_fallback_and_existing_reconciliation_metadata(
        executor_harness, position):
    h = executor_harness
    h.env.pop("RECON_THROTTLE_SEC", None)
    h.env["INVAR_THROTTLE_SEC"] = 30
    setup_unknown(h, position, "timeout", {})
    position["recon"] = {"last_emit": {"pos_clear:unknown": h.now - 1}, "existing": True}
    result = h.run_ticks({"position": position})
    assert alerts(h)[0]["throttle_sec"] == 30
    assert result["position"]["recon"]["existing"]
    assert result["position"]["recon"]["last_emit"]["pos_clear:unknown"] == h.now - 1
    h.now += 29
    result = h.run_ticks(h.load())
    assert not alerts(h)
    h.now += 1
    h.run_ticks(h.load())
    assert len(alerts(h)) == 1


def test_webhook_failure_keeps_durable_reservation_and_ownership(
        executor_harness, position, monkeypatch):
    h = executor_harness
    setup_unknown(h, position, "poll", {})
    webhook = Mock(side_effect=RuntimeError("operator webhook unavailable"))
    monkeypatch.setattr(ex, "send_webhook", webhook)
    result = h.run_ticks({"position": position})
    assert result["position"]["status"] == "PENDING"
    assert result["position"]["recon"]["last_emit"][KEY] == h.now
    assert any(t[:2] == ("log", EVENT) for t in h.trace)
    h.now += 10
    result = h.run_ticks(h.load())
    webhook.assert_called_once()
    assert result["position"]["status"] == "PENDING"
    h.api.place_spot_market.assert_not_called()
