from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .contracts import Candidate, TradeResult


RESOLVED = {"PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"}
COMPONENTS = {
    "component_a_weak_peak_le_50": "weak_peak_le_50",
    "component_b_oi_down_60_and_weak_240m_flow": "oi_down_60_and_directional_delta_pct_240_lt_0_06",
    "conservative_union": "loss_avoidance_conservative_union",
}


def _outcome_class(result: TradeResult) -> str:
    if result.entry_status != "FILLED":
        return "NOT_FILLED"
    if result.lifecycle_class in RESOLVED:
        return result.lifecycle_class
    return "UNRESOLVED_FILLED"


def _aggregate(
    items: list[tuple[Candidate, TradeResult]],
    *,
    candidate_group: str,
    cohort: str,
    blocked_candidates: int,
    blocked_fills: int,
) -> dict[str, Any]:
    results = [result for _, result in items]
    filled = [result for result in results if result.entry_status == "FILLED"]
    resolved = [result for result in filled if result.lifecycle_class in RESOLVED]
    gross_values = [float(result.gross_pnl_usdc) for result in filled if result.gross_pnl_usdc is not None]
    net_values = [float(result.net_pnl_usdc) for result in filled if result.net_pnl_usdc is not None]
    return {
        "candidate_group": candidate_group,
        "cohort": cohort,
        "candidate_count": len(items),
        "filled_count": len(filled),
        "fill_rate": len(filled) / len(items) if items else None,
        "resolved_count": len(resolved),
        "resolved_rate_per_fill": len(resolved) / len(filled) if filled else None,
        "plain_sl_count": sum(result.lifecycle_class == "PLAIN_SL" for result in resolved),
        "plain_sl_rate_per_resolved": sum(result.lifecycle_class == "PLAIN_SL" for result in resolved) / len(resolved) if resolved else None,
        "tp1_sl_count": sum(result.lifecycle_class == "TP1_SL" for result in resolved),
        "tp1_sl_rate_per_resolved": sum(result.lifecycle_class == "TP1_SL" for result in resolved) / len(resolved) if resolved else None,
        "protected_count": sum(result.lifecycle_class == "TP1_TP2_TRAILING_STOP" for result in resolved),
        "protected_rate_per_resolved": sum(result.lifecycle_class == "TP1_TP2_TRAILING_STOP" for result in resolved) / len(resolved) if resolved else None,
        "unresolved_filled_count": len(filled) - len(resolved),
        "gross_pnl_usdc_sum": sum(gross_values),
        "net_pnl_usdc_sum": sum(net_values),
        "expectancy_per_fill_usdc": sum(net_values) / len(filled) if filled else None,
        "pnl_known_filled_count": len(net_values),
        "filter_blocked_candidate_count": blocked_candidates,
        "filter_blocked_filled_count": blocked_fills,
    }


