from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


SELECTOR_VERSION = "SHI_RESET_36B_SIGNIFICANT_ZONE_SELECTOR_V0"
SELECTED_ZONES_CSV = "selected_zones.csv"
SELECTOR_SUMMARY_MD = "significant_zone_selector_summary.md"
SELECTOR_MANIFEST_JSON = "significant_zone_selector_manifest.json"

BUCKET_MAJOR = "MAJOR"
BUCKET_PRIMARY = "PRIMARY"
BUCKET_MINIMUM = "MINIMUM"
BUCKET_LOCAL_CONTEXT = "LOCAL_CONTEXT"
BUCKET_NOISE = "NOISE_HIDE_BY_DEFAULT"
SIDE_BALANCE_PROMOTION_REASON = (
    "selected to preserve two-sided liquidity map; strong opposite-side MAJOR/PRIMARY zone within score gap"
)
SIDE_BALANCE_DISPLACED_REASON = (
    "hidden by side-balanced visibility cap; lower priority than opposite-side zone needed for market map"
)

SELECTED_ZONE_COLUMNS = [
    "rank",
    "zone_id",
    "source_day",
    "side",
    "source_timeframe",
    "source_family",
    "level_type",
    "label",
    "price_lower",
    "price_upper",
    "representative_price",
    "current_price",
    "distance_to_current_price_pct",
    "lifecycle_status",
    "status",
    "confidence",
    "bucket",
    "significance_score",
    "score_components_json",
    "penalty_components_json",
    "evidence_fields_present",
    "evidence_fields_missing",
    "flow_evidence_summary",
    "reason_selected",
    "reason_hidden",
    "visible_on_snapshot",
]

INPUT_TABLES = [
    "structure_levels.csv",
    "liquidity_map.csv",
    "liquidity_zone_registry.csv",
    "event_log.csv",
    "post_sweep_observation.csv",
    "volume_delta_state.csv",
    "market_state_timeline.csv",
    "accumulation_zones.csv",
    "pattern_structures.csv",
]

HIDDEN_STATUSES = {
    "EXPIRED",
    "INVALIDATED",
    "CONSUMED",
    "CHOPPED_THROUGH",
    "MERGED",
}


class SignificantZoneSelectorError(RuntimeError):
    """Raised when significant zone selection cannot be completed."""


@dataclass(frozen=True)
class SignificantZoneSelectorResult:
    output_dir: Path
    selected_zones_path: Path
    summary_path: Path
    manifest_path: Path
    total_candidate_count: int
    visible_zone_count: int
    visible_buy_side_count: int
    visible_sell_side_count: int


def run_significant_zone_selector(
    *,
    input_root: str | Path,
    output_dir: str | Path,
    start: str | date,
    end: str | date,
    max_visible_zones: int = 7,
) -> SignificantZoneSelectorResult:
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date > end_date:
        raise SignificantZoneSelectorError("start must be <= end")
    if max_visible_zones < 1:
        raise SignificantZoneSelectorError("max_visible_zones must be >= 1")

    root = Path(input_root)
    out_dir = Path(output_dir)
    if not root.exists() or not root.is_dir():
        raise SignificantZoneSelectorError(f"input root not found: {root}")
    out_dir.mkdir(parents=True, exist_ok=True)

    loaded = _load_window(root, start_date, end_date)
    liquidity_map = loaded["liquidity_map.csv"]
    if liquidity_map.empty:
        selected = pd.DataFrame(columns=SELECTED_ZONE_COLUMNS)
    else:
        selected = _score_candidates(loaded)
        selected = _assign_visibility(selected, max_visible_zones=max_visible_zones)
        selected = selected.sort_values(
            ["visible_on_snapshot", "significance_score", "source_day", "zone_id"],
            ascending=[False, False, True, True],
            kind="mergesort",
        ).reset_index(drop=True)
        selected["rank"] = range(1, len(selected) + 1)
        selected = selected[SELECTED_ZONE_COLUMNS]

    selected_path = out_dir / SELECTED_ZONES_CSV
    summary_path = out_dir / SELECTOR_SUMMARY_MD
    manifest_path = out_dir / SELECTOR_MANIFEST_JSON
    selected.to_csv(selected_path, index=False)

    row_counts = {name: int(len(frame)) for name, frame in loaded.items()}
    missing_flags = _missing_data_flags(loaded)
    summary_path.write_text(
        _render_summary(
            selected=selected,
            row_counts=row_counts,
            input_root=root,
            start_date=start_date,
            end_date=end_date,
            max_visible_zones=max_visible_zones,
            missing_flags=missing_flags,
        ),
        encoding="utf-8",
    )
    manifest = {
        "selector_version": SELECTOR_VERSION,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "input_root": str(root),
        "outputs": {
            "selected_zones_csv": str(selected_path),
            "summary_md": str(summary_path),
            "manifest_json": str(manifest_path),
        },
        "max_visible_zones": max_visible_zones,
        "visible_zone_count": _visible_zone_count(selected),
        "visible_side_counts": _visible_side_counts(selected),
        "side_balance_policy": _side_balance_policy(max_visible_zones),
        "total_candidate_count": int(len(selected)),
        "missing_data_flags": missing_flags,
        "repo_commit": _repo_commit(),
        "scope": "research_monitor_selection_only_not_trading_advice",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    visible = selected[selected["visible_on_snapshot"].astype(str) == "true"]
    return SignificantZoneSelectorResult(
        output_dir=out_dir,
        selected_zones_path=selected_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        total_candidate_count=int(len(selected)),
        visible_zone_count=int(len(visible)),
        visible_buy_side_count=int((visible["side"] == "BUY_SIDE").sum()) if not visible.empty else 0,
        visible_sell_side_count=int((visible["side"] == "SELL_SIDE").sum()) if not visible.empty else 0,
    )


def _load_window(root: Path, start_date: date, end_date: date) -> dict[str, pd.DataFrame]:
    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in INPUT_TABLES}
    for day in _date_range(start_date, end_date):
        day_dir = root / day.isoformat()
        if not day_dir.exists():
            raise SignificantZoneSelectorError(f"missing daily output directory: {day_dir}")
        for filename in INPUT_TABLES:
            path = day_dir / filename
            if path.exists():
                try:
                    frame = pd.read_csv(path)
                except pd.errors.EmptyDataError:
                    frame = pd.DataFrame()
            else:
                frame = pd.DataFrame()
            frame["_source_day"] = day.isoformat()
            frame["_source_path"] = str(path)
            frames[filename].append(frame)
    return {
        name: pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
        for name, parts in frames.items()
    }


