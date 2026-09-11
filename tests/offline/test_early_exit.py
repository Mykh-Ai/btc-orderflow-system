from dataclasses import replace
from datetime import timedelta

import pytest

from deltascout.research_bundle.build_early_exit import EARLY, ExitRule, apply_early_exit, compare
from deltascout.research_bundle.build_trade_development import FeedIndex
from deltascout.research_bundle.scout_backtester.contracts import ReplayConfig, ReplayEvent, TradeResult
from deltascout.research_bundle.scout_backtester.portfolio import replay_portfolio
from deltascout.research_bundle.scout_backtester.replay_engine import _add_leg, _finalize_economics
from tests.offline.scout_backtester.conftest import BASE_TS, bar, candidate


def sample(side="LONG"):
    sign = 1 if side == "LONG" else -1
    config = ReplayConfig(experiment_id="early-test", commission_rate=.001,
                          entry_slippage_bps=0, exit_slippage_bps=1, stop_slippage_bps=2)
    base = TradeResult(trade_id="t", candidate_id="C1", experiment_id=config.experiment_id,
                       replay_mode="independent_opportunity", candidate_group="PEAK_EMIT_BASELINE",
                       side=side, signal_ts_utc=BASE_TS-timedelta(minutes=1), entry_status="FILLED",
                       entry_fill_ts=BASE_TS, entry_fill_price=100, initial_stop_price=100-sign*10,
                       tp1_price=100+sign*10, tp2_price=100+sign*20, initial_risk_usd=10,
                       qty_total=3, qty1=1, qty2=1, qty3=1, lifecycle_class="PLAIN_SL",
                       exit_ts=BASE_TS+timedelta(minutes=120), same_bar_ambiguous=True,
                       same_bar_collision_count=1, final_stop_price=100-sign*10)
    _add_leg(base, "INITIAL_STOP", 3, base.initial_stop_price, base.exit_ts)
    _finalize_economics(base, config)
    bars = [bar(i, open_=100, high=101, low=99, close=100) for i in range(122)]
    bars[30] = replace(bars[30], high=105 if sign == 1 else 101, low=95 if sign == -1 else 99)
    bars[60] = replace(bars[60], close=100-sign)
    bars[61] = replace(bars[61], open=100-sign*2, low=97, high=103)
    refs = [replace(b, buy_qty=.2 if sign == 1 else .8, sell_qty=.8 if sign == 1 else .2) for b in bars]
    events = [ReplayEvent(BASE_TS, "ENTRY_FILLED", "t", "C1", "independent_opportunity"),
              ReplayEvent(base.exit_ts, "STOP_FILLED", "t", "C1", "independent_opportunity")]
    return base, events, FeedIndex(bars), FeedIndex(refs), config


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_causal_exit_uses_next_open_and_normal_costs_symmetrically(side):
    base, events, execution, reference, config = sample(side)
    result, changed, audit = apply_early_exit(base, events, execution, reference, config, ExitRule())
    sign = 1 if side == "LONG" else -1
    price = 100-sign*2
    assert audit["fired"] and audit["decision"]["age_min"] == 60
    assert audit["decision"]["mfe_r"] == pytest.approx(.5)
    assert audit["decision"]["directional_delta_pct"] == pytest.approx(-.6)
    assert result.lifecycle_class == EARLY
    assert result.exit_ts == BASE_TS+timedelta(minutes=61)
    assert result.legs[0].exit_price == price
    assert result.net_pnl_usdc == pytest.approx(-6-(300+3*price)*.001-3*price*.0001)
    assert not result.same_bar_ambiguous and result.same_bar_collision_count == 0
    assert [e.event_type for e in changed] == ["ENTRY_FILLED", "EARLY_EXIT_DECIDED", "EARLY_EXIT_FILLED", "POSITION_CLOSED"]
    assert base.lifecycle_class == "PLAIN_SL" and len(base.legs) == 1  # no mutation


def test_future_labels_wicks_and_order_events_do_not_leak_into_decision():
    base, events, execution, reference, config = sample()
    expected, _, first = apply_early_exit(base, events, execution, reference, config, ExitRule())
    changed_base = replace(base, lifecycle_class="TP1_TP2_TRAILING_STOP", net_pnl_usdc=9999,
                           tp1_fill_ts=BASE_TS+timedelta(minutes=100),
                           tp2_fill_ts=BASE_TS+timedelta(minutes=110), trail_update_count=400)
    # The later stop/TP on the execution bar occurs after the open exit.
    changed_bars = [replace(b, high=1000, low=1, close=200) if b.ts > BASE_TS+timedelta(minutes=60) else b for b in execution.bars]
    changed_refs = [replace(b, buy_qty=100, sell_qty=0) if b.ts > BASE_TS+timedelta(minutes=60) else b for b in reference.bars]
    actual, _, audit = apply_early_exit(changed_base, events, FeedIndex(changed_bars), FeedIndex(changed_refs), config, ExitRule())
    assert audit["decision"] == first["decision"]
    assert actual.net_pnl_usdc == expected.net_pnl_usdc
    assert actual.tp1_fill_ts is None and actual.tp2_fill_ts is None and actual.trail_update_count == 0


