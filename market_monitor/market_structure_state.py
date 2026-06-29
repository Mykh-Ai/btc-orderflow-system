from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd


STATE_VERSION = "SHI_RESET_37E_ONLINE_MARKET_STRUCTURE_STATE_MEMORY_V0"

MARKET_STRUCTURE_LEVELS_CSV = "market_structure_levels.csv"
MARKET_STRUCTURE_EVENTS_CSV = "market_structure_events.csv"
MARKET_STRUCTURE_STATE_TIMELINE_CSV = "market_structure_state_timeline.csv"
MARKET_STRUCTURE_SUMMARY_MD = "market_structure_state_summary.md"
MARKET_STRUCTURE_MANIFEST_JSON = "market_structure_state_manifest.json"

MARKET_STRUCTURE_LEVEL_COLUMNS = [
    "band_id",
    "role",
    "liquidity_sides",
    "price_lower",
    "price_upper",
    "price_mid",
    "band_width_pct",
    "strength_score",
    "strength_bucket",
    "status",
    "first_seen_at",
    "last_seen_at",
    "last_touch_at",
    "last_cross_at",
    "active_days",
    "touch_count",
    "cross_count",
    "source_zone_ids",
    "source_timeframes",
    "source_zone_types",
    "evidence_summary",
]

MARKET_STRUCTURE_EVENT_COLUMNS = [
    "event_id",
    "event_timestamp",
    "event_type",
    "band_id",
    "role",
    "price_lower",
    "price_upper",
    "event_price",
    "strength_score",
    "evidence_summary",
    "source",
]

MARKET_STRUCTURE_STATE_COLUMNS = [
    "state_id",
    "start_timestamp",
    "end_timestamp",
    "market_state",
    "confidence_tier",
    "active_support_band_id",
    "active_support_price_lower",
    "active_support_price_upper",
    "active_resistance_band_id",
    "active_resistance_price_lower",
    "active_resistance_price_upper",
    "next_zone_in_front_of_price",
    "candidate_bias",
    "candidate_strength",
    "price_open",
    "price_close",
    "price_high",
    "price_low",
    "price_change_pct",
    "range_pct",
    "close_position",
    "delta_pct",
    "open_interest_change",
    "oi_context",
    "evidence_summary",
]


class MarketStructureStateError(RuntimeError):
    """Raised when market-structure state memory cannot be built."""


@dataclass(frozen=True)
class MarketStructureStateResult:
    output_dir: Path
    levels_path: Path
    events_path: Path
    state_timeline_path: Path
    summary_path: Path
    manifest_path: Path
    level_count: int
    event_count: int
    state_count: int


