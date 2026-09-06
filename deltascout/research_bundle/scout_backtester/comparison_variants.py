from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

from .contracts import Candidate, CandidateQualityRow, ReplayConfig, TradeResult
from .ledger import write_csv


DISCOVERY_END_UTC = datetime(2026, 6, 1, tzinfo=timezone.utc)
VARIANTS = (
    "ALMOST_2OF3_PRICE_FAIL",
    "ALMOST_2OF3_VOLUME_FAIL",
    "ALMOST_2OF3_VWAP_FAIL",
)
RESOLVED = {"PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"}
FILTERS = {
    "COMPONENT_A": "weak_peak_le_50",
    "COMPONENT_B": "oi_down_60_and_directional_delta_pct_240_lt_0_06",
    "OVERLAP_A_AND_B": "_overlap",
    "UNION_A_OR_B": "loss_avoidance_conservative_union",
}


def validate_comparison_variants(candidates: Iterable[Candidate]) -> list[CandidateQualityRow]:
    quality: list[CandidateQualityRow] = []
    for candidate in candidates:
        if candidate.candidate_group != "ALMOST_PEAK_2_OF_3":
            continue
        flags = (
            candidate.comparison_price_pass,
            candidate.comparison_vol_pass,
            candidate.comparison_vwap_pass,
        )
        true_count = sum(value is True for value in flags)
        false_count = sum(value is False for value in flags)
        if true_count != 2 or false_count != 1 or candidate.comparison_setup_variant not in VARIANTS:
            quality.append(
                CandidateQualityRow(
                    candidate.source_path,
                    None,
                    "ALMOST_2OF3_VARIANT_INVALID",
                    f"true_count={true_count}; false_count={false_count}; variant={candidate.comparison_setup_variant}",
                    candidate.candidate_id,
                )
            )
    return quality


def _period(candidate: Candidate) -> str:
    return "DISCOVERY" if candidate.signal_ts_utc < DISCOVERY_END_UTC else "VALIDATION"


def _cohorts(candidate: Candidate) -> list[str]:
    if candidate.candidate_group == "PEAK_EMIT_BASELINE":
        return ["PEAK_EMIT_BASELINE"]
    if candidate.candidate_group == "ALMOST_PEAK_2_OF_3":
        cohorts = ["ALMOST_PEAK_2_OF_3"]
        if candidate.comparison_setup_variant in VARIANTS:
            cohorts.append(str(candidate.comparison_setup_variant))
        return cohorts
    return []


def _max_drawdown(items: list[TradeResult]) -> float:
    equity = peak = maximum = 0.0
    closed = sorted(
        (item for item in items if item.entry_status == "FILLED" and item.net_pnl_usdc is not None),
        key=lambda item: (item.exit_ts or item.signal_ts_utc, item.trade_id),
    )
    for item in closed:
        equity += float(item.net_pnl_usdc or 0.0)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _metric_row(cohort: str, period: str, side: str, pairs: list[tuple[Candidate, TradeResult]]) -> dict[str, Any]:
    results = [result for _, result in pairs]
    filled = [result for result in results if result.entry_status == "FILLED"]
    net = [float(result.net_pnl_usdc) for result in filled if result.net_pnl_usdc is not None]
    gross = [float(result.gross_pnl_usdc) for result in filled if result.gross_pnl_usdc is not None]
    fees = [float(result.commission_usdc) for result in filled if result.commission_usdc is not None]
    r_values = [float(result.position_r) for result in filled if result.position_r is not None]
    gains = sum(value for value in net if value > 0)
    losses = -sum(value for value in net if value < 0)
    return {
        "comparison_cohort": cohort,
        "period": period,
        "side": side,
        "candidate_count": len(pairs),
        "filled_count": len(filled),
        "fill_rate": len(filled) / len(pairs) if pairs else None,
        "plain_sl_count": sum(result.lifecycle_class == "PLAIN_SL" for result in filled),
        "tp1_sl_count": sum(result.lifecycle_class == "TP1_SL" for result in filled),
        "protected_count": sum(result.lifecycle_class == "TP1_TP2_TRAILING_STOP" for result in filled),
        "no_entry_count": len(pairs) - len(filled),
        "gross_pnl_usdc": sum(gross),
        "commission_usdc": sum(fees),
        "net_pnl_usdc": sum(net),
        "mean_net_pnl_per_fill_usdc": mean(net) if net else None,
        "median_net_pnl_usdc": median(net) if net else None,
        "profit_factor": gains / losses if losses else None,
        "max_drawdown_usdc": _max_drawdown(filled),
        "average_r": mean(r_values) if r_values else None,
        "total_r": sum(r_values),
    }


