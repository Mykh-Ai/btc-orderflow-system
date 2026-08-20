from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Any

from .contracts import TradeResult


RESOLVED = {"PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"}


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def build_group_metrics(results: list[TradeResult]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[TradeResult]] = defaultdict(list)
    for result in results:
        groups[(result.replay_mode, result.candidate_group, "side", result.side)].append(result)
        groups[(result.replay_mode, result.candidate_group, "side", "ALL")].append(result)
        groups[(result.replay_mode, result.candidate_group, "session", result.session_label or "UNKNOWN")].append(result)
        groups[(result.replay_mode, result.candidate_group, "feed_quality", result.feed_quality_class or "NO_TRADE")].append(result)
        for field in (
            "weak_peak_le_50",
            "oi_down_60_and_directional_delta_pct_240_lt_0_06",
            "loss_avoidance_conservative_union",
        ):
            value = getattr(result, field)
            groups[(result.replay_mode, result.candidate_group, "shadow_label", f"{field}={value if value is not None else 'UNKNOWN'}")].append(result)
    rows: list[dict[str, Any]] = []
    for (mode, group, dimension_type, dimension_value), items in sorted(groups.items()):
        filled = [item for item in items if item.entry_status == "FILLED"]
        resolved = [item for item in filled if item.lifecycle_class in RESOLVED]
        net_values = [float(item.net_pnl_usdc) for item in filled if item.net_pnl_usdc is not None]
        r_values = [float(item.position_r) for item in filled if item.position_r is not None]
        positive = sum(value for value in net_values if value > 0)
        negative = -sum(value for value in net_values if value < 0)
        holding_minutes = [
            (item.exit_ts - item.entry_fill_ts).total_seconds() / 60.0
            for item in resolved
            if item.exit_ts is not None and item.entry_fill_ts is not None
        ]
        strict_wins = sum(1 for value in net_values if value > 0)
        utility_wins = sum(1 for item in resolved if item.utility_bucket == "PROTECTED_WINNER")
        rows.append(
            {
                "replay_mode": mode,
                "candidate_group": group,
                "dimension_type": dimension_type,
                "dimension_value": dimension_value,
                "side": dimension_value if dimension_type == "side" else "ALL",
                "total_candidates": len(items),
                "valid_execution_plans": sum(1 for item in items if item.entry_status not in {"INVALID", "BLOCKED"}),
                "filled_count": len(filled),
                "entry_fill_rate": len(filled) / len(items) if items else None,
                "no_fill_count": sum(1 for item in items if item.lifecycle_class == "NO_FILL"),
                "resolved_count": len(resolved),
                "unresolved_count": sum(1 for item in filled if item.lifecycle_class not in RESOLVED),
                "plain_sl_count": sum(1 for item in resolved if item.lifecycle_class == "PLAIN_SL"),
                "plain_sl_rate": sum(1 for item in resolved if item.lifecycle_class == "PLAIN_SL") / len(resolved) if resolved else None,
                "tp1_sl_count": sum(1 for item in resolved if item.lifecycle_class == "TP1_SL"),
                "tp1_sl_rate": sum(1 for item in resolved if item.lifecycle_class == "TP1_SL") / len(resolved) if resolved else None,
                "protected_winner_count": sum(1 for item in resolved if item.lifecycle_class == "TP1_TP2_TRAILING_STOP"),
                "protected_winner_rate": sum(1 for item in resolved if item.lifecycle_class == "TP1_TP2_TRAILING_STOP") / len(resolved) if resolved else None,
                "gross_pnl_usdc_sum": sum(float(item.gross_pnl_usdc or 0.0) for item in filled),
                "net_pnl_usdc_sum": sum(net_values),
                "mean_net_pnl_usdc": _safe_mean(net_values),
                "median_net_pnl_usdc": _safe_median(net_values),
                "expectancy_per_filled_trade": _safe_mean(net_values),
                "strict_net_win_count": strict_wins,
                "strict_net_win_rate": strict_wins / len(filled) if filled else None,
                "utility_win_count": utility_wins,
                "utility_win_rate": utility_wins / len(resolved) if resolved else None,
                "profit_factor": positive / negative if negative > 0 else None,
                "average_r": _safe_mean(r_values),
                "median_r": _safe_median(r_values),
                "average_holding_minutes": _safe_mean(holding_minutes),
                "same_bar_ambiguous_count": sum(1 for item in filled if item.same_bar_ambiguous),
                "same_bar_ambiguous_share": sum(1 for item in filled if item.same_bar_ambiguous) / len(filled) if filled else None,
                "recovery_overlap_count": sum(1 for item in filled if item.recovery_overlap),
                "blocked_count": sum(1 for item in items if item.entry_status == "BLOCKED"),
            }
        )
    return rows


