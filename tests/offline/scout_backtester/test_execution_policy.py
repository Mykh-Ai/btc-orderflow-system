from __future__ import annotations

from deltascout.research_bundle.scout_backtester.execution_policy import (
    build_entry_price,
    compute_targets,
    initial_stop,
    notional_to_qty,
    split_quantity,
)


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
