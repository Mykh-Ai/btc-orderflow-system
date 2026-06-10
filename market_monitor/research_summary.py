from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from market_monitor.events import GROUPING_WINDOW_MODE, MARKET_MOVE_GROUP_WINDOW_MINUTES
from market_monitor.label_taxonomy import (
    SWEEP_INVALID_SAMPLE,
    SWEEP_NO_LABEL,
    format_label_counts,
    label_stats,
)
from market_monitor.score_instrumentation import SCORE_INSTRUMENTATION_COLUMNS


ROW_SUMMARY_COLUMNS = [
    "source_run_dir",
    "taxonomy_version",
    "sweep_label",
    "label_reason",
    "observation_id",
    "source_event_id",
    "source_event_timestamp",
    "market_move_id",
    "market_move_role",
    "market_move_event_count",
    "group_start_timestamp",
    "group_end_timestamp",
    "group_span_minutes",
    "grouping_window_mode",
    "zone_id",
    "side",
    "zone_type",
    "zone_price_lower",
    "zone_price_upper",
    "zone_price_mid",
    "confidence_score",
    "confidence_tier",
    "source_timeframes",
    *SCORE_INSTRUMENTATION_COLUMNS,
    "observation_bars_expected",
    "observation_bars_available",
    "observation_complete",
    "max_high_after_event",
    "min_low_after_event",
    "close_at_window_end",
    "max_excursion_beyond_zone",
    "max_return_inside_zone",
    "bars_inside_zone",
    "bars_above_zone",
    "bars_below_zone",
    "first_return_inside_at",
    "first_close_inside_at",
    "first_close_beyond_at",
    "net_close_change_abs",
    "net_close_change_pct",
    "post_volume_sum",
    "post_buy_qty_sum",
    "post_sell_qty_sum",
    "post_delta_sum",
    "post_delta_pct",
    "post_trades_sum",
    "post_oi_change",
    "post_max_volume_zscore",
    "post_max_abs_delta_zscore",
    "data_quality",
]

GROUP_SUMMARY_COLUMNS = [
    "group_type",
    "group_value",
    "observation_count",
    "complete_count",
    "incomplete_count",
    "avg_max_excursion_beyond_zone",
    "median_max_excursion_beyond_zone",
    "avg_max_return_inside_zone",
    "median_max_return_inside_zone",
    "avg_bars_inside_zone",
    "avg_bars_above_zone",
    "avg_bars_below_zone",
    "avg_net_close_change_pct",
    "avg_post_delta_pct",
    "avg_post_oi_change",
    "avg_post_max_volume_zscore",
    "avg_post_max_abs_delta_zscore",
]

BOUNDARY_STATEMENT = (
    "This research summary is descriptive only. It does not classify trade outcomes, "
    "does not generate trading signals, does not define entries/exits, does not "
    "calculate PnL, and does not trigger Backtester or Executor behavior."
)


@dataclass(frozen=True)
class ResearchSummaryResult:
    markdown_path: Path
    row_summary_path: Path
    group_summary_path: Path
    observation_count: int
    complete_count: int
    incomplete_count: int
    event_counts_by_type: dict[str, int]
    warnings: tuple[str, ...]
    label_counts: dict[str, int]
    clean_labelable_count: int
    no_label_count: int
    invalid_sample_count: int


def build_post_sweep_research_summary(
    input_dirs,
    output_dir,
    run_timestamp: str | None = None,
) -> ResearchSummaryResult:
    input_paths = _input_paths(input_dirs)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    loaded = [_load_run_dir(path) for path in input_paths]
    observations = _combined_observations(loaded)
    event_counts = _combined_event_counts(loaded)
    labels = _combined_labels(loaded)
    observations = _join_labels(observations, labels)
    group_summary = _group_summary(observations)
    warnings = tuple(warning for item in loaded for warning in item["warnings"])

    row_summary = observations[ROW_SUMMARY_COLUMNS]
    row_path = output_path / "post_sweep_research_summary.csv"
    group_path = output_path / "post_sweep_group_summary.csv"
    markdown_path = output_path / "post_sweep_research_summary.md"
    row_summary.to_csv(row_path, index=False)
    group_summary.to_csv(group_path, index=False)
    markdown_path.write_text(
        _markdown_summary(
            input_paths=input_paths,
            observations=observations,
            group_summary=group_summary,
            event_counts=event_counts,
        warnings=warnings,
        labels=labels,
        run_timestamp=run_timestamp or "",
        ),
        encoding="utf-8",
    )

    complete = _complete_mask(observations)
    return ResearchSummaryResult(
        markdown_path=markdown_path,
        row_summary_path=row_path,
        group_summary_path=group_path,
        observation_count=len(observations),
        complete_count=int(complete.sum()),
        incomplete_count=int((~complete).sum()) if len(observations) else 0,
        event_counts_by_type=event_counts,
        warnings=warnings,
        **label_stats(labels),
    )


