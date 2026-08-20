from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from math import isnan
from statistics import mean, median
from typing import Any

from scripts.offline.common import read_jsonl

ACCEPTED_EVENT_TYPE = "PEAK_EMIT"
REJECT_EVENT_TYPES = (
    "CANDIDATE_COMPARISON_REJECT",
    "CANDIDATE_GATE_REJECT",
)
MATCHED_FEED_FIELDS = (
    "matched_open_interest",
    "matched_funding_rate",
    "matched_liq_buy_qty",
    "matched_liq_sell_qty",
)
BASE_FIELDS = (
    "ts",
    "day",
    "event_type",
    "kind",
    "reject_reason",
    "delta",
    "vol",
    "imb",
    "price",
    "vwap",
    "poc",
    "matched_feed_ts",
)
REVIEW_SHARED_FIELDS = BASE_FIELDS + MATCHED_FEED_FIELDS + (
    "source_file",
    "terminal_decision_present",
)
CONTEXT_FIELDS = (
    "cum_delta_24h",
    "cum_delta_180m",
    "cum_delta_60m",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
    "abs_dist_vwap",
    "price_vs_vwap_side",
)
ACCEPTED_JOIN_FIELDS = (
    "join_status",
    "join_confidence",
    "close_ts",
    "close_reason",
    "entry",
    "side",
    "final_close_ts",
    "final_close_reason",
    "lifecycle_tp1_done",
    "lifecycle_tp2_done",
    "lifecycle_sl_done",
    "lifecycle_trail_active",
    "lifecycle_trail_sl_price",
    "lifecycle_prices_entry",
    "lifecycle_prices_sl",
    "lifecycle_prices_tp1",
    "lifecycle_prices_tp2",
    "trade_lifecycle_state",
)
ACCEPTED_CLOSE_LOOKAHEAD_DAYS = 3
REJECT_REASON_SUMMARY_FIELDS = (
    "date",
    "reject_reason",
    "kind",
    "count",
    "cum_delta_60m_mean",
    "cum_delta_60m_median",
    "cum_delta_180m_mean",
    "cum_delta_180m_median",
    "ret_15m_mean",
    "ret_15m_median",
    "ret_60m_mean",
    "ret_60m_median",
    "dist_vwap_mean",
    "dist_vwap_median",
    "abs_dist_vwap_mean",
    "abs_dist_vwap_median",
    "price_vs_vwap_side_mode",
    "price_vs_vwap_side_mode_count",
)
REJECT_REASON_NUMERIC_FIELDS = (
    "cum_delta_60m",
    "cum_delta_180m",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
    "abs_dist_vwap",
)
UNKNOWN_REJECT_REASON = "UNKNOWN"
UNKNOWN_KIND = "UNKNOWN"
DEFAULT_MANUAL_CLOSE_OVERRIDES_FILE = Path("deltascout/research_material/manual_close_overrides.jsonl")


INTERESTING_REJECT_FIELDS = (
    "interesting_reject_flag",
    "interesting_reject_bucket",
    "interesting_reject_note",
    "interesting_rule_id",
)
INTERESTING_REJECT_EXCLUDED_REASONS = {"no_prev_peak", "imb_band"}
INTERESTING_REJECT_REASON_SET = {"direction_mismatch", "vwap_side", "3of3_fail"}
INTERESTING_REJECT_RULE_NOTES = {
    "IR_B1": "supportive 60m/180m flow and 15m return context despite reject",
    "IR_A1": "direction_mismatch with supportive 60m flow but weak/contrary 15m return",
    "IR_A2": "vwap_side reject near VWAP with directional cumulative buildup",
    "IR_D1": "strong cumulative flow with contrary price reaction; possible exhaustion probe",
    "IR_E1": "local directional pressure but broader context does not confirm",
    "IR_E2": "short-term continuation pressure against contrary medium-horizon context",
    "IR_C1": "supportive flow and return context despite vwap-side rejection",
    "IR_C2": "3of3 fail despite supportive medium-horizon pressure",
    "IR_F1": "contextually non-trivial reject retained for review",
}


