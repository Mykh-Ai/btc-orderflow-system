from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedEvent:
    ts: datetime
    event_type: str
    kind: str | None
    reject_reason: str | None
    delta: float | None
    vol: float | None
    imb: float | None
    price: float | None
    vwap: float | None
    poc: float | None
    source_file: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class FeedRow:
    ts: datetime
    price: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    buy_qty: float | None
    sell_qty: float | None
    vol_1m: float | None
    vwap: float | None
    open_interest: float | None
    funding_rate: float | None
    liq_buy_qty: float | None
    liq_sell_qty: float | None
    is_synthetic: bool | None
    row: dict[str, Any]
    source_file: str


@dataclass(frozen=True)
class MinuteEventRow:
    ts: datetime
    day: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    buy_qty: float | None
    sell_qty: float | None
    vol_1m: float | None
    delta_1m: float | None
    imbalance_1m: float | None
    vwap: float | None
    open_interest: float | None
    funding_rate: float | None
    liq_buy_qty: float | None
    liq_sell_qty: float | None
    is_synthetic: bool | None
    source_file: str


@dataclass(frozen=True)
class MinuteEventMechanicsRow:
    ts: datetime
    day: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    buy_qty: float | None
    sell_qty: float | None
    vol_1m: float | None
    delta_1m: float | None
    imbalance_1m: float | None
    vwap: float | None
    open_interest: float | None
    funding_rate: float | None
    liq_buy_qty: float | None
    liq_sell_qty: float | None
    is_synthetic: bool | None
    source_file: str
    abs_delta_1m: float | None
    delta_sign: str
    delta_to_vol_ratio: float | None
    delta_pct_60m: float | None
    delta_pct_180m: float | None
    vol_pct_60m: float | None
    vol_pct_180m: float | None
    close_minus_open: float | None
    high_minus_low: float | None
    body_to_range_ratio: float | None
    close_location_in_range: float | None
    price_move_sign: str
    delta_price_alignment_1m: str
    delta_price_efficiency_1m: float | None
    dist_from_vwap: float | None
    abs_dist_from_vwap: float | None
    price_vs_vwap_side: str
    high_above_vwap_flag: bool | None
    low_below_vwap_flag: bool | None
    oi_change_1m: float | None
    abs_oi_change_1m: float | None
    oi_change_pct_60m: float | None
    oi_change_pct_180m: float | None
    delta_oi_alignment_flag: str
    price_oi_alignment_flag: str
    liq_total_1m: float | None
    liq_imbalance_1m: float | None
    liq_dominant_side: str
    liq_burst_flag: bool | None
    delta_vs_liq_relation_flag: str


