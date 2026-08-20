from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from .contracts import (
    BacktestContractError,
    Candidate,
    ExecutionPlan,
    FeedBar,
    ReplayConfig,
)


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
    pre_signal_closes: list[float],
    config: ReplayConfig,
) -> float:
    pct_stop = entry * (1 - config.sl_pct) if side == "LONG" else entry * (1 + config.sl_pct)
    if side == "LONG":
        swing = min(pre_signal_closes) if pre_signal_closes else pct_stop
        stop = min(pct_stop, swing, entry - config.tick_size)
        return floor_to_step(stop, config.tick_size)
    if side == "SHORT":
        swing = max(pre_signal_closes) if pre_signal_closes else pct_stop
        stop = max(pct_stop, swing, entry + config.tick_size)
        return ceil_to_step(stop, config.tick_size)
    raise BacktestContractError(f"invalid side={side}")


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
    bars: list[FeedBar],
    config: ReplayConfig,
    *,
    timestamps: list | None = None,
) -> ExecutionPlan:
    config.validate()
    timestamps = timestamps or [bar.ts for bar in bars]
    cutoff = bisect_right(timestamps, candidate.signal_ts_utc)
    history = [
        bar.close
        for bar in bars[max(0, cutoff - config.swing_lookback_minutes):cutoff]
        if not bar.is_synthetic
    ]
    entry = build_entry_price(candidate.side, candidate.signal_price, config)
    stop = initial_stop(candidate.side, entry, history, config)
    tp1, tp2 = compute_targets(candidate.side, entry, stop, config)
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
    )
