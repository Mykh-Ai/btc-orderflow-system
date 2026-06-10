from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from market_monitor.label_taxonomy import (
    ALLOWED_SWEEP_LABELS,
    SWEEP_ACCEPTED,
    SWEEP_INVALID_SAMPLE,
    SWEEP_NO_LABEL,
    SWEEP_REJECTED,
    SWEEP_UNRESOLVED,
)


LABEL_QUALITY_TRACKING_ONLY = "LABEL_QUALITY_TRACKING_ONLY"
LABEL_QUALITY_DESCRIPTIVE_READY = "LABEL_QUALITY_DESCRIPTIVE_READY"
LABEL_QUALITY_RULE_DESIGN_CANDIDATE = "LABEL_QUALITY_RULE_DESIGN_CANDIDATE"
LABEL_QUALITY_NEEDS_MORE_DATA = "LABEL_QUALITY_NEEDS_MORE_DATA"
LABEL_QUALITY_NEEDS_TAXONOMY_PATCH = "LABEL_QUALITY_NEEDS_TAXONOMY_PATCH"
LABEL_QUALITY_NEEDS_DATA_SPLIT = "LABEL_QUALITY_NEEDS_DATA_SPLIT"
LABEL_QUALITY_BACKTESTER_BLOCKED = "LABEL_QUALITY_BACKTESTER_BLOCKED"

SUMMARY_COLUMNS = [
    "scope",
    "label",
    "count",
    "share",
    "quality_verdict",
    "quality_reason",
    "tracking_only",
    "descriptive_ready",
    "rules_design_candidate",
    "rules_design_blocked",
    "backtester_blocked",
    "top_1_day_share",
    "top_5_day_share",
    "buy_side_count",
    "sell_side_count",
    "side_imbalance_ratio",
    "complete_count",
    "incomplete_count",
    "no_label_count",
    "invalid_count",
]

BUCKET_COLUMNS = [
    "group_type",
    "group_value",
    "label",
    "count",
    "share",
]

BEHAVIOR_COLUMNS = [
    "label",
    "metric",
    "count",
    "mean",
    "median",
    "p75",
    "p90",
    "min",
    "max",
]

FORBIDDEN_OUTPUT_COLUMNS = {
    "signal",
    "entry",
    "exit",
    "order",
    "position",
    "position_size",
    "leverage",
    "stop_loss",
    "take_profit",
    "risk",
    "pnl",
    "win",
    "loss",
    "profit",
}

BOUNDARY_STATEMENT = (
    "This label quality report is descriptive research only. It does not "
    "generate trading signals, does not define entries or exits, does not "
    "calculate PnL, does not validate edge, and does not trigger Backtester "
    "or Executor behavior."
)


@dataclass(frozen=True)
class LabelQualityResult:
    markdown_path: Path
    summary_path: Path
    bucket_path: Path
    behavior_path: Path
    global_verdict: str
    label_verdicts: dict[str, str]
    total_market_moves: int
    clean_labelable_moves: int
    rules_design_blockers: tuple[str, ...]
    backtester_blockers: tuple[str, ...]


