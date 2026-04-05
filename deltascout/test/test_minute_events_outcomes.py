from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_minute_events_outcomes import (
    build_minute_events_outcomes_dataset,
)
from deltascout.delta_analyzer.types import MinuteEventMechanicsRow


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _minute(
    ts: str,
    *,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    delta_sign: str = "flat_or_unknown",
    price_move_sign: str = "flat_or_unknown",
    price_vs_vwap_side: str = "at_or_unknown",
    delta_1m: float | None = None,
    vol_1m: float | None = None,
    vwap: float | None = None,
) -> MinuteEventMechanicsRow:
    return MinuteEventMechanicsRow(
        ts=_dt(ts),
        day=_dt(ts).strftime("%Y-%m-%d"),
        open=open,
        high=high,
        low=low,
        close=close,
        buy_qty=None,
        sell_qty=None,
        vol_1m=vol_1m,
        delta_1m=delta_1m,
        imbalance_1m=None,
        vwap=vwap,
        open_interest=None,
        funding_rate=None,
        liq_buy_qty=None,
        liq_sell_qty=None,
        is_synthetic=None,
        source_file="synthetic.csv",
        abs_delta_1m=abs(delta_1m) if delta_1m is not None else None,
        delta_sign=delta_sign,
        delta_to_vol_ratio=None,
        delta_pct_60m=None,
        delta_pct_180m=None,
        vol_pct_60m=None,
        vol_pct_180m=None,
        close_minus_open=None if close is None or open is None else close - open,
        high_minus_low=None if high is None or low is None else high - low,
        body_to_range_ratio=None,
        close_location_in_range=None,
        price_move_sign=price_move_sign,
        delta_price_alignment_1m="flat_or_unknown",
        delta_price_efficiency_1m=None,
        dist_from_vwap=None if close is None or vwap is None else close - vwap,
        abs_dist_from_vwap=None if close is None or vwap is None else abs(close - vwap),
        price_vs_vwap_side=price_vs_vwap_side,
        high_above_vwap_flag=None,
        low_below_vwap_flag=None,
        oi_change_1m=None,
        abs_oi_change_1m=None,
        oi_change_pct_60m=None,
        oi_change_pct_180m=None,
        delta_oi_alignment_flag="flat_or_unknown",
        price_oi_alignment_flag="flat_or_unknown",
        liq_total_1m=None,
        liq_imbalance_1m=None,
        liq_dominant_side="balanced_or_unknown",
        liq_burst_flag=None,
        delta_vs_liq_relation_flag="flat_or_unknown",
    )


def test_m2_5_rows_remain_timestamp_sorted_and_reference_direction_uses_price_then_delta():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:02:00", close=101.0, price_move_sign="flat_or_unknown", delta_sign="negative"),
            _minute("2026-01-01T00:01:00", close=100.0, price_move_sign="up", delta_sign="negative"),
            _minute("2026-01-01T00:03:00", close=102.0, price_move_sign="flat_or_unknown", delta_sign="flat_or_unknown"),
        ]
    )

    assert [row.ts for row in rows] == [_dt("2026-01-01T00:01:00"), _dt("2026-01-01T00:02:00"), _dt("2026-01-01T00:03:00")]
    assert rows[0].reference_direction == "up"
    assert rows[1].reference_direction == "down"
    assert rows[2].reference_direction == "unknown"


def test_m2_5_forward_returns_use_latest_valid_future_close_within_horizon():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0),
            _minute("2026-01-01T00:03:00", close=101.0),
            _minute("2026-01-01T00:05:00", close=102.0),
            _minute("2026-01-01T00:16:00", close=105.0),
            _minute("2026-01-01T00:30:00", close=106.0),
            _minute("2026-01-01T01:00:00", close=110.0),
        ]
    )

    row = rows[0]
    assert row.ret_fwd_5m == 2.0
    assert row.ret_fwd_15m == 2.0
    assert row.ret_fwd_30m == 6.0
    assert row.ret_fwd_60m == 10.0