class ReviewBuildError(RuntimeError):
    """Raised when deterministic review-builder inputs are missing or invalid."""


@dataclass(frozen=True)
class ReviewBuildResult:
    date: str
    accepted_count: int
    reject_count: int
    interesting_reject_count: int
    matched_close_count: int
    output_dir: Path
    accepted_path: Path
    reject_path: Path
    interesting_rejects_path: Path
    reject_reason_summary_path: Path
    summary_path: Path


def build_daily_review_package(
    date: str, input_root: Path | str, output_root: Path | str
) -> ReviewBuildResult:
    input_root = Path(input_root)
    output_root = Path(output_root)

    events_context_rows = _load_required_csv(
        input_root / f"events_context_{date}.csv", required_name="events_context"
    )
    close_outcome_rows_by_date = _load_forward_close_outcomes(
        input_root, date, ACCEPTED_CLOSE_LOOKAHEAD_DAYS
    )

    accepted_rows = build_accepted_event_context_rows(
        events_context_rows, close_outcome_rows_by_date
    )
    reject_rows = build_reject_event_context_rows(events_context_rows)
    interesting_reject_rows = build_interesting_reject_rows(reject_rows)

    review_dir = output_root / "reviews" / date
    review_dir.mkdir(parents=True, exist_ok=True)

    accepted_path = review_dir / f"accepted_event_context_{date}.csv"
    reject_path = review_dir / f"reject_event_context_{date}.csv"
    interesting_rejects_path = review_dir / f"interesting_rejects_{date}.csv"
    reject_reason_summary_path = review_dir / f"reject_reason_summary_{date}.csv"
    summary_path = review_dir / f"daily_review_summary_{date}.md"
    reject_reason_summary_rows = build_reject_reason_summary_rows(date, reject_rows)

    _write_csv(
        accepted_path,
        accepted_rows,
        REVIEW_SHARED_FIELDS + CONTEXT_FIELDS + ACCEPTED_JOIN_FIELDS,
    )
    reject_fields = _ordered_reject_fields(reject_rows)
    _write_csv(reject_path, reject_rows, reject_fields)
    _write_csv(
        interesting_rejects_path,
        interesting_reject_rows,
        _ordered_interesting_reject_fields(reject_fields, interesting_reject_rows),
    )
    _write_csv(
        reject_reason_summary_path,
        reject_reason_summary_rows,
        REJECT_REASON_SUMMARY_FIELDS,
    )
    summary_path.write_text(
        _build_summary(
            date,
            accepted_rows,
            reject_rows,
            interesting_reject_rows,
            reject_reason_summary_rows,
            accepted_path,
            reject_path,
            interesting_rejects_path,
            reject_reason_summary_path,
            summary_path,
        ),
        encoding="utf-8",
    )

    return ReviewBuildResult(
        date=date,
        accepted_count=len(accepted_rows),
        reject_count=len(reject_rows),
        interesting_reject_count=len(interesting_reject_rows),
        matched_close_count=sum(1 for row in accepted_rows if row.get("join_status") == "joined"),
        output_dir=review_dir,
        accepted_path=accepted_path,
        reject_path=reject_path,
        interesting_rejects_path=interesting_rejects_path,
        reject_reason_summary_path=reject_reason_summary_path,
        summary_path=summary_path,
    )


