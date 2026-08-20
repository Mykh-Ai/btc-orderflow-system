from __future__ import annotations

from bisect import bisect_right

from .contracts import ExecutionPlan, FeedBar, ReplayConfig


def find_entry_fill(
    bars: list[FeedBar],
    *,
    signal_ts,
    plan: ExecutionPlan,
    config: ReplayConfig,
    timestamps: list | None = None,
) -> tuple[int | None, float | None, object | None, bool]:
    timestamps = timestamps or [bar.ts for bar in bars]
    start = bisect_right(timestamps, signal_ts)
    eligible = bars[start:start + config.entry_expiry_bars]
    expiry_ts = eligible[-1].ts if eligible else None
    for offset, bar in enumerate(eligible):
        if bar.is_synthetic:
            return None, None, expiry_ts, True
        if plan.side == "LONG":
            if bar.open <= plan.planned_entry_price:
                return start + offset, min(bar.open, plan.planned_entry_price), expiry_ts, False
            if bar.low <= plan.planned_entry_price:
                return start + offset, plan.planned_entry_price, expiry_ts, False
        else:
            if bar.open >= plan.planned_entry_price:
                return start + offset, max(bar.open, plan.planned_entry_price), expiry_ts, False
            if bar.high >= plan.planned_entry_price:
                return start + offset, plan.planned_entry_price, expiry_ts, False
    return None, None, expiry_ts, False
