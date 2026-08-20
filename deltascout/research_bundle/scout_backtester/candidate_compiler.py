from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .contracts import (
    BacktestContractError,
    Candidate,
    CandidateQualityRow,
    REQUIRED_GROUPS,
)


LOCAL_TZ = ZoneInfo("Europe/Bratislava")
TERMINAL_EVENTS = {
    "PEAK_EMIT",
    "CANDIDATE_COMPARISON_REJECT",
    "CANDIDATE_GATE_REJECT",
}
RAW_EVENTS = {"DELTA_MAX", "DELTA_MIN"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _boolean(value: Any) -> bool | None:
    text = _text(value).lower()
    if not text:
        return None
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def local_event_to_utc(value: Any) -> datetime:
    """Convert legacy Bratislava-local-naive event time to aware UTC.

    Ambiguous fall-back minutes and nonexistent spring-forward minutes are rejected;
    a replay must never guess which market minute a candidate belongs to.
    """
    text = _text(value)
    if not text:
        raise BacktestContractError("candidate timestamp is empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BacktestContractError(f"unparseable candidate timestamp={text!r}") from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)

    fold0 = parsed.replace(tzinfo=LOCAL_TZ, fold=0)
    fold1 = parsed.replace(tzinfo=LOCAL_TZ, fold=1)
    if fold0.utcoffset() != fold1.utcoffset():
        raise BacktestContractError(f"ambiguous Bratislava local timestamp={text!r}")
    result = fold0.astimezone(timezone.utc)
    roundtrip = result.astimezone(LOCAL_TZ).replace(tzinfo=None)
    if roundtrip != parsed:
        raise BacktestContractError(f"nonexistent Bratislava local timestamp={text!r}")
    return result


def _row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _event_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _text(row.get("ts")),
        _text(row.get("event") or row.get("event_type")),
        _text(row.get("kind")).lower(),
        _text(row.get("reject_reason")),
    )


def _raw_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_text(row.get("ts")), _text(row.get("kind")).lower())


def _load_raw_day(path: Path) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    terminals: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    raw_events: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.exists():
        return terminals, raw_events
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BacktestContractError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            event = _text(row.get("event"))
            if event in RAW_EVENTS:
                raw_events[_raw_key(row)] = row
            elif event in TERMINAL_EVENTS:
                terminals[_event_key(row)] = row
    return terminals, raw_events


def _comparison_diagnostics(row: dict[str, Any]) -> tuple[int | None, str | None]:
    if _text(row.get("reject_reason")) != "3of3_fail":
        return None, None
    explicit_count = _integer(row.get("comparison_3of3_pass_count"))
    explicit_failed = _text(row.get("comparison_3of3_failed_subconditions"))
    if explicit_count is not None:
        return explicit_count, explicit_failed or None

    kind = _text(row.get("kind")).lower()
    current_price = _number(row.get("price"))
    current_vol = _number(row.get("vol"))
    current_vwap = _number(row.get("vwap"))
    previous_price = _number(row.get("prev_price"))
    previous_vol = _number(row.get("prev_vol"))
    previous_vwap = _number(row.get("prev_vwap"))
    checks: list[tuple[str, bool | None]] = []
    checks.append(("price", None if current_price is None or previous_price is None else (current_price > previous_price if kind == "long" else current_price < previous_price)))
    checks.append(("vol", None if current_vol is None or previous_vol is None else current_vol > previous_vol))
    checks.append(("vwap", None if current_vwap is None or previous_vwap is None else (current_vwap > previous_vwap if kind == "long" else current_vwap < previous_vwap)))
    if any(value is None for _, value in checks):
        return None, None
    return (
        sum(1 for _, passed in checks if passed),
        "|".join(name for name, passed in checks if not passed) or None,
    )


def _candidate_group(event_type: str, reject_reason: str, pass_count: int | None) -> str:
    if event_type == "PEAK_EMIT":
        return "PEAK_EMIT_BASELINE"
    if event_type == "CANDIDATE_GATE_REJECT":
        return "GATE_REJECT"
    if reject_reason == "3of3_fail" and pass_count == 2:
        return "ALMOST_PEAK_2_OF_3"
    if reject_reason == "3of3_fail" and pass_count == 1:
        return "ALMOST_PEAK_1_OF_3"
    if reject_reason == "direction_mismatch":
        return "DIRECTION_MISMATCH_REJECT"
    if reject_reason == "vwap_side":
        return "VWAP_SIDE_REJECT"
    return "OTHER_COMPARISON_REJECT"


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _shadow_flags(row: dict[str, Any]) -> dict[str, bool | None]:
    percentile = _first_number(
        row.get("peak_percentile"),
        row.get("same_side_peak_percentile"),
        row.get("event_peak_percentile"),
    )
    weak = None if percentile is None else percentile <= 50.0
    oi_change = _first_number(row.get("oi_change_60m"), row.get("open_interest_change_60m"))
    directional_delta_pct = _first_number(
        row.get("directional_delta_pct_240"),
        row.get("directional_delta_pct_240m"),
    )
    oi_rule = None if oi_change is None or directional_delta_pct is None else oi_change < 0 and directional_delta_pct < 0.06
    known = [value for value in (weak, oi_rule) if value is not None]
    union = any(known) if known else None
    return {
        "weak_peak_le_50": weak,
        "oi_down_60_and_directional_delta_pct_240_lt_0_06": oi_rule,
        "loss_avoidance_conservative_union": union,
    }