def _score_candidates(loaded: dict[str, pd.DataFrame]) -> pd.DataFrame:
    liquidity_map = loaded["liquidity_map.csv"].copy()
    event_log = loaded["event_log.csv"]
    observations = loaded["post_sweep_observation.csv"]
    event_groups = _group_by_day_zone(event_log)
    observation_groups = _group_by_day_zone(observations)

    rows = []
    for _, zone in liquidity_map.iterrows():
        source_day = _string(zone.get("_source_day"))
        zone_id = _string(zone.get("zone_id"))
        events = event_groups.get((source_day, zone_id), pd.DataFrame())
        zone_observations = observation_groups.get((source_day, zone_id), pd.DataFrame())
        rows.append(_score_zone(zone, events, zone_observations))
    frame = pd.DataFrame(rows)
    return frame.sort_values(
        ["significance_score", "source_day", "zone_id"],
        ascending=[False, True, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _score_zone(zone: pd.Series, events: pd.DataFrame, observations: pd.DataFrame) -> dict[str, object]:
    score_components: dict[str, float] = {}
    penalty_components: dict[str, float] = {}
    evidence_present: set[str] = set()
    evidence_missing: set[str] = set()
    reasons: list[str] = []

    source_day = _string(zone.get("_source_day"))
    zone_id = _string(zone.get("zone_id"))
    side = _string(zone.get("side")) or "UNKNOWN"
    source_timeframe = _string(zone.get("source_timeframes")) or "UNKNOWN"
    source_family = _source_family(source_timeframe)
    label = _first_nonempty(
        zone.get("zone_type"),
        zone.get("htf_level_type"),
        _score_level_types(zone.get("score_components_json")),
    )
    level_type = _first_nonempty(zone.get("htf_level_type"), _score_level_types(zone.get("score_components_json")))
    status = _string(zone.get("status")) or "UNKNOWN"
    lifecycle_status = _first_nonempty(zone.get("htf_lifecycle_status"), zone.get("consumption_status"), status)
    confidence = _string(zone.get("confidence_tier")) or "UNKNOWN"
    representative_price = _float(zone.get("price_mid"))
    distance = _float(zone.get("distance_from_close_pct"))
    current_price = _current_price(representative_price, distance)
    sources = _split_sources(source_timeframe)

    _add_source_scores(zone, sources, score_components, evidence_present, reasons)
    _add_lifecycle_scores(status, lifecycle_status, score_components, penalty_components, reasons)
    _add_confidence_scores(confidence, score_components, penalty_components, reasons)
    _add_distance_scores(distance, score_components, penalty_components, evidence_present, reasons)
    _add_interaction_scores(zone, score_components, evidence_present, reasons)
    _add_precision_scores(zone, score_components, penalty_components, reasons)
    _add_event_scores(events, score_components, penalty_components, evidence_present, evidence_missing, reasons)
    _add_observation_scores(
        observations,
        score_components,
        evidence_present,
        evidence_missing,
        reasons,
    )
    _add_context_penalties(sources, events, observations, penalty_components, reasons)

    missing_data = _zone_missing_data_notes()
    evidence_missing.update(missing_data)

    raw_score = sum(score_components.values()) + sum(penalty_components.values())
    bucket = _bucket_for_zone(raw_score, sources, zone, status, events, observations)
    flow_summary = _flow_summary(events, observations)
    hidden_reason = _base_hidden_reason(
        bucket=bucket,
        status=status,
        lifecycle_status=lifecycle_status,
        events=events,
        observations=observations,
        sources=sources,
    )

    return {
        "rank": 0,
        "zone_id": zone_id,
        "source_day": source_day,
        "side": side,
        "source_timeframe": source_timeframe,
        "source_family": source_family,
        "level_type": level_type,
        "label": label,
        "price_lower": zone.get("price_lower", ""),
        "price_upper": zone.get("price_upper", ""),
        "representative_price": representative_price,
        "current_price": current_price,
        "distance_to_current_price_pct": distance,
        "lifecycle_status": lifecycle_status,
        "status": status,
        "confidence": confidence,
        "bucket": bucket,
        "significance_score": round(float(raw_score), 3),
        "score_components_json": json.dumps(score_components, sort_keys=True),
        "penalty_components_json": json.dumps(penalty_components, sort_keys=True),
        "evidence_fields_present": "|".join(sorted(evidence_present)),
        "evidence_fields_missing": "|".join(sorted(evidence_missing)),
        "flow_evidence_summary": flow_summary,
        "reason_selected": "; ".join(reasons[:12]),
        "reason_hidden": hidden_reason,
        "visible_on_snapshot": "false",
    }


def _assign_visibility(frame: pd.DataFrame, *, max_visible_zones: int) -> pd.DataFrame:
    out = frame.copy()
    out["visible_on_snapshot"] = "false"
    eligible = out[out.apply(_is_visibility_eligible, axis=1)].copy()
    if eligible.empty:
        return out

    eligible_indices = _visibility_sorted_indices(out, eligible.index)
    selected_indices = eligible_indices[:max_visible_zones]
    selected_indices = _rebalance_visible_sides(
        out,
        eligible_indices=eligible_indices,
        selected_indices=selected_indices,
        max_visible_zones=max_visible_zones,
    )

    out.loc[selected_indices, "visible_on_snapshot"] = "true"
    out.loc[out["visible_on_snapshot"] == "true", "reason_hidden"] = ""
    out.loc[
        (out["visible_on_snapshot"] == "false") & (out["reason_hidden"] == ""),
        "reason_hidden",
    ] = "outside max visible zone cap or lower ranked than selected zones"
    return out


def _rebalance_visible_sides(
    frame: pd.DataFrame,
    *,
    eligible_indices: list[int],
    selected_indices: list[int],
    max_visible_zones: int,
) -> list[int]:
    if max_visible_zones < 2:
        return selected_indices

    selected = list(selected_indices)
    available_sides = {
        _string(frame.loc[idx, "side"])
        for idx in eligible_indices
        if _string(frame.loc[idx, "side"]) in {"BUY_SIDE", "SELL_SIDE"}
    }
    if not {"BUY_SIDE", "SELL_SIDE"}.issubset(available_sides):
        return selected

    selected = _promote_to_side_minimum(
        frame,
        eligible_indices=eligible_indices,
        selected_indices=selected,
        side="BUY_SIDE",
        target_count=1,
        require_visible_side=True,
    )
    selected = _promote_to_side_minimum(
        frame,
        eligible_indices=eligible_indices,
        selected_indices=selected,
        side="SELL_SIDE",
        target_count=1,
        require_visible_side=True,
    )

    if max_visible_zones >= 6:
        for side in ["BUY_SIDE", "SELL_SIDE"]:
            if _eligible_side_count(frame, eligible_indices, side) >= 2:
                selected = _promote_to_side_minimum(
                    frame,
                    eligible_indices=eligible_indices,
                    selected_indices=selected,
                    side=side,
                    target_count=2,
                    require_visible_side=False,
                )
    return _visibility_sorted_indices(frame, selected)[:max_visible_zones]


def _promote_to_side_minimum(
    frame: pd.DataFrame,
    *,
    eligible_indices: list[int],
    selected_indices: list[int],
    side: str,
    target_count: int,
    require_visible_side: bool,
) -> list[int]:
    selected = list(selected_indices)
    while _selected_side_count(frame, selected, side) < target_count:
        candidate = _best_hidden_side_candidate(frame, eligible_indices, selected, side)
        if candidate is None:
            return selected
        displaced = _replacement_index_for_side_balance(
            frame,
            selected,
            candidate,
            require_visible_side=require_visible_side,
        )
        if displaced is None:
            return selected
        selected.remove(displaced)
        selected.append(candidate)
        _append_reason(frame, candidate, "reason_selected", SIDE_BALANCE_PROMOTION_REASON)
        frame.loc[displaced, "reason_hidden"] = SIDE_BALANCE_DISPLACED_REASON
    return selected


def _best_hidden_side_candidate(
    frame: pd.DataFrame,
    eligible_indices: list[int],
    selected_indices: list[int],
    side: str,
) -> int | None:
    selected = set(selected_indices)
    for idx in eligible_indices:
        if idx in selected:
            continue
        row = frame.loc[idx]
        if _string(row.get("side")) != side:
            continue
        if _is_side_balance_candidate(row):
            return idx
    return None


def _replacement_index_for_side_balance(
    frame: pd.DataFrame,
    selected_indices: list[int],
    candidate_idx: int,
    *,
    require_visible_side: bool,
) -> int | None:
    candidate = frame.loc[candidate_idx]
    candidate_side = _string(candidate.get("side"))
    candidate_score = _float(candidate.get("significance_score"))
    side_counts = {
        side: _selected_side_count(frame, selected_indices, side)
        for side in ["BUY_SIDE", "SELL_SIDE"]
    }
    overrepresented_sides = [
        side for side, count in side_counts.items() if side != candidate_side and count > 1
    ]
    if not overrepresented_sides:
        return None

    replacement_pool = [
        idx
        for idx in selected_indices
        if _string(frame.loc[idx].get("side")) in overrepresented_sides
    ]
    for replace_idx in reversed(_visibility_sorted_indices(frame, replacement_pool)):
        replacement = frame.loc[replace_idx]
        if require_visible_side:
            return replace_idx
        replacement_score = _float(replacement.get("significance_score"))
        if replacement_score - candidate_score > 10:
            continue
        if _candidate_can_replace(candidate, replacement):
            return replace_idx
    return None


def _candidate_can_replace(candidate: pd.Series, replacement: pd.Series) -> bool:
    candidate_distance = abs(_float(candidate.get("distance_to_current_price_pct"), 999.0))
    replacement_distance = abs(_float(replacement.get("distance_to_current_price_pct"), 999.0))
    if candidate_distance < replacement_distance:
        return True
    if _bucket_strength(candidate.get("bucket")) > _bucket_strength(replacement.get("bucket")):
        return True
    return _source_strength(candidate.get("source_timeframe")) > _source_strength(replacement.get("source_timeframe"))


def _is_side_balance_candidate(row: pd.Series) -> bool:
    if _string(row.get("bucket")) not in {BUCKET_MAJOR, BUCKET_PRIMARY}:
        return False
    if not _valid_price_range(row):
        return False
    if _string(row.get("side")) not in {"BUY_SIDE", "SELL_SIDE"}:
        return False
    distance = abs(_float(row.get("distance_to_current_price_pct"), 999.0))
    return distance <= 2.0 or _has_strong_structural_or_event_evidence(row)


def _valid_price_range(row: pd.Series) -> bool:
    lower = _float(row.get("price_lower"))
    upper = _float(row.get("price_upper"))
    return not pd.isna(lower) and not pd.isna(upper) and lower <= upper


def _has_strong_structural_or_event_evidence(row: pd.Series) -> bool:
    present = set(_string(row.get("evidence_fields_present")).split("|"))
    return bool({"has_h4_source", "has_h1_source", "event_log", "post_sweep_observation"} & present)


def _eligible_side_count(frame: pd.DataFrame, eligible_indices: list[int], side: str) -> int:
    return sum(1 for idx in eligible_indices if _string(frame.loc[idx].get("side")) == side)


def _selected_side_count(frame: pd.DataFrame, selected_indices: list[int], side: str) -> int:
    return sum(1 for idx in selected_indices if _string(frame.loc[idx].get("side")) == side)


def _visibility_sorted_indices(frame: pd.DataFrame, indices: Iterable[int]) -> list[int]:
    return sorted((int(idx) for idx in indices), key=lambda idx: _visibility_priority_key(frame.loc[idx], idx))


def _visibility_priority_key(row: pd.Series, idx: int) -> tuple[float, float, int, int, str, int]:
    return (
        -_float(row.get("significance_score")),
        abs(_float(row.get("distance_to_current_price_pct"), 999.0)),
        -_bucket_strength(row.get("bucket")),
        -_source_strength(row.get("source_timeframe")),
        _string(row.get("zone_id")),
        idx,
    )


def _bucket_strength(bucket: object) -> int:
    return {
        BUCKET_MAJOR: 4,
        BUCKET_PRIMARY: 3,
        BUCKET_MINIMUM: 2,
        BUCKET_LOCAL_CONTEXT: 1,
    }.get(_string(bucket), 0)


def _source_strength(source_timeframe: object) -> int:
    sources = _split_sources(source_timeframe)
    if "H4" in sources:
        return 4
    if "H1" in sources:
        return 3
    if "M15" in sources:
        return 2
    if "SESSION" in sources:
        return 1
    return 0


def _append_reason(frame: pd.DataFrame, idx: int, column: str, reason: str) -> None:
    existing = _string(frame.loc[idx, column])
    if reason in existing:
        return
    frame.loc[idx, column] = f"{existing}; {reason}" if existing else reason


def _is_visibility_eligible(row: pd.Series) -> bool:
    if row["bucket"] == BUCKET_NOISE:
        return False
    if row["status"] in HIDDEN_STATUSES:
        return False
    if row["status"] == "CROSSED_UNCLASSIFIED" and not _has_supporting_evidence(row):
        return False
    if row["bucket"] in {BUCKET_MAJOR, BUCKET_PRIMARY}:
        return True
    if row["bucket"] == BUCKET_MINIMUM:
        return abs(_float(row["distance_to_current_price_pct"], 999.0)) <= 1.0 and _has_supporting_evidence(row)
    return False


def _has_supporting_evidence(row: pd.Series) -> bool:
    present = set(_string(row.get("evidence_fields_present")).split("|"))
    return bool({"event_log", "post_sweep_observation", "sweep_count", "touch_count"} & present)


def _visible_zone_count(selected: pd.DataFrame) -> int:
    if selected.empty:
        return 0
    return int((selected["visible_on_snapshot"].astype(str) == "true").sum())


def _visible_side_counts(selected: pd.DataFrame) -> dict[str, int]:
    if selected.empty:
        return {}
    visible = selected[selected["visible_on_snapshot"].astype(str) == "true"]
    return {key: int(value) for key, value in visible["side"].value_counts().to_dict().items()}


def _side_balance_policy(max_visible_zones: int) -> str:
    if max_visible_zones >= 6:
        return "require one zone per side when available; prefer two zones per side from eligible MAJOR/PRIMARY zones within score gap"
    if max_visible_zones >= 2:
        return "require one zone per side when available"
    return "single visible zone cap cannot preserve both sides"


def _side_balance_note(selected: pd.DataFrame, max_visible_zones: int) -> str:
    if selected.empty:
        return "no candidate zones"
    visible_counts = _visible_side_counts(selected)
    if max_visible_zones < 6:
        return "visible cap below six only guarantees one zone per side when available"
    notes = []
    for side in ["BUY_SIDE", "SELL_SIDE"]:
        eligible_count = int(
            selected[
                (selected["side"] == side)
                & selected.apply(_is_visibility_eligible, axis=1)
                & selected.apply(_is_side_balance_candidate, axis=1)
            ].shape[0]
        )
        visible_count = visible_counts.get(side, 0)
        if eligible_count < 2:
            notes.append(f"{side} has fewer than two high-quality eligible zones")
        elif visible_count < 2:
            notes.append(f"{side} has fewer than two visible zones because score-gap replacement criteria were not met")
    return "; ".join(notes) if notes else "both sides preserved when high-quality eligible zones were available"


def _add_source_scores(
    zone: pd.Series,
    sources: set[str],
    score: dict[str, float],
    evidence: set[str],
    reasons: list[str],
) -> None:
    if "H4" in sources or _truth(zone.get("has_h4_source")):
        score["h4_source"] = 40
        evidence.add("has_h4_source")
        reasons.append("H4 structural source")
    if "H1" in sources or _truth(zone.get("has_h1_source")):
        score["h1_source"] = 24
        evidence.add("has_h1_source")
        reasons.append("H1 structural source")
    if _truth(zone.get("has_pdh_pdl_source")) or _contains_any(zone.get("zone_type"), ["PDH", "PDL"]):
        score["pdh_pdl_source"] = 32
        evidence.add("has_pdh_pdl_source")
        reasons.append("previous day reference")
    if "M15" in sources:
        score["m15_source"] = 12
        evidence.add("m15_source")
        reasons.append("M15 structure")
    if "SESSION" in sources or _truth(zone.get("has_session_source")):
        score["session_context"] = 6
        evidence.add("has_session_source")
        reasons.append("session/local context")
    if _truth(zone.get("has_equal_level_source")):
        score["equal_level_source"] = 8
        evidence.add("has_equal_level_source")
        reasons.append("equal high/low liquidity pool")
    cluster_count = _int(zone.get("cluster_member_count"))
    if "CLUSTER" in sources or cluster_count > 1:
        score["source_cluster"] = min(16, 4 * max(cluster_count, 2))
        evidence.add("cluster_member_count")
        reasons.append(f"clustered sources={cluster_count}")


def _add_lifecycle_scores(
    status: str,
    lifecycle_status: str,
    score: dict[str, float],
    penalty: dict[str, float],
    reasons: list[str],
) -> None:
    if status == "ACTIVE" or lifecycle_status == "ACTIVE":
        score["active_lifecycle"] = 15
        reasons.append("active lifecycle")
    if status in {"EXPIRED", "INVALIDATED"}:
        penalty["expired_or_invalidated"] = -35
        reasons.append(f"hidden lifecycle={status}")
    elif status in {"CONSUMED", "CHOPPED_THROUGH", "MERGED"}:
        penalty["consumed_or_chopped_or_merged"] = -24
        reasons.append(f"penalty lifecycle={status}")
    elif status == "CROSSED_UNCLASSIFIED":
        penalty["crossed_unclassified"] = -18
        reasons.append("crossed but unclassified")


def _add_confidence_scores(
    confidence: str,
    score: dict[str, float],
    penalty: dict[str, float],
    reasons: list[str],
) -> None:
    if confidence == "HIGH":
        score["high_confidence"] = 12
        reasons.append("high confidence")
    elif confidence == "MEDIUM":
        score["medium_confidence"] = 6
        reasons.append("medium confidence")
    else:
        penalty["low_or_unknown_confidence"] = -6
        reasons.append("low/unknown confidence")


def _add_distance_scores(
    distance: float,
    score: dict[str, float],
    penalty: dict[str, float],
    evidence: set[str],
    reasons: list[str],
) -> None:
    if not pd.isna(distance):
        evidence.add("distance_to_current_price_pct")
    absolute = abs(distance)
    if absolute <= 0.5:
        score["distance_within_0_5_pct"] = 18
        reasons.append("near current price <=0.5 pct")
    elif absolute <= 1.0:
        score["distance_within_1_pct"] = 12
        reasons.append("near current price <=1 pct")
    elif absolute <= 2.0:
        score["distance_within_2_pct"] = 6
        reasons.append("near current price <=2 pct")
    elif absolute > 5.0:
        penalty["far_from_current_price"] = -12
        reasons.append("far from current price >5 pct")


def _add_interaction_scores(
    zone: pd.Series,
    score: dict[str, float],
    evidence: set[str],
    reasons: list[str],
) -> None:
    touch_count = max(_int(zone.get("touch_count")), _int(zone.get("m1_interaction_count")))
    if touch_count > 0:
        score["touch_or_retest_history"] = min(8, touch_count * 2)
        evidence.add("touch_count")
        reasons.append(f"touch/retest count={touch_count}")
    sweep_count = max(_int(zone.get("sweep_count")), _int(zone.get("resweep_count")), _int(zone.get("htf_sweep_count")))
    if sweep_count > 0:
        score["sweep_history"] = min(30, sweep_count * 10)
        evidence.add("sweep_count")
        reasons.append(f"sweep history={sweep_count}")
    recent = _first_nonempty(
        zone.get("last_touch_at"),
        zone.get("last_clean_reaction_at"),
        zone.get("first_sweep_at"),
        zone.get("drift_away_confirmed_at"),
    )
    if recent:
        score["recent_interaction"] = 6
        evidence.add("recent_interaction_timestamp")
        reasons.append("recent interaction present")


def _add_precision_scores(
    zone: pd.Series,
    score: dict[str, float],
    penalty: dict[str, float],
    reasons: list[str],
) -> None:
    if _string(zone.get("precision_status")) == "PRECISE":
        score["precise_zone_width"] = 4
        reasons.append("precise width")
    else:
        penalty["imprecise_or_wide_zone"] = -8
        reasons.append("imprecise/wide zone")
    if _float(zone.get("zone_width_pct")) > 0.5:
        penalty["hard_wide_zone_width"] = -8
        reasons.append("wide zone width pct")


def _add_event_scores(
    events: pd.DataFrame,
    score: dict[str, float],
    penalty: dict[str, float],
    present: set[str],
    missing: set[str],
    reasons: list[str],
) -> None:
    if events.empty:
        missing.add("event_log")
        penalty["missing_event_evidence"] = -4
        return
    present.add("event_log")
    score["event_evidence"] = min(12, len(events) * 3)
    reasons.append(f"event evidence count={len(events)}")
    max_excursion = _column_abs_max(events, "excursion_abs")
    if max_excursion > 0:
        score["excursion_magnitude"] = min(8, max_excursion / 100)
        present.add("excursion_abs")
    max_volume = _column_abs_max(events, "volume_zscore")
    if max_volume >= 2:
        score["volume_anomaly"] = 8
        present.add("volume_zscore")
        reasons.append(f"volume anomaly z={max_volume:.2f}")
    else:
        missing.add("volume_anomaly")
    max_delta = _column_abs_max(events, "delta_zscore")
    if max_delta >= 2:
        score["delta_anomaly"] = 8
        present.add("delta_zscore")
        reasons.append(f"delta anomaly z={max_delta:.2f}")
    else:
        missing.add("delta_anomaly")
    if _column_abs_max(events, "oi_change") > 0:
        score["oi_context"] = 4
        present.add("oi_change")
    else:
        missing.add("oi_context")


def _add_observation_scores(
    observations: pd.DataFrame,
    score: dict[str, float],
    present: set[str],
    missing: set[str],
    reasons: list[str],
) -> None:
    if observations.empty:
        missing.add("post_sweep_observation")
        return
    present.add("post_sweep_observation")
    score["post_sweep_observation"] = min(10, len(observations) * 2)
    reasons.append(f"post-sweep observations={len(observations)}")
    if _column_abs_max(observations, "post_max_volume_zscore") >= 2:
        score["post_sweep_volume_context"] = 5
        present.add("post_max_volume_zscore")
    if _column_abs_max(observations, "post_max_abs_delta_zscore") >= 2:
        score["post_sweep_delta_context"] = 5
        present.add("post_max_abs_delta_zscore")
    if _column_abs_max(observations, "post_oi_change") > 0:
        score["post_sweep_oi_context"] = 4
        present.add("post_oi_change")
    verdicts = [_reaction_verdict(row.get("evidence_json")) for _, row in observations.iterrows()]
    if any(verdict not in {"", "NOT_CLASSIFIED", "UNCLASSIFIED", "NONE"} for verdict in verdicts):
        score["classified_post_sweep_reaction"] = 10
        present.add("reaction_verdict")
        reasons.append("classified post-sweep reaction")
    else:
        missing.add("classified_post_sweep_reaction")


def _add_context_penalties(
    sources: set[str],
    events: pd.DataFrame,
    observations: pd.DataFrame,
    penalty: dict[str, float],
    reasons: list[str],
) -> None:
    if sources and sources.issubset({"SESSION"}) and events.empty and observations.empty:
        penalty["session_only_without_event_evidence"] = -10
        reasons.append("session-only without event evidence")
    if "PATTERN" in sources:
        penalty["pattern_only_low_confidence_context"] = -6
        reasons.append("pattern source treated as context only")


def _bucket_for_zone(
    score: float,
    sources: set[str],
    zone: pd.Series,
    status: str,
    events: pd.DataFrame,
    observations: pd.DataFrame,
) -> str:
    if status in HIDDEN_STATUSES:
        return BUCKET_NOISE
    if sources.issubset({"SESSION"}) and events.empty and observations.empty:
        return BUCKET_LOCAL_CONTEXT if score >= 35 else BUCKET_NOISE
    has_major = "H4" in sources or _truth(zone.get("has_h4_source")) or _truth(zone.get("has_pdh_pdl_source"))
    if score >= 85 and has_major:
        return BUCKET_MAJOR
    if score >= 60 and ("H1" in sources or _truth(zone.get("has_h1_source")) or has_major):
        return BUCKET_PRIMARY
    if score >= 35 and "M15" in sources:
        return BUCKET_MINIMUM
    if score >= 35:
        return BUCKET_LOCAL_CONTEXT
    return BUCKET_NOISE


def _base_hidden_reason(
    *,
    bucket: str,
    status: str,
    lifecycle_status: str,
    events: pd.DataFrame,
    observations: pd.DataFrame,
    sources: set[str],
) -> str:
    if bucket == BUCKET_NOISE:
        return "noise or hide-by-default bucket"
    if status in HIDDEN_STATUSES or lifecycle_status in HIDDEN_STATUSES:
        return f"hidden lifecycle/status={status or lifecycle_status}"
    if status == "CROSSED_UNCLASSIFIED" and events.empty and observations.empty:
        return "crossed-unclassified without supporting event or observation evidence"
    if bucket == BUCKET_LOCAL_CONTEXT:
        return "local/session context, not dominant snapshot zone"
    if sources.issubset({"SESSION"}):
        return "session-only context"
    return ""


def _render_summary(
    *,
    selected: pd.DataFrame,
    row_counts: dict[str, int],
    input_root: Path,
    start_date: date,
    end_date: date,
    max_visible_zones: int,
    missing_flags: dict[str, str],
) -> str:
    visible = selected[selected["visible_on_snapshot"].astype(str) == "true"] if not selected.empty else selected
    hidden = selected[selected["visible_on_snapshot"].astype(str) != "true"] if not selected.empty else selected
    bucket_counts = selected["bucket"].value_counts().to_dict() if not selected.empty else {}
    side_counts = selected["side"].value_counts().to_dict() if not selected.empty else {}
    visible_side_counts = _visible_side_counts(selected)

    lines = [
        "# Significant Zone Selector Summary",
        "",
        "Research monitor selection only. This is not trading advice.",
        "",
        "## Inputs",
        "",
        f"- Date range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"- Input root: `{input_root}`",
        f"- Max visible zones: {max_visible_zones}",
        "",
        "## Row Counts",
        "",
    ]
    lines.extend(f"- `{name}`: {count}" for name, count in sorted(row_counts.items()))
    lines.extend(
        [
            "",
            "## Zone Inventory Counts",
            "",
            f"- Total candidate zones: {len(selected)}",
            f"- Visible zones: {len(visible)}",
            f"- Side counts: {json.dumps(side_counts, sort_keys=True)}",
            f"- Visible side counts: {json.dumps(visible_side_counts, sort_keys=True)}",
            f"- Bucket counts: {json.dumps(bucket_counts, sort_keys=True)}",
            f"- Side balance policy: {_side_balance_policy(max_visible_zones)}.",
            f"- Side balance note: {_side_balance_note(selected, max_visible_zones)}",
            "",
            "## Scoring Model Summary",
            "",
            "- Priority sequence: H4 major structure > H1 primary structure > M15 minimum structure > SESSION/local context.",
            "- Positive components: structural source weight, PDH/PDL, equal level source, clustering, lifecycle, confidence, proximity, touch/retest, sweep, event, flow, OI, post-sweep observation, reaction, and precision.",
            "- Negative components: expired/invalidated/consumed/chopped/merged lifecycle, crossed-unclassified without support, distance, old/no recent interaction, local-only clutter, pattern context, imprecision, and missing evidence.",
            "",
            "## Visible Selected Zones",
            "",
            _markdown_table(
                visible,
                ["rank", "source_day", "zone_id", "side", "bucket", "significance_score", "reason_selected"],
            ),
            "",
            "## Hidden Top-Ranked Zones",
            "",
            _markdown_table(
                hidden.head(10),
                ["rank", "source_day", "zone_id", "side", "bucket", "significance_score", "reason_hidden"],
            ),
            "",
            "## Missing Data Notes",
            "",
        ]
    )
    lines.extend(f"- {key}: {value}" for key, value in sorted(missing_flags.items()))
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Selector consumes existing Market Monitor outputs only; it does not create new market logic.",
            "- Compression boundaries are not faked when first-class compression zones are unavailable.",
            "- Liquidation and VWAP confirmations are marked unavailable when absent.",
            "- Scores are deterministic v0 selection weights, not strategy validation.",
        ]
    )
    return "\n".join(lines) + "\n"


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "_None_"
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        values = [_escape_markdown(_string(row.get(column))) for column in columns]
        out.append("| " + " | ".join(values) + " |")
    return "\n".join(out)


