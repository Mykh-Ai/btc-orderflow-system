"""Safety/parity checks through real refactor adapters and durable JSON state."""
from copy import deepcopy
from decimal import Decimal
from unittest.mock import Mock

import pandas as pd
import pytest

import executor as ex
from executor_mod import entry_math, market_data, quote_sync, risk_math, state_store
from executor_mod.order_utils import validated_executed_qty
from test.sc01.conftest import executor_harness, position


def frame(end="2026-01-02T00:00:00Z"):
    return pd.DataFrame({
        "Timestamp": pd.date_range(end=end, periods=7, freq="min"),
        "price": [100.] * 7, "ClosePrice": [100.] * 7,
        "LowPrice": [98., 96.04, 98., 97.04, 98., 98., 98.],
        "HiPrice": [101., 103.06, 101., 102.06, 101., 101., 101.],
        "low_usdt": [98., 96.04, 98., 97.04, 98., 98., 98.],
        "high_usdt": [101., 103.06, 101., 102.06, 101., 101., 101.],
        "volume_1m": [1., 150., 1., 100., 1., 1., 1.],
        "swing_row_real": [True] * 7,
    })


@pytest.fixture
def math_env(monkeypatch):
    env = deepcopy(ex.ENV)
    env.update(INITIAL_SWING_LOOKBACK=7, INITIAL_SWING_LR=1,
               INITIAL_SWING_BUFFER_USD=.05, INITIAL_SWING_MAX_DISTANCE_USD=10.,
               TICK_SIZE=Decimal("0.1"), SL_PCT=.002)
    for module in (ex, entry_math, market_data, risk_math):
        monkeypatch.setattr(module, "ENV", env)
    return env


@pytest.mark.parametrize("side,expected", [("BUY", 95.9), ("SELL", 103.2)])
def test_structural_stop_volume_confirmation_buffer_and_outward_rounding(math_env, side, expected):
    selected = ex.select_volume_confirmed_initial_stop(frame(), 6, side, 100.)
    assert selected.stop_usdt == expected
    assert selected.swing_volume == 150.
    assert selected.eligible_count == 2 and selected.confirmed_count == 2
    assert selected.window_gap_count == 0
    assert selected.swing_ts == frame().iloc[1]["Timestamp"].to_pydatetime()


@pytest.mark.parametrize("side,expected", [("BUY", 96.9), ("SELL", 102.2)])
def test_equal_volume_uses_newest_confirmed_swing(math_env, side, expected):
    df = frame()
    df.loc[3, "volume_1m"] = 150.
    assert ex.select_volume_confirmed_initial_stop(df, 6, side, 100.).stop_usdt == expected


def test_distance_cap_applies_after_buffer_and_rounding(math_env):
    math_env["INITIAL_SWING_MAX_DISTANCE_USD"] = 4.
    selected = ex.select_volume_confirmed_initial_stop(frame(), 6, "BUY", 100.)
    assert selected.stop_usdt == 96.9 and selected.eligible_count == 1
    math_env["INITIAL_SWING_MAX_DISTANCE_USD"] = 2.
    with pytest.raises(ex.InitialStopSelectionError, match="NO_SWING_WITHIN_INITIAL_STOP_CAP"):
        ex.select_volume_confirmed_initial_stop(frame(), 6, "BUY", 100.)


def test_structural_window_excludes_future_unconfirmed_and_nonreal_rows(math_env):
    df = frame()
    # A future high-volume low must not influence the exact signal window.
    future = df.iloc[-1:].copy()
    future["Timestamp"] += pd.Timedelta(minutes=1)
    future["low_usdt"] = 50.
    future["volume_1m"] = 1e9
    df = pd.concat([df, future], ignore_index=True)
    assert ex.select_volume_confirmed_initial_stop(df, 6, "BUY", 100.).stop_usdt == 95.9
    df.loc[0, "swing_row_real"] = False
    assert ex.select_volume_confirmed_initial_stop(df, 6, "BUY", 100.).stop_usdt == 96.9
    df.loc[4, "swing_row_real"] = False
    with pytest.raises(ex.InitialStopSelectionError, match="NO_CONFIRMED_VOLUME_SWING"):
        ex.select_volume_confirmed_initial_stop(df, 6, "BUY", 100.)