def build_variant_metrics(candidates: Iterable[Candidate], results: Iterable[TradeResult]) -> list[dict[str, Any]]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    buckets: dict[tuple[str, str, str], list[tuple[Candidate, TradeResult]]] = defaultdict(list)
    for result in results:
        candidate = candidate_by_id[result.candidate_id]
        for cohort in _cohorts(candidate):
            for period in ("ALL", _period(candidate)):
                buckets[(cohort, period, "ALL")].append((candidate, result))
                buckets[(cohort, period, candidate.side)].append((candidate, result))
    return [_metric_row(*key, pairs) for key, pairs in sorted(buckets.items())]


def build_variant_trades(candidates: Iterable[Candidate], results: Iterable[TradeResult]) -> list[dict[str, Any]]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    rows: list[dict[str, Any]] = []
    for result in results:
        candidate = candidate_by_id[result.candidate_id]
        if candidate.comparison_setup_variant not in VARIANTS:
            continue
        failed = str(candidate.comparison_3of3_failed_subconditions)
        current = {"price": candidate.signal_price, "vol": candidate.volume, "vwap": candidate.vwap}.get(failed)
        previous = {
            "price": candidate.comparison_previous_price,
            "vol": candidate.comparison_previous_vol,
            "vwap": candidate.comparison_previous_vwap,
        }.get(failed)
        rows.append({
            "signal_ts_utc": candidate.signal_ts_utc.isoformat(),
            "direction": candidate.side,
            "candidate_id": candidate.candidate_id,
            "candidate_group": candidate.candidate_group,
            "comparison_setup_variant": candidate.comparison_setup_variant,
            "period": _period(candidate),
            "signal_price_usdt": candidate.signal_price,
            "execution_entry_usdc": result.entry_fill_price,
            "sl_usdc": result.initial_stop_price,
            "tp1_usdc": result.tp1_price,
            "tp2_usdc": result.tp2_price,
            "entry_status": result.entry_status,
            "outcome": result.lifecycle_class,
            "net_pnl_usdc": result.net_pnl_usdc,
            "position_r": result.position_r,
            "failed_subcondition": failed,
            "failed_current_value": current,
            "failed_previous_value": previous,
            "comparison_price_pass": candidate.comparison_price_pass,
            "comparison_vol_pass": candidate.comparison_vol_pass,
            "comparison_vwap_pass": candidate.comparison_vwap_pass,
        })
    return rows


def build_variant_monthly(candidates: Iterable[Candidate], results: Iterable[TradeResult]) -> list[dict[str, Any]]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    buckets: dict[tuple[str, str, str], list[tuple[Candidate, TradeResult]]] = defaultdict(list)
    for result in results:
        candidate = candidate_by_id[result.candidate_id]
        month = candidate.signal_ts_utc.strftime("%Y-%m")
        for cohort in _cohorts(candidate):
            buckets[(cohort, month, "ALL")].append((candidate, result))
            buckets[(cohort, month, candidate.side)].append((candidate, result))
    rows = []
    for (cohort, month, side), pairs in sorted(buckets.items()):
        row = _metric_row(cohort, month, side, pairs)
        row["month"] = row.pop("period")
        rows.append(row)
    return rows


def _filter_match(candidate: Candidate, name: str) -> bool:
    flags = candidate.shadow_flags
    if name == "OVERLAP_A_AND_B":
        return flags.get("weak_peak_le_50") is True and flags.get("oi_down_60_and_directional_delta_pct_240_lt_0_06") is True
    return flags.get(FILTERS[name]) is True


