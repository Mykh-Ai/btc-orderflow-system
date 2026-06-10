from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from market_monitor.events import GROUPING_WINDOW_MODE, MARKET_MOVE_GROUP_WINDOW_MINUTES


TAXONOMY_VERSION = "SWEEP_LABEL_TAXONOMY_V1"

SWEEP_REJECTED = "SWEEP_REJECTED"
SWEEP_ACCEPTED = "SWEEP_ACCEPTED"
SWEEP_UNRESOLVED = "SWEEP_UNRESOLVED"
SWEEP_NO_LABEL = "SWEEP_NO_LABEL"
SWEEP_INVALID_SAMPLE = "SWEEP_INVALID_SAMPLE"

ALLOWED_SWEEP_LABELS = {
    SWEEP_REJECTED,
    SWEEP_ACCEPTED,
    SWEEP_UNRESOLVED,
    SWEEP_NO_LABEL,
    SWEEP_INVALID_SAMPLE,
}

REJECTED_CLOSE_INSIDE_MINUTES = 10
REJECTED_BARS_INSIDE_MIN = 3
RETURN_INSIDE_ZONE_WIDTH_FRACTION = 0.5
ACCEPTED_BARS_BEYOND_MIN = 24
ACCEPTED_BARS_INSIDE_MAX = 2

SWEEP_LABEL_TAXONOMY_COLUMNS = [
    "taxonomy_version",
    "market_move_id",
    "label",
    "label_reason",
    "label_evidence_json",
    "primary_event_id",
    "primary_observation_id",
    "primary_zone_id",
    "side",
    "source_event_timestamp",
    "group_start_timestamp",
    "group_end_timestamp",
    "group_span_minutes",
    "market_move_event_count",
    "precision_status",
    "group_precision_statuses",
    "confidence_score",
    "confidence_tier",
    "zone_price_lower",
    "zone_price_upper",
    "zone_price_mid",
    "zone_width",
    "zone_width_pct",
    "observation_complete",
    "observation_bars_expected",
    "observation_bars_available",
    "first_return_inside_at",
    "first_close_inside_at",
    "bars_inside_zone",
    "bars_above_zone",
    "bars_below_zone",
    "max_return_inside_zone",
    "max_excursion_beyond_zone",
    "close_at_window_end",
    "data_quality",
]

SWEEP_LABEL_SUMMARY_COLUMNS = [
    "taxonomy_version",
    "label",
    "count",
    "share",
    "complete_count",
    "incomplete_count",
    "buy_side_count",
    "sell_side_count",
    "high_confidence_count",
    "medium_confidence_count",
    "low_confidence_count",
    "precise_count",
    "low_precision_count",
    "too_wide_count",
]


@dataclass(frozen=True)
class SweepLabelResult:
    taxonomy_path: Path
    summary_path: Path
    taxonomy: pd.DataFrame
    summary: pd.DataFrame
    label_counts: dict[str, int]
    clean_labelable_count: int
    no_label_count: int
    invalid_sample_count: int


