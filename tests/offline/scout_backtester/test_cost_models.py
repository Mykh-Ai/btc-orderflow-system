from __future__ import annotations

from datetime import datetime, timezone

from deltascout.research_bundle.scout_backtester.contracts import TradeLeg
from deltascout.research_bundle.scout_backtester.cost_models import calculate_costs, gross_for_leg


def test_long_short_gross_and_declared_costs() -> None:
    assert gross_for_leg("LONG", 1.0, 100.0, 110.0) == 10.0
    assert gross_for_leg("SHORT", 1.0, 100.0, 90.0) == 10.0
    leg = TradeLeg("T", "L1", "TP1", 1.0, 100.0, 110.0, datetime(2026, 1, 1, tzinfo=timezone.utc), 10.0, 210.0)
    turnover, commission, slippage = calculate_costs(
        qty_total=1.0,
        entry_price=100.0,
        legs=[leg],
        commission_rate=0.001,
        entry_slippage_bps=1.0,
        exit_slippage_bps=2.0,
        stop_slippage_bps=3.0,
    )
    assert turnover == 210.0
    assert commission == 0.21
    assert round(slippage, 8) == 0.032