def build_label_quality_report(
    input_dirs: list[str | Path],
    output_dir: str | Path,
    run_timestamp: str | None = None,
) -> LabelQualityResult:
    input_paths = sorted([Path(path) for path in input_dirs], key=lambda path: str(path))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _load_inputs(input_paths)
    primary = _primary_rows(rows)
    label_counts = _label_counts(primary)
    total = int(len(primary))
    clean_labelable = total - label_counts[SWEEP_NO_LABEL] - label_counts[SWEEP_INVALID_SAMPLE]
    complete_mask = _complete_mask(primary)
    concentration = _concentration(primary)
    global_verdict = _global_verdict(total, label_counts, primary)
    label_verdicts = {
        label: _label_verdict(label, label_counts[label])
        for label in sorted(ALLOWED_SWEEP_LABELS)
    }
    rules_blockers = _rules_design_blockers(total, label_counts)
    backtester_blockers = _backtester_blockers(total, label_counts)

    summary = _summary_frame(
        primary=primary,
        total=total,
        label_counts=label_counts,
        label_verdicts=label_verdicts,
        global_verdict=global_verdict,
        clean_labelable=clean_labelable,
        complete_count=int(complete_mask.sum()) if total else 0,
        incomplete_count=int((~complete_mask).sum()) if total else 0,
        concentration=concentration,
    )
    buckets = _bucket_frame(primary)
    behavior = _behavior_frame(primary)

    summary_path = out_dir / "label_quality_summary.csv"
    bucket_path = out_dir / "label_quality_by_bucket.csv"
    behavior_path = out_dir / "label_quality_behavior_metrics.csv"
    markdown_path = out_dir / "label_quality_report.md"
    summary.to_csv(summary_path, index=False)
    buckets.to_csv(bucket_path, index=False)
    behavior.to_csv(behavior_path, index=False)
    markdown_path.write_text(
        _markdown_report(
            input_paths=input_paths,
            run_timestamp=run_timestamp or "",
            primary=primary,
            total=total,
            clean_labelable=clean_labelable,
            label_counts=label_counts,
            label_verdicts=label_verdicts,
            global_verdict=global_verdict,
            summary=summary,
            buckets=buckets,
            behavior=behavior,
            concentration=concentration,
            rules_blockers=rules_blockers,
            backtester_blockers=backtester_blockers,
        ),
        encoding="utf-8",
    )
    _assert_no_forbidden_columns(summary)
    return LabelQualityResult(
        markdown_path=markdown_path,
        summary_path=summary_path,
        bucket_path=bucket_path,
        behavior_path=behavior_path,
        global_verdict=global_verdict,
        label_verdicts=label_verdicts,
        total_market_moves=total,
        clean_labelable_moves=clean_labelable,
        rules_design_blockers=rules_blockers,
        backtester_blockers=backtester_blockers,
    )