def build_loss_avoidance_artifacts(
    candidates: Iterable[Candidate],
    independent: Iterable[TradeResult],
    *,
    parity_rows: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    parity_by_candidate = {
        str(row.get("candidate_id") or ""): row
        for row in parity_rows
        if str(row.get("candidate_id") or "")
    }
    pairs: list[tuple[Candidate, TradeResult]] = []
    detail_rows: list[dict[str, Any]] = []
    for result in independent:
        candidate = candidate_by_id[result.candidate_id]
        flags = candidate.shadow_flags
        union = flags.get("loss_avoidance_conservative_union")
        decision = "BLOCKED" if union is True else "KEPT_UNKNOWN" if union is None else "KEPT"
        parity = parity_by_candidate.get(candidate.candidate_id, {})
        pairs.append((candidate, result))
        detail_rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_group": candidate.candidate_group,
                "signal_ts_utc": candidate.signal_ts_utc.isoformat(),
                "side": candidate.side,
                "counterfactual_decision": decision,
                "component_a": flags.get("weak_peak_le_50"),
                "component_b": flags.get("oi_down_60_and_directional_delta_pct_240_lt_0_06"),
                "conservative_union": union,
                "same_side_peak_count_24h": flags.get("same_side_peak_count_24h"),
                "same_side_peak_percentile_24h": flags.get("same_side_peak_percentile_24h"),
                "oi_change_60m": flags.get("oi_change_60m"),
                "oi_trusted_60m": flags.get("oi_trusted_60m"),
                "directional_delta_pct_240m": flags.get("directional_delta_pct_240m"),
                "directional_delta_240m_available": flags.get("directional_delta_240m_available"),
                "baseline_entry_status": result.entry_status,
                "baseline_lifecycle": result.lifecycle_class,
                "baseline_gross_pnl_usdc": result.gross_pnl_usdc,
                "baseline_net_pnl_usdc": result.net_pnl_usdc,
                "operational_trade_key": parity.get("trade_key"),
                "operational_parity_join_status": parity.get("candidate_join_status"),
                "operational_record_source": parity.get("operational_record_source"),
                "operational_excluded_from_scoring": parity.get("excluded_from_scoring"),
                "operational_lifecycle": parity.get("operational_lifecycle"),
                "operational_lifecycle_match": parity.get("lifecycle_match"),
                "parity_entry_plan_match": parity.get("entry_plan_match"),
                "parity_stop_plan_difference_usd": parity.get("stop_plan_difference_usd"),
                "parity_tp1_difference_usd": parity.get("tp1_difference_usd"),
                "parity_tp2_difference_usd": parity.get("tp2_difference_usd"),
                "parity_mismatch_reason": parity.get("mismatch_reason"),
            }
        )

    by_group: dict[str, list[tuple[Candidate, TradeResult]]] = defaultdict(list)
    for pair in pairs:
        by_group[pair[0].candidate_group].append(pair)
    metric_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for group, group_items in sorted(by_group.items()):
        blocked = [pair for pair in group_items if pair[0].shadow_flags.get("loss_avoidance_conservative_union") is True]
        kept = [pair for pair in group_items if pair[0].shadow_flags.get("loss_avoidance_conservative_union") is not True]
        blocked_fills = sum(result.entry_status == "FILLED" for _, result in blocked)
        metric_rows.extend(
            [
                _aggregate(group_items, candidate_group=group, cohort="BASELINE_BEFORE_FILTER", blocked_candidates=len(blocked), blocked_fills=blocked_fills),
                _aggregate(kept, candidate_group=group, cohort="COUNTERFACTUAL_AFTER_FILTER", blocked_candidates=len(blocked), blocked_fills=blocked_fills),
                _aggregate(blocked, candidate_group=group, cohort="BLOCKED_BY_FILTER", blocked_candidates=len(blocked), blocked_fills=blocked_fills),
            ]
        )
        outcome_groups: dict[str, list[tuple[Candidate, TradeResult]]] = {"ALL_CANDIDATES": group_items}
        for outcome in ("NOT_FILLED", "UNRESOLVED_FILLED", "PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"):
            outcome_groups[outcome] = [pair for pair in group_items if _outcome_class(pair[1]) == outcome]
        for outcome, outcome_items in outcome_groups.items():
            for component_name, flag_name in COMPONENTS.items():
                values = [candidate.shadow_flags.get(flag_name) for candidate, _ in outcome_items]
                known = [value for value in values if value is not None]
                matched = sum(value is True for value in values)
                coverage_rows.append(
                    {
                        "candidate_group": group,
                        "outcome_class": outcome,
                        "component": component_name,
                        "denominator_count": len(outcome_items),
                        "known_count": len(known),
                        "unknown_count": len(outcome_items) - len(known),
                        "matched_true_count": matched,
                        "matched_rate_per_outcome": matched / len(outcome_items) if outcome_items else None,
                        "matched_rate_per_known": matched / len(known) if known else None,
                        "oi_untrusted_count": sum(
                            candidate.shadow_flags.get("oi_trusted_60m") is not True
                            for candidate, _ in outcome_items
                        ),
                        "directional_240m_unknown_count": sum(
                            candidate.shadow_flags.get("directional_delta_pct_240m") is None
                            for candidate, _ in outcome_items
                        ),
                    }
                )
    return detail_rows, metric_rows, coverage_rows


def _rate(count: int, denominator: int) -> str:
    return f"{count}/{denominator} ({count / denominator * 100:.1f}%)" if denominator else "0/0 (n/a)"


def _number_text(value: Any) -> str:
    return f"{float(value):.2f}" if value is not None else "n/a"


