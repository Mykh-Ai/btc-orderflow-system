from __future__ import annotations

import bisect
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from .candidate_compiler import local_event_to_utc
from .contracts import BacktestContractError, Candidate, FeedBar


TRUSTED_OI_CLASSES = {"REAL_ENRICHED"}


def _load_peak_history(raw_archive_root: Path, date_from: str, date_to: str) -> list[tuple[object, str, float]]:
    start = (local_event_to_utc(f"{date_from} 12:00:00") - timedelta(hours=36)).date().isoformat()
    rows: list[tuple[object, str, float]] = []
    for path in sorted(raw_archive_root.glob("*.jsonl")):
        if path.stem < start or path.stem > date_to:
            continue
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BacktestContractError(f"invalid raw archive JSON at {path}:{line_number}") from exc
                if str(row.get("event") or "") not in {"DELTA_MAX", "DELTA_MIN"}:
                    continue
                side = {"long": "LONG", "short": "SHORT"}.get(str(row.get("kind") or "").lower())
                try:
                    delta = abs(float(row.get("delta")))
                except (TypeError, ValueError):
                    continue
                if side:
                    rows.append((local_event_to_utc(row.get("ts")), side, delta))
    rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return rows


def _window(bars: list[FeedBar], timestamps: list, cutoff, minutes: int) -> list[FeedBar]:
    end = bisect.bisect_right(timestamps, cutoff)
    start = bisect.bisect_left(timestamps, cutoff - timedelta(minutes=minutes - 1), 0, end)
    return bars[start:end]


def enrich_shadow_flags(
    candidates: list[Candidate],
    bars: list[FeedBar],
    *,
    raw_archive_root: Path,
    date_from: str,
    date_to: str,
) -> list[Candidate]:
    peak_history = _load_peak_history(raw_archive_root, date_from, date_to)
    peak_times = [item[0] for item in peak_history]
    feed_times = [bar.ts for bar in bars]
    enriched: list[Candidate] = []
    for candidate in candidates:
        peak_start = bisect.bisect_left(peak_times, candidate.signal_ts_utc - timedelta(hours=24))
        peak_end = bisect.bisect_right(peak_times, candidate.signal_ts_utc)
        values = [delta for ts, side, delta in peak_history[peak_start:peak_end] if side == candidate.side]
        percentile = (
            sum(value <= abs(candidate.delta) for value in values) / len(values) * 100.0
            if values
            else None
        )
        weak = percentile <= 50.0 if percentile is not None else None

        bars_60 = _window(bars, feed_times, candidate.signal_ts_utc, 60)
        oi_values = [bar.optional.get("OpenInterest") for bar in bars_60 if bar.optional.get("OpenInterest") is not None]
        oi_trusted = bool(bars_60) and all(
            not bar.is_synthetic and bar.feed_quality_class in TRUSTED_OI_CLASSES for bar in bars_60
        )
        oi_change = oi_values[-1] - oi_values[0] if oi_trusted and len(oi_values) >= 2 else None

        bars_240 = _window(bars, feed_times, candidate.signal_ts_utc, 240)
        directional_delta_pct = None
        if bars_240 and not any(bar.is_synthetic for bar in bars_240):
            buy = sum(bar.buy_qty for bar in bars_240)
            sell = sum(bar.sell_qty for bar in bars_240)
            total = buy + sell
            if total > 0:
                directional_delta_pct = (buy - sell) / total * (1 if candidate.side == "LONG" else -1)
        oi_rule = (
            oi_change < 0 and directional_delta_pct < 0.06
            if oi_change is not None and directional_delta_pct is not None
            else None
        )
        known = [value for value in (weak, oi_rule) if value is not None]
        union = any(known) if known else None
        enriched.append(
            replace(
                candidate,
                shadow_flags={
                    "weak_peak_le_50": weak,
                    "oi_down_60_and_directional_delta_pct_240_lt_0_06": oi_rule,
                    "loss_avoidance_conservative_union": union,
                },
            )
        )
    return enriched
