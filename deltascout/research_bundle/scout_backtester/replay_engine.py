from __future__ import annotations

import hashlib
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime

from .contracts import (
    BacktestContractError,
    Candidate,
    FeedBar,
    InitialStopSelectionError,
    ReplayConfig,
    ReplayEvent,
    TradeLeg,
    TradeResult,
)
from .cost_models import calculate_costs, gross_for_leg
from .execution_policy import (
    build_execution_plan,
    ceil_to_step,
    floor_to_step,
    notional_to_qty,
    split_quantity,
)
from .fill_models import find_entry_fill
from .same_bar_policies import level_touched, stop_wins


def _trade_id(candidate: Candidate, config: ReplayConfig, mode: str) -> str:
    payload = f"{config.experiment_id}|{candidate.candidate_id}|{mode}|{config.same_bar_policy_id}"
    return "TR_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _session_label(ts: datetime) -> str:
    if ts.hour < 8:
        return "ASIA_UTC"
    if ts.hour < 16:
        return "EUROPE_UTC"
    return "US_UTC"


def _utility(lifecycle: str) -> str:
    return {
        "PLAIN_SL": "LOSS_TARGET",
        "TP1_SL": "SCRATCH_NEUTRAL",
        "TP1_TP2_TRAILING_STOP": "PROTECTED_WINNER",
        "TP1_TP2_OPEN_TRAIL": "UNRESOLVED",
        "UNRESOLVED_END_OF_DATA": "UNRESOLVED",
        "NO_FILL": "NO_TRADE",
        "INVALID_EXECUTION_PLAN": "NO_TRADE",
    }.get(lifecycle, "NO_TRADE")


@dataclass(frozen=True)
class _TrailingStopQuote:
    stop_usdt: float
    stop_execution: float
    conversion_ratio: float
    conversion_reference_ts: datetime
    reference_close_usdt: float
    execution_close: float
    swing_ts: datetime
    swing_price_usdt: float


def _last_fractal_bar(bars: list[FeedBar], lr: int, kind: str) -> FeedBar | None:
    if len(bars) < 2 * lr + 1:
        return None
    for index in range(len(bars) - lr - 1, lr - 1, -1):
        neighborhood = bars[index - lr:index + lr + 1]
        if any(bar.is_synthetic for bar in neighborhood):
            continue
        value = bars[index].low if kind == "low" else bars[index].high
        left = [bar.low if kind == "low" else bar.high for bar in bars[index - lr:index]]
        right = [bar.low if kind == "low" else bar.high for bar in bars[index + 1:index + 1 + lr]]
        if kind == "low" and all(value < item for item in left) and all(value < item for item in right):
            return bars[index]
        if kind == "high" and all(value > item for item in left) and all(value > item for item in right):
            return bars[index]
    return None


def _reference_context(
    execution_bar: FeedBar,
    reference_bars: list[FeedBar],
    reference_timestamps: list,
) -> tuple[int, FeedBar] | None:
    index = bisect_right(reference_timestamps, execution_bar.ts) - 1
    if index < 0 or reference_bars[index].ts != execution_bar.ts:
        return None
    reference_bar = reference_bars[index]
    if reference_bar.is_synthetic or reference_bar.close <= 0 or execution_bar.close <= 0:
        return None
    return index, reference_bar


def _desired_trail_quote(
    side: str,
    execution_bar: FeedBar,
    reference_bars: list[FeedBar],
    reference_timestamps: list,
    active_stop: float,
    config: ReplayConfig,
    *,
    require_step_improvement: bool,
) -> _TrailingStopQuote | None:
    context = _reference_context(execution_bar, reference_bars, reference_timestamps)
    if context is None:
        return None
    reference_index, reference_bar = context
    first = max(0, reference_index + 1 - config.trail_swing_lookback)
    swing_bar = _last_fractal_bar(
        reference_bars[first:reference_index + 1],
        config.trail_swing_lr,
        "low" if side == "LONG" else "high",
    )
    if swing_bar is None:
        return None

    if side == "LONG":
        swing_price = swing_bar.low
        stop_usdt = swing_price - config.trail_swing_buffer_usd
    elif side == "SHORT":
        swing_price = swing_bar.high
        stop_usdt = swing_price + config.trail_swing_buffer_usd
    else:
        raise BacktestContractError(f"invalid side={side}")

    conversion_ratio = (
        1.0
        if config.price_contour == "btcusdt_signal"
        else execution_bar.close / reference_bar.close
    )
    if not config.usdt_usdc_ratio_min <= conversion_ratio <= config.usdt_usdc_ratio_max:
        return None

    raw_stop = stop_usdt * conversion_ratio
    if side == "LONG":
        stop_execution = floor_to_step(raw_stop, config.tick_size)
        if stop_execution > execution_bar.close - config.tick_size:
            return None
        if require_step_improvement and stop_execution < active_stop + config.trail_step_usd:
            return None
    else:
        stop_execution = ceil_to_step(raw_stop, config.tick_size)
        if stop_execution < execution_bar.close + config.tick_size:
            return None
        if require_step_improvement and stop_execution > active_stop - config.trail_step_usd:
            return None

    return _TrailingStopQuote(
        stop_usdt=stop_usdt,
        stop_execution=stop_execution,
        conversion_ratio=conversion_ratio,
        conversion_reference_ts=execution_bar.ts,
        reference_close_usdt=reference_bar.close,
        execution_close=execution_bar.close,
        swing_ts=swing_bar.ts,
        swing_price_usdt=swing_price,
    )