def build_variant_loss_filter(candidates: Iterable[Candidate], results: Iterable[TradeResult]) -> list[dict[str, Any]]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    by_variant: dict[str, list[tuple[Candidate, TradeResult]]] = defaultdict(list)
    for result in results:
        candidate = candidate_by_id[result.candidate_id]
        if candidate.comparison_setup_variant in VARIANTS:
            by_variant[str(candidate.comparison_setup_variant)].append((candidate, result))
    rows: list[dict[str, Any]] = []
    for variant in VARIANTS:
        pairs = by_variant.get(variant, [])
        baseline_fills = [result for _, result in pairs if result.entry_status == "FILLED"]
        baseline_net = sum(float(result.net_pnl_usdc or 0.0) for result in baseline_fills)
        for filter_name in FILTERS:
            blocked = [pair for pair in pairs if _filter_match(pair[0], filter_name)]
            blocked_ids = {candidate.candidate_id for candidate, _ in blocked}
            blocked_fills = [result for _, result in blocked if result.entry_status == "FILLED"]
            kept_fills = [result for result in baseline_fills if result.candidate_id not in blocked_ids]
            kept_net = sum(float(result.net_pnl_usdc or 0.0) for result in kept_fills)
            rows.append({
                "comparison_setup_variant": variant,
                "filter_component": filter_name,
                "candidate_count_before": len(pairs),
                "filled_count_before": len(baseline_fills),
                "blocked_candidate_count": len(blocked),
                "blocked_filled_count": len(blocked_fills),
                "blocked_plain_sl_count": sum(result.lifecycle_class == "PLAIN_SL" for result in blocked_fills),
                "blocked_tp1_sl_count": sum(result.lifecycle_class == "TP1_SL" for result in blocked_fills),
                "blocked_protected_count": sum(result.lifecycle_class == "TP1_TP2_TRAILING_STOP" for result in blocked_fills),
                "overlap_candidate_count": sum(_filter_match(candidate, "OVERLAP_A_AND_B") for candidate, _ in pairs),
                "candidate_count_after": len(pairs) - len(blocked),
                "filled_count_after": len(kept_fills),
                "expectancy_before_usdc": baseline_net / len(baseline_fills) if baseline_fills else None,
                "expectancy_after_usdc": kept_net / len(kept_fills) if kept_fills else None,
                "net_pnl_before_usdc": baseline_net,
                "net_pnl_after_usdc": kept_net,
            })
    return rows


