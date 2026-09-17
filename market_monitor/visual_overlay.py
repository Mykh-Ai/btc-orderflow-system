from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from market_monitor.feed_adapter import load_feed
from market_monitor.zone_registry import (
    LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES,
    local_session_context_role,
)


REQUIRED_RUN_FILES = [
    "market_summary.md",
    "structure_levels.csv",
    "liquidity_map.csv",
    "liquidity_zone_registry.csv",
    "event_log.csv",
    "market_move_groups.csv",
    "post_sweep_observation.csv",
    "sweep_label_taxonomy.csv",
    "volume_delta_state.csv",
]

ACTIVE_ZONE_STATUSES = {"ACTIVE", "TOUCHED", "REACTED", "FLIPPED_REACTION_ZONE"}
INACTIVE_CONSUMPTION_STATUSES = {"CONSUMED", "CHOPPED_THROUGH", "EXPIRED"}
NON_FRESH_ACTIVE_ROLES = {"REACTION_ZONE", "DISTRIBUTION_ZONE", "RETEST_ZONE", "AUDIT_ONLY"}
SWEEP_ACTIVITY_ZSCORE_THRESHOLD = 1.5
SWEEP_MIN_EXCURSION_FRACTION = 0.0002
SWEEP_MIN_EXCURSION_USD = 10.0


@dataclass(frozen=True)
class VisualOverlayOptions:
    run_dir: Path
    feed_file: Path
    output_dir: Path
    market_move_id: str | None = None
    missed_timestamp: str | None = None
    window_hours_before: float = 24.0
    window_hours_after: float = 24.0
    timeframe: str = "M1"
    output_format: str = "html"
    include_low_precision: bool = False
    include_consumed: bool = False
    include_expired: bool = False
    include_secondary: bool = False
    focused_price_window_pct: float = 2.0


@dataclass(frozen=True)
class VisualOverlayResult:
    files: list[Path]
    manifest_path: Path
    summaries: list[dict[str, str]]
    missed_explanation_path: Path | None = None


def build_visual_overlay(options: VisualOverlayOptions) -> VisualOverlayResult:
    data = _load_visual_data(options.run_dir, options.feed_file)
    options.output_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    summaries: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []
    missed_explanation_path: Path | None = None

    if options.missed_timestamp:
        chart, markdown, summary = _build_missed_case(data, options)
        html_path = options.output_dir / f"missed_case_{_compact_minute(options.missed_timestamp)}.html"
        md_path = options.output_dir / f"missed_case_{_compact_minute(options.missed_timestamp)}.md"
        explanation_path = options.output_dir / "missed_case_explanation.md"
        html_path.write_text(chart, encoding="utf-8")
        md_path.write_text(markdown, encoding="utf-8")
        explanation_path.write_text(markdown, encoding="utf-8")
        files.extend([html_path, md_path, explanation_path])
        missed_explanation_path = explanation_path
        summaries.append(summary)
        manifest_rows.append(_manifest_row("missed_case", html_path, summary))
    elif options.market_move_id:
        chart, summary = _build_market_move_chart(data, options)
        html_path = options.output_dir / f"market_move_{options.market_move_id}.html"
        html_path.write_text(chart, encoding="utf-8")
        files.append(html_path)
        summaries.append(summary)
        manifest_rows.append(_manifest_row("market_move", html_path, summary))
    else:
        chart, summary = _build_full_day_chart(data, options)
        date_token = _date_token(data.feed)
        html_path = options.output_dir / f"liquidity_overlay_{date_token}.html"
        html_path.write_text(chart, encoding="utf-8")
        files.append(html_path)
        summaries.append(summary)
        manifest_rows.append(_manifest_row("full_day", html_path, summary))

    if options.output_format in {"png", "both"}:
        png_files = _try_write_png_fallback(files)
        files.extend(png_files)
        for png_path in png_files:
            manifest_rows.append(_manifest_row("static_fallback", png_path, {"summary": "static fallback"}))

    manifest_path = options.output_dir / "visual_audit_manifest.csv"
    pd.DataFrame(manifest_rows, columns=_manifest_columns()).to_csv(manifest_path, index=False)
    files.append(manifest_path)
    return VisualOverlayResult(files=files, manifest_path=manifest_path, summaries=summaries, missed_explanation_path=missed_explanation_path)


@dataclass(frozen=True)
class _VisualData:
    run_dir: Path
    feed: pd.DataFrame
    structure_levels: pd.DataFrame
    liquidity_map: pd.DataFrame
    registry: pd.DataFrame
    event_log: pd.DataFrame
    market_move_groups: pd.DataFrame
    observations: pd.DataFrame
    labels: pd.DataFrame
    volume_delta: pd.DataFrame
    pattern_structures: pd.DataFrame
    feed_has_liquidations: bool