def write_loss_avoidance_summary(
    path: Path,
    *,
    metrics: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    details: list[dict[str, Any]],
) -> Path:
    rows = {(row["candidate_group"], row["cohort"]): row for row in metrics}
    lines = [
        "# Conservative Loss-Avoidance Counterfactual",
        "",
        "Frozen shadow rule: block when component A OR component B is true. Component A is same-side delta-candidate percentile `<=50` over the source-of-truth 24h cutoff window. Component B is trusted `oi_change_60m < 0` AND direction-adjusted `buy_sell_delta_pct_240m < 0.06`. Unknown/untrusted values are kept, never blocked automatically. `oi_change_240m` is not used.",
        "",
        "## Before / after",
        "",
        "| Group | Cohort | Candidates | Filled | Resolved | Plain SL | TP1->SL | Protected | Gross PnL | Net PnL | Expectancy/fill | Blocked candidates/fills |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group in sorted({key[0] for key in rows}):
        for cohort in ("BASELINE_BEFORE_FILTER", "COUNTERFACTUAL_AFTER_FILTER", "BLOCKED_BY_FILTER"):
            row = rows[(group, cohort)]
            expectancy = (
                f"{row['expectancy_per_fill_usdc']:.2f}"
                if row["expectancy_per_fill_usdc"] is not None
                else "n/a"
            )
            lines.append(
                f"| `{group}` | `{cohort}` | {row['candidate_count']} | {row['filled_count']} | {row['resolved_count']} | "
                f"{row['plain_sl_count']} | {row['tp1_sl_count']} | {row['protected_count']} | "
                f"{row['gross_pnl_usdc_sum']:.2f} | {row['net_pnl_usdc_sum']:.2f} | {expectancy} | "
                f"{row['filter_blocked_candidate_count']}/{row['filter_blocked_filled_count']} |"
            )
    lines.extend(
        [
            "",
            "## Outcome protection guardrail",
            "",
            "| Group | Component | Plain SL blocked | TP1->SL blocked | Protected blocked | Unknown among all candidates |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    coverage_index = {
        (row["candidate_group"], row["component"], row["outcome_class"]): row
        for row in coverage
    }
    for group in sorted({row["candidate_group"] for row in coverage}):
        for component in COMPONENTS:
            plain = coverage_index[(group, component, "PLAIN_SL")]
            scratch = coverage_index[(group, component, "TP1_SL")]
            protected = coverage_index[(group, component, "TP1_TP2_TRAILING_STOP")]
            all_rows = coverage_index[(group, component, "ALL_CANDIDATES")]
            lines.append(
                f"| `{group}` | `{component}` | {_rate(plain['matched_true_count'], plain['denominator_count'])} | "
                f"{_rate(scratch['matched_true_count'], scratch['denominator_count'])} | "
                f"{_rate(protected['matched_true_count'], protected['denominator_count'])} | "
                f"{all_rows['unknown_count']}/{all_rows['denominator_count']} |"
            )
    lines.extend(
        [
            "",
            "## Unknown and untrusted coverage",
            "",
            "| Group | Component B known | Component B unknown | OI untrusted | 240m directional flow unknown | Union unknown (kept) |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for group in sorted({row["candidate_group"] for row in coverage}):
        component_b = coverage_index[(group, "component_b_oi_down_60_and_weak_240m_flow", "ALL_CANDIDATES")]
        union = coverage_index[(group, "conservative_union", "ALL_CANDIDATES")]
        lines.append(
            f"| `{group}` | {component_b['known_count']}/{component_b['denominator_count']} | "
            f"{component_b['unknown_count']}/{component_b['denominator_count']} | "
            f"{component_b['oi_untrusted_count']}/{component_b['denominator_count']} | "
            f"{component_b['directional_240m_unknown_count']}/{component_b['denominator_count']} | "
            f"{union['unknown_count']}/{union['denominator_count']} |"
        )

    peak_filled = [
        row
        for row in details
        if row.get("candidate_group") == "PEAK_EMIT_BASELINE"
        and row.get("baseline_entry_status") == "FILLED"
    ]
    lines.extend(
        [
            "",
            "## PEAK component comparison on corrected replay",
            "",
            "Unknown component values are kept. Net PnL and expectancy refer to the replay cohort left after applying that component alone.",
            "",
            "| Component | Blocked fills | Blocked Plain/TP1->SL/Protected | Kept fills | Kept net PnL | Kept expectancy/fill |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for component_name in COMPONENTS:
        if component_name == "component_a_weak_peak_le_50":
            blocked = [row for row in peak_filled if row.get("component_a") is True]
        elif component_name == "component_b_oi_down_60_and_weak_240m_flow":
            blocked = [row for row in peak_filled if row.get("component_b") is True]
        else:
            blocked = [row for row in peak_filled if row.get("conservative_union") is True]
        kept = [row for row in peak_filled if row not in blocked]
        kept_net = sum(float(row["baseline_net_pnl_usdc"]) for row in kept if row.get("baseline_net_pnl_usdc") is not None)
        kept_expectancy = f"{kept_net / len(kept):.2f}" if kept else "n/a"
        lines.append(
            f"| `{component_name}` | {len(blocked)} | "
            f"{sum(row.get('baseline_lifecycle') == 'PLAIN_SL' for row in blocked)}/"
            f"{sum(row.get('baseline_lifecycle') == 'TP1_SL' for row in blocked)}/"
            f"{sum(row.get('baseline_lifecycle') == 'TP1_TP2_TRAILING_STOP' for row in blocked)} | "
            f"{len(kept)} | {kept_net:.2f} | {kept_expectancy} |"
        )

    operational_peak = [
        row
        for row in details
        if row.get("candidate_group") == "PEAK_EMIT_BASELINE"
        and row.get("operational_parity_join_status") == "MATCHED"
        and row.get("operational_excluded_from_scoring") is not True
        and row.get("operational_lifecycle") in RESOLVED
    ]
    lines.extend(
        [
            "",
            "## Operational PEAK guardrail",
            "",
            "This table uses comparable, non-test operational outcomes and the same cutoff-safe candidate flags. Operational labels are not overwritten by replay labels.",
            "",
            "| Component | Comparable operational trades | Plain SL blocked | TP1->SL blocked | Protected blocked |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for component_name, _ in COMPONENTS.items():
        if component_name == "component_a_weak_peak_le_50":
            flag_field = "component_a"
        elif component_name == "component_b_oi_down_60_and_weak_240m_flow":
            flag_field = "component_b"
        else:
            flag_field = "conservative_union"
        lines.append(
            f"| `{component_name}` | {len(operational_peak)} | "
            f"{sum(row.get(flag_field) is True and row.get('operational_lifecycle') == 'PLAIN_SL' for row in operational_peak)}/"
            f"{sum(row.get('operational_lifecycle') == 'PLAIN_SL' for row in operational_peak)} | "
            f"{sum(row.get(flag_field) is True and row.get('operational_lifecycle') == 'TP1_SL' for row in operational_peak)}/"
            f"{sum(row.get('operational_lifecycle') == 'TP1_SL' for row in operational_peak)} | "
            f"{sum(row.get(flag_field) is True and row.get('operational_lifecycle') == 'TP1_TP2_TRAILING_STOP' for row in operational_peak)}/"
            f"{sum(row.get('operational_lifecycle') == 'TP1_TP2_TRAILING_STOP' for row in operational_peak)} |"
        )
    lines.extend(
        [
            "",
            "Replay lifecycle mismatch against these operational outcomes: "
            + ", ".join(
                f"`{outcome}` "
                f"{sum(row.get('baseline_lifecycle') != outcome for row in operational_peak if row.get('operational_lifecycle') == outcome)}/"
                f"{sum(row.get('operational_lifecycle') == outcome for row in operational_peak)}"
                for outcome in ("PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP")
            )
            + ".",
        ]
    )
    replay_protected_blocked = [
        row
        for row in details
        if row.get("counterfactual_decision") == "BLOCKED"
        and row.get("baseline_lifecycle") == "TP1_TP2_TRAILING_STOP"
    ]
    lines.extend(
        [
            "",
            "## Every replay-protected blocked case and operational parity",
            "",
            "Replay protected outcomes remain the conservative denominator above. A joined operational lifecycle is reported separately and does not rewrite replay results.",
            "",
            "| Candidate | Group | Parity join | Join source | Replay lifecycle | Operational trade | Operational lifecycle | Entry match | SL/TP1/TP2 plan delta | Classification |",
            "|---|---|---|---|---|---|---|---|---:|---|",
        ]
    )
    for row in replay_protected_blocked:
        lines.append(
            f"| `{row['candidate_id']}` | `{row['candidate_group']}` | `{row['operational_parity_join_status'] or 'UNMATCHED'}` | "
            f"`{row['operational_record_source'] or ''}` | "
            f"`{row['baseline_lifecycle']}` | `{row['operational_trade_key']}` | `{row['operational_lifecycle']}` | "
            f"`{row['parity_entry_plan_match']}` | "
            f"{_number_text(row['parity_stop_plan_difference_usd'])}/{_number_text(row['parity_tp1_difference_usd'])}/{_number_text(row['parity_tp2_difference_usd'])} | "
            f"`{row['parity_mismatch_reason']}` |"
        )
    if not replay_protected_blocked:
        lines.append("| n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | No replay-protected blocked cases |")
    april_23 = next((row for row in details if row.get("candidate_id") == "SCOUT_2eb9fce285ba04239e3b"), None)
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- TP1->SL is treated as scratch-neutral; blocking it is not the main guardrail failure.",
            "- Blocking a `TP1_TP2_TRAILING_STOP` is the critical false positive and must be reported explicitly.",
            "- The rule was discovered on accepted PEAK lifecycle evidence. Applying it to ALMOST 2/3 is a domain-transfer test, not validation of the rule for that cohort.",
            "- The earlier single-feed `v5` run used BTCUSDT Futures OHLC as an execution proxy and is superseded for lifecycle and expectancy conclusions by this dual-feed run.",
            (
                f"- Targeted `2026-04-23` regression: filter=`{april_23.get('counterfactual_decision')}`, "
                f"replay lifecycle=`{april_23.get('baseline_lifecycle')}`, operational lifecycle=`{april_23.get('operational_lifecycle')}`."
                if april_23
                else "- Targeted `2026-04-23` candidate is absent from this cohort and requires audit."
            ),
            "- This is an independent-opportunity counterfactual. It does not re-sequence the one-position portfolio after removing signals.",
            "- No live admission logic is changed by this report.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