@pytest.mark.parametrize("boundary", ["tp1_fill_ts", "exit_ts", "data_quality_interruption_ts"])
def test_decision_cannot_follow_tp1_exit_or_interruption_on_same_minute(boundary):
    base, events, execution, reference, config = sample()
    base = replace(base, **{boundary: BASE_TS+timedelta(minutes=60)})
    result, _, audit = apply_early_exit(base, events, execution, reference, config, ExitRule())
    assert not audit["fired"] and result is base


def test_entry_bar_wicks_cannot_arm_the_rule():
    base, events, execution, reference, config = sample()
    bars = [replace(b, high=101) for b in execution.bars]
    bars[0] = replace(bars[0], high=109)  # may have occurred before entry
    result, _, audit = apply_early_exit(base, events, FeedIndex(bars), reference, config, ExitRule())
    assert not audit["fired"] and result is base


@pytest.mark.parametrize("kind", ["neutral", "zero_volume", "synthetic", "missing"])
def test_unavailable_or_neutral_flow_does_not_trigger(kind):
    base, events, execution, reference, config = sample()
    refs = reference.bars
    if kind == "neutral":
        refs = [replace(b, buy_qty=.5, sell_qty=.5) for b in refs]
    elif kind == "zero_volume":
        refs = [replace(b, buy_qty=0, sell_qty=0) for b in refs]
    elif kind == "synthetic":
        refs = [replace(b, is_synthetic=True) for b in refs]
    else:
        refs = [b for i,b in enumerate(refs) if i % 5]
    result, _, audit = apply_early_exit(base, events, execution, FeedIndex(refs), config, ExitRule())
    assert not audit["fired"] and result is base


def test_missing_execution_breaks_scan_without_forward_filling():
    base, events, execution, reference, config = sample()
    bars = [b for i,b in enumerate(execution.bars) if i != 59]
    result, _, audit = apply_early_exit(base, events, FeedIndex(bars), reference, config, ExitRule())
    assert audit["execution_gap"] and not audit["fired"] and result is base


@pytest.mark.parametrize("open_price,boundary", [(89, "exit_ts"), (111, "tp1_fill_ts")])
def test_standing_bracket_at_next_open_takes_priority(open_price, boundary):
    base, events, execution, reference, config = sample()
    base = replace(base, **{boundary: BASE_TS+timedelta(minutes=61)})
    bars = [replace(b, open=open_price) if i == 61 else b for i,b in enumerate(execution.bars)]
    result, _, audit = apply_early_exit(base, events, FeedIndex(bars), reference, config, ExitRule())
    assert not audit["fired"] and result is base
    assert audit["standing_bracket_open_collisions"] == 1


def test_resequencing_releases_slot_after_cooldown_and_changes_pnl():
    base, events, execution, reference, config = sample()
    changed, changed_events, _ = apply_early_exit(base, events, execution, reference, config, ExitRule())
    c1, c2 = candidate(offset_minutes=-1), candidate(candidate_id="C2", offset_minutes=65)
    second = replace(base, trade_id="t2", candidate_id="C2", signal_ts_utc=c2.signal_ts_utc,
                     entry_fill_ts=c2.signal_ts_utc+timedelta(minutes=1),
                     exit_ts=c2.signal_ts_utc+timedelta(minutes=10), legs=list(base.legs))
    before, _, _ = replay_portfolio([c1, c2], [base, second], config)
    after, _, _ = replay_portfolio([c1, c2], [changed, second], config, changed_events)
    assert before[1].entry_status == "BLOCKED" and after[1].entry_status == "FILLED"
    summary, rows = compare(before, after)
    assert summary["added_count"] == 1 and summary["removed_count"] == 0
    assert summary["net_change_usdc"] == pytest.approx(summary["common_trade_change_usdc"] + summary["admission_change_usdc"])
    assert rows[1]["membership_change"] == "ADDED"


def test_no_exit_without_minimum_age_or_impulse():
    base, events, execution, reference, config = sample()
    for rule in (ExitRule(minimum_age_min=121), ExitRule(minimum_mfe_r=.6)):
        result, same_events, audit = apply_early_exit(base, events, execution, reference, config, rule)
        assert result is base and same_events is events and not audit["fired"]
