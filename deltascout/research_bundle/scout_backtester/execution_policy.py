from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .contracts import (
    BacktestContractError,
    Candidate,
    ExecutionPlan,
    FeedBar,
    InitialStopSelectionError,
    ReplayConfig,
)


@dataclass(frozen=True)
class InitialSwingSelection:
    stop: float
    swing_ts: datetime
    swing_price: float
    swing_volume: float
    eligible_count: int
    confirmed_count: int


def _step(value: float, step: float, rounding: str) -> float:
    value_d = Decimal(str(value))
    step_d = Decimal(str(step))
    units = (value_d / step_d).to_integral_value(rounding=rounding)
    return float(units * step_d)


def floor_to_step(value: float, step: float) -> float:
    return _step(value, step, ROUND_FLOOR)


def ceil_to_step(value: float, step: float) -> float:
    return _step(value, step, ROUND_CEILING)


def build_entry_price(side: str, signal_price: float, config: ReplayConfig) -> float:
    if side == "LONG":
        raw = max(signal_price + config.entry_offset_usd, signal_price + config.tick_size)
        return floor_to_step(raw, config.tick_size)
    if side == "SHORT":
        raw = min(signal_price - config.entry_offset_usd, signal_price - config.tick_size)
        return ceil_to_step(raw, config.tick_size)
    raise BacktestContractError(f"invalid side={side}")


def notional_to_qty(entry: float, notional: float, config: ReplayConfig) -> float:
    if entry <= 0:
        return 0.0
    return floor_to_step(notional / entry, config.qty_step)


def split_quantity(qty_total: float, config: ReplayConfig) -> tuple[float, float, float]:
    total_units = int((Decimal(str(qty_total)) / Decimal(str(config.qty_step))).to_integral_value(rounding=ROUND_FLOOR))
    if total_units <= 0:
        raise BacktestContractError("quantity rounds to zero")
    u1 = total_units // 3
    u2 = total_units // 3
    u3 = total_units - u1 - u2
    if u1 <= 0 or u2 <= 0:
        u1 = total_units // 2
        u2 = total_units - u1
        u3 = 0
    if u1 <= 0 or u2 <= 0 or u1 + u2 + u3 != total_units:
        raise BacktestContractError("invalid quantity split")
    step = Decimal(str(config.qty_step))
    return float(Decimal(u1) * step), float(Decimal(u2) * step), float(Decimal(u3) * step)


def initial_stop(
    side: str,
    entry: float,
    pre_signal_prices: list[float],
    config: ReplayConfig,
) -> float:
    pct_stop = entry * (1 - config.sl_pct) if side == "LONG" else entry * (1 + config.sl_pct)
    if side == "LONG":
        swing = (
            min(pre_signal_prices) - config.initial_swing_buffer_usd
            if pre_signal_prices
            else pct_stop
        )
        stop = min(pct_stop, swing, entry - config.tick_size)
        return floor_to_step(stop, config.tick_size)
    if side == "SHORT":
        swing = (
            max(pre_signal_prices) + config.initial_swing_buffer_usd
            if pre_signal_prices
            else pct_stop
        )
        stop = max(pct_stop, swing, entry + config.tick_size)
        return ceil_to_step(stop, config.tick_size)
    raise BacktestContractError(f"invalid side={side}")


