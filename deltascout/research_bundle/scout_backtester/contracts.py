from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal


Side = Literal["LONG", "SHORT"]

CANDIDATE_CONTRACT_VERSION = "SCOUT_CANDIDATE_V0_1"
FEED_CONTRACT_VERSION = "SCOUT_FEED_V0_1"
EXECUTION_POLICY_ID = "EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2"
USDT_SIGNAL_EXECUTION_POLICY_ID = "EXECUTOR_V15_REPLAY_USDT_SIGNAL_CONTOUR_V0_1"
FILL_MODEL_ID = "MARKETABLE_LIMIT_NEXT_BAR_V0_1"
LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID = "LIMIT_THEN_MARKET_90S_GUARDED_V0_1"
CONSERVATIVE_SAME_BAR_POLICY_ID = "CONSERVATIVE_STOP_FIRST_V0_1"
TARGET_FIRST_SAME_BAR_POLICY_ID = "TARGET_FIRST_SENSITIVITY_V0_1"
COMMISSION_MODEL_ID = "COMMISSION_TURNOVER_RATE_V0_1"
ZERO_SLIPPAGE_MODEL_ID = "ZERO_SLIPPAGE_DIAGNOSTIC"
FIXED_BPS_SLIPPAGE_MODEL_ID = "FIXED_BPS_ADVERSE"
UTILITY_POLICY_ID = "SCOUT_UTILITY_V0_1"
QUALITY_POLICY_ID = "EFFECTIVE_FEED_RECOVERY_QUALITY_V0_1"
CONVERSION_MODEL_ID = "CONTEMPORANEOUS_BTCUSDC_SPOT_TO_BTCUSDT_REFERENCE_CLOSE_RATIO_V0_1"
IDENTITY_CONVERSION_MODEL_ID = "IDENTITY_BTCUSDT_SIGNAL_CONTOUR_V0_1"

REQUIRED_GROUPS = (
    "PEAK_EMIT_BASELINE",
    "ALMOST_PEAK_2_OF_3",
    "ALMOST_PEAK_1_OF_3",
    "DIRECTION_MISMATCH_REJECT",
    "VWAP_SIDE_REJECT",
    "GATE_REJECT",
    "OTHER_COMPARISON_REJECT",
)


class BacktestContractError(RuntimeError):
    """Raised when deterministic replay inputs violate a declared contract."""