def run_market_structure_state(
    *,
    input_root: str | Path,
    feed_dir: str | Path,
    output_dir: str | Path,
    start: str | date,
    end: str | date,
    as_of: str | datetime | None = None,
    merge_gap_bps: float = 50.0,
) -> MarketStructureStateResult:
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date > end_date:
        raise MarketStructureStateError("start must be <= end")
    as_of_ts = _parse_as_of(as_of)
    if as_of_ts is not None and as_of_ts.date() < start_date:
        raise MarketStructureStateError("as-of timestamp must be on or after start")

    root = Path(input_root)
    feeds = Path(feed_dir)
    out_dir = Path(output_dir)
    if not root.exists() or not root.is_dir():
        raise MarketStructureStateError(f"input root not found: {root}")
    if not feeds.exists() or not feeds.is_dir():
        raise MarketStructureStateError(f"feed directory not found: {feeds}")
    out_dir.mkdir(parents=True, exist_ok=True)

    online_completed_end = _completed_daily_end(end_date, as_of_ts)
    loaded = _load_daily_artifacts(root, start_date, online_completed_end)
    feed = _load_feed_window(feeds, start_date, end_date, as_of_ts)
    current_price = _last_close(feed)

    levels = _build_level_bands(
        loaded["liquidity_zone_registry.csv"],
        current_price=current_price,
        merge_gap_bps=merge_gap_bps,
    )
    events = _build_structure_events(
        post_sweep=loaded["post_sweep_observation.csv"],
        levels=levels,
    )
    states = _build_state_timeline(
        feed=feed,
        levels=levels,
        start_date=start_date,
        end_date=end_date,
        as_of_ts=as_of_ts,
    )

    levels_path = out_dir / MARKET_STRUCTURE_LEVELS_CSV
    events_path = out_dir / MARKET_STRUCTURE_EVENTS_CSV
    states_path = out_dir / MARKET_STRUCTURE_STATE_TIMELINE_CSV
    summary_path = out_dir / MARKET_STRUCTURE_SUMMARY_MD
    manifest_path = out_dir / MARKET_STRUCTURE_MANIFEST_JSON

    levels.reindex(columns=MARKET_STRUCTURE_LEVEL_COLUMNS).to_csv(levels_path, index=False)
    events.reindex(columns=MARKET_STRUCTURE_EVENT_COLUMNS).to_csv(events_path, index=False)
    states.reindex(columns=MARKET_STRUCTURE_STATE_COLUMNS).to_csv(states_path, index=False)
    summary_path.write_text(
        _render_summary(
            levels=levels,
            events=events,
            states=states,
            input_root=root,
            feed_dir=feeds,
            start_date=start_date,
            end_date=end_date,
            as_of_ts=as_of_ts,
            completed_daily_end=online_completed_end,
        ),
        encoding="utf-8",
    )
    manifest = {
        "state_version": STATE_VERSION,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "as_of": _format_ts(as_of_ts) if as_of_ts is not None else "",
        "completed_daily_artifacts_through": online_completed_end.isoformat()
        if online_completed_end is not None
        else "",
        "input_root": str(root),
        "feed_dir": str(feeds),
        "outputs": {
            "market_structure_levels_csv": str(levels_path),
            "market_structure_events_csv": str(events_path),
            "market_structure_state_timeline_csv": str(states_path),
            "summary_md": str(summary_path),
            "manifest_json": str(manifest_path),
        },
        "level_count": int(len(levels)),
        "event_count": int(len(events)),
        "state_count": int(len(states)),
        "scope": "research_monitor_state_memory_only_not_trading_advice",
        "repo_commit": _repo_commit(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return MarketStructureStateResult(
        output_dir=out_dir,
        levels_path=levels_path,
        events_path=events_path,
        state_timeline_path=states_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        level_count=int(len(levels)),
        event_count=int(len(events)),
        state_count=int(len(states)),
    )


def _load_daily_artifacts(root: Path, start_date: date, end_date: date | None) -> dict[str, pd.DataFrame]:
    names = [
        "liquidity_zone_registry.csv",
        "post_sweep_observation.csv",
    ]
    if end_date is None or end_date < start_date:
        return {name: pd.DataFrame() for name in names}

    frames: dict[str, list[pd.DataFrame]] = {name: [] for name in names}
    for day in _date_range(start_date, end_date):
        day_dir = root / day.isoformat()
        if not day_dir.exists():
            raise MarketStructureStateError(f"missing daily output directory: {day_dir}")
        for name in names:
            path = day_dir / name
            if path.exists():
                try:
                    frame = pd.read_csv(path)
                except pd.errors.EmptyDataError:
                    frame = pd.DataFrame()
            else:
                frame = pd.DataFrame()
            frame["_source_day"] = day.isoformat()
            frames[name].append(frame)
    return {
        name: pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()
        for name, parts in frames.items()
    }


def _load_feed_window(
    feed_dir: Path,
    start_date: date,
    end_date: date,
    as_of_ts: datetime | None,
) -> pd.DataFrame:
    frames = []
    for day in _date_range(start_date, end_date):
        path = feed_dir / f"{day.isoformat()}.csv"
        if not path.exists():
            raise MarketStructureStateError(f"missing feed file: {path}")
        frame = pd.read_csv(path)
        frame = _normalize_feed(frame)
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    feed = pd.concat(frames, ignore_index=True, sort=False)
    feed = feed.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    if as_of_ts is not None:
        feed = feed[feed["Timestamp"] <= pd.Timestamp(as_of_ts.replace(tzinfo=None))].copy()
    return feed


def _normalize_feed(frame: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "Open": "OpenPrice",
        "High": "HiPrice",
        "Low": "LowPrice",
        "Close": "ClosePrice",
        "Volume": "TotalQty",
    }
    frame = frame.rename(columns=rename).copy()
    required = [
        "Timestamp",
        "OpenPrice",
        "HiPrice",
        "LowPrice",
        "ClosePrice",
        "TotalQty",
        "BuyQty",
        "SellQty",
        "OpenInterest",
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise MarketStructureStateError(f"feed missing columns: {missing}")
    frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], utc=False)
    for column in required:
        if column != "Timestamp":
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def _build_level_bands(
    registry: pd.DataFrame,
    *,
    current_price: float | None,
    merge_gap_bps: float,
) -> pd.DataFrame:
    if registry.empty or current_price is None:
        return pd.DataFrame(columns=MARKET_STRUCTURE_LEVEL_COLUMNS)
    frame = registry.copy()
    for column in [
        "price_lower",
        "price_upper",
        "price_mid",
        "confidence_score",
        "touch_count",
        "cross_count",
        "active_days",
    ]:
        frame[column] = pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0.0)
    frame = frame[
        ~frame.get("status", "").astype(str).isin({"EXPIRED", "INVALIDATED", "MERGED"})
    ].copy()
    frame = frame[frame["price_upper"] > 0]
    frame["role"] = frame.apply(lambda row: _trader_role(row, current_price), axis=1)
    frame = frame[frame["role"].isin({"SUPPORT", "RESISTANCE", "CURRENT_ZONE"})].copy()
    if frame.empty:
        return pd.DataFrame(columns=MARKET_STRUCTURE_LEVEL_COLUMNS)

    rows = []
    band_index = 1
    for role in ["SUPPORT", "CURRENT_ZONE", "RESISTANCE"]:
        role_rows = frame[frame["role"] == role].copy()
        for side in ["SELL_SIDE", "BUY_SIDE"]:
            side_rows = role_rows[role_rows["side"].astype(str) == side].sort_values(
                ["price_lower", "price_upper", "zone_id"], kind="mergesort"
            )
            cluster: list[pd.Series] = []
            for _, row in side_rows.iterrows():
                if not cluster:
                    cluster = [row]
                    continue
                current_upper = max(float(item["price_upper"]) for item in cluster)
                gap = float(row["price_lower"]) - current_upper
                tolerance = max(50.0, ((current_upper + float(row["price_lower"])) / 2.0) * merge_gap_bps / 10000.0)
                if gap <= tolerance:
                    cluster.append(row)
                else:
                    rows.append(_band_row(f"band_{band_index:06d}", role, cluster))
                    band_index += 1
                    cluster = [row]
            if cluster:
                rows.append(_band_row(f"band_{band_index:06d}", role, cluster))
                band_index += 1
    result = pd.DataFrame(rows, columns=MARKET_STRUCTURE_LEVEL_COLUMNS)
    if result.empty:
        return result
    return result.sort_values(["price_mid", "role"], kind="mergesort").reset_index(drop=True)