def build_equity_and_drawdown(results: list[TradeResult]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    closed = sorted(
        [item for item in results if item.replay_mode == "executor_portfolio" and item.exit_ts is not None and item.net_pnl_usdc is not None],
        key=lambda item: (item.exit_ts, item.trade_id),
    )
    equity = 0.0
    peak = 0.0
    equity_rows: list[dict[str, Any]] = []
    drawdown_rows: list[dict[str, Any]] = []
    for item in closed:
        equity += float(item.net_pnl_usdc)
        peak = max(peak, equity)
        drawdown = peak - equity
        equity_rows.append(
            {
                "exit_ts": item.exit_ts.isoformat(),
                "trade_id": item.trade_id,
                "net_pnl_usdc": item.net_pnl_usdc,
                "cumulative_net_pnl_usdc": equity,
            }
        )
        drawdown_rows.append(
            {
                "exit_ts": item.exit_ts.isoformat(),
                "trade_id": item.trade_id,
                "equity_peak_usdc": peak,
                "equity_usdc": equity,
                "drawdown_usdc": drawdown,
            }
        )
    return equity_rows, drawdown_rows


def build_portfolio_metrics(
    results: list[TradeResult],
    opportunities: list[dict[str, Any]],
    drawdown_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked = [item for item in results if item.entry_status == "BLOCKED"]
    position_lock_blocked = [item for item in blocked if item.blocked_reason in {"POSITION_ALREADY_OPEN", "POSITION_PENDING_ENTRY", "COOLDOWN_ACTIVE"}]
    no_feed_blocked = [item for item in blocked if item.blocked_reason == "NO_FEED_COVERAGE"]
    evaluable = [row for row in opportunities if row.get("opportunity_cost_evaluable") is True]
    return [
        {
            "total_candidates": len(results),
            "executed_filled_count": sum(1 for item in results if item.entry_status == "FILLED"),
            "position_lock_blocked_count": len(position_lock_blocked),
            "no_feed_coverage_blocked_count": len(no_feed_blocked),
            "portfolio_state_unknown_from": min((item.signal_ts_utc for item in no_feed_blocked), default=None).isoformat() if no_feed_blocked else "",
            "concurrent_signal_pressure_share": len(position_lock_blocked) / len(results) if results else None,
            "blocked_tp1_opportunity_count": sum(1 for row in evaluable if row.get("blocked_reached_tp1")),
            "blocked_tp2_opportunity_count": sum(1 for row in evaluable if row.get("blocked_reached_tp2")),
            "net_opportunity_cost_usdc": sum(float(row.get("fixed_notional_pnl_difference") or 0.0) for row in evaluable),
            "blocked_outperformed_active_count": sum(1 for row in evaluable if row.get("blocked_outperformed_active") is True),
            "r_pnl_ranking_disagreement_count": sum(1 for row in evaluable if row.get("r_pnl_ranking_disagrees") is True),
            "max_drawdown_usdc": max((float(row["drawdown_usdc"]) for row in drawdown_rows), default=0.0),
        }
    ]