def select_volume_confirmed_initial_stop(
    side: str,
    entry: float,
    bars: list[FeedBar],
    config: ReplayConfig,
) -> InitialSwingSelection:
    """Select the highest-volume confirmed swing whose buffered stop is within cap.

    A swing is confirmed entirely before the signal cutoff using strict fractal
    comparisons over ``initial_swing_lr`` bars on each side. Synthetic bars cannot
    define or confirm a swing. Ties on volume prefer the most recent swing.
    """

    lr = config.initial_swing_lr
    if len(bars) < 2 * lr + 1:
        raise InitialStopSelectionError(
            "NO_FULL_INITIAL_SWING_WINDOW",
            f"bars={len(bars)} required={2 * lr + 1}",
        )

    confirmed_count = 0
    eligible: list[tuple[float, datetime, float, float]] = []
    for index in range(lr, len(bars) - lr):
        neighborhood = bars[index - lr:index + lr + 1]
        if any(bar.is_synthetic for bar in neighborhood):
            continue
        bar = bars[index]
        if side == "LONG":
            swing_price = bar.low
            if swing_price >= entry:
                continue
            left = [item.low for item in bars[index - lr:index]]
            right = [item.low for item in bars[index + 1:index + lr + 1]]
            is_swing = all(swing_price < value for value in left + right)
        elif side == "SHORT":
            swing_price = bar.high
            if swing_price <= entry:
                continue
            left = [item.high for item in bars[index - lr:index]]
            right = [item.high for item in bars[index + 1:index + lr + 1]]
            is_swing = all(swing_price > value for value in left + right)
        else:
            raise BacktestContractError(f"invalid side={side}")
        if not is_swing:
            continue

        confirmed_count += 1
        stop = initial_stop(side, entry, [swing_price], config)
        distance = abs(entry - stop)
        cap = config.initial_swing_max_distance_usd
        if cap > 0 and distance > cap:
            continue
        eligible.append((bar.volume, bar.ts, swing_price, stop))

    if not eligible:
        reason = "NO_SWING_WITHIN_INITIAL_STOP_CAP" if confirmed_count else "NO_CONFIRMED_VOLUME_SWING"
        raise InitialStopSelectionError(
            reason,
            f"confirmed={confirmed_count} cap={config.initial_swing_max_distance_usd}",
        )

    swing_volume, swing_ts, swing_price, stop = max(eligible, key=lambda item: (item[0], item[1]))
    return InitialSwingSelection(
        stop=stop,
        swing_ts=swing_ts,
        swing_price=swing_price,
        swing_volume=swing_volume,
        eligible_count=len(eligible),
        confirmed_count=confirmed_count,
    )


def compute_targets(side: str, entry: float, stop: float, config: ReplayConfig) -> tuple[float, float]:
    risk = abs(entry - stop)
    if risk <= 0:
        raise BacktestContractError("initial risk must be positive")
    values: list[float] = []
    for multiplier in config.tp_r_multipliers:
        raw = entry + multiplier * risk if side == "LONG" else entry - multiplier * risk
        values.append(floor_to_step(raw, config.tick_size) if side == "LONG" else ceil_to_step(raw, config.tick_size))
    if len(values) != 2:
        raise BacktestContractError("exactly two TP multipliers are required")
    return values[0], values[1]


