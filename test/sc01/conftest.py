"""SC-01 fixtures scoped to this directory; real save/load, no live API calls."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

import executor as ex
from executor_mod import event_dedup, exits_flow, market_data, risk_math, state_store


BASE_ENV = deepcopy(ex.ENV)


class EndTick(BaseException):
    """Exit main only between ticks, never inside an Exception handler."""


@pytest.fixture
def executor_harness(monkeypatch, tmp_path):
    env = deepcopy(BASE_ENV)
    env.update(
        TRADE_MODE="margin", MARGIN_ISOLATED="FALSE", MARGIN_BORROW_MODE="manual",
        MARGIN_SIDE_EFFECT="NO_SIDE_EFFECT", SYMBOL="BTCUSDC", INVAR_ENABLED=False,
        LIVE_VALIDATE_ONLY=False, FAILSAFE_FLATTEN=False, LLM_TRADE_JUDGE_ENABLED=False,
        TICK_SIZE=Decimal("0.01"), QTY_STEP=Decimal("0.00001"),
        MIN_QTY=Decimal("0.00001"), MIN_NOTIONAL=5., QTY_USD=100.,
        ENTRY_MODE="LIMIT_THEN_MARKET", ENTRY_OFFSET_USD=.5, TP_R_LIST=[1., 2.],
        LIVE_STATUS_POLL_EVERY=10, LIVE_ENTRY_TIMEOUT_SEC=90,
        EXITS_RETRY_EVERY_SEC=15, MANAGE_EVERY_SEC=15, COOLDOWN_SEC=180, LOCK_SEC=15,
        TRAIL_ACTIVATE_AFTER_TP2=True, TRAIL_SOURCE="AGG", TRAIL_STEP_USD=20.,
        TRAIL_UPDATE_EVERY_SEC=20, I13_CLEAR_STATE_ON_EXCHANGE_CLEAR=False,
        STATE_FN=str(tmp_path / "state.json"), AGG_CSV=str(tmp_path / "feed.csv"),
        INITIAL_STOP_POLICY="VOLUME_SWING_24H_LR25", INITIAL_SWING_LOOKBACK=1440,
        INITIAL_SWING_LR=25, INITIAL_SWING_BUFFER_USD=50., INITIAL_SWING_MAX_DISTANCE_USD=1200.,
        INITIAL_SWING_REQUIRE_FULL_WINDOW=True, SL_PCT=.002,
        STRICT_SOURCE=True, DEDUP_PRICE_DECIMALS=2, MAX_PEAK_AGE_SEC=120,
        USDT_USDC_RATIO_MIN=.95, USDT_USDC_RATIO_MAX=1.05,
    )
    for mod in (ex, risk_math, market_data, exits_flow):
        monkeypatch.setattr(mod, "ENV", env)
    monkeypatch.setenv("STATE_FN", env["STATE_FN"])
    # Modules may read these environment paths directly; all remain temporary.
    for key in ("EXEC_LOG", "TRADE_OUTCOMES_FN", "TRADE_EXECUTION_SNAPSHOTS_FN",
                "LLM_TRADE_JUDGE_VERDICTS_FN", "INVAR_STATE_FN"):
        monkeypatch.setenv(key, str(tmp_path / (key.lower() + ".jsonl")))

    network_attempts = []
    def reject_network(*args, **kwargs):
        network_attempts.append(True)
        raise AssertionError("network forbidden in characterization")
    monkeypatch.setattr(requests.sessions.Session, "request", reject_network)

    trace, unexpected = [], []
    h = SimpleNamespace(env=env, trace=trace, now=1767312000., state_path=tmp_path / "state.json")
    def forbidden(name):
        def call(*args, **kwargs):
            unexpected.append(name)
            raise AssertionError("unconfigured exchange call: " + name)
        return call
    api = Mock(spec=ex.binance_api)
    for name in ("open_orders", "check_order_status", "get_order", "get_order_by_client_id", "cancel_order",
                 "place_order_raw", "place_spot_market", "place_spot_limit", "flatten_market",
                 "get_mid_price", "_planb_exec_price", "margin_account", "margin_borrow",
                 "margin_repay", "get_margin_debt_snapshot", "margin_my_trades"):
        getattr(api, name).side_effect = forbidden(name)
    api._env.return_value = env
    monkeypatch.setattr(ex, "binance_api", api)
    h.api = api

    def save(st):
        state_store.save_state(st)
        trace.append(("save", deepcopy(st)))
    h.save, h.load = save, state_store.load_state
    monkeypatch.setattr(ex, "save_state", save)
    monkeypatch.setattr(ex, "load_state", state_store.load_state)
    monkeypatch.setattr(ex, "_now_s", lambda: h.now)
    monkeypatch.setattr(ex, "iso_utc", lambda dt=None: (dt or datetime.fromtimestamp(h.now, timezone.utc)).isoformat())
    monkeypatch.setattr(ex, "time", SimpleNamespace(time=lambda: h.now, sleep=None))
    monkeypatch.setattr(ex, "locked", lambda st: h.now < float(st.get("lock_until") or 0))
    monkeypatch.setattr(ex, "in_cooldown", lambda st: h.now < float(st.get("cooldown_until") or 0))
    monkeypatch.setattr(ex, "log_event", lambda event, **kw: trace.append(("log", event, deepcopy(kw))))
    monkeypatch.setattr(ex, "send_webhook", lambda payload: trace.append(("webhook", deepcopy(payload))))
    for name, value in {"_ENV": env, "_iso_utc": ex.iso_utc, "_save_state": save, "_log_event": ex.log_event}.items():
        monkeypatch.setattr(event_dedup, name, value)
    monkeypatch.setattr(ex, "atexit", SimpleNamespace(register=lambda fn: None))
    monkeypatch.setattr(ex, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    monkeypatch.setattr(ex, "bootstrap_seen_keys_from_tail", lambda *args: None)
    monkeypatch.setattr(ex, "_preflight_margin_cross_usdc", lambda: None)
    monkeypatch.setattr(ex, "read_tail_lines", lambda *args, **kwargs: [])
    # Individual recon tests invoke the saved real callable directly.
    h.reconcile = ex.sync_from_binance
    monkeypatch.setattr(ex, "sync_from_binance", lambda st: None)
    hooks = SimpleNamespace(
        on_startup=Mock(), on_shutdown=Mock(),
        on_before_entry=Mock(side_effect=lambda *a, **k: trace.append(("before_entry",))),
        on_after_entry_opened=Mock(side_effect=lambda *a, **k: trace.append(("after_open",))),
        on_after_position_closed=Mock(side_effect=lambda *a, **k: trace.append(("after_close",))),
    )
    monkeypatch.setattr(ex, "margin_guard", hooks)
    h.hooks = hooks
    def snapshot(st, source, **kwargs):
        trace.append(("snapshot", source, deepcopy(st), kwargs))
        return None
    monkeypatch.setattr(ex, "_record_trade_execution_snapshot", snapshot)
    monkeypatch.setattr(ex.trade_outcome_archive, "record_outcome",
                        lambda st, *a: trace.append(("archive", deepcopy(st))))
    monkeypatch.setattr(ex, "_send_trade_closed_summary", lambda *a: trace.append(("summary",)))
    monkeypatch.setattr(ex.llm_trade_judge, "maybe_record_llm_pretrade_judge",
                        lambda *a, **kw: trace.append(("judge",)))
    def baseline(api, env, symbol, tk, kind):
        trace.append(("baseline", tk, kind))
        return {"trade_key": tk, "baseline_kind": kind}
    monkeypatch.setattr(ex.baseline_policy, "take_snapshot", baseline)
    for name, value in {
        "save_state": save, "log_event": ex.log_event, "send_webhook": ex.send_webhook,
        "validate_exit_plan": lambda *a, **kw: ex.validate_exit_plan(*a, **kw),
        "place_exits_v15": lambda *a, **kw: ex.place_exits_v15(*a, **kw),
        "post_exits_success_hook": lambda *a: trace.append(("judge",)),
    }.items():
        monkeypatch.setattr(exits_flow, name, value)

    def run_ticks(st, ticks=1, events=()):
        import json
        state_store.save_state(st)
        trace.clear()
        monkeypatch.setattr(ex, "read_tail_lines", lambda *a, **kw: [json.dumps(e) for e in events])
        count = 0
        def sleep(seconds):
            nonlocal count
            if count >= ticks:
                raise EndTick()
            count += 1
        ex.time.sleep = sleep
        with pytest.raises(EndTick):
            ex.main()
        return h.load()
    h.run_ticks = run_ticks
    yield h
    assert not network_attempts, "a characterization attempted real HTTP"
    assert not unexpected, "unexpected exchange calls: " + repr(unexpected)


@pytest.fixture
def position():
    return {
        "mode": "live", "status": "OPEN", "side": "LONG", "qty": .12,
        "order_id": 100, "client_id": "EX_EN_AUDIT", "trade_key": "EX_EN_AUDIT",
        "opened_s": 1767311800., "opened_at": "2026-01-01T23:56:40+00:00",
        "entry_actual": 100.25, "prices": {"entry": 100., "sl": 90., "tp1": 110., "tp2": 120.},
        "orders": {"sl": 333, "tp1": 111, "tp2": 222, "qty1": .04, "qty2": .04, "qty3": .04},
    }