@pytest.mark.parametrize("index,reason", [(-1, "MISSING_EXACT_SIGNAL_MINUTE"), (7, "MISSING_EXACT_SIGNAL_MINUTE"), (5, "NO_FULL_INITIAL_SWING_WINDOW")])
def test_invalid_exact_index_and_short_window_skip(math_env, index, reason):
    with pytest.raises(ex.InitialStopSelectionError, match=reason):
        ex.select_volume_confirmed_initial_stop(frame(), index, "BUY", 100.)


def test_schema_timestamp_and_policy_fail_loud(math_env):
    with pytest.raises(ex.InitialStopSelectionError, match="INITIAL_SWING_SCHEMA_MISSING"):
        ex.select_volume_confirmed_initial_stop(frame().drop(columns="volume_1m"), 6, "BUY", 100.)
    df = frame()
    df["Timestamp"] = df["Timestamp"].astype(object)
    df.loc[6, "Timestamp"] = "invalid"
    with pytest.raises(ex.InitialStopSelectionError, match="INVALID_INITIAL_SWING_TIMESTAMPS"):
        ex.select_volume_confirmed_initial_stop(df, 6, "BUY", 100.)
    math_env["INITIAL_STOP_POLICY"] = "other"
    with pytest.raises(ex.InitialStopSelectionError, match="UNSUPPORTED_INITIAL_STOP_POLICY"):
        ex.select_volume_confirmed_initial_stop(frame(), 6, "BUY", 100.)


@pytest.mark.parametrize("value,expected", [("2026-01-02T00:00:59Z", 6), ("2026-01-02T00:01:00Z", -1), ("bad", -1), (None, -1)])
def test_exact_minute_lookup_never_defaults_to_latest(math_env, value, expected):
    assert ex.locate_index_by_ts(frame(), value) == expected


@pytest.mark.parametrize("side,expected", [("BUY", 58950.), ("SELL", 61050.)])
def test_default_1440_bar_25_25_policy(executor_harness, side, expected):
    h = executor_harness
    df = pd.DataFrame({"Timestamp": pd.date_range(end=ex.iso_utc(), periods=1440, freq="min"),
                       "low_usdt": [59900.] * 1440, "high_usdt": [60100.] * 1440,
                       "volume_1m": [1.] * 1440, "swing_row_real": [True] * 1440})
    df.loc[700, ["low_usdt", "high_usdt", "volume_1m"]] = [59000., 61000., 999.]
    assert ex.select_volume_confirmed_initial_stop(df, 1439, side, 60000.).stop_usdt == expected


def test_same_cycle_quote_reads_both_mids_and_records_timestamp(math_env, monkeypatch):
    reader = Mock(side_effect=[60000., 60060.])
    monkeypatch.setattr(ex.binance_api, "get_mid_price", reader)
    snapshot = ex.get_usdt_usdc_quote_snapshot()
    assert [call.args[0] for call in reader.call_args_list] == ["BTCUSDT", "BTCUSDC"]
    assert snapshot.ratio == 1.001 and snapshot.mid_usdc == 60060.
    assert snapshot.observed_at_utc


@pytest.mark.parametrize("mids", [(100., 120.), (100., 90.), (0., 100.), (-1., 100.), (float("nan"), 100.), (100., float("inf")), (None, 100.), (100., "bad")])
def test_unreliable_quote_is_sync_error(math_env, monkeypatch, mids):
    monkeypatch.setattr(ex.binance_api, "get_mid_price", Mock(side_effect=mids))
    with pytest.raises(ex.QuoteSyncError):
        ex.get_usdt_usdc_quote_snapshot()


@pytest.mark.parametrize("stop,side,expected", [(95.05, "LONG", 96.), (95.05, "SHORT", 96.1)])
def test_conversion_rounds_outward_with_decimal_ratio(math_env, stop, side, expected):
    assert ex.convert_stop_usdt_to_usdc(stop, side, 1.01) == expected