def _input_paths(input_dirs) -> list[Path]:
    paths = [Path(path) for path in input_dirs]
    return sorted(paths, key=lambda path: str(path))


def _load_run_dir(path: Path) -> dict[str, object]:
    warnings: list[str] = []
    observation_path = path / "post_sweep_observation.csv"
    if observation_path.exists():
        observations = pd.read_csv(observation_path)
    else:
        observations = pd.DataFrame(columns=ROW_SUMMARY_COLUMNS)
        warnings.append(f"Missing post_sweep_observation.csv in {path}")

    if not observations.empty:
        observations = observations.copy()
        observations["source_run_dir"] = str(path)
        observations = _enrich_from_event_log(observations, path / "event_log.csv")
        observations = _normalize_observations(observations)
    else:
        observations = pd.DataFrame(columns=ROW_SUMMARY_COLUMNS)

    event_counts = _event_counts(path / "event_log.csv")
    labels = _load_labels(path / "sweep_label_taxonomy.csv", path)
    return {
        "observations": observations,
        "event_counts": event_counts,
        "labels": labels,
        "warnings": warnings,
    }


def _combined_observations(loaded: list[dict[str, object]]) -> pd.DataFrame:
    frames = [item["observations"] for item in loaded if not item["observations"].empty]
    if not frames:
        return pd.DataFrame(columns=ROW_SUMMARY_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(
        [
            "source_run_dir",
            "source_event_timestamp",
            "market_move_id",
            "zone_id",
            "observation_id",
        ],
        kind="mergesort",
    ).reset_index(drop=True)
    return out


def _combined_event_counts(loaded: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in loaded:
        for event_type, count in item["event_counts"].items():
            counts[event_type] = counts.get(event_type, 0) + int(count)
    return dict(sorted(counts.items()))


def _combined_labels(loaded: list[dict[str, object]]) -> pd.DataFrame:
    frames = [item["labels"] for item in loaded if not item["labels"].empty]
    if not frames:
        return pd.DataFrame(columns=["source_run_dir", "market_move_id", "taxonomy_version", "label", "label_reason"])
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["source_run_dir", "market_move_id"], kind="mergesort").reset_index(drop=True)


def _join_labels(observations: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    out = observations.copy()
    for column in ["taxonomy_version", "sweep_label", "label_reason"]:
        out[column] = ""
    if out.empty or labels.empty:
        return out[ROW_SUMMARY_COLUMNS]
    keep = labels[["source_run_dir", "market_move_id", "taxonomy_version", "label", "label_reason"]].copy()
    keep = keep.rename(columns={"label": "sweep_label"})
    out = out.drop(columns=["taxonomy_version", "sweep_label", "label_reason"], errors="ignore").merge(
        keep,
        on=["source_run_dir", "market_move_id"],
        how="left",
        sort=False,
    )
    for column in ["taxonomy_version", "sweep_label", "label_reason"]:
        out[column] = out[column].fillna("")
    return out[ROW_SUMMARY_COLUMNS]


def _normalize_observations(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column in ROW_SUMMARY_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    for column in _numeric_columns():
        out[column] = pd.to_numeric(out[column], errors="coerce")
    return out[ROW_SUMMARY_COLUMNS]


def _enrich_from_event_log(observations: pd.DataFrame, event_log_path: Path) -> pd.DataFrame:
    observations = observations.copy()
    observations["confidence_tier"] = ""
    observations["source_timeframes"] = ""
    observations["confidence_score"] = ""
    observations["market_move_id"] = observations.get("market_move_id", "")
    observations["market_move_role"] = observations.get("market_move_role", "")
    observations["market_move_event_count"] = observations.get("market_move_event_count", "")
    observations["group_start_timestamp"] = observations.get("group_start_timestamp", "")
    observations["group_end_timestamp"] = observations.get("group_end_timestamp", "")
    observations["group_span_minutes"] = observations.get("group_span_minutes", "")
    observations["grouping_window_mode"] = observations.get("grouping_window_mode", "")
    for column in SCORE_INSTRUMENTATION_COLUMNS:
        observations[column] = observations.get(column, "")
    if not event_log_path.exists():
        return observations
    event_log = pd.read_csv(event_log_path)
    if event_log.empty or "event_id" not in event_log.columns:
        return observations
    evidence_by_event = {}
    for _, row in event_log.iterrows():
        try:
            evidence = json.loads(str(row.get("evidence_json", "{}")))
        except json.JSONDecodeError:
            evidence = {}
        evidence_by_event[str(row["event_id"])] = evidence
    events_by_id = {
        str(row["event_id"]): row.to_dict()
        for _, row in event_log.iterrows()
    }
    observations["market_move_id"] = observations["source_event_id"].map(
        lambda event_id: str(events_by_id.get(str(event_id), {}).get("market_move_id", ""))
    )
    observations["market_move_role"] = observations["source_event_id"].map(
        lambda event_id: str(events_by_id.get(str(event_id), {}).get("market_move_role", ""))
    )
    observations["market_move_event_count"] = observations["source_event_id"].map(
        lambda event_id: events_by_id.get(str(event_id), {}).get("market_move_event_count", "")
    )
    observations["group_start_timestamp"] = observations["source_event_id"].map(
        lambda event_id: str(events_by_id.get(str(event_id), {}).get("group_start_timestamp", ""))
    )
    observations["group_end_timestamp"] = observations["source_event_id"].map(
        lambda event_id: str(events_by_id.get(str(event_id), {}).get("group_end_timestamp", ""))
    )
    observations["group_span_minutes"] = observations["source_event_id"].map(
        lambda event_id: events_by_id.get(str(event_id), {}).get("group_span_minutes", "")
    )
    observations["grouping_window_mode"] = observations["source_event_id"].map(
        lambda event_id: str(events_by_id.get(str(event_id), {}).get("grouping_window_mode", ""))
    )
    observations["confidence_tier"] = observations["source_event_id"].map(
        lambda event_id: str(evidence_by_event.get(str(event_id), {}).get("confidence_tier", ""))
    )
    observations["source_timeframes"] = observations["source_event_id"].map(
        lambda event_id: str(evidence_by_event.get(str(event_id), {}).get("source_timeframes", ""))
    )
    observations["confidence_score"] = observations["source_event_id"].map(
        lambda event_id: evidence_by_event.get(str(event_id), {}).get("confidence_score", "")
    )
    for column in SCORE_INSTRUMENTATION_COLUMNS:
        observations[column] = observations["source_event_id"].map(
            lambda event_id, column=column: evidence_by_event.get(str(event_id), {}).get(column, "")
        )
    return observations


def _event_counts(event_log_path: Path) -> dict[str, int]:
    if not event_log_path.exists():
        return {}
    event_log = pd.read_csv(event_log_path)
    if event_log.empty or "event_type" not in event_log.columns:
        return {}
    counts = event_log["event_type"].value_counts().sort_index()
    return {str(name): int(count) for name, count in counts.items()}


def _load_labels(label_path: Path, run_dir: Path) -> pd.DataFrame:
    if not label_path.exists():
        return pd.DataFrame(columns=["source_run_dir", "market_move_id", "taxonomy_version", "label", "label_reason"])
    labels = pd.read_csv(label_path)
    if labels.empty:
        return pd.DataFrame(columns=["source_run_dir", "market_move_id", "taxonomy_version", "label", "label_reason"])
    labels = labels.copy()
    labels["source_run_dir"] = str(run_dir)
    for column in ["market_move_id", "taxonomy_version", "label", "label_reason"]:
        if column not in labels.columns:
            labels[column] = ""
    return labels[["source_run_dir", "market_move_id", "taxonomy_version", "label", "label_reason"]]


def _group_summary(observations: pd.DataFrame) -> pd.DataFrame:
    observations = _with_score_buckets(observations)
    rows = [_group_row("ALL", "ALL", observations)]
    if not observations.empty:
        for column, group_type in [
            ("side", "side"),
            ("data_quality", "data_quality"),
            ("observation_complete", "observation_complete"),
            ("zone_type", "zone_type"),
            ("confidence_tier", "confidence_tier"),
            ("precision_status", "precision_status"),
            ("market_move_role", "market_move_role"),
            ("market_move_event_count", "market_move_event_count"),
            ("grouping_window_mode", "grouping_window_mode"),
            ("sweep_label", "sweep_label"),
            ("source_timeframes", "source_timeframes"),
            ("has_h4_source", "has_h4_source"),
            ("has_session_source", "has_session_source"),
            ("source_level_count_bucket", "source_level_count_bucket"),
            ("zone_width_pct_bucket", "zone_width_pct_bucket"),
        ]:
            if column in observations.columns:
                for value, group in observations.groupby(column, sort=True, dropna=False):
                    if str(value):
                        rows.append(_group_row(group_type, str(value), group))
    return pd.DataFrame(rows, columns=GROUP_SUMMARY_COLUMNS)


def _group_row(group_type: str, group_value: str, group: pd.DataFrame) -> dict[str, object]:
    complete = _complete_mask(group)
    return {
        "group_type": group_type,
        "group_value": group_value,
        "observation_count": len(group),
        "complete_count": int(complete.sum()) if len(group) else 0,
        "incomplete_count": int((~complete).sum()) if len(group) else 0,
        "avg_max_excursion_beyond_zone": _mean(group, "max_excursion_beyond_zone"),
        "median_max_excursion_beyond_zone": _median(group, "max_excursion_beyond_zone"),
        "avg_max_return_inside_zone": _mean(group, "max_return_inside_zone"),
        "median_max_return_inside_zone": _median(group, "max_return_inside_zone"),
        "avg_bars_inside_zone": _mean(group, "bars_inside_zone"),
        "avg_bars_above_zone": _mean(group, "bars_above_zone"),
        "avg_bars_below_zone": _mean(group, "bars_below_zone"),
        "avg_net_close_change_pct": _mean(group, "net_close_change_pct"),
        "avg_post_delta_pct": _mean(group, "post_delta_pct"),
        "avg_post_oi_change": _mean(group, "post_oi_change"),
        "avg_post_max_volume_zscore": _mean(group, "post_max_volume_zscore"),
        "avg_post_max_abs_delta_zscore": _mean(group, "post_max_abs_delta_zscore"),
    }


def _markdown_summary(
    *,
    input_paths: list[Path],
    observations: pd.DataFrame,
    group_summary: pd.DataFrame,
    event_counts: dict[str, int],
    warnings: tuple[str, ...],
    labels: pd.DataFrame,
    run_timestamp: str,
) -> str:
    complete = _complete_mask(observations)
    observation_count = len(observations)
    move_stats = _market_move_stats(observations)
    sweep_label_stats = label_stats(labels)
    label_counts = sweep_label_stats["label_counts"]
    lines = [
        "# Post-Sweep Observation Research Summary",
        "",
        "## Run Metadata",
        "",
        f"- Run timestamp: {run_timestamp}",
        f"- Input directories: {', '.join(str(path) for path in input_paths)}",
        f"- Observation rows loaded: {observation_count}",
        f"- Complete observations: {int(complete.sum()) if observation_count else 0}",
        f"- Incomplete observations: {int((~complete).sum()) if observation_count else 0}",
        "",
        "## Event Context",
        "",
        f"- Event counts by type: {_format_counts(event_counts)}",
        f"- Unresolved sweep count: {event_counts.get('LIQUIDITY_SWEEP_UNRESOLVED', 0)}",
        f"- Grouped unresolved market moves: {move_stats['grouped_market_move_count']}",
        f"- Multi-event market moves: {move_stats['multi_event_market_move_count']}",
        (
            "- Average unresolved rows per market move: "
            f"{_fmt(move_stats['avg_unresolved_events_per_market_move'])}"
        ),
        (
            "- Max unresolved rows per market move: "
            f"{move_stats['max_unresolved_events_per_market_move']}"
        ),
        f"- Max group span minutes: {_fmt(move_stats['max_group_span_minutes'])}",
        f"- Groups over configured window: {move_stats['groups_over_configured_window']}",
        f"- Grouping window mode: {move_stats['grouping_window_mode']}",
        "",
        "## Observation Overview",
        "",
        f"- observation_count: {observation_count}",
        f"- by data_quality: {_counts_for(observations, 'data_quality')}",
        f"- by observation_complete: {_counts_for(observations, 'observation_complete')}",
        f"- by confidence_tier: {_counts_for(observations, 'confidence_tier')}",
        f"- by market_move_role: {_counts_for(observations, 'market_move_role')}",
        f"- by market_move_event_count: {_counts_for(observations, 'market_move_event_count')}",
        f"- by grouping_window_mode: {_counts_for(observations, 'grouping_window_mode')}",
        f"- by sweep_label: {_counts_for(observations, 'sweep_label')}",
        f"- score instrumentation available: {'yes' if _score_instrumentation_available(observations) else 'no'}",
        f"- by has_h4_source: {_counts_for(observations, 'has_h4_source')}",
        f"- by has_session_source: {_counts_for(observations, 'has_session_source')}",
        f"- by source_level_count_bucket: {_counts_for(_with_score_buckets(observations), 'source_level_count_bucket')}",
        f"- by zone_width_pct_bucket: {_counts_for(_with_score_buckets(observations), 'zone_width_pct_bucket')}",
        "",
        "## Descriptive Metrics",
        "",
        f"- average max_excursion_beyond_zone: {_fmt(_mean(observations, 'max_excursion_beyond_zone'))}",
        f"- median max_excursion_beyond_zone: {_fmt(_median(observations, 'max_excursion_beyond_zone'))}",
        f"- average max_return_inside_zone: {_fmt(_mean(observations, 'max_return_inside_zone'))}",
        f"- median max_return_inside_zone: {_fmt(_median(observations, 'max_return_inside_zone'))}",
        f"- average bars_inside_zone: {_fmt(_mean(observations, 'bars_inside_zone'))}",
        f"- average bars_above_zone: {_fmt(_mean(observations, 'bars_above_zone'))}",
        f"- average bars_below_zone: {_fmt(_mean(observations, 'bars_below_zone'))}",
        f"- average net_close_change_pct: {_fmt(_mean(observations, 'net_close_change_pct'))}",
        f"- average post_delta_pct: {_fmt(_mean(observations, 'post_delta_pct'))}",
        f"- average post_oi_change: {_fmt(_mean(observations, 'post_oi_change'))}",
        "",
        "## Data Quality Caveats",
        "",
        f"- Degraded rows present: {'yes' if _has_degraded(observations) else 'no'}",
        "",
        "## Sweep Label Taxonomy",
        "",
        f"- Sweep taxonomy labels available: {'yes' if not labels.empty else 'no'}",
        f"- Sweep taxonomy label rows: {len(labels)}",
        f"- Sweep taxonomy label counts: {format_label_counts(label_counts)}",
        f"- Clean V1 labelable moves: {sweep_label_stats['clean_labelable_count']}",
        f"- No-label moves: {label_counts[SWEEP_NO_LABEL]}",
        f"- Invalid samples: {label_counts[SWEEP_INVALID_SAMPLE]}",
    ]
    if observation_count < 30:
        lines.append("- Sample size is below 30 observations. This summary is insufficient for strategy rules or validation.")
    if observation_count < 100:
        lines.append("- Sample size is below 100 observations. Treat descriptive metrics as preliminary.")
    for warning in warnings:
        lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Boundary Statement",
            "",
            BOUNDARY_STATEMENT,
            "",
        ]
    )
    return "\n".join(lines)


def _complete_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "observation_complete" not in frame.columns:
        return pd.Series(dtype=bool)
    return frame["observation_complete"].astype(str).str.lower() == "true"


def _numeric_columns() -> list[str]:
    return [
        "zone_price_lower",
        "zone_price_upper",
        "zone_price_mid",
        "observation_bars_expected",
        "observation_bars_available",
        "max_high_after_event",
        "min_low_after_event",
        "close_at_window_end",
        "max_excursion_beyond_zone",
        "max_return_inside_zone",
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "net_close_change_abs",
        "net_close_change_pct",
        "post_volume_sum",
        "post_buy_qty_sum",
        "post_sell_qty_sum",
        "post_delta_sum",
        "post_delta_pct",
        "post_trades_sum",
        "post_oi_change",
        "post_max_volume_zscore",
        "post_max_abs_delta_zscore",
        "confidence_score",
        "market_move_event_count",
        "group_span_minutes",
        "source_level_count",
        "source_ref_count",
        "cluster_member_count",
        "zone_width",
        "zone_width_pct",
    ]


def _with_score_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        for column in ["source_level_count_bucket", "zone_width_pct_bucket"]:
            out[column] = ""
        return out
    source_counts = pd.to_numeric(out.get("source_level_count", ""), errors="coerce")
    zone_width_pct = pd.to_numeric(out.get("zone_width_pct", ""), errors="coerce")
    out["source_level_count_bucket"] = source_counts.map(_source_count_bucket)
    out["zone_width_pct_bucket"] = zone_width_pct.map(_zone_width_pct_bucket)
    return out


def _source_count_bucket(value) -> str:
    if pd.isna(value):
        return "unknown"
    value = int(value)
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 5:
        return "3-5"
    return "6+"


def _zone_width_pct_bucket(value) -> str:
    if pd.isna(value):
        return "unknown"
    value = float(value)
    if value < 0.10:
        return "<0.10"
    if value < 0.25:
        return "0.10-0.25"
    if value < 0.50:
        return "0.25-0.50"
    return ">=0.50"


def _score_instrumentation_available(frame: pd.DataFrame) -> bool:
    return not frame.empty and "score_components_json" in frame.columns and bool(
        frame["score_components_json"].fillna("").astype(str).str.len().gt(0).any()
    )


def _mean(frame: pd.DataFrame, column: str):
    if frame.empty or column not in frame.columns:
        return ""
    value = pd.to_numeric(frame[column], errors="coerce").mean()
    return "" if pd.isna(value) else float(value)


def _median(frame: pd.DataFrame, column: str):
    if frame.empty or column not in frame.columns:
        return ""
    value = pd.to_numeric(frame[column], errors="coerce").median()
    return "" if pd.isna(value) else float(value)


def _counts_for(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return "none"
    counts = frame[column].astype(str).value_counts().sort_index()
    counts = counts[counts.index != ""]
    if counts.empty:
        return "none"
    return ", ".join(f"{name}={int(count)}" for name, count in counts.items())


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _has_degraded(frame: pd.DataFrame) -> bool:
    return not frame.empty and bool((frame["data_quality"] == "RECOVERED_DEGRADED").any())


def _market_move_stats(observations: pd.DataFrame) -> dict[str, object]:
    if observations.empty or "market_move_id" not in observations.columns:
        return {
            "grouped_market_move_count": 0,
            "multi_event_market_move_count": 0,
            "avg_unresolved_events_per_market_move": 0.0,
            "max_unresolved_events_per_market_move": 0,
            "max_group_span_minutes": 0.0,
            "groups_over_configured_window": 0,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
        }
    grouped = observations[observations["market_move_id"].fillna("").astype(str) != ""]
    if grouped.empty:
        return {
            "grouped_market_move_count": 0,
            "multi_event_market_move_count": 0,
            "avg_unresolved_events_per_market_move": 0.0,
            "max_unresolved_events_per_market_move": 0,
            "max_group_span_minutes": 0.0,
            "groups_over_configured_window": 0,
            "grouping_window_mode": GROUPING_WINDOW_MODE,
        }
    counts = grouped.groupby("market_move_id", sort=True).size()
    spans = (
        pd.to_numeric(grouped.get("group_span_minutes", ""), errors="coerce")
        .groupby(grouped["market_move_id"])
        .max()
    )
    max_span = 0.0 if spans.empty else float(spans.max())
    modes = _counts_for(grouped.drop_duplicates("market_move_id"), "grouping_window_mode")
    return {
        "grouped_market_move_count": int(len(counts)),
        "multi_event_market_move_count": int((counts > 1).sum()),
        "avg_unresolved_events_per_market_move": float(counts.mean()),
        "max_unresolved_events_per_market_move": int(counts.max()),
        "max_group_span_minutes": max_span,
        "groups_over_configured_window": int((spans > MARKET_MOVE_GROUP_WINDOW_MINUTES).sum()),
        "grouping_window_mode": modes if modes != "none" else GROUPING_WINDOW_MODE,
    }


def _fmt(value) -> str:
    if value == "":
        return ""
    return f"{float(value):.8g}"
