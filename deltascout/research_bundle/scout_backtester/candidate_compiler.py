from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from deltascout.loss_avoidance_policy import evaluate_loss_avoidance_policy

from .contracts import (
    BacktestContractError,
    Candidate,
    CandidateQualityRow,
    REQUIRED_GROUPS,
)


LOCAL_TZ = ZoneInfo("Europe/Bratislava")
TERMINAL_EVENTS = {
    "PEAK_EMIT",
    "PEAK_LOSS_FILTER_REJECT",
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


def _normalize_filter_reject(row: dict[str, Any]) -> dict[str, Any]:
    if _text(row.get("event")) != "PEAK_LOSS_FILTER_REJECT":
        return row
    would_be_peak = row.get("would_be_peak")
    normalized = dict(would_be_peak) if isinstance(would_be_peak, dict) else {}
    normalized.update(row)
    normalized["event"] = "PEAK_LOSS_FILTER_REJECT"
    normalized["event_type"] = "PEAK_LOSS_FILTER_REJECT"
    normalized.setdefault("reject_reason", "loss_avoidance_union")
    return normalized


def _load_raw_day(
    path: Path,
) -> tuple[
    dict[tuple[str, str, str, str], dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
    list[tuple[int, dict[str, Any]]],
]:
    terminals: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    raw_events: dict[tuple[str, str], dict[str, Any]] = {}
    filter_rejects: list[tuple[int, dict[str, Any]]] = []
    if not path.exists():
        return terminals, raw_events, filter_rejects
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BacktestContractError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            row = _normalize_filter_reject(row)
            event = _text(row.get("event"))
            if event in RAW_EVENTS:
                raw_events[_raw_key(row)] = row
            elif event in TERMINAL_EVENTS:
                terminals[_event_key(row)] = row
                if event == "PEAK_LOSS_FILTER_REJECT":
                    filter_rejects.append((line_number, row))
    return terminals, raw_events, filter_rejects


def comparison_diagnostics(row: dict[str, Any]) -> dict[str, Any]:
    if _text(row.get("reject_reason")) != "3of3_fail":
        return {
            "price_pass": None, "vol_pass": None, "vwap_pass": None,
            "pass_count": None, "failed": None, "variant": None,
            "previous_price": None, "previous_vol": None, "previous_vwap": None,
            "valid": True, "quality_detail": "",
        }

    kind = _text(row.get("kind")).lower()
    current_price = _first_number(row.get("price"), row.get("price_now"))
    current_vol = _first_number(row.get("vol"), row.get("volume"))
    current_vwap = _first_number(row.get("vwap"), row.get("vwap_now"))
    previous_price = _number(row.get("prev_price"))
    previous_vol = _number(row.get("prev_vol"))
    previous_vwap = _number(row.get("prev_vwap"))
    if kind not in {"long", "short"}:
        checks = [("price", None), ("vol", None), ("vwap", None)]
    else:
        checks = []
        checks.append(("price", None if current_price is None or previous_price is None else (current_price > previous_price if kind == "long" else current_price < previous_price)))
        checks.append(("vol", None if current_vol is None or previous_vol is None else current_vol > previous_vol))
        checks.append(("vwap", None if current_vwap is None or previous_vwap is None else (current_vwap > previous_vwap if kind == "long" else current_vwap < previous_vwap)))
    values = {name: passed for name, passed in checks}
    valid = not any(value is None for value in values.values())
    pass_count = sum(value is True for value in values.values()) if valid else None
    failed_names = [name for name, passed in checks if passed is False]
    failed = ("|".join(failed_names) or None) if valid else None
    variant = None
    if pass_count == 2 and len(failed_names) == 1:
        variant = {
            "price": "ALMOST_2OF3_PRICE_FAIL",
            "vol": "ALMOST_2OF3_VOLUME_FAIL",
            "vwap": "ALMOST_2OF3_VWAP_FAIL",
        }[failed_names[0]]
    missing = [name for name, value in values.items() if value is None]
    return {
        "price_pass": values["price"], "vol_pass": values["vol"], "vwap_pass": values["vwap"],
        "pass_count": pass_count, "failed": failed, "variant": variant,
        "previous_price": previous_price, "previous_vol": previous_vol, "previous_vwap": previous_vwap,
        "valid": valid,
        "quality_detail": f"missing_or_invalid={('|'.join(missing) or 'none')}; kind={kind or 'missing'}",
    }


def _comparison_diagnostics(row: dict[str, Any]) -> tuple[int | None, str | None]:
    diagnostics = comparison_diagnostics(row)
    return diagnostics["pass_count"], diagnostics["failed"]


def _candidate_group(event_type: str, reject_reason: str, pass_count: int | None) -> str:
    if event_type in {"PEAK_EMIT", "PEAK_LOSS_FILTER_REJECT"}:
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


def _shadow_flags(row: dict[str, Any]) -> dict[str, Any]:
    explicit_a = _boolean(row.get("component_a"))
    explicit_b = _boolean(row.get("component_b"))
    explicit_union = _boolean(row.get("union"))
    percentile = _first_number(
        row.get("same_side_peak_percentile_24h"),
        row.get("peak_percentile"),
        row.get("same_side_peak_percentile"),
        row.get("event_peak_percentile"),
    )
    weak = explicit_a if explicit_a is not None else (None if percentile is None else percentile <= 50.0)
    oi_change = _first_number(row.get("oi_change_60m"), row.get("open_interest_change_60m"))
    directional_delta_pct = _first_number(
        row.get("directional_delta_pct_240"),
        row.get("directional_delta_pct_240m"),
    )
    oi_trusted = _boolean(row.get("oi_trusted_60m"))
    if oi_trusted is None:
        oi_trusted = oi_change is not None and directional_delta_pct is not None
    policy = evaluate_loss_avoidance_policy(
        same_side_peak_percentile_24h=percentile,
        oi_change_60m=oi_change,
        oi_trusted_60m=oi_trusted,
        directional_delta_pct_240m=directional_delta_pct,
    )
    oi_rule = explicit_b if explicit_b is not None else policy.component_b
    union = explicit_union if explicit_union is not None else (
        True if weak is True or oi_rule is True else False if weak is False and oi_rule is False else None
    )
    return {
        "weak_peak_le_50": weak,
        "oi_down_60_and_directional_delta_pct_240_lt_0_06": oi_rule,
        "loss_avoidance_conservative_union": union,
        "same_side_peak_count_24h": _integer(row.get("same_side_peak_count_24h")),
        "same_side_peak_percentile_24h": percentile,
        "oi_change_60m": oi_change,
        "oi_trusted_60m": oi_trusted,
        "directional_delta_pct_240m": directional_delta_pct,
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

    def append_candidate(
        merged: dict[str, Any],
        *,
        event_type: str,
        source_path: Path,
        row_number: int,
        suppress_duplicate_quality: bool = False,
    ) -> None:
        try:
            signal_ts = local_event_to_utc(merged.get("ts"))
            side: Any = {"long": "LONG", "short": "SHORT"}.get(_text(merged.get("kind")).lower())
            if side is None:
                raise BacktestContractError(f"invalid side={merged.get('kind')!r}")
            comparison = comparison_diagnostics(merged)
            pass_count, failed = comparison["pass_count"], comparison["failed"]
            reject_reason = _text(merged.get("reject_reason"))
            group = _candidate_group(event_type, reject_reason, pass_count)
            if reject_reason == "3of3_fail" and not comparison["valid"]:
                quality.append(
                    CandidateQualityRow(
                        str(source_path), row_number, "COMPARISON_CLASSIFICATION_INVALID",
                        comparison["quality_detail"],
                    )
                )
            if group not in selected_groups:
                return
            price = _first_number(merged.get("price"), merged.get("price_now"))
            delta = _first_number(merged.get("delta"))
            volume = _first_number(merged.get("vol"), merged.get("volume"))
            if price is None or delta is None or volume is None:
                raise BacktestContractError("candidate requires signal price, delta, and volume")
            identity_event_type = "PEAK_EMIT" if event_type == "PEAK_LOSS_FILTER_REJECT" else event_type
            dedupe_key = (
                signal_ts.replace(second=0, microsecond=0).isoformat(),
                side,
                identity_event_type,
                round(price, price_precision),
            )
            candidate_id = "SCOUT_" + hashlib.sha256("|".join(map(str, dedupe_key)).encode("utf-8")).hexdigest()[:20]
            if dedupe_key in seen:
                if not suppress_duplicate_quality:
                    quality.append(
                        CandidateQualityRow(
                            str(source_path),
                            row_number,
                            "DUPLICATE_CANDIDATE",
                            f"duplicate_of={seen[dedupe_key]}",
                            candidate_id,
                        )
                    )
                return
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
                    source_path=str(source_path),
                    source_row_hash=source_hash,
                    admission_status=(
                        "FILTER_REJECTED"
                        if event_type == "PEAK_LOSS_FILTER_REJECT"
                        else "ADMITTED"
                        if event_type == "PEAK_EMIT"
                        else "PRE_ADMISSION_REJECT"
                    ),
                    filter_rule_id=_text(merged.get("rule_id")) or None,
                    filter_decision=_text(merged.get("decision")) or None,
                    comparison_price_pass=comparison["price_pass"],
                    comparison_vol_pass=comparison["vol_pass"],
                    comparison_vwap_pass=comparison["vwap_pass"],
                    comparison_setup_variant=comparison["variant"],
                    comparison_previous_price=comparison["previous_price"],
                    comparison_previous_vol=comparison["previous_vol"],
                    comparison_previous_vwap=comparison["previous_vwap"],
                )
            )
        except BacktestContractError as exc:
            quality.append(CandidateQualityRow(str(source_path), row_number, "INVALID_CANDIDATE", str(exc)))

    paths = sorted(candidate_root.glob("*/events_context_*.csv"))
    for path in paths:
        day = path.parent.name
        if day < date_from or day > date_to:
            continue
        terminals, raw_events, _ = _load_raw_day(raw_archive_root / f"{day}.jsonl")
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
                append_candidate(merged, event_type=event_type, source_path=path, row_number=row_number)

    raw_filter_reject_count = 0
    for raw_path in sorted(raw_archive_root.glob("*.jsonl")):
        day = raw_path.stem
        if day < date_from or day > date_to:
            continue
        _, raw_events, filter_rejects = _load_raw_day(raw_path)
        for line_number, filter_reject in filter_rejects:
            raw_filter_reject_count += 1
            merged = dict(raw_events.get(_raw_key(filter_reject), {}))
            merged.update(filter_reject)
            append_candidate(
                merged,
                event_type="PEAK_LOSS_FILTER_REJECT",
                source_path=raw_path,
                row_number=line_number,
                suppress_duplicate_quality=True,
            )

    candidates.sort(key=lambda item: (item.signal_ts_utc, item.candidate_id))
    if not paths and raw_filter_reject_count == 0:
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
