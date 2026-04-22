from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from ..types import ChainClusterSummaryRow, MinuteEventChainCandidateRow, MinuteEventChainReferenceCaseRow

SUPPORTED_FAMILIES = {"F1", "F2"}
SUPPORTED_CHAIN_ROLES = {"seed", "release", "continuation", "late_exhaustion", "unknown"}
WINDOW_GAP_MINUTES = 20


def build_m2_6_outputs(
    mechanics_rows: list[dict[str, str]],
    outcomes_rows: list[dict[str, str]],
) -> tuple[list[MinuteEventChainCandidateRow], list[MinuteEventChainReferenceCaseRow], list[ChainClusterSummaryRow]]:
    merged = _build_merged_rows(mechanics_rows, outcomes_rows)
    candidates = _build_candidates(merged)
    reference_cases = build_reference_cases(candidates)
    cluster_summaries = build_cluster_summaries(candidates)
    return candidates, reference_cases, cluster_summaries


def build_m2_6_outputs_for_scope(
    *,
    input_root: str,
    output_root: str,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Path]:
    scope_start, scope_end = _resolve_scope_dates(input_root, date=date, date_from=date_from, date_to=date_to)
    mechanics_rows = _load_rows_for_scope(Path(input_root), "minute_events_mechanics", scope_start, scope_end)
    outcomes_rows = _load_rows_for_scope(Path(input_root), "minute_events_outcomes", scope_start, scope_end)
    candidates, reference_cases, cluster_summaries = build_m2_6_outputs(mechanics_rows, outcomes_rows)

    suffix = f"{scope_start}_to_{scope_end}"
    out_dir = Path(output_root) / "m2_6"
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates_path = out_dir / f"minute_event_chain_candidates_{suffix}.csv"
    reference_cases_path = out_dir / f"minute_event_chain_reference_cases_{suffix}.csv"
    cluster_summaries_path = out_dir / f"chain_cluster_summaries_{suffix}.csv"

    _write_dataclass_csv(candidates, candidates_path, MinuteEventChainCandidateRow)
    _write_dataclass_csv(reference_cases, reference_cases_path, MinuteEventChainReferenceCaseRow)
    _write_dataclass_csv(cluster_summaries, cluster_summaries_path, ChainClusterSummaryRow)

    return {
        "candidates": candidates_path,
        "reference_cases": reference_cases_path,
        "cluster_summaries": cluster_summaries_path,
        "scope_start": Path(scope_start),
        "scope_end": Path(scope_end),
    }


