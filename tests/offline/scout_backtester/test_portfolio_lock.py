from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from deltascout.research_bundle.scout_backtester.portfolio import replay_portfolio
from deltascout.research_bundle.scout_backtester.replay_engine import replay_independent

from .conftest import bar, candidate


def test_two_candidates_compete_and_blocked_result_keeps_independent_join(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(3, open_=100.5, high=100.6, low=100.2, close=100.3),
        bar(4, open_=100.4, high=100.5, low=100.4, close=100.4),
    ]
    first = candidate("LONG", candidate_id="C1")
    second = replace(candidate("LONG", candidate_id="C2"), signal_ts_utc=first.signal_ts_utc + timedelta(minutes=2))
    independent, _ = replay_independent([first, second], bars, replay_config)
    portfolio, _, opportunities = replay_portfolio([first, second], independent, replay_config)
    assert portfolio[0].entry_status == "FILLED"
    assert portfolio[1].entry_status == "BLOCKED"
    assert portfolio[1].blocked_reason == "POSITION_ALREADY_OPEN"
    assert opportunities[0]["blocked_independent_lifecycle"] == independent[1].lifecycle_class


def test_candidate_during_cooldown_is_blocked(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.6, low=100.2, close=100.3),
        bar(3, open_=100.4, high=100.5, low=100.4, close=100.4),
    ]
    first = candidate("LONG", candidate_id="C1")
    second = replace(candidate("LONG", candidate_id="C2"), signal_ts_utc=first.signal_ts_utc + timedelta(minutes=3))
    independent, _ = replay_independent([first, second], bars, replay_config)
    portfolio, _, _ = replay_portfolio([first, second], independent, replay_config)
    assert portfolio[1].blocked_reason == "COOLDOWN_ACTIVE"


def test_portfolio_state_after_synthetic_gap_is_not_counted_as_position_lock(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.5, low=100.5, close=100.5, synthetic=True),
        bar(3, open_=100.5, high=100.6, low=100.2, close=100.3),
        bar(4, open_=100.4, high=100.5, low=100.3, close=100.4),
    ]
    first = candidate("LONG", candidate_id="C1")
    second = replace(candidate("LONG", candidate_id="C2"), signal_ts_utc=first.signal_ts_utc + timedelta(minutes=3))
    independent, _ = replay_independent([first, second], bars, replay_config)
    portfolio, _, opportunities = replay_portfolio([first, second], independent, replay_config)
    assert portfolio[1].blocked_reason == "NO_FEED_COVERAGE"
    assert opportunities[0]["opportunity_cost_evaluable"] is False
