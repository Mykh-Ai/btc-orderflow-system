from __future__ import annotations

import argparse
import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

MOVE_THRESHOLD_USD = 1000.0
WATCH_LOOKBACK_MINUTES = 60
M2_DENSITY_WINDOWS = (15, 30, 60)
FORWARD_WINDOWS = (15, 30, 60)
TIGHT_STOP_USD = 100.0
SWEEP_STOP_USD = 250.0


@dataclass(frozen=True)
class FastMoneyPreImpulseRow:
    move_cluster_id: str
    proxy_kind: str
    candidate_ts: str
    day: str
    side: str
    candidate_family: str
    phase_label: str
    session_label: str
    entry_price: str
    move_signal_start: str
    move_signal_end: str
    minutes_from_move_start: str
    m2_6_count_15m: str
    m2_6_count_30m: str
    m2_6_count_60m: str
    m2_6_family_counts_60m: str
    m2_6_role_counts_60m: str
    nearest_m2_6_ts: str
    nearest_m2_6_family: str
    nearest_m2_6_role: str
    nearest_reject_ts: str
    nearest_reject_reason: str
    nearest_peak_ts: str
    peak_delay_min: str
    accepted_peak_count_near: str
    reject_count_near: str
    price_vs_vwap_side: str
    cum_delta_24h: str
    cum_delta_180m: str
    cum_delta_60m: str
    ret_15m: str
    ret_60m: str
    m2_6_context_alignment: str
    is_countertrend: str
    mfe_15m: str
    mfe_30m: str
    mfe_60m: str
    mae_15m: str
    mae_30m: str
    mae_60m: str
    time_to_500: str
    time_to_1000: str
    adverse_before_500: str
    adverse_before_1000: str
    stop_tight_survived: str
    stop_sweep_survived: str
    stop_vwap_reclaim_survived: str
    is_fast_money_trigger: str
    is_late_no_edge: str
    source_basis: str
    notes: str


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: list[FastMoneyPreImpulseRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FastMoneyPreImpulseRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _fmt_ts(value: datetime | None) -> str:
    return "" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")


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


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _day_range(start: datetime, end: datetime) -> list[str]:
    days: list[str] = []
    current = datetime(start.year, start.month, start.day)
    final = datetime(end.year, end.month, end.day)
    while current <= final:
        days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def _scope_from_move_first(path: Path) -> str:
    stem = path.stem
    prefix = "move_first_windows_"
    if stem.startswith(prefix):
        return stem[len(prefix) :]
    return "unknown_scope"


def _latest_move_first_path(output_root: Path) -> Path:
    paths = sorted(output_root.glob("move_first_windows_*_to_*.csv"))
    if not paths:
        raise RuntimeError(f"no move_first_windows CSV found under {output_root}")
    return paths[-1]


def _load_day_rows(root: Path, prefix: str, start: datetime, end: datetime) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day in _day_range(start, end):
        rows.extend(_read_csv_rows(root / f"{prefix}_{day}.csv"))
    return rows


def _row_ts(row: dict[str, str]) -> datetime | None:
    ts = row.get("ts", "") or row.get("accepted_ts", "")
    if not ts:
        return None
    return _parse_ts(ts)


def _row_side(row: dict[str, str]) -> str:
    return row.get("direction", "") or row.get("kind", "") or row.get("side", "")


def _in_side_window(row: dict[str, str], side: str, start: datetime, end: datetime) -> bool:
    ts = _row_ts(row)
    return ts is not None and _row_side(row) == side and start <= ts <= end


def _nearest(rows: list[dict[str, str]], side: str, center: datetime, start: datetime, end: datetime) -> dict[str, str]:
    scoped = [row for row in rows if _in_side_window(row, side, start, end)]
    if not scoped:
        return {}
    return min(scoped, key=lambda row: abs((_row_ts(row) - center).total_seconds()))  # type: ignore[operator]


def _count_side_rows(rows: list[dict[str, str]], side: str, start: datetime, end: datetime) -> int:
    return sum(1 for row in rows if _in_side_window(row, side, start, end))


def _counter(rows: list[dict[str, str]], field: str) -> str:
    counts = Counter(row.get(field, "") for row in rows if row.get(field, ""))
    return ";".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def _session_label(ts: datetime) -> str:
    hour = ts.hour
    minute = ts.minute
    minutes = hour * 60 + minute
    if minutes < 8 * 60:
        return "asia_utc"
    if minutes < 12 * 60:
        return "europe_utc"
    if minutes < 13 * 60 + 30:
        return "us_premarket_utc"
    if minutes < 16 * 60:
        return "us_open_window_utc"
    if minutes < 21 * 60:
        return "us_session_utc"
    return "late_us_asia_transition_utc"


def _directional_value(side: str, long_value: str | None, short_value: str | None) -> float | None:
    return _float(short_value) if side == "short" else _float(long_value)


def _mfe_mae_from_outcome(row: dict[str, str], side: str, minutes: int, kind: str) -> float | None:
    if kind == "mfe":
        if side == "short":
            return _float(row.get(f"downside_max_{minutes}m"))
        return _float(row.get(f"upside_max_{minutes}m"))
    if side == "short":
        return _float(row.get(f"upside_max_{minutes}m"))
    return _float(row.get(f"downside_max_{minutes}m"))


def _entry_price(row: dict[str, str]) -> float | None:
    return _float(row.get("close"))


def _future_rows(minute_dataset_root: Path, start: datetime, minutes: int) -> list[dict[str, str]]:
    end = start + timedelta(minutes=minutes)
    rows: list[dict[str, str]] = []
    for day in _day_range(start, end):
        rows.extend(_read_csv_rows(minute_dataset_root / f"minute_events_outcomes_{day}.csv"))
    return [row for row in rows if start <= _parse_ts(row["ts"]) <= end]


def _target_stats(
    minute_dataset_root: Path,
    candidate_ts: datetime,
    side: str,
    entry: float | None,
    target: float,
    max_minutes: int = 60,
) -> tuple[float | None, float | None]:
    if entry is None:
        return None, None
    adverse = 0.0
    for row in _future_rows(minute_dataset_root, candidate_ts, max_minutes):
        high = _float(row.get("high"))
        low = _float(row.get("low"))
        if high is None or low is None:
            continue
        ts = _parse_ts(row["ts"])
        if side == "short":
            adverse = max(adverse, high - entry)
            if low <= entry - target:
                return (ts - candidate_ts).total_seconds() / 60.0, adverse
        else:
            adverse = max(adverse, entry - low)
            if high >= entry + target:
                return (ts - candidate_ts).total_seconds() / 60.0, adverse
    return None, adverse


def _vwap_reclaim_survived(minute_dataset_root: Path, candidate_ts: datetime, side: str) -> bool:
    rows = _future_rows(minute_dataset_root, candidate_ts, 60)
    for row in rows:
        high = _float(row.get("high"))
        low = _float(row.get("low"))
        close = _float(row.get("close"))
        vwap = _float(row.get("vwap"))
        if high is None or low is None or close is None or vwap is None:
            continue
        # Stop checking once the $1000 target is hit.
        entry = _entry_price(rows[0])
        if entry is not None:
            if side == "short" and low <= entry - MOVE_THRESHOLD_USD:
                return True
            if side == "long" and high >= entry + MOVE_THRESHOLD_USD:
                return True
        if side == "short" and close > vwap:
            return False
        if side == "long" and close < vwap:
            return False
    return True


def _context_alignment(side: str, row: dict[str, str]) -> str:
    signs: list[int] = []
    for field in ("cum_delta_24h", "cum_delta_180m", "cum_delta_60m"):
        value = _float(row.get(field))
        if value is None:
            continue
        signs.append(1 if value > 0 else -1 if value < 0 else 0)
    if not signs:
        return "unknown"
    side_sign = 1 if side == "long" else -1
    aligned = sum(1 for sign in signs if sign == side_sign)
    opposed = sum(1 for sign in signs if sign == -side_sign)
    if aligned == len(signs):
        return "aligned"
    if opposed == len(signs):
        return "opposed"
    if aligned > opposed:
        return "aligned_majority"
    if opposed > aligned:
        return "opposed_majority"
    return "mixed"


def _family(side: str, proxy_kind: str, m2_context: dict[str, str], nearest_reject: dict[str, str]) -> tuple[str, str]:
    alignment = _context_alignment(side, m2_context)
    role = m2_context.get("chain_role_hypothesis", "")
    if alignment in {"opposed", "opposed_majority"}:
        return "FAST_MONEY_COUNTERTREND_IMPULSE", "countertrend_impulse"
    if side == "long":
        if nearest_reject:
            return "FAST_MONEY_LONG_FORERUNNER", "reversal_forerunner"
        return "FAST_MONEY_LONG_PRE_IMPULSE", "acceleration_trigger" if proxy_kind == "best_proxy" else "early_watch"
    if side == "short":
        if role and "late" in role:
            return "FAST_MONEY_SHORT_LATE_RISK", "late_after_impulse"
        return "FAST_MONEY_SHORT_PRE_IMPULSE", "acceleration_trigger" if proxy_kind == "best_proxy" else "early_watch"
    return "FAST_MONEY_UNKNOWN", "unknown"


def _find_outcome_row(minute_dataset_root: Path, ts: datetime) -> dict[str, str]:
    rows = _read_csv_rows(minute_dataset_root / f"minute_events_outcomes_{ts.strftime('%Y-%m-%d')}.csv")
    ts_text = ts.strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        if row.get("ts") == ts_text:
            return row
    return {}


def _find_mechanics_row(minute_dataset_root: Path, ts: datetime) -> dict[str, str]:
    rows = _read_csv_rows(minute_dataset_root / f"minute_events_mechanics_{ts.strftime('%Y-%m-%d')}.csv")
    ts_text = ts.strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        if row.get("ts") == ts_text:
            return row
    return {}


def _load_review_rows(review_root: Path, prefix: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for day_dir in sorted(review_root.iterdir()):
        if not day_dir.is_dir():
            continue
        day = day_dir.name
        rows.extend(_read_csv_rows(day_dir / f"{prefix}_{day}.csv"))
    return rows


def _build_row(
    window: dict[str, str],
    proxy_kind: str,
    review_root: Path,
    minute_dataset_root: Path,
    m2_rows: list[dict[str, str]],
    reject_rows: list[dict[str, str]],
    accepted_rows: list[dict[str, str]],
) -> FastMoneyPreImpulseRow:
    side = window.get("direction", "")
    ts_text = window[f"{proxy_kind}_ts"]
    candidate_ts = _parse_ts(ts_text)
    move_start = _parse_ts(window["move_signal_start"])
    move_end = _parse_ts(window["move_signal_end"])
    outcome = _find_outcome_row(minute_dataset_root, candidate_ts)
    mechanics = _find_mechanics_row(minute_dataset_root, candidate_ts)
    entry = _entry_price(outcome)

    density: dict[int, list[dict[str, str]]] = {}
    for minutes in M2_DENSITY_WINDOWS:
        start = candidate_ts - timedelta(minutes=minutes)
        density[minutes] = [row for row in m2_rows if _in_side_window(row, side, start, candidate_ts)]
    detector_start = _parse_ts(window["detector_window_start"])
    detector_end = _parse_ts(window["detector_window_end"])
    nearest_m2 = _nearest(m2_rows, side, candidate_ts, candidate_ts - timedelta(minutes=WATCH_LOOKBACK_MINUTES), candidate_ts)
    nearest_reject = _nearest(reject_rows, side, candidate_ts, detector_start, detector_end)
    nearest_peak = _nearest(accepted_rows, side, candidate_ts, candidate_ts, detector_end)
    peak_ts = _row_ts(nearest_peak) if nearest_peak else None
    peak_delay = (peak_ts - candidate_ts).total_seconds() / 60.0 if peak_ts else None
    m2_context = nearest_m2 or mechanics
    family, phase = _family(side, proxy_kind, m2_context, nearest_reject)
    alignment = _context_alignment(side, m2_context)
    is_countertrend = alignment in {"opposed", "opposed_majority"}

    mfe = {minutes: _mfe_mae_from_outcome(outcome, side, minutes, "mfe") for minutes in FORWARD_WINDOWS}
    mae = {minutes: _mfe_mae_from_outcome(outcome, side, minutes, "mae") for minutes in FORWARD_WINDOWS}
    time500, adverse500 = _target_stats(minute_dataset_root, candidate_ts, side, entry, 500.0)
    time1000, adverse1000 = _target_stats(minute_dataset_root, candidate_ts, side, entry, MOVE_THRESHOLD_USD)
    adverse_for_stop = adverse1000 if adverse1000 is not None else (mae.get(60) or 0.0)
    stop_tight = adverse_for_stop <= TIGHT_STOP_USD
    stop_sweep = adverse_for_stop <= SWEEP_STOP_USD
    stop_vwap = _vwap_reclaim_survived(minute_dataset_root, candidate_ts, side)
    is_trigger = bool(time1000 is not None and time1000 <= 30 and adverse_for_stop <= SWEEP_STOP_USD)
    is_late = candidate_ts > move_start + timedelta(minutes=45) and proxy_kind == "best_proxy"

    notes = []
    if nearest_reject:
        notes.append(f"reject_support={nearest_reject.get('reject_reason', '')}")
    if nearest_peak:
        notes.append("accepted_peak_after_candidate")
    if is_countertrend:
        notes.append("countertrend_by_delta_context")

    return FastMoneyPreImpulseRow(
        move_cluster_id=window["move_cluster_id"],
        proxy_kind=proxy_kind,
        candidate_ts=ts_text,
        day=window.get("day", ts_text[:10]),
        side=side,
        candidate_family=family,
        phase_label=phase,
        session_label=_session_label(candidate_ts),
        entry_price=_fmt_float(entry),
        move_signal_start=window["move_signal_start"],
        move_signal_end=window["move_signal_end"],
        minutes_from_move_start=_fmt_float((candidate_ts - move_start).total_seconds() / 60.0),
        m2_6_count_15m=str(len(density[15])),
        m2_6_count_30m=str(len(density[30])),
        m2_6_count_60m=str(len(density[60])),
        m2_6_family_counts_60m=_counter(density[60], "family_hint"),
        m2_6_role_counts_60m=_counter(density[60], "chain_role_hypothesis"),
        nearest_m2_6_ts=_fmt_ts(_row_ts(nearest_m2)) if nearest_m2 else "",
        nearest_m2_6_family=nearest_m2.get("family_hint", ""),
        nearest_m2_6_role=nearest_m2.get("chain_role_hypothesis", ""),
        nearest_reject_ts=_fmt_ts(_row_ts(nearest_reject)) if nearest_reject else "",
        nearest_reject_reason=nearest_reject.get("reject_reason", ""),
        nearest_peak_ts=_fmt_ts(peak_ts),
        peak_delay_min=_fmt_float(peak_delay),
        accepted_peak_count_near=window.get("accepted_peak_count_near", ""),
        reject_count_near=window.get("reject_count_near", ""),
        price_vs_vwap_side=m2_context.get("price_vs_vwap_side", mechanics.get("price_vs_vwap_side", "")),
        cum_delta_24h=m2_context.get("cum_delta_24h", ""),
        cum_delta_180m=m2_context.get("cum_delta_180m", ""),
        cum_delta_60m=m2_context.get("cum_delta_60m", ""),
        ret_15m=m2_context.get("ret_15m", ""),
        ret_60m=m2_context.get("ret_60m", ""),
        m2_6_context_alignment=alignment,
        is_countertrend=_bool(is_countertrend),
        mfe_15m=_fmt_float(mfe[15]),
        mfe_30m=_fmt_float(mfe[30]),
        mfe_60m=_fmt_float(mfe[60]),
        mae_15m=_fmt_float(mae[15]),
        mae_30m=_fmt_float(mae[30]),
        mae_60m=_fmt_float(mae[60]),
        time_to_500=_fmt_float(time500),
        time_to_1000=_fmt_float(time1000),
        adverse_before_500=_fmt_float(adverse500),
        adverse_before_1000=_fmt_float(adverse1000),
        stop_tight_survived=_bool(stop_tight),
        stop_sweep_survived=_bool(stop_sweep),
        stop_vwap_reclaim_survived=_bool(stop_vwap),
        is_fast_money_trigger=_bool(is_trigger),
        is_late_no_edge=_bool(is_late),
        source_basis="move_first_window_proxy",
        notes="; ".join(notes),
    )


def _write_summary(path: Path, rows: list[FastMoneyPreImpulseRow], scope_id: str) -> None:
    by_family = Counter(row.candidate_family for row in rows)
    by_phase = Counter(row.phase_label for row in rows)
    by_proxy = Counter(row.proxy_kind for row in rows)
    trigger_rows = [row for row in rows if row.is_fast_money_trigger == "true"]
    lines = [
        "# Fast Money Pre-Impulse Table Summary",
        "",
        f"scope: `{scope_id}`",
        f"rows: `{len(rows)}`",
        f"fast_money_trigger_rows: `{len(trigger_rows)}`",
        "",
        "## Proxy Kinds",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_proxy.items()))
    lines.extend(["", "## Candidate Families", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_family.items()))
    lines.extend(["", "## Phase Labels", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in sorted(by_phase.items()))
    lines.extend(["", "## Use", ""])
    lines.append("This table is an event-study surface for pre-impulse / fast-money research, not a live signal spec.")
    lines.append("Use it to compare early watch vs lower-adverse trigger timing, stop survival, and PEAK delay.")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_fast_money_pre_impulse_table(
    review_root: Path,
    minute_dataset_root: Path,
    output_root: Path,
    move_first_path: Path | None = None,
) -> tuple[Path, Path, int]:
    move_first_path = move_first_path or _latest_move_first_path(output_root)
    scope_id = _scope_from_move_first(move_first_path)
    windows = _read_csv_rows(move_first_path)
    if not windows:
        raise RuntimeError(f"no move-first rows found in {move_first_path}")
    m2_rows: list[dict[str, str]] = []
    for path in sorted((minute_dataset_root / "m2_6").glob("minute_event_chain_candidates_*.csv")):
        m2_rows.extend(_read_csv_rows(path))
    reject_rows = _load_review_rows(review_root, "reject_event_context")
    accepted_rows = _load_review_rows(review_root, "accepted_event_context")

    rows: list[FastMoneyPreImpulseRow] = []
    for window in windows:
        for proxy_kind in ("earliest_proxy", "best_proxy"):
            if window.get(f"{proxy_kind}_ts"):
                rows.append(_build_row(window, proxy_kind, review_root, minute_dataset_root, m2_rows, reject_rows, accepted_rows))

    rows = sorted(rows, key=lambda row: (row.day, row.move_cluster_id, row.proxy_kind))
    output_root.mkdir(parents=True, exist_ok=True)
    out_csv = output_root / f"fast_money_pre_impulse_table_{scope_id}.csv"
    out_md = output_root / f"fast_money_pre_impulse_table_{scope_id}_summary.md"
    _write_csv(out_csv, rows)
    _write_summary(out_md, rows, scope_id)
    return out_csv, out_md, len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build fast-money pre-impulse event-study table from move-first windows")
    parser.add_argument("--review-root", required=True)
    parser.add_argument("--minute-dataset-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--move-first", help="Explicit move_first_windows_<scope>.csv path. Defaults to latest under output-root.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    out_csv, out_md, row_count = build_fast_money_pre_impulse_table(
        review_root=Path(args.review_root),
        minute_dataset_root=Path(args.minute_dataset_root),
        output_root=Path(args.output_root),
        move_first_path=Path(args.move_first) if args.move_first else None,
    )
    print("DeltaScout Fast Money Pre-Impulse Table Build")
    print(f"fast_money_pre_impulse_table={out_csv}")
    print(f"fast_money_pre_impulse_summary={out_md}")
    print(f"row_count={row_count}")


if __name__ == "__main__":
    main()