def build_other_groups_inventory(candidates: Iterable[Candidate]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.candidate_group == "ALMOST_PEAK_1_OF_3":
            subgroup = candidate.comparison_3of3_failed_subconditions or "UNCLASSIFIED"
        elif candidate.candidate_group == "GATE_REJECT":
            reason = candidate.reject_reason or "UNSPECIFIED"
            subgroup = reason if reason in {"ema50_vwap_regime", "chop_coh", "imb_band"} else f"other:{reason}"
        else:
            subgroup = candidate.reject_reason or "ALL"
        buckets[(candidate.candidate_group, subgroup)].append(candidate)
    rows = []
    for (group, subgroup), items in sorted(buckets.items()):
        comparison = [item for item in items if item.reject_reason == "3of3_fail"]
        rows.append({
            "candidate_group": group,
            "inventory_subgroup": subgroup,
            "candidate_count": len(items),
            "long_count": sum(item.side == "LONG" for item in items),
            "short_count": sum(item.side == "SHORT" for item in items),
            "signal_core_complete_count": sum(item.signal_price is not None and item.volume is not None and item.vwap is not None for item in items),
            "comparison_complete_count": sum(
                item.comparison_price_pass is not None and item.comparison_vol_pass is not None and item.comparison_vwap_pass is not None
                for item in comparison
            ),
            "comparison_applicable_count": len(comparison),
            "loss_filter_union_known_count": sum(item.shadow_flags.get("loss_avoidance_conservative_union") is not None for item in items),
        })
    return rows


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def write_variant_summary(
    path: Path,
    *,
    config: ReplayConfig,
    metrics: list[dict[str, Any]],
    loss_filter: list[dict[str, Any]],
    quality: list[CandidateQualityRow],
    distribution: dict[str, int],
    applied_candidate_loss_filter: dict[str, object] | None = None,
) -> Path:
    all_rows = {row["comparison_cohort"]: row for row in metrics if row["period"] == "ALL" and row["side"] == "ALL"}
    validation = {row["comparison_cohort"]: row for row in metrics if row["period"] == "VALIDATION" and row["side"] == "ALL"}
    variants = [all_rows[name] for name in VARIANTS if name in all_rows]
    worst = min(variants, key=lambda row: row["mean_net_pnl_per_fill_usdc"] if row["mean_net_pnl_per_fill_usdc"] is not None else float("inf")) if variants else None
    union = {row["comparison_setup_variant"]: row for row in loss_filter if row["filter_component"] == "UNION_A_OR_B"}
    lines = [
        "# ALMOST PEAK 2/3 failed-gate variants",
        "",
        "The candidate identity and original `candidate_group` are preserved. `comparison_setup_variant` is an additive research dimension.",
        "",
        "## Frozen chronology",
        "",
        "- Discovery: signal timestamp before `2026-06-01T00:00:00Z`.",
        "- Validation: signal timestamp on or after `2026-06-01T00:00:00Z`.",
        "- The boundary was fixed before variant outcome aggregation.",
        "",
        "## Classification control",
        "",
        f"- Current replay price failed: {distribution.get('ALMOST_2OF3_PRICE_FAIL', 0)}.",
        f"- Current replay volume failed: {distribution.get('ALMOST_2OF3_VOLUME_FAIL', 0)}.",
        f"- Current replay VWAP failed: {distribution.get('ALMOST_2OF3_VWAP_FAIL', 0)}.",
        "- Frozen v3 control through `2026-08-18`: `66 price / 74 volume / 107 vwap`; enforced by a separate regression test.",
        f"- Invalid/ambiguous comparison rows: {sum(row.reason in {'COMPARISON_CLASSIFICATION_INVALID', 'ALMOST_2OF3_VARIANT_INVALID'} for row in quality)}.",
    ]
    if applied_candidate_loss_filter and applied_candidate_loss_filter.get("policy") != "NONE":
        lines.extend([
            "",
            "## Applied pre-replay loss filter",
            "",
            f"- Policy: `{applied_candidate_loss_filter['policy']}`.",
            f"- Candidates before / blocked / kept: {applied_candidate_loss_filter['input_candidate_count']} / "
            f"{applied_candidate_loss_filter['blocked_candidate_count']} / {applied_candidate_loss_filter['kept_candidate_count']}.",
            f"- Unknown values kept fail-open: {applied_candidate_loss_filter['unknown_kept_count']}.",
            "- Blocked identities are recorded in `candidate_loss_filter_exclusions.csv`.",
        ])
    lines.extend([
        "",
        "## Independent deterministic replay",
        "",
        "| Cohort | Candidates | Fills | Plain SL | TP1→SL | Protected | Net PnL | Expectancy/fill | PF | Avg R | Total R | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for name in ("PEAK_EMIT_BASELINE", "ALMOST_PEAK_2_OF_3", *VARIANTS):
        row = all_rows.get(name)
        if not row:
            continue
        lines.append(
            f"| `{name}` | {row['candidate_count']} | {row['filled_count']} | {row['plain_sl_count']} | {row['tp1_sl_count']} | "
            f"{row['protected_count']} | {_fmt(row['net_pnl_usdc'])} | {_fmt(row['mean_net_pnl_per_fill_usdc'])} | "
            f"{_fmt(row['profit_factor'])} | {_fmt(row['average_r'])} | {_fmt(row['total_r'])} | {_fmt(row['max_drawdown_usdc'])} |"
        )
    lines.extend(["", "## Conclusions", ""])
    if worst:
        lines.append(f"- Worst full-history subgroup by expectancy: `{worst['comparison_cohort']}` at {_fmt(worst['mean_net_pnl_per_fill_usdc'])} USDC/fill.")
    positive = [row["comparison_cohort"] for row in variants if float(row["mean_net_pnl_per_fill_usdc"] or 0.0) > 0]
    lines.append(f"- Positive full-history expectancy: {', '.join(f'`{name}`' for name in positive) if positive else 'none' }.")
    for name in VARIANTS:
        row = validation.get(name)
        if row:
            label = "positive" if float(row["mean_net_pnl_per_fill_usdc"] or 0.0) > 0 else "non-positive"
            exploratory = "; exploratory due to fewer than 30 validation fills" if row["filled_count"] < 30 else ""
            lines.append(f"- `{name}` validation: {row['filled_count']} fills, {_fmt(row['mean_net_pnl_per_fill_usdc'])} USDC/fill ({label}){exploratory}.")
    side_rows = {
        (row["comparison_cohort"], row["side"]): row
        for row in metrics
        if row["period"] == "ALL" and row["side"] in {"LONG", "SHORT"}
    }
    for name in VARIANTS:
        long_row, short_row = side_rows.get((name, "LONG")), side_rows.get((name, "SHORT"))
        if long_row and short_row:
            lines.append(
                f"- `{name}` side split: LONG {_fmt(long_row['mean_net_pnl_per_fill_usdc'])} vs "
                f"SHORT {_fmt(short_row['mean_net_pnl_per_fill_usdc'])} USDC/fill "
                f"({long_row['filled_count']}/{short_row['filled_count']} fills)."
            )
    if applied_candidate_loss_filter and applied_candidate_loss_filter.get("policy") != "NONE":
        lines.append(
            "- `comparison_variant_loss_filter.csv` is a residual reapplication diagnostic on the already filtered candidate set; use the manifest and exclusion ledger for the pre-replay filter effect."
        )
    else:
        for name in VARIANTS:
            row = union.get(name)
            if row:
                lines.append(
                    f"- `{name}` union filter: blocks {row['blocked_candidate_count']} candidates/{row['blocked_filled_count']} fills, "
                    f"including {row['blocked_protected_count']} protected; net {_fmt(row['net_pnl_before_usdc'])} → {_fmt(row['net_pnl_after_usdc'])} USDC."
                )
        lines.append(
            "- The union filter is not portable across variants: it blocks protected winners, and its net effect changes by failed-gate cohort and stop policy."
        )
    contour_constraint = (
        "- Candidate construction, entry/SL/TP/trailing levels, and lifecycle touches all use the BTCUSDT signal feed; no USDT/USDC conversion is applied."
        if config.price_contour == "btcusdt_signal"
        else "- BTCUSDT Futures remains the signal/context contour; BTCUSDC Spot remains the entry/SL/TP/trailing execution contour."
    )
    validation_positive = {
        name
        for name, row in validation.items()
        if float(row["mean_net_pnl_per_fill_usdc"] or 0.0) > 0
    }
    continuation = [name for name in positive if name in validation_positive]
    if continuation:
        recommendation = (
            "- Recommended next step: continue only "
            + ", ".join(f"`{name}`" for name in continuation)
            + " as exploratory watchlist cohort(s), and extend the frozen validation window with future untouched data before any live-policy change."
        )
    elif positive:
        recommendation = (
            "- No subgroup is positive in both full-history and validation under this run; do not select a watchlist cohort without additional untouched evidence."
        )
    else:
        recommendation = (
            "- No failed-gate subgroup has positive full-history expectancy under this run; do not promote a subgroup from this stop-policy replay."
        )
    lines.extend([
        "- LONG/SHORT and monthly slices are in `comparison_variant_metrics.csv` and `comparison_variant_monthly.csv`.",
        "- Any subgroup with a small validation denominator remains exploratory and is not a live-readiness claim.",
        recommendation,
        "",
        "## Data and execution constraints",
        "",
        contour_constraint,
        "- The recovered feed and its sidecars govern the documented 2026-04-23 to 2026-05-06 gap; synthetic originals are not treated as market evidence.",
        "- One-minute same-bar ambiguity uses the conservative stop-first baseline.",
        "- This is offline research only. No live filter or VPS runtime was changed.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def materialize_variant_artifacts(
    output_dir: Path,
    *,
    config: ReplayConfig,
    candidates: list[Candidate],
    inventory_candidates: list[Candidate],
    independent: list[TradeResult],
    quality: list[CandidateQualityRow],
    applied_candidate_loss_filter: dict[str, object] | None = None,
) -> tuple[list[Path], dict[str, Any]]:
    variant_quality = validate_comparison_variants(candidates)
    quality.extend(variant_quality)
    metrics = build_variant_metrics(candidates, independent)
    trades = build_variant_trades(candidates, independent)
    monthly = build_variant_monthly(candidates, independent)
    loss_filter = build_variant_loss_filter(candidates, independent)
    inventory = build_other_groups_inventory(inventory_candidates)
    distribution = Counter(
        str(candidate.comparison_setup_variant)
        for candidate in candidates
        if candidate.candidate_group == "ALMOST_PEAK_2_OF_3" and candidate.comparison_setup_variant
    )
    paths = [
        write_csv(output_dir / "comparison_variant_metrics.csv", metrics),
        write_csv(output_dir / "comparison_variant_trades.csv", trades),
        write_csv(output_dir / "comparison_variant_monthly.csv", monthly),
        write_csv(output_dir / "comparison_variant_loss_filter.csv", loss_filter),
        write_csv(output_dir / "other_candidate_groups_inventory.csv", inventory),
        write_variant_summary(
            output_dir / "summary.md", config=config, metrics=metrics, loss_filter=loss_filter,
            quality=quality, distribution=dict(distribution),
            applied_candidate_loss_filter=applied_candidate_loss_filter,
        ),
    ]
    payload = {
        "price_contour": config.price_contour,
        "discovery_period_end_exclusive_utc": DISCOVERY_END_UTC.isoformat(),
        "validation_period_start_utc": DISCOVERY_END_UTC.isoformat(),
        "comparison_variant_distribution": dict(sorted(distribution.items())),
        "classification_invalid_count": len(variant_quality),
        "artifact_content_sha256": hashlib.sha256(
            json.dumps({"metrics": metrics, "monthly": monthly, "loss_filter": loss_filter}, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }
    return paths, payload