def _load_inputs(input_paths: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in input_paths:
        frames.extend(_load_input(path))
    if not frames:
        return _empty_rows()
    out = pd.concat(frames, ignore_index=True)
    out = _normalize_rows(out)
    return out.sort_values(
        ["source_segment", "source_event_timestamp", "market_move_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _load_input(path: Path) -> list[pd.DataFrame]:
    research_csv = path / "research_summary" / "post_sweep_research_summary.csv"
    if research_csv.exists():
        frame = pd.read_csv(research_csv)
        frame["source_segment"] = path.name
        return [frame]
    daily_root = path / "daily"
    if daily_root.exists():
        return [_load_daily_dir(day) for day in sorted(daily_root.iterdir()) if day.is_dir()]
    if (path / "sweep_label_taxonomy.csv").exists():
        return [_load_daily_dir(path)]
    return []


def _load_daily_dir(path: Path) -> pd.DataFrame:
    taxonomy_path = path / "sweep_label_taxonomy.csv"
    if not taxonomy_path.exists():
        return _empty_rows()
    labels = pd.read_csv(taxonomy_path)
    labels = labels.rename(columns={"label": "sweep_label"})
    observations_path = path / "post_sweep_observation.csv"
    if observations_path.exists():
        observations = pd.read_csv(observations_path)
        observations = observations.rename(columns={"observation_id": "primary_observation_id"})
        labels = labels.merge(
            observations,
            left_on="market_move_id",
            right_on="market_move_id",
            how="left",
            suffixes=("", "_observation"),
        )
    labels["source_segment"] = path.name
    return labels


def _normalize_rows(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    rename_map = {"label": "sweep_label"}
    out = out.rename(columns={k: v for k, v in rename_map.items() if k in out.columns})
    for column in _required_columns():
        if column not in out.columns:
            out[column] = ""
    if "source_event_timestamp" not in out.columns and "event_timestamp" in out.columns:
        out["source_event_timestamp"] = out["event_timestamp"]
    for column in _numeric_columns():
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out["event_date"] = out["source_event_timestamp"].astype(str).str.slice(0, 10)
    out["zone_width_bucket"] = pd.to_numeric(out["zone_width_pct"], errors="coerce").map(_zone_width_bucket)
    return out[_required_columns() + ["event_date", "zone_width_bucket"]]


def _empty_rows() -> pd.DataFrame:
    return pd.DataFrame(columns=_required_columns() + ["event_date", "zone_width_bucket"])


def _required_columns() -> list[str]:
    return [
        "source_segment",
        "taxonomy_version",
        "sweep_label",
        "label_reason",
        "source_event_timestamp",
        "market_move_id",
        "market_move_role",
        "market_move_event_count",
        "side",
        "confidence_tier",
        "source_timeframes",
        "precision_status",
        "has_h4_source",
        "has_session_source",
        "zone_width",
        "zone_width_pct",
        "observation_complete",
        "observation_bars_expected",
        "observation_bars_available",
        "max_excursion_beyond_zone",
        "max_return_inside_zone",
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "first_close_inside_at",
        "post_delta_pct",
        "post_oi_change",
        "post_max_volume_zscore",
        "post_max_abs_delta_zscore",
        "data_quality",
    ]


def _numeric_columns() -> list[str]:
    return [
        "market_move_event_count",
        "zone_width",
        "zone_width_pct",
        "observation_bars_expected",
        "observation_bars_available",
        "max_excursion_beyond_zone",
        "max_return_inside_zone",
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "post_delta_pct",
        "post_oi_change",
        "post_max_volume_zscore",
        "post_max_abs_delta_zscore",
    ]


def _primary_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    roles = frame["market_move_role"].fillna("").astype(str)
    primary = frame[(roles == "PRIMARY") | (roles == "")]
    primary = primary.drop_duplicates(["source_segment", "market_move_id"], keep="first")
    return primary.reset_index(drop=True)


def _label_counts(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty:
        return {label: 0 for label in sorted(ALLOWED_SWEEP_LABELS)}
    counts = frame["sweep_label"].fillna("").astype(str).value_counts()
    return {label: int(counts.get(label, 0)) for label in sorted(ALLOWED_SWEEP_LABELS)}


def _summary_frame(
    *,
    primary: pd.DataFrame,
    total: int,
    label_counts: dict[str, int],
    label_verdicts: dict[str, str],
    global_verdict: str,
    clean_labelable: int,
    complete_count: int,
    incomplete_count: int,
    concentration: dict[str, float],
) -> pd.DataFrame:
    rows = []
    for label in sorted(ALLOWED_SWEEP_LABELS):
        label_rows = primary[primary["sweep_label"] == label] if not primary.empty else primary
        count = label_counts[label]
        buy = _count_value(label_rows, "side", "BUY_SIDE")
        sell = _count_value(label_rows, "side", "SELL_SIDE")
        complete = int(_complete_mask(label_rows).sum()) if count else 0
        verdict = label_verdicts[label]
        rows.append(
            {
                "scope": "LABEL",
                "label": label,
                "count": count,
                "share": _share(count, total),
                "quality_verdict": verdict,
                "quality_reason": _label_quality_reason(label, count, verdict),
                "tracking_only": verdict == LABEL_QUALITY_TRACKING_ONLY,
                "descriptive_ready": verdict == LABEL_QUALITY_DESCRIPTIVE_READY,
                "rules_design_candidate": verdict == LABEL_QUALITY_RULE_DESIGN_CANDIDATE,
                "rules_design_blocked": verdict != LABEL_QUALITY_RULE_DESIGN_CANDIDATE,
                "backtester_blocked": True,
                "top_1_day_share": _label_top_day_share(label_rows, 1),
                "top_5_day_share": _label_top_day_share(label_rows, 5),
                "buy_side_count": buy,
                "sell_side_count": sell,
                "side_imbalance_ratio": _imbalance_ratio(buy, sell),
                "complete_count": complete,
                "incomplete_count": count - complete,
                "no_label_count": count if label == SWEEP_NO_LABEL else 0,
                "invalid_count": count if label == SWEEP_INVALID_SAMPLE else 0,
            }
        )
    rows.append(
        {
            "scope": "GLOBAL",
            "label": "GLOBAL",
            "count": total,
            "share": 1.0 if total else 0.0,
            "quality_verdict": global_verdict,
            "quality_reason": _global_quality_reason(global_verdict, total, clean_labelable),
            "tracking_only": global_verdict == LABEL_QUALITY_TRACKING_ONLY,
            "descriptive_ready": global_verdict == LABEL_QUALITY_DESCRIPTIVE_READY,
            "rules_design_candidate": False,
            "rules_design_blocked": True,
            "backtester_blocked": True,
            "top_1_day_share": concentration["top_1_day_share"],
            "top_5_day_share": concentration["top_5_day_share"],
            "buy_side_count": _count_value(primary, "side", "BUY_SIDE"),
            "sell_side_count": _count_value(primary, "side", "SELL_SIDE"),
            "side_imbalance_ratio": _imbalance_ratio(
                _count_value(primary, "side", "BUY_SIDE"),
                _count_value(primary, "side", "SELL_SIDE"),
            ),
            "complete_count": complete_count,
            "incomplete_count": incomplete_count,
            "no_label_count": label_counts[SWEEP_NO_LABEL],
            "invalid_count": label_counts[SWEEP_INVALID_SAMPLE],
        }
    )
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)


def _bucket_frame(primary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for group_type, column in [
        ("side", "side"),
        ("confidence_tier", "confidence_tier"),
        ("precision_status", "precision_status"),
        ("source_timeframes", "source_timeframes"),
        ("market_move_event_count", "market_move_event_count"),
        ("has_h4_source", "has_h4_source"),
        ("has_session_source", "has_session_source"),
        ("zone_width_bucket", "zone_width_bucket"),
        ("data_quality", "data_quality"),
        ("observation_complete", "observation_complete"),
        ("source_segment", "source_segment"),
    ]:
        if primary.empty or column not in primary.columns:
            continue
        for label in sorted(ALLOWED_SWEEP_LABELS):
            label_rows = primary[primary["sweep_label"] == label]
            total = len(label_rows)
            counts = label_rows[column].fillna("").astype(str).value_counts().sort_index()
            for value, count in counts.items():
                if value:
                    rows.append(
                        {
                            "group_type": group_type,
                            "group_value": value,
                            "label": label,
                            "count": int(count),
                            "share": _share(int(count), total),
                        }
                    )
    return pd.DataFrame(rows, columns=BUCKET_COLUMNS)


def _behavior_frame(primary: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "bars_inside_zone",
        "bars_above_zone",
        "bars_below_zone",
        "max_return_inside_zone",
        "max_excursion_beyond_zone",
        "close_inside_delay_minutes",
        "post_delta_pct",
        "post_oi_change",
        "post_max_volume_zscore",
        "post_max_abs_delta_zscore",
    ]
    frame = primary.copy()
    frame["close_inside_delay_minutes"] = _close_inside_delay(frame)
    rows: list[dict[str, object]] = []
    for label in sorted(ALLOWED_SWEEP_LABELS):
        label_rows = frame[frame["sweep_label"] == label]
        for metric in metrics:
            rows.append({"label": label, "metric": metric, **_descriptive_stats(label_rows, metric)})
    return pd.DataFrame(rows, columns=BEHAVIOR_COLUMNS)


def _concentration(primary: pd.DataFrame) -> dict[str, float]:
    if primary.empty:
        return {
            "max_labels_per_day": 0,
            "top_1_day_share": 0.0,
            "top_5_day_share": 0.0,
        }
    counts = primary["event_date"].fillna("").astype(str).value_counts()
    counts = counts[counts.index != ""].sort_values(ascending=False)
    total = len(primary)
    if counts.empty:
        return {
            "max_labels_per_day": 0,
            "top_1_day_share": 0.0,
            "top_5_day_share": 0.0,
        }
    return {
        "max_labels_per_day": int(counts.iloc[0]),
        "top_1_day_share": _share(int(counts.iloc[0]), total),
        "top_5_day_share": _share(int(counts.head(5).sum()), total),
    }


def _label_verdict(label: str, count: int) -> str:
    if label == SWEEP_INVALID_SAMPLE:
        return LABEL_QUALITY_TRACKING_ONLY if count == 0 else LABEL_QUALITY_NEEDS_TAXONOMY_PATCH
    if count < 30:
        return LABEL_QUALITY_TRACKING_ONLY
    if label in {SWEEP_NO_LABEL, SWEEP_UNRESOLVED}:
        return LABEL_QUALITY_DESCRIPTIVE_READY
    if count < 300:
        return LABEL_QUALITY_DESCRIPTIVE_READY
    return LABEL_QUALITY_RULE_DESIGN_CANDIDATE


def _global_verdict(total: int, label_counts: dict[str, int], primary: pd.DataFrame) -> str:
    if label_counts[SWEEP_INVALID_SAMPLE] > 0:
        invalid_share = _share(label_counts[SWEEP_INVALID_SAMPLE], total)
        if invalid_share > 0.02:
            return LABEL_QUALITY_NEEDS_TAXONOMY_PATCH
    if _has_mixed_data_quality(primary):
        return LABEL_QUALITY_NEEDS_DATA_SPLIT
    if total < 100:
        return LABEL_QUALITY_NEEDS_MORE_DATA
    return LABEL_QUALITY_DESCRIPTIVE_READY


def _rules_design_blockers(total: int, label_counts: dict[str, int]) -> tuple[str, ...]:
    blockers = [
        "Any target bucket under 100 examples blocks rules design.",
        f"{SWEEP_ACCEPTED} has {label_counts[SWEEP_ACCEPTED]} examples and remains too small.",
        "Threshold-edge and overlap diagnostics have not yet been promoted to a rules gate.",
        "The current clean sample is discontinuous around the degraded/recovered window.",
        "Low-precision no-label rows require source and width diagnostics.",
        "No holdout or segment protocol has been accepted for rules design.",
    ]
    if total < 500:
        blockers.insert(0, f"Total market moves is {total}, below the 500+ rules-design floor.")
    return tuple(blockers)


def _backtester_blockers(total: int, label_counts: dict[str, int]) -> tuple[str, ...]:
    return (
        f"Total market moves is {total}, below the 1000+ adapter-consideration floor.",
        "No label bucket is near 300 examples.",
        f"{SWEEP_ACCEPTED} has {label_counts[SWEEP_ACCEPTED]} examples and is tracking-only.",
        "Backtester is legacy, audit-required, and not active.",
        "No audited adapter contract exists from Market Monitor artifacts to validation harness.",
        "Labels are descriptive research artifacts, not edge evidence.",
    )


def _markdown_report(
    *,
    input_paths: list[Path],
    run_timestamp: str,
    primary: pd.DataFrame,
    total: int,
    clean_labelable: int,
    label_counts: dict[str, int],
    label_verdicts: dict[str, str],
    global_verdict: str,
    summary: pd.DataFrame,
    buckets: pd.DataFrame,
    behavior: pd.DataFrame,
    concentration: dict[str, float],
    rules_blockers: tuple[str, ...],
    backtester_blockers: tuple[str, ...],
) -> str:
    complete = _complete_mask(primary)
    lines = [
        "# Label Quality Report V1",
        "",
        "## Run Metadata",
        "",
        f"- Run timestamp: {run_timestamp}",
        f"- Input dirs: {', '.join(str(path) for path in input_paths)}",
        f"- Total market moves: {total}",
        f"- Data quality scope: {_counts_for(primary, 'data_quality')}",
        f"- Label taxonomy version: {_counts_for(primary, 'taxonomy_version')}",
        "",
        "## Sample Size Summary",
        "",
        f"- total_market_moves: {total}",
        f"- clean_labelable_moves: {clean_labelable}",
        f"- count_by_label: {_format_label_counts(label_counts)}",
        f"- share_by_label: {_format_label_shares(label_counts, total)}",
        f"- complete_observation_count: {int(complete.sum()) if total else 0}",
        f"- incomplete_observation_count: {int((~complete).sum()) if total else 0}",
        f"- minimum_bucket_count: {_minimum_bucket_count(label_counts)}",
        f"- labelable_share: {_fmt(_share(clean_labelable, total))}",
        "",
        "## Label Bucket Quality Verdicts",
        "",
        "| Label | Count | Share | Quality Verdict | Explanation |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for label in sorted(ALLOWED_SWEEP_LABELS):
        count = label_counts[label]
        verdict = label_verdicts[label]
        lines.append(
            f"| `{label}` | {count} | {_fmt_pct(_share(count, total))} | "
            f"`{verdict}` | {_label_quality_reason(label, count, verdict)} |"
        )
    lines.extend(
        [
            "",
            "## Concentration Metrics",
            "",
            f"- max_labels_per_day: {concentration['max_labels_per_day']}",
            f"- top_1_day_share: {_fmt_pct(concentration['top_1_day_share'])}",
            f"- top_5_day_share: {_fmt_pct(concentration['top_5_day_share'])}",
            f"- warnings/blockers: {_concentration_warning(concentration)}",
            "",
            "## Side Balance",
            "",
            _markdown_pivot(buckets, "side"),
            "",
            "## Confidence / Precision / Source Metrics",
            "",
            "### Confidence Tier",
            "",
            _markdown_pivot(buckets, "confidence_tier"),
            "",
            "### Precision Status",
            "",
            _markdown_pivot(buckets, "precision_status"),
            "",
            "### Source Timeframes",
            "",
            _markdown_pivot(buckets, "source_timeframes"),
            "",
            "### Market Move Event Count",
            "",
            _markdown_pivot(buckets, "market_move_event_count"),
            "",
            "### H4 / Session / Zone Width Buckets",
            "",
            _markdown_pivot(buckets, "has_h4_source"),
            "",
            _markdown_pivot(buckets, "has_session_source"),
            "",
            _markdown_pivot(buckets, "zone_width_bucket"),
            "",
            "## Observation Behavior Metrics",
            "",
            _markdown_behavior(behavior),
            "",
            "## No-Label / Invalid Metrics",
            "",
            f"- no_label_count_by_reason: {_reason_counts(primary, SWEEP_NO_LABEL)}",
            f"- invalid_count_by_reason: {_reason_counts(primary, SWEEP_INVALID_SAMPLE)}",
            f"- no_label_share: {_fmt_pct(_share(label_counts[SWEEP_NO_LABEL], total))}",
            f"- invalid_share: {_fmt_pct(_share(label_counts[SWEEP_INVALID_SAMPLE], total))}",
            f"- incomplete_observation_share: {_fmt_pct(_share(int((~complete).sum()) if total else 0, total))}",
            f"- low_precision_exclusion_share: {_fmt_pct(_low_precision_exclusion_share(primary, total))}",
            f"- too_many_events_share: {_fmt_pct(_too_many_events_share(primary, total))}",
            "",
            "## Segment / Drift Metrics",
            "",
            _markdown_pivot(buckets, "source_segment"),
            "",
            f"- Segment limitation: {'multiple input segments available' if len(input_paths) > 1 else 'single input segment only'}",
            "",
            "## Global Quality Verdict",
            "",
            f"`{global_verdict}`",
            "",
            "Backtester status: `LABEL_QUALITY_BACKTESTER_BLOCKED`",
            "",
            "## Rules-Design Blockers",
            "",
        ]
    )
    lines.extend(f"- {blocker}" for blocker in rules_blockers)
    lines.extend(["", "## Backtester Blockers", ""])
    lines.extend(f"- {blocker}" for blocker in backtester_blockers)
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


def _label_quality_reason(label: str, count: int, verdict: str) -> str:
    if label == SWEEP_INVALID_SAMPLE:
        return "No invalid samples present." if count == 0 else "Invalid samples require taxonomy/data-quality review."
    if label == SWEEP_ACCEPTED and count < 30:
        return "Accepted bucket is below 30 examples; tracking only."
    if count < 30:
        return "Bucket is below 30 examples; tracking only."
    if label == SWEEP_NO_LABEL:
        return "Diagnostic exclusion bucket; descriptive review only."
    if label == SWEEP_UNRESOLVED:
        return "Ambiguity diagnostic bucket; descriptive review only."
    if verdict == LABEL_QUALITY_DESCRIPTIVE_READY:
        return "Bucket has enough examples for descriptive review only."
    return "Bucket count is high enough for future rule-design discussion if all quality gates pass."


def _global_quality_reason(verdict: str, total: int, clean_labelable: int) -> str:
    if verdict == LABEL_QUALITY_DESCRIPTIVE_READY:
        return f"{total} market moves and {clean_labelable} clean labelable moves support descriptive review."
    if verdict == LABEL_QUALITY_NEEDS_MORE_DATA:
        return "Total market moves are below the 100-row descriptive floor."
    if verdict == LABEL_QUALITY_NEEDS_DATA_SPLIT:
        return "Data quality scope must be split before combined interpretation."
    return "Taxonomy or data-quality blockers require review."


def _complete_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "observation_complete" not in frame.columns:
        return pd.Series([], dtype=bool)
    return frame["observation_complete"].fillna("").astype(str).str.lower() == "true"


def _share(count: int, total: int) -> float:
    return 0.0 if total == 0 else round(float(count) / float(total), 6)


def _count_value(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int((frame[column].fillna("").astype(str) == value).sum())


def _imbalance_ratio(first: int, second: int) -> float:
    smaller = min(first, second)
    larger = max(first, second)
    if larger == 0:
        return 0.0
    if smaller == 0:
        return float(larger)
    return round(float(larger) / float(smaller), 6)


def _label_top_day_share(frame: pd.DataFrame, n: int) -> float:
    if frame.empty:
        return 0.0
    counts = frame["event_date"].fillna("").astype(str).value_counts()
    counts = counts[counts.index != ""]
    return _share(int(counts.head(n).sum()), len(frame))


def _descriptive_stats(frame: pd.DataFrame, column: str) -> dict[str, object]:
    if frame.empty or column not in frame.columns:
        return {"count": 0, "mean": "", "median": "", "p75": "", "p90": "", "min": "", "max": ""}
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return {"count": 0, "mean": "", "median": "", "p75": "", "p90": "", "min": "", "max": ""}
    return {
        "count": int(len(values)),
        "mean": _round(values.mean()),
        "median": _round(values.median()),
        "p75": _round(values.quantile(0.75)),
        "p90": _round(values.quantile(0.90)),
        "min": _round(values.min()),
        "max": _round(values.max()),
    }


def _close_inside_delay(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series([], dtype=float)
    event_ts = pd.to_datetime(frame["source_event_timestamp"], errors="coerce", utc=True)
    close_ts = pd.to_datetime(frame["first_close_inside_at"], errors="coerce", utc=True)
    return (close_ts - event_ts).dt.total_seconds() / 60.0


def _zone_width_bucket(value) -> str:
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


def _has_mixed_data_quality(frame: pd.DataFrame) -> bool:
    if frame.empty:
        return False
    values = set(frame["data_quality"].fillna("").astype(str))
    values.discard("")
    return len(values) > 1


def _minimum_bucket_count(label_counts: dict[str, int]) -> int:
    nonzero = [count for count in label_counts.values() if count > 0]
    return min(nonzero) if nonzero else 0


def _format_label_counts(label_counts: dict[str, int]) -> str:
    return ", ".join(f"{label}={label_counts[label]}" for label in sorted(ALLOWED_SWEEP_LABELS))


def _format_label_shares(label_counts: dict[str, int], total: int) -> str:
    return ", ".join(
        f"{label}={_fmt_pct(_share(label_counts[label], total))}"
        for label in sorted(ALLOWED_SWEEP_LABELS)
    )


def _counts_for(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return "none"
    counts = frame[column].fillna("").astype(str).value_counts().sort_index()
    counts = counts[counts.index != ""]
    if counts.empty:
        return "none"
    return ", ".join(f"{name}={int(count)}" for name, count in counts.items())


def _reason_counts(frame: pd.DataFrame, label: str) -> str:
    if frame.empty:
        return "none"
    subset = frame[frame["sweep_label"] == label]
    return _counts_for(subset, "label_reason")


def _low_precision_exclusion_share(frame: pd.DataFrame, total: int) -> float:
    if frame.empty:
        return 0.0
    no_label = frame[frame["sweep_label"] == SWEEP_NO_LABEL]
    low_precision = no_label["label_reason"].fillna("").astype(str).str.contains("low_precision", regex=False)
    return _share(int(low_precision.sum()), total)


def _too_many_events_share(frame: pd.DataFrame, total: int) -> float:
    if frame.empty:
        return 0.0
    reasons = frame["label_reason"].fillna("").astype(str)
    event_reason = reasons.str.contains("event_count", regex=False) | reasons.str.contains("too_many", regex=False)
    return _share(int(event_reason.sum()), total)


def _concentration_warning(concentration: dict[str, float]) -> str:
    if concentration["top_5_day_share"] > 0.50:
        return "blocker: top five days exceed 50% of labels"
    if concentration["top_1_day_share"] > 0.15:
        return "blocker: top day exceeds 15% of labels"
    if concentration["top_5_day_share"] > 0.35:
        return "warning: top five days exceed 35% of labels"
    if concentration["top_1_day_share"] > 0.10:
        return "warning: top day exceeds 10% of labels"
    return "none"


def _markdown_pivot(buckets: pd.DataFrame, group_type: str) -> str:
    subset = buckets[buckets["group_type"] == group_type] if not buckets.empty else buckets
    if subset.empty:
        return "No data available."
    pivot = subset.pivot_table(
        index="group_value",
        columns="label",
        values="count",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    labels = [label for label in sorted(ALLOWED_SWEEP_LABELS) if label in pivot.columns]
    lines = ["| Value | " + " | ".join(labels) + " |"]
    lines.append("| --- | " + " | ".join("---:" for _ in labels) + " |")
    for _, row in pivot.sort_values("group_value", kind="mergesort").iterrows():
        lines.append(
            "| "
            + _md_cell(row["group_value"])
            + " | "
            + " | ".join(str(int(row[label])) for label in labels)
            + " |"
        )
    return "\n".join(lines)


def _markdown_behavior(behavior: pd.DataFrame) -> str:
    if behavior.empty:
        return "No behavior metrics available."
    keep_metrics = [
        "bars_inside_zone",
        "max_return_inside_zone",
        "max_excursion_beyond_zone",
        "close_inside_delay_minutes",
        "post_delta_pct",
        "post_oi_change",
    ]
    subset = behavior[behavior["metric"].isin(keep_metrics)]
    lines = ["| Label | Metric | Count | Mean | Median | P75 | P90 | Min | Max |"]
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for _, row in subset.sort_values(["label", "metric"], kind="mergesort").iterrows():
        lines.append(
            f"| `{row['label']}` | `{row['metric']}` | {row['count']} | "
            f"{_fmt(row['mean'])} | {_fmt(row['median'])} | {_fmt(row['p75'])} | "
            f"{_fmt(row['p90'])} | {_fmt(row['min'])} | {_fmt(row['max'])} |"
        )
    return "\n".join(lines)


def _round(value) -> float:
    return round(float(value), 6)


def _fmt(value) -> str:
    if value == "" or pd.isna(value):
        return ""
    return f"{float(value):.6g}"


def _fmt_pct(value: float) -> str:
    return f"{100.0 * float(value):.2f}%"


def _md_cell(value) -> str:
    return str(value).replace("|", "\\|")


def _assert_no_forbidden_columns(frame: pd.DataFrame) -> None:
    forbidden = {column.lower() for column in frame.columns} & FORBIDDEN_OUTPUT_COLUMNS
    if forbidden:
        raise ValueError(f"Forbidden label quality columns: {sorted(forbidden)}")
