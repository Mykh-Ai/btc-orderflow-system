from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

MOVE_THRESHOLD_USD = 1000.0


@dataclass(frozen=True)
class FastMoneySetupCase:
    setup_case_id: str
    move_cluster_id: str
    day: str
    side: str
    case_start_ts: str
    case_end_ts: str
    move_signal_start: str
    move_signal_end: str
    proxy_count: str
    earliest_valid_entry_ts: str
    earliest_valid_entry_price: str
    best_execution_entry_ts: str
    best_execution_entry_price: str
    recommended_proxy_kind: str
    recommended_entry_ts: str
    recommended_entry_price: str
    quality_class: str
    impulse_quality_score: str
    execution_quality_score: str
    continuation_score: str
    risk_score: str
    repeatability_family: str
    candidate_family_votes: str
    phase_votes: str
    session_votes: str
    context_alignment_votes: str
    is_countertrend_case: str
    has_fast_money_trigger: str
    has_late_no_edge: str
    m2_6_count_60m_max: str
    reject_support_count: str
    accepted_peak_count_near_max: str
    best_mfe_15m: str
    best_mfe_30m: str
    best_mfe_60m: str
    best_mae_60m: str
    best_time_to_1000: str
    best_adverse_before_1000: str
    best_stop_tight_survived: str
    best_stop_sweep_survived: str
    earliest_time_to_1000: str
    earliest_adverse_before_1000: str
    earliest_stop_sweep_survived: str
    duplicate_note: str
    review_priority: str
    notes: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[FastMoneySetupCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FastMoneySetupCase.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _fmt_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _scope_id_from_path(path: Path) -> str:
    match = re.search(r"fast_money_pre_impulse_table_(\d{4}-\d{2}-\d{2}_to_\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if match:
        return match.group(1)
    return "unknown_scope"


def _latest_pre_impulse_table(output_root: Path) -> Path:
    paths = sorted(output_root.glob("fast_money_pre_impulse_table_*_to_*.csv"))
    paths = [path for path in paths if not path.name.endswith("_summary.csv")]
    if not paths:
        raise RuntimeError(f"no fast_money_pre_impulse_table CSV found under {output_root}")
    return paths[-1]


def _counter_summary(values: list[str], limit: int = 5) -> str:
    counter = Counter(value for value in values if value)
    return "; ".join(f"{key}:{count}" for key, count in counter.most_common(limit))


def _best_float(rows: list[dict[str, str]], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _min_float(rows: list[dict[str, str]], field: str) -> float | None:
    values = [_float(row.get(field)) for row in rows]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _proxy_score(row: dict[str, str]) -> float:
    mfe60 = _float(row.get("mfe_60m")) or 0.0
    mae60 = _float(row.get("mae_60m")) or 0.0
    time1000 = _float(row.get("time_to_1000"))
    adverse1000 = _float(row.get("adverse_before_1000"))

    favorable = min(mfe60 / 2500.0, 1.0) * 30.0
    speed = max(0.0, (60.0 - (time1000 if time1000 is not None else 75.0)) / 60.0) * 25.0
    risk_basis = adverse1000 if adverse1000 is not None else mae60
    risk = max(0.0, 1.0 - min(risk_basis, 750.0) / 750.0) * 25.0
    stop = 0.0
    if row.get("stop_tight_survived") == "true":
        stop += 8.0
    if row.get("stop_sweep_survived") == "true":
        stop += 5.0
    if row.get("stop_vwap_reclaim_survived") == "true":
        stop += 4.0
    trigger = 8.0 if row.get("is_fast_money_trigger") == "true" else 0.0
    late_penalty = 18.0 if row.get("is_late_no_edge") == "true" else 0.0
    barely_penalty = 10.0 if 0.0 < mfe60 < 1200.0 else 0.0
    no_hit_penalty = 20.0 if time1000 is None else 0.0
    score = favorable + speed + risk + stop + trigger - late_penalty - barely_penalty - no_hit_penalty
    return max(0.0, min(100.0, score))


def _risk_score(row: dict[str, str]) -> float:
    mae60 = _float(row.get("mae_60m")) or 0.0
    adverse1000 = _float(row.get("adverse_before_1000"))
    risk_basis = adverse1000 if adverse1000 is not None else mae60
    return max(0.0, min(100.0, 100.0 - min(risk_basis, 1000.0) / 10.0))


def _execution_score(row: dict[str, str]) -> float:
    time1000 = _float(row.get("time_to_1000"))
    adverse1000 = _float(row.get("adverse_before_1000"))
    if time1000 is None:
        return 0.0
    speed = max(0.0, 100.0 - min(time1000, 60.0) * 1.4)
    adverse_penalty = min(adverse1000 or 0.0, 500.0) / 8.0
    stop_bonus = 8.0 if row.get("stop_sweep_survived") == "true" else 0.0
    return max(0.0, min(100.0, speed - adverse_penalty + stop_bonus))


def _continuation_score(row: dict[str, str]) -> float:
    mfe30 = _float(row.get("mfe_30m")) or 0.0
    mfe60 = _float(row.get("mfe_60m")) or 0.0
    extra = max(0.0, mfe60 - max(MOVE_THRESHOLD_USD, mfe30))
    return max(0.0, min(100.0, (mfe60 / 2500.0) * 70.0 + (extra / 1000.0) * 30.0))


def _quality_class(row: dict[str, str]) -> str:
    if row.get("is_countertrend") == "true" and row.get("is_fast_money_trigger") == "true":
        return "F_COUNTERTREND_SWEEP"
    if row.get("is_late_no_edge") == "true":
        return "D_LATE_NO_EDGE"

    mfe60 = _float(row.get("mfe_60m")) or 0.0
    time1000 = _float(row.get("time_to_1000"))
    adverse1000 = _float(row.get("adverse_before_1000"))
    mae60 = _float(row.get("mae_60m")) or 0.0
    risk_basis = adverse1000 if adverse1000 is not None else mae60

    if time1000 is None or mfe60 < MOVE_THRESHOLD_USD:
        return "E_FAILED_OR_TOO_RISKY"
    if mfe60 >= 1600.0 and time1000 <= 25.0 and risk_basis <= 150.0:
        return "A_STRONG_IMPULSE"
    if mfe60 >= 1200.0 and time1000 <= 35.0 and risk_basis <= 250.0:
        return "B_CLEAN_SCALP"
    if mfe60 < 1200.0 or time1000 >= 45.0 or risk_basis > 250.0:
        return "C_BARELY_HIT"
    return "B_CLEAN_SCALP"


def _repeatability_family(row: dict[str, str]) -> str:
    family = row.get("candidate_family", "")
    phase = row.get("phase_label", "")
    if row.get("is_countertrend") == "true":
        return "countertrend_stop_sweep"
    if "LONG_FORERUNNER" in family or phase == "reversal_forerunner":
        return "reversal_forerunner"
    if "LATE_RISK" in family or row.get("is_late_no_edge") == "true":
        return "late_liquidity_chase"
    if row.get("m2_6_count_60m") and (_float(row.get("m2_6_count_60m")) or 0.0) >= 8.0:
        return "m2_density_pre_impulse"
    if row.get("nearest_reject_reason"):
        return "reject_supported_pre_impulse"
    return "generic_pre_impulse"


def _review_priority(row: dict[str, str], score: float) -> str:
    quality = _quality_class(row)
    if quality in {"A_STRONG_IMPULSE", "F_COUNTERTREND_SWEEP"} and score >= 70.0:
        return "top_manual_review"
    if quality == "F_COUNTERTREND_SWEEP":
        return "countertrend_review"
    if quality in {"A_STRONG_IMPULSE", "B_CLEAN_SCALP"}:
        return "candidate_family_review"
    if quality == "C_BARELY_HIT":
        return "borderline_review"
    if quality == "D_LATE_NO_EDGE":
        return "timing_filter_review"
    return "discard_or_failure_review"


def _preferred_row(rows: list[dict[str, str]]) -> dict[str, str]:
    triggers = [row for row in rows if row.get("is_fast_money_trigger") == "true" and row.get("is_late_no_edge") != "true"]
    candidates = triggers or rows
    return max(candidates, key=_proxy_score)


def _row_for_kind(rows: list[dict[str, str]], kind: str) -> dict[str, str]:
    for row in rows:
        if row.get("proxy_kind") == kind:
            return row
    return {}


def _make_case(rows: list[dict[str, str]]) -> FastMoneySetupCase:
    ordered = sorted(rows, key=lambda row: row.get("candidate_ts", ""))
    best = _row_for_kind(ordered, "best_proxy") or max(ordered, key=_proxy_score)
    earliest = _row_for_kind(ordered, "earliest_proxy") or ordered[0]
    recommended = _preferred_row(ordered)

    quality = _quality_class(recommended)
    impulse_score = _proxy_score(recommended)
    execution_score = _execution_score(recommended)
    continuation_score = _continuation_score(recommended)
    risk_score = _risk_score(recommended)
    repeatability = _repeatability_family(recommended)
    has_trigger = any(row.get("is_fast_money_trigger") == "true" for row in ordered)
    has_late = any(row.get("is_late_no_edge") == "true" for row in ordered)
    is_countertrend = any(row.get("is_countertrend") == "true" for row in ordered)
    reject_support_count = sum(1 for row in ordered if row.get("nearest_reject_ts"))

    notes: list[str] = []
    if len(ordered) > 1:
        notes.append("deduped_proxy_rows")
    if has_trigger:
        notes.append("has_fast_money_trigger")
    if is_countertrend:
        notes.append("has_countertrend_context")
    if has_late:
        notes.append("has_late_proxy")

    setup_case_id = best.get("move_cluster_id", "").replace("_mf", "_fmsc")
    return FastMoneySetupCase(
        setup_case_id=setup_case_id,
        move_cluster_id=best.get("move_cluster_id", ""),
        day=best.get("day", ""),
        side=best.get("side", ""),
        case_start_ts=ordered[0].get("candidate_ts", ""),
        case_end_ts=ordered[-1].get("candidate_ts", ""),
        move_signal_start=best.get("move_signal_start", ""),
        move_signal_end=best.get("move_signal_end", ""),
        proxy_count=str(len(ordered)),
        earliest_valid_entry_ts=earliest.get("candidate_ts", ""),
        earliest_valid_entry_price=earliest.get("entry_price", ""),
        best_execution_entry_ts=best.get("candidate_ts", ""),
        best_execution_entry_price=best.get("entry_price", ""),
        recommended_proxy_kind=recommended.get("proxy_kind", ""),
        recommended_entry_ts=recommended.get("candidate_ts", ""),
        recommended_entry_price=recommended.get("entry_price", ""),
        quality_class=quality,
        impulse_quality_score=_fmt_float(impulse_score),
        execution_quality_score=_fmt_float(execution_score),
        continuation_score=_fmt_float(continuation_score),
        risk_score=_fmt_float(risk_score),
        repeatability_family=repeatability,
        candidate_family_votes=_counter_summary([row.get("candidate_family", "") for row in ordered]),
        phase_votes=_counter_summary([row.get("phase_label", "") for row in ordered]),
        session_votes=_counter_summary([row.get("session_label", "") for row in ordered]),
        context_alignment_votes=_counter_summary([row.get("m2_6_context_alignment", "") for row in ordered]),
        is_countertrend_case=_bool_text(is_countertrend),
        has_fast_money_trigger=_bool_text(has_trigger),
        has_late_no_edge=_bool_text(has_late),
        m2_6_count_60m_max=_fmt_float(_best_float(ordered, "m2_6_count_60m")),
        reject_support_count=str(reject_support_count),
        accepted_peak_count_near_max=_fmt_float(_best_float(ordered, "accepted_peak_count_near")),
        best_mfe_15m=_fmt_float(_best_float(ordered, "mfe_15m")),
        best_mfe_30m=_fmt_float(_best_float(ordered, "mfe_30m")),
        best_mfe_60m=_fmt_float(_best_float(ordered, "mfe_60m")),
        best_mae_60m=_fmt_float(_min_float(ordered, "mae_60m")),
        best_time_to_1000=_fmt_float(_min_float(ordered, "time_to_1000")),
        best_adverse_before_1000=_fmt_float(_min_float(ordered, "adverse_before_1000")),
        best_stop_tight_survived=_bool_text(any(row.get("stop_tight_survived") == "true" for row in ordered)),
        best_stop_sweep_survived=_bool_text(any(row.get("stop_sweep_survived") == "true" for row in ordered)),
        earliest_time_to_1000=earliest.get("time_to_1000", ""),
        earliest_adverse_before_1000=earliest.get("adverse_before_1000", ""),
        earliest_stop_sweep_survived=earliest.get("stop_sweep_survived", ""),
        duplicate_note="one_setup_case_from_multiple_proxy_rows" if len(ordered) > 1 else "",
        review_priority=_review_priority(recommended, impulse_score),
        notes="; ".join(notes),
    )


def _write_summary(path: Path, rows: list[FastMoneySetupCase], scope_id: str) -> None:
    by_quality = Counter(row.quality_class for row in rows)
    by_family = Counter(row.repeatability_family for row in rows)
    by_priority = Counter(row.review_priority for row in rows)
    top_rows = rows[:20]
    lines = [
        "# Fast Money Setup Cases Summary",
        "",
        f"scope: `{scope_id}`",
        f"setup_cases: `{len(rows)}`",
        "",
        "## Quality Classes",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_quality.items()))
    lines.extend(["", "## Repeatability Families", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_family.items()))
    lines.extend(["", "## Review Priority", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_priority.items()))
    lines.extend(["", "## Top Manual Review Cases", ""])
    for row in top_rows:
        lines.append(
            f"- `{row.setup_case_id}` `{row.recommended_entry_ts}` `{row.side}` "
            f"`{row.quality_class}` `{row.repeatability_family}` "
            f"score={row.impulse_quality_score} mfe60={row.best_mfe_60m} "
            f"t1000={row.best_time_to_1000} adverse1000={row.best_adverse_before_1000} "
            f"priority=`{row.review_priority}`"
        )
    lines.extend(["", "## Use", ""])
    lines.append("This table deduplicates pre-impulse proxy rows into one setup case per move cluster.")
    lines.append("Use it to separate strong/repeatable impulses from barely-hit, late, failed, and countertrend cases before backtesting.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_fast_money_setup_cases(
    pre_impulse_table: Path,
    output_root: Path,
) -> tuple[Path, Path, int]:
    rows = _read_csv_rows(pre_impulse_table)
    if not rows:
        raise RuntimeError(f"no pre-impulse rows found in {pre_impulse_table}")

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("move_cluster_id", ""), []).append(row)

    cases = [_make_case(group_rows) for _, group_rows in sorted(grouped.items()) if group_rows]
    cases = sorted(cases, key=lambda row: float(row.impulse_quality_score or 0.0), reverse=True)
    scope_id = _scope_id_from_path(pre_impulse_table)
    output_root.mkdir(parents=True, exist_ok=True)
    out_csv = output_root / f"fast_money_setup_cases_{scope_id}.csv"
    out_md = output_root / f"fast_money_setup_cases_{scope_id}_summary.md"
    _write_csv(out_csv, cases)
    _write_summary(out_md, cases, scope_id)
    return out_csv, out_md, len(cases)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deduplicate fast-money proxy rows into setup cases with quality/family labels")
    parser.add_argument("--pre-impulse-table", help="fast_money_pre_impulse_table_<scope>.csv. Defaults to latest under output-root.")
    parser.add_argument("--output-root", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_root = Path(args.output_root)
    pre_impulse_table = Path(args.pre_impulse_table) if args.pre_impulse_table else _latest_pre_impulse_table(output_root)
    out_csv, out_md, case_count = build_fast_money_setup_cases(pre_impulse_table=pre_impulse_table, output_root=output_root)
    print("DeltaScout Fast Money Setup Cases Build")
    print(f"fast_money_setup_cases={out_csv}")
    print(f"fast_money_setup_cases_summary={out_md}")
    print(f"case_count={case_count}")


if __name__ == "__main__":
    main()