def build_execution_plan(
    candidate: Candidate,
    reference_bars: list[FeedBar],
    config: ReplayConfig,
    *,
    execution_bars: list[FeedBar] | None = None,
    reference_timestamps: list | None = None,
    execution_timestamps: list | None = None,
) -> ExecutionPlan:
    config.validate()
    execution_bars = execution_bars or reference_bars
    reference_timestamps = reference_timestamps or [bar.ts for bar in reference_bars]
    execution_timestamps = execution_timestamps or [bar.ts for bar in execution_bars]
    cutoff = bisect_right(reference_timestamps, candidate.signal_ts_utc)
    execution_cutoff = bisect_right(execution_timestamps, candidate.signal_ts_utc)
    if cutoff <= 0 or reference_bars[cutoff - 1].ts != candidate.signal_ts_utc:
        raise BacktestContractError("missing exact reference-feed signal minute")
    if execution_cutoff <= 0 or execution_bars[execution_cutoff - 1].ts != candidate.signal_ts_utc:
        raise BacktestContractError("missing exact execution-feed signal minute")
    window_bars = reference_bars[max(0, cutoff - config.swing_lookback_minutes):cutoff]
    if config.initial_swing_require_full_window and len(window_bars) < config.swing_lookback_minutes:
        raise InitialStopSelectionError(
            "NO_FULL_INITIAL_SWING_WINDOW",
            f"bars={len(window_bars)} required={config.swing_lookback_minutes}",
        )
    history_bars = [bar for bar in window_bars if not bar.is_synthetic]
    reference_close = reference_bars[cutoff - 1].close
    execution_close = execution_bars[execution_cutoff - 1].close
    if reference_close <= 0 or execution_close <= 0:
        raise BacktestContractError("invalid conversion reference close")
    if config.price_contour == "btcusdt_signal":
        # Research contour: candidate, plan, barriers, and lifecycle all remain
        # in the signal feed's BTCUSDT quote space. The CLI supplies the same
        # quality-checked bars for reference and execution in this mode.
        execution_close = reference_close
        conversion_ratio = 1.0
    else:
        conversion_ratio = execution_close / reference_close
    if not config.usdt_usdc_ratio_min <= conversion_ratio <= config.usdt_usdc_ratio_max:
        raise BacktestContractError(
            "conversion ratio outside sanity band: "
            f"ratio={conversion_ratio} "
            f"band=[{config.usdt_usdc_ratio_min},{config.usdt_usdc_ratio_max}]"
        )
    entry_usdt = build_entry_price(candidate.side, candidate.signal_price, config)
    selected_swing: InitialSwingSelection | None = None
    if config.initial_stop_policy == "volume_confirmed_swing":
        selected_swing = select_volume_confirmed_initial_stop(
            candidate.side,
            entry_usdt,
            window_bars,
            config,
        )
        stop_usdt = selected_swing.stop
    else:
        if config.initial_swing_price_source == "extreme":
            history = [bar.low if candidate.side == "LONG" else bar.high for bar in history_bars]
        else:
            history = [bar.close for bar in history_bars]
        stop_usdt = initial_stop(candidate.side, entry_usdt, history, config)
    tp1_usdt, tp2_usdt = compute_targets(candidate.side, entry_usdt, stop_usdt, config)
    raw_entry = entry_usdt * conversion_ratio
    raw_stop = stop_usdt * conversion_ratio
    raw_tp1 = tp1_usdt * conversion_ratio
    raw_tp2 = tp2_usdt * conversion_ratio
    signal_close_usdc = candidate.signal_price * conversion_ratio
    if candidate.side == "LONG":
        entry = floor_to_step(raw_entry, config.tick_size)
        entry = max(entry, ceil_to_step(signal_close_usdc + config.tick_size, config.tick_size))
        stop = floor_to_step(raw_stop, config.tick_size)
        tp1 = floor_to_step(raw_tp1, config.tick_size)
        tp2 = floor_to_step(raw_tp2, config.tick_size)
    else:
        entry = ceil_to_step(raw_entry, config.tick_size)
        entry = min(entry, floor_to_step(signal_close_usdc - config.tick_size, config.tick_size))
        stop = ceil_to_step(raw_stop, config.tick_size)
        tp1 = ceil_to_step(raw_tp1, config.tick_size)
        tp2 = ceil_to_step(raw_tp2, config.tick_size)
    if candidate.side == "LONG" and not (stop < entry < tp1 <= tp2):
        raise BacktestContractError("invalid LONG execution plan ordering")
    if candidate.side == "SHORT" and not (stop > entry > tp1 >= tp2):
        raise BacktestContractError("invalid SHORT execution plan ordering")
    return ExecutionPlan(
        candidate_id=candidate.candidate_id,
        side=candidate.side,
        planned_entry_price=entry,
        initial_stop_price=stop,
        initial_risk_usd=abs(entry - stop),
        tp1_price=tp1,
        tp2_price=tp2,
        fixed_notional_usdc=config.fixed_notional_usdc,
        signal_reference_price_usdt=candidate.signal_price,
        reference_feed_close_usdt=reference_close,
        execution_feed_close_usdc=execution_close,
        conversion_ratio=conversion_ratio,
        conversion_reference_ts=candidate.signal_ts_utc,
        planned_entry_price_usdt=entry_usdt,
        initial_stop_price_usdt=stop_usdt,
        tp1_price_usdt=tp1_usdt,
        tp2_price_usdt=tp2_usdt,
        initial_swing_ts=selected_swing.swing_ts if selected_swing else None,
        initial_swing_price_usdt=selected_swing.swing_price if selected_swing else None,
        initial_swing_volume=selected_swing.swing_volume if selected_swing else None,
        initial_swing_eligible_count=selected_swing.eligible_count if selected_swing else 0,
        initial_swing_confirmed_count=selected_swing.confirmed_count if selected_swing else 0,
    )