def _load_visual_data(run_dir: Path, feed_file: Path) -> _VisualData:
    missing = [name for name in REQUIRED_RUN_FILES if not (run_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing required Market Monitor output: {missing[0]}")

    feed_has_liquidations = _csv_has_columns(feed_file, {"LiqBuyQty", "LiqSellQty"})
    feed = load_feed(feed_file)
    raw_feed = pd.read_csv(feed_file)
    for column in ["LiqBuyQty", "LiqSellQty"]:
        if column in raw_feed.columns:
            feed[column] = pd.to_numeric(raw_feed[column], errors="coerce").fillna(0.0)

    return _VisualData(
        run_dir=run_dir,
        feed=feed,
        structure_levels=_read_csv(run_dir / "structure_levels.csv"),
        liquidity_map=_read_csv(run_dir / "liquidity_map.csv"),
        registry=_read_csv(run_dir / "liquidity_zone_registry.csv"),
        event_log=_read_csv(run_dir / "event_log.csv"),
        market_move_groups=_read_csv(run_dir / "market_move_groups.csv"),
        observations=_read_csv(run_dir / "post_sweep_observation.csv"),
        labels=_read_csv(run_dir / "sweep_label_taxonomy.csv"),
        volume_delta=_read_csv(run_dir / "volume_delta_state.csv"),
        pattern_structures=_read_csv_if_exists(run_dir / "pattern_structures.csv"),
        feed_has_liquidations=feed_has_liquidations,
    )


def _build_full_day_chart(data: _VisualData, options: VisualOverlayOptions) -> tuple[str, dict[str, str]]:
    feed = _aggregate_feed(data.feed, options.timeframe)
    zones = _annotate_zones_with_patterns(_filter_zones(data.registry, options), data.pattern_structures)
    events = _events_for_window(data.event_log, feed["Timestamp"].min(), feed["Timestamp"].max())
    labels = _labels_for_events(data.labels, events)
    levels = _levels_for_window(data.structure_levels, feed["Timestamp"].min(), feed["Timestamp"].max())
    body = _render_chart_page(
        title=f"Full-day liquidity overlay {_date_token(feed)}",
        feed=feed,
        zones=zones,
        events=events,
        labels=labels,
        levels=levels,
        volume_delta=data.volume_delta,
        feed_has_liquidations=data.feed_has_liquidations,
        explanation_blocks=[
            _source_reference_warning(zones),
            _liquidation_message(data.feed_has_liquidations),
        ],
    )
    summary = {
        "summary": f"Full-day overlay with {len(zones)} zones and {len(events)} events.",
        "market_move_id": "",
        "label": "",
        "what_was_swept": "",
    }
    return body, summary


def _build_market_move_chart(data: _VisualData, options: VisualOverlayOptions) -> tuple[str, dict[str, str]]:
    move = _one_row(data.market_move_groups, "market_move_id", options.market_move_id or "")
    if move.empty:
        raise ValueError(f"market_move_id not found: {options.market_move_id}")
    start = pd.Timestamp(move["group_start_timestamp"])
    end = pd.Timestamp(move["group_end_timestamp"])
    window_start = start - pd.Timedelta(hours=options.window_hours_before)
    window_end = end + pd.Timedelta(hours=options.window_hours_after)
    feed = _aggregate_feed(_slice_feed(data.feed, window_start, window_end), options.timeframe)
    events = data.event_log[data.event_log["market_move_id"].astype(str) == options.market_move_id].copy()
    if not options.include_secondary:
        primary = events[events["market_move_role"].astype(str) == "PRIMARY"]
        events = primary if not primary.empty else events
    zones = _annotate_zones_with_patterns(
        _zones_for_ids(data.registry, _pipe_values(str(move.get("zone_ids", ""))) or events["zone_id"].astype(str).tolist(), options),
        data.pattern_structures,
    )
    labels = _labels_for_events(data.labels, events)
    levels = _levels_for_zone_sources(data.structure_levels, zones)
    what_was_swept = _what_was_swept_text(move, zones, events, labels)
    why_label = _why_label_text(labels)
    body = _render_chart_page(
        title=f"Market move {options.market_move_id}",
        feed=feed,
        zones=zones,
        events=events,
        labels=labels,
        levels=levels,
        volume_delta=data.volume_delta,
        feed_has_liquidations=data.feed_has_liquidations,
        explanation_blocks=[
            f"<h2>what_was_swept</h2><p>{html.escape(what_was_swept)}</p>",
            f"<h2>why_label</h2><p>{html.escape(why_label)}</p>",
            _source_reference_warning(zones),
            _liquidation_message(data.feed_has_liquidations),
        ],
    )
    summary = {
        "summary": f"Market move overlay for {options.market_move_id}.",
        "market_move_id": options.market_move_id or "",
        "label": _label_value(labels),
        "what_was_swept": what_was_swept,
    }
    return body, summary


def _build_missed_case(data: _VisualData, options: VisualOverlayOptions) -> tuple[str, str, dict[str, str]]:
    ts = pd.Timestamp(options.missed_timestamp)
    window_start = ts - pd.Timedelta(hours=options.window_hours_before)
    window_end = ts + pd.Timedelta(hours=options.window_hours_after)
    feed_window = _aggregate_feed(_slice_feed(data.feed, window_start, window_end), options.timeframe)
    if feed_window.empty:
        raise ValueError(f"No feed rows in missed-case window around {options.missed_timestamp}")

    price_row = _nearest_feed_row(data.feed, ts)
    price = float(price_row["ClosePrice"])
    all_near, far_away = _focused_zones(data.registry, price, options.focused_price_window_pct)
    all_near = _annotate_zones_with_patterns(all_near, data.pattern_structures)
    active_zones = _active_zones_at(all_near, ts, options)
    nearest_above, nearest_below = _nearest_zones(all_near, price)
    crossed_historical = _category_zones(all_near, status={"CROSSED_UNCLASSIFIED"})
    touched_zones = _category_zones(all_near, status={"TOUCHED"})
    consumed_or_chopped = _category_zones(all_near, consumption={"CONSUMED", "CHOPPED_THROUGH"})
    expired_or_merged = _category_zones(all_near, status={"EXPIRED", "MERGED"})
    htf_structural_levels = _htf_structural_levels(all_near)
    m15_structure_zones = _m15_structure_zones(all_near)
    local_session_zones = _local_session_zones(all_near)
    m1_local_zones = _m1_local_zones(all_near)
    h4_65500_audit = _h4_65500_audit(
        registry=data.registry,
        structure_levels=data.structure_levels,
        event_log=data.event_log,
        timestamp=ts,
    )
    broad_reaction_zones = _broad_reaction_zones(all_near)
    display_zones = _dedupe_zones(
        pd.concat(
            [active_zones, broad_reaction_zones, htf_structural_levels, m15_structure_zones],
            ignore_index=True,
        )
    )
    crossed = _crossed_zones_at(display_zones, price_row)
    gate_rows = [_missed_gate_row(zone, price_row, data.volume_delta, data.event_log) for _, zone in crossed.iterrows()]
    if not gate_rows and active_zones.empty:
        primary_reason = "no_active_forward_zone_at_price"
    elif not gate_rows:
        primary_reason = "no_zone_near_price" if all_near.empty else "insufficient_excursion"
    else:
        primary_reason = _primary_missed_reason(gate_rows)

    context_events = _events_for_window(data.event_log, window_start, window_end)
    labels = _labels_for_events(data.labels, context_events)
    levels = _levels_for_zone_sources(data.structure_levels, display_zones)
    explanation = _missed_markdown(
        timestamp=_format_ts(ts),
        price=price,
        active_zones=active_zones,
        nearest_above=nearest_above,
        nearest_below=nearest_below,
        crossed=crossed,
        crossed_historical=crossed_historical,
        touched_zones=touched_zones,
        consumed_or_chopped=consumed_or_chopped,
        expired_or_merged=expired_or_merged,
        htf_structural_levels=htf_structural_levels,
        m15_structure_zones=m15_structure_zones,
        local_session_zones=local_session_zones,
        m1_local_zones=m1_local_zones,
        h4_65500_audit=h4_65500_audit,
        broad_reaction_zones=broad_reaction_zones,
        far_away=far_away,
        gate_rows=gate_rows,
        primary_reason=primary_reason,
    )
    body = _render_chart_page(
        title=f"Missed-case overlay {_format_ts(ts)}",
        feed=feed_window,
        zones=display_zones,
        events=context_events,
        labels=labels,
        levels=levels,
        volume_delta=data.volume_delta,
        feed_has_liquidations=data.feed_has_liquidations,
        vertical_markers=[(_format_ts(ts), "missed manual timestamp")],
        explanation_blocks=[
            "<h2>missed_case_explanation</h2>" + _markdown_as_html(explanation),
            _source_reference_warning(display_zones),
            _liquidation_message(data.feed_has_liquidations),
        ],
    )
    summary = {
        "summary": f"Missed timestamp {_format_ts(ts)}: {primary_reason}.",
        "market_move_id": "",
        "label": "",
        "what_was_swept": primary_reason,
    }
    return body, explanation, summary


def _render_chart_page(
    *,
    title: str,
    feed: pd.DataFrame,
    zones: pd.DataFrame,
    events: pd.DataFrame,
    labels: pd.DataFrame,
    levels: pd.DataFrame,
    volume_delta: pd.DataFrame,
    feed_has_liquidations: bool,
    explanation_blocks: list[str],
    vertical_markers: list[tuple[str, str]] | None = None,
) -> str:
    vertical_markers = vertical_markers or []
    price_svg = _price_svg(feed, zones, events, levels, vertical_markers)
    volume_svg = _bar_svg(feed, "TotalQty", "Volume TotalQty")
    delta_svg = _delta_svg(feed)
    oi_svg = _line_svg(feed, "OpenInterest", "Open Interest")
    liquidation_panel = (
        _liquidation_svg(feed)
        if feed_has_liquidations and {"LiqBuyQty", "LiqSellQty"}.issubset(feed.columns)
        else '<div class="notice">Liquidation fields unavailable for this feed/day.</div>'
    )
    return "\n".join(
        [
            "<!doctype html>",
            "<html><head><meta charset=\"utf-8\">",
            f"<title>{html.escape(title)}</title>",
            "<style>",
            _css(),
            "</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
            '<section class="panel"><h2>Price panel</h2>',
            price_svg,
            _zone_table(zones),
            _event_table(events, labels),
            "</section>",
            '<section class="panel"><h2>Source levels</h2>',
            _source_level_table(levels, zones),
            "</section>",
            '<section class="panel"><h2>OI / Volume / Delta / Liquidations</h2>',
            volume_svg,
            delta_svg,
            oi_svg,
            liquidation_panel,
            _context_table(feed, volume_delta),
            "</section>",
            '<section class="panel"><h2>Audit explanation</h2>',
            "\n".join(explanation_blocks),
            "</section>",
            "</body></html>",
        ]
    )


def _price_svg(
    feed: pd.DataFrame,
    zones: pd.DataFrame,
    events: pd.DataFrame,
    levels: pd.DataFrame,
    vertical_markers: list[tuple[str, str]],
) -> str:
    if feed.empty:
        return '<div class="notice">No feed rows available for chart window.</div>'
    width, height = 1200, 440
    left, right, top, bottom = 70, 30, 20, 40
    inner_w = width - left - right
    inner_h = height - top - bottom
    price_min = min(
        float(feed["LowPrice"].min()),
        _numeric_min(zones, "price_lower"),
        _numeric_min(zones, "zone_outer_lower"),
        _numeric_min(levels, "price"),
    )
    price_max = max(
        float(feed["HiPrice"].max()),
        _numeric_max(zones, "price_upper"),
        _numeric_max(zones, "zone_outer_upper"),
        _numeric_max(levels, "price"),
    )
    if price_max <= price_min:
        price_max = price_min + 1
    times = list(feed["Timestamp"])
    first = pd.Timestamp(times[0])
    last = pd.Timestamp(times[-1])
    span = max((last - first).total_seconds(), 60.0)

    def x_for(ts) -> float:
        return left + (pd.Timestamp(ts) - first).total_seconds() / span * inner_w

    def y_for(price) -> float:
        return top + (price_max - float(price)) / (price_max - price_min) * inner_h

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="price candles liquidity zones events">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#637083"/>',
        f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#637083"/>',
    ]
    for _, zone in zones.iterrows():
        start = max(pd.Timestamp(zone.get("first_seen_at", first)), first)
        end_value = zone.get("last_seen_at") or zone.get("last_updated_at") or last
        end = min(pd.Timestamp(end_value), last)
        if end < first or start > last:
            continue
        color = _zone_color(zone)
        opacity = _zone_opacity(zone)
        dash = _zone_dash(zone)
        outer_lower = _zone_outer_lower(zone)
        outer_upper = _zone_outer_upper(zone)
        core_lower = _zone_core_lower(zone)
        core_upper = _zone_core_upper(zone)
        y1 = y_for(outer_upper)
        y2 = y_for(outer_lower)
        x1 = x_for(start)
        x2 = x_for(end)
        label = _zone_label(zone)
        parts.append(
            f'<rect x="{x1:.2f}" y="{min(y1, y2):.2f}" width="{max(2, x2-x1):.2f}" '
            f'height="{max(2, abs(y2-y1)):.2f}" fill="{color}" opacity="{opacity}">'
            f'<title>{html.escape(label)}</title></rect>'
        )
        if _is_broad_zone(zone):
            core_y1 = y_for(core_upper)
            core_y2 = y_for(core_lower)
            parts.append(
                f'<rect x="{x1:.2f}" y="{min(core_y1, core_y2):.2f}" width="{max(2, x2-x1):.2f}" '
                f'height="{max(2, abs(core_y2-core_y1)):.2f}" fill="{color}" opacity="0.28">'
                f'<title>{html.escape(label + " core zone")}</title></rect>'
            )
        mid_y = y_for(zone["price_mid"])
        parts.append(f'<line x1="{x1:.2f}" y1="{mid_y:.2f}" x2="{x2:.2f}" y2="{mid_y:.2f}" stroke="{color}" stroke-dasharray="{dash}"/>')
        parts.append(f'<text x="{x1 + 3:.2f}" y="{max(12, mid_y - 4):.2f}" font-size="10" fill="{color}">{html.escape(str(zone.get("zone_id", "")))}</text>')
    for _, level in levels.iterrows():
        if "price" not in level or _is_missing(level.get("price")):
            continue
        y = y_for(level["price"])
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#6b7280" stroke-width="1" opacity="0.35"/>')
    candle_w = max(1.5, min(7.0, inner_w / max(len(feed), 1) * 0.65))
    for _, row in feed.iterrows():
        x = x_for(row["Timestamp"])
        open_y = y_for(row["OpenPrice"])
        close_y = y_for(row["ClosePrice"])
        high_y = y_for(row["HiPrice"])
        low_y = y_for(row["LowPrice"])
        up = float(row["ClosePrice"]) >= float(row["OpenPrice"])
        color = "#15803d" if up else "#b91c1c"
        parts.append(f'<line x1="{x:.2f}" y1="{high_y:.2f}" x2="{x:.2f}" y2="{low_y:.2f}" stroke="{color}" stroke-width="1"/>')
        parts.append(f'<rect x="{x - candle_w/2:.2f}" y="{min(open_y, close_y):.2f}" width="{candle_w:.2f}" height="{max(1.5, abs(close_y-open_y)):.2f}" fill="{color}" opacity="0.85"/>')
    for _, event in events.iterrows():
        x = x_for(event["event_timestamp"])
        y = y_for(_event_marker_price(event, price_min))
        role = str(event.get("market_move_role", ""))
        color = "#7c3aed" if role == "PRIMARY" else "#0f766e"
        marker = _event_title(event)
        parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="6" fill="{color}" opacity="0.9"><title>{html.escape(marker)}</title></circle>')
        parts.append(f'<text x="{x + 7:.2f}" y="{y - 7:.2f}" font-size="10" fill="{color}">{html.escape(str(event.get("market_move_id", "")) or str(event.get("event_type", "")))}</text>')
    for marker_ts, marker_label in vertical_markers:
        x = x_for(marker_ts)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" stroke="#111827" stroke-width="2" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{x + 5:.2f}" y="{top + 14}" font-size="11" fill="#111827">{html.escape(marker_label)}</text>')
    for pct in [0, 0.25, 0.5, 0.75, 1]:
        price = price_max - (price_max - price_min) * pct
        y = top + inner_h * pct
        parts.append(f'<text x="6" y="{y + 4:.2f}" font-size="11" fill="#374151">{price:.2f}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _bar_svg(feed: pd.DataFrame, column: str, title: str) -> str:
    if feed.empty or column not in feed.columns:
        return f'<div class="notice">{html.escape(title)} unavailable.</div>'
    width, height = 1200, 150
    left, right, top, bottom = 70, 30, 20, 25
    values = pd.to_numeric(feed[column], errors="coerce").fillna(0)
    max_value = max(float(values.max()), 1.0)
    bar_w = max(1.0, (width - left - right) / max(len(feed), 1))
    parts = [f'<h3>{html.escape(title)}</h3>', f'<svg viewBox="0 0 {width} {height}">', f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for idx, value in enumerate(values):
        h = float(value) / max_value * (height - top - bottom)
        x = left + idx * bar_w
        y = height - bottom - h
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(1.0, bar_w * 0.8):.2f}" height="{h:.2f}" fill="#64748b" opacity="0.75"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _delta_svg(feed: pd.DataFrame) -> str:
    if feed.empty:
        return '<div class="notice">Delta unavailable.</div>'
    frame = feed.copy()
    frame["Delta"] = pd.to_numeric(frame["BuyQty"], errors="coerce").fillna(0) - pd.to_numeric(frame["SellQty"], errors="coerce").fillna(0)
    return _signed_bar_svg(frame, "Delta", "Delta BuyQty - SellQty")


def _liquidation_svg(feed: pd.DataFrame) -> str:
    frame = feed.copy()
    frame["Liquidations"] = pd.to_numeric(frame["LiqBuyQty"], errors="coerce").fillna(0) + pd.to_numeric(frame["LiqSellQty"], errors="coerce").fillna(0)
    return _bar_svg(frame, "Liquidations", "Liquidations LiqBuyQty + LiqSellQty")


def _signed_bar_svg(feed: pd.DataFrame, column: str, title: str) -> str:
    width, height = 1200, 150
    left, right, top, bottom = 70, 30, 20, 25
    values = pd.to_numeric(feed[column], errors="coerce").fillna(0)
    max_abs = max(float(values.abs().max()), 1.0)
    center = top + (height - top - bottom) / 2
    bar_w = max(1.0, (width - left - right) / max(len(feed), 1))
    parts = [f'<h3>{html.escape(title)}</h3>', f'<svg viewBox="0 0 {width} {height}">', f'<rect width="{width}" height="{height}" fill="#ffffff"/>', f'<line x1="{left}" y1="{center:.2f}" x2="{width-right}" y2="{center:.2f}" stroke="#94a3b8"/>']
    for idx, value in enumerate(values):
        h = abs(float(value)) / max_abs * ((height - top - bottom) / 2)
        x = left + idx * bar_w
        y = center - h if value >= 0 else center
        color = "#15803d" if value >= 0 else "#b91c1c"
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(1.0, bar_w * 0.8):.2f}" height="{h:.2f}" fill="{color}" opacity="0.75"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _line_svg(feed: pd.DataFrame, column: str, title: str) -> str:
    if feed.empty or column not in feed.columns:
        return f'<div class="notice">{html.escape(title)} unavailable.</div>'
    width, height = 1200, 150
    left, right, top, bottom = 70, 30, 20, 25
    values = pd.to_numeric(feed[column], errors="coerce").fillna(0)
    min_v = float(values.min())
    max_v = float(values.max())
    if max_v <= min_v:
        max_v = min_v + 1
    step = (width - left - right) / max(len(values) - 1, 1)
    points = []
    for idx, value in enumerate(values):
        x = left + idx * step
        y = top + (max_v - float(value)) / (max_v - min_v) * (height - top - bottom)
        points.append(f"{x:.2f},{y:.2f}")
    return "\n".join(
        [
            f"<h3>{html.escape(title)}</h3>",
            f'<svg viewBox="0 0 {width} {height}">',
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
            f'<polyline points="{" ".join(points)}" fill="none" stroke="#4338ca" stroke-width="2"/>',
            "</svg>",
        ]
    )


def _zone_table(zones: pd.DataFrame) -> str:
    columns = [
        "zone_id",
        "side",
        "zone_type",
        "price_lower",
        "price_upper",
        "price_mid",
        "first_seen_at",
        "last_seen_at",
        "status",
        "consumption_status",
        "active_forward",
        "active_forward_role",
        "structural_zone_mode",
        "zone_behavior_state",
        "zone_outer_lower",
        "zone_outer_upper",
        "zone_core_lower",
        "zone_core_upper",
        "first_sweep_at",
        "resweep_count",
        "failed_acceptance_count",
        "rejection_without_sweep_count",
        "drift_away_confirmed_at",
        "cross_through_count",
        "alternating_close_count",
        "bars_inside_zone_lifetime",
        "precision_status",
        "confidence_tier",
        "pattern_type",
        "source_timeframe_primary",
        "source_timeframes",
        "htf_level_type",
        "htf_origin_timestamp",
        "htf_origin_price",
        "htf_confirmation_timestamp",
        "htf_lifecycle_status",
        "m1_interaction_count",
        "htf_sweep_count",
        "htf_close_through_count",
        "htf_acceptance_count",
        "history_context_start",
        "history_context_incomplete",
        "sweep_importance_class",
        "source_level_ids",
        "source_ref_count",
    ]
    return _table("Liquidity zones", zones, columns)


def _event_table(events: pd.DataFrame, labels: pd.DataFrame) -> str:
    frame = events.copy()
    if not frame.empty and not labels.empty:
        label_map = labels.set_index("market_move_id")["label"].to_dict()
        reason_map = labels.set_index("market_move_id")["label_reason"].to_dict()
        frame["label"] = frame["market_move_id"].map(label_map).fillna("")
        frame["label_reason"] = frame["market_move_id"].map(reason_map).fillna("")
    columns = [
        "event_timestamp",
        "event_type",
        "market_move_id",
        "market_move_role",
        "zone_id",
        "side",
        "excursion_abs",
        "volume_zscore",
        "delta_zscore",
        "oi_change",
        "reaction_status",
        "label",
        "label_reason",
    ]
    return _table("Event annotations", frame, columns)


def _source_level_table(levels: pd.DataFrame, zones: pd.DataFrame) -> str:
    source_detail = _table(
        "Source level rows",
        levels,
        [
            "level_id",
            "created_at",
            "level_timestamp",
            "timeframe",
            "source_timeframe_primary",
            "level_type",
            "price",
            "htf_level_type",
            "htf_origin_timestamp",
            "htf_origin_price",
            "htf_confirmation_timestamp",
            "strength_score",
            "status",
        ],
    )
    refs = _table(
        "Zone source references",
        zones,
        [
            "zone_id",
            "source_level_ids",
            "source_timeframe_primary",
            "source_timeframes",
            "htf_level_type",
            "htf_lifecycle_status",
            "sweep_importance_class",
            "source_ref_count",
            "zone_type",
        ],
    )
    return refs + source_detail


def _context_table(feed: pd.DataFrame, volume_delta: pd.DataFrame) -> str:
    frame = volume_delta.copy()
    if frame.empty:
        frame = pd.DataFrame()
    columns = ["timestamp", "total_qty", "delta", "volume_zscore", "delta_zscore", "oi", "oi_change"]
    return _table("Context rows", frame.tail(20), columns)


def _table(title: str, frame: pd.DataFrame, columns: list[str]) -> str:
    present = [column for column in columns if column in frame.columns]
    if frame.empty or not present:
        return f'<h3>{html.escape(title)}</h3><div class="notice">No rows.</div>'
    rows = [f"<h3>{html.escape(title)}</h3>", "<table><thead><tr>"]
    rows.extend(f"<th>{html.escape(column)}</th>" for column in present)
    rows.append("</tr></thead><tbody>")
    for _, row in frame[present].head(200).iterrows():
        rows.append("<tr>")
        rows.extend(f"<td>{html.escape(_display(value))}</td>" for value in row)
        rows.append("</tr>")
    rows.append("</tbody></table>")
    return "\n".join(rows)


def _what_was_swept_text(move: pd.Series, zones: pd.DataFrame, events: pd.DataFrame, labels: pd.DataFrame) -> str:
    primary_zone_id = str(move.get("primary_zone_id", ""))
    primary_zone = _one_row(zones, "zone_id", primary_zone_id)
    primary_event = _one_row(events, "event_id", str(move.get("primary_event_id", "")))
    zone = primary_zone if not primary_zone.empty else (zones.iloc[0] if not zones.empty else pd.Series(dtype=object))
    event = primary_event if not primary_event.empty else (events.iloc[0] if not events.empty else pd.Series(dtype=object))
    if zone.empty:
        return f"{move.get('side', '')} market_move {move.get('market_move_id', '')}: zone detail unavailable."
    structure_note = _structure_note(zone)
    return (
        f"{_weak_local_badge(zone)}"
        f"{zone.get('side', '')} sweep of {zone.get('zone_id', '')}. "
        f"Zone type: {zone.get('zone_type', '')}"
        f"{' / ' + str(zone.get('pattern_type', '')) if str(zone.get('pattern_type', '')) else ''}. "
        f"Zone bounds: {zone.get('price_lower', '')} - {zone.get('price_upper', '')}. "
        f"Source primary: {zone.get('source_timeframe_primary', '')}; source: {zone.get('source_timeframes', '')}; "
        f"source_level_ids={zone.get('source_level_ids', '')}; "
        f"htf_lifecycle_status={zone.get('htf_lifecycle_status', '')}; "
        f"sweep_importance_class={zone.get('sweep_importance_class', '')}; "
        f"confidence_tier={zone.get('confidence_tier', '')}; precision_status={zone.get('precision_status', '')}; "
        f"consumption_status={zone.get('consumption_status', '')}; "
        f"zone_behavior_state={zone.get('zone_behavior_state', '')}; active_forward_role={zone.get('active_forward_role', '')}; "
        f"{structure_note} "
        f"Created before event: {_created_before(zone, event)}. "
        f"Active forward before event: {_active_forward_before(zone, event)}. "
        f"Excursion beyond zone: {event.get('excursion_abs', '')}. "
        f"Volume z-score: {event.get('volume_zscore', '')}. "
        f"Delta z-score: {event.get('delta_zscore', '')}. "
        f"OI change: {event.get('oi_change', '')}. "
        f"Label: {_label_value(labels)}."
    )


def _why_label_text(labels: pd.DataFrame) -> str:
    if labels.empty:
        return "SWEEP_NO_LABEL because no label taxonomy row was available for this market_move_id."
    label = str(labels.iloc[0].get("label", ""))
    reason = str(labels.iloc[0].get("label_reason", ""))
    if label == "SWEEP_REJECTED":
        return f"{label} because {reason}; return/close-inside and bars-inside metrics are recorded in sweep_label_taxonomy.csv."
    if label == "SWEEP_ACCEPTED":
        return f"{label} because {reason}; post-event close stayed beyond the swept side under taxonomy rules."
    if label == "SWEEP_NO_LABEL":
        return f"{label} because {reason}."
    if label == "SWEEP_INVALID_SAMPLE":
        return f"{label} because {reason}."
    return f"{label or 'SWEEP_UNRESOLVED'} because {reason or 'eligible_but_ambiguous'}."


def _missed_markdown(
    *,
    timestamp: str,
    price: float,
    active_zones: pd.DataFrame,
    nearest_above: pd.Series | None,
    nearest_below: pd.Series | None,
    crossed: pd.DataFrame,
    crossed_historical: pd.DataFrame,
    touched_zones: pd.DataFrame,
    consumed_or_chopped: pd.DataFrame,
    expired_or_merged: pd.DataFrame,
    htf_structural_levels: pd.DataFrame,
    m15_structure_zones: pd.DataFrame,
    local_session_zones: pd.DataFrame,
    m1_local_zones: pd.DataFrame,
    h4_65500_audit: str,
    broad_reaction_zones: pd.DataFrame,
    far_away: pd.DataFrame,
    gate_rows: list[dict[str, str]],
    primary_reason: str,
) -> str:
    return "\n".join(
        [
            "# missed_case_explanation",
            "",
            f"timestamp inspected: {timestamp}",
            f"price at timestamp: {price:.2f}",
            "",
            "## ACTIVE_FORWARD_ZONES_NEAR_PRICE",
            _markdown_zone_list(active_zones),
            "",
            "## NEAREST_ZONES_ABOVE_BELOW",
            f"nearest above: {_markdown_zone_one(nearest_above)}",
            f"nearest below: {_markdown_zone_one(nearest_below)}",
            "",
            "## CROSSED_HISTORICAL_ZONES_NEAR_PRICE",
            _markdown_zone_list(crossed_historical),
            "",
            "## TOUCHED_ZONES_NEAR_PRICE",
            _markdown_zone_list(touched_zones),
            "",
            "## CONSUMED_OR_CHOPPED_ZONES_NEAR_PRICE",
            _markdown_zone_list(consumed_or_chopped),
            "",
            "## EXPIRED_OR_MERGED_ZONES_NEAR_PRICE",
            _markdown_zone_list(expired_or_merged),
            "",
            "## HTF_STRUCTURAL_LEVELS",
            _markdown_zone_list(htf_structural_levels),
            "",
            "## M15_MINIMUM_STRUCTURE",
            _markdown_zone_list(m15_structure_zones),
            "",
            "## LOCAL_SESSION_ZONES",
            _markdown_zone_list(local_session_zones),
            "",
            "## M1_LOCAL_ZONES",
            _markdown_zone_list(m1_local_zones),
            "",
            "## H4_65500_MISSED_CASE_AUDIT",
            h4_65500_audit,
            "",
            "## BROAD_DISTRIBUTION_REACTION_ZONES_NEAR_PRICE",
            _markdown_zone_list(broad_reaction_zones),
            "",
            "## FAR_AWAY_ZONES_EXCLUDED_FROM_FOCUSED_VIEW",
            _markdown_zone_list(far_away),
            "",
            "## ZONES_CROSSED_AT_TIMESTAMP",
            _markdown_zone_list(crossed),
            "",
            "## why no LIQUIDITY_SWEEP_UNRESOLVED was emitted",
            primary_reason,
            "",
            _markdown_gate_rows(gate_rows),
            "",
            "## what data was missing if any",
            "No liquidation conclusion is made unless LiqBuyQty/LiqSellQty exist in the feed. Source level references are daily-local when not globally qualified.",
            "",
            "## recommendation",
            _recommendation(primary_reason),
            "",
            "## repeated interaction note",
            _repeated_interaction_note(primary_reason, broad_reaction_zones),
            "",
        ]
    )


def _missed_gate_row(zone: pd.Series, candle: pd.Series, volume_delta: pd.DataFrame, event_log: pd.DataFrame) -> dict[str, str]:
    ts = _format_ts(candle["Timestamp"])
    existing_event = event_log[
        (event_log.get("event_timestamp", "").astype(str) == ts)
        & (event_log.get("zone_id", "").astype(str) == str(zone.get("zone_id", "")))
    ]
    ctx = _context_at(volume_delta, ts)
    side = str(zone.get("side", ""))
    excursion = _cross_excursion(zone, candle)
    min_excursion = max(SWEEP_MIN_EXCURSION_USD, float(zone.get("price_mid", 0) or 0) * SWEEP_MIN_EXCURSION_FRACTION)
    reasons = []
    if str(zone.get("active_forward", "")).lower() == "false":
        reasons.append("no_active_forward_zone_at_price")
    if str(zone.get("status", "")) == "CROSSED_UNCLASSIFIED":
        reasons.append("zone_already_crossed_before_timestamp")
    role = str(zone.get("active_forward_role", "") or "FRESH_LIQUIDITY")
    first_sweep_at = str(zone.get("first_sweep_at", "") or "")
    if _is_local_context_forward_zone(zone) or (
        role in NON_FRESH_ACTIVE_ROLES
        and (not first_sweep_at or pd.Timestamp(first_sweep_at) < pd.Timestamp(candle["Timestamp"]))
    ):
        reasons.append("repeated_interaction_not_modeled")
    if str(zone.get("consumption_status", "")) == "CONSUMED":
        reasons.append("zone_consumed_before_timestamp")
    if str(zone.get("consumption_status", "")) == "CHOPPED_THROUGH":
        reasons.append("zone_chopped_through_before_timestamp")
    if pd.Timestamp(zone.get("first_seen_at")) >= pd.Timestamp(candle["Timestamp"]):
        reasons.append("zone_already_crossed_before_timestamp")
    if str(zone.get("precision_status", "")) != "PRECISE":
        reasons.append("precision_status_not_eligible")
    if excursion < min_excursion:
        reasons.append("insufficient_excursion")
    if not _activity_passed(ctx):
        reasons.append("insufficient_activity_context")
    if not existing_event.empty:
        labels = existing_event["event_type"].astype(str).tolist()
        if "LIQUIDITY_SWEEP_UNRESOLVED" in labels:
            reasons.append("model_blind_spot_candidate")
        else:
            reasons.append("repeated_interaction_not_modeled")
    return {
        "zone_id": str(zone.get("zone_id", "")),
        "side": side,
        "active_forward_role": role,
        "zone_behavior_state": str(zone.get("zone_behavior_state", "")),
        "excursion_abs": f"{excursion:.6g}",
        "min_excursion_abs": f"{min_excursion:.6g}",
        "volume_zscore": str(ctx.get("volume_zscore", "")),
        "delta_zscore": str(ctx.get("delta_zscore", "")),
        "oi_change": str(ctx.get("oi_change", "")),
        "reasons": ", ".join(dict.fromkeys(reasons)) if reasons else "model_blind_spot_candidate",
    }


def _markdown_gate_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "No crossed active zone was available for gate diagnostics."
    lines = [
        "| zone_id | side | active_forward_role | zone_behavior_state | excursion_abs | min_excursion_abs | volume_zscore | delta_zscore | oi_change | reasons |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['zone_id']} | {row['side']} | {row['active_forward_role']} | {row['zone_behavior_state']} | "
            f"{row['excursion_abs']} | {row['min_excursion_abs']} | "
            f"{row['volume_zscore']} | {row['delta_zscore']} | {row['oi_change']} | {row['reasons']} |"
        )
    return "\n".join(lines)


def _primary_missed_reason(rows: list[dict[str, str]]) -> str:
    joined = " | ".join(row["reasons"] for row in rows)
    for reason in [
        "zone_consumed_before_timestamp",
        "zone_chopped_through_before_timestamp",
        "repeated_interaction_not_modeled",
        "zone_already_crossed_before_timestamp",
        "no_active_forward_zone_at_price",
        "precision_status_not_eligible",
        "insufficient_excursion",
        "insufficient_activity_context",
        "model_blind_spot_candidate",
    ]:
        if reason in joined:
            return reason
    return "model_blind_spot_candidate"


def _recommendation(reason: str) -> str:
    if reason == "repeated_interaction_not_modeled":
        return "nearest zone is a repeated-interaction or reaction/distribution candidate; current model does not emit repeated-interaction sweep events from this state"
    if reason in {"zone_consumed_before_timestamp", "zone_chopped_through_before_timestamp", "zone_already_crossed_before_timestamp"}:
        return "expected exclusion from active forward liquidity"
    if reason in {"no_zone_near_price", "no_active_forward_zone_at_price"}:
        return "zone construction or active-forward coverage issue"
    if "activity" in reason:
        return "activity gate issue"
    if "precision" in reason:
        return "precision issue"
    return "model blind spot candidate for manual review"


def _repeated_interaction_note(reason: str, zones: pd.DataFrame) -> str:
    if reason == "repeated_interaction_not_modeled":
        return "Nearest zone was previously crossed and is now a reaction/distribution/retest candidate. Current model does not emit repeated-interaction sweep events from this state."
    if not zones.empty:
        return "Broad structural reaction/distribution zones are visible for audit, but they are not fresh first-sweep liquidity."
    return "No broad structural reaction/distribution zone was identified near this timestamp."


def _filter_zones(registry: pd.DataFrame, options: VisualOverlayOptions) -> pd.DataFrame:
    zones = registry.copy()
    if zones.empty:
        return zones
    if not options.include_consumed and "consumption_status" in zones.columns:
        zones = zones[~zones["consumption_status"].astype(str).isin({"CONSUMED", "CHOPPED_THROUGH"})]
    if not options.include_expired and "status" in zones.columns:
        zones = zones[zones["status"].astype(str) != "MERGED"]
        zones = zones[zones["status"].astype(str) != "EXPIRED"]
    if not options.include_low_precision and "precision_status" in zones.columns:
        zones = zones[zones["precision_status"].astype(str) != "TOO_WIDE"]
    return zones.reset_index(drop=True)


def _zones_for_ids(registry: pd.DataFrame, zone_ids: Iterable[str], options: VisualOverlayOptions) -> pd.DataFrame:
    ids = {str(value) for value in zone_ids if str(value)}
    zones = _filter_zones(registry, options)
    if not ids or zones.empty:
        return zones.iloc[0:0]
    return zones[zones["zone_id"].astype(str).isin(ids)].copy()


def _active_zones_at(registry: pd.DataFrame, ts: pd.Timestamp, options: VisualOverlayOptions) -> pd.DataFrame:
    zones = registry.copy()
    if zones.empty:
        return zones
    first_seen = zones["first_seen_at"].map(pd.Timestamp)
    last_seen = zones["last_seen_at"].map(pd.Timestamp)
    active = zones[(first_seen <= ts) & (last_seen >= ts)].copy()
    active = active[active["status"].astype(str).isin(ACTIVE_ZONE_STATUSES)]
    if "active_forward" in active.columns:
        active = active[active["active_forward"].map(_bool_value)]
    if "consumption_status" in active.columns:
        active = active[~active["consumption_status"].astype(str).isin(INACTIVE_CONSUMPTION_STATUSES)]
    active = active[~active.apply(_is_local_context_forward_zone, axis=1)]
    return active.reset_index(drop=True)


def _focused_zones(registry: pd.DataFrame, price: float, focused_price_window_pct: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if registry.empty:
        return registry.copy(), registry.copy()
    lower = price * (1 - focused_price_window_pct / 100)
    upper = price * (1 + focused_price_window_pct / 100)
    mids = pd.to_numeric(registry["price_mid"], errors="coerce")
    near = registry[(mids >= lower) & (mids <= upper)].copy()
    far = registry[(mids < lower) | (mids > upper)].copy()
    return near.reset_index(drop=True), far.reset_index(drop=True)


def _category_zones(
    zones: pd.DataFrame,
    *,
    status: set[str] | None = None,
    consumption: set[str] | None = None,
) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    mask = pd.Series([True] * len(zones), index=zones.index)
    if status is not None:
        mask &= zones["status"].astype(str).isin(status)
    if consumption is not None:
        mask &= zones["consumption_status"].astype(str).isin(consumption)
    return zones[mask].copy()


def _htf_structural_levels(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    return zones[zones.apply(_is_htf_zone, axis=1)].copy()


def _m15_structure_zones(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    return zones[zones.apply(_is_m15_zone, axis=1)].copy()


def _local_session_zones(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    mask = zones.apply(_is_local_session_zone, axis=1)
    return zones[mask].copy()


def _m1_local_zones(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    mask = (
        ~zones.apply(_is_htf_zone, axis=1)
        & ~zones.apply(_is_m15_zone, axis=1)
        & ~zones.apply(_is_local_session_zone, axis=1)
    )
    return zones[mask].copy()


def _h4_65500_audit(
    *,
    registry: pd.DataFrame,
    structure_levels: pd.DataFrame,
    event_log: pd.DataFrame,
    timestamp: pd.Timestamp,
) -> str:
    target_price = 65500.0
    tolerance = 1200.0
    window_start = timestamp - pd.Timedelta(hours=1)
    window_end = timestamp + pd.Timedelta(hours=1)
    h4_levels = _h4_levels_near(structure_levels, target_price, tolerance)
    registry_candidates = _h4_registry_zones_near(registry, target_price, tolerance)
    if h4_levels.empty and registry_candidates.empty:
        return "\n".join(
            [
                "classification: model_blind_spot_htf_structure",
                "h4_level_exists: false",
                "registry_zone_exists: false",
                f"target_price: {target_price:.2f}",
                f"candidate_window_utc: {_format_ts(window_start)} to {_format_ts(window_end)}",
                "explanation: no H4 SELL_SIDE structural low near 65,500 was present in structure_levels.csv, so the missed case cannot be explained as a modeled H4 structural sweep.",
            ]
        )

    h4_level = h4_levels.iloc[0] if not h4_levels.empty else pd.Series(dtype=object)
    if registry_candidates.empty:
        return "\n".join(
            [
                "classification: model_blind_spot_htf_structure",
                "h4_level_exists: true",
                "registry_zone_exists: false",
                f"h4_level_type: {_display(h4_level.get('level_type', ''))}",
                f"h4_origin_timestamp: {_display(h4_level.get('level_timestamp', ''))}",
                f"h4_origin_price: {_display(h4_level.get('price', ''))}",
                f"h4_confirmation_timestamp: {_display(h4_level.get('created_at', ''))}",
                f"candidate_window_utc: {_format_ts(window_start)} to {_format_ts(window_end)}",
                "explanation: the H4 low was created, but no registry zone near 65,500 carried the H4 structural lineage.",
            ]
        )

    zone = registry_candidates.iloc[0]
    zone_id = str(zone.get("zone_id", ""))
    sweep_times = _zone_sweep_times(zone, event_log)
    window_sweeps = [ts for ts in sweep_times if window_start <= pd.Timestamp(ts) <= window_end]
    exact_sweep = any(pd.Timestamp(ts) == timestamp for ts in sweep_times)
    htf_sweep_count = int(float(zone.get("htf_sweep_count", 0) or 0))
    htf_close_through_count = int(float(zone.get("htf_close_through_count", 0) or 0))
    htf_acceptance_count = int(float(zone.get("htf_acceptance_count", 0) or 0))
    consumed_or_chopped = str(zone.get("consumption_status", "")) in {"CONSUMED", "CHOPPED_THROUGH"}
    no_active_forward = str(zone.get("active_forward", "")).strip().lower() == "false"
    model_blind_spot = htf_sweep_count <= 0 and not sweep_times
    classification = (
        "HTF_STRUCTURAL_SWEEP"
        if htf_sweep_count > 0 or sweep_times
        else "model_blind_spot_htf_structure"
    )
    return "\n".join(
        [
            f"classification: {classification}",
            "h4_level_exists: true",
            "h4_level_source: structure_levels.csv" if not h4_levels.empty else "h4_level_source: liquidity_zone_registry.csv",
            "registry_zone_exists: true",
            f"zone_id: {zone_id}",
            f"h4_level_type: {_display(h4_level.get('level_type', zone.get('htf_level_type', '')))}",
            f"h4_origin_timestamp: {_display(zone.get('htf_origin_timestamp', h4_level.get('level_timestamp', '')))}",
            f"h4_origin_price: {_display(zone.get('htf_origin_price', h4_level.get('price', '')))}",
            f"h4_confirmation_timestamp: {_display(zone.get('htf_confirmation_timestamp', h4_level.get('created_at', '')))}",
            f"zone_bounds: {_display(zone.get('price_lower', ''))}-{_display(zone.get('price_upper', ''))}",
            f"source_timeframe_primary: {_display(zone.get('source_timeframe_primary', ''))}",
            f"source_timeframes: {_display(zone.get('source_timeframes', ''))}",
            f"htf_lifecycle_status: {_display(zone.get('htf_lifecycle_status', ''))}",
            f"m1_interaction_count: {_display(zone.get('m1_interaction_count', ''))}",
            f"htf_sweep_count: {htf_sweep_count}",
            f"htf_close_through_count: {htf_close_through_count}",
            f"htf_acceptance_count: {htf_acceptance_count}",
            f"sweep_importance_class: {_display(zone.get('sweep_importance_class', ''))}",
            f"first_sweep_at: {_display(zone.get('first_sweep_at', ''))}",
            f"sweep_times_for_zone: {'|'.join(sweep_times) if sweep_times else ''}",
            f"candidate_window_utc: {_format_ts(window_start)} to {_format_ts(window_end)}",
            f"sweep_inside_plus_minus_1h: {'true ' + '|'.join(window_sweeps) if window_sweeps else 'false'}",
            f"swept_at_exact_2026_03_29_2200: {_bool_text(exact_sweep)}",
            f"repeated_interaction_for_h4_level: false",
            f"consumed_or_chopped_for_h4_level: {_bool_text(consumed_or_chopped)}",
            f"no_active_forward_h4_zone: {_bool_text(no_active_forward)}",
            f"model_blind_spot_htf_structure: {_bool_text(model_blind_spot)}",
            "explanation: the 65,500 H4 low is audited as an HTF structural level. M1 touches are counted as m1_interaction_count only and do not become H4 resweeps.",
        ]
    )


def _broad_reaction_zones(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    mode = zones["structural_zone_mode"].astype(str) if "structural_zone_mode" in zones.columns else pd.Series([""] * len(zones), index=zones.index)
    role = zones["active_forward_role"].astype(str) if "active_forward_role" in zones.columns else pd.Series([""] * len(zones), index=zones.index)
    state = zones["zone_behavior_state"].astype(str) if "zone_behavior_state" in zones.columns else pd.Series(["NONE"] * len(zones), index=zones.index)
    mask = (
        mode.isin({"BROAD_STRUCTURAL_ZONE", "PATTERN_DERIVED_ZONE", "REACTION_ZONE"})
        & (
            role.isin({"REACTION_ZONE", "DISTRIBUTION_ZONE", "RETEST_ZONE", "AUDIT_ONLY"})
            | state.ne("NONE")
        )
    )
    return zones[mask].copy()


def _dedupe_zones(zones: pd.DataFrame) -> pd.DataFrame:
    if zones.empty or "zone_id" not in zones.columns:
        return zones.copy()
    return zones.drop_duplicates(subset=["zone_id"], keep="first").reset_index(drop=True)


def _annotate_zones_with_patterns(zones: pd.DataFrame, patterns: pd.DataFrame) -> pd.DataFrame:
    if zones.empty:
        return zones.copy()
    out = zones.copy()
    for column in ["pattern_id", "pattern_type", "pattern_role"]:
        if column not in out.columns:
            out[column] = ""
    if patterns.empty or "linked_zone_id" not in patterns.columns:
        return out
    pattern_by_zone = {
        str(row["linked_zone_id"]): row
        for _, row in patterns.iterrows()
        if str(row.get("linked_zone_id", ""))
    }
    for idx, row in out.iterrows():
        pattern = pattern_by_zone.get(str(row.get("zone_id", "")))
        if pattern is None:
            continue
        out.at[idx, "pattern_id"] = str(pattern.get("pattern_id", ""))
        out.at[idx, "pattern_type"] = str(pattern.get("pattern_type", ""))
        out.at[idx, "pattern_role"] = str(pattern.get("pattern_role", ""))
    return out


def _nearest_zones(zones: pd.DataFrame, price: float) -> tuple[pd.Series | None, pd.Series | None]:
    if zones.empty:
        return None, None
    lower_col = "zone_outer_lower" if "zone_outer_lower" in zones.columns else "price_lower"
    upper_col = "zone_outer_upper" if "zone_outer_upper" in zones.columns else "price_upper"
    above = zones[pd.to_numeric(zones[lower_col], errors="coerce") > price].copy()
    below = zones[pd.to_numeric(zones[upper_col], errors="coerce") < price].copy()
    nearest_above = above.assign(_distance=above[lower_col].astype(float) - price).sort_values("_distance").iloc[0] if not above.empty else None
    nearest_below = below.assign(_distance=price - below[upper_col].astype(float)).sort_values("_distance").iloc[0] if not below.empty else None
    return nearest_above, nearest_below


def _crossed_zones_at(zones: pd.DataFrame, candle: pd.Series) -> pd.DataFrame:
    if zones.empty:
        return zones
    rows = []
    for _, zone in zones.iterrows():
        if _cross_excursion(zone, candle) > 0:
            rows.append(zone)
    return pd.DataFrame(rows, columns=zones.columns)


def _cross_excursion(zone: pd.Series, candle: pd.Series) -> float:
    lower = _zone_outer_lower(zone)
    upper = _zone_outer_upper(zone)
    if str(zone.get("side", "")) == "BUY_SIDE":
        return max(0.0, float(candle["HiPrice"]) - upper)
    return max(0.0, lower - float(candle["LowPrice"]))


def _activity_passed(ctx: dict[str, float]) -> bool:
    return (
        float(ctx.get("volume_zscore", 0.0) or 0.0) >= SWEEP_ACTIVITY_ZSCORE_THRESHOLD
        or abs(float(ctx.get("delta_zscore", 0.0) or 0.0)) >= SWEEP_ACTIVITY_ZSCORE_THRESHOLD
        or abs(float(ctx.get("oi_change", 0.0) or 0.0)) > 0
    )


def _context_at(volume_delta: pd.DataFrame, timestamp: str) -> dict[str, float]:
    if volume_delta.empty or "timestamp" not in volume_delta.columns:
        return {"volume_zscore": 0.0, "delta_zscore": 0.0, "oi_change": 0.0}
    row = volume_delta[volume_delta["timestamp"].astype(str) == timestamp]
    if row.empty:
        return {"volume_zscore": 0.0, "delta_zscore": 0.0, "oi_change": 0.0}
    first = row.iloc[0]
    return {
        "volume_zscore": float(first.get("volume_zscore", 0.0) or 0.0),
        "delta_zscore": float(first.get("delta_zscore", 0.0) or 0.0),
        "oi_change": float(first.get("oi_change", 0.0) or 0.0),
    }


def _aggregate_feed(feed: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    frame = feed.copy()
    if frame.empty or timeframe == "M1":
        return frame.reset_index(drop=True)
    rule = {"M5": "5min", "M15": "15min"}[timeframe]
    frame = frame.set_index("Timestamp").sort_index()
    agg = frame.resample(rule).agg(
        {
            "OpenPrice": "first",
            "HiPrice": "max",
            "LowPrice": "min",
            "ClosePrice": "last",
            "TotalQty": "sum",
            "Trades": "sum",
            "BuyQty": "sum",
            "SellQty": "sum",
            "OpenInterest": "last",
            "FundingRate": "last",
            **({"LiqBuyQty": "sum", "LiqSellQty": "sum"} if {"LiqBuyQty", "LiqSellQty"}.issubset(frame.columns) else {}),
        }
    ).dropna(subset=["OpenPrice", "HiPrice", "LowPrice", "ClosePrice"])
    return agg.reset_index()


def _slice_feed(feed: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return feed[(feed["Timestamp"] >= start) & (feed["Timestamp"] <= end)].copy()


def _events_for_window(events: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if events.empty or "event_timestamp" not in events.columns:
        return events.copy()
    ts = events["event_timestamp"].map(pd.Timestamp)
    return events[(ts >= start) & (ts <= end)].copy()


def _labels_for_events(labels: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if labels.empty or events.empty or "market_move_id" not in labels.columns:
        return labels.iloc[0:0].copy()
    move_ids = set(events["market_move_id"].fillna("").astype(str)) - {""}
    return labels[labels["market_move_id"].astype(str).isin(move_ids)].copy()


def _levels_for_window(levels: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if levels.empty:
        return levels.copy()
    timestamp_column = "level_timestamp" if "level_timestamp" in levels.columns else "timestamp"
    if timestamp_column not in levels.columns:
        return levels.copy()
    ts = levels[timestamp_column].map(pd.Timestamp)
    return levels[(ts >= start) & (ts <= end)].copy()


def _levels_for_zone_sources(levels: pd.DataFrame, zones: pd.DataFrame) -> pd.DataFrame:
    if levels.empty or zones.empty or "level_id" not in levels.columns:
        return levels.iloc[0:0].copy()
    ids: set[str] = set()
    for value in zones.get("source_level_ids", []):
        ids.update(_pipe_values(str(value)))
    if not ids:
        return levels.iloc[0:0].copy()
    return levels[levels["level_id"].astype(str).isin(ids)].copy()


def _nearest_feed_row(feed: pd.DataFrame, ts: pd.Timestamp) -> pd.Series:
    exact = feed[feed["Timestamp"] == ts]
    if not exact.empty:
        return exact.iloc[0]
    before = feed[feed["Timestamp"] <= ts]
    if not before.empty:
        return before.iloc[-1]
    return feed.iloc[0]


def _source_reference_warning(zones: pd.DataFrame) -> str:
    if zones.empty:
        return '<div class="notice">Source level references unavailable because no zones are in this view.</div>'
    return '<div class="notice">Source level references are not globally qualified yet.</div>'


def _liquidation_message(feed_has_liquidations: bool) -> str:
    if feed_has_liquidations:
        return '<div class="notice">Liquidation fields LiqBuyQty/LiqSellQty are shown when nonzero.</div>'
    return '<div class="notice">Liquidation fields unavailable for this feed/day.</div>'


def _try_write_png_fallback(html_files: list[Path]) -> list[Path]:
    try:
        import matplotlib.pyplot as plt  # type: ignore
    except Exception:
        return []
    written: list[Path] = []
    for html_path in html_files:
        if html_path.suffix.lower() != ".html":
            continue
        png_path = html_path.with_suffix(".png")
        fig = plt.figure(figsize=(10, 2))
        fig.text(0.02, 0.55, f"Static visual artifact: {html_path.name}", fontsize=12)
        fig.text(0.02, 0.35, "Open the HTML file for the full audit overlay.", fontsize=10)
        fig.savefig(png_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        written.append(png_path)
    return written


def _manifest_columns() -> list[str]:
    return ["artifact_type", "path", "market_move_id", "label", "summary", "what_was_swept"]


def _manifest_row(artifact_type: str, path: Path, summary: dict[str, str]) -> dict[str, str]:
    return {
        "artifact_type": artifact_type,
        "path": str(path),
        "market_move_id": summary.get("market_move_id", ""),
        "label": summary.get("label", ""),
        "summary": summary.get("summary", ""),
        "what_was_swept": summary.get("what_was_swept", ""),
    }


def _markdown_zone_list(zones: pd.DataFrame) -> str:
    if zones.empty:
        return "No zones."
    lines = []
    for _, zone in zones.head(20).iterrows():
        value = lambda key: _display(zone.get(key, ""))
        lines.append(
            f"- {value('zone_id')} {value('side')} {value('price_lower')}-{value('price_upper')} "
            f"{value('status')} {value('precision_status')} {value('confidence_tier')} "
            f"mode={value('structural_zone_mode')} behavior={value('zone_behavior_state')} "
            f"role={value('active_forward_role')} outer={value('zone_outer_lower')}-{value('zone_outer_upper')} "
            f"core={value('zone_core_lower')}-{value('zone_core_upper')} first_sweep_at={value('first_sweep_at')} "
            f"resweeps={value('resweep_count')} failed_acceptances={value('failed_acceptance_count')} "
            f"primary={value('source_timeframe_primary')} htf_type={value('htf_level_type')} "
            f"htf_origin={value('htf_origin_timestamp')} htf_price={value('htf_origin_price')} "
            f"htf_status={value('htf_lifecycle_status')} m1_interactions={value('m1_interaction_count')} "
            f"htf_sweeps={value('htf_sweep_count')} htf_closes={value('htf_close_through_count')} "
            f"htf_acceptances={value('htf_acceptance_count')} importance={value('sweep_importance_class')} "
            f"sources={value('source_timeframes')} source_level_ids={value('source_level_ids')}"
        )
    return "\n".join(lines)


def _markdown_zone_one(zone: pd.Series | None) -> str:
    if zone is None or zone.empty:
        return "none"
    value = lambda key: _display(zone.get(key, ""))
    return (
        f"{value('zone_id')} {value('side')} {value('price_lower')}-{value('price_upper')} "
        f"mode={value('structural_zone_mode')} behavior={value('zone_behavior_state')} "
        f"role={value('active_forward_role')} primary={value('source_timeframe_primary')} "
        f"htf_status={value('htf_lifecycle_status')} importance={value('sweep_importance_class')}"
    )


def _markdown_as_html(markdown: str) -> str:
    return "<pre>" + html.escape(markdown) + "</pre>"


def _css() -> str:
    return """
body { font-family: Arial, sans-serif; margin: 20px; color: #111827; background: #f8fafc; }
h1 { font-size: 24px; margin: 0 0 16px; }
h2 { font-size: 18px; margin: 18px 0 8px; }
h3 { font-size: 14px; margin: 14px 0 6px; }
.panel { background: #ffffff; border: 1px solid #d1d5db; padding: 14px; margin-bottom: 14px; }
.notice { padding: 8px 10px; background: #f1f5f9; border-left: 3px solid #64748b; margin: 8px 0; }
table { border-collapse: collapse; width: 100%; font-size: 12px; margin: 8px 0 14px; }
th, td { border: 1px solid #d1d5db; padding: 4px 6px; text-align: left; vertical-align: top; }
th { background: #e5e7eb; }
pre { white-space: pre-wrap; background: #f8fafc; border: 1px solid #d1d5db; padding: 10px; }
svg { width: 100%; height: auto; border: 1px solid #e5e7eb; }
"""


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _csv_has_columns(path: Path, columns: set[str]) -> bool:
    header = pd.read_csv(path, nrows=0).columns
    return columns.issubset(set(header))


def _one_row(frame: pd.DataFrame, column: str, value: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=object)
    found = frame[frame[column].astype(str) == str(value)]
    if found.empty:
        return pd.Series(dtype=object)
    return found.iloc[0]


def _pipe_values(value: str) -> list[str]:
    return [part for part in str(value).split("|") if part]


def _created_before(zone: pd.Series, event: pd.Series) -> str:
    if zone.empty or event.empty:
        return "unknown"
    return "yes" if pd.Timestamp(zone.get("first_seen_at")) < pd.Timestamp(event.get("event_timestamp")) else "no"


def _active_forward_before(zone: pd.Series, event: pd.Series) -> str:
    if zone.empty or event.empty:
        return "unknown"
    if pd.Timestamp(zone.get("first_seen_at")) >= pd.Timestamp(event.get("event_timestamp")):
        return "false"
    if str(zone.get("consumption_status", "")) in INACTIVE_CONSUMPTION_STATUSES:
        consumed_at = str(zone.get("consumed_at", "") or "")
        if not consumed_at or pd.Timestamp(consumed_at) <= pd.Timestamp(event.get("event_timestamp")):
            return "false"
    if str(zone.get("status", "")) in {"EXPIRED", "MERGED"}:
        return "false"
    return "true"


def _structure_note(zone: pd.Series) -> str:
    if _is_htf_zone(zone):
        return (
            "HTF structural liquidity level: "
            f"primary={_display(zone.get('source_timeframe_primary', ''))}; "
            f"htf_level_type={_display(zone.get('htf_level_type', ''))}; "
            f"origin={_display(zone.get('htf_origin_timestamp', ''))}; "
            f"origin_price={_display(zone.get('htf_origin_price', ''))}; "
            f"confirmation={_display(zone.get('htf_confirmation_timestamp', ''))}; "
            f"lifecycle={_display(zone.get('htf_lifecycle_status', ''))}; "
            f"m1_interaction_count={_display(zone.get('m1_interaction_count', ''))}; "
            f"htf_sweep_count={_display(zone.get('htf_sweep_count', ''))}; "
            f"htf_close_through_count={_display(zone.get('htf_close_through_count', ''))}; "
            f"htf_acceptance_count={_display(zone.get('htf_acceptance_count', ''))}."
        )
    if _is_m15_zone(zone):
        return (
            "M15 minimum structure level: "
            f"primary={_display(zone.get('source_timeframe_primary', ''))}; "
            f"source={_display(zone.get('source_timeframes', ''))}; "
            f"lifecycle={_display(zone.get('htf_lifecycle_status', ''))}; "
            f"first_sweep_at={_display(zone.get('first_sweep_at', ''))}; "
            f"resweep_count={_display(zone.get('resweep_count', ''))}; "
            f"active_forward_role={_display(zone.get('active_forward_role', ''))}."
        )
    if _is_broad_zone(zone):
        return (
            "Broad structural liquidity zone: "
            f"outer: {_zone_outer_lower(zone)} - {_zone_outer_upper(zone)}; "
            f"core: {_zone_core_lower(zone)} - {_zone_core_upper(zone)}; "
            f"origin: {_display(zone.get('zone_origin_start', ''))} - {_display(zone.get('zone_origin_end', ''))}; "
            f"first_sweep_at: {_display(zone.get('first_sweep_at', ''))}; "
            f"resweep_count: {_display(zone.get('resweep_count', ''))}; "
            f"failed_acceptance_count: {_display(zone.get('failed_acceptance_count', ''))}; "
            f"zone_behavior_state: {_display(zone.get('zone_behavior_state', ''))}; "
            f"active_forward_role: {_display(zone.get('active_forward_role', ''))}."
        )
    return "Thin/session-only local level: not a broad structural zone."


def _weak_local_badge(zone: pd.Series) -> str:
    if _is_htf_zone(zone):
        return "HTF_STRUCTURAL_LEVEL. M1 touches are context only. "
    if _is_m15_zone(zone):
        return "M15_MINIMUM_STRUCTURE. M1 touches are context only. "
    if str(zone.get("sweep_importance_class", "") or "") == "MICRO_SWEEP":
        return "MICRO_SWEEP. M1/local context only, not a structural sweep. "
    sources = set(str(zone.get("source_timeframes", "")).split("|"))
    if str(zone.get("confidence_tier", "")) == "LOW" or sources == {"SESSION"}:
        return "LOW_CONFIDENCE_LOCAL_SWEEP. SESSION-only source. Not a high-priority structural sweep. "
    return ""


def _label_value(labels: pd.DataFrame) -> str:
    if labels.empty:
        return ""
    return str(labels.iloc[0].get("label", ""))


def _date_token(feed: pd.DataFrame) -> str:
    if feed.empty:
        return "unknown_date"
    return pd.Timestamp(feed["Timestamp"].min()).strftime("%Y-%m-%d")


def _compact_minute(timestamp: str) -> str:
    return pd.Timestamp(timestamp).strftime("%Y%m%d_%H%M")


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _display(value) -> str:
    if _is_missing(value):
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _clean_text(value) -> str:
    if _is_missing(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _event_marker_price(event: pd.Series, fallback: float) -> float:
    for key in ["event_close", "event_high", "event_low"]:
        value = event.get(key)
        if _is_missing(value):
            continue
        return float(value)
    return float(fallback)


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    return str(value) == ""


def _numeric_min(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return float("inf")
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.min()) if not values.empty else float("inf")


def _numeric_max(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return float("-inf")
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.max()) if not values.empty else float("-inf")


def _zone_color(zone: pd.Series) -> str:
    if str(zone.get("consumption_status", "")) in {"CONSUMED", "CHOPPED_THROUGH"}:
        return "#6b7280"
    if str(zone.get("status", "")) == "EXPIRED":
        return "#9ca3af"
    if _is_htf_zone(zone):
        return "#b91c1c"
    if _is_m15_zone(zone):
        return "#0891b2"
    if str(zone.get("zone_behavior_state", "")) in {"DISTRIBUTION_CANDIDATE", "FAILED_ACCEPTANCE"}:
        return "#be123c"
    if str(zone.get("zone_behavior_state", "")) in {"REJECTION_FROM_ZONE", "DRIFT_AWAY_FROM_ZONE"}:
        return "#0f766e"
    if str(zone.get("pattern_type", "")):
        return "#9333ea"
    if _is_broad_zone(zone):
        return "#7c2d12"
    return "#d97706" if str(zone.get("side", "")) == "BUY_SIDE" else "#2563eb"


def _zone_opacity(zone: pd.Series) -> str:
    if str(zone.get("consumption_status", "")) in {"CONSUMED", "CHOPPED_THROUGH"}:
        return "0.10"
    if str(zone.get("precision_status", "")) == "LOW_PRECISION":
        return "0.12"
    return "0.20"


def _zone_dash(zone: pd.Series) -> str:
    if str(zone.get("consumption_status", "")) in {"CONSUMED", "CHOPPED_THROUGH"}:
        return "2 5"
    if _is_htf_zone(zone):
        return "1 0"
    if _is_m15_zone(zone):
        return "3 2"
    if str(zone.get("status", "")) == "EXPIRED" or str(zone.get("precision_status", "")) == "LOW_PRECISION":
        return "6 4"
    return "4 3"


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _bool_text(value) -> str:
    return "true" if _bool_value(value) else "false"


def _is_local_context_forward_zone(zone: pd.Series) -> bool:
    role = _clean_text(zone.get("active_forward_role", "") or "FRESH_LIQUIDITY")
    if role in LOCAL_CONTEXT_ACTIVE_FORWARD_ROLES:
        return True
    return role == "FRESH_LIQUIDITY" and bool(local_session_context_role(zone))


def _is_htf_zone(zone: pd.Series) -> bool:
    primary = _clean_text(zone.get("source_timeframe_primary", ""))
    source_timeframes = {part for part in _clean_text(zone.get("source_timeframes", "")).split("|") if part}
    sweep_class = _clean_text(zone.get("sweep_importance_class", ""))
    return (
        bool(_clean_text(zone.get("htf_level_type", "")))
        or primary in {"H1", "H4"}
        or bool({"H1", "H4"} & source_timeframes)
        or sweep_class.startswith("HTF_STRUCTURAL")
    )


def _is_m15_zone(zone: pd.Series) -> bool:
    if _is_htf_zone(zone):
        return False
    primary = _clean_text(zone.get("source_timeframe_primary", ""))
    source_timeframes = {part for part in _clean_text(zone.get("source_timeframes", "")).split("|") if part}
    sweep_class = _clean_text(zone.get("sweep_importance_class", ""))
    role = _clean_text(zone.get("active_forward_role", ""))
    lifecycle = _clean_text(zone.get("htf_lifecycle_status", ""))
    zone_type = _clean_text(zone.get("zone_type", ""))
    return (
        primary == "M15"
        or "M15" in source_timeframes
        or sweep_class.startswith("M15_")
        or role.startswith("M15_")
        or lifecycle.startswith("M15_")
        or zone_type.startswith("M15_")
    )


def _is_local_session_zone(zone: pd.Series) -> bool:
    if _is_htf_zone(zone):
        return False
    if _is_m15_zone(zone):
        return False
    primary = _clean_text(zone.get("source_timeframe_primary", ""))
    source_timeframes = {part for part in _clean_text(zone.get("source_timeframes", "")).split("|") if part}
    sweep_class = _clean_text(zone.get("sweep_importance_class", ""))
    structural_mode = _clean_text(zone.get("structural_zone_mode", ""))
    return (
        primary == "SESSION"
        or source_timeframes == {"SESSION"}
        or sweep_class.startswith("LOCAL_SESSION")
        or structural_mode == "PATTERN_DERIVED_ZONE"
    )


def _h4_levels_near(structure_levels: pd.DataFrame, target_price: float, tolerance: float) -> pd.DataFrame:
    if structure_levels.empty:
        return structure_levels.copy()
    frame = structure_levels.copy()
    timeframe_column = "timeframe" if "timeframe" in frame.columns else "source_timeframe"
    if timeframe_column not in frame.columns or "price" not in frame.columns:
        return frame.iloc[0:0].copy()
    prices = pd.to_numeric(frame["price"], errors="coerce")
    side = frame["side"].astype(str) if "side" in frame.columns else pd.Series([""] * len(frame), index=frame.index)
    mask = (
        frame[timeframe_column].astype(str).eq("H4")
        & side.eq("SELL_SIDE")
        & prices.sub(target_price).abs().le(tolerance)
    )
    out = frame[mask].copy()
    if out.empty:
        return out
    out["_distance"] = pd.to_numeric(out["price"], errors="coerce").sub(target_price).abs()
    sort_columns = ["_distance"]
    if "level_timestamp" in out.columns:
        sort_columns.append("level_timestamp")
    return out.sort_values(sort_columns, kind="mergesort").drop(columns=["_distance"])


def _h4_registry_zones_near(registry: pd.DataFrame, target_price: float, tolerance: float) -> pd.DataFrame:
    if registry.empty:
        return registry.copy()
    frame = registry.copy()
    h4_mask = frame.apply(_is_h4_registry_zone, axis=1)
    prices = pd.to_numeric(frame.get("htf_origin_price", frame.get("price_mid", 0)), errors="coerce")
    mids = pd.to_numeric(frame.get("price_mid", 0), errors="coerce")
    price_mask = prices.sub(target_price).abs().le(tolerance) | mids.sub(target_price).abs().le(tolerance)
    side = frame["side"].astype(str) if "side" in frame.columns else pd.Series([""] * len(frame), index=frame.index)
    side_mask = side.eq("SELL_SIDE")
    out = frame[h4_mask & price_mask & side_mask].copy()
    if out.empty:
        return out
    out["_distance"] = pd.to_numeric(
        out.get("htf_origin_price", out.get("price_mid", 0)), errors="coerce"
    ).fillna(pd.to_numeric(out.get("price_mid", 0), errors="coerce")).sub(target_price).abs()
    return out.sort_values(["_distance", "first_seen_at", "zone_id"], kind="mergesort").drop(columns=["_distance"])


def _is_h4_registry_zone(zone: pd.Series) -> bool:
    primary = _clean_text(zone.get("source_timeframe_primary", ""))
    source_timeframes = {part for part in _clean_text(zone.get("source_timeframes", "")).split("|") if part}
    htf_level_type = _clean_text(zone.get("htf_level_type", ""))
    return primary == "H4" or "H4" in source_timeframes or htf_level_type.startswith("H4_")


def _zone_sweep_times(zone: pd.Series, event_log: pd.DataFrame) -> list[str]:
    times: list[str] = []
    first_sweep_at = str(zone.get("first_sweep_at", "") or "")
    if first_sweep_at:
        times.append(_format_ts(first_sweep_at))
    if not event_log.empty and "zone_id" in event_log.columns and "event_timestamp" in event_log.columns:
        zone_events = event_log[
            (event_log["zone_id"].astype(str) == str(zone.get("zone_id", "")))
            & event_log["event_type"].astype(str).isin(
                {"LIQUIDITY_SWEEP_UNRESOLVED", "LIQUIDITY_ZONE_CROSSED_UNCLASSIFIED"}
            )
        ]
        times.extend(_format_ts(value) for value in zone_events["event_timestamp"].astype(str))
    return sorted(dict.fromkeys(times))


def _is_broad_zone(zone: pd.Series) -> bool:
    return str(zone.get("structural_zone_mode", "")) in {
        "BROAD_STRUCTURAL_ZONE",
        "PATTERN_DERIVED_ZONE",
        "REACTION_ZONE",
    }


def _zone_outer_lower(zone: pd.Series) -> float:
    return float(zone.get("zone_outer_lower", zone.get("price_lower", 0)) or zone.get("price_lower", 0))


def _zone_outer_upper(zone: pd.Series) -> float:
    return float(zone.get("zone_outer_upper", zone.get("price_upper", 0)) or zone.get("price_upper", 0))


def _zone_core_lower(zone: pd.Series) -> float:
    return float(zone.get("zone_core_lower", zone.get("price_lower", 0)) or zone.get("price_lower", 0))


def _zone_core_upper(zone: pd.Series) -> float:
    return float(zone.get("zone_core_upper", zone.get("price_upper", 0)) or zone.get("price_upper", 0))


def _zone_label(zone: pd.Series) -> str:
    return (
        f"{zone.get('zone_id', '')} {zone.get('side', '')} {zone.get('zone_type', '')} "
        f"bounds={zone.get('price_lower', '')}-{zone.get('price_upper', '')} "
        f"outer={zone.get('zone_outer_lower', '')}-{zone.get('zone_outer_upper', '')} "
        f"core={zone.get('zone_core_lower', '')}-{zone.get('zone_core_upper', '')} "
        f"mid={zone.get('price_mid', '')} precision_status={zone.get('precision_status', '')} "
        f"confidence_tier={zone.get('confidence_tier', '')} consumption_status={zone.get('consumption_status', '')} "
        f"structural_zone_mode={zone.get('structural_zone_mode', '')} zone_behavior_state={zone.get('zone_behavior_state', '')} "
        f"active_forward_role={zone.get('active_forward_role', '')} "
        f"active_forward={zone.get('active_forward', '')} pattern_type={zone.get('pattern_type', '')} "
        f"primary={zone.get('source_timeframe_primary', '')} sources={zone.get('source_timeframes', '')} "
        f"htf_level_type={zone.get('htf_level_type', '')} htf_origin={zone.get('htf_origin_timestamp', '')} "
        f"htf_status={zone.get('htf_lifecycle_status', '')} m1_interactions={zone.get('m1_interaction_count', '')} "
        f"htf_sweeps={zone.get('htf_sweep_count', '')} importance={zone.get('sweep_importance_class', '')}"
    )


def _event_title(event: pd.Series) -> str:
    return (
        f"{event.get('event_timestamp', '')} {event.get('event_type', '')} "
        f"market_move_id={event.get('market_move_id', '')} zone_id={event.get('zone_id', '')} "
        f"excursion_abs={event.get('excursion_abs', '')} volume_zscore={event.get('volume_zscore', '')} "
        f"delta_zscore={event.get('delta_zscore', '')} oi_change={event.get('oi_change', '')}"
    )