class InitialStopSelectionError(BacktestContractError):
    """Raised when an opt-in initial-stop policy rejects a candidate."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    source_event_ts_local: str
    signal_ts_utc: datetime
    side: Side
    event_type: str
    candidate_group: str
    reject_reason: str | None
    signal_price: float
    delta: float
    volume: float
    imbalance: float | None
    vwap: float | None
    poc: float | None
    comparison_3of3_pass_count: int | None
    comparison_3of3_failed_subconditions: str | None
    shadow_flags: dict[str, Any]
    source_path: str
    source_row_hash: str
    admission_status: str = "ADMITTED"
    filter_rule_id: str | None = None
    filter_decision: str | None = None
    comparison_price_pass: bool | None = None
    comparison_vol_pass: bool | None = None
    comparison_vwap_pass: bool | None = None
    comparison_setup_variant: str | None = None
    comparison_previous_price: float | None = None
    comparison_previous_vol: float | None = None
    comparison_previous_vwap: float | None = None

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["signal_ts_utc"] = self.signal_ts_utc.isoformat()
        return row


@dataclass(frozen=True)
class CandidateQualityRow:
    source_path: str
    source_row_number: int | None
    reason: str
    detail: str
    candidate_id: str = ""


@dataclass(frozen=True)
class FeedBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_qty: float
    sell_qty: float
    is_synthetic: bool
    feed_quality_class: str
    recovery_overlap: bool
    source_path: str
    row_number: int
    optional: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ReplayConfig:
    experiment_id: str
    description: str = ""
    price_contour: str = "btcusdc_spot"
    symbol: str = "BTCUSDC"
    signal_price_symbol: str = "BTCUSDT_REFERENCE"
    signal_feature_feed_symbol: str = "BTCUSDT_USDM_FUTURES_ENRICHED"
    replay_feed_symbol: str = "BTCUSDC_SPOT_1M"
    execution_symbol: str = "BTCUSDC"
    fixed_notional_usdc: float = 3000.0
    tick_size: float = 0.01
    qty_step: float = 0.00001
    min_qty: float = 0.00001
    min_notional: float = 5.0
    entry_offset_usd: float = 0.5
    entry_expiry_bars: int = 2
    live_entry_timeout_seconds: int = 90
    planb_max_dev_r_mult: float = 0.25
    planb_max_dev_usd: float = 0.0
    planb_require_price: bool = True
    planb_abort_if_past_tp1: bool = True
    planb_price_proxy: str = "SECOND_NEXT_BAR_OPEN"
    sl_pct: float = 0.002
    swing_lookback_minutes: int = 180
    initial_stop_policy: str = "window_extreme"
    initial_swing_price_source: str = "close"
    initial_swing_buffer_usd: float = 0.0
    initial_swing_lr: int = 25
    initial_swing_max_distance_usd: float = 0.0
    initial_swing_require_full_window: bool = False
    tp_r_multipliers: tuple[float, float] = (1.0, 2.0)
    cooldown_seconds: int = 180
    trail_swing_lookback: int = 240
    trail_swing_lr: int = 2
    trail_swing_buffer_usd: float = 50.0
    trail_step_usd: float = 20.0
    trail_confirm_buffer_usd: float = 0.0
    usdt_usdc_ratio_min: float = 0.95
    usdt_usdc_ratio_max: float = 1.05
    sl_limit_gap_ticks: int = 2
    execution_policy_id: str = EXECUTION_POLICY_ID
    fill_model_id: str = FILL_MODEL_ID
    same_bar_policy_id: str = CONSERVATIVE_SAME_BAR_POLICY_ID
    cost_model_id: str = COMMISSION_MODEL_ID
    slippage_model_id: str = FIXED_BPS_SLIPPAGE_MODEL_ID
    commission_rate: float = 0.000744
    commission_calibration_source: str = "PINNED_SPEC_REFERENCE_0_000744"
    commission_calibration_count: int = 0
    entry_slippage_bps: float = 0.0
    exit_slippage_bps: float = 1.0
    stop_slippage_bps: float = 2.0
    conversion_model_id: str = CONVERSION_MODEL_ID
    quality_policy_id: str = QUALITY_POLICY_ID
    utility_policy_id: str = UTILITY_POLICY_ID

    def validate(self) -> None:
        if not self.experiment_id.strip():
            raise BacktestContractError("experiment_id must not be empty")
        if self.price_contour not in {"btcusdc_spot", "btcusdt_signal"}:
            raise BacktestContractError(f"unsupported price_contour={self.price_contour}")
        if self.initial_swing_price_source not in {"close", "extreme"}:
            raise BacktestContractError(
                f"unsupported initial_swing_price_source={self.initial_swing_price_source}"
            )
        if self.initial_swing_buffer_usd < 0:
            raise BacktestContractError(
                f"initial_swing_buffer_usd must be non-negative, got {self.initial_swing_buffer_usd}"
            )
        if self.fill_model_id not in {
            FILL_MODEL_ID,
            LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
        }:
            raise BacktestContractError(f"unsupported fill_model_id={self.fill_model_id}")
        if self.live_entry_timeout_seconds <= 0:
            raise BacktestContractError(
                "live_entry_timeout_seconds must be positive, "
                f"got {self.live_entry_timeout_seconds}"
            )
        if (
            self.fill_model_id == LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID
            and self.live_entry_timeout_seconds != 90
        ):
            raise BacktestContractError(
                "LIMIT_THEN_MARKET_90S_GUARDED_V0_1 requires "
                "live_entry_timeout_seconds=90"
            )
        if self.planb_max_dev_r_mult < 0:
            raise BacktestContractError(
                f"planb_max_dev_r_mult must be non-negative, got {self.planb_max_dev_r_mult}"
            )
        if self.planb_max_dev_usd < 0:
            raise BacktestContractError(
                f"planb_max_dev_usd must be non-negative, got {self.planb_max_dev_usd}"
            )
        if self.planb_price_proxy != "SECOND_NEXT_BAR_OPEN":
            raise BacktestContractError(f"unsupported planb_price_proxy={self.planb_price_proxy}")
        if self.initial_stop_policy not in {"window_extreme", "volume_confirmed_swing"}:
            raise BacktestContractError(f"unsupported initial_stop_policy={self.initial_stop_policy}")
        if self.initial_swing_lr <= 0:
            raise BacktestContractError(f"initial_swing_lr must be positive, got {self.initial_swing_lr}")
        if self.initial_swing_max_distance_usd < 0:
            raise BacktestContractError(
                "initial_swing_max_distance_usd must be non-negative, "
                f"got {self.initial_swing_max_distance_usd}"
            )
        if self.trail_swing_lookback <= 0:
            raise BacktestContractError(
                f"trail_swing_lookback must be positive, got {self.trail_swing_lookback}"
            )
        if self.trail_swing_lr <= 0:
            raise BacktestContractError(
                f"trail_swing_lr must be positive, got {self.trail_swing_lr}"
            )
        if self.trail_swing_buffer_usd < 0 or self.trail_step_usd < 0:
            raise BacktestContractError("trailing buffers and step must be non-negative")
        if self.trail_confirm_buffer_usd < 0:
            raise BacktestContractError(
                "trail_confirm_buffer_usd must be non-negative, "
                f"got {self.trail_confirm_buffer_usd}"
            )
        if (
            self.usdt_usdc_ratio_min <= 0
            or self.usdt_usdc_ratio_max <= 0
            or self.usdt_usdc_ratio_min > self.usdt_usdc_ratio_max
        ):
            raise BacktestContractError(
                "invalid USDT/USDC ratio band: "
                f"[{self.usdt_usdc_ratio_min}, {self.usdt_usdc_ratio_max}]"
            )
        if (
            self.initial_stop_policy == "volume_confirmed_swing"
            and self.swing_lookback_minutes < 2 * self.initial_swing_lr + 1
        ):
            raise BacktestContractError(
                "volume_confirmed_swing lookback must contain at least one complete fractal window"
            )
        positive = {
            "fixed_notional_usdc": self.fixed_notional_usdc,
            "tick_size": self.tick_size,
            "qty_step": self.qty_step,
            "entry_expiry_bars": self.entry_expiry_bars,
            "swing_lookback_minutes": self.swing_lookback_minutes,
        }
        for name, value in positive.items():
            if value <= 0:
                raise BacktestContractError(f"{name} must be positive, got {value}")
        if self.same_bar_policy_id not in {
            CONSERVATIVE_SAME_BAR_POLICY_ID,
            TARGET_FIRST_SAME_BAR_POLICY_ID,
        }:
            raise BacktestContractError(f"unsupported same_bar_policy_id={self.same_bar_policy_id}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionPlan:
    candidate_id: str
    side: Side
    planned_entry_price: float
    initial_stop_price: float
    initial_risk_usd: float
    tp1_price: float
    tp2_price: float
    fixed_notional_usdc: float
    signal_reference_price_usdt: float
    reference_feed_close_usdt: float
    execution_feed_close_usdc: float
    conversion_ratio: float
    conversion_reference_ts: datetime
    planned_entry_price_usdt: float
    initial_stop_price_usdt: float
    tp1_price_usdt: float
    tp2_price_usdt: float
    initial_swing_ts: datetime | None
    initial_swing_price_usdt: float | None
    initial_swing_volume: float | None
    initial_swing_eligible_count: int
    initial_swing_confirmed_count: int


@dataclass(frozen=True)
class TradeLeg:
    trade_id: str
    leg_id: str
    leg_type: str
    qty: float
    entry_price: float
    exit_price: float
    exit_ts: datetime
    gross_pnl_usdc: float
    turnover_usdc: float

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["exit_ts"] = self.exit_ts.isoformat()
        return row


@dataclass
class ReplayEvent:
    event_ts: datetime
    event_type: str
    trade_id: str
    candidate_id: str
    replay_mode: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["event_ts"] = self.event_ts.isoformat()
        return row


@dataclass
class TradeResult:
    trade_id: str
    candidate_id: str
    experiment_id: str
    replay_mode: str
    candidate_group: str
    side: Side
    signal_ts_utc: datetime
    entry_status: str
    session_label: str = ""
    signal_reference_price_usdt: float | None = None
    reference_feed_close_usdt: float | None = None
    execution_feed_close_usdc: float | None = None
    conversion_ratio: float | None = None
    conversion_reference_ts: datetime | None = None
    planned_entry_price_usdt: float | None = None
    initial_stop_price_usdt: float | None = None
    tp1_price_usdt: float | None = None
    tp2_price_usdt: float | None = None
    initial_swing_ts: datetime | None = None
    initial_swing_price_usdt: float | None = None
    initial_swing_volume: float | None = None
    initial_swing_eligible_count: int = 0
    initial_swing_confirmed_count: int = 0
    weak_peak_le_50: bool | None = None
    oi_down_60_and_directional_delta_pct_240_lt_0_06: bool | None = None
    loss_avoidance_conservative_union: bool | None = None
    entry_fill_ts: datetime | None = None
    entry_expiry_ts: datetime | None = None
    entry_fill_method: str = ""
    planb_decision: str = ""
    planb_abort_reason: str = ""
    planb_exec_price_proxy: float | None = None
    planb_deviation_usd: float | None = None
    planb_max_deviation_usd: float | None = None
    planb_risk_usd: float | None = None
    data_quality_interruption_ts: datetime | None = None
    planned_entry_price: float | None = None
    entry_fill_price: float | None = None
    fixed_notional_usdc: float = 0.0
    qty_total: float = 0.0
    qty1: float = 0.0
    qty2: float = 0.0
    qty3: float = 0.0
    initial_stop_price: float | None = None
    initial_risk_usd: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None
    tp1_fill_ts: datetime | None = None
    tp2_fill_ts: datetime | None = None
    breakeven_stop_price: float | None = None
    trail_activation_ts: datetime | None = None
    trail_update_count: int = 0
    final_stop_price: float | None = None
    exit_ts: datetime | None = None
    lifecycle_class: str = ""
    utility_bucket: str = ""
    gross_pnl_usdc: float | None = None
    commission_usdc: float | None = None
    commission_rate: float = 0.0
    commission_calibration_source: str = ""
    commission_calibration_count: int = 0
    cost_model_id: str = ""
    slippage_model_id: str = ""
    slippage_usdc: float | None = None
    borrow_interest_usdc: float | None = None
    net_pnl_usdc: float | None = None
    net_pnl_scope: str = "after_commission_before_borrow_interest"
    position_r: float | None = None
    same_bar_ambiguous: bool = False
    same_bar_collision_count: int = 0
    same_bar_policy_id: str = ""
    outcome_changes_under_sensitivity: bool | None = None
    feed_quality_class: str = ""
    recovery_overlap: bool = False
    blocked_reason: str = ""
    active_trade_id_when_blocked: str = ""
    source_path: str = ""
    run_fingerprint: str = ""
    independent_trade_id: str = ""
    legs: list[TradeLeg] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("legs", None)
        for key in (
            "signal_ts_utc",
            "conversion_reference_ts",
            "initial_swing_ts",
            "entry_fill_ts",
            "entry_expiry_ts",
            "data_quality_interruption_ts",
            "tp1_fill_ts",
            "tp2_fill_ts",
            "trail_activation_ts",
            "exit_ts",
        ):
            value = row[key]
            row[key] = value.isoformat() if value is not None else ""
        return row
