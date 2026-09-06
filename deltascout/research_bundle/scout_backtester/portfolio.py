from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from typing import Any

from .contracts import Candidate, ReplayConfig, ReplayEvent, TradeResult
from .replay_engine import clone_for_mode


def _portfolio_trade_id(candidate_id: str, config: ReplayConfig) -> str:
    payload = f"{config.experiment_id}|{candidate_id}|executor_portfolio|{config.same_bar_policy_id}"
    return "TR_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _blocked_copy(
    independent: TradeResult,
    config: ReplayConfig,
    reason: str,
    active_trade_id: str,
) -> TradeResult:
    result = clone_for_mode(independent, "executor_portfolio", _portfolio_trade_id(independent.candidate_id, config))
    result.entry_status = "BLOCKED"
    result.entry_fill_ts = None
    result.exit_ts = None
    result.lifecycle_class = "NO_TRADE"
    result.utility_bucket = "NO_TRADE"
    result.gross_pnl_usdc = 0.0
    result.commission_usdc = 0.0
    result.slippage_usdc = 0.0
    result.net_pnl_usdc = 0.0
    result.position_r = None
    result.blocked_reason = reason
    result.active_trade_id_when_blocked = active_trade_id
    result.feed_quality_class = ""
    result.recovery_overlap = False
    result.legs = []
    return result