def _band_row(band_id: str, role: str, cluster: list[pd.Series]) -> dict[str, object]:
    lower = min(float(row["price_lower"]) for row in cluster)
    upper = max(float(row["price_upper"]) for row in cluster)
    mid = (lower + upper) / 2.0
    confidence_score = max(float(row.get("confidence_score", 0) or 0) for row in cluster)
    active_days = max(int(float(row.get("active_days", 0) or 0)) for row in cluster)
    touch_count = sum(int(float(row.get("touch_count", 0) or 0)) for row in cluster)
    cross_count = sum(int(float(row.get("cross_count", 0) or 0)) for row in cluster)
    strength = min(100.0, confidence_score + min(active_days, 10) * 1.5 + min(touch_count, 8) * 2.0 + min(cross_count, 8) * 2.0)
    statuses = sorted({str(row.get("status", "") or "") for row in cluster if str(row.get("status", "") or "")})
    liquidity_sides = sorted({str(row.get("side", "") or "") for row in cluster if str(row.get("side", "") or "")})
    zone_ids = sorted({str(row.get("zone_id", "") or "") for row in cluster if str(row.get("zone_id", "") or "")})
    source_timeframes = sorted(
        {
            part
            for row in cluster
            for part in str(row.get("source_timeframes", "") or "").split("|")
            if part
        }
    )
    zone_types = sorted({str(row.get("zone_type", "") or "") for row in cluster if str(row.get("zone_type", "") or "")})
    return {
        "band_id": band_id,
        "role": role,
        "liquidity_sides": "|".join(liquidity_sides),
        "price_lower": round(lower, 6),
        "price_upper": round(upper, 6),
        "price_mid": round(mid, 6),
        "band_width_pct": round(((upper / lower) - 1.0) * 100.0, 6) if lower else 0.0,
        "strength_score": round(strength, 3),
        "strength_bucket": _strength_bucket(strength),
        "status": "|".join(statuses),
        "first_seen_at": min(str(row.get("first_seen_at", "") or "") for row in cluster),
        "last_seen_at": max(str(row.get("last_seen_at", "") or "") for row in cluster),
        "last_touch_at": max((str(row.get("last_touch_at", "") or "") for row in cluster), default=""),
        "last_cross_at": max((str(row.get("last_cross_at", "") or "") for row in cluster), default=""),
        "active_days": active_days,
        "touch_count": touch_count,
        "cross_count": cross_count,
        "source_zone_ids": "|".join(zone_ids),
        "source_timeframes": "|".join(source_timeframes),
        "source_zone_types": "|".join(zone_types),
        "evidence_summary": (
            f"sources={len(zone_ids)}; statuses={'|'.join(statuses)}; "
            f"timeframes={'|'.join(source_timeframes)}; touch_count={touch_count}; "
            f"cross_count={cross_count}; active_days={active_days}"
        ),
    }


