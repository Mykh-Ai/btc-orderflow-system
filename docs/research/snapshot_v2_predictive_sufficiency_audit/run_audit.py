"""Descriptive audit of unchanged, committed Snapshot V2 fields. No model calls."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
SNAPSHOTS = ROOT / "docs/research/open_trade_outcome_predictor_v1/blind_run_v3/frozen_model_view_snapshots.jsonl"
MANIFEST = ROOT / "docs/research/open_trade_outcome_predictor_hierarchical_v1/blind_run/blind_manifest.csv"
LEDGER = ROOT / "docs/research/canonical_trade_evaluation_snapshot/case_ledger.csv"
EXCLUDED = "EX_EN_1779900918"
EXPECTED_SNAPSHOT_SHA256 = "402de774d4a2a7705f0b2d7c79470ee5f2ca0254a84d9cd51b4bd0ed16d024dd"
EXPECTED_MANIFEST_SHA256 = "6412e434007d27435298049d8720168382dcd4a94b5f91b5423157b0a6caf2b8"
SEGMENTS = (
    ("T-1440_TO_T-240", "seg_1440_240", 1200),
    ("T-240_TO_T-60", "seg_240_60", 180),
    ("T-60_TO_T-15", "seg_60_15", 45),
    ("T-15_TO_T-5", "seg_15_5", 10),
    ("T-5_TO_T0", "seg_5_0", 5),
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_ratio(numerator: Any, denominator: Any, scale: float = 1.0) -> float | None:
    a, b = _num(numerator), _num(denominator)
    return scale * a / b if a is not None and b not in (None, 0) else None


def flatten(snapshot: dict[str, Any]) -> tuple[dict[str, float | None], dict[str, str], dict[str, str], dict[str, str]]:
    numeric: dict[str, float | None] = {}
    family: dict[str, str] = {}
    provenance: dict[str, str] = {}
    categorical: dict[str, str] = {}

    def add(name: str, value: Any, section: str, source: str = "frozen_raw") -> None:
        numeric[name] = _num(value)
        family[name] = section
        provenance[name] = source

    def cat(name: str, value: Any) -> None:
        categorical[name] = "MISSING" if value is None else ("YES" if value is True else "NO" if value is False else str(value))

    signal = snapshot["signal"]
    execution = snapshot["execution"]
    temporal = snapshot["temporal_market"]
    structure = snapshot["structure_geometry"]
    quality = snapshot["quality"]
    side = signal["side"].lower()
    sign = 1 if side == "long" else -1
    measurements = signal["measurements"]
    cat("signal_side", side.upper())
    for key in ("signal_price",):
        add(key, signal.get(key), "SIGNAL")
    for source_key, name in (("delta", "signal_delta"), ("vol", "signal_volume"),
                             ("imb", "signal_imbalance"), ("vwap", "signal_vwap"),
                             ("poc", "signal_poc"), ("strength", "signal_strength")):
        add(name, measurements.get(source_key), "SIGNAL")
    add("directional_signal_delta", sign * numeric["signal_delta"] if numeric["signal_delta"] is not None else None,
        "SIGNAL", "direction_sign_only")
    for reference in ("vwap", "poc"):
        add(f"analysis_only_directional_signal_price_minus_{reference}_pct",
            _safe_ratio(sign * (numeric["signal_price"] - numeric[f"signal_{reference}"]), numeric[f"signal_{reference}"], 100)
            if numeric["signal_price"] is not None and numeric[f"signal_{reference}"] is not None else None,
            "SIGNAL", "deterministic_relationship_of_frozen_fields")

    for key in ("actual_entry_price", "filled_quantity", "initial_sl", "initial_tp1", "initial_tp2",
                "entry_to_sl_risk", "tp1_reward", "tp1_R", "tp2_reward", "tp2_R",
                "entry_minus_signal_distance_approx", "entry_minus_signal_pct_approx",
                "signal_to_fill_elapsed_seconds", "quote_conversion_at_entry_approx"):
        add(key, execution.get(key), "EXECUTION_GEOMETRY")
    add("analysis_only_risk_pct", _safe_ratio(execution.get("entry_to_sl_risk"), execution.get("actual_entry_price"), 100),
        "EXECUTION_GEOMETRY", "deterministic_relationship_of_frozen_fields")

    by_segment = {row["segment"]: row for row in temporal["segments"]}
    for segment_name, prefix, _ in SEGMENTS:
        row = by_segment[segment_name]
        cat(prefix + "_complete", row.get("complete"))
        cat(prefix + "_source_quality", row.get("source_quality"))
        for key in ("price_open", "price_close", "high", "low", "price_change_pct", "delta",
                    "delta_pct", "total_qty", "open_interest_change", "rows_expected", "rows_used"):
            add(prefix + "_" + key, row.get(key), "TEMPORAL_MARKET")
        for key in ("price_change_pct", "delta", "delta_pct"):
            raw = numeric[prefix + "_" + key]
            add(prefix + "_directional_" + key, sign * raw if raw is not None else None,
                "TEMPORAL_MARKET", "direction_sign_only")
    for horizon in ("1d", "3d", "7d"):
        row = temporal["broad_context"][horizon]
        cat("broad_" + horizon + "_complete", row.get("complete"))
        cat("broad_" + horizon + "_source_quality", row.get("source_quality"))
        for key in ("price_change_pct", "delta_pct", "rows_expected", "rows_used"):
            add("broad_" + horizon + "_" + key, row.get(key), "BROAD_CONTEXT")
        for key in ("price_change_pct", "delta_pct"):
            raw = numeric["broad_" + horizon + "_" + key]
            add("broad_" + horizon + "_directional_" + key, sign * raw if raw is not None else None,
                "BROAD_CONTEXT", "direction_sign_only")

    add("current_price_market_quote", structure.get("current_price_market_quote"), "LOCATION")
    for window in ("240m", "1440m"):
        row = structure["range_" + window]
        prefix = "range_" + window
        for key in ("high", "low", "position_in_range", "distance_to_high", "distance_to_low"):
            add(prefix + "_" + key, row.get(key), "LOCATION")
        pos = numeric[prefix + "_position_in_range"]
        add(prefix + "_directional_position_in_range", pos if sign == 1 else 1 - pos if pos is not None else None,
            "LOCATION", "direction_sign_only")
        add(prefix + "_distance_to_directional_extreme",
            row.get("distance_to_high") if sign == 1 else row.get("distance_to_low"),
            "LOCATION", "directional_selection_of_frozen_field")
        extreme = row.get("high") if sign == 1 else row.get("low")
        k_entry = _num(execution.get("quote_conversion_at_entry_approx"))
        for target in ("tp1", "tp2"):
            target_value = _num(execution.get("initial_" + target))
            difference = sign * (target_value / k_entry - extreme) if target_value is not None and k_entry not in (None, 0) and _num(extreme) is not None else None
            add(f"analysis_only_{target}_beyond_{window}_directional_extreme_market_quote_approx",
                difference, "EXECUTION_GEOMETRY", "deterministic_quote_approx_relationship")

    zone = structure.get("nearest_qualified_opposing_zone")
    cat("opposing_zone_present", zone is not None)
    if zone:
        for key in ("lower", "upper", "distance_from_current_price_market_quote", "interaction_count",
                    "minutes_since_last_interaction", "resweep_count", "failed_acceptance_count",
                    "close_above_count", "close_below_count"):
            add("opposing_zone_" + key, zone.get(key), "STRUCTURE_ZONES")
        for key in ("price_position", "qualification", "status", "consumption_status"):
            cat("opposing_zone_" + key, zone.get(key))
        cat("opposing_zone_first_sweep_present", zone.get("first_sweep_timestamp") is not None)
        cat("opposing_zone_already_interacted", (_num(zone.get("interaction_count")) or 0) > 0)
        accepted_key = "accepted_above_timestamp" if sign == 1 else "accepted_below_timestamp"
        cat("opposing_zone_accepted_beyond_in_direction", zone.get(accepted_key) is not None)
        matched = zone.get("matched_registry_lifecycle")
        cat("matched_registry_lifecycle_present", matched is not None)
        if matched:
            for key in ("interaction_count", "resweep_count", "failed_acceptance_count", "close_above_count", "close_below_count"):
                add("matched_registry_" + key, matched.get(key), "STRUCTURE_ZONES")
            cat("matched_registry_accepted_beyond_in_direction", matched.get(accepted_key) is not None)
            cat("matched_registry_first_sweep_present", matched.get("first_sweep_timestamp") is not None)
    else:
        for key in ("lower", "upper", "distance_from_current_price_market_quote", "interaction_count",
                    "minutes_since_last_interaction", "resweep_count", "failed_acceptance_count",
                    "close_above_count", "close_below_count"):
            add("opposing_zone_" + key, None, "STRUCTURE_ZONES")
        for key in ("price_position", "qualification", "status", "consumption_status", "first_sweep_present",
                    "already_interacted", "accepted_beyond_in_direction"):
            cat("opposing_zone_" + key, None)
        cat("matched_registry_lifecycle_present", False)
    cleared = structure.get("recent_cleared_structure_in_trade_direction")
    cat("recent_cleared_structure_present", cleared is not None)
    if cleared:
        for key in ("lower", "upper", "minutes_since_acceptance", "distance_current_price_beyond_zone"):
            add("recent_cleared_" + key, cleared.get(key), "STRUCTURE_ZONES")
        cat("recent_cleared_returned_inside", cleared.get("returned_inside_after_acceptance"))
        cat("recent_cleared_returned_through_opposite_boundary", cleared.get("returned_through_opposite_boundary_after_acceptance"))
    liquidity = structure.get("nearest_active_liquidity_in_trade_direction")
    cat("directional_liquidity_present", liquidity is not None)
    if liquidity:
        for key in ("distance_from_current_price", "lower", "upper"):
            add("directional_liquidity_" + key, liquidity.get(key), "STRUCTURE_ZONES")
        cat("directional_liquidity_side", liquidity.get("side"))
    else:
        for key in ("distance_from_current_price", "lower", "upper"):
            add("directional_liquidity_" + key, None, "STRUCTURE_ZONES")
        cat("directional_liquidity_side", None)
    geometry = structure.get("target_clear_air_geometry")
    for key in ("distance_from_actual_entry_R_approx", "distance_from_actual_entry_execution_quote_approx",
                "near_boundary_market_quote"):
        add("target_geometry_" + key, geometry.get(key) if geometry else None, "STRUCTURE_ZONES")
    for key in ("tp1_relation", "tp2_relation"):
        cat("target_geometry_" + key, geometry.get(key) if geometry else None)

    for key in ("open_interest_available", "zone_history_available", "degraded_or_recovered_feed",
                "open_price_close_fallback", "conversion_available", "historical_prediction_cutoff_proxy"):
        cat("quality_" + key, quality.get(key))
    cat("quality_chronology_anomaly", quality.get("chronology_anomaly"))
    cat("quality_prediction_cutoff_source", quality.get("prediction_cutoff_source"))
    add("quality_missing_evidence_count", len(quality.get("missing_evidence") or []), "QUALITY_CHRONOLOGY", "count_of_frozen_quality_entries")
    add("quality_incomplete_segments_count", len(quality.get("incomplete_segments") or []), "QUALITY_CHRONOLOGY", "count_of_frozen_quality_entries")
    add("quality_incomplete_broad_context_count", len(quality.get("incomplete_broad_context") or []), "QUALITY_CHRONOLOGY", "count_of_frozen_quality_entries")

    # Two predeclared trajectory diagnostics from existing non-overlapping segments.
    d5 = numeric["seg_5_0_directional_delta_pct"]
    d10 = numeric["seg_15_5_directional_delta_pct"]
    p5 = numeric["seg_5_0_directional_price_change_pct"]
    p10 = numeric["seg_15_5_directional_price_change_pct"]
    add("diagnostic_recent_minus_prior_directional_delta_pct", d5 - d10 if d5 is not None and d10 is not None else None,
        "TEMPORAL_TRAJECTORY", "analysis_only_predeclared_diagnostic")
    add("diagnostic_recent_minus_prior_directional_price_change_pct_per_minute",
        p5 / 5 - p10 / 10 if p5 is not None and p10 is not None else None,
        "TEMPORAL_TRAJECTORY", "analysis_only_predeclared_diagnostic")
    return numeric, categorical, family, provenance


def _summarize(values: list[float | None]) -> dict[str, Any]:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    if not finite:
        return {"count": 0, "missing": len(values), "mean": None, "median": None,
                "min": None, "q1": None, "q3": None, "max": None, "std": None}
    array = np.asarray(finite, dtype=float)
    return {"count": len(finite), "missing": len(values) - len(finite),
            "mean": float(array.mean()), "median": float(np.median(array)),
            "min": float(array.min()), "q1": float(np.quantile(array, .25)),
            "q3": float(np.quantile(array, .75)), "max": float(array.max()),
            "std": float(array.std(ddof=1)) if len(array) > 1 else None}


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    width = max(a1, b1) - min(a0, b0)
    if width == 0:
        return 1.0
    return max(0.0, min(a1, b1) - max(a0, b0)) / width


def _compare(a: list[float | None], b: list[float | None]) -> dict[str, float | None]:
    first = [v for v in a if v is not None and math.isfinite(v)]
    second = [v for v in b if v is not None and math.isfinite(v)]
    if not first or not second:
        return {"median_difference_group2_minus_group1": None, "hedges_g": None,
                "rank_biserial_group2_vs_group1": None, "iqr_overlap_ratio": None, "range_overlap_ratio": None}
    sa, sb = _summarize(first), _summarize(second)
    pairs = len(first) * len(second)
    favorable = sum((x > y) + .5 * (x == y) for x in second for y in first)
    rank_biserial = 2 * favorable / pairs - 1
    g = None
    if len(first) > 1 and len(second) > 1:
        pooled_variance = ((len(first) - 1) * statistics.variance(first) + (len(second) - 1) * statistics.variance(second)) / (len(first) + len(second) - 2)
        if pooled_variance > 0:
            d = (statistics.mean(second) - statistics.mean(first)) / math.sqrt(pooled_variance)
            g = d * (1 - 3 / (4 * (len(first) + len(second)) - 9))
    return {"median_difference_group2_minus_group1": sb["median"] - sa["median"],
            "hedges_g": g, "rank_biserial_group2_vs_group1": rank_biserial,
            "iqr_overlap_ratio": _overlap(sa["q1"], sa["q3"], sb["q1"], sb["q3"]),
            "range_overlap_ratio": _overlap(sa["min"], sa["max"], sb["min"], sb["max"])}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"empty output: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    output = Path(__file__).resolve().parent
    if hashlib.sha256(SNAPSHOTS.read_bytes()).hexdigest() != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError("frozen Snapshot V2 bytes changed")
    if hashlib.sha256(MANIFEST.read_bytes()).hexdigest() != EXPECTED_MANIFEST_SHA256:
        raise ValueError("committed hierarchical manifest bytes changed")
    with MANIFEST.open(encoding="utf-8", newline="") as stream:
        manifest = list(csv.DictReader(stream))
    cohort = {case["trade_key"] for case in manifest if case["score_eligible"].lower() == "true"}
    if len(cohort) != 19 or {case["trade_key"] for case in manifest if case["score_eligible"].lower() != "true"} != {EXCLUDED}:
        raise ValueError("hierarchical blind cohort identity changed")
    with LEDGER.open(encoding="utf-8", newline="") as stream:
        ledger = {row["trade_key"]: row for row in csv.DictReader(stream)}
    snapshots = [json.loads(line) for line in SNAPSHOTS.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(snapshots) != 20 or {snapshot["signal"]["trade_key"] for snapshot in snapshots} != {case["trade_key"] for case in manifest}:
        raise ValueError("frozen snapshot membership differs from manifest")
    records = []
    families: dict[str, str] = {}
    provenance: dict[str, str] = {}
    categorical_names: set[str] = set()
    for snapshot in snapshots:
        key = snapshot["signal"]["trade_key"]
        if key == EXCLUDED:
            continue
        if key not in cohort:
            raise ValueError(f"unexpected Snapshot V2 key: {key}")
        truth = "STRONG_FAVORABLE" if ledger[key]["tp2_done"].lower() == "true" else "MIXED" if ledger[key]["tp1_done"].lower() == "true" else "NEGATIVE" if ledger[key]["outcome_reason"].upper() == "SL" else "UNKNOWN"
        if truth == "UNKNOWN":
            raise ValueError(f"unresolved independent lifecycle truth: {key}")
        numeric, categorical, these_families, these_provenance = flatten(snapshot)
        families.update(these_families)
        provenance.update(these_provenance)
        categorical_names.update(categorical)
        records.append({"trade_key": key, "true_lifecycle": truth,
                        "target_A": "NEGATIVE" if truth == "NEGATIVE" else "TP1_REACHED",
                        "target_B": truth if truth in ("MIXED", "STRONG_FAVORABLE") else "NOT_APPLICABLE",
                        **numeric, **{"category_" + name: value for name, value in categorical.items()}})
    if len(records) != 19 or Counter(r["true_lifecycle"] for r in records) != {"NEGATIVE": 9, "MIXED": 4, "STRONG_FAVORABLE": 6}:
        raise ValueError("valid cohort counts changed")
    _write_csv(output / "case_feature_matrix.csv", records)

    distributions = []
    targets = (("A", "NEGATIVE", "TP1_REACHED"), ("B", "MIXED", "STRONG_FAVORABLE"))
    for target, group1, group2 in targets:
        field = "target_" + target
        first = [r for r in records if r[field] == group1]
        second = [r for r in records if r[field] == group2]
        for feature in sorted(families):
            values1 = [r.get(feature) for r in first]
            values2 = [r.get(feature) for r in second]
            stats1, stats2 = _summarize(values1), _summarize(values2)
            row = {"target": target, "family": families[feature], "feature": feature,
                   "provenance": provenance[feature], "group1": group1, "group2": group2,
                   "n_group1": len(first), "n_group2": len(second)}
            row.update({"group1_" + key: value for key, value in stats1.items()})
            row.update({"group2_" + key: value for key, value in stats2.items()})
            row.update(_compare(values1, values2))
            distributions.append(row)
    _write_csv(output / "feature_distribution.csv", distributions)

    categorical_rows = []
    for target, group1, group2 in targets:
        field = "target_" + target
        first = [r for r in records if r[field] == group1]
        second = [r for r in records if r[field] == group2]
        for name in sorted(categorical_names):
            values1 = Counter(r.get("category_" + name, "MISSING") for r in first)
            values2 = Counter(r.get("category_" + name, "MISSING") for r in second)
            for category in sorted(set(values1) | set(values2)):
                categorical_rows.append({"target": target, "feature": name, "category": category,
                                         "group1": group1, "group1_count": values1[category], "group1_n": len(first),
                                         "group2": group2, "group2_count": values2[category], "group2_n": len(second)})
    _write_csv(output / "categorical_distribution.csv", categorical_rows)

    print(json.dumps({"cohort": len(records), "numeric_features": len(families),
                      "distribution_rows": len(distributions), "categorical_rows": len(categorical_rows),
                      "class_counts": dict(Counter(r["true_lifecycle"] for r in records)),
                      "snapshot_sha256": hashlib.sha256(SNAPSHOTS.read_bytes()).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
