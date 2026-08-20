from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ReplayConfig, TradeResult


def _rate(count: int, denominator: int) -> str:
    return f"{count}/{denominator} ({count / denominator * 100:.1f}%)" if denominator else "0/0 (n/a)"


def write_summary(
    path: Path,
    *,
    config: ReplayConfig,
    date_from: str,
    date_to: str,
    candidates: int,
    independent: list[TradeResult],
    portfolio: list[TradeResult],
    parity_rows: list[dict[str, Any]],
    feed_quality_counts: dict[str, int],
    opportunity_rows: list[dict[str, Any]],
) -> Path:
    filled = [item for item in independent if item.entry_status == "FILLED"]
    resolved = [item for item in filled if item.lifecycle_class in {"PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"}]
    plain = sum(1 for item in resolved if item.lifecycle_class == "PLAIN_SL")
    scratch = sum(1 for item in resolved if item.lifecycle_class == "TP1_SL")
    protected = sum(1 for item in resolved if item.lifecycle_class == "TP1_TP2_TRAILING_STOP")
    ambiguous = sum(1 for item in filled if item.same_bar_ambiguous)
    sensitivity_changes = sum(1 for item in filled if item.outcome_changes_under_sensitivity is True)
    blocked = [item for item in portfolio if item.entry_status == "BLOCKED" and item.blocked_reason in {"POSITION_ALREADY_OPEN", "POSITION_PENDING_ENTRY", "COOLDOWN_ACTIVE"}]
    no_feed_blocked = [item for item in portfolio if item.entry_status == "BLOCKED" and item.blocked_reason == "NO_FEED_COVERAGE"]
    evaluable_opportunities = [row for row in opportunity_rows if row.get("opportunity_cost_evaluable") is True]
    parity_comparable = [row for row in parity_rows if not row["excluded_from_scoring"] and row["candidate_join_status"] == "MATCHED" and row["lifecycle_match"] is not None]
    parity_matches = sum(1 for row in parity_comparable if row["lifecycle_match"])
    planning_comparable = [row for row in parity_comparable if row["entry_plan_match"] is not None]
    planning_matches = sum(1 for row in planning_comparable if row["entry_plan_match"])
    protected_to_plain = sum(1 for row in parity_comparable if row["operational_lifecycle"] == "TP1_TP2_TRAILING_STOP" and row["replay_lifecycle"] == "PLAIN_SL")
    parity_status = (
        "PARITY_VALIDATED"
        if len(parity_comparable) and parity_matches / len(parity_comparable) >= 0.9 and protected_to_plain == 0 and planning_matches == len(planning_comparable)
        else "LIFECYCLE_THRESHOLD_MET_PLANNING_AUDIT_REQUIRED"
        if len(parity_comparable) and parity_matches / len(parity_comparable) >= 0.9 and protected_to_plain == 0
        else "PARITY_AUDIT_REQUIRED"
    )
    net = sum(float(item.net_pnl_usdc or 0.0) for item in filled)
    zero_slippage_net = sum(float(item.gross_pnl_usdc or 0.0) - float(item.commission_usdc or 0.0) for item in filled)
    lines = [
        "# DeltaScout Scout Replay Backtester Summary",
        "",
        "## Scope and contracts",
        "",
        f"- Experiment: `{config.experiment_id}`",
        f"- Candidate range: `{date_from}` through `{date_to}`",
        f"- Execution policy: `{config.execution_policy_id}`",
        f"- Fill model: `{config.fill_model_id}`",
        f"- Same-bar baseline: `{config.same_bar_policy_id}`",
        f"- Cost model: `{config.cost_model_id}`; commission rate `{config.commission_rate:.6%}`",
        f"- Slippage: entry `{config.entry_slippage_bps}` bps, exit `{config.exit_slippage_bps}` bps, stop `{config.stop_slippage_bps}` bps",
        f"- Conversion: `{config.conversion_model_id}`",
        "",
        "## Cohort and lifecycle",
        "",
        f"- Candidates: {candidates}",
        f"- Filled independent opportunities: {_rate(len(filled), candidates)}",
        f"- Resolved: {_rate(len(resolved), len(filled))}",
        f"- Plain stops: {_rate(plain, len(resolved))}",
        f"- TP1 scratches: {_rate(scratch, len(resolved))}",
        f"- TP1+TP2 protected outcomes: {_rate(protected, len(resolved))}",
        f"- Same-bar ambiguous: {_rate(ambiguous, len(filled))}",
        f"- Lifecycle changes under target-first sensitivity: {_rate(sensitivity_changes, len(filled))}",
        f"- Independent fixed-notional net PnL: `{net:.2f} USDC`",
        f"- Zero-slippage diagnostic net PnL: `{zero_slippage_net:.2f} USDC`",
        "",
        "## Portfolio position lock",
        "",
        f"- Blocked candidates: {_rate(len(blocked), len(portfolio))}",
        f"- Portfolio rows excluded after loss of feed state: {_rate(len(no_feed_blocked), len(portfolio))}",
        f"- Blocked candidates outperforming active trade: {sum(1 for row in evaluable_opportunities if row.get('blocked_outperformed_active') is True)}/{len(evaluable_opportunities)}",
        "",
        "## Feed quality",
        "",
    ]
    lines.extend(f"- `{name}`: {count}" for name, count in feed_quality_counts.items())
    lines.extend(
        [
            "",
            "## Candidate-group comparison",
            "",
            "| Group | Candidates | Filled | Plain SL | TP1 scratch | Protected | Net expectancy / fill |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for group in sorted({item.candidate_group for item in independent}):
        group_all = [item for item in independent if item.candidate_group == group]
        group_filled = [item for item in group_all if item.entry_status == "FILLED"]
        group_resolved = [item for item in group_filled if item.lifecycle_class in {"PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"}]
        group_net = sum(float(item.net_pnl_usdc or 0.0) for item in group_filled)
        lines.append(
            f"| `{group}` | {len(group_all)} | {_rate(len(group_filled), len(group_all))} | "
            f"{_rate(sum(1 for item in group_resolved if item.lifecycle_class == 'PLAIN_SL'), len(group_resolved))} | "
            f"{_rate(sum(1 for item in group_resolved if item.lifecycle_class == 'TP1_SL'), len(group_resolved))} | "
            f"{_rate(sum(1 for item in group_resolved if item.lifecycle_class == 'TP1_TP2_TRAILING_STOP'), len(group_resolved))} | "
            f"{group_net / len(group_filled):.2f} USDC |"
        )
    lines.extend(
        [
            "",
            "## Shadow loss-avoidance labels",
            "",
            "| Label | Known filled | Matched plain stops | Matched protected winners |",
            "|---|---:|---:|---:|",
        ]
    )
    for field in (
        "weak_peak_le_50",
        "oi_down_60_and_directional_delta_pct_240_lt_0_06",
        "loss_avoidance_conservative_union",
    ):
        known = [item for item in filled if getattr(item, field) is not None]
        matched_plain = sum(1 for item in known if getattr(item, field) is True and item.lifecycle_class == "PLAIN_SL")
        matched_protected = sum(1 for item in known if getattr(item, field) is True and item.lifecycle_class == "TP1_TP2_TRAILING_STOP")
        lines.append(f"| `{field}` | {len(known)}/{len(filled)} | {matched_plain}/{plain} | {matched_protected}/{protected} |")
    lines.extend(
        [
            "",
            "## Executor parity",
            "",
            f"- Comparable lifecycle matches: {_rate(parity_matches, len(parity_comparable))}",
            f"- Comparable entry-plan matches: {_rate(planning_matches, len(planning_comparable))}",
            f"- Operational protected winners replayed as plain stops: {protected_to_plain}/{len(parity_comparable)}",
            f"- Policy status: `{parity_status}`",
            f"- Total operational records: {len(parity_rows)}",
            "- Planning parity and exchange-fill parity remain separate; unmatched and excluded rows are retained in `parity_report.csv`.",
            "",
            "## Limitations",
            "",
            "- One-minute OHLC cannot prove intrabar event order; conservative baseline and target-first sensitivity are reported separately.",
            "- Signal/reference and execution symbols use the declared 1:1 USDT/USDC approximation.",
            "- Borrow interest is unavailable and is not treated as observed zero.",
            "- Recovered rows support price/volume/delta replay, while funding and liquidation evidence remain degraded in the documented gap.",
            "- This is offline research/shadow evidence. It is not a live-promotion or market-edge claim.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