def build_accepted_event_context_rows(
    events_context_rows: list[dict[str, str]],
    close_outcome_rows_by_date: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in events_context_rows:
        if row.get("event_type") != ACCEPTED_EVENT_TYPE:
            continue
        output_row = {
            field: row.get(field, "") for field in REVIEW_SHARED_FIELDS + CONTEXT_FIELDS
        }
        close_row = _match_close_outcome_for_accepted_peak(
            row, close_outcome_rows_by_date
        )
        for field in ACCEPTED_JOIN_FIELDS:
            output_row[field] = close_row.get(field, "") if close_row else ""
        rows.append(output_row)
    return rows


def build_reject_event_context_rows(
    events_context_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in events_context_rows:
        if row.get("event_type") in REJECT_EVENT_TYPES:
            rows.append(dict(row))
    return rows


def build_interesting_reject_rows(
    reject_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in reject_rows:
        classification = _classify_interesting_reject(row)
        if classification is None:
            continue
        output_row = dict(row)
        output_row.update(classification)
        rows.append(output_row)
    return rows


def build_reject_reason_summary_rows(
    date: str,
    reject_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in reject_rows:
        reject_reason = (
            row.get("reject_reason") or ""
        ).strip() or UNKNOWN_REJECT_REASON
        kind = (row.get("kind") or "").strip() or UNKNOWN_KIND
        grouped.setdefault((reject_reason, kind), []).append(row)

    summary_rows: list[dict[str, str]] = []
    for reject_reason, kind in sorted(grouped):
        rows = grouped[(reject_reason, kind)]
        summary_row = {
            "date": date,
            "reject_reason": reject_reason,
            "kind": kind,
            "count": str(len(rows)),
        }
        for field in REJECT_REASON_NUMERIC_FIELDS:
            values = _collect_numeric_values(rows, field)
            summary_row[f"{field}_mean"] = _format_stat(values, mean)
            summary_row[f"{field}_median"] = _format_stat(values, median)
        mode_value, mode_count = _mode_with_count(rows, "price_vs_vwap_side")
        summary_row["price_vs_vwap_side_mode"] = mode_value
        summary_row["price_vs_vwap_side_mode_count"] = (
            str(mode_count) if mode_count else ""
        )
        summary_rows.append(summary_row)
    return summary_rows


def _classify_interesting_reject(row: dict[str, str]) -> dict[str, str] | None:
    reject_reason = (row.get("reject_reason") or "").strip()
    if reject_reason in INTERESTING_REJECT_EXCLUDED_REASONS:
        return None

    cum_delta_60m = _parse_float(row.get("cum_delta_60m", ""))
    ret_15m = _parse_float(row.get("ret_15m", ""))
    abs_dist_vwap = _parse_float(row.get("abs_dist_vwap", ""))
    if (
        cum_delta_60m is not None
        and ret_15m is not None
        and abs_dist_vwap is not None
        and abs(cum_delta_60m) < 150
        and abs(ret_15m) < 0.0015
        and abs(abs_dist_vwap) < 150
    ):
        return None

    rules = (
        _match_ir_b1,
        _match_ir_a1,
        _match_ir_a2,
        _match_ir_d1,
        _match_ir_e1,
        _match_ir_e2,
        _match_ir_c1,
        _match_ir_c2,
        _match_ir_f1,
    )
    for rule in rules:
        match = rule(row)
        if match is not None:
            return {
                "interesting_reject_flag": "1",
                "interesting_reject_bucket": match["bucket"],
                "interesting_reject_note": INTERESTING_REJECT_RULE_NOTES[match["rule_id"]],
                "interesting_rule_id": match["rule_id"],
            }
    return None


def _ordered_interesting_reject_fields(
    reject_fields: tuple[str, ...], rows: list[dict[str, str]]
) -> tuple[str, ...]:
    fields = list(reject_fields)
    for field in INTERESTING_REJECT_FIELDS:
        if field not in fields:
            fields.append(field)
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    return tuple(fields)


def _match_ir_b1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() not in {"vwap_side", "3of3_fail"}:
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not (
        _supports_kind(kind, row.get("cum_delta_60m"))
        and _supports_kind(kind, row.get("cum_delta_180m"))
        and _supports_kind(kind, row.get("ret_15m"))
        and _abs_at_most(row.get("abs_dist_vwap"), 500)
    ):
        return None
    return {"bucket": "possible_reversal_confirmation", "rule_id": "IR_B1"}


def _match_ir_a1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "direction_mismatch":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not _supports_kind(kind, row.get("cum_delta_60m")):
        return None
    if not (
        _supports_kind(kind, row.get("cum_delta_180m"))
        or _abs_below(row.get("cum_delta_180m"), 200)
    ):
        return None
    if not (
        _does_not_support_kind(kind, row.get("ret_15m"))
        or _abs_below(row.get("ret_15m"), 0.001)
    ):
        return None
    if not _abs_at_most(row.get("abs_dist_vwap"), 600):
        return None
    return {"bucket": "possible_reversal_onset", "rule_id": "IR_A1"}


def _match_ir_a2(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "vwap_side":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not (
        _supports_kind(kind, row.get("cum_delta_60m"))
        and _opposes_kind(kind, row.get("ret_15m"))
        and _abs_at_most(row.get("abs_dist_vwap"), 350)
    ):
        return None
    return {"bucket": "possible_reversal_onset", "rule_id": "IR_A2"}


def _match_ir_d1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "direction_mismatch":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not _supports_kind_with_threshold(kind, row.get("cum_delta_60m"), 400):
        return None
    if not _opposes_kind(kind, row.get("ret_15m")):
        return None
    if not (_opposes_kind(kind, row.get("ret_60m")) or _abs_below(row.get("ret_60m"), 0.001)):
        return None
    if not _abs_at_least(row.get("abs_dist_vwap"), 200):
        return None
    return {"bucket": "possible_exhaustion_probe", "rule_id": "IR_D1"}


def _match_ir_e1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "vwap_side":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not _supports_kind(kind, row.get("cum_delta_60m")):
        return None
    if not (_opposes_kind(kind, row.get("ret_60m")) or _opposes_kind(kind, row.get("cum_delta_180m"))):
        return None
    if not _abs_at_least(row.get("abs_dist_vwap"), 200):
        return None
    return {"bucket": "possible_trap_or_false_break", "rule_id": "IR_E1"}


def _match_ir_e2(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "3of3_fail":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not (
        _supports_kind(kind, row.get("ret_15m"))
        and _opposes_kind(kind, row.get("ret_60m"))
        and _does_not_support_kind(kind, row.get("cum_delta_180m"))
    ):
        return None
    return {"bucket": "possible_trap_or_false_break", "rule_id": "IR_E2"}


def _match_ir_c1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "vwap_side":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not (
        _supports_kind(kind, row.get("cum_delta_60m"))
        and _supports_kind(kind, row.get("ret_15m"))
        and _supports_kind(kind, row.get("ret_60m"))
        and _abs_at_most(row.get("abs_dist_vwap"), 800)
    ):
        return None
    return {"bucket": "possible_continuation_pressure", "rule_id": "IR_C1"}


def _match_ir_c2(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() != "3of3_fail":
        return None
    kind = _normalize_kind_key(row.get("kind"))
    if not kind:
        return None
    if not (
        _supports_kind(kind, row.get("cum_delta_60m"))
        and _supports_kind(kind, row.get("ret_60m"))
        and _abs_at_most(row.get("abs_dist_vwap"), 700)
    ):
        return None
    return {"bucket": "possible_continuation_pressure", "rule_id": "IR_C2"}


def _match_ir_f1(row: dict[str, str]) -> dict[str, str] | None:
    if (row.get("reject_reason") or "").strip() not in INTERESTING_REJECT_REASON_SET:
        return None
    conditions = sum(
        (
            _abs_at_least(row.get("cum_delta_60m"), 250),
            _abs_at_least(row.get("cum_delta_180m"), 400),
            _abs_at_least(row.get("ret_15m"), 0.002),
            _abs_at_least(row.get("abs_dist_vwap"), 250),
        )
    )
    if conditions < 2:
        return None
    return {"bucket": "unclear_but_constructive", "rule_id": "IR_F1"}


def _supports_kind(kind: str, value: Any) -> bool:
    parsed = _parse_float(value)
    if parsed is None:
        return False
    if kind == "long":
        return parsed > 0
    if kind == "short":
        return parsed < 0
    return False


def _supports_kind_with_threshold(kind: str, value: Any, threshold: float) -> bool:
    parsed = _parse_float(value)
    if parsed is None or abs(parsed) < threshold:
        return False
    return _supports_kind(kind, parsed)


def _opposes_kind(kind: str, value: Any) -> bool:
    parsed = _parse_float(value)
    if parsed is None:
        return False
    if kind == "long":
        return parsed < 0
    if kind == "short":
        return parsed > 0
    return False


def _does_not_support_kind(kind: str, value: Any) -> bool:
    parsed = _parse_float(value)
    if parsed is None:
        return False
    return not _supports_kind(kind, parsed)


def _abs_below(value: Any, threshold: float) -> bool:
    parsed = _parse_float(value)
    return parsed is not None and abs(parsed) < threshold


def _abs_at_most(value: Any, threshold: float) -> bool:
    parsed = _parse_float(value)
    return parsed is not None and abs(parsed) <= threshold


def _abs_at_least(value: Any, threshold: float) -> bool:
    parsed = _parse_float(value)
    return parsed is not None and abs(parsed) >= threshold


def _ordered_reject_fields(rows: list[dict[str, str]]) -> tuple[str, ...]:
    preferred = list(REVIEW_SHARED_FIELDS + CONTEXT_FIELDS)
    extras: list[str] = []
    for row in rows:
        for key in row:
            if key not in preferred and key not in extras:
                extras.append(key)
    return tuple(preferred + extras)


def _load_required_csv(path: Path, *, required_name: str) -> list[dict[str, str]]:
    if not path.exists():
        raise ReviewBuildError(f"missing {required_name} input: {path}")
    return _load_csv(path)


def _load_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return _load_csv(path)


def _load_manual_close_override_rows(date: str) -> list[dict[str, str]]:
    if not DEFAULT_MANUAL_CLOSE_OVERRIDES_FILE.exists():
        return []

    rows: list[dict[str, str]] = []
    for row in read_jsonl(DEFAULT_MANUAL_CLOSE_OVERRIDES_FILE):
        if not isinstance(row, dict):
            continue
        if str(row.get("source_date") or "").strip() != date:
            continue
        peak_ts = str(row.get("peak_ts") or "").strip()
        peak_kind = str(row.get("peak_kind") or "").strip()
        if not peak_ts or not peak_kind:
            continue
        rows.append(
            {
                "peak_ts": peak_ts,
                "peak_kind": peak_kind,
                "join_status": row.get("join_status", "manual_override"),
                "join_confidence": row.get("join_confidence", "1.0"),
                "close_ts": row.get("close_ts", ""),
                "close_reason": row.get("close_reason", ""),
                "entry": row.get("entry", ""),
                "side": row.get("side", ""),
                "final_close_ts": row.get("final_close_ts", row.get("close_ts", "")),
                "final_close_reason": row.get("final_close_reason", row.get("close_reason", "")),
                "lifecycle_tp1_done": row.get("lifecycle_tp1_done", ""),
                "lifecycle_tp2_done": row.get("lifecycle_tp2_done", ""),
                "lifecycle_sl_done": row.get("lifecycle_sl_done", ""),
                "lifecycle_trail_active": row.get("lifecycle_trail_active", ""),
                "lifecycle_trail_sl_price": row.get("lifecycle_trail_sl_price", ""),
                "lifecycle_prices_entry": row.get("lifecycle_prices_entry", row.get("entry", "")),
                "lifecycle_prices_sl": row.get("lifecycle_prices_sl", row.get("sl", "")),
                "lifecycle_prices_tp1": row.get("lifecycle_prices_tp1", ""),
                "lifecycle_prices_tp2": row.get("lifecycle_prices_tp2", ""),
                "trade_lifecycle_state": row.get("trade_lifecycle_state", "manual_override"),
                "schema": row.get("schema", "manual_close_override_v1"),
                "event": row.get("event", "MANUAL_CLOSE_OVERRIDE"),
                "record_ts": row.get("record_ts", ""),
                "symbol": row.get("symbol", ""),
                "source": row.get("source", "manual_user_confirmed"),
            }
        )
    return rows


def _merge_manual_close_override_rows(rows: list[dict[str, str]], manual_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not manual_rows:
        return rows

    existing_keys = {
        (_normalize_ts_key(row.get("peak_ts")), _normalize_kind_key(row.get("peak_kind")))
        for row in rows
        if _normalize_ts_key(row.get("peak_ts"))
    }
    merged = list(rows)
    for row in manual_rows:
        key = (_normalize_ts_key(row.get("peak_ts")), _normalize_kind_key(row.get("peak_kind")))
        if key in existing_keys:
            continue
        merged.append(row)
        existing_keys.add(key)
    return merged


def _load_optional_close_outcomes(input_root: Path, date: str) -> list[dict[str, str]]:
    csv_path = input_root / f"close_outcomes_{date}.csv"
    parquet_path = input_root / f"close_outcomes_{date}.parquet"
    rows: list[dict[str, str]] = []
    # Prefer CSV when both are present to match the review builder's existing file convention.
    if csv_path.exists():
        rows = _load_csv(csv_path)
    elif parquet_path.exists():
        rows = _load_parquet(parquet_path)
    return _merge_manual_close_override_rows(rows, _load_manual_close_override_rows(date))


def _load_forward_close_outcomes(
    input_root: Path, date: str, lookahead_days: int
) -> dict[str, list[dict[str, str]]]:
    rows_by_date: dict[str, list[dict[str, str]]] = {}
    start = datetime.strptime(date, "%Y-%m-%d")
    for offset in range(lookahead_days + 1):
        lookup_date = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        rows_by_date[lookup_date] = _load_optional_close_outcomes_for_date(input_root, lookup_date)
    return rows_by_date


def _load_optional_close_outcomes_for_date(
    input_root: Path, date: str
) -> list[dict[str, str]]:
    for candidate_root in _candidate_close_lookup_roots(input_root, date):
        rows = _load_optional_close_outcomes(candidate_root, date)
        if rows:
            return rows
    return []


def _candidate_close_lookup_roots(input_root: Path, date: str) -> list[Path]:
    roots: list[Path] = [input_root]
    if input_root.name.count("-") == 2:
        roots.append(input_root.parent / date)
    else:
        roots.append(input_root / date)
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_parquet(path: Path) -> list[dict[str, str]]:
    try:
        pd = import_module("pandas")
    except ModuleNotFoundError as exc:
        raise ReviewBuildError(
            f"parquet close_outcomes requires pandas: {path}"
        ) from exc
    rows = pd.read_parquet(path).fillna("").to_dict(orient="records")
    return [
        {str(key): "" if value is None else str(value) for key, value in row.items()}
        for row in rows
    ]


def _index_close_outcomes(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    indexed: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (
            _normalize_ts_key(row.get("peak_ts")),
            _normalize_kind_key(row.get("peak_kind")),
        )
        if not key[0]:
            continue
        indexed.setdefault(key, []).append(row)
    return indexed


def _match_close_outcome_for_accepted_peak(
    accepted_row: dict[str, str],
    close_outcome_rows_by_date: dict[str, list[dict[str, str]]],
) -> dict[str, str]:
    peak_key = (
        _normalize_ts_key(accepted_row.get("ts")),
        _normalize_kind_key(accepted_row.get("kind")),
    )
    exact_matches: list[dict[str, str]] = []
    for rows in close_outcome_rows_by_date.values():
        indexed = _index_close_outcomes(rows)
        exact_matches.extend(indexed.get(peak_key, []))

    if len(exact_matches) == 1:
        return _build_accepted_join_row(exact_matches[0], "joined", "1.0")
    if len(exact_matches) > 1:
        return _build_unresolved_accepted_join_row("ambiguous")
    return _build_unresolved_accepted_join_row("missing")


def _build_accepted_join_row(
    close_row: dict[str, str], linkage_status: str, linkage_confidence: str
) -> dict[str, str]:
    final_close_ts = close_row.get("close_ts", "")
    final_close_reason = close_row.get("close_reason", "")
    return {
        "join_status": linkage_status,
        "join_confidence": linkage_confidence,
        "close_ts": final_close_ts,
        "close_reason": final_close_reason,
        "entry": close_row.get("entry", ""),
        "side": close_row.get("side", ""),
        "final_close_ts": final_close_ts,
        "final_close_reason": final_close_reason,
        "lifecycle_tp1_done": _close_row_value(
            close_row, "lifecycle_tp1_done", "lc_tp1_done"
        ),
        "lifecycle_tp2_done": _close_row_value(
            close_row, "lifecycle_tp2_done", "lc_tp2_done"
        ),
        "lifecycle_sl_done": _close_row_value(close_row, "lifecycle_sl_done", "lc_sl_done"),
        "lifecycle_trail_active": _close_row_value(
            close_row, "lifecycle_trail_active", "lc_trail_active"
        ),
        "lifecycle_trail_sl_price": _close_row_value(
            close_row, "lifecycle_trail_sl_price", "lc_trail_sl_price"
        ),
        "lifecycle_prices_entry": _close_row_value(
            close_row, "lifecycle_prices_entry", "lc_prices_entry"
        ),
        "lifecycle_prices_sl": _close_row_value(
            close_row, "lifecycle_prices_sl", "lc_prices_sl"
        ),
        "lifecycle_prices_tp1": _close_row_value(
            close_row, "lifecycle_prices_tp1", "lc_prices_tp1"
        ),
        "lifecycle_prices_tp2": _close_row_value(
            close_row, "lifecycle_prices_tp2", "lc_prices_tp2"
        ),
        "trade_lifecycle_state": close_row.get("trade_lifecycle_state", ""),
    }


def _close_row_value(close_row: dict[str, str], primary_key: str, fallback_key: str) -> str:
    value = close_row.get(primary_key, "")
    if str(value).strip():
        return value
    return close_row.get(fallback_key, "")


def _build_unresolved_accepted_join_row(linkage_status: str) -> dict[str, str]:
    row = {field: "" for field in ACCEPTED_JOIN_FIELDS}
    row["join_status"] = linkage_status
    row["join_confidence"] = "0.0"
    return row


def _normalize_ts_key(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.replace(microsecond=0).isoformat()


def _normalize_kind_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _collect_numeric_values(rows: list[dict[str, str]], field: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        parsed = _parse_float(row.get(field, ""))
        if parsed is not None:
            values.append(parsed)
    return values


def _parse_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if isnan(parsed):
        return None
    return parsed


def _format_stat(values: list[float], aggregator: Any) -> str:
    if not values:
        return ""
    return format(aggregator(values), "g")


def _mode_with_count(rows: list[dict[str, str]], field: str) -> tuple[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = (row.get(field) or "").strip()
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return "", 0
    mode_value, mode_count = sorted(
        counts.items(), key=lambda item: (-item[1], item[0])
    )[0]
    return mode_value, mode_count


def _write_csv(
    path: Path, rows: list[dict[str, str]], fieldnames: tuple[str, ...]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _build_summary(
    date: str,
    accepted_rows: list[dict[str, str]],
    reject_rows: list[dict[str, str]],
    interesting_reject_rows: list[dict[str, str]],
    reject_reason_summary_rows: list[dict[str, str]],
    accepted_path: Path,
    reject_path: Path,
    interesting_rejects_path: Path,
    reject_reason_summary_path: Path,
    summary_path: Path,
) -> str:
    matched_close_count = sum(1 for row in accepted_rows if row.get("join_status") == "joined")
    reason_counts: dict[str, int] = {}
    for row in reject_reason_summary_rows:
        reason = row.get("reject_reason", "")
        reason_counts[reason] = reason_counts.get(reason, 0) + int(
            row.get("count") or 0
        )

    lines = [
        f"# Daily Review Summary {date}",
        "",
        f"- processed_date: {date}",
        f"- accepted_row_count: {len(accepted_rows)}",
        f"- reject_row_count: {len(reject_rows)}",
        f"- interesting_reject_row_count: {len(interesting_reject_rows)}",
        f"- accepted_with_close_outcomes: {matched_close_count}",
        f"- reject_reason_summary_created: {reject_reason_summary_path.name}",
        f"- reject_reason_summary_group_count: {len(reject_reason_summary_rows)}",
        "- reject_counts_by_reason:",
    ]
    if reason_counts:
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"  - {reason}: {count}")
    else:
        lines.append("  - <none>: 0")
    lines.extend(
        [
            "- files_created:",
            f"  - {accepted_path.name}",
            f"  - {reject_path.name}",
            f"  - {interesting_rejects_path.name}",
            f"  - {reject_reason_summary_path.name}",
            f"  - {summary_path.name}",
            "",
        ]
    )
    return "\n".join(lines)