def replay_portfolio(
    candidates: list[Candidate],
    independent_results: list[TradeResult],
    config: ReplayConfig,
    independent_events: list[ReplayEvent] | None = None,
) -> tuple[list[TradeResult], list[ReplayEvent], list[dict[str, Any]]]:
    independent_by_id = {result.candidate_id: result for result in independent_results}
    events_by_candidate: dict[str, list[ReplayEvent]] = {}
    for replay_event in independent_events or []:
        events_by_candidate.setdefault(replay_event.candidate_id, []).append(replay_event)
    results: list[TradeResult] = []
    events: list[ReplayEvent] = []
    opportunities: list[dict[str, Any]] = []
    active: TradeResult | None = None
    cooldown_until = None
    portfolio_unknown_from = None

    for candidate in sorted(candidates, key=lambda item: (item.signal_ts_utc, item.candidate_id)):
        independent = independent_by_id[candidate.candidate_id]
        now = candidate.signal_ts_utc
        reason = ""
        active_id = ""

        if portfolio_unknown_from is not None and now >= portfolio_unknown_from:
            reason = "NO_FEED_COVERAGE"
            active_id = active.trade_id if active else ""
        elif active is not None:
            pending_until = active.entry_fill_ts or active.entry_expiry_ts
            if active.entry_status in {"NO_FILL", "ABORTED"} and pending_until is not None and now > pending_until:
                active = None
            elif active.exit_ts is not None and now > active.exit_ts:
                cooldown_until = active.exit_ts + timedelta(seconds=config.cooldown_seconds)
                active = None
            elif active.entry_fill_ts is None or now < active.entry_fill_ts:
                reason = "POSITION_PENDING_ENTRY"
                active_id = active.trade_id
            else:
                reason = "POSITION_ALREADY_OPEN"
                active_id = active.trade_id

        if not reason and cooldown_until is not None and now <= cooldown_until:
            reason = "COOLDOWN_ACTIVE"

        if reason:
            blocked = _blocked_copy(independent, config, reason, active_id)
            results.append(blocked)
            events.append(
                ReplayEvent(
                    event_ts=now,
                    event_type="CANDIDATE_BLOCKED",
                    trade_id=blocked.trade_id,
                    candidate_id=blocked.candidate_id,
                    replay_mode="executor_portfolio",
                    payload={"reason": reason, "active_trade_id": active_id},
                )
            )
            active_result = next((item for item in results if item.trade_id == active_id), None)
            r_difference = (
                float(independent.position_r) - float(active_result.position_r)
                if active_result and independent.position_r is not None and active_result.position_r is not None
                else None
            )
            pnl_difference = (
                float(independent.net_pnl_usdc) - float(active_result.net_pnl_usdc)
                if active_result and independent.net_pnl_usdc is not None and active_result.net_pnl_usdc is not None
                else None
            )
            evaluable = reason != "NO_FEED_COVERAGE"
            opportunities.append(
                {
                    "blocked_trade_id": blocked.trade_id,
                    "candidate_id": candidate.candidate_id,
                    "blocked_reason": reason,
                    "active_trade_id": active_id,
                    "blocked_independent_lifecycle": independent.lifecycle_class,
                    "blocked_independent_gross_pnl_usdc": independent.gross_pnl_usdc,
                    "blocked_independent_net_pnl_usdc": independent.net_pnl_usdc,
                    "blocked_independent_position_r": independent.position_r,
                    "blocked_reached_tp1": bool(independent.tp1_fill_ts),
                    "blocked_reached_tp2": bool(independent.tp2_fill_ts),
                    "opportunity_cost_evaluable": evaluable,
                    "active_lifecycle": active_result.lifecycle_class if active_result and evaluable else "",
                    "active_net_pnl_usdc": active_result.net_pnl_usdc if active_result and evaluable else None,
                    "active_position_r": active_result.position_r if active_result and evaluable else None,
                    "entry_improvement_usd": (
                        abs(float(active_result.entry_fill_price) - float(independent.entry_fill_price))
                        if active_result and evaluable and active_result.entry_fill_price is not None and independent.entry_fill_price is not None
                        else None
                    ),
                    "entry_improvement_pct": (
                        abs(float(active_result.entry_fill_price) - float(independent.entry_fill_price)) / float(active_result.entry_fill_price) * 100.0
                        if active_result and evaluable and active_result.entry_fill_price and independent.entry_fill_price is not None
                        else None
                    ),
                    "normalized_r_difference": r_difference if evaluable else None,
                    "fixed_notional_pnl_difference": pnl_difference if evaluable else None,
                    "r_pnl_ranking_disagrees": (
                        bool((r_difference > 0) != (pnl_difference > 0))
                        if evaluable and r_difference not in (None, 0.0) and pnl_difference not in (None, 0.0)
                        else False
                    ),
                    "blocked_outperformed_active": (
                        bool(float(independent.net_pnl_usdc) > float(active_result.net_pnl_usdc))
                        if active_result and evaluable and independent.net_pnl_usdc is not None and active_result.net_pnl_usdc is not None
                        else None
                    ),
                }
            )
            continue

        accepted = clone_for_mode(independent, "executor_portfolio", _portfolio_trade_id(candidate.candidate_id, config))
        results.append(accepted)
        events.append(
            ReplayEvent(
                event_ts=now,
                event_type="CANDIDATE_SEEN",
                trade_id=accepted.trade_id,
                candidate_id=accepted.candidate_id,
                replay_mode="executor_portfolio",
                payload={"admission": "ACCEPTED"},
            )
        )
        for source_event in events_by_candidate.get(candidate.candidate_id, []):
            if source_event.event_type == "CANDIDATE_SEEN":
                continue
            events.append(
                ReplayEvent(
                    event_ts=source_event.event_ts,
                    event_type=source_event.event_type,
                    trade_id=accepted.trade_id,
                    candidate_id=accepted.candidate_id,
                    replay_mode="executor_portfolio",
                    payload=dict(source_event.payload),
                )
            )
        if accepted.entry_status in {"FILLED", "NO_FILL", "ABORTED"}:
            active = accepted
            if accepted.entry_status == "FILLED" and accepted.data_quality_interruption_ts is not None:
                portfolio_unknown_from = accepted.data_quality_interruption_ts
            if accepted.exit_ts is not None and accepted.exit_ts <= now:
                cooldown_until = accepted.exit_ts + timedelta(seconds=config.cooldown_seconds)
                active = None
        else:
            active = None

    events.sort(key=lambda item: (item.event_ts, item.trade_id, item.event_type))
    return results, events, opportunities
