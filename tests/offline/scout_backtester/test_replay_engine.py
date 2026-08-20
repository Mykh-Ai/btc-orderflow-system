from __future__ import annotations

import pytest

from deltascout.research_bundle.scout_backtester.contracts import TARGET_FIRST_SAME_BAR_POLICY_ID
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate

from .conftest import bar, candidate


@pytest.mark.parametrize(
    ("side", "bars", "expected"),
    [
        ("LONG", [bar(0, open_=100.4, high=100.4, low=100.4, close=100.4), bar(1, open_=100.5, high=100.6, low=100.4, close=100.5), bar(2, open_=100.5, high=100.6, low=100.2, close=100.3)], "PLAIN_SL"),
        ("SHORT", [bar(0, open_=99.6, high=99.6, low=99.6, close=99.6), bar(1, open_=99.5, high=99.6, low=99.4, close=99.5), bar(2, open_=99.5, high=99.8, low=99.4, close=99.7)], "PLAIN_SL"),
        ("LONG", [bar(0, open_=100.4, high=100.4, low=100.4, close=100.4), bar(1, open_=100.5, high=100.6, low=100.4, close=100.5), bar(2, open_=100.6, high=100.75, low=100.49, close=100.6)], "TP1_SL"),
        ("SHORT", [bar(0, open_=99.6, high=99.6, low=99.6, close=99.6), bar(1, open_=99.5, high=99.6, low=99.4, close=99.5), bar(2, open_=99.4, high=99.51, low=99.25, close=99.4)], "TP1_SL"),
    ],
)
def test_basic_lifecycle_symmetry(side, bars, expected, replay_config) -> None:
    result, _ = replay_candidate(candidate(side), bars, replay_config)
    assert result.lifecycle_class == expected


def test_entry_never_fills_and_end_of_data_unresolved(replay_config) -> None:
    no_fill_bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=101.0, high=101.2, low=100.8, close=101.0),
        bar(2, open_=101.0, high=101.2, low=100.8, close=101.0),
    ]
    no_fill, _ = replay_candidate(candidate("LONG"), no_fill_bars, replay_config)
    assert no_fill.lifecycle_class == "NO_FILL"
    unresolved_bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
    ]
    unresolved, _ = replay_candidate(candidate("LONG"), unresolved_bars, replay_config)
    assert unresolved.lifecycle_class == "UNRESOLVED_END_OF_DATA"


def test_same_bar_policy_changes_collision_outcome(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=101.0, low=100.2, close=100.6),
        bar(3, open_=100.6, high=100.7, low=100.4, close=100.5),
    ]
    conservative, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    optimistic_config = replay_config.__class__(**{**replay_config.to_dict(), "same_bar_policy_id": TARGET_FIRST_SAME_BAR_POLICY_ID})
    optimistic, _ = replay_candidate(candidate("LONG"), bars, optimistic_config)
    assert conservative.lifecycle_class == "PLAIN_SL"
    assert optimistic.lifecycle_class == "TP1_TP2_TRAILING_STOP"
    assert conservative.same_bar_ambiguous is True


def test_tp1_tp2_and_confirmed_trailing_has_no_future_leakage(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.7, high=101.0, low=100.6, close=100.9),
        bar(3, open_=100.9, high=101.1, low=100.85, close=101.0),
        bar(4, open_=101.0, high=101.05, low=100.75, close=100.8),
        bar(5, open_=100.9, high=101.3, low=100.78, close=101.2),
        bar(6, open_=101.2, high=101.3, low=100.9, close=101.0),
        bar(7, open_=101.1, high=101.5, low=100.95, close=101.4),
        bar(8, open_=101.2, high=101.3, low=100.9, close=100.95),
    ]
    result, events = replay_candidate(candidate("LONG"), bars, replay_config)
    assert result.lifecycle_class == "TP1_TP2_TRAILING_STOP"
    updates = [event for event in events if event.event_type == "TRAIL_UPDATED"]
    assert len(updates) >= 2
    assert updates[0].event_ts > result.trail_activation_ts


def test_short_tp1_tp2_multiple_trail_updates_and_stop(replay_config) -> None:
    bars = [
        bar(0, open_=99.6, high=99.6, low=99.6, close=99.6),
        bar(1, open_=99.5, high=99.6, low=99.4, close=99.5),
        bar(2, open_=99.3, high=99.4, low=99.0, close=99.0),
        bar(3, open_=99.0, high=99.1, low=98.9, close=99.0),
        bar(4, open_=99.05, high=99.15, low=99.0, close=99.1),
        bar(5, open_=99.0, high=99.12, low=98.7, close=98.8),
        bar(6, open_=98.9, high=99.1, low=98.8, close=98.9),
        bar(7, open_=98.8, high=98.95, low=98.5, close=98.6),
        bar(8, open_=98.8, high=99.0, low=98.7, close=98.9),
    ]
    result, events = replay_candidate(candidate("SHORT"), bars, replay_config)
    assert result.lifecycle_class == "TP1_TP2_TRAILING_STOP"
    assert len([event for event in events if event.event_type == "TRAIL_UPDATED"]) >= 2


def test_untrusted_synthetic_bar_interrupts_market_evidence(replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.5, low=100.5, close=100.5, synthetic=True),
        bar(3, open_=100.5, high=100.6, low=100.2, close=100.3),
    ]
    result, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    assert result.lifecycle_class == "UNRESOLVED_END_OF_DATA"
    assert result.blocked_reason == "NO_FEED_COVERAGE"
    assert result.feed_quality_class == "DEGRADED_SYNTHETIC"
