from __future__ import annotations

import html
import json
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd
from PIL import Image, ImageDraw, ImageFont


RENDERER_VERSION = "SHI_RESET_36C_TRADER_SNAPSHOT_BUILDER_V0"
HTML_OUTPUT = "trader_snapshot.html"
SVG_OUTPUT = "trader_snapshot.svg"
PNG_OUTPUT = "trader_snapshot.png"
MANIFEST_OUTPUT = "trader_snapshot_manifest.json"
RENDERED_ZONES_OUTPUT = "rendered_zones.csv"
STATE_OUTPUT = "snapshot_state.json"

WIDTH = 1600
HEIGHT = 980
CHART_X = 70
CHART_Y = 72
CHART_W = 1040
CHART_H = 555
PANEL_X = 1140
PANEL_Y = 72
PANEL_W = 390
TABLE_Y = 675
TABLE_H = 245
MAX_VISIBLE_ZONES = 7

RENDERED_ZONE_COLUMNS = [
    "rank",
    "zone_id",
    "side",
    "bucket",
    "source_timeframe",
    "source_family",
    "price_lower",
    "price_upper",
    "representative_price",
    "current_price",
    "distance_to_current_price_pct",
    "significance_score",
    "reason_selected",
    "visible_on_snapshot",
]


class TraderSnapshotBuilderError(RuntimeError):
    """Raised when a trader snapshot cannot be rendered from accepted inputs."""


@dataclass(frozen=True)
class TraderSnapshotResult:
    output_dir: Path
    html_path: Path
    svg_path: Path
    png_path: Path
    manifest_path: Path
    rendered_zones_path: Path
    state_path: Path