@pytest.mark.parametrize("stop,ratio", [(float("nan"), 1.), (float("inf"), 1.), (-1., -1.), (1., 0.), (None, 1.)])
def test_invalid_converted_price_cannot_reach_order(math_env, stop, ratio):
    with pytest.raises(ex.QuoteSyncError):
        ex.convert_stop_usdt_to_usdc(stop, "LONG", ratio)


@pytest.mark.parametrize("side,stop,valid", [("LONG", 99.9, True), ("LONG", 100., False), ("SHORT", 100.1, True), ("SHORT", 100., False), ("LONG", float("nan"), False)])
def test_stop_validated_against_execution_mid(math_env, side, stop, valid):
    if valid:
        ex._validate_stop_against_usdc_mid(side, stop, 100.)
    else:
        with pytest.raises(ex.QuoteSyncError):
            ex._validate_stop_against_usdc_mid(side, stop, 100.)


def prepare_entry(h):
    h.env.update(INITIAL_SWING_LOOKBACK=7, INITIAL_SWING_LR=1,
                 INITIAL_SWING_BUFFER_USD=.05, INITIAL_SWING_MAX_DISTANCE_USD=10.,
                 TICK_SIZE=Decimal("0.1"))
    frame(ex.iso_utc()).to_csv(h.env["AGG_CSV"], index=False)
    h.api.open_orders.side_effect = lambda *args: []
    h.api.place_spot_limit.side_effect = lambda *args, **kwargs: {"orderId": 123}
    h.api.get_mid_price.side_effect = lambda symbol: 101. if symbol == "BTCUSDC" else 100.
    return {"ts": ex.iso_utc(), "action": "PEAK", "source": "DeltaScout", "kind": "long", "price": 100.}


@pytest.mark.parametrize("kind", ["long", "short"])
def test_real_entry_pipeline_persists_stop_quote_and_open_text(executor_harness, kind):
    h = executor_harness
    event = prepare_entry(h)
    event["kind"] = kind
    loaded = h.run_ticks({"position": None}, events=[event])
    pos = loaded["position"]
    assert pos["status"] == "PENDING"
    assert pos["initial_swing"]["policy"] == "VOLUME_SWING_24H_LR25"
    assert pos["entry_conversion"]["ratio"] == 1.01
    notice = next(t[1] for t in h.trace if t[0] == "webhook" and t[1]["event"] == "OPEN")
    for label in ("Symbol: BTCUSDC", "Side:", "Volume:", "Entry:", "Stop-loss:", "R (entry to SL):", "Take profit 1:", "Take profit 2:", "%"):
        assert label in notice["text"]
    assert "1.00R" not in notice["text"] and "2.00R" not in notice["text"]
    assert notice["tp1_r"] is not None and notice["tp2_r"] is not None
    h.api.place_spot_limit.assert_called_once()
    # A restart retains intent/geometry and blocks another entry.
    h.now += 20
    h.api.check_order_status.side_effect = lambda *args: {"status": "NEW", "executedQty": "0"}
    event["ts"] = ex.iso_utc()
    restarted = h.run_ticks(h.load(), events=[event])
    assert restarted["position"]["initial_swing"] == pos["initial_swing"]
    assert restarted["position"]["entry_conversion"] == pos["entry_conversion"]
    h.api.place_spot_limit.assert_called_once()