def build_reference_cases(candidates: list[MinuteEventChainCandidateRow]) -> list[MinuteEventChainReferenceCaseRow]:
    if not candidates:
        return []
    ranked = sorted(candidates, key=lambda row: (row.day, row.ts, row.family_hint, row.direction))
    by_family = {"F1": [], "F2": []}
    for row in ranked:
        if row.family_hint in by_family:
            by_family[row.family_hint].append(row)

    selected: dict[tuple[datetime, str, str], MinuteEventChainCandidateRow] = {}

    for family in ("F1", "F2"):
        rows = by_family[family]
        if not rows:
            continue
        strong = max(rows, key=_reference_strength_score)
        weak = min(rows, key=_reference_strength_score)
        selected[(strong.ts, strong.direction, strong.family_hint)] = strong
        selected[(weak.ts, weak.direction, weak.family_hint)] = weak

    late_rows = [row for row in ranked if row.chain_role_hypothesis == "late_exhaustion"]
    unknown_rows = [row for row in ranked if row.chain_role_hypothesis == "unknown"]
    if late_rows:
        chosen = max(late_rows, key=lambda row: abs(row.adverse_max_30m or 0.0))
        selected[(chosen.ts, chosen.direction, chosen.family_hint)] = chosen
    if unknown_rows:
        chosen = unknown_rows[0]
        selected[(chosen.ts, chosen.direction, chosen.family_hint)] = chosen

    output: list[MinuteEventChainReferenceCaseRow] = []
    for row in sorted(selected.values(), key=lambda item: (item.day, item.ts, item.family_hint, item.direction)):
        confidence = "medium" if row.chain_role_hypothesis in {"seed", "release", "continuation"} else "low"
        output.append(
            MinuteEventChainReferenceCaseRow(
                ts=row.ts,
                day=row.day,
                direction=row.direction,
                family_hint=row.family_hint,
                chain_role_label=f"provisional_{row.chain_role_hypothesis}",
                role_confidence=confidence,
                phase_marker_vs_entry_candidate="entry_candidate" if row.candidate_rank_in_window == 1 else "post_entry_chain",
                reference_window_id=row.reference_window_id,
                pre_window_summary=(
                    f"pre: cum_delta_60m={_fmt_num(row.cum_delta_60m)}; ret_15m={_fmt_num(row.ret_15m)}; "
                    f"vwap_side={row.price_vs_vwap_side}"
                ),
                post_window_summary=(
                    f"post: ret_fwd_30m={_fmt_num(row.ret_fwd_30m)}; ret_fwd_60m={_fmt_num(row.ret_fwd_60m)}; "
                    f"favorable_30m={_fmt_num(row.favorable_max_30m)}"
                ),
                move_followthrough_notes=(
                    "followthrough supportive" if (row.favorable_max_30m or 0.0) >= (row.adverse_max_30m or 0.0) else "followthrough weak"
                ),
                invalidating_notes=(
                    "adverse excursion dominates" if (row.adverse_max_30m or 0.0) > (row.favorable_max_30m or 0.0) else "no strong invalidation observed"
                ),
            )
        )
    return output


def build_cluster_summaries(candidates: list[MinuteEventChainCandidateRow]) -> list[ChainClusterSummaryRow]:
    if not candidates:
        return []
    grouped: dict[str, list[MinuteEventChainCandidateRow]] = {}
    for row in candidates:
        grouped.setdefault(row.reference_window_id, []).append(row)

    output: list[ChainClusterSummaryRow] = []
    for window_id in sorted(grouped):
        rows = sorted(grouped[window_id], key=lambda row: row.ts)
        role_set = {row.chain_role_hypothesis for row in rows}
        if len(rows) == 1 and rows[0].chain_role_hypothesis == "seed":
            pattern = "seed_only"
        elif any(row.chain_role_hypothesis == "seed" for row in rows) and any(
            row.chain_role_hypothesis == "release" for row in rows
        ):
            pattern = "seed_then_release"
        elif len(rows) == 1 and rows[0].chain_role_hypothesis == "release":
            pattern = "release_only"
        elif role_set == {"continuation"}:
            pattern = "continuation_cluster"
        elif "late_exhaustion" in role_set:
            pattern = "late_mixed"
        else:
            pattern = "ambiguous"

        family_counts: dict[str, int] = {}
        for row in rows:
            family_counts[row.family_hint] = family_counts.get(row.family_hint, 0) + 1
        mix = "|".join(f"{name}:{family_counts[name]}" for name in sorted(family_counts))

        long_count = sum(1 for row in rows if row.direction == "long")
        short_count = sum(1 for row in rows if row.direction == "short")
        directional_bias = "long" if long_count > short_count else "short" if short_count > long_count else "mixed"

        output.append(
            ChainClusterSummaryRow(
                reference_window_id=window_id,
                day=rows[0].day,
                directional_bias=directional_bias,
                candidate_count=len(rows),
                family_mix=mix,
                earliest_ts=rows[0].ts,
                latest_ts=rows[-1].ts,
                provisional_chain_pattern=pattern,
                contains_seed_flag="seed" in role_set,
                contains_release_flag="release" in role_set,
                contains_continuation_flag="continuation" in role_set,
                contains_late_flag="late_exhaustion" in role_set,
            )
        )
    return output


