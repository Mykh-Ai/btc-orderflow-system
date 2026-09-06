from __future__ import annotations

from dataclasses import replace

import pytest

from deltascout.research_bundle.scout_backtester.contracts import (
    LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
    BacktestContractError,
    ExecutionPlan,
)
from deltascout.research_bundle.scout_backtester.fill_models import find_entry_fill
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate

from .conftest import BASE_TS, bar, candidate


def _plan(
    side: str = "LONG",
    *,
    entry: float = 100.0,
    stop: float = 99.0,
    tp1: float = 101.0,
) -> ExecutionPlan:
    risk = abs(entry - stop)
    tp2 = entry + 2 * risk if side == "LONG" else entry - 2 * risk
    return ExecutionPlan(
        candidate_id="C1",
        side=side,
        planned_entry_price=entry,
        initial_stop_price=stop,
        initial_risk_usd=risk,
        tp1_price=tp1,
        tp2_price=tp2,
        fixed_notional_usdc=3000.0,
        signal_reference_price_usdt=entry,
        reference_feed_close_usdt=entry,
        execution_feed_close_usdc=entry,
        conversion_ratio=1.0,
        conversion_reference_ts=BASE_TS,
        planned_entry_price_usdt=entry,
        initial_stop_price_usdt=stop,
        tp1_price_usdt=tp1,
        tp2_price_usdt=tp2,
        initial_swing_ts=BASE_TS,
        initial_swing_price_usdt=stop,
        initial_swing_volume=10.0,
        initial_swing_eligible_count=1,
        initial_swing_confirmed_count=1,
    )


def _config(replay_config, **changes):
    return replace(
        replay_config,
        fill_model_id=LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
        **changes,
    )


def test_guarded_planb_keeps_limit_fill_in_first_complete_bar(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.3, high=100.4, low=99.9, close=100.2),
        bar(2, open_=100.2, high=100.3, low=100.1, close=100.2),
    ]

    decision = find_entry_fill(
        bars,
        signal_ts=BASE_TS,
        plan=_plan(),
        config=_config(replay_config),
    )

    assert decision.entry_index == 1
    assert decision.entry_price == 100.0
    assert decision.fill_method == "LIMIT"
    assert decision.decision == "LIMIT_FILLED"


@pytest.mark.parametrize(
    ("side", "stop", "tp1", "timeout_open"),
    [
        ("LONG", 99.0, 101.0, 100.2),
        ("SHORT", 101.0, 99.0, 99.8),
    ],
)
def test_guarded_planb_market_fill_is_symmetric(
    side, stop, tp1, timeout_open, replay_config
) -> None:
    away = 100.3 if side == "LONG" else 99.7
    bars = [
        bar(0, open_=100.0, high=100.0, low=100.0, close=100.0),
        bar(1, open_=away, high=away, low=away, close=away),
        bar(2, open_=timeout_open, high=timeout_open, low=timeout_open, close=timeout_open),
    ]

    decision = find_entry_fill(
        bars,
        signal_ts=BASE_TS,
        plan=_plan(side, stop=stop, tp1=tp1),
        config=_config(replay_config),
    )

    assert decision.entry_index == 2
    assert decision.entry_price == timeout_open
    assert decision.fill_method == "PLANB_MARKET"
    assert decision.planb_deviation_usd == pytest.approx(0.2)
    assert decision.planb_max_deviation_usd == pytest.approx(0.25)


def test_guarded_planb_aborts_when_timeout_price_exceeds_quarter_r(replay_config) -> None:
    bars = [
        bar(0, open_=100.0, high=100.0, low=100.0, close=100.0),
        bar(1, open_=100.4, high=100.4, low=100.3, close=100.4),
        bar(2, open_=100.3, high=100.3, low=100.3, close=100.3),
    ]

    decision = find_entry_fill(
        bars,
        signal_ts=BASE_TS,
        plan=_plan(),
        config=_config(replay_config),
    )

    assert decision.entry_index is None
    assert decision.decision == "ABORT"
    assert decision.abort_reason == "PLANB_DEVIATION_TOO_LARGE"
    assert decision.planb_deviation_usd == pytest.approx(0.3)
    assert decision.planb_max_deviation_usd == pytest.approx(0.25)


def test_guarded_planb_checks_past_tp1_after_deviation_guard(replay_config) -> None:
    bars = [
        bar(0, open_=100.0, high=100.0, low=100.0, close=100.0),
        bar(1, open_=100.5, high=100.5, low=100.4, close=100.5),
        bar(2, open_=101.1, high=101.1, low=101.1, close=101.1),
    ]

    decision = find_entry_fill(
        bars,
        signal_ts=BASE_TS,
        plan=_plan(),
        config=_config(replay_config, planb_max_dev_usd=2.0),
    )

    assert decision.entry_index is None
    assert decision.abort_reason == "PLANB_PAST_TP1"


def test_planb_abort_is_persisted_in_trade_result_and_events(monkeypatch, replay_config) -> None:
    bars = [
        bar(0, open_=100.0, high=100.0, low=100.0, close=100.0),
        bar(1, open_=100.4, high=100.4, low=100.3, close=100.4),
        bar(2, open_=100.3, high=100.3, low=100.3, close=100.3),
    ]
    monkeypatch.setattr(
        "deltascout.research_bundle.scout_backtester.replay_engine.build_execution_plan",
        lambda *args, **kwargs: _plan(),
    )

    result, events = replay_candidate(candidate(), bars, _config(replay_config))

    assert result.entry_status == "ABORTED"
    assert result.lifecycle_class == "NO_FILL"
    assert result.planb_abort_reason == "PLANB_DEVIATION_TOO_LARGE"
    assert result.blocked_reason == "PLANB_DEVIATION_TOO_LARGE"
    assert [event.event_type for event in events][-1] == "ENTRY_PLANB_ABORTED"


def test_guarded_planb_requires_its_frozen_90_second_timeout(replay_config) -> None:
    config = _config(replay_config, live_entry_timeout_seconds=120)
    with pytest.raises(BacktestContractError, match="requires live_entry_timeout_seconds=90"):
        config.validate()
