from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from deltascout.research_bundle.build_trade_development import FeedIndex, checkpoint
from tests.offline.scout_backtester.conftest import BASE_TS, bar


COSTS = dict(commission_rate=.001, entry_slippage_bps=0., exit_slippage_bps=1., stop_slippage_bps=2.)


def sample(side="LONG", *, exit_min=3):
    sign = 1 if side == "LONG" else -1
    entry = 100.
    trade = dict(candidate_id="c", trade_id="t", side=side, entry_fill_ts=BASE_TS.isoformat(),
        exit_ts=(BASE_TS + timedelta(minutes=exit_min)).isoformat(), entry_fill_price=entry,
        initial_stop_price=entry-sign*10, qty_total=3., initial_swing_price_usdt=entry-sign*8,
        tp1_fill_ts=(BASE_TS+timedelta(minutes=2)).isoformat(), tp2_fill_ts="", lifecycle_class="TP1_SL")
    legs = [dict(leg_type="TP1", qty=1., exit_price=entry+sign*10, gross_pnl_usdc=10.,
                 exit_ts=(BASE_TS+timedelta(minutes=2)).isoformat()),
            dict(leg_type="BREAKEVEN_STOP", qty=2., exit_price=100., gross_pnl_usdc=0.,
                 exit_ts=trade["exit_ts"])]
    trade["net_pnl_usdc"] = 10 - (300+(100+sign*10)+200)*.001 - ((100+sign*10)*.0001+200*.0002)
    return trade, legs


def feed(n=1440):
    return FeedIndex([bar(i, open_=100, high=102, low=98, close=101) for i in range(n+1)])


def test_partial_exit_accounting_and_no_future_outcome_leakage():
    trade, legs = sample()
    f = feed(10)
    before = checkpoint(trade, legs, f, f, 1, COSTS)
    after_tp = checkpoint(trade, legs, f, f, 2, COSTS)
    assert before["remaining_qty"] == 3
    assert before["position_gross_realized_usdc"] == 0
    assert before["position_gross_unrealized_usdc"] == 3
    assert before["position_net_if_closed_now_usdc"] == pytest.approx(3-.3-303*.0011)
    assert after_tp["state_at_checkpoint"] == "TP1_DONE"
    assert after_tp["remaining_qty"] == 2
    assert after_tp["position_net_if_closed_now_usdc"] == pytest.approx(12-.410-.011-202*.0011)
    changed = {**trade, "lifecycle_class":"FUTURE_CHANGED", "net_pnl_usdc":999}
    changed_legs = [legs[0], {**legs[1], "exit_price":999, "gross_pnl_usdc":999}]
    future_changed = checkpoint(changed, changed_legs, f, f, 1, COSTS)
    assert {k:v for k,v in before.items() if not k.startswith("label_")} == {
        k:v for k,v in future_changed.items() if not k.startswith("label_")}


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_closed_pnl_freezes_while_market_path_continues(side):
    trade, legs = sample(side)
    f = feed()
    r = [checkpoint(trade, legs, f, f, h, COSTS) for h in [5, 240, 1440]]
    assert all(row["state_at_checkpoint"] == "CLOSED" for row in r)
    assert all(row["remaining_qty"] == 0 for row in r)
    assert all(row["position_net_if_closed_now_usdc"] == pytest.approx(trade["net_pnl_usdc"]) for row in r)
    assert r[-1]["market_complete"] is True
    assert r[-1]["market_minutes_observed"] == 1440


def test_exit_bar_and_post_exit_wicks_do_not_inflate_position_mfe():
    trade, legs = sample()
    f = feed(10)
    bars = [replace(b, high=200, low=1) if b.ts >= BASE_TS+timedelta(minutes=3) else b for b in f.bars]
    r = checkpoint(trade, legs, FeedIndex(bars), f, 5, COSTS)
    assert r["market_mfe_r"] == 10
    assert r["market_mae_r"] == 9.9
    assert r["position_mfe_lower_bound_r"] == 1
    assert r["position_mae_lower_bound_r"] == .2


def test_missing_minute_and_missing_endpoint_are_not_filled_with_future_or_zero():
    trade, legs = sample(exit_min=20)
    f = feed(10)
    missing = FeedIndex([b for i,b in enumerate(f.bars) if i != 4])
    r = checkpoint(trade, legs, missing, missing, 5, COSTS)
    assert r["market_complete"] is False and r["market_mfe_r"] is None
    assert r["directional_delta_qty"] is None
    assert r["market_price_r"] == .1  # exact endpoint still exists
    endpoint_missing = FeedIndex([b for i,b in enumerate(f.bars) if i != 5])
    r = checkpoint(trade, legs, endpoint_missing, endpoint_missing, 5, COSTS)
    assert r["market_close_usdc"] is None and r["position_net_if_closed_now_r"] is None


def test_synthetic_reference_is_unavailable_and_zero_delta_is_neutral():
    trade, legs = sample()
    f = feed(10)
    r = checkpoint(trade, legs, f, f, 5, COSTS)
    assert r["directional_delta_pct"] == 0
    assert r["flow_price_response"] == "NEUTRAL_NO_PROGRESS"
    synthetic = FeedIndex([replace(b, is_synthetic=True) if i==2 else b for i,b in enumerate(f.bars)])
    r = checkpoint(trade, legs, f, synthetic, 5, COSTS)
    assert r["reference_complete"] is False
    assert r["flow_price_response"] == "UNAVAILABLE"
    assert r["structure_adverse_at_checkpoint"] is None


@pytest.mark.parametrize("side,close", [("LONG",91), ("SHORT",109)])
def test_directional_structure_breach_uses_frozen_usdt_swing(side, close):
    trade, legs = sample(side)
    f = feed(10)
    refs = FeedIndex([replace(b, close=close) if i==4 else b for i,b in enumerate(f.bars)])
    r = checkpoint(trade, legs, f, refs, 5, COSTS)
    assert r["structure_breached_by_checkpoint"] is True
    assert r["structure_first_adverse_min"] == 4
    assert r["structure_adverse_at_checkpoint"] is False
