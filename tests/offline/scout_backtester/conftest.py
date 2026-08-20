from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from deltascout.research_bundle.scout_backtester.contracts import Candidate, FeedBar, ReplayConfig


BASE_TS = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def candidate(side: str = "LONG", *, candidate_id: str = "C1", offset_minutes: int = 0) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        source_event_ts_local="2026-01-02 13:00:00",
        signal_ts_utc=BASE_TS + timedelta(minutes=offset_minutes),
        side=side,
        event_type="PEAK_EMIT",
        candidate_group="PEAK_EMIT_BASELINE",
        reject_reason=None,
        signal_price=100.0,
        delta=10.0 if side == "LONG" else -10.0,
        volume=20.0,
        imbalance=0.5,
        vwap=100.0,
        poc=100.0,
        comparison_3of3_pass_count=None,
        comparison_3of3_failed_subconditions=None,
        shadow_flags={
            "weak_peak_le_50": None,
            "oi_down_60_and_directional_delta_pct_240_lt_0_06": None,
            "loss_avoidance_conservative_union": None,
        },
        source_path="synthetic.csv",
        source_row_hash="hash",
    )


def bar(
    minute: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    synthetic: bool = False,
) -> FeedBar:
    return FeedBar(
        ts=BASE_TS + timedelta(minutes=minute),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        buy_qty=0.5,
        sell_qty=0.5,
        is_synthetic=synthetic,
        feed_quality_class="SYNTHETIC_UNTRUSTED" if synthetic else "REAL_ENRICHED",
        recovery_overlap=False,
        source_path="synthetic.csv",
        row_number=minute + 2,
    )


@pytest.fixture
def replay_config() -> ReplayConfig:
    return ReplayConfig(
        experiment_id="synthetic",
        fixed_notional_usdc=3000.0,
        tick_size=0.01,
        qty_step=0.00001,
        sl_pct=0.002,
        swing_lookback_minutes=10,
        trail_swing_lookback=20,
        trail_swing_lr=1,
        trail_swing_buffer_usd=0.05,
        trail_step_usd=0.01,
        commission_rate=0.0,
        exit_slippage_bps=0.0,
        stop_slippage_bps=0.0,
    )