def compile_candidates(
    candidate_root: Path,
    *,
    date_from: str,
    date_to: str,
    raw_archive_root: Path | None = None,
    candidate_groups: Iterable[str] | None = None,
    price_precision: int = 2,
) -> tuple[list[Candidate], list[CandidateQualityRow]]:
    selected_groups = set(candidate_groups or REQUIRED_GROUPS)
    unknown_groups = selected_groups.difference(REQUIRED_GROUPS)
    if unknown_groups:
        raise BacktestContractError(f"unknown candidate groups={sorted(unknown_groups)}")
    raw_archive_root = raw_archive_root or candidate_root.parent / "raw_archive"
    candidates: list[Candidate] = []
    quality: list[CandidateQualityRow] = []
    seen: dict[tuple[str, str, str, float], str] = {}

    paths = sorted(candidate_root.glob("*/events_context_*.csv"))
    for path in paths:
        day = path.parent.name
        if day < date_from or day > date_to:
            continue
        terminals, raw_events = _load_raw_day(raw_archive_root / f"{day}.jsonl")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"ts", "event_type", "kind"}
            missing = required.difference(reader.fieldnames or [])
            if missing:
                raise BacktestContractError(f"missing candidate columns={sorted(missing)} in {path}")
            for row_number, source_row in enumerate(reader, start=2):
                event_type = _text(source_row.get("event_type"))
                if event_type not in TERMINAL_EVENTS:
                    continue
                raw_terminal = terminals.get(_event_key(source_row), {})
                raw_delta = raw_events.get(_raw_key(source_row), {})
                merged = dict(raw_delta)
                merged.update(raw_terminal)
                for key, value in source_row.items():
                    if _text(value):
                        merged[key] = value
                try:
                    signal_ts = local_event_to_utc(merged.get("ts"))
                    side: Any = {"long": "LONG", "short": "SHORT"}.get(_text(merged.get("kind")).lower())
                    if side is None:
                        raise BacktestContractError(f"invalid side={merged.get('kind')!r}")
                    pass_count, failed = _comparison_diagnostics(merged)
                    reject_reason = _text(merged.get("reject_reason"))
                    group = _candidate_group(event_type, reject_reason, pass_count)
                    if group not in selected_groups:
                        continue
                    price = _first_number(merged.get("price"), merged.get("price_now"))
                    delta = _first_number(merged.get("delta"))
                    volume = _first_number(merged.get("vol"), merged.get("volume"))
                    if price is None or delta is None or volume is None:
                        raise BacktestContractError("candidate requires signal price, delta, and volume")
                    dedupe_key = (
                        signal_ts.replace(second=0, microsecond=0).isoformat(),
                        side,
                        event_type,
                        round(price, price_precision),
                    )
                    candidate_id = "SCOUT_" + hashlib.sha256("|".join(map(str, dedupe_key)).encode("utf-8")).hexdigest()[:20]
                    if dedupe_key in seen:
                        quality.append(CandidateQualityRow(str(path), row_number, "DUPLICATE_CANDIDATE", f"duplicate_of={seen[dedupe_key]}", candidate_id))
                        continue
                    seen[dedupe_key] = candidate_id
                    source_hash = _row_hash(merged)
                    candidates.append(
                        Candidate(
                            candidate_id=candidate_id,
                            source_event_ts_local=_text(merged.get("ts")),
                            signal_ts_utc=signal_ts,
                            side=side,
                            event_type=event_type,
                            candidate_group=group,
                            reject_reason=reject_reason or None,
                            signal_price=price,
                            delta=delta,
                            volume=volume,
                            imbalance=_first_number(merged.get("imb"), merged.get("imbalance")),
                            vwap=_first_number(merged.get("vwap"), merged.get("vwap_now")),
                            poc=_first_number(merged.get("poc")),
                            comparison_3of3_pass_count=pass_count,
                            comparison_3of3_failed_subconditions=failed,
                            shadow_flags=_shadow_flags(merged),
                            source_path=str(path),
                            source_row_hash=source_hash,
                        )
                    )
                except BacktestContractError as exc:
                    quality.append(CandidateQualityRow(str(path), row_number, "INVALID_CANDIDATE", str(exc)))

    candidates.sort(key=lambda item: (item.signal_ts_utc, item.candidate_id))
    if not paths:
        raise BacktestContractError(f"no events_context CSV files found under {candidate_root}")
    return candidates, quality


def write_candidate_artifacts(
    candidates: Iterable[Candidate],
    quality_rows: Iterable[CandidateQualityRow],
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = output_dir / "normalized_candidates.csv"
    quality_path = output_dir / "candidate_quality.csv"
    candidate_rows = [candidate.to_dict() for candidate in candidates]
    for row in candidate_rows:
        row["shadow_flags"] = json.dumps(row["shadow_flags"], sort_keys=True, separators=(",", ":"))
    candidate_fields = list(candidate_rows[0]) if candidate_rows else list(Candidate.__dataclass_fields__)
    with candidates_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=candidate_fields)
        writer.writeheader()
        writer.writerows(candidate_rows)
    quality_dicts = [vars(row) for row in quality_rows]
    quality_fields = list(CandidateQualityRow.__dataclass_fields__)
    with quality_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=quality_fields)
        writer.writeheader()
        writer.writerows(quality_dicts)
    return candidates_path, quality_path
