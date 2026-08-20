from __future__ import annotations

from .contracts import (
    CONSERVATIVE_SAME_BAR_POLICY_ID,
    TARGET_FIRST_SAME_BAR_POLICY_ID,
    BacktestContractError,
    FeedBar,
)


def level_touched(side: str, bar: FeedBar, level: float, kind: str) -> bool:
    if kind == "stop":
        return bar.low <= level if side == "LONG" else bar.high >= level
    if kind == "target":
        return bar.high >= level if side == "LONG" else bar.low <= level
    raise BacktestContractError(f"unsupported active level kind={kind}")


def stop_wins(policy_id: str) -> bool:
    if policy_id == CONSERVATIVE_SAME_BAR_POLICY_ID:
        return True
    if policy_id == TARGET_FIRST_SAME_BAR_POLICY_ID:
        return False
    raise BacktestContractError(f"unsupported same-bar policy={policy_id}")
