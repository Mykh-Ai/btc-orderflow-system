from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime

from .contracts import (
    FILL_MODEL_ID,
    LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
    BacktestContractError,
    ExecutionPlan,
    FeedBar,
    ReplayConfig,
)


@dataclass(frozen=True)
class EntryFillDecision:
    entry_index: int | None
    entry_price: float | None
    expiry_ts: datetime | None
    quality_interrupted: bool = False
    fill_method: str = ""
    decision: str = ""
    abort_reason: str = ""
    planb_exec_price_proxy: float | None = None
    planb_deviation_usd: float | None = None
    planb_max_deviation_usd: float | None = None
    planb_risk_usd: float | None = None


def _limit_fill_price(bar: FeedBar, plan: ExecutionPlan) -> float | None:
    if plan.side == "LONG":
        if bar.open <= plan.planned_entry_price:
            return min(bar.open, plan.planned_entry_price)
        if bar.low <= plan.planned_entry_price:
            return plan.planned_entry_price
        return None
    if bar.open >= plan.planned_entry_price:
        return max(bar.open, plan.planned_entry_price)
    if bar.high >= plan.planned_entry_price:
        return plan.planned_entry_price
    return None


def _legacy_limit_fill(
    bars: list[FeedBar],
    *,
    start: int,
    plan: ExecutionPlan,
    config: ReplayConfig,
) -> EntryFillDecision:
    eligible = bars[start:start + config.entry_expiry_bars]
    expiry_ts = eligible[-1].ts if eligible else None
    for offset, bar in enumerate(eligible):
        if bar.is_synthetic:
            return EntryFillDecision(None, None, expiry_ts, quality_interrupted=True)
        fill_price = _limit_fill_price(bar, plan)
        if fill_price is not None:
            return EntryFillDecision(
                start + offset,
                fill_price,
                expiry_ts,
                fill_method="LIMIT",
                decision="LIMIT_FILLED",
            )
    return EntryFillDecision(None, None, expiry_ts, decision="LIMIT_EXPIRED")


def _guarded_planb_fill(
    bars: list[FeedBar],
    *,
    start: int,
    plan: ExecutionPlan,
    config: ReplayConfig,
) -> EntryFillDecision:
    # Frozen one-minute approximation of the live 90-second sequence. The first
    # complete post-signal bar is the LIMIT window; the second post-signal bar's
    # open is the closest deterministic timeout-price proxy available in 1m OHLC.
    limit_bar = bars[start] if start < len(bars) else None
    timeout_index = start + 1
    timeout_bar = bars[timeout_index] if timeout_index < len(bars) else None
    expiry_ts = timeout_bar.ts if timeout_bar is not None else limit_bar.ts if limit_bar is not None else None

    if limit_bar is None or timeout_bar is None:
        return EntryFillDecision(None, None, expiry_ts, quality_interrupted=True)
    if limit_bar.is_synthetic or timeout_bar.is_synthetic:
        return EntryFillDecision(None, None, expiry_ts, quality_interrupted=True)

    limit_price = _limit_fill_price(limit_bar, plan)
    if limit_price is not None:
        return EntryFillDecision(
            start,
            limit_price,
            expiry_ts,
            fill_method="LIMIT",
            decision="LIMIT_FILLED",
        )

    exec_price = timeout_bar.open
    risk = abs(plan.planned_entry_price - plan.initial_stop_price)
    max_deviation = risk * config.planb_max_dev_r_mult
    if config.planb_max_dev_usd > 0:
        max_deviation = max(max_deviation, config.planb_max_dev_usd)
    deviation = abs(exec_price - plan.planned_entry_price)
    common = {
        "expiry_ts": expiry_ts,
        "planb_exec_price_proxy": exec_price,
        "planb_deviation_usd": deviation,
        "planb_max_deviation_usd": max_deviation,
        "planb_risk_usd": risk,
    }

    if config.planb_require_price and exec_price <= 0:
        return EntryFillDecision(
            None,
            None,
            abort_reason="PLANB_PRICE_UNAVAILABLE",
            decision="ABORT",
            **common,
        )
    if max_deviation > 0 and deviation > max_deviation:
        return EntryFillDecision(
            None,
            None,
            abort_reason="PLANB_DEVIATION_TOO_LARGE",
            decision="ABORT",
            **common,
        )
    past_tp1 = (
        plan.side == "LONG" and exec_price >= plan.tp1_price
    ) or (
        plan.side == "SHORT" and exec_price <= plan.tp1_price
    )
    if config.planb_abort_if_past_tp1 and past_tp1:
        return EntryFillDecision(
            None,
            None,
            abort_reason="PLANB_PAST_TP1",
            decision="ABORT",
            **common,
        )
    return EntryFillDecision(
        timeout_index,
        exec_price,
        fill_method="PLANB_MARKET",
        decision="MARKET_FILLED",
        **common,
    )


def find_entry_fill(
    bars: list[FeedBar],
    *,
    signal_ts,
    plan: ExecutionPlan,
    config: ReplayConfig,
    timestamps: list | None = None,
) -> EntryFillDecision:
    timestamps = timestamps or [bar.ts for bar in bars]
    start = bisect_right(timestamps, signal_ts)
    if config.fill_model_id == FILL_MODEL_ID:
        return _legacy_limit_fill(bars, start=start, plan=plan, config=config)
    if config.fill_model_id == LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID:
        return _guarded_planb_fill(bars, start=start, plan=plan, config=config)
    raise BacktestContractError(f"unsupported fill_model_id={config.fill_model_id}")