def build_trader_snapshot(
    *,
    start: str | date,
    end: str | date,
    selected_zones_path: str | Path,
    input_root: str | Path,
    feed_dir: str | Path,
    output_dir: str | Path,
) -> TraderSnapshotResult:
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date > end_date:
        raise TraderSnapshotBuilderError("start must be <= end")

    selected_path = Path(selected_zones_path)
    input_root_path = Path(input_root)
    feed_root = Path(feed_dir)
    out_dir = Path(output_dir)
    if not selected_path.exists():
        raise TraderSnapshotBuilderError(f"selected_zones.csv not found: {selected_path}")
    if not input_root_path.exists():
        raise TraderSnapshotBuilderError(f"input root not found: {input_root_path}")
    if not feed_root.exists():
        raise TraderSnapshotBuilderError(f"feed dir not found: {feed_root}")
    out_dir.mkdir(parents=True, exist_ok=True)

    selected = pd.read_csv(selected_path)
    _validate_selected_zones(selected, selected_path)
    rendered_zones = _visible_zones(selected)
    price_path = _load_price_path(feed_root, start_date, end_date)
    current_price = float(price_path["Close"].iloc[-1])
    missing_flags = _missing_data_flags(selected)
    state = _snapshot_state(
        start_date=start_date,
        end_date=end_date,
        current_price=current_price,
        rendered_zones=rendered_zones,
        missing_flags=missing_flags,
    )

    rendered_zones_path = out_dir / RENDERED_ZONES_OUTPUT
    rendered_zones[RENDERED_ZONE_COLUMNS].to_csv(rendered_zones_path, index=False)

    svg_text = _render_svg(price_path, rendered_zones, state)
    html_text = _render_html(svg_text, state, rendered_zones)
    svg_path = out_dir / SVG_OUTPUT
    html_path = out_dir / HTML_OUTPUT
    png_path = out_dir / PNG_OUTPUT
    state_path = out_dir / STATE_OUTPUT
    manifest_path = out_dir / MANIFEST_OUTPUT
    svg_path.write_text(svg_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    _render_png(price_path, rendered_zones, state, png_path)

    state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "renderer_version": RENDERER_VERSION,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "input_selected_zones": str(selected_path),
        "input_root": str(input_root_path),
        "feed_dir": str(feed_root),
        "selected_visible_count": int(len(rendered_zones)),
        "no_hidden_zones_rendered": True,
        "repo_commit": _repo_commit(),
        "outputs": {
            "trader_snapshot_html": str(html_path),
            "trader_snapshot_svg": str(svg_path),
            "trader_snapshot_png": str(png_path),
            "trader_snapshot_manifest_json": str(manifest_path),
            "rendered_zones_csv": str(rendered_zones_path),
            "snapshot_state_json": str(state_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    return TraderSnapshotResult(
        output_dir=out_dir,
        html_path=html_path,
        svg_path=svg_path,
        png_path=png_path,
        manifest_path=manifest_path,
        rendered_zones_path=rendered_zones_path,
        state_path=state_path,
    )


def _validate_selected_zones(frame: pd.DataFrame, path: Path) -> None:
    required = set(RENDERED_ZONE_COLUMNS)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise TraderSnapshotBuilderError(f"{path} missing required columns: {', '.join(missing)}")


def _visible_zones(selected: pd.DataFrame) -> pd.DataFrame:
    visible = selected[selected["visible_on_snapshot"].astype(str).str.lower() == "true"].copy()
    if len(visible) > MAX_VISIBLE_ZONES:
        raise TraderSnapshotBuilderError(f"selected visible zones exceeds {MAX_VISIBLE_ZONES}: {len(visible)}")
    if visible.empty:
        raise TraderSnapshotBuilderError("selected_zones.csv has no visible_on_snapshot=true rows")
    for column in ["price_lower", "price_upper", "representative_price", "significance_score"]:
        visible[column] = pd.to_numeric(visible[column], errors="coerce")
    if visible[["price_lower", "price_upper", "representative_price"]].isna().any().any():
        raise TraderSnapshotBuilderError("visible selected zones contain missing price fields")
    return visible.sort_values(["rank", "zone_id"], kind="mergesort").reset_index(drop=True)


def _load_price_path(feed_dir: Path, start_date: date, end_date: date) -> pd.DataFrame:
    frames = []
    for day in _date_range(start_date, end_date):
        path = feed_dir / f"{day.isoformat()}.csv"
        if not path.exists():
            raise TraderSnapshotBuilderError(f"missing feed file: {path}")
        frame = pd.read_csv(path)
        required = {"Timestamp", "Open", "High", "Low", "Close"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise TraderSnapshotBuilderError(f"{path} missing price columns: {', '.join(missing)}")
        frame = frame[["Timestamp", "Open", "High", "Low", "Close"]].copy()
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
        for column in ["Open", "High", "Low", "Close"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["Timestamp", "Open", "High", "Low", "Close"])
        if frame.empty:
            raise TraderSnapshotBuilderError(f"{path} has no usable price rows")
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("Timestamp", kind="mergesort").reset_index(drop=True)
    if out.empty:
        raise TraderSnapshotBuilderError("no usable price data loaded")
    return out


def _missing_data_flags(selected: pd.DataFrame) -> dict[str, str]:
    text = "|".join(selected.get("evidence_fields_missing", pd.Series(dtype=str)).fillna("").astype(str)).lower()
    flags = {}
    for key in ["liquidations", "vwap", "compression"]:
        flags[key] = "not_available" if f"{key}=not_available" in text else "available_or_not_reported"
    return flags


def _snapshot_state(
    *,
    start_date: date,
    end_date: date,
    current_price: float,
    rendered_zones: pd.DataFrame,
    missing_flags: dict[str, str],
) -> dict[str, object]:
    buy_rows = rendered_zones[rendered_zones["side"] == "BUY_SIDE"]
    sell_rows = rendered_zones[rendered_zones["side"] == "SELL_SIDE"]
    nearest_buy = _nearest_zone(buy_rows, current_price)
    nearest_sell = _nearest_zone(sell_rows, current_price)
    nearest_above = _nearest_above(rendered_zones, current_price)
    nearest_below = _nearest_below(rendered_zones, current_price)
    zone_front = {
        "above_price": nearest_above or "not_available_from_selected_zones",
        "below_price": nearest_below or "not_available_from_selected_zones",
    }
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "current_price": round(current_price, 4),
        "visible_zone_count": int(len(rendered_zones)),
        "buy_side_visible_count": int((rendered_zones["side"] == "BUY_SIDE").sum()),
        "sell_side_visible_count": int((rendered_zones["side"] == "SELL_SIDE").sum()),
        "nearest_buy_side_zone": nearest_buy or "not_available_from_selected_zones",
        "nearest_sell_side_zone": nearest_sell or "not_available_from_selected_zones",
        "nearest_above_price_zone": nearest_above or "not_available_from_selected_zones",
        "nearest_below_price_zone": nearest_below or "not_available_from_selected_zones",
        "zone_in_front_of_price": zone_front,
        "missing_data_flags": missing_flags,
        "forbidden_trade_fields_absent": True,
    }


def _nearest_zone(frame: pd.DataFrame, current_price: float) -> dict[str, object] | None:
    if frame.empty:
        return None
    distances = (frame["representative_price"].astype(float) - current_price).abs()
    row = frame.loc[distances.sort_values(kind="mergesort").index[0]]
    return _zone_ref(row)


def _nearest_above(frame: pd.DataFrame, current_price: float) -> dict[str, object] | None:
    above = frame[frame["price_lower"].astype(float) > current_price]
    if above.empty:
        return None
    row = above.sort_values(["price_lower", "rank"], kind="mergesort").iloc[0]
    return _zone_ref(row)


def _nearest_below(frame: pd.DataFrame, current_price: float) -> dict[str, object] | None:
    below = frame[frame["price_upper"].astype(float) < current_price]
    if below.empty:
        return None
    row = below.sort_values(["price_upper", "rank"], ascending=[False, True], kind="mergesort").iloc[0]
    return _zone_ref(row)


def _zone_ref(row: pd.Series) -> dict[str, object]:
    return {
        "rank": int(row["rank"]),
        "zone_id": str(row["zone_id"]),
        "side": str(row["side"]),
        "bucket": str(row["bucket"]),
        "representative_price": round(float(row["representative_price"]), 4),
        "price_lower": round(float(row["price_lower"]), 4),
        "price_upper": round(float(row["price_upper"]), 4),
        "distance_to_current_price_pct": round(float(row["distance_to_current_price_pct"]), 4),
    }


def _render_svg(price_path: pd.DataFrame, zones: pd.DataFrame, state: dict[str, object]) -> str:
    scale = _scale(price_path, zones)
    points = _decimated_points(price_path, max_points=520)
    polyline = " ".join(f"{_x(i, len(points)):.1f},{scale(float(row.Close)):.1f}" for i, row in enumerate(points.itertuples()))
    current_y = scale(float(state["current_price"]))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="1600" height="980" fill="#f7f8fa"/>',
        '<text x="70" y="36" font-family="Arial" font-size="24" font-weight="700" fill="#17202a">SHI_RESET_36C Trader Snapshot Research</text>',
        f'<text x="70" y="58" font-family="Arial" font-size="13" fill="#5f6b7a">{state["start"]} to {state["end"]} | research monitor snapshot, not trading advice</text>',
        f'<rect x="{CHART_X}" y="{CHART_Y}" width="{CHART_W}" height="{CHART_H}" fill="#ffffff" stroke="#b8c0cc"/>',
    ]
    parts.extend(_price_grid_svg(scale))
    parts.extend(_zone_svg(zones, scale))
    parts.append(f'<polyline points="{polyline}" fill="none" stroke="#1f2937" stroke-width="2"/>')
    parts.append(f'<line x1="{CHART_X}" x2="{CHART_X + CHART_W}" y1="{current_y:.1f}" y2="{current_y:.1f}" stroke="#111827" stroke-width="1.5" stroke-dasharray="6 5"/>')
    parts.append(f'<text x="{CHART_X + CHART_W - 150}" y="{current_y - 7:.1f}" font-family="Arial" font-size="12" fill="#111827">current {float(state["current_price"]):.1f}</text>')
    parts.extend(_right_panel_svg(state))
    parts.extend(_bottom_table_svg(zones))
    parts.append("</svg>")
    return "\n".join(parts)


def _render_html(svg_text: str, state: dict[str, object], zones: pd.DataFrame) -> str:
    zone_notes = "\n".join(
        f"<li>#{int(row.rank)} {html.escape(str(row.side))} {html.escape(str(row.bucket))}: "
        f"{html.escape(_short(row.reason_selected, 130))} | flow: "
        f"{html.escape(_short(getattr(row, 'flow_evidence_summary', 'not_available'), 130))}</li>"
        for row in zones.itertuples()
    )
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8"/>',
            "<title>SHI_RESET_36C Trader Snapshot Research</title>",
            "<style>body{margin:0;background:#eef1f5;font-family:Arial,sans-serif;color:#17202a}.wrap{width:1600px;margin:0 auto;background:#f7f8fa}.notes{padding:0 70px 32px 70px;font-size:13px;line-height:1.35}.notes h2{font-size:16px;margin:12px 0 6px}.notes ul{columns:2;margin-top:6px}</style>",
            "</head>",
            "<body>",
            '<div class="wrap">',
            svg_text,
            '<div class="notes">',
            "<h2>Selected Zone Evidence Notes</h2>",
            f"<ul>{zone_notes}</ul>",
            "<p>Research monitor snapshot, not trading advice. Hidden selector rows are retained in selected_zones.csv but are not drawn on the main chart.</p>",
            "</div>",
            "</div>",
            "</body>",
            "</html>",
        ]
    )