@dataclass(frozen=True)
class MinuteEventOutcomesRow:
    ts: datetime
    day: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    delta_1m: float | None
    vol_1m: float | None
    vwap: float | None
    source_file: str
    delta_sign: str
    price_move_sign: str
    price_vs_vwap_side: str
    reference_direction: str
    ret_fwd_5m: float | None
    ret_fwd_15m: float | None
    ret_fwd_30m: float | None
    ret_fwd_60m: float | None
    upside_max_5m: float | None
    downside_max_5m: float | None
    upside_max_15m: float | None
    downside_max_15m: float | None
    upside_max_30m: float | None
    downside_max_30m: float | None
    upside_max_60m: float | None
    downside_max_60m: float | None
    favorable_max_5m: float | None
    adverse_max_5m: float | None
    favorable_max_15m: float | None
    adverse_max_15m: float | None
    favorable_max_30m: float | None
    adverse_max_30m: float | None
    favorable_max_60m: float | None
    adverse_max_60m: float | None
    up_hit_10bp_5m_flag: bool | None
    down_hit_10bp_5m_flag: bool | None
    up_time_to_hit_10bp_5m_min: float | None
    down_time_to_hit_10bp_5m_min: float | None
    up_before_down_10bp_5m_flag: bool | None
    down_before_up_10bp_5m_flag: bool | None
    both_hit_10bp_5m_flag: bool | None
    up_hit_10bp_15m_flag: bool | None
    down_hit_10bp_15m_flag: bool | None
    up_time_to_hit_10bp_15m_min: float | None
    down_time_to_hit_10bp_15m_min: float | None
    up_before_down_10bp_15m_flag: bool | None
    down_before_up_10bp_15m_flag: bool | None
    both_hit_10bp_15m_flag: bool | None
    up_hit_10bp_30m_flag: bool | None
    down_hit_10bp_30m_flag: bool | None
    up_time_to_hit_10bp_30m_min: float | None
    down_time_to_hit_10bp_30m_min: float | None
    up_before_down_10bp_30m_flag: bool | None
    down_before_up_10bp_30m_flag: bool | None
    both_hit_10bp_30m_flag: bool | None
    up_hit_10bp_60m_flag: bool | None
    down_hit_10bp_60m_flag: bool | None
    up_time_to_hit_10bp_60m_min: float | None
    down_time_to_hit_10bp_60m_min: float | None
    up_before_down_10bp_60m_flag: bool | None
    down_before_up_10bp_60m_flag: bool | None
    both_hit_10bp_60m_flag: bool | None
    up_hit_25bp_5m_flag: bool | None
    down_hit_25bp_5m_flag: bool | None
    up_time_to_hit_25bp_5m_min: float | None
    down_time_to_hit_25bp_5m_min: float | None
    up_before_down_25bp_5m_flag: bool | None
    down_before_up_25bp_5m_flag: bool | None
    both_hit_25bp_5m_flag: bool | None
    up_hit_25bp_15m_flag: bool | None
    down_hit_25bp_15m_flag: bool | None
    up_time_to_hit_25bp_15m_min: float | None
    down_time_to_hit_25bp_15m_min: float | None
    up_before_down_25bp_15m_flag: bool | None
    down_before_up_25bp_15m_flag: bool | None
    both_hit_25bp_15m_flag: bool | None
    up_hit_25bp_30m_flag: bool | None
    down_hit_25bp_30m_flag: bool | None
    up_time_to_hit_25bp_30m_min: float | None
    down_time_to_hit_25bp_30m_min: float | None
    up_before_down_25bp_30m_flag: bool | None
    down_before_up_25bp_30m_flag: bool | None
    both_hit_25bp_30m_flag: bool | None
    up_hit_25bp_60m_flag: bool | None
    down_hit_25bp_60m_flag: bool | None
    up_time_to_hit_25bp_60m_min: float | None
    down_time_to_hit_25bp_60m_min: float | None
    up_before_down_25bp_60m_flag: bool | None
    down_before_up_25bp_60m_flag: bool | None
    both_hit_25bp_60m_flag: bool | None
    up_hit_50bp_5m_flag: bool | None
    down_hit_50bp_5m_flag: bool | None
    up_time_to_hit_50bp_5m_min: float | None
    down_time_to_hit_50bp_5m_min: float | None
    up_before_down_50bp_5m_flag: bool | None
    down_before_up_50bp_5m_flag: bool | None
    both_hit_50bp_5m_flag: bool | None
    up_hit_50bp_15m_flag: bool | None
    down_hit_50bp_15m_flag: bool | None
    up_time_to_hit_50bp_15m_min: float | None
    down_time_to_hit_50bp_15m_min: float | None
    up_before_down_50bp_15m_flag: bool | None
    down_before_up_50bp_15m_flag: bool | None
    both_hit_50bp_15m_flag: bool | None
    up_hit_50bp_30m_flag: bool | None
    down_hit_50bp_30m_flag: bool | None
    up_time_to_hit_50bp_30m_min: float | None
    down_time_to_hit_50bp_30m_min: float | None
    up_before_down_50bp_30m_flag: bool | None
    down_before_up_50bp_30m_flag: bool | None
    both_hit_50bp_30m_flag: bool | None
    up_hit_50bp_60m_flag: bool | None
    down_hit_50bp_60m_flag: bool | None
    up_time_to_hit_50bp_60m_min: float | None
    down_time_to_hit_50bp_60m_min: float | None
    up_before_down_50bp_60m_flag: bool | None
    down_before_up_50bp_60m_flag: bool | None
    both_hit_50bp_60m_flag: bool | None


@dataclass(frozen=True)
class EventsBaseRow:
    ts: datetime
    event_type: str
    kind: str | None
    reject_reason: str | None
    delta: float | None
    vol: float | None
    imb: float | None
    price: float | None
    vwap: float | None
    poc: float | None
    matched_feed_ts: datetime | None
    matched_open_interest: float | None
    matched_funding_rate: float | None
    matched_liq_buy_qty: float | None
    matched_liq_sell_qty: float | None
    source_file: str
    terminal_decision_present: bool
    prev_price: float | None
    prev_vol: float | None
    prev_vwap: float | None
    comparison_price_pass: bool | None
    comparison_vol_pass: bool | None
    comparison_vwap_pass: bool | None
    comparison_3of3_pass_count: int | None
    comparison_3of3_failed_subconditions: str


@dataclass(frozen=True)
class EventsContextRow:
    ts: datetime
    event_type: str
    kind: str | None
    reject_reason: str | None
    delta: float | None
    vol: float | None
    imb: float | None
    price: float | None
    vwap: float | None
    poc: float | None
    matched_feed_ts: datetime | None
    matched_open_interest: float | None
    matched_funding_rate: float | None
    matched_liq_buy_qty: float | None
    matched_liq_sell_qty: float | None
    source_file: str
    terminal_decision_present: bool
    prev_price: float | None
    prev_vol: float | None
    prev_vwap: float | None
    comparison_price_pass: bool | None
    comparison_vol_pass: bool | None
    comparison_vwap_pass: bool | None
    comparison_3of3_pass_count: int | None
    comparison_3of3_failed_subconditions: str
    cum_delta_24h: float | None
    cum_delta_180m: float | None
    cum_delta_60m: float | None
    ret_15m: float | None
    ret_60m: float | None
    dist_vwap: float | None
    abs_dist_vwap: float | None
    price_vs_vwap_side: str


@dataclass(frozen=True)
class IntegrityReport:
    missing_feed_match_count: int
    multi_event_timestamps: int
    unmatched_events: list[str]
    raw_delta_without_terminal_decision: int