def build_sweep_label_outputs(
    run_output_dir: str | Path,
    output_dir: str | Path | None = None,
    taxonomy_version: str = TAXONOMY_VERSION,
) -> SweepLabelResult:
    run_dir = Path(run_output_dir)
    out_dir = Path(output_dir) if output_dir is not None else run_dir
    observations = _read_csv(run_dir / "post_sweep_observation.csv")
    groups = _read_csv(run_dir / "market_move_groups.csv")
    taxonomy, summary = build_sweep_label_frames(
        observations=observations,
        market_move_groups=groups,
        taxonomy_version=taxonomy_version,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    taxonomy_path = out_dir / "sweep_label_taxonomy.csv"
    summary_path = out_dir / "sweep_label_summary.csv"
    taxonomy.to_csv(taxonomy_path, index=False)
    summary.to_csv(summary_path, index=False)
    return _result(taxonomy_path, summary_path, taxonomy, summary)


def build_sweep_label_frames(
    *,
    observations: pd.DataFrame,
    market_move_groups: pd.DataFrame | None = None,
    taxonomy_version: str = TAXONOMY_VERSION,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations = observations.copy()
    groups = market_move_groups.copy() if market_move_groups is not None else pd.DataFrame()
    if observations.empty and groups.empty:
        taxonomy = pd.DataFrame(columns=SWEEP_LABEL_TAXONOMY_COLUMNS)
        return taxonomy, _summary_frame(taxonomy, taxonomy_version)

    for column in _observation_required_columns():
        if column not in observations.columns:
            observations[column] = ""
    group_by_move = _groups_by_move(groups)

    move_ids = _market_move_ids(observations, groups)
    rows = [
        _label_row(
            move_id=move_id,
            observations=observations[observations["market_move_id"].astype(str) == move_id],
            group=group_by_move.get(move_id, {}),
            taxonomy_version=taxonomy_version,
        )
        for move_id in move_ids
    ]
    taxonomy = pd.DataFrame(rows, columns=SWEEP_LABEL_TAXONOMY_COLUMNS)
    taxonomy = taxonomy.sort_values(
        ["source_event_timestamp", "market_move_id"], kind="mergesort"
    ).reset_index(drop=True)
    return taxonomy[SWEEP_LABEL_TAXONOMY_COLUMNS], _summary_frame(taxonomy, taxonomy_version)


def label_stats(taxonomy: pd.DataFrame) -> dict[str, object]:
    if taxonomy.empty:
        return {
            "label_counts": {label: 0 for label in sorted(ALLOWED_SWEEP_LABELS)},
            "clean_labelable_count": 0,
            "no_label_count": 0,
            "invalid_sample_count": 0,
        }
    counts = taxonomy["label"].value_counts().sort_index()
    label_counts = {label: int(counts.get(label, 0)) for label in sorted(ALLOWED_SWEEP_LABELS)}
    return {
        "label_counts": label_counts,
        "clean_labelable_count": int(
            len(taxonomy)
            - label_counts[SWEEP_NO_LABEL]
            - label_counts[SWEEP_INVALID_SAMPLE]
        ),
        "no_label_count": label_counts[SWEEP_NO_LABEL],
        "invalid_sample_count": label_counts[SWEEP_INVALID_SAMPLE],
    }


def format_label_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{label}={int(counts.get(label, 0))}" for label in sorted(ALLOWED_SWEEP_LABELS))


def _label_row(
    *,
    move_id: str,
    observations: pd.DataFrame,
    group: dict[str, object],
    taxonomy_version: str,
) -> dict[str, object]:
    invalid_reason = _structural_invalid_reason(move_id, observations)
    primary = (
        pd.Series(dtype=object)
        if invalid_reason or observations.empty
        else _primary_row(observations)
    )
    group_precision = str(group.get("precision_statuses", ""))
    if not group_precision and not primary.empty:
        group_precision = str(primary.get("precision_status", ""))

    base = _base_row(
        taxonomy_version=taxonomy_version,
        move_id=move_id,
        primary=primary,
        group=group,
        group_precision=group_precision,
    )
    if invalid_reason:
        return _with_label(base, SWEEP_INVALID_SAMPLE, invalid_reason, invalid_reason=invalid_reason)

    invalid_reason = _field_invalid_reason(primary, group_precision)
    if invalid_reason:
        return _with_label(base, SWEEP_INVALID_SAMPLE, invalid_reason, invalid_reason=invalid_reason)

    no_label_reason = _no_label_reason(primary, group_precision)
    if no_label_reason:
        return _with_label(base, SWEEP_NO_LABEL, no_label_reason, exclusion_reason=no_label_reason)

    rejected_reason = _rejected_reason(primary)
    if rejected_reason:
        return _with_label(base, SWEEP_REJECTED, rejected_reason)

    accepted_reason = _accepted_reason(primary)
    if accepted_reason:
        return _with_label(base, SWEEP_ACCEPTED, accepted_reason)

    return _with_label(base, SWEEP_UNRESOLVED, "eligible_but_ambiguous")


def _structural_invalid_reason(move_id: str, observations: pd.DataFrame) -> str:
    if not move_id:
        return "missing_market_move_id"
    if observations.empty:
        return "missing_post_sweep_observation_row"
    primary_count = int((observations["market_move_role"].astype(str) == "PRIMARY").sum())
    if primary_count == 0:
        return "missing_primary_observation_row"
    if primary_count > 1:
        return "multiple_primary_observation_rows"
    return ""


def _field_invalid_reason(primary: pd.Series, group_precision: str) -> str:
    if str(primary.get("side", "")) not in {"BUY_SIDE", "SELL_SIDE"}:
        return "invalid_side"
    for column in [
        "zone_price_lower",
        "zone_price_upper",
        "zone_width",
        "source_event_timestamp",
        "market_move_event_count",
        "group_span_minutes",
        "observation_bars_expected",
        "observation_bars_available",
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "max_return_inside_zone",
        "max_excursion_beyond_zone",
        "close_at_window_end",
    ]:
        if _is_missing(primary.get(column, "")):
            return f"missing_{column}"
    lower = _float(primary.get("zone_price_lower"))
    upper = _float(primary.get("zone_price_upper"))
    width = _float(primary.get("zone_width"))
    if lower is None or upper is None or width is None:
        return "non_numeric_zone_bounds"
    if upper <= lower:
        return "zone_price_upper_not_above_lower"
    if width <= 0:
        return "zone_width_not_positive"
    if str(primary.get("data_quality", "")) != "RAW":
        return "non_raw_data_quality"
    if str(primary.get("precision_status", "")) == "TOO_WIDE" or "TOO_WIDE" in group_precision.split("|"):
        return "too_wide_precision"
    event_ts = _timestamp(primary.get("source_event_timestamp", ""))
    start_ts = _timestamp(primary.get("observation_start_timestamp", ""))
    if event_ts is None:
        return "invalid_source_event_timestamp"
    if start_ts is not None and start_ts <= event_ts:
        return "observation_start_not_after_event"
    return ""


def _no_label_reason(primary: pd.Series, group_precision: str) -> str:
    if not _bool(primary.get("observation_complete", False)):
        return "incomplete_observation"
    if str(primary.get("precision_status", "")) == "LOW_PRECISION":
        return "low_precision_primary"
    if "LOW_PRECISION" in group_precision.split("|"):
        return "low_precision_group"
    if str(primary.get("precision_status", "")) != "PRECISE":
        return "non_precise_primary"
    if group_precision != "PRECISE":
        return "non_precise_group"
    if _int(primary.get("market_move_event_count")) > 3:
        return "market_move_event_count_gt_3"
    if str(primary.get("grouping_window_mode", "")) != GROUPING_WINDOW_MODE:
        return "unexpected_grouping_window_mode"
    if (_float(primary.get("group_span_minutes")) or 0.0) > MARKET_MOVE_GROUP_WINDOW_MINUTES:
        return "group_span_minutes_gt_2"
    return ""


def _rejected_reason(primary: pd.Series) -> str:
    if _is_missing(primary.get("first_return_inside_at", "")):
        return ""
    if _is_missing(primary.get("first_close_inside_at", "")):
        return ""
    close_inside_minutes = _minutes_after(
        primary.get("source_event_timestamp", ""),
        primary.get("first_close_inside_at", ""),
    )
    if close_inside_minutes is None or close_inside_minutes > REJECTED_CLOSE_INSIDE_MINUTES:
        return ""
    if _int(primary.get("bars_inside_zone")) < REJECTED_BARS_INSIDE_MIN:
        return ""
    width = _float(primary.get("zone_width")) or 0.0
    max_return = _float(primary.get("max_return_inside_zone")) or 0.0
    if max_return < RETURN_INSIDE_ZONE_WIDTH_FRACTION * width:
        return ""
    close_end = _float(primary.get("close_at_window_end"))
    lower = _float(primary.get("zone_price_lower"))
    upper = _float(primary.get("zone_price_upper"))
    if close_end is None or lower is None or upper is None:
        return ""
    if str(primary.get("side", "")) == "BUY_SIDE" and close_end <= upper:
        return "returned_and_closed_inside_within_10_bars"
    if str(primary.get("side", "")) == "SELL_SIDE" and close_end >= lower:
        return "returned_and_closed_inside_within_10_bars"
    return ""


def _accepted_reason(primary: pd.Series) -> str:
    if not _is_missing(primary.get("first_close_inside_at", "")):
        return ""
    side = str(primary.get("side", ""))
    beyond_bars = (
        _int(primary.get("bars_above_zone"))
        if side == "BUY_SIDE"
        else _int(primary.get("bars_below_zone"))
    )
    if beyond_bars < ACCEPTED_BARS_BEYOND_MIN:
        return ""
    if _int(primary.get("bars_inside_zone")) > ACCEPTED_BARS_INSIDE_MAX:
        return ""
    width = _float(primary.get("zone_width")) or 0.0
    max_return = _float(primary.get("max_return_inside_zone")) or 0.0
    if max_return > RETURN_INSIDE_ZONE_WIDTH_FRACTION * width:
        return ""
    close_end = _float(primary.get("close_at_window_end"))
    lower = _float(primary.get("zone_price_lower"))
    upper = _float(primary.get("zone_price_upper"))
    if close_end is None or lower is None or upper is None:
        return ""
    if side == "BUY_SIDE" and close_end > upper:
        return "maintained_close_beyond_swept_side"
    if side == "SELL_SIDE" and close_end < lower:
        return "maintained_close_beyond_swept_side"
    return ""


def _base_row(
    *,
    taxonomy_version: str,
    move_id: str,
    primary: pd.Series,
    group: dict[str, object],
    group_precision: str,
) -> dict[str, object]:
    return {
        "taxonomy_version": taxonomy_version,
        "market_move_id": move_id,
        "label": "",
        "label_reason": "",
        "label_evidence_json": "",
        "primary_event_id": str(group.get("primary_event_id", "")) or str(primary.get("source_event_id", "")),
        "primary_observation_id": str(primary.get("observation_id", "")),
        "primary_zone_id": str(group.get("primary_zone_id", "")) or str(primary.get("zone_id", "")),
        "side": str(primary.get("side", group.get("side", ""))),
        "source_event_timestamp": str(primary.get("source_event_timestamp", group.get("event_timestamp", ""))),
        "group_start_timestamp": str(primary.get("group_start_timestamp", group.get("group_start_timestamp", ""))),
        "group_end_timestamp": str(primary.get("group_end_timestamp", group.get("group_end_timestamp", ""))),
        "group_span_minutes": _value(primary, group, "group_span_minutes"),
        "market_move_event_count": _value(primary, group, "market_move_event_count", group_key="event_count"),
        "precision_status": str(primary.get("precision_status", "")),
        "group_precision_statuses": group_precision,
        "confidence_score": _value(primary, group, "confidence_score"),
        "confidence_tier": str(primary.get("confidence_tier", "")),
        "zone_price_lower": _value(primary, group, "zone_price_lower", group_key="min_zone_price_lower"),
        "zone_price_upper": _value(primary, group, "zone_price_upper", group_key="max_zone_price_upper"),
        "zone_price_mid": _value(primary, group, "zone_price_mid", group_key="representative_zone_price_mid"),
        "zone_width": primary.get("zone_width", ""),
        "zone_width_pct": primary.get("zone_width_pct", ""),
        "observation_complete": _bool(primary.get("observation_complete", False)),
        "observation_bars_expected": primary.get("observation_bars_expected", ""),
        "observation_bars_available": primary.get("observation_bars_available", ""),
        "first_return_inside_at": str(primary.get("first_return_inside_at", "")),
        "first_close_inside_at": str(primary.get("first_close_inside_at", "")),
        "bars_inside_zone": primary.get("bars_inside_zone", ""),
        "bars_above_zone": primary.get("bars_above_zone", ""),
        "bars_below_zone": primary.get("bars_below_zone", ""),
        "max_return_inside_zone": primary.get("max_return_inside_zone", ""),
        "max_excursion_beyond_zone": primary.get("max_excursion_beyond_zone", ""),
        "close_at_window_end": primary.get("close_at_window_end", ""),
        "data_quality": str(primary.get("data_quality", group.get("data_quality", ""))),
    }


def _with_label(
    row: dict[str, object],
    label: str,
    reason: str,
    *,
    exclusion_reason: str = "",
    invalid_reason: str = "",
) -> dict[str, object]:
    row = dict(row)
    row["label"] = label
    row["label_reason"] = reason
    row["label_evidence_json"] = _evidence_json(
        row,
        exclusion_reason=exclusion_reason,
        invalid_reason=invalid_reason,
    )
    return row


def _evidence_json(
    row: dict[str, object],
    *,
    exclusion_reason: str,
    invalid_reason: str,
) -> str:
    evidence = {
        "accepted_bars_threshold": ACCEPTED_BARS_BEYOND_MIN,
        "bars_above_zone": _int(row.get("bars_above_zone")),
        "bars_below_zone": _int(row.get("bars_below_zone")),
        "bars_inside_acceptance_max": ACCEPTED_BARS_INSIDE_MAX,
        "bars_inside_zone": _int(row.get("bars_inside_zone")),
        "close_inside_minutes": _minutes_after(
            row.get("source_event_timestamp", ""),
            row.get("first_close_inside_at", ""),
        ),
        "data_quality": str(row.get("data_quality", "")),
        "first_close_inside_at": str(row.get("first_close_inside_at", "")),
        "first_return_inside_at": str(row.get("first_return_inside_at", "")),
        "group_precision_statuses": str(row.get("group_precision_statuses", "")),
        "label": str(row.get("label", "")),
        "label_reason": str(row.get("label_reason", "")),
        "market_move_event_count": _int(row.get("market_move_event_count")),
        "market_move_id": str(row.get("market_move_id", "")),
        "max_excursion_beyond_zone": _float(row.get("max_excursion_beyond_zone")),
        "max_return_inside_zone": _float(row.get("max_return_inside_zone")),
        "observation_complete": bool(row.get("observation_complete", False)),
        "precision_status": str(row.get("precision_status", "")),
        "reaction_label_is_not_signal": True,
        "return_inside_threshold": RETURN_INSIDE_ZONE_WIDTH_FRACTION
        * (_float(row.get("zone_width")) or 0.0),
        "side": str(row.get("side", "")),
        "taxonomy_version": str(row.get("taxonomy_version", "")),
        "zone_width": _float(row.get("zone_width")),
    }
    if exclusion_reason:
        evidence["exclusion_reason"] = exclusion_reason
    if invalid_reason:
        evidence["invalid_reason"] = invalid_reason
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"))


def _summary_frame(taxonomy: pd.DataFrame, taxonomy_version: str) -> pd.DataFrame:
    rows = []
    total = len(taxonomy)
    for label in sorted(ALLOWED_SWEEP_LABELS):
        group = taxonomy[taxonomy["label"] == label] if not taxonomy.empty else taxonomy
        complete = group["observation_complete"].astype(str).str.lower().eq("true") if not group.empty else []
        rows.append(
            {
                "taxonomy_version": taxonomy_version,
                "label": label,
                "count": len(group),
                "share": (len(group) / total) if total else 0.0,
                "complete_count": int(complete.sum()) if len(group) else 0,
                "incomplete_count": int((~complete).sum()) if len(group) else 0,
                "buy_side_count": _count(group, "side", "BUY_SIDE"),
                "sell_side_count": _count(group, "side", "SELL_SIDE"),
                "high_confidence_count": _count(group, "confidence_tier", "HIGH"),
                "medium_confidence_count": _count(group, "confidence_tier", "MEDIUM"),
                "low_confidence_count": _count(group, "confidence_tier", "LOW"),
                "precise_count": _count(group, "precision_status", "PRECISE"),
                "low_precision_count": _count(group, "precision_status", "LOW_PRECISION"),
                "too_wide_count": _count(group, "precision_status", "TOO_WIDE"),
            }
        )
    return pd.DataFrame(rows, columns=SWEEP_LABEL_SUMMARY_COLUMNS)


def _result(
    taxonomy_path: Path,
    summary_path: Path,
    taxonomy: pd.DataFrame,
    summary: pd.DataFrame,
) -> SweepLabelResult:
    stats = label_stats(taxonomy)
    return SweepLabelResult(
        taxonomy_path=taxonomy_path,
        summary_path=summary_path,
        taxonomy=taxonomy,
        summary=summary,
        label_counts=stats["label_counts"],
        clean_labelable_count=stats["clean_labelable_count"],
        no_label_count=stats["no_label_count"],
        invalid_sample_count=stats["invalid_sample_count"],
    )


def _market_move_ids(observations: pd.DataFrame, groups: pd.DataFrame) -> list[str]:
    ids: list[str] = []
    for frame, column in [(observations, "market_move_id"), (groups, "market_move_id")]:
        if frame.empty or column not in frame.columns:
            continue
        for value in frame[column].fillna("").astype(str):
            if value and value not in ids:
                ids.append(value)
    return sorted(ids, key=_move_sort_key)


def _move_sort_key(move_id: str):
    return move_id


def _groups_by_move(groups: pd.DataFrame) -> dict[str, dict[str, object]]:
    if groups.empty or "market_move_id" not in groups.columns:
        return {}
    return {
        str(row["market_move_id"]): row.to_dict()
        for _, row in groups.sort_values("market_move_id", kind="mergesort").iterrows()
        if str(row.get("market_move_id", ""))
    }


def _primary_row(observations: pd.DataFrame) -> pd.Series:
    primary = observations[observations["market_move_role"].astype(str) == "PRIMARY"]
    return primary.sort_values(
        ["source_event_timestamp", "zone_id", "observation_id"], kind="mergesort"
    ).iloc[0]


def _observation_required_columns() -> list[str]:
    return [
        "market_move_id",
        "market_move_role",
        "source_event_id",
        "observation_id",
        "source_event_timestamp",
        "observation_start_timestamp",
        "zone_id",
        "side",
        "zone_price_lower",
        "zone_price_upper",
        "zone_price_mid",
        "zone_width",
        "zone_width_pct",
        "precision_status",
        "confidence_score",
        "confidence_tier",
        "market_move_event_count",
        "group_start_timestamp",
        "group_end_timestamp",
        "group_span_minutes",
        "grouping_window_mode",
        "observation_complete",
        "observation_bars_expected",
        "observation_bars_available",
        "first_return_inside_at",
        "first_close_inside_at",
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "max_return_inside_zone",
        "max_excursion_beyond_zone",
        "close_at_window_end",
        "data_quality",
    ]


def _value(primary: pd.Series, group: dict[str, object], column: str, group_key: str | None = None):
    value = primary.get(column, "")
    if not _is_missing(value):
        return value
    return group.get(group_key or column, "")


def _bool(value) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _int(value) -> int:
    parsed = _float(value)
    return 0 if parsed is None else int(parsed)


def _float(value) -> float | None:
    if _is_missing(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _timestamp(value) -> pd.Timestamp | None:
    if _is_missing(value):
        return None
    try:
        return pd.Timestamp(value)
    except (TypeError, ValueError):
        return None


def _minutes_after(start, end) -> int | None:
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if start_ts is None or end_ts is None:
        return None
    return int((end_ts - start_ts).total_seconds() / 60)


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value) == ""


def _count(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column].astype(str) == value).sum())


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)