def _missing_data_flags(loaded: dict[str, pd.DataFrame]) -> dict[str, str]:
    accumulation = loaded["accumulation_zones.csv"]
    volume_delta = loaded["volume_delta_state.csv"]
    return {
        "liquidations": _liquidation_availability(volume_delta),
        "vwap": "not_available",
        "compression": "not_available" if accumulation.empty else "partial",
    }


def _liquidation_availability(volume_delta: pd.DataFrame) -> str:
    required = {"liq_buy_qty", "liq_sell_qty"}
    if volume_delta.empty or not required.issubset(volume_delta.columns):
        return "not_available"
    values = (
        pd.to_numeric(volume_delta["liq_buy_qty"], errors="coerce").fillna(0).abs()
        + pd.to_numeric(volume_delta["liq_sell_qty"], errors="coerce").fillna(0).abs()
    )
    return "available" if float(values.sum()) > 0 else "available_zero"


def _zone_missing_data_notes() -> set[str]:
    return {"liquidations=not_available", "vwap=not_available", "compression=not_available_or_partial"}


def _flow_summary(events: pd.DataFrame, observations: pd.DataFrame) -> str:
    event_count = 0 if events.empty else len(events)
    observation_count = 0 if observations.empty else len(observations)
    max_volume = max(_column_abs_max(events, "volume_zscore"), _column_abs_max(observations, "post_max_volume_zscore"))
    max_delta = max(_column_abs_max(events, "delta_zscore"), _column_abs_max(observations, "post_max_abs_delta_zscore"))
    max_oi = max(_column_abs_max(events, "oi_change"), _column_abs_max(observations, "post_oi_change"))
    return (
        f"events={event_count}; post_sweep_observations={observation_count}; "
        f"max_volume_zscore={max_volume:.3f}; max_abs_delta_zscore={max_delta:.3f}; "
        f"max_abs_oi_change={max_oi:.3f}; liquidations=not_available; vwap=not_available"
    )