@pytest.mark.parametrize("issue,reason", [("missing_minute", "MISSING_EXACT_SIGNAL_MINUTE"), ("invalid_ts", "MISSING_EXACT_SIGNAL_MINUTE"), ("quote_ratio", "USDT_USDC_SYNC_FAILED"), ("quote_lookup", "USDT_USDC_SYNC_FAILED"), ("invalid_sl", "INITIAL_STOP_INVALID_ON_USDC"), ("missing_schema", "INITIAL_SWING_SCHEMA_MISSING")])
def test_real_entry_skips_unsafe_context_before_order(executor_harness, issue, reason):
    h = executor_harness
    event = prepare_entry(h)
    if issue == "missing_minute":
        event["ts"] = pd.Timestamp(event["ts"]) - pd.Timedelta(minutes=20)
        event["ts"] = event["ts"].isoformat()
        h.env["MAX_PEAK_AGE_SEC"] = 0
    elif issue == "invalid_ts":
        event["ts"] = "bad"
    elif issue == "quote_ratio":
        h.api.get_mid_price.side_effect = lambda symbol: 120. if symbol == "BTCUSDC" else 100.
    elif issue == "quote_lookup":
        h.api.get_mid_price.side_effect = TimeoutError("quote unavailable")
    elif issue == "invalid_sl":
        h.api.get_mid_price.side_effect = lambda symbol: 80.
    elif issue == "missing_schema":
        frame(ex.iso_utc()).drop(columns="volume_1m").to_csv(h.env["AGG_CSV"], index=False)
    result = h.run_ticks({"position": None}, events=[event])
    assert result["position"] is None
    assert any(t[:2] == ("log", "SKIP_OPEN") and t[2]["reason"] == reason for t in h.trace)
    h.api.place_spot_limit.assert_not_called()
    h.api.place_spot_market.assert_not_called()


@pytest.mark.parametrize("activation", [True, False])
@pytest.mark.parametrize("error", ["ratio", "lookup", "stop"])
def test_trailing_sync_failure_keeps_protective_sl_on_restart(executor_harness, position, monkeypatch, activation, error):
    h = executor_harness
    position.update(tp1_done=True, tp2_done=not activation, trail_active=not activation,
                    trail_qty=.04, trail_sl_price=90., trail_last_update_s=0.,
                    trail_wait_confirm=False, sl_done=False)
    position["orders"] = {"sl": 333, "tp2": 222 if activation else None, "qty3": .04}
    h.api.open_orders.side_effect = lambda *args: [{"orderId": 333}]
    h.api.check_order_status.side_effect = lambda symbol, oid: {"status": "FILLED" if oid == 222 else "NEW"}
    monkeypatch.setattr(ex, "_trail_desired_stop_from_agg", lambda pos: 95.)
    if error == "ratio":
        h.api.get_mid_price.side_effect = lambda symbol: 120. if symbol == "BTCUSDC" else 100.
    elif error == "lookup":
        h.api.get_mid_price.side_effect = TimeoutError("quote unavailable")
    else:
        h.api.get_mid_price.side_effect = lambda symbol: 90.
    # Reference can be recorded from the USDT feed; no source/execution mixing.
    frame(ex.iso_utc()).to_csv(h.env["AGG_CSV"], index=False)
    result = h.run_ticks({"position": position})
    assert result["position"]["orders"]["sl"] == 333
    assert result["position"]["trail_sl_price"] == 90.
    h.api.cancel_order.assert_not_called()
    h.api.place_order_raw.assert_not_called()
    assert any(t[:2] == ("log", "TRAIL_USDC_SYNC_ERROR") for t in h.trace)
    assert any(t[0] == "webhook" and t[1]["event"] == "TRAIL_USDC_SYNC_ERROR" for t in h.trace)
    h.now += 30
    restarted = h.run_ticks(h.load())
    assert restarted["position"]["orders"]["sl"] == 333
    h.api.cancel_order.assert_not_called()
    h.api.place_order_raw.assert_not_called()


