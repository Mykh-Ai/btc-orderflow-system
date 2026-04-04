from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_minute_events_mechanics import (
    build_minute_events_mechanics_dataset,
)
from deltascout.delta_analyzer.types import MinuteEventRow


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _minute(
    ts: str,
    *,
    open: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    vol_1m: float | None = None,
    delta_1m: float | None = None,
    vwap: float | None = None,
) -> MinuteEventRow:
    return MinuteEventRow(
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
    )


def test_m2a_delta_mechanics_compute_basic_fields_and_sort_rows():
    rows = build_minute_events_mechanics_dataset(
        [
            _minute("2026-01-01T00:02:00", delta_1m=-5.0, vol_1m=20.0),
            _minute("2026-01-01T00:01:00", delta_1m=10.0, vol_1m=40.0),
        ]
    )

    assert [row.ts for row in rows] == [_dt("2026-01-01T00:01:00"), _dt("2026-01-01T00:02:00")]
    assert rows[0].abs_delta_1m == 10.0
    assert rows[0].delta_sign == "positive"
    assert rows[0].delta_to_vol_ratio == 0.25
    assert rows[1].abs_delta_1m == 5.0
    assert rows[1].delta_sign == "negative"
    assert rows[1].delta_to_vol_ratio == 0.25


def test_m2a_percentile_fields_use_inclusive_current_row_and_min_history():
    start = _dt("2026-01-01T00:00:00")
    rows = []
    for idx in range(20):
        ts = (start + timedelta(minutes=idx)).isoformat()
        rows.append(_minute(ts, delta_1m=float(idx + 1), vol_1m=float((idx + 1) * 10)))

    mechanics = build_minute_events_mechanics_dataset(rows)

    assert mechanics[18].delta_pct_60m is None
    assert mechanics[18].vol_pct_60m is None
    assert mechanics[19].delta_pct_60m == 1.0
    assert mechanics[19].vol_pct_60m == 1.0
    assert mechanics[19].delta_pct_180m == 1.0
    assert mechanics[19].vol_pct_180m == 1.0


def test_m2a_percentile_fields_respect_time_windows():
    start = _dt("2026-01-01T00:00:00")
    rows = []
    for idx in range(19):
        ts = (start + timedelta(minutes=idx)).isoformat()
        rows.append(_minute(ts, delta_1m=1.0, vol_1m=10.0))
    rows.append(_minute("2026-01-01T02:00:00", delta_1m=2.0, vol_1m=20.0))

    mechanics = build_minute_events_mechanics_dataset(rows)
    last = mechanics[-1]

    assert last.delta_pct_60m is None
    assert last.vol_pct_60m is None
    assert last.delta_pct_180m == 1.0
    assert last.vol_pct_180m == 1.0


def test_m2a_percentiles_and_ratios_stay_null_when_inputs_unknown():
    rows = build_minute_events_mechanics_dataset(
        [
            _minute("2026-01-01T00:00:00", delta_1m=None, vol_1m=10.0),
            _minute("2026-01-01T00:01:00", delta_1m=5.0, vol_1m=0.0),
        ]
    )

    assert rows[0].abs_delta_1m is None
    assert rows[0].delta_sign == "flat_or_unknown"
    assert rows[0].delta_to_vol_ratio is None
    assert rows[0].delta_pct_60m is None
    assert rows[1].delta_to_vol_ratio is None


def test_m2a_price_response_fields_compute_correctly():
    row = build_minute_events_mechanics_dataset(
        [
            _minute(
                "2026-01-01T00:00:00",
                open=100.0,
                high=120.0,
                low=90.0,
                close=110.0,
                delta_1m=5.0,
                vol_1m=20.0,
            )
        ]
    )[0]

    assert row.close_minus_open == 10.0
    assert row.high_minus_low == 30.0
    assert row.body_to_range_ratio == 10.0 / 30.0
    assert row.close_location_in_range == 20.0 / 30.0
    assert row.price_move_sign == "up"
    assert row.delta_price_alignment_1m == "aligned"
    assert row.delta_price_efficiency_1m == 2.0


def test_m2a_delta_price_alignment_handles_opposed_and_flat_cases():
    rows = build_minute_events_mechanics_dataset(
        [
            _minute("2026-01-01T00:00:00", open=100.0, high=101.0, low=98.0, close=99.0, delta_1m=5.0),
            _minute("2026-01-01T00:01:00", open=100.0, high=101.0, low=99.0, close=100.0, delta_1m=5.0),
            _minute("2026-01-01T00:02:00", open=None, high=101.0, low=99.0, close=100.0, delta_1m=5.0),
        ]
    )

    assert rows[0].delta_price_alignment_1m == "opposed"
    assert rows[1].delta_price_alignment_1m == "flat_or_unknown"
    assert rows[2].delta_price_alignment_1m == "flat_or_unknown"


def test_m2a_zero_range_keeps_ratio_fields_null():
    row = build_minute_events_mechanics_dataset(
        [
            _minute("2026-01-01T00:00:00", open=100.0, high=100.0, low=100.0, close=100.0, delta_1m=3.0)
        ]
    )[0]

    assert row.high_minus_low == 0.0
    assert row.body_to_range_ratio is None
    assert row.close_location_in_range is None


def test_m2a_vwap_fields_compute_correctly():
    row = build_minute_events_mechanics_dataset(
        [
            _minute(
                "2026-01-01T00:00:00",
                open=100.0,
                high=111.0,
                low=95.0,
                close=108.0,
                vwap=103.0,
            )
        ]
    )[0]

    assert row.dist_from_vwap == 5.0
    assert row.abs_dist_from_vwap == 5.0
    assert row.price_vs_vwap_side == "above"
    assert row.high_above_vwap_flag is True
    assert row.low_below_vwap_flag is True


def test_m2a_vwap_fields_handle_unknowns_and_below_side():
    rows = build_minute_events_mechanics_dataset(
        [
            _minute("2026-01-01T00:00:00", close=98.0, high=99.0, low=97.0, vwap=100.0),
            _minute("2026-01-01T00:01:00", close=None, high=None, low=None, vwap=100.0),
        ]
    )

    assert rows[0].price_vs_vwap_side == "below"
    assert rows[0].high_above_vwap_flag is False
    assert rows[0].low_below_vwap_flag is True
    assert rows[1].dist_from_vwap is None
    assert rows[1].abs_dist_from_vwap is None
    assert rows[1].price_vs_vwap_side == "at_or_unknown"
    assert rows[1].high_above_vwap_flag is None
    assert rows[1].low_below_vwap_flag is None