def _group_by_day_zone(frame: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    if frame.empty or "zone_id" not in frame.columns:
        return {}
    grouped = {}
    for key, group in frame.groupby(["_source_day", "zone_id"], dropna=False, sort=False):
        grouped[(str(key[0]), str(key[1]))] = group.copy()
    return grouped


def _source_family(source_timeframe: str) -> str:
    sources = _split_sources(source_timeframe)
    if "H4" in sources:
        return "H4_MAJOR_STRUCTURE"
    if "H1" in sources:
        return "H1_PRIMARY_STRUCTURE"
    if "M15" in sources:
        return "M15_MINIMUM_STRUCTURE"
    if "SESSION" in sources:
        return "SESSION_LOCAL_CONTEXT"
    if "PATTERN" in sources:
        return "PATTERN_CONTEXT"
    return "UNKNOWN_CONTEXT"


def _split_sources(value: object) -> set[str]:
    text = _string(value).replace(",", "|")
    return {part.strip() for part in text.split("|") if part.strip()} or {"UNKNOWN"}


def _score_level_types(raw_json: object) -> str:
    try:
        data = json.loads(_string(raw_json) or "{}")
    except json.JSONDecodeError:
        return ""
    return _string(data.get("level_types"))


def _reaction_verdict(raw_json: object) -> str:
    try:
        data = json.loads(_string(raw_json) or "{}")
    except json.JSONDecodeError:
        return ""
    return _string(data.get("reaction_verdict"))


def _column_abs_max(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = pd.to_numeric(frame[column], errors="coerce").abs().fillna(0)
    return float(values.max()) if not values.empty else 0.0


def _current_price(representative_price: float, distance_pct: float) -> float:
    if pd.isna(representative_price) or pd.isna(distance_pct):
        return representative_price
    denominator = 1.0 + (distance_pct / 100.0)
    if denominator == 0:
        return representative_price
    return representative_price / denominator


def _parse_date(value: str | date, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SignificantZoneSelectorError(f"{field_name} must be YYYY-MM-DD") from exc


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    days = (end_date - start_date).days
    for offset in range(days + 1):
        yield start_date + timedelta(days=offset)


def _repo_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _float(value: object, default: float = float("nan")) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _truth(value: object) -> bool:
    return _string(value).lower() == "true"


def _contains_any(value: object, candidates: list[str]) -> bool:
    text = _string(value).upper()
    return any(candidate in text for candidate in candidates)


def _first_nonempty(*values: object) -> str:
    for value in values:
        text = _string(value)
        if text:
            return text
    return ""


def _string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)


def _escape_markdown(value: str) -> str:
    return value.replace("|", "/").replace("\n", " ")