def _build_candidates(merged_rows: list[dict[str, object]]) -> list[MinuteEventChainCandidateRow]:
    if not merged_rows:
        return []
    selected: list[dict[str, object]] = []
    for row in merged_rows:
        family_hint = _assign_family_hint(row)
        if family_hint not in SUPPORTED_FAMILIES:
            continue
        row = dict(row)
        row["family_hint"] = family_hint
        selected.append(row)

    selected.sort(key=lambda row: (str(row["day"]), row["ts"], str(row.get("direction", "")), str(row.get("family_hint", ""))))

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in selected:
        grouped.setdefault((str(row["day"]), str(row["direction"])), []).append(row)

    for (_, direction), rows in grouped.items():
        window_num = 0
        last_ts: datetime | None = None
        last_window_num = 0
        for idx, row in enumerate(rows):
            ts = row["ts"]
            if last_ts is None or (ts - last_ts).total_seconds() / 60.0 > WINDOW_GAP_MINUTES:
                window_num += 1
                last_window_num = window_num
                rank = 1
            else:
                rank = sum(1 for prior in rows[:idx] if prior.get("reference_window_id") == f"{row['day']}_{direction}_w{last_window_num:03d}") + 1
            row["reference_window_id"] = f"{row['day']}_{direction}_w{last_window_num:03d}"
            row["candidate_rank_in_window"] = rank
            row["minutes_from_prev_candidate_same_family"] = _minutes_since_prev(rows, idx, family_filter=str(row["family_hint"]))
            row["minutes_from_prev_candidate_any_family"] = _minutes_since_prev(rows, idx, family_filter=None)
            last_ts = ts

    by_window: dict[str, list[dict[str, object]]] = {}
    for row in selected:
        by_window.setdefault(str(row["reference_window_id"]), []).append(row)

    for rows in by_window.values():
        rows.sort(key=lambda row: row["ts"])
        for idx, row in enumerate(rows):
            row["chain_role_hypothesis"] = _assign_chain_role(row, idx)
            row["reference_case_flag"] = False
            row["notes"] = ""

    candidates = [
        MinuteEventChainCandidateRow(
            ts=row["ts"],
            day=str(row["day"]),
            direction=str(row["direction"]),
            family_hint=str(row["family_hint"]),
            chain_role_hypothesis=str(row["chain_role_hypothesis"]),
            reference_window_id=str(row["reference_window_id"]),
            price_vs_vwap_side=str(row.get("price_vs_vwap_side", "at_or_unknown")),
            cum_delta_24h=_as_float(row.get("cum_delta_24h")),
            cum_delta_180m=_as_float(row.get("cum_delta_180m")),
            cum_delta_60m=_as_float(row.get("cum_delta_60m")),
            ret_15m=_as_float(row.get("ret_15m")),
            ret_60m=_as_float(row.get("ret_60m")),
            delta_1m=_as_float(row.get("delta_1m")),
            vol_1m=_as_float(row.get("vol_1m")),
            imbalance_1m=_as_float(row.get("imbalance_1m")),
            delta_price_alignment_1m=str(row.get("delta_price_alignment_1m", "flat_or_unknown")),
            delta_price_efficiency_1m=_as_float(row.get("delta_price_efficiency_1m")),
            dist_from_vwap=_as_float(row.get("dist_from_vwap")),
            open_interest=_as_float(row.get("open_interest")),
            funding_rate=_as_float(row.get("funding_rate")),
            liq_buy_qty=_as_float(row.get("liq_buy_qty")),
            liq_sell_qty=_as_float(row.get("liq_sell_qty")),
            ret_fwd_30m=_as_float(row.get("ret_fwd_30m")),
            ret_fwd_60m=_as_float(row.get("ret_fwd_60m")),
            favorable_max_30m=_as_float(row.get("favorable_max_30m")),
            adverse_max_30m=_as_float(row.get("adverse_max_30m")),
            notes=str(row.get("notes", "")),
            reference_case_flag=bool(row.get("reference_case_flag", False)),
            minutes_from_prev_candidate_same_family=_as_float(row.get("minutes_from_prev_candidate_same_family")),
            minutes_from_prev_candidate_any_family=_as_float(row.get("minutes_from_prev_candidate_any_family")),
            candidate_rank_in_window=int(row.get("candidate_rank_in_window", 1)),
        )
        for row in selected
    ]
    return sorted(candidates, key=lambda row: (row.day, row.ts, row.direction, row.family_hint, row.reference_window_id))