def _trail_event_payload(quote: _TrailingStopQuote) -> dict[str, object]:
    return {
        "stop": quote.stop_execution,
        "stop_usdt": quote.stop_usdt,
        "conversion_ratio": quote.conversion_ratio,
        "conversion_reference_ts": quote.conversion_reference_ts.isoformat(),
        "reference_close_usdt": quote.reference_close_usdt,
        "execution_close": quote.execution_close,
        "swing_ts": quote.swing_ts.isoformat(),
        "swing_price_usdt": quote.swing_price_usdt,
    }


def _quality(bars: list[FeedBar]) -> tuple[str, bool]:
    if not bars:
        return "NO_FEED_COVERAGE", False
    classes = {bar.feed_quality_class for bar in bars}
    overlap = any(bar.recovery_overlap for bar in bars)
    if any(bar.is_synthetic for bar in bars):
        return "DEGRADED_SYNTHETIC", overlap
    if overlap:
        return "RECOVERED", True
    if len(classes) == 1:
        return next(iter(classes)), False
    return "MIXED", overlap


def _event(events: list[ReplayEvent], ts: datetime, kind: str, result: TradeResult, **payload) -> None:
    events.append(ReplayEvent(ts, kind, result.trade_id, result.candidate_id, result.replay_mode, payload))


def _add_leg(result: TradeResult, leg_type: str, qty: float, exit_price: float, ts: datetime) -> None:
    if qty <= 0 or result.entry_fill_price is None:
        return
    gross = gross_for_leg(result.side, qty, result.entry_fill_price, exit_price)
    result.legs.append(
        TradeLeg(
            trade_id=result.trade_id,
            leg_id=f"{result.trade_id}_L{len(result.legs) + 1}",
            leg_type=leg_type,
            qty=qty,
            entry_price=result.entry_fill_price,
            exit_price=exit_price,
            exit_ts=ts,
            gross_pnl_usdc=gross,
            turnover_usdc=qty * (result.entry_fill_price + exit_price),
        )
    )


def _finalize_economics(result: TradeResult, config: ReplayConfig) -> None:
    if result.entry_fill_price is None:
        result.gross_pnl_usdc = 0.0
        result.commission_usdc = 0.0
        result.slippage_usdc = 0.0
        result.net_pnl_usdc = 0.0
        return
    result.gross_pnl_usdc = sum(leg.gross_pnl_usdc for leg in result.legs)
    _, commission, slippage = calculate_costs(
        qty_total=result.qty_total,
        entry_price=result.entry_fill_price,
        legs=result.legs,
        commission_rate=config.commission_rate,
        entry_slippage_bps=config.entry_slippage_bps,
        exit_slippage_bps=config.exit_slippage_bps,
        stop_slippage_bps=config.stop_slippage_bps,
    )
    result.commission_usdc = commission
    result.slippage_usdc = slippage
    result.net_pnl_usdc = result.gross_pnl_usdc - commission - slippage
    risk_capital = result.qty_total * float(result.initial_risk_usd or 0.0)
    result.position_r = result.gross_pnl_usdc / risk_capital if risk_capital > 0 else None