def test_trailing_uses_current_ratio_and_persists_quote_audit(executor_harness, position, monkeypatch):
    h = executor_harness
    position.update(tp1_done=True, tp2_done=True, trail_active=True, trail_qty=.04,
                    trail_sl_price=90., trail_last_update_s=0., k_entry=.95)
    position["orders"] = {"sl": 333}
    h.env["TRAIL_STEP_USD"] = 1.
    h.api.open_orders.side_effect = lambda *args: [{"orderId": 333}]
    h.api.check_order_status.side_effect = lambda *args: {"status": "NEW"}
    h.api.get_mid_price.side_effect = lambda symbol: 101. if symbol == "BTCUSDC" else 100.
    monkeypatch.setattr(ex, "_trail_desired_stop_from_agg", lambda pos: 95.)
    def cancel(*args):
        h.api.check_order_status.side_effect = lambda *args: {"status": "CANCELED"}
        return {}
    h.api.cancel_order.side_effect = cancel
    h.api.place_order_raw.side_effect = lambda payload: {"orderId": 444}
    result = h.run_ticks({"position": position})
    pos = result["position"]
    assert pos["orders"]["sl"] == 444 and pos["trail_sl_price"] == 95.95
    assert pos["trail_sl_price_usdt"] == 95. and pos["trail_conversion_ratio"] == 1.01
    assert pos["trail_conversion_mid_usdt"] == 100. and pos["trail_conversion_mid_usdc"] == 101.


@pytest.mark.parametrize("value", [None, "", "bad", "nan", "inf", "-.1", False, True, "1e-1000", "1e1000"])
@pytest.mark.parametrize("phase", ["timeout", "after_cancel", "reconciliation"])
def test_terminal_unknown_qty_never_releases_or_reenters(executor_harness, position, value, phase):
    h = executor_harness
    position.update(status="PENDING", orders={}, opened_s=h.now - 200, last_poll_s=h.now)
    unknown = {"status": "CANCELED", "executedQty": value}
    if phase == "reconciliation":
        h.api.open_orders.side_effect = lambda *args: []
        h.api.check_order_status.side_effect = lambda *args: unknown
        h.save({"position": position})
        st = h.load()
        h.reconcile(st)
        assert st["position"] is not None
    else:
        h.api.check_order_status.side_effect = [unknown] if phase == "timeout" else [{"status": "NEW", "executedQty": "0"}, unknown]
        h.api.cancel_order.side_effect = lambda *args: {}
        result = h.run_ticks({"position": position})
        assert result["position"]["status"] == "PENDING"
    h.api.place_spot_market.assert_not_called()
    h.api.place_order_raw.assert_not_called()
    h.hooks.on_after_position_closed.assert_not_called()


def test_reconciliation_uncertainty_throttle_survives_restart(executor_harness, position, monkeypatch):
    h = executor_harness
    h.env.update(I13_CLEAR_STATE_ON_EXCHANGE_CLEAR=True, RECON_THROTTLE_SEC=600)
    h.api.open_orders.side_effect = lambda *args: []
    h.api.check_order_status.side_effect = lambda *args: {"status": "NEW", "executedQty": "0"}
    monkeypatch.setattr(ex, "_exchange_position_exists", lambda symbol: None)
    h.save({"position": position})
    h.reconcile(h.load())
    saved = h.load()
    assert saved["position"]["recon"]["last_emit"]["pos_clear:unknown"] == h.now
    h.now += 1
    h.reconcile(h.load())
    assert sum(t[:2] == ("log", "POSITION_CLEAR_EXCHANGE_UNKNOWN") for t in h.trace) == 1


def test_failsafe_intent_blocks_cleanup_even_with_legacy_abort_status(executor_harness, position):
    h = executor_harness
    position.update(status="ENTRY_CANCELED", failsafe_flatten={"next_check_s": h.now + 600})
    assert state_store.has_open_position({"position": position})
    event = {"ts": ex.iso_utc(), "action": "PEAK", "source": "DeltaScout", "kind": "long", "price": 100.}
    result = h.run_ticks({"position": position}, events=[event])
    assert result["position"]["status"] == "ENTRY_CANCELED"
    h.api.place_spot_market.assert_not_called()
    h.api.place_spot_limit.assert_not_called()
    h.api.open_orders.assert_not_called()