def _build_merged_rows(mechanics_rows: list[dict[str, str]], outcomes_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    outcomes_by_key = {(row.get("day", ""), row.get("ts", "")): row for row in outcomes_rows}
    ordered_mechanics = sorted(
        [dict(row) for row in mechanics_rows],
        key=lambda row: (str(row.get("day", "")), _parse_ts(row.get("ts", "")) or datetime.min),
    )

    by_day: dict[str, list[dict[str, object]]] = {}
    for row in ordered_mechanics:
        day = str(row.get("day", ""))
        ts = _parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        outcome = outcomes_by_key.get((day, row.get("ts", "")), {})
        merged = dict(row)
        merged.update(
            {
                "ts": ts,
                "direction": _resolve_direction(outcome, row),
                "ret_fwd_30m": _as_float(outcome.get("ret_fwd_30m")),
                "ret_fwd_60m": _as_float(outcome.get("ret_fwd_60m")),
                "favorable_max_30m": _as_float(outcome.get("favorable_max_30m")),
                "adverse_max_30m": _as_float(outcome.get("adverse_max_30m")),
            }
        )
        by_day.setdefault(day, []).append(merged)

    enriched: list[dict[str, object]] = []
    for day in sorted(by_day):
        day_rows = sorted(by_day[day], key=lambda row: row["ts"])
        closes = [_as_float(row.get("close")) for row in day_rows]
        deltas = [_as_float(row.get("delta_1m")) for row in day_rows]

        for idx, row in enumerate(day_rows):
            row = dict(row)
            row["cum_delta_24h"] = _rolling_sum(deltas, idx, 24 * 60)
            row["cum_delta_180m"] = _rolling_sum(deltas, idx, 180)
            row["cum_delta_60m"] = _rolling_sum(deltas, idx, 60)
            row["ret_15m"] = _backward_return(closes, idx, 15)
            row["ret_60m"] = _backward_return(closes, idx, 60)
            enriched.append(row)
    return sorted(enriched, key=lambda row: (str(row.get("day", "")), row["ts"]))


def _assign_family_hint(row: dict[str, object]) -> str | None:
    abs_delta = abs(_as_float(row.get("delta_1m")) or 0.0)
    abs_imbalance = abs(_as_float(row.get("imbalance_1m")) or 0.0)
    vol = _as_float(row.get("vol_1m")) or 0.0
    dist_vwap = abs(_as_float(row.get("dist_from_vwap")) or 0.0)
    favorable_30 = _as_float(row.get("favorable_max_30m")) or 0.0
    adverse_30 = _as_float(row.get("adverse_max_30m")) or 0.0
    aligned = str(row.get("delta_price_alignment_1m", "")) == "aligned"

    if aligned and abs_delta >= 35.0 and (favorable_30 - adverse_30) >= 15.0 and vol >= 25.0:
        return "F2"
    if abs_delta >= 20.0 and abs_imbalance >= 0.45 and dist_vwap >= 15.0:
        return "F1"
    return None


def _assign_chain_role(row: dict[str, object], rank_in_window_zero_based: int) -> str:
    family = str(row.get("family_hint", ""))
    favorable_30 = _as_float(row.get("favorable_max_30m")) or 0.0
    adverse_30 = _as_float(row.get("adverse_max_30m")) or 0.0
    ret_30 = _as_float(row.get("ret_fwd_30m")) or 0.0
    aligned = str(row.get("delta_price_alignment_1m", "")) == "aligned"

    if adverse_30 > favorable_30 * 1.2:
        return "late_exhaustion"
    if rank_in_window_zero_based == 0 and family == "F2" and aligned:
        return "seed"
    if rank_in_window_zero_based == 0 and family == "F1" and aligned:
        return "release"
    if rank_in_window_zero_based > 0 and family == "F1" and aligned and ret_30 != 0.0:
        return "continuation"
    return "unknown"


def _minutes_since_prev(rows: list[dict[str, object]], idx: int, family_filter: str | None) -> float | None:
    if idx <= 0:
        return None
    current_ts = rows[idx]["ts"]
    for prev_idx in range(idx - 1, -1, -1):
        if family_filter and str(rows[prev_idx].get("family_hint")) != family_filter:
            continue
        prev_ts = rows[prev_idx]["ts"]
        return (current_ts - prev_ts).total_seconds() / 60.0
    return None


def _resolve_direction(outcome_row: dict[str, str], mechanics_row: dict[str, str]) -> str:
    direction = str(outcome_row.get("reference_direction", "")).strip().lower()
    if direction == "up":
        return "long"
    if direction == "down":
        return "short"
    delta_sign = str(mechanics_row.get("delta_sign", "")).strip().lower()
    if delta_sign == "positive":
        return "long"
    if delta_sign == "negative":
        return "short"
    return "unknown"


def _reference_strength_score(row: MinuteEventChainCandidateRow) -> float:
    return (row.favorable_max_30m or 0.0) - (row.adverse_max_30m or 0.0)


def _rolling_sum(values: list[float | None], idx: int, lookback_rows: int) -> float | None:
    start = max(0, idx - lookback_rows + 1)
    window = [value for value in values[start : idx + 1] if value is not None]
    if not window:
        return None
    return float(sum(window))


def _backward_return(closes: list[float | None], idx: int, lookback_rows: int) -> float | None:
    current = closes[idx]
    anchor_idx = idx - lookback_rows
    if current is None or anchor_idx < 0:
        return None
    anchor = closes[anchor_idx]
    if anchor is None:
        return None
    return current - anchor


def _resolve_scope_dates(
    input_root: str,
    *,
    date: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, str]:
    if date:
        return date, date
    if date_from and date_to:
        return date_from, date_to
    if date_from and not date_to:
        return date_from, date_from

    dates = sorted(_discover_available_dates(Path(input_root), "minute_events_mechanics") & _discover_available_dates(Path(input_root), "minute_events_outcomes"))
    if not dates:
        raise ValueError("no overlapping minute_events_mechanics/minute_events_outcomes datasets found")
    return dates[0], dates[-1]


def _discover_available_dates(input_root: Path, dataset_name: str) -> set[str]:
    values: set[str] = set()
    for path in sorted(input_root.glob(f"{dataset_name}_*.csv")):
        date_part = path.stem.replace(f"{dataset_name}_", "")
        if _is_valid_date(date_part):
            values.add(date_part)
    return values


def _load_rows_for_scope(input_root: Path, dataset_name: str, date_from: str, date_to: str) -> list[dict[str, str]]:
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    if start > end:
        raise ValueError("date_from must be <= date_to")

    rows: list[dict[str, str]] = []
    cursor = start
    while cursor <= end:
        date_str = cursor.strftime("%Y-%m-%d")
        path = input_root / f"{dataset_name}_{date_str}.csv"
        if path.exists():
            rows.extend(_load_csv(path))
        cursor += timedelta(days=1)
    return rows


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_dataclass_csv(rows: list[object], out_path: Path, row_type: type[object]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    field_names = list(row_type.__dataclass_fields__.keys())
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: _serialize_value(asdict(row).get(name)) for name in field_names})


def _serialize_value(value: object) -> object:
    if value is None:
        return ""
    return value


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "na"
    return f"{value:.2f}"


def _parse_ts(value: str) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True