def _build_structure_events(post_sweep: pd.DataFrame, levels: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if not post_sweep.empty:
        frame = post_sweep.copy()
        for column in [
            "zone_price_lower",
            "zone_price_upper",
            "zone_price_mid",
            "net_close_change_pct",
            "bars_above_zone",
            "bars_below_zone",
            "max_return_inside_zone",
            "max_excursion_beyond_zone",
        ]:
            frame[column] = pd.to_numeric(frame.get(column, 0), errors="coerce").fillna(0.0)
        for _, row in frame.iterrows():
            side = str(row.get("side", ""))
            net_change = float(row["net_close_change_pct"])
            bars_above = int(float(row["bars_above_zone"]))
            bars_below = int(float(row["bars_below_zone"]))
            event_type = ""
            if side == "SELL_SIDE" and net_change >= 0.5 and bars_above > bars_below:
                event_type = "FAILED_BREAKDOWN_RECLAIM"
            elif side == "BUY_SIDE" and net_change <= -0.5 and bars_below > bars_above:
                event_type = "FAILED_BREAKOUT_REJECTION"
            if not event_type:
                continue
            band = _nearest_band(levels, float(row["zone_price_mid"]))
            rows.append(
                {
                    "event_id": f"structure_event_{len(rows) + 1:06d}",
                    "event_timestamp": str(row.get("source_event_timestamp", "")),
                    "event_type": event_type,
                    "band_id": str(band.get("band_id", "")),
                    "role": str(band.get("role", "")),
                    "price_lower": float(row["zone_price_lower"]),
                    "price_upper": float(row["zone_price_upper"]),
                    "event_price": float(row["zone_price_mid"]),
                    "strength_score": float(band.get("strength_score", 0) or 0),
                    "evidence_summary": (
                        f"net_close_change_pct={net_change:.3f}; bars_above={bars_above}; "
                        f"bars_below={bars_below}; max_return_inside={float(row['max_return_inside_zone']):.3f}; "
                        f"max_excursion_beyond={float(row['max_excursion_beyond_zone']):.3f}"
                    ),
                    "source": "post_sweep_observation",
                }
            )
    return pd.DataFrame(rows, columns=MARKET_STRUCTURE_EVENT_COLUMNS)


def _build_state_timeline(
    *,
    feed: pd.DataFrame,
    levels: pd.DataFrame,
    start_date: date,
    end_date: date,
    as_of_ts: datetime | None,
) -> pd.DataFrame:
    if feed.empty:
        return pd.DataFrame(columns=MARKET_STRUCTURE_STATE_COLUMNS)
    rows = []
    previous_states: list[str] = []
    for day in _date_range(start_date, end_date):
        start_ts = datetime.combine(day, time.min)
        end_ts = datetime.combine(day, time(23, 59))
        if as_of_ts is not None and day == as_of_ts.date():
            end_ts = as_of_ts.replace(tzinfo=None)
        if as_of_ts is not None and start_ts > as_of_ts.replace(tzinfo=None):
            continue
        day_feed = feed[(feed["Timestamp"] >= pd.Timestamp(start_ts)) & (feed["Timestamp"] <= pd.Timestamp(end_ts))]
        if day_feed.empty:
            continue
        metrics = _window_metrics(day_feed)
        support = _nearest_band_for_price(levels, "SUPPORT", metrics["close"])
        resistance = _nearest_band_for_price(levels, "RESISTANCE", metrics["close"])
        market_state, confidence, bias, candidate_strength, evidence = _classify_state(
            metrics=metrics,
            support=support,
            resistance=resistance,
            previous_states=previous_states,
        )
        previous_states.append(market_state)
        rows.append(
            {
                "state_id": f"state_{len(rows) + 1:06d}",
                "start_timestamp": _format_ts(pd.Timestamp(start_ts)),
                "end_timestamp": _format_ts(pd.Timestamp(end_ts)),
                "market_state": market_state,
                "confidence_tier": confidence,
                "active_support_band_id": str(support.get("band_id", "")),
                "active_support_price_lower": support.get("price_lower", ""),
                "active_support_price_upper": support.get("price_upper", ""),
                "active_resistance_band_id": str(resistance.get("band_id", "")),
                "active_resistance_price_lower": resistance.get("price_lower", ""),
                "active_resistance_price_upper": resistance.get("price_upper", ""),
                "next_zone_in_front_of_price": _next_zone_text(resistance),
                "candidate_bias": bias,
                "candidate_strength": candidate_strength,
                "price_open": metrics["open"],
                "price_close": metrics["close"],
                "price_high": metrics["high"],
                "price_low": metrics["low"],
                "price_change_pct": metrics["price_change_pct"],
                "range_pct": metrics["range_pct"],
                "close_position": metrics["close_position"],
                "delta_pct": metrics["delta_pct"],
                "open_interest_change": metrics["open_interest_change"],
                "oi_context": _oi_context(metrics),
                "evidence_summary": evidence,
            }
        )
    return pd.DataFrame(rows, columns=MARKET_STRUCTURE_STATE_COLUMNS)


def _classify_state(
    *,
    metrics: dict[str, float],
    support: pd.Series,
    resistance: pd.Series,
    previous_states: list[str],
) -> tuple[str, str, str, str, str]:
    close = metrics["close"]
    high = metrics["high"]
    price_change = metrics["price_change_pct"]
    range_pct = metrics["range_pct"]
    delta_pct = metrics["delta_pct"]
    close_position = metrics.get("close_position", 0.5)
    support_strength = _series_float(support, "strength_score")
    resistance_strength = _series_float(resistance, "strength_score")
    resistance_lower = _series_float(resistance, "price_lower")
    resistance_upper = _series_float(resistance, "price_upper")
    support_upper = _series_float(support, "price_upper")
    support_context = "present" if support_strength > 0 and support_upper > 0 and close > support_upper else "absent"
    resistance_context = "present" if resistance_strength > 0 and resistance_lower > 0 else "absent"
    near_resistance = bool(resistance_lower and high >= resistance_lower * 0.995)
    strong_resistance = resistance_strength >= 65

    pressure = _market_pressure_dominance(
        metrics=metrics,
        support=support,
        resistance=resistance,
    )
    evidence = (
        f"price_change_pct={price_change:.3f}; range_pct={range_pct:.3f}; "
        f"close_position={close_position:.3f}; delta_pct={delta_pct:.3f}; "
        f"support_strength={support_strength:.1f}; resistance_strength={resistance_strength:.1f}; "
        f"seller_pressure_score={pressure['seller_pressure_score']:.1f}; "
        f"buyer_response_score={pressure['buyer_response_score']:.1f}; "
        f"overhead_supply_score={pressure['overhead_supply_score']:.1f}; "
        f"underlying_demand_score={pressure['underlying_demand_score']:.1f}; "
        f"dominant_side={pressure['dominant_side']}; range_quality={pressure['range_quality']}; "
        f"support_context={support_context}; resistance_context={resistance_context}"
    )

    next_round_level = math.ceil(float(metrics["open"]) / 10000.0) * 10000.0
    if (
        float(metrics["open"]) < next_round_level * 0.995
        and high >= next_round_level
        and close <= next_round_level * 0.995
        and close_position <= 0.45
    ):
        return (
            "FAILED_CONTINUATION_ABOVE_ROUND_LEVEL",
            "MEDIUM",
            "MIXED",
            "MEDIUM",
            evidence + f"; high crossed round_level={next_round_level:.0f} but did not hold",
        )

    previous_state = previous_states[-1] if previous_states else ""
    if (
        previous_state
        in {"UP_EXPANSION_INTO_MAJOR_RESISTANCE", "FAILED_CONTINUATION_ABOVE_ROUND_LEVEL"}
        and strong_resistance
        and close >= resistance_lower * 0.98
    ):
        return (
            "PULLBACK_RETEST_INSIDE_MAJOR_RESISTANCE",
            "MEDIUM",
            "MIXED",
            "MEDIUM",
            evidence + "; post-expansion price remains inside/near major resistance band",
        )

    if pressure["dominant_side"] == "SELLER" and price_change <= -0.45 and range_pct >= 1.2:
        state = "MARKDOWN_ABOVE_SUPPORT" if support_context == "present" else "EXPANSION_DOWN"
        confidence = "HIGH" if pressure["seller_pressure_score"] >= 70 else "MEDIUM"
        strength = "HIGH" if pressure["seller_pressure_score"] >= 70 else "MEDIUM"
        return (
            state,
            confidence,
            "DOWN",
            strength,
            evidence + "; downside expansion classified before support/range fallback",
        )

    if strong_resistance and near_resistance and pressure["dominant_side"] == "SELLER" and close_position <= 0.45:
        return (
            "FAILED_BREAKOUT_SELLER_RECLAIM",
            "MEDIUM",
            "DOWN",
            "MEDIUM",
            evidence + "; seller pressure reclaimed below/inside overhead resistance context",
        )

    if price_change >= 1.0 and delta_pct > 0 and near_resistance and strong_resistance:
        return (
            "UP_EXPANSION_INTO_MAJOR_RESISTANCE",
            "HIGH",
            "UP",
            "HIGH",
            evidence + "; upside expansion reached next strong resistance band",
        )

    if pressure["dominant_side"] == "BUYER" and price_change >= 1.0 and range_pct >= 1.5:
        return (
            "EXPANSION_UP",
            "MEDIUM",
            "UP",
            "MEDIUM",
            evidence + "; upside expansion classified before range fallback",
        )

    if pressure["range_quality"] == "BALANCED" and support_context == "present" and resistance_context == "present":
        return (
            "BALANCED_RANGE_BETWEEN_LEVELS",
            "MEDIUM",
            "MIXED",
            "LOW",
            evidence + "; balance requires low range, mixed pressure, and middle close",
        )

    if pressure["dominant_side"] == "SELLER" and support_context == "present":
        return (
            "PRESSURE_INTO_SUPPORT",
            "MEDIUM",
            "DOWN",
            "MEDIUM",
            evidence + f"; seller pressure persists above support_upper={support_upper:.3f}",
        )

    if pressure["dominant_side"] == "BUYER" and support_context == "present" and range_pct <= 2.5:
        return (
            "COMPRESSION_ABOVE_SUPPORT",
            "MEDIUM",
            "UP",
            "MEDIUM",
            evidence + f"; buyer response holds above support_upper={support_upper:.3f}",
        )

    if resistance_context == "present" and close < resistance_upper and pressure["range_quality"] != "BIASED":
        return (
            "CONTEXT_BELOW_RESISTANCE",
            "LOW",
            "MIXED",
            "LOW",
            evidence + f"; price remains below resistance_upper={resistance_upper:.3f} without proven balance",
        )

    return (
        "MARKET_STRUCTURE_CONTEXT",
        "LOW",
        "NONE",
        "LOW",
        evidence + "; no dominant state transition",
    )


def _market_pressure_dominance(
    *,
    metrics: dict[str, float],
    support: pd.Series,
    resistance: pd.Series,
) -> dict[str, float | str]:
    price_change = metrics["price_change_pct"]
    range_pct = metrics["range_pct"]
    delta_pct = metrics["delta_pct"]
    close_position = metrics.get("close_position", 0.5)
    close = metrics["close"]
    support_strength = _series_float(support, "strength_score")
    support_upper = _series_float(support, "price_upper")
    resistance_strength = _series_float(resistance, "strength_score")
    resistance_lower = _series_float(resistance, "price_lower")

    seller_pressure = _clamp(
        max(-price_change, 0.0) * 28.0
        + max(-delta_pct, 0.0) * 1.8
        + max(0.45 - close_position, 0.0) * 70.0
        + max(range_pct - 1.0, 0.0) * 7.0,
        0.0,
        100.0,
    )
    buyer_response = _clamp(
        max(price_change, 0.0) * 28.0
        + max(delta_pct, 0.0) * 1.8
        + max(close_position - 0.55, 0.0) * 70.0
        + max(range_pct - 1.0, 0.0) * 4.0,
        0.0,
        100.0,
    )
    overhead_supply = 0.0
    if resistance_lower > 0:
        distance_to_resistance_pct = max((resistance_lower - close) / close * 100.0, 0.0) if close else 0.0
        overhead_supply = _clamp(resistance_strength - min(distance_to_resistance_pct * 15.0, 40.0), 0.0, 100.0)
    underlying_demand = 0.0
    if support_upper > 0:
        distance_to_support_pct = max((close - support_upper) / close * 100.0, 0.0) if close else 0.0
        underlying_demand = _clamp(support_strength - min(distance_to_support_pct * 12.0, 45.0), 0.0, 100.0)

    if seller_pressure >= buyer_response + 12.0 and seller_pressure >= 35.0:
        dominant_side = "SELLER"
    elif buyer_response >= seller_pressure + 12.0 and buyer_response >= 35.0:
        dominant_side = "BUYER"
    else:
        dominant_side = "MIXED"

    if range_pct <= 1.6 and abs(price_change) <= 0.35 and abs(delta_pct) <= 6.0 and 0.35 <= close_position <= 0.65:
        range_quality = "BALANCED"
    elif dominant_side == "MIXED" and range_pct <= 2.5 and 0.25 <= close_position <= 0.75:
        range_quality = "MIXED"
    else:
        range_quality = "BIASED"

    return {
        "seller_pressure_score": round(float(seller_pressure), 3),
        "buyer_response_score": round(float(buyer_response), 3),
        "overhead_supply_score": round(float(overhead_supply), 3),
        "underlying_demand_score": round(float(underlying_demand), 3),
        "dominant_side": dominant_side,
        "range_quality": range_quality,
    }

def _window_metrics(frame: pd.DataFrame) -> dict[str, float]:
    sorted_frame = frame.sort_values("Timestamp", kind="mergesort")
    first = sorted_frame.iloc[0]
    last = sorted_frame.iloc[-1]
    high = float(sorted_frame["HiPrice"].max())
    low = float(sorted_frame["LowPrice"].min())
    buy = float(sorted_frame["BuyQty"].sum())
    sell = float(sorted_frame["SellQty"].sum())
    total = float(sorted_frame["TotalQty"].sum())
    open_price = float(first["OpenPrice"])
    close = float(last["ClosePrice"])
    close_position = (close - low) / (high - low) if high != low else 0.5
    return {
        "open": round(open_price, 6),
        "close": round(close, 6),
        "high": round(high, 6),
        "low": round(low, 6),
        "price_change_pct": round(((close / open_price) - 1.0) * 100.0, 6) if open_price else 0.0,
        "range_pct": round(((high / low) - 1.0) * 100.0, 6) if low else 0.0,
        "close_position": round(float(close_position), 4),
        "delta_pct": round(((buy - sell) / total) * 100.0, 6) if total else 0.0,
        "open_interest_change": round(float(last["OpenInterest"]) - float(first["OpenInterest"]), 6),
    }

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

def _trader_role(row: pd.Series, current_price: float) -> str:
    lower = float(row["price_lower"])
    upper = float(row["price_upper"])
    if upper < current_price:
        return "SUPPORT"
    if lower > current_price:
        return "RESISTANCE"
    return "CURRENT_ZONE"


def _nearest_role_band(levels: pd.DataFrame, role: str, price: float) -> pd.Series:
    if levels.empty:
        return pd.Series(dtype=object)
    frame = levels[levels["role"] == role].copy()
    if frame.empty:
        return pd.Series(dtype=object)
    if role == "SUPPORT":
        frame = frame[pd.to_numeric(frame["price_upper"], errors="coerce") <= price]
        if frame.empty:
            return pd.Series(dtype=object)
        return frame.sort_values("price_upper", ascending=False, kind="mergesort").iloc[0]
    ahead = frame[pd.to_numeric(frame["price_lower"], errors="coerce") >= price]
    if not ahead.empty:
        return ahead.sort_values("price_lower", ascending=True, kind="mergesort").iloc[0]
    containing = frame[pd.to_numeric(frame["price_upper"], errors="coerce") >= price]
    if containing.empty:
        return pd.Series(dtype=object)
    return containing.sort_values("price_upper", ascending=True, kind="mergesort").iloc[0]


def _nearest_band_for_price(levels: pd.DataFrame, role: str, price: float) -> pd.Series:
    if levels.empty:
        return pd.Series(dtype=object)
    frame = levels.copy()
    frame["price_lower"] = pd.to_numeric(frame["price_lower"], errors="coerce")
    frame["price_upper"] = pd.to_numeric(frame["price_upper"], errors="coerce")
    frame = frame.dropna(subset=["price_lower", "price_upper"])
    if role == "SUPPORT":
        below = frame[frame["price_upper"] <= price]
        if below.empty:
            return pd.Series(dtype=object)
        return below.sort_values("price_upper", ascending=False, kind="mergesort").iloc[0]
    containing = frame[(frame["price_lower"] <= price) & (frame["price_upper"] >= price)]
    if not containing.empty:
        return containing.sort_values("strength_score", ascending=False, kind="mergesort").iloc[0]
    above = frame[frame["price_lower"] >= price]
    if above.empty:
        return pd.Series(dtype=object)
    return above.sort_values("price_lower", ascending=True, kind="mergesort").iloc[0]


def _nearest_band(levels: pd.DataFrame, price: float) -> pd.Series:
    if levels.empty:
        return pd.Series(dtype=object)
    frame = levels.copy()
    frame["price_lower"] = pd.to_numeric(frame["price_lower"], errors="coerce")
    frame["price_upper"] = pd.to_numeric(frame["price_upper"], errors="coerce")
    covering = frame[(frame["price_lower"] <= price) & (frame["price_upper"] >= price)].copy()
    if not covering.empty:
        covering["_width"] = covering["price_upper"] - covering["price_lower"]
        return covering.sort_values(
            ["strength_score", "_width"],
            ascending=[False, True],
            kind="mergesort",
        ).iloc[0]
    frame["_distance"] = (pd.to_numeric(frame["price_mid"], errors="coerce") - price).abs()
    return frame.sort_values("_distance", kind="mergesort").iloc[0]


def _oi_context(metrics: dict[str, float]) -> str:
    price_change = metrics["price_change_pct"]
    oi_change = metrics["open_interest_change"]
    if price_change > 0 and oi_change < 0:
        return "OI_DOWN_DURING_UP_MOVE_POSITION_UNWIND_OR_SHORT_COVERING_UNCONFIRMED"
    if price_change < 0 and oi_change < 0:
        return "OI_DOWN_DURING_DOWN_MOVE_POSITION_UNWIND_UNCONFIRMED"
    if price_change > 0 and oi_change > 0:
        return "OI_UP_DURING_UP_MOVE_PARTICIPATION_BUILD_UNCONFIRMED"
    if price_change < 0 and oi_change > 0:
        return "OI_UP_DURING_DOWN_MOVE_PARTICIPATION_BUILD_UNCONFIRMED"
    return "OI_NEUTRAL_OR_UNCLEAR"


def _strength_bucket(value: float) -> str:
    if value >= 80:
        return "MAJOR"
    if value >= 55:
        return "PRIMARY"
    return "LOCAL_CONTEXT"


def _series_float(row: pd.Series, key: str) -> float:
    if row.empty:
        return 0.0
    try:
        return float(row.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _next_zone_text(row: pd.Series) -> str:
    if row.empty:
        return ""
    return (
        f"{row.get('band_id')} {row.get('role')} "
        f"{row.get('price_lower')}-{row.get('price_upper')} "
        f"strength={row.get('strength_bucket')}"
    )


def _last_close(feed: pd.DataFrame) -> float | None:
    if feed.empty:
        return None
    return float(feed.sort_values("Timestamp", kind="mergesort").iloc[-1]["ClosePrice"])


def _completed_daily_end(end_date: date, as_of_ts: datetime | None) -> date | None:
    if as_of_ts is None:
        return end_date
    as_of_date = as_of_ts.date()
    if as_of_ts.time() >= time(23, 59):
        return min(end_date, as_of_date)
    return min(end_date, as_of_date - timedelta(days=1))


def _parse_date(value: str | date, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MarketStructureStateError(f"{label} must be YYYY-MM-DD") from exc


def _parse_as_of(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketStructureStateError("as-of must be ISO timestamp") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _format_ts(value: pd.Timestamp | datetime | None) -> str:
    if value is None:
        return ""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def _repo_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _render_summary(
    *,
    levels: pd.DataFrame,
    events: pd.DataFrame,
    states: pd.DataFrame,
    input_root: Path,
    feed_dir: Path,
    start_date: date,
    end_date: date,
    as_of_ts: datetime | None,
    completed_daily_end: date | None,
) -> str:
    lines = [
        "# SHI_RESET_37E Market Structure State Memory",
        "",
        f"- Version: {STATE_VERSION}",
        f"- Input root: `{input_root}`",
        f"- Feed dir: `{feed_dir}`",
        f"- Window: {start_date.isoformat()} -> {end_date.isoformat()}",
        f"- As-of: {_format_ts(as_of_ts) if as_of_ts is not None else 'not_set'}",
        f"- Completed daily artifacts through: {completed_daily_end.isoformat() if completed_daily_end else 'none'}",
        f"- Level bands: {len(levels)}",
        f"- Structure events: {len(events)}",
        f"- State rows: {len(states)}",
        "- Scope: research monitor state memory only; no orders, execution, PnL, or live-readiness claims.",
        "",
        "## Current State",
    ]
    if states.empty:
        lines.append("- none")
    else:
        last = states.iloc[-1]
        lines.extend(
            [
                f"- Market state: {last['market_state']}",
                f"- Candidate bias: {last['candidate_bias']} ({last['candidate_strength']})",
                f"- Active support: {last['active_support_price_lower']} -> {last['active_support_price_upper']}",
                f"- Active resistance: {last['active_resistance_price_lower']} -> {last['active_resistance_price_upper']}",
                f"- Next zone: {last['next_zone_in_front_of_price']}",
                f"- OI context: {last['oi_context']}",
                f"- Evidence: {last['evidence_summary']}",
            ]
        )
    lines.append("")
    lines.append("## State Counts")
    if states.empty:
        lines.append("- none")
    else:
        for state, count in states["market_state"].value_counts().sort_index().items():
            lines.append(f"- {state}: {count}")
    lines.append("")
    lines.append("## Event Counts")
    if events.empty:
        lines.append("- none")
    else:
        for event_type, count in events["event_type"].value_counts().sort_index().items():
            lines.append(f"- {event_type}: {count}")
    lines.append("")
    return "\n".join(lines)
