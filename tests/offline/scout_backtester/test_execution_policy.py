from __future__ import annotations

import pytest

from deltascout.research_bundle.scout_backtester.contracts import InitialStopSelectionError
from deltascout.research_bundle.scout_backtester.execution_policy import (
    build_entry_price,
    compute_targets,
    initial_stop,
    notional_to_qty,
    select_volume_confirmed_initial_stop,
    split_quantity,
)

from .conftest import bar


def test_executor_plan_math_is_long_short_symmetric(replay_config) -> None:
    long_entry = build_entry_price("LONG", 100.0, replay_config)
    short_entry = build_entry_price("SHORT", 100.0, replay_config)
    assert long_entry == 100.5
    assert short_entry == 99.5
    long_stop = initial_stop("LONG", long_entry, [100.4], replay_config)
    short_stop = initial_stop("SHORT", short_entry, [99.6], replay_config)
    assert long_stop == 100.29
    assert short_stop == 99.7
    # Mirrors Executor's float risk calculation followed by directional Decimal rounding.
    assert compute_targets("LONG", long_entry, long_stop, replay_config) == (100.71, 100.91)
    assert compute_targets("SHORT", short_entry, short_stop, replay_config) == (99.3, 99.1)


def test_quantity_rounding_and_split_fallback(replay_config) -> None:
    qty = notional_to_qty(100.5, 3000.0, replay_config)
    assert qty == 29.85074
    q1, q2, q3 = split_quantity(qty, replay_config)
    assert round(q1 + q2 + q3, 5) == qty
    tiny = replay_config.__class__(**{**replay_config.to_dict(), "qty_step": 1.0})
    assert split_quantity(2.0, tiny) == (1.0, 1.0, 0.0)


def test_initial_stop_applies_structural_buffer_symmetrically(replay_config) -> None:
    config = replay_config.__class__(
        **{
            **replay_config.to_dict(),
            "initial_swing_price_source": "extreme",
            "initial_swing_buffer_usd": 0.5,
        }
    )
    assert initial_stop("LONG", 100.0, [99.0, 98.0], config) == 97.5
    assert initial_stop("SHORT", 100.0, [101.0, 102.0], config) == 102.5


def test_volume_swing_selects_highest_volume_inside_distance_cap(replay_config) -> None:
    config = replay_config.__class__(
        **{
            **replay_config.to_dict(),
            "initial_stop_policy": "volume_confirmed_swing",
            "initial_swing_lr": 1,
            "initial_swing_buffer_usd": 0.5,
            "initial_swing_max_distance_usd": 5.0,
        }
    )
    bars = [
        bar(-6, open_=100, high=101, low=99, close=100),
        bar(-5, open_=100, high=100, low=90, close=95, volume=500),  # too far
        bar(-4, open_=96, high=101, low=96, close=100),
        bar(-3, open_=100, high=101, low=99, close=100),
        bar(-2, open_=100, high=100, low=98, close=99, volume=200),  # selected
        bar(-1, open_=99, high=101, low=99, close=100),
        bar(0, open_=100, high=101, low=99.5, close=100),
    ]
    selected = select_volume_confirmed_initial_stop("LONG", 100.5, bars, config)
    assert selected.swing_price == 98
    assert selected.swing_volume == 200
    assert selected.stop == 97.5
    assert selected.confirmed_count == 2
    assert selected.eligible_count == 1


def test_volume_swing_rejects_when_every_confirmed_swing_exceeds_cap(replay_config) -> None:
    config = replay_config.__class__(
        **{
            **replay_config.to_dict(),
            "initial_stop_policy": "volume_confirmed_swing",
            "initial_swing_lr": 1,
            "initial_swing_buffer_usd": 0.5,
            "initial_swing_max_distance_usd": 5.0,
        }
    )
    bars = [
        bar(-2, open_=100, high=101, low=99, close=100),
        bar(-1, open_=95, high=96, low=90, close=95, volume=500),
        bar(0, open_=100, high=101, low=99, close=100),
    ]
    with pytest.raises(InitialStopSelectionError, match="NO_SWING_WITHIN_INITIAL_STOP_CAP"):
        select_volume_confirmed_initial_stop("LONG", 100.5, bars, config)


def test_volume_swing_short_uses_high_plus_buffer(replay_config) -> None:
    config = replay_config.__class__(
        **{
            **replay_config.to_dict(),
            "initial_stop_policy": "volume_confirmed_swing",
            "initial_swing_lr": 1,
            "initial_swing_buffer_usd": 0.5,
            "initial_swing_max_distance_usd": 5.0,
        }
    )
    bars = [
        bar(-6, open_=100, high=101, low=99, close=100),
        bar(-5, open_=105, high=110, low=104, close=105, volume=500),  # too far
        bar(-4, open_=100, high=101, low=99, close=100),
        bar(-3, open_=100, high=101, low=99, close=100),
        bar(-2, open_=101, high=102, low=100, close=101, volume=200),  # selected
        bar(-1, open_=100, high=101, low=99, close=100),
        bar(0, open_=100, high=101, low=99, close=100),
    ]
    selected = select_volume_confirmed_initial_stop("SHORT", 99.5, bars, config)
    assert selected.swing_price == 102
    assert selected.swing_volume == 200
    assert selected.stop == 102.5