def test_m2_5_horizon_selection_excludes_current_row_and_outside_boundary():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0),
            _minute("2026-01-01T00:05:00", close=101.0),
            _minute("2026-01-01T00:05:01", close=120.0),
        ]
    )

    row = rows[0]
    assert row.ret_fwd_5m == 1.0


def test_m2_5_symmetric_path_extremes_use_high_low_with_close_fallback():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0),
            _minute("2026-01-01T00:02:00", high=104.0, low=99.0, close=101.0),
            _minute("2026-01-01T00:04:00", high=None, low=None, close=97.0),
        ]
    )

    row = rows[0]
    assert row.upside_max_5m == 4.0
    assert row.downside_max_5m == 3.0


def test_m2_5_threshold_hits_times_and_ordering_are_deterministic():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0, price_move_sign="up", delta_sign="positive"),
            _minute("2026-01-01T00:02:00", high=100.2, low=99.95, close=100.1),
            _minute("2026-01-01T00:04:00", high=100.3, low=99.7, close=100.0),
        ]
    )

    row = rows[0]
    assert row.up_hit_10bp_5m_flag is True
    assert row.down_hit_10bp_5m_flag is True
    assert row.up_time_to_hit_10bp_5m_min == 2.0
    assert row.down_time_to_hit_10bp_5m_min == 4.0
    assert row.both_hit_10bp_5m_flag is True
    assert row.up_before_down_10bp_5m_flag is True
    assert row.down_before_up_10bp_5m_flag is False


def test_m2_5_threshold_not_reached_returns_false_and_null_time():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0),
            _minute("2026-01-01T00:02:00", high=100.05, low=99.95, close=100.01),
        ]
    )

    row = rows[0]
    assert row.up_hit_10bp_5m_flag is False
    assert row.down_hit_10bp_5m_flag is False
    assert row.up_time_to_hit_10bp_5m_min is None
    assert row.down_time_to_hit_10bp_5m_min is None
    assert row.both_hit_10bp_5m_flag is False
    assert row.up_before_down_10bp_5m_flag is False
    assert row.down_before_up_10bp_5m_flag is False


def test_m2_5_null_handling_is_strict_for_unknown_anchor_and_missing_future_rows():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=None),
            _minute("2026-01-01T00:01:00", close=101.0),
            _minute("2026-01-01T01:10:00", close=102.0),
        ]
    )

    first = rows[0]
    second = rows[1]
    assert first.ret_fwd_5m is None
    assert first.upside_max_5m is None
    assert first.up_hit_10bp_5m_flag is None
    assert first.both_hit_10bp_5m_flag is None
    assert second.ret_fwd_5m is None
    assert second.upside_max_5m is None
    assert second.up_hit_10bp_5m_flag is None
    assert second.both_hit_10bp_5m_flag is None


def test_m2_5_favorable_and_adverse_fields_map_from_reference_direction():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0, price_move_sign="up", delta_sign="positive"),
            _minute("2026-01-01T00:01:00", close=101.0, price_move_sign="down", delta_sign="negative"),
            _minute("2026-01-01T00:02:00", high=103.0, low=99.0, close=101.0),
            _minute("2026-01-01T00:03:00", high=102.0, low=98.0, close=100.0),
        ]
    )

    up_row = rows[0]
    down_row = rows[1]
    assert up_row.favorable_max_5m == up_row.upside_max_5m
    assert up_row.adverse_max_5m == up_row.downside_max_5m
    assert down_row.favorable_max_5m == down_row.downside_max_5m
    assert down_row.adverse_max_5m == down_row.upside_max_5m


def test_m2_5_unknown_reference_direction_keeps_favorable_and_adverse_null():
    rows = build_minute_events_outcomes_dataset(
        [
            _minute("2026-01-01T00:00:00", close=100.0, price_move_sign="flat_or_unknown", delta_sign="flat_or_unknown"),
            _minute("2026-01-01T00:02:00", high=102.0, low=98.0, close=101.0),
        ]
    )

    row = rows[0]
    assert row.reference_direction == "unknown"
    assert row.favorable_max_5m is None
    assert row.adverse_max_5m is None