def replay_candidate(
    candidate: Candidate,
    bars: list[FeedBar],
    config: ReplayConfig,
    *,
    reference_bars: list[FeedBar] | None = None,
    replay_mode: str = "independent_opportunity",
    _timestamps: list | None = None,
    _reference_timestamps: list | None = None,
) -> tuple[TradeResult, list[ReplayEvent]]:
    reference_bars = reference_bars or bars
    _timestamps = _timestamps or [bar.ts for bar in bars]
    _reference_timestamps = _reference_timestamps or [bar.ts for bar in reference_bars]
    result = TradeResult(
        trade_id=_trade_id(candidate, config, replay_mode),
        candidate_id=candidate.candidate_id,
        experiment_id=config.experiment_id,
        replay_mode=replay_mode,
        candidate_group=candidate.candidate_group,
        side=candidate.side,
        signal_ts_utc=candidate.signal_ts_utc,
        entry_status="PENDING",
        session_label=_session_label(candidate.signal_ts_utc),
        weak_peak_le_50=candidate.shadow_flags.get("weak_peak_le_50"),
        oi_down_60_and_directional_delta_pct_240_lt_0_06=candidate.shadow_flags.get("oi_down_60_and_directional_delta_pct_240_lt_0_06"),
        loss_avoidance_conservative_union=candidate.shadow_flags.get("loss_avoidance_conservative_union"),
        fixed_notional_usdc=config.fixed_notional_usdc,
        commission_rate=config.commission_rate,
        commission_calibration_source=config.commission_calibration_source,
        commission_calibration_count=config.commission_calibration_count,
        cost_model_id=config.cost_model_id,
        slippage_model_id=config.slippage_model_id,
        same_bar_policy_id=config.same_bar_policy_id,
        source_path=candidate.source_path,
    )
    events: list[ReplayEvent] = []
    _event(events, candidate.signal_ts_utc, "CANDIDATE_SEEN", result)
    try:
        plan = build_execution_plan(
            candidate,
            reference_bars,
            config,
            execution_bars=bars,
            reference_timestamps=_reference_timestamps,
            execution_timestamps=_timestamps,
        )
    except InitialStopSelectionError as exc:
        result.entry_status = "BLOCKED"
        result.lifecycle_class = "NO_TRADE"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = exc.reason
        _event(events, candidate.signal_ts_utc, "CANDIDATE_BLOCKED", result, reason=str(exc))
        _finalize_economics(result, config)
        return result, events
    except BacktestContractError as exc:
        result.entry_status = "INVALID"
        result.lifecycle_class = "INVALID_EXECUTION_PLAN"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = "INVALID_CANDIDATE"
        _event(events, candidate.signal_ts_utc, "CANDIDATE_BLOCKED", result, reason=str(exc))
        _finalize_economics(result, config)
        return result, events

    result.planned_entry_price = plan.planned_entry_price
    result.signal_reference_price_usdt = plan.signal_reference_price_usdt
    result.reference_feed_close_usdt = plan.reference_feed_close_usdt
    result.execution_feed_close_usdc = plan.execution_feed_close_usdc
    result.conversion_ratio = plan.conversion_ratio
    result.conversion_reference_ts = plan.conversion_reference_ts
    result.planned_entry_price_usdt = plan.planned_entry_price_usdt
    result.initial_stop_price_usdt = plan.initial_stop_price_usdt
    result.tp1_price_usdt = plan.tp1_price_usdt
    result.tp2_price_usdt = plan.tp2_price_usdt
    result.initial_swing_ts = plan.initial_swing_ts
    result.initial_swing_price_usdt = plan.initial_swing_price_usdt
    result.initial_swing_volume = plan.initial_swing_volume
    result.initial_swing_eligible_count = plan.initial_swing_eligible_count
    result.initial_swing_confirmed_count = plan.initial_swing_confirmed_count
    result.initial_stop_price = plan.initial_stop_price
    result.initial_risk_usd = plan.initial_risk_usd
    result.tp1_price = plan.tp1_price
    result.tp2_price = plan.tp2_price
    _event(events, candidate.signal_ts_utc, "ENTRY_PENDING", result, planned_entry=plan.planned_entry_price)
    entry_decision = find_entry_fill(
        bars,
        signal_ts=candidate.signal_ts_utc,
        plan=plan,
        config=config,
        timestamps=_timestamps,
    )
    entry_index = entry_decision.entry_index
    entry_price = entry_decision.entry_price
    expiry_ts = entry_decision.expiry_ts
    result.entry_expiry_ts = expiry_ts
    result.entry_fill_method = entry_decision.fill_method
    result.planb_decision = entry_decision.decision
    result.planb_abort_reason = entry_decision.abort_reason
    result.planb_exec_price_proxy = entry_decision.planb_exec_price_proxy
    result.planb_deviation_usd = entry_decision.planb_deviation_usd
    result.planb_max_deviation_usd = entry_decision.planb_max_deviation_usd
    result.planb_risk_usd = entry_decision.planb_risk_usd
    if entry_decision.quality_interrupted:
        result.entry_status = "NO_FEED_COVERAGE"
        result.lifecycle_class = "NO_FILL"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = "NO_FEED_COVERAGE"
        result.feed_quality_class = "DEGRADED_SYNTHETIC"
        result.data_quality_interruption_ts = expiry_ts
        _event(events, expiry_ts or candidate.signal_ts_utc, "ENTRY_EXPIRED", result, reason="untrusted synthetic entry window")
        _finalize_economics(result, config)
        return result, events
    if entry_decision.abort_reason:
        result.entry_status = "ABORTED"
        result.lifecycle_class = "NO_FILL"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = entry_decision.abort_reason
        _event(
            events,
            expiry_ts or candidate.signal_ts_utc,
            "ENTRY_PLANB_ABORTED",
            result,
            reason=entry_decision.abort_reason,
            exec_price_proxy=entry_decision.planb_exec_price_proxy,
            deviation_usd=entry_decision.planb_deviation_usd,
            max_deviation_usd=entry_decision.planb_max_deviation_usd,
        )
        _finalize_economics(result, config)
        return result, events
    if entry_index is None or entry_price is None:
        result.entry_status = "NO_FILL" if expiry_ts is not None else "NO_FEED_COVERAGE"
        result.lifecycle_class = "NO_FILL"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = "NO_FEED_COVERAGE" if expiry_ts is None else ""
        _event(events, expiry_ts or candidate.signal_ts_utc, "ENTRY_EXPIRED", result)
        _finalize_economics(result, config)
        return result, events

    result.entry_status = "FILLED"
    result.entry_fill_ts = bars[entry_index].ts
    result.entry_fill_price = entry_price
    result.qty_total = notional_to_qty(entry_price, config.fixed_notional_usdc, config)
    if result.qty_total < config.min_qty or result.qty_total * entry_price < config.min_notional:
        result.entry_status = "INVALID"
        result.lifecycle_class = "INVALID_EXECUTION_PLAN"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = "INVALID_CANDIDATE"
        _event(events, bars[entry_index].ts, "CANDIDATE_BLOCKED", result, reason="exchange minimum")
        _finalize_economics(result, config)
        return result, events
    try:
        result.qty1, result.qty2, result.qty3 = split_quantity(result.qty_total, config)
    except BacktestContractError as exc:
        result.entry_status = "INVALID"
        result.lifecycle_class = "INVALID_EXECUTION_PLAN"
        result.utility_bucket = _utility(result.lifecycle_class)
        result.blocked_reason = "INVALID_CANDIDATE"
        _event(events, bars[entry_index].ts, "CANDIDATE_BLOCKED", result, reason=str(exc))
        _finalize_economics(result, config)
        return result, events
    _event(
        events,
        bars[entry_index].ts,
        "ENTRY_FILLED",
        result,
        fill_price=entry_price,
        qty=result.qty_total,
        fill_method=result.entry_fill_method,
    )
    _event(events, bars[entry_index].ts, "INITIAL_SL_SET", result, stop=result.initial_stop_price)

    active_stop = float(result.initial_stop_price)
    pending_trail: _TrailingStopQuote | None = None
    trail_ref_price_usdt: float | None = None
    trail_wait_confirm = False
    state = "OPEN"
    used_bars: list[FeedBar] = []
    remaining = result.qty_total
    data_quality_interrupted = False

    for index in range(entry_index, len(bars)):
        bar = bars[index]
        used_bars.append(bar)
        if pending_trail is not None:
            active_stop = pending_trail.stop_execution
            result.final_stop_price = active_stop
            if state == "TRAILING":
                result.trail_update_count += 1
                _event(
                    events,
                    bar.ts,
                    "TRAIL_UPDATED",
                    result,
                    **_trail_event_payload(pending_trail),
                )
            pending_trail = None
        if bar.is_synthetic:
            data_quality_interrupted = True
            result.data_quality_interruption_ts = bar.ts
            break
        stop_hit = level_touched(result.side, bar, active_stop, "stop")
        target_level = result.tp1_price if state == "OPEN" else result.tp2_price if state == "TP1_DONE" else None
        target_hit = target_level is not None and level_touched(result.side, bar, float(target_level), "target")
        second_target_hit = state == "OPEN" and level_touched(result.side, bar, float(result.tp2_price), "target")
        collision = bool(stop_hit and target_hit)
        if collision:
            result.same_bar_ambiguous = True
            result.same_bar_collision_count += 1

        if stop_hit and (not target_hit or stop_wins(config.same_bar_policy_id)):
            leg_type = "INITIAL_STOP" if state == "OPEN" else "BREAKEVEN_STOP" if state == "TP1_DONE" else "TRAILING_STOP"
            _add_leg(result, leg_type, remaining, active_stop, bar.ts)
            _event(events, bar.ts, "STOP_FILLED", result, stop=active_stop, state=state)
            result.exit_ts = bar.ts
            result.final_stop_price = active_stop
            result.lifecycle_class = "PLAIN_SL" if state == "OPEN" else "TP1_SL" if state == "TP1_DONE" else "TP1_TP2_TRAILING_STOP"
            remaining = 0.0
            break

        if state == "OPEN" and target_hit:
            _add_leg(result, "TP1", result.qty1, float(result.tp1_price), bar.ts)
            remaining -= result.qty1
            result.tp1_fill_ts = bar.ts
            result.breakeven_stop_price = result.entry_fill_price
            active_stop = float(result.entry_fill_price)
            result.final_stop_price = active_stop
            state = "TP1_DONE"
            _event(events, bar.ts, "TP1_FILLED", result, price=result.tp1_price)
            _event(events, bar.ts, "SL_MOVED_TO_BE", result, stop=active_stop)
            breakeven_hit = level_touched(result.side, bar, active_stop, "stop")
            if breakeven_hit and stop_wins(config.same_bar_policy_id):
                result.same_bar_ambiguous = True
                result.same_bar_collision_count += 1
                _add_leg(result, "BREAKEVEN_STOP", remaining, active_stop, bar.ts)
                remaining = 0.0
                result.exit_ts = bar.ts
                result.lifecycle_class = "TP1_SL"
                _event(events, bar.ts, "STOP_FILLED", result, stop=active_stop, state=state)
                break
            if second_target_hit:
                _add_leg(result, "TP2", result.qty2, float(result.tp2_price), bar.ts)
                remaining -= result.qty2
                result.tp2_fill_ts = bar.ts
                result.trail_activation_ts = bar.ts
                state = "TRAILING"
                _event(events, bar.ts, "TP2_FILLED", result, price=result.tp2_price)
                pending_trail = _desired_trail_quote(
                    result.side,
                    bar,
                    reference_bars,
                    _reference_timestamps,
                    active_stop,
                    config,
                    require_step_improvement=False,
                )
                reference_context = _reference_context(bar, reference_bars, _reference_timestamps)
                if reference_context is not None:
                    trail_ref_price_usdt = reference_context[1].close
                    trail_wait_confirm = True
                _event(
                    events,
                    bar.ts,
                    "TRAIL_ACTIVATED",
                    result,
                    confirmation_ref_price_usdt=trail_ref_price_usdt,
                    initial_trail_quote=(
                        _trail_event_payload(pending_trail) if pending_trail is not None else None
                    ),
                )
                if stop_hit and not stop_wins(config.same_bar_policy_id):
                    _add_leg(result, "TRAILING_STOP", remaining, active_stop, bar.ts)
                    remaining = 0.0
                    result.exit_ts = bar.ts
                    result.lifecycle_class = "TP1_TP2_TRAILING_STOP"
                    _event(events, bar.ts, "STOP_FILLED", result, stop=active_stop, state=state)
                    break
            elif breakeven_hit:
                result.same_bar_ambiguous = True
                result.same_bar_collision_count += 1
                _add_leg(result, "BREAKEVEN_STOP", remaining, active_stop, bar.ts)
                remaining = 0.0
                result.exit_ts = bar.ts
                result.lifecycle_class = "TP1_SL"
                _event(events, bar.ts, "STOP_FILLED", result, stop=active_stop, state=state)
                break
            continue

        if state == "TP1_DONE" and target_hit:
            _add_leg(result, "TP2", result.qty2, float(result.tp2_price), bar.ts)
            remaining -= result.qty2
            result.tp2_fill_ts = bar.ts
            result.trail_activation_ts = bar.ts
            state = "TRAILING"
            _event(events, bar.ts, "TP2_FILLED", result, price=result.tp2_price)
            pending_trail = _desired_trail_quote(
                result.side,
                bar,
                reference_bars,
                _reference_timestamps,
                active_stop,
                config,
                require_step_improvement=False,
            )
            reference_context = _reference_context(bar, reference_bars, _reference_timestamps)
            if reference_context is not None:
                trail_ref_price_usdt = reference_context[1].close
                trail_wait_confirm = True
            _event(
                events,
                bar.ts,
                "TRAIL_ACTIVATED",
                result,
                confirmation_ref_price_usdt=trail_ref_price_usdt,
                initial_trail_quote=(
                    _trail_event_payload(pending_trail) if pending_trail is not None else None
                ),
            )
            if stop_hit and not stop_wins(config.same_bar_policy_id):
                _add_leg(result, "TRAILING_STOP", remaining, active_stop, bar.ts)
                remaining = 0.0
                result.exit_ts = bar.ts
                result.lifecycle_class = "TP1_TP2_TRAILING_STOP"
                _event(events, bar.ts, "STOP_FILLED", result, stop=active_stop, state=state)
                break
            continue

        if state == "TRAILING":
            reference_context = _reference_context(bar, reference_bars, _reference_timestamps)
            if trail_wait_confirm:
                if reference_context is None or trail_ref_price_usdt is None:
                    continue
                reference_close = reference_context[1].close
                confirmed = (
                    reference_close > trail_ref_price_usdt + config.trail_confirm_buffer_usd
                    if result.side == "LONG"
                    else reference_close < trail_ref_price_usdt - config.trail_confirm_buffer_usd
                )
                if not confirmed:
                    continue
                trail_wait_confirm = False
                _event(
                    events,
                    bar.ts,
                    "TRAIL_CONFIRM_BREAK",
                    result,
                    ref_price_usdt=trail_ref_price_usdt,
                    close_price_usdt=reference_close,
                    buffer_usd=config.trail_confirm_buffer_usd,
                )
            desired = _desired_trail_quote(
                result.side,
                bar,
                reference_bars,
                _reference_timestamps,
                active_stop,
                config,
                require_step_improvement=True,
            )
            if desired is not None:
                pending_trail = desired

    if data_quality_interrupted:
        result.lifecycle_class = "TP1_TP2_OPEN_TRAIL" if state == "TRAILING" else "UNRESOLVED_END_OF_DATA"
        result.exit_ts = None
        result.blocked_reason = "NO_FEED_COVERAGE"
        _event(events, used_bars[-1].ts, "RUN_ENDED_UNRESOLVED", result, state=state, reason="untrusted synthetic feed row")
    elif not result.lifecycle_class:
        result.lifecycle_class = "TP1_TP2_OPEN_TRAIL" if state == "TRAILING" else "UNRESOLVED_END_OF_DATA"
        result.exit_ts = None
        _event(events, bars[-1].ts if bars else candidate.signal_ts_utc, "RUN_ENDED_UNRESOLVED", result, state=state)
    else:
        _event(events, result.exit_ts or candidate.signal_ts_utc, "POSITION_CLOSED", result, lifecycle=result.lifecycle_class)
    result.utility_bucket = _utility(result.lifecycle_class)
    result.feed_quality_class, result.recovery_overlap = _quality(used_bars)
    _finalize_economics(result, config)
    return result, events


def replay_independent(
    candidates: list[Candidate],
    bars: list[FeedBar],
    config: ReplayConfig,
    *,
    reference_bars: list[FeedBar] | None = None,
) -> tuple[list[TradeResult], list[ReplayEvent]]:
    results: list[TradeResult] = []
    events: list[ReplayEvent] = []
    timestamps = [bar.ts for bar in bars]
    reference_bars = reference_bars or bars
    reference_timestamps = [bar.ts for bar in reference_bars]
    for candidate in candidates:
        result, candidate_events = replay_candidate(
            candidate,
            bars,
            config,
            reference_bars=reference_bars,
            _timestamps=timestamps,
            _reference_timestamps=reference_timestamps,
        )
        results.append(result)
        events.extend(candidate_events)
    events.sort(key=lambda item: (item.event_ts, item.trade_id, item.event_type))
    return results, events


def clone_for_mode(result: TradeResult, mode: str, trade_id: str) -> TradeResult:
    cloned = replace(result, replay_mode=mode, trade_id=trade_id, independent_trade_id=result.trade_id)
    cloned.legs = [replace(leg, trade_id=trade_id, leg_id=f"{trade_id}_L{index + 1}") for index, leg in enumerate(result.legs)]
    return cloned