def _render_png(price_path: pd.DataFrame, zones: pd.DataFrame, state: dict[str, object], path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    scale = _scale(price_path, zones)
    points = _decimated_points(price_path, max_points=520)
    draw.text((70, 20), "SHI_RESET_36C Trader Snapshot Research", fill="#17202a", font=font)
    draw.text((70, 44), f"{state['start']} to {state['end']} | research monitor snapshot, not trading advice", fill="#5f6b7a", font=font)
    draw.rectangle([CHART_X, CHART_Y, CHART_X + CHART_W, CHART_Y + CHART_H], fill="#ffffff", outline="#b8c0cc")
    zone_rows = list(zones.itertuples())
    label_y = _zone_label_positions(zone_rows, scale)
    for idx, zone in enumerate(zone_rows):
        y1 = scale(float(zone.price_upper))
        y2 = scale(float(zone.price_lower))
        fill = "#fde2e2" if zone.side == "BUY_SIDE" else "#d9f0ff"
        outline = "#b42318" if zone.side == "BUY_SIDE" else "#075985"
        draw.rectangle([CHART_X + 1, y1, CHART_X + CHART_W - 1, y2], fill=fill, outline=outline)
        draw.text(
            (CHART_X + 8, label_y[idx]),
            f"#{int(zone.rank)} {zone.side} {zone.source_family} {float(zone.representative_price):.1f}",
            fill=outline,
            font=font,
        )
    xy = [(_x(i, len(points)), scale(float(row.Close))) for i, row in enumerate(points.itertuples())]
    if len(xy) > 1:
        draw.line(xy, fill="#1f2937", width=2)
    current_y = scale(float(state["current_price"]))
    draw.line([CHART_X, current_y, CHART_X + CHART_W, current_y], fill="#111827", width=1)
    draw.text((CHART_X + CHART_W - 140, current_y - 12), f"current {float(state['current_price']):.1f}", fill="#111827", font=font)
    draw.rectangle([PANEL_X, PANEL_Y, PANEL_X + PANEL_W, 620], fill="#ffffff", outline="#b8c0cc")
    for idx, line in enumerate(_panel_lines(state)):
        draw.text((PANEL_X + 16, PANEL_Y + 18 + idx * 21), line, fill="#17202a", font=font)
    draw.rectangle([CHART_X, TABLE_Y, CHART_X + 1460, TABLE_Y + TABLE_H], fill="#ffffff", outline="#b8c0cc")
    for idx, line in enumerate(_table_lines(zones)):
        draw.text((CHART_X + 12, TABLE_Y + 14 + idx * 23), line, fill="#17202a", font=font)
    image.save(path)


def _price_grid_svg(scale) -> list[str]:
    lines = []
    for i in range(1, 5):
        y = CHART_Y + i * CHART_H / 5
        lines.append(f'<line x1="{CHART_X}" x2="{CHART_X + CHART_W}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e5e7eb"/>')
    return lines


def _zone_svg(zones: pd.DataFrame, scale) -> list[str]:
    parts = []
    zone_rows = list(zones.itertuples())
    label_y = _zone_label_positions(zone_rows, scale)
    for idx, row in enumerate(zone_rows):
        y_top = scale(float(row.price_upper))
        y_bottom = scale(float(row.price_lower))
        height = max(8.0, y_bottom - y_top)
        fill = "#fde2e2" if row.side == "BUY_SIDE" else "#d9f0ff"
        stroke = "#b42318" if row.side == "BUY_SIDE" else "#075985"
        parts.append(f'<rect x="{CHART_X + 1}" y="{y_top:.1f}" width="{CHART_W - 2}" height="{height:.1f}" fill="{fill}" fill-opacity="0.72" stroke="{stroke}" stroke-width="1.3"/>')
        label = f"#{int(row.rank)} {row.side} {row.source_family} {float(row.representative_price):.1f}"
        parts.append(f'<text x="{CHART_X + 10}" y="{label_y[idx] + 10:.1f}" font-family="Arial" font-size="12" font-weight="700" fill="{stroke}">{html.escape(label)}</text>')
    return parts


def _zone_label_positions(zone_rows: list[object], scale) -> list[float]:
    keyed = []
    for idx, row in enumerate(zone_rows):
        y = scale(float(row.price_upper)) + 4
        keyed.append((y, idx))
    keyed.sort()
    min_gap = 17.0
    placed: list[tuple[float, int]] = []
    previous = CHART_Y + 4
    for y, idx in keyed:
        placed_y = max(y, previous)
        placed_y = min(placed_y, CHART_Y + CHART_H - 18)
        placed.append((placed_y, idx))
        previous = placed_y + min_gap
    out = [0.0 for _ in zone_rows]
    for y, idx in placed:
        out[idx] = y
    return out


def _right_panel_svg(state: dict[str, object]) -> list[str]:
    lines = [
        f'<rect x="{PANEL_X}" y="{PANEL_Y}" width="{PANEL_W}" height="555" fill="#ffffff" stroke="#b8c0cc"/>',
        f'<text x="{PANEL_X + 16}" y="{PANEL_Y + 28}" font-family="Arial" font-size="18" font-weight="700" fill="#17202a">Market State</text>',
    ]
    for idx, line in enumerate(_panel_lines(state)):
        y = PANEL_Y + 58 + idx * 24
        lines.append(f'<text x="{PANEL_X + 16}" y="{y}" font-family="Arial" font-size="13" fill="#17202a">{html.escape(line)}</text>')
    return lines


def _bottom_table_svg(zones: pd.DataFrame) -> list[str]:
    lines = [
        f'<rect x="{CHART_X}" y="{TABLE_Y}" width="1460" height="{TABLE_H}" fill="#ffffff" stroke="#b8c0cc"/>',
        f'<text x="{CHART_X + 14}" y="{TABLE_Y + 24}" font-family="Arial" font-size="17" font-weight="700" fill="#17202a">Selected Visible Zones</text>',
    ]
    for idx, line in enumerate(_table_lines(zones)):
        y = TABLE_Y + 52 + idx * 24
        lines.append(f'<text x="{CHART_X + 14}" y="{y}" font-family="Arial" font-size="12" fill="#17202a">{html.escape(line)}</text>')
    return lines


def _panel_lines(state: dict[str, object]) -> list[str]:
    nearest_buy = _state_zone_label(state["nearest_buy_side_zone"])
    nearest_sell = _state_zone_label(state["nearest_sell_side_zone"])
    above = _state_zone_label(state["nearest_above_price_zone"])
    below = _state_zone_label(state["nearest_below_price_zone"])
    flags = state["missing_data_flags"]
    return [
        f"Date range: {state['start']} to {state['end']}",
        f"Current price: {float(state['current_price']):.1f}",
        f"Visible zones: {state['visible_zone_count']} ({state['buy_side_visible_count']} BUY_SIDE / {state['sell_side_visible_count']} SELL_SIDE)",
        f"Nearest BUY_SIDE liquidity: {nearest_buy}",
        f"Nearest SELL_SIDE liquidity: {nearest_sell}",
        f"Nearest above price: {above}",
        f"Nearest below price: {below}",
        "Current level context: unclear from selected zones",
        f"Liquidations: {flags['liquidations']}",
        f"VWAP: {flags['vwap']}",
        f"Compression: {flags['compression']}",
        "Research monitor snapshot, not trading advice",
    ]


def _table_lines(zones: pd.DataFrame) -> list[str]:
    lines = ["rank | side | bucket | source | range | distance | score | reason"]
    for row in zones.itertuples():
        price_range = f"{float(row.price_lower):.1f}-{float(row.price_upper):.1f}"
        reason = _short(str(row.reason_selected), 82)
        lines.append(
            f"#{int(row.rank)} | {row.side} | {row.bucket} | {row.source_family} | "
            f"{price_range} | {float(row.distance_to_current_price_pct):.2f}% | "
            f"{float(row.significance_score):.1f} | {reason}"
        )
    return lines


def _state_zone_label(value: object) -> str:
    if isinstance(value, dict):
        return f"#{value['rank']} {value['side']} {value['representative_price']:.1f}"
    return str(value)


def _scale(price_path: pd.DataFrame, zones: pd.DataFrame):
    lows = [float(price_path["Low"].min()), *zones["price_lower"].astype(float).tolist()]
    highs = [float(price_path["High"].max()), *zones["price_upper"].astype(float).tolist()]
    low = min(lows)
    high = max(highs)
    padding = max((high - low) * 0.08, 1.0)
    low -= padding
    high += padding

    def y(price: float) -> float:
        return CHART_Y + (high - price) / (high - low) * CHART_H

    return y


def _x(index: int, count: int) -> float:
    if count <= 1:
        return CHART_X
    return CHART_X + index / (count - 1) * CHART_W


def _decimated_points(frame: pd.DataFrame, *, max_points: int) -> pd.DataFrame:
    if len(frame) <= max_points:
        return frame
    step = max(1, len(frame) // max_points)
    return frame.iloc[::step].copy()


def _short(text: str, length: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= length:
        return clean
    return clean[: max(0, length - 3)].rstrip() + "..."


def _parse_date(value: str | date, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise TraderSnapshotBuilderError(f"{name} must be YYYY-MM-DD: {value}") from exc


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _repo_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"