def test_refactored_clear_persists_real_margin_hook_flags_and_error_evidence(executor_harness, position, monkeypatch):
    h = executor_harness
    from executor_mod import margin_guard, margin_policy
    monkeypatch.setattr(ex, "margin_guard", margin_guard)
    for name, value in {"ENV": h.env, "api_client": h.api, "save_state_fn": h.save, "log_event": ex.log_event,
                        "send_webhook_fn": ex.send_webhook, "margin_policy": margin_policy}.items():
        monkeypatch.setattr(margin_guard, name, value)
    monkeypatch.setattr(margin_policy, "repay_if_any", lambda *args: None)
    # Missing debt evidence must be durable error, not clean, while flags clear.
    h.api.margin_account.side_effect = lambda *args, **kwargs: {}
    st = {"position": position, "margin": {"active_trade_key": position["trade_key"], "is_isolated": False},
          "mg_runtime": {"borrow_done": {position["trade_key"]: True}, "borrow_started": {position["trade_key"]: True},
                         "after_open_done": {position["trade_key"]: True}}}
    h.save(st)
    ex._clear_position_slot(st, "TEST_CONFIRMED_CLOSE")
    loaded = h.load()
    assert loaded["position"] is None and loaded["margin"]["active_trade_key"] is None
    for flag in ("borrow_done", "borrow_started", "after_open_done"):
        assert position["trade_key"] not in loaded["mg_runtime"][flag]
    assert loaded["margin"]["post_close_debt_cleanup"]["last_result"]["cleanup_status"] == "error"


@pytest.mark.parametrize("minimum,maximum", [(float("nan"), 1.05), (.95, float("inf")), (1.05, .95)])
def test_invalid_ratio_sanity_configuration_fails_closed(math_env, monkeypatch, minimum, maximum):
    math_env.update(USDT_USDC_RATIO_MIN=minimum, USDT_USDC_RATIO_MAX=maximum)
    monkeypatch.setattr(ex.binance_api, "get_mid_price", lambda symbol: 100.)
    with pytest.raises(ex.QuoteSyncError, match="sanity band"):
        ex.get_usdt_usdc_quote_snapshot()


def test_structural_gap_count_preserves_current_policy_evidence(math_env):
    df = frame()
    df.loc[6, "Timestamp"] += pd.Timedelta(minutes=1)
    selection = ex.select_volume_confirmed_initial_stop(df, 6, "BUY", 100.)
    assert selection.window_gap_count == 1 and selection.stop_usdt == 95.9


@pytest.mark.parametrize("qty", ["bad", None, float("nan"), float("inf"), -.1])
def test_invalid_failsafe_quantity_is_visible_and_never_submits(executor_harness, position, qty):
    h = executor_harness
    h.env.update(FAILSAFE_FLATTEN=True, FAILSAFE_EXITS_MAX_TRIES=1, FAILSAFE_EXITS_GRACE_SEC=0)
    position.update(status="OPEN_FILLED", orders={}, qty=qty)
    h.api.place_order_raw.side_effect = RuntimeError("exits unavailable")
    st = {"position": position}
    ex.handle_open_filled_exits_retry(st)
    assert st["position"] is position and "failsafe_flatten" not in position
    h.api.flatten_market.assert_not_called()
    assert any(t[:2] == ("log", "FAILSAFE_FLATTEN_UNCONFIRMED") for t in h.trace)
    assert any(t[0] == "webhook" and t[1]["event"] == "FAILSAFE_FLATTEN_UNCONFIRMED" for t in h.trace)


@pytest.mark.parametrize("intent", [None, "bad", {"next_check_s": "bad"}, {"next_check_s": float("nan")}])
def test_malformed_persisted_intent_stays_owned_and_visible(executor_harness, position, intent):
    h = executor_harness
    position.update(status="OPEN_FILLED", orders={}, failsafe_flatten=intent)
    h.save({"position": position})
    restarted = h.run_ticks(h.load())
    assert restarted["position"] is not None
    h.api.flatten_market.assert_not_called()
    h.api.get_order_by_client_id.assert_not_called()
    h.api.place_order_raw.assert_not_called()
    assert any(t[:2] == ("log", "FAILSAFE_FLATTEN_UNCONFIRMED") for t in h.trace)
    assert any(t[0] == "webhook" and t[1]["event"] == "FAILSAFE_FLATTEN_UNCONFIRMED" for t in h.trace)
