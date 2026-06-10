from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


RESEARCH_VERSION = "SHI_RESET_37A_MARKET_REGIME_AND_HIDDEN_FLOW_RESEARCH_V0"
WINDOWS_CSV = "market_regime_windows.csv"
CANDIDATES_CSV = "hidden_flow_candidates.csv"
FUTURE_LABELS_CSV = "hidden_flow_future_labels.csv"
SUMMARY_MD = "hidden_flow_research_summary.md"
MANIFEST_JSON = "hidden_flow_manifest.json"
MAX_CANDIDATES = 100
MAX_VISIBLE_REVIEW = 20

FORBIDDEN_CANDIDATE_LABELS = {
    "BUY",
    "SELL",
    "LONG",
    "SHORT",
    "ENTRY",
    "EXIT",
    "SIGNAL",
    "SETUP_READY",
    "TRADE_READY",
    "EDGE_VALIDATED",
    "LIVE_READY",
    "ORDER",
    "PNL",
}

WINDOW_COLUMNS = [
    "window_id",
    "start_timestamp",
    "end_timestamp",
    "window_minutes",
    "trend_direction",
    "prior_trend_direction",
    "trend_strength",
    "downtrend_exhaustion_score",
    "uptrend_exhaustion_score",
    "normalization_score",
    "compression_score",
    "range_position",
    "zone_position_context",
    "distance_to_selected_zone",
    "nearest_zone_id",
    "nearest_zone_side",
    "nearest_zone_bucket",
    "total_qty",
    "trades",
    "buy_qty",
    "sell_qty",
    "cumulative_delta",
    "delta_pct",
    "volume_zscore",
    "relative_volume",
    "trades_zscore",
    "relative_trades",
    "open_interest_change",
    "funding_context",
    "price_change",
    "price_change_pct",
    "high_low_range",
    "range_pct",
    "price_progress_score",
    "close_location_in_window",
    "effort_result_ratio",
    "pressure_without_progress_score",
    "positive_delta_no_up_progress_score",
    "negative_delta_no_down_progress_score",
    "high_volume_low_range_score",
    "oi_build_without_price_progress_score",
    "zone_hold_score",
    "compression_before_expansion_score",
    "accumulation_direction_score",
    "distribution_direction_score",
    "buyer_absorption_score",
    "seller_absorption_score",
    "neutral_compression_score",
    "absorption_score",
    "accumulation_score",
    "distribution_score",
    "candidate_label",
    "confidence",
    "candidate_score",
    "directional_classification_reason",
    "evidence_summary",
    "missing_data_flags",
]

CANDIDATE_COLUMNS = [
    "candidate_id",
    "start_timestamp",
    "end_timestamp",
    "window_minutes",
    "candidate_label",
    "confidence",
    "trend_context",
    "prior_trend_direction",
    "range_position",
    "zone_position_context",
    "close_location_in_window",
    "nearest_zone_id",
    "nearest_zone_side",
    "nearest_zone_bucket",
    "distance_to_zone_pct",
    "cumulative_delta",
    "delta_pct",
    "total_qty",
    "trades",
    "open_interest_change",
    "price_change",
    "price_change_pct",
    "range_pct",
    "price_progress_score",
    "pressure_without_progress_score",
    "compression_score",
    "accumulation_direction_score",
    "distribution_direction_score",
    "buyer_absorption_score",
    "seller_absorption_score",
    "neutral_compression_score",
    "absorption_score",
    "accumulation_score",
    "distribution_score",
    "directional_classification_reason",
    "evidence_summary",
    "missing_data_flags",
    "review_priority_rank",
    "visible_for_review",
]

FUTURE_COLUMNS = [
    "candidate_id",
    "future_window_minutes",
    "future_price_change",
    "future_price_change_pct",
    "max_favorable_up",
    "max_favorable_down",
    "impulse_direction_label",
    "impulse_size_bucket",
    "false_positive_flag",
]


class HiddenFlowResearchError(RuntimeError):
    """Raised when hidden-flow research cannot be completed."""


@dataclass(frozen=True)
class HiddenFlowResearchResult:
    output_dir: Path
    windows_path: Path
    candidates_path: Path
    future_labels_path: Path
    summary_path: Path
    manifest_path: Path
    window_count: int
    candidate_count: int
    visible_review_count: int


def run_hidden_flow_research(
    *,
    start: str | date,
    end: str | date,
    feed_dir: str | Path,
    selected_zones_path: str | Path,
    input_root: str | Path,
    output_dir: str | Path,
    windows: Iterable[int] = (60, 240, 720, 1440),
    future_windows: Iterable[int] = (60, 240, 720),
) -> HiddenFlowResearchResult:
    start_date = _parse_date(start, "start")
    end_date = _parse_date(end, "end")
    if start_date > end_date:
        raise HiddenFlowResearchError("start must be <= end")
    window_list = _parse_positive_ints(windows, "windows")
    future_window_list = _parse_positive_ints(future_windows, "future_windows")

    feed_root = Path(feed_dir)
    selected_path = Path(selected_zones_path)
    input_root_path = Path(input_root)
    out_dir = Path(output_dir)
    if not feed_root.exists():
        raise HiddenFlowResearchError(f"feed dir not found: {feed_root}")
    if not selected_path.exists():
        raise HiddenFlowResearchError(f"selected_zones.csv not found: {selected_path}")
    if not input_root_path.exists():
        raise HiddenFlowResearchError(f"input root not found: {input_root_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    feed = _load_feed(feed_root, start_date, end_date)
    selected_zones = _load_visible_selected_zones(selected_path)
    missing_flags = _missing_flags(feed, selected_zones)
    windows_frame = _build_windows(feed, selected_zones, window_list, missing_flags)
    candidates = _select_candidates(windows_frame)
    future_labels = _build_future_labels(feed, candidates, future_window_list)

    windows_path = out_dir / WINDOWS_CSV
    candidates_path = out_dir / CANDIDATES_CSV
    future_path = out_dir / FUTURE_LABELS_CSV
    summary_path = out_dir / SUMMARY_MD
    manifest_path = out_dir / MANIFEST_JSON
    windows_frame[WINDOW_COLUMNS].to_csv(windows_path, index=False)
    candidates[CANDIDATE_COLUMNS].to_csv(candidates_path, index=False)
    future_labels[FUTURE_COLUMNS].to_csv(future_path, index=False)
    summary_path.write_text(
        _render_summary(
            start_date=start_date,
            end_date=end_date,
            feed=feed,
            windows_frame=windows_frame,
            candidates=candidates,
            future_labels=future_labels,
            missing_flags=missing_flags,
        ),
        encoding="utf-8",
    )
    manifest = {
        "research_version": RESEARCH_VERSION,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "feed_dir": str(feed_root),
        "selected_zones": str(selected_path),
        "input_root": str(input_root_path),
        "windows": window_list,
        "future_windows": future_window_list,
        "detection_features_use_future_data": False,
        "future_labels_evaluation_only": True,
        "candidate_cap": MAX_CANDIDATES,
        "visible_review_cap": MAX_VISIBLE_REVIEW,
        "missing_data_flags": missing_flags,
        "repo_commit": _repo_commit(),
        "outputs": {
            "market_regime_windows_csv": str(windows_path),
            "hidden_flow_candidates_csv": str(candidates_path),
            "hidden_flow_future_labels_csv": str(future_path),
            "hidden_flow_research_summary_md": str(summary_path),
            "hidden_flow_manifest_json": str(manifest_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return HiddenFlowResearchResult(
        output_dir=out_dir,
        windows_path=windows_path,
        candidates_path=candidates_path,
        future_labels_path=future_path,
        summary_path=summary_path,
        manifest_path=manifest_path,
        window_count=int(len(windows_frame)),
        candidate_count=int(len(candidates)),
        visible_review_count=int((candidates["visible_for_review"].astype(str) == "true").sum())
        if not candidates.empty
        else 0,
    )


def _load_feed(feed_dir: Path, start_date: date, end_date: date) -> pd.DataFrame:
    parts = []
    for day in _date_range(start_date, end_date):
        path = feed_dir / f"{day.isoformat()}.csv"
        if not path.exists():
            raise HiddenFlowResearchError(f"missing feed file: {path}")
        frame = pd.read_csv(path)
        normalized = pd.DataFrame(
            {
                "timestamp": _column(frame, ["Timestamp", "timestamp"]),
                "trades": _column(frame, ["Trades", "AggTrades", "trades"]),
                "total_qty": _column(frame, ["TotalQty", "Volume", "total_qty"]),
                "buy_qty": _column(frame, ["BuyQty", "buy_qty"]),
                "sell_qty": _column(frame, ["SellQty", "sell_qty"]),
                "close_price": _column(frame, ["ClosePrice", "Close", "close_price"]),
                "high_price": _column(frame, ["HiPrice", "High", "high_price"]),
                "low_price": _column(frame, ["LowPrice", "Low", "low_price"]),
                "open_interest": _column(frame, ["OpenInterest", "oi", "open_interest"]),
                "funding_rate": _column(frame, ["FundingRate", "funding_rate"]),
                "liq_buy_qty": _optional_column(frame, ["LiqBuyQty", "liq_buy_qty"], 0.0),
                "liq_sell_qty": _optional_column(frame, ["LiqSellQty", "liq_sell_qty"], 0.0),
            }
        )
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce", utc=True)
        for column in normalized.columns:
            if column != "timestamp":
                normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        normalized = normalized.dropna(subset=["timestamp", "close_price", "high_price", "low_price"])
        if normalized.empty:
            raise HiddenFlowResearchError(f"{path} has no usable feed rows")
        parts.append(normalized)
    out = pd.concat(parts, ignore_index=True).sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    for column in [
        "trades",
        "total_qty",
        "buy_qty",
        "sell_qty",
        "open_interest",
        "funding_rate",
        "liq_buy_qty",
        "liq_sell_qty",
    ]:
        out[column] = out[column].fillna(0.0)
    return out


def _column(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    raise HiddenFlowResearchError(f"feed missing required field; expected one of: {', '.join(names)}")


def _optional_column(frame: pd.DataFrame, names: list[str], default: float) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return pd.Series([default] * len(frame), index=frame.index)


def _load_visible_selected_zones(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"zone_id", "side", "bucket", "representative_price", "price_lower", "price_upper", "visible_on_snapshot"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise HiddenFlowResearchError(f"{path} missing selected zone columns: {', '.join(missing)}")
    visible = frame[frame["visible_on_snapshot"].astype(str).str.lower() == "true"].copy()
    if visible.empty:
        raise HiddenFlowResearchError("selected_zones.csv has no visible_on_snapshot=true rows")
    for column in ["representative_price", "price_lower", "price_upper"]:
        visible[column] = pd.to_numeric(visible[column], errors="coerce")
    visible = visible.dropna(subset=["representative_price", "price_lower", "price_upper"])
    if visible.empty:
        raise HiddenFlowResearchError("visible selected zones have no usable price levels")
    return visible.reset_index(drop=True)


def _build_windows(
    feed: pd.DataFrame,
    selected_zones: pd.DataFrame,
    windows: list[int],
    missing_flags: dict[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    window_id = 1
    for minutes in windows:
        for end_pos in range(minutes, len(feed) + 1, 60):
            start_pos = end_pos - minutes
            window = feed.iloc[start_pos:end_pos]
            if len(window) < minutes:
                continue
            prior_context = _prior_trend_context(feed, start_pos, minutes)
            rows.append(_score_window(window, selected_zones, minutes, window_id, missing_flags, prior_context))
            window_id += 1
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=WINDOW_COLUMNS)
    frame = _add_relative_metrics(frame)
    scored_rows = [_finalize_window(row) for _, row in frame.iterrows()]
    return pd.DataFrame(scored_rows)[WINDOW_COLUMNS]


def _score_window(
    window: pd.DataFrame,
    selected_zones: pd.DataFrame,
    minutes: int,
    window_id: int,
    missing_flags: dict[str, str],
    prior_context: dict[str, object],
) -> dict[str, object]:
    start_price = float(window["close_price"].iloc[0])
    end_price = float(window["close_price"].iloc[-1])
    high = float(window["high_price"].max())
    low = float(window["low_price"].min())
    total_qty = float(window["total_qty"].sum())
    trades = float(window["trades"].sum())
    buy_qty = float(window["buy_qty"].sum())
    sell_qty = float(window["sell_qty"].sum())
    cumulative_delta = buy_qty - sell_qty
    delta_pct = cumulative_delta / total_qty if total_qty else 0.0
    price_change = end_price - start_price
    price_change_pct = price_change / start_price * 100 if start_price else 0.0
    high_low_range = high - low
    range_pct = high_low_range / start_price * 100 if start_price else 0.0
    range_position = (end_price - low) / high_low_range if high_low_range else 0.5
    close_location = range_position
    oi_change = float(window["open_interest"].iloc[-1] - window["open_interest"].iloc[0])
    funding_context = float(window["funding_rate"].mean())
    nearest = _nearest_zone(selected_zones, end_price)
    progress = abs(price_change_pct) / max(range_pct, 0.05)
    price_progress_score = _clamp(100 * (1 - min(progress, 1.0)), 0, 100)
    effort_result_ratio = (abs(delta_pct) * 100 + 1) / (abs(price_change_pct) + 0.05)
    trend_direction = "UP" if price_change_pct > 0.25 else "DOWN" if price_change_pct < -0.25 else "RANGE"
    trend_strength = _clamp(abs(price_change_pct) * 12 + range_pct * 2, 0, 100)
    zone_position_context = _zone_position_context(selected_zones, end_price, nearest)
    return {
        "window_id": f"window_{window_id:06d}",
        "start_timestamp": window["timestamp"].iloc[0].isoformat(),
        "end_timestamp": window["timestamp"].iloc[-1].isoformat(),
        "window_minutes": int(minutes),
        "trend_direction": trend_direction,
        "prior_trend_direction": prior_context["prior_trend_direction"],
        "trend_strength": round(trend_strength, 3),
        "range_position": round(float(range_position), 4),
        "zone_position_context": zone_position_context,
        "distance_to_selected_zone": nearest["distance_pct"],
        "nearest_zone_id": nearest["zone_id"],
        "nearest_zone_side": nearest["side"],
        "nearest_zone_bucket": nearest["bucket"],
        "total_qty": round(total_qty, 6),
        "trades": round(trades, 6),
        "buy_qty": round(buy_qty, 6),
        "sell_qty": round(sell_qty, 6),
        "cumulative_delta": round(cumulative_delta, 6),
        "delta_pct": round(delta_pct, 6),
        "open_interest_change": round(oi_change, 6),
        "funding_context": round(funding_context, 10),
        "price_change": round(price_change, 6),
        "price_change_pct": round(price_change_pct, 6),
        "high_low_range": round(high_low_range, 6),
        "range_pct": round(range_pct, 6),
        "price_progress_score": round(price_progress_score, 3),
        "close_location_in_window": round(float(close_location), 4),
        "effort_result_ratio": round(float(effort_result_ratio), 6),
        "missing_data_flags": _format_missing_flags(missing_flags),
    }


def _prior_trend_context(feed: pd.DataFrame, start_pos: int, minutes: int) -> dict[str, object]:
    if start_pos <= 0:
        return {"prior_trend_direction": "UNKNOWN", "prior_trend_change_pct": 0.0}
    lookback = min(max(int(minutes), 60), 1440)
    prior = feed.iloc[max(0, start_pos - lookback) : start_pos]
    if len(prior) < min(60, lookback):
        return {"prior_trend_direction": "UNKNOWN", "prior_trend_change_pct": 0.0}
    start_price = float(prior["close_price"].iloc[0])
    end_price = float(prior["close_price"].iloc[-1])
    change_pct = (end_price - start_price) / start_price * 100 if start_price else 0.0
    direction = "UP" if change_pct > 0.35 else "DOWN" if change_pct < -0.35 else "RANGE"
    return {"prior_trend_direction": direction, "prior_trend_change_pct": round(change_pct, 6)}


def _zone_position_context(zones: pd.DataFrame, price: float, nearest: dict[str, object]) -> str:
    lower = float(nearest["price_lower"])
    upper = float(nearest["price_upper"])
    side = str(nearest["side"])
    distance = abs(float(nearest["distance_pct"]))
    if lower <= price <= upper:
        return "inside_zone"
    if side == "BUY_SIDE" and price < lower and distance <= 0.85:
        return "near_upper_zone"
    if side == "SELL_SIDE" and price > upper and distance <= 0.85:
        return "near_lower_zone"

    representatives = zones["representative_price"].astype(float)
    sides = zones["side"].astype(str)
    has_lower_sell = bool(((sides == "SELL_SIDE") & (representatives < price)).any())
    has_upper_buy = bool(((sides == "BUY_SIDE") & (representatives > price)).any())
    if has_lower_sell and has_upper_buy:
        return "between_zones"
    return "unclear"


def _add_relative_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for column, rel_name, z_name in [
        ("total_qty", "relative_volume", "volume_zscore"),
        ("trades", "relative_trades", "trades_zscore"),
    ]:
        values = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
        grouped = out.groupby("window_minutes")[column]
        med = grouped.transform("median").replace(0, 1.0)
        std = grouped.transform("std").fillna(0.0).replace(0, 1.0)
        mean = grouped.transform("mean").fillna(0.0)
        out[rel_name] = values / med
        out[z_name] = (values - mean) / std
    range_med = out.groupby("window_minutes")["range_pct"].transform("median").replace(0, 0.01)
    out["_range_relative"] = out["range_pct"] / range_med
    return out


def _finalize_window(row: pd.Series) -> dict[str, object]:
    volume_z = float(row["volume_zscore"])
    trades_z = float(row["trades_zscore"])
    rel_volume = float(row["relative_volume"])
    rel_trades = float(row["relative_trades"])
    delta_pct = float(row["delta_pct"])
    progress_score = float(row["price_progress_score"])
    range_relative = float(row["_range_relative"])
    distance = abs(float(row["distance_to_selected_zone"]))
    effort = _clamp(max(abs(delta_pct) * 140, rel_volume * 28, rel_trades * 24, max(volume_z, trades_z) * 18), 0, 100)
    compression = _clamp((1.0 - min(range_relative, 1.5) / 1.5) * 100, 0, 100)
    zone_hold = _clamp(100 - distance * 120, 0, 100)
    pressure = _clamp(0.48 * effort + 0.34 * progress_score + 0.18 * max(zone_hold, compression), 0, 100)
    positive_no_up = pressure if delta_pct > 0.04 and float(row["price_change_pct"]) < 0.35 else 0.0
    negative_no_down = pressure if delta_pct < -0.04 and float(row["price_change_pct"]) > -0.35 else 0.0
    high_volume_low_range = _clamp(max(rel_volume, rel_trades) * 35 + progress_score * 0.45 + compression * 0.25, 0, 100)
    oi_build = _clamp(abs(float(row["open_interest_change"])) / 50 + progress_score * 0.45, 0, 100)
    compression_before = _clamp(compression * 0.7 + pressure * 0.3, 0, 100)
    directional_scores = _directional_sub_scores(
        row=row,
        pressure=pressure,
        compression=compression,
        positive_no_up=positive_no_up,
        negative_no_down=negative_no_down,
        zone_hold=zone_hold,
        oi_build=oi_build,
    )
    accumulation = directional_scores["accumulation_direction_score"]
    distribution = directional_scores["distribution_direction_score"]
    buyer_absorption = directional_scores["buyer_absorption_score"]
    seller_absorption = directional_scores["seller_absorption_score"]
    neutral_compression = directional_scores["neutral_compression_score"]
    absorption = max(buyer_absorption, seller_absorption)
    down_exhaustion = _clamp(accumulation * 0.65 + (40 if row["trend_direction"] == "DOWN" else 0), 0, 100)
    up_exhaustion = _clamp(distribution * 0.65 + (40 if row["trend_direction"] == "UP" else 0), 0, 100)
    normalization = _clamp(progress_score * 0.45 + compression * 0.35 + (20 if row["trend_direction"] == "RANGE" else 0), 0, 100)
    label, confidence, reason = _candidate_label_and_confidence(
        row=row,
        pressure=pressure,
        compression=compression,
        absorption=absorption,
        accumulation=accumulation,
        distribution=distribution,
        buyer_absorption=buyer_absorption,
        seller_absorption=seller_absorption,
        neutral_compression=neutral_compression,
        down_exhaustion=down_exhaustion,
        up_exhaustion=up_exhaustion,
    )
    candidate_score = max(
        pressure,
        absorption,
        accumulation,
        distribution,
        neutral_compression,
        compression_before,
        down_exhaustion,
        up_exhaustion,
    )
    out = row.to_dict()
    out.update(
        {
            "downtrend_exhaustion_score": round(down_exhaustion, 3),
            "uptrend_exhaustion_score": round(up_exhaustion, 3),
            "normalization_score": round(normalization, 3),
            "compression_score": round(compression, 3),
            "volume_zscore": round(volume_z, 6),
            "relative_volume": round(rel_volume, 6),
            "trades_zscore": round(trades_z, 6),
            "relative_trades": round(rel_trades, 6),
            "pressure_without_progress_score": round(pressure, 3),
            "positive_delta_no_up_progress_score": round(positive_no_up, 3),
            "negative_delta_no_down_progress_score": round(negative_no_down, 3),
            "high_volume_low_range_score": round(high_volume_low_range, 3),
            "oi_build_without_price_progress_score": round(oi_build, 3),
            "zone_hold_score": round(zone_hold, 3),
            "compression_before_expansion_score": round(compression_before, 3),
            "accumulation_direction_score": round(accumulation, 3),
            "distribution_direction_score": round(distribution, 3),
            "buyer_absorption_score": round(buyer_absorption, 3),
            "seller_absorption_score": round(seller_absorption, 3),
            "neutral_compression_score": round(neutral_compression, 3),
            "absorption_score": round(absorption, 3),
            "accumulation_score": round(accumulation, 3),
            "distribution_score": round(distribution, 3),
            "candidate_label": label,
            "confidence": confidence,
            "candidate_score": round(candidate_score, 3),
            "directional_classification_reason": reason,
            "evidence_summary": _evidence_summary(
                row,
                pressure,
                compression,
                buyer_absorption,
                seller_absorption,
                accumulation,
                distribution,
                neutral_compression,
            ),
        }
    )
    return {column: out.get(column, "") for column in WINDOW_COLUMNS}


def _directional_sub_scores(
    *,
    row: pd.Series,
    pressure: float,
    compression: float,
    positive_no_up: float,
    negative_no_down: float,
    zone_hold: float,
    oi_build: float,
) -> dict[str, float]:
    lower_context = _lower_context_score(row)
    upper_context = _upper_context_score(row)
    prior = str(row["prior_trend_direction"])
    close_location = float(row["close_location_in_window"])
    oi_component = min(oi_build * 0.12, 10.0)

    markdown_bonus = 16.0 if prior == "DOWN" else 8.0 if prior == "RANGE" else 0.0
    markup_bonus = 16.0 if prior == "UP" else 8.0 if prior == "RANGE" else 0.0
    lower_close_hold = 8.0 if close_location >= 0.38 else 0.0
    upper_close_reject = 8.0 if close_location <= 0.62 else 0.0

    accumulation = _clamp(
        positive_no_up * 0.34
        + negative_no_down * 0.18
        + compression * 0.16
        + zone_hold * 0.10
        + lower_context * 0.24
        + markdown_bonus
        + lower_close_hold
        + oi_component,
        0,
        100,
    )
    distribution = _clamp(
        positive_no_up * 0.28
        + negative_no_down * 0.20
        + compression * 0.16
        + zone_hold * 0.10
        + upper_context * 0.24
        + markup_bonus
        + upper_close_reject
        + oi_component,
        0,
        100,
    )
    buyer_absorption = _clamp(
        negative_no_down * 0.58
        + lower_context * 0.22
        + zone_hold * 0.08
        + compression * 0.08
        + lower_close_hold
        + oi_component * 0.6,
        0,
        100,
    )
    seller_absorption = _clamp(
        positive_no_up * 0.58
        + upper_context * 0.22
        + zone_hold * 0.08
        + compression * 0.08
        + upper_close_reject
        + oi_component * 0.6,
        0,
        100,
    )
    directional_leader = max(accumulation, distribution, buyer_absorption, seller_absorption)
    neutral_penalty = max(0.0, directional_leader - 70.0) * 0.35
    neutral = _clamp(compression * 0.68 + pressure * 0.32 - neutral_penalty, 0, 100)
    return {
        "accumulation_direction_score": accumulation,
        "distribution_direction_score": distribution,
        "buyer_absorption_score": buyer_absorption,
        "seller_absorption_score": seller_absorption,
        "neutral_compression_score": neutral,
    }


def _lower_context_score(row: pd.Series) -> float:
    score = 0.0
    location = float(row["range_position"])
    zone_context = str(row["zone_position_context"])
    nearest_side = str(row["nearest_zone_side"])
    distance = abs(float(row["distance_to_selected_zone"]))
    if zone_context == "near_lower_zone":
        score += 45
    elif zone_context == "inside_zone" and nearest_side == "SELL_SIDE":
        score += 42
    elif zone_context == "between_zones":
        score += 12
    if nearest_side == "SELL_SIDE" and distance <= 0.85:
        score += 22
    if location <= 0.35:
        score += 30
    elif location <= 0.50:
        score += 16
    return _clamp(score, 0, 100)


def _upper_context_score(row: pd.Series) -> float:
    score = 0.0
    location = float(row["range_position"])
    zone_context = str(row["zone_position_context"])
    nearest_side = str(row["nearest_zone_side"])
    distance = abs(float(row["distance_to_selected_zone"]))
    if zone_context == "near_upper_zone":
        score += 45
    elif zone_context == "inside_zone" and nearest_side == "BUY_SIDE":
        score += 42
    elif zone_context == "between_zones":
        score += 12
    if nearest_side == "BUY_SIDE" and distance <= 0.85:
        score += 22
    if location >= 0.65:
        score += 30
    elif location >= 0.50:
        score += 16
    return _clamp(score, 0, 100)


def _candidate_label_and_confidence(
    *,
    row: pd.Series,
    pressure: float,
    compression: float,
    absorption: float,
    accumulation: float,
    distribution: float,
    buyer_absorption: float,
    seller_absorption: float,
    neutral_compression: float,
    down_exhaustion: float,
    up_exhaustion: float,
) -> tuple[str, str, str]:
    delta_pct = float(row["delta_pct"])
    price_change_pct = float(row["price_change_pct"])
    lower_context = _lower_context_score(row)
    upper_context = _upper_context_score(row)
    prior = str(row["prior_trend_direction"])
    zone_context = str(row["zone_position_context"])
    close_location = float(row["close_location_in_window"])
    if pressure < 45:
        return (
            "UNCLEAR_FLOW_ANOMALY",
            "LOW",
            f"pressure below directional threshold; pressure={pressure:.1f}; zone_context={zone_context}; prior_trend={prior}",
        )
    if delta_pct > 0.04 and price_change_pct < 0.35 and upper_context >= 45:
        if prior == "UP" and distribution >= 78 and distribution >= neutral_compression + 8:
            return (
                "HIDDEN_DISTRIBUTION_DOWN_CANDIDATE",
                _confidence(distribution, pressure),
                _direction_reason(
                    "positive delta without upward progress after prior upward context near upper zone",
                    row,
                    distribution,
                    neutral_compression,
                ),
            )
        if seller_absorption >= 72 and seller_absorption >= neutral_compression + 5:
            return (
                "SELLER_ABSORPTION_CANDIDATE",
                _confidence(seller_absorption, pressure),
                _direction_reason(
                    "positive delta without upward progress rejected near upper zone",
                    row,
                    seller_absorption,
                    neutral_compression,
                ),
            )
        if neutral_compression >= 58:
            return (
                "COMPRESSION_BEFORE_EXPANSION_CANDIDATE",
                _confidence(neutral_compression, pressure),
                _direction_reason(
                    "upper-zone positive delta pressure did not beat neutral compression",
                    row,
                    max(distribution, seller_absorption),
                    neutral_compression,
                ),
            )
        return (
            "UNCLEAR_FLOW_ANOMALY",
            "LOW",
            _direction_reason("upper-zone positive delta pressure has mixed directional evidence", row, distribution, neutral_compression),
        )
    if delta_pct < -0.04 and price_change_pct > -0.35 and lower_context >= 45:
        if buyer_absorption >= 60 and buyer_absorption >= neutral_compression - 5:
            return (
                "BUYER_ABSORPTION_CANDIDATE",
                _confidence(buyer_absorption, pressure),
                _direction_reason(
                    "negative delta without downward progress held near lower zone",
                    row,
                    buyer_absorption,
                    neutral_compression,
                ),
            )
        if accumulation >= 78 and accumulation >= neutral_compression + 8:
            return (
                "HIDDEN_ACCUMULATION_UP_CANDIDATE",
                _confidence(accumulation, pressure),
                _direction_reason(
                    "seller pressure failed to push lower in lower-zone context",
                    row,
                    accumulation,
                    neutral_compression,
                ),
            )
    if delta_pct > 0.04 and price_change_pct < 0.45 and lower_context >= 45:
        if accumulation >= 78 and accumulation >= neutral_compression + 5:
            label = "DOWNTREND_EXHAUSTION_CANDIDATE" if prior == "DOWN" and accumulation < 86 else "HIDDEN_ACCUMULATION_UP_CANDIDATE"
            return (
                label,
                _confidence(max(accumulation, down_exhaustion), pressure),
                _direction_reason(
                    "positive delta compressed after lower-zone or markdown context",
                    row,
                    accumulation,
                    neutral_compression,
                ),
            )
        if neutral_compression >= 58:
            return (
                "COMPRESSION_BEFORE_EXPANSION_CANDIDATE",
                _confidence(neutral_compression, pressure),
                _direction_reason(
                    "lower-zone positive delta compression lacks enough accumulation separation",
                    row,
                    accumulation,
                    neutral_compression,
                ),
            )
    if delta_pct < -0.04 and price_change_pct > -0.45 and upper_context >= 45:
        if prior == "UP" and distribution >= 78 and distribution >= neutral_compression + 8:
            label = "UPTREND_EXHAUSTION_CANDIDATE" if up_exhaustion >= distribution else "HIDDEN_DISTRIBUTION_DOWN_CANDIDATE"
            return (
                label,
                _confidence(max(distribution, up_exhaustion), pressure),
                _direction_reason(
                    "negative delta compressed after upper-zone or markup context",
                    row,
                    distribution,
                    neutral_compression,
                ),
            )
        if neutral_compression >= 58:
            return (
                "COMPRESSION_BEFORE_EXPANSION_CANDIDATE",
                _confidence(neutral_compression, pressure),
                _direction_reason(
                    "upper-zone negative delta compression lacks enough distribution separation",
                    row,
                    distribution,
                    neutral_compression,
                ),
            )
    if compression >= 55 and pressure >= 50:
        return (
            "COMPRESSION_BEFORE_EXPANSION_CANDIDATE",
            _confidence(max(compression, neutral_compression), pressure),
            _direction_reason(
                "high compression with no dominant directional sub-score",
                row,
                max(accumulation, distribution, absorption),
                neutral_compression,
            ),
        )
    if row["trend_direction"] == "DOWN" and float(row["price_progress_score"]) >= 55:
        return (
            "NORMALIZATION_AFTER_MARKDOWN",
            "LOW",
            f"range normalized after markdown context; pressure={pressure:.1f}; close_location={close_location:.2f}",
        )
    if row["trend_direction"] == "UP" and float(row["price_progress_score"]) >= 55:
        return (
            "NORMALIZATION_AFTER_MARKUP",
            "LOW",
            f"range normalized after markup context; pressure={pressure:.1f}; close_location={close_location:.2f}",
        )
    return (
        "UNCLEAR_FLOW_ANOMALY",
        "LOW",
        f"mixed effort-result evidence; pressure={pressure:.1f}; zone_context={zone_context}; prior_trend={prior}",
    )


def _direction_reason(prefix: str, row: pd.Series, directional_score: float, neutral_score: float) -> str:
    return (
        f"{prefix}; prior_trend={row['prior_trend_direction']}; "
        f"zone_context={row['zone_position_context']}; "
        f"close_location={float(row['close_location_in_window']):.2f}; "
        f"directional_score={directional_score:.1f}; "
        f"neutral_compression_score={neutral_score:.1f}"
    )


def _confidence(primary: float, pressure: float) -> str:
    score = max(primary, pressure)
    if score >= 78:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def _select_candidates(windows_frame: pd.DataFrame) -> pd.DataFrame:
    if windows_frame.empty:
        return pd.DataFrame(columns=CANDIDATE_COLUMNS)
    frame = windows_frame.copy()
    candidate_mask = (
        (frame["pressure_without_progress_score"] >= 48)
        & (frame["price_progress_score"] >= 35)
        & (
            (frame["zone_hold_score"] >= 20)
            | (frame["compression_score"] >= 35)
            | (frame["high_volume_low_range_score"] >= 65)
        )
    )
    selected = frame[candidate_mask].copy()
    if selected.empty:
        selected = frame.sort_values(
            ["pressure_without_progress_score", "compression_score"], ascending=[False, False], kind="mergesort"
        ).head(20)
    selected = selected.sort_values(
        ["candidate_score", "pressure_without_progress_score", "compression_score", "end_timestamp"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).head(MAX_CANDIDATES)
    rows = []
    for rank, (_, row) in enumerate(selected.iterrows(), start=1):
        rows.append(
            {
                "candidate_id": f"hidden_flow_{rank:04d}",
                "start_timestamp": row["start_timestamp"],
                "end_timestamp": row["end_timestamp"],
                "window_minutes": int(row["window_minutes"]),
                "candidate_label": row["candidate_label"],
                "confidence": row["confidence"],
                "trend_context": row["trend_direction"],
                "prior_trend_direction": row["prior_trend_direction"],
                "range_position": row["range_position"],
                "zone_position_context": row["zone_position_context"],
                "close_location_in_window": row["close_location_in_window"],
                "nearest_zone_id": row["nearest_zone_id"],
                "nearest_zone_side": row["nearest_zone_side"],
                "nearest_zone_bucket": row["nearest_zone_bucket"],
                "distance_to_zone_pct": row["distance_to_selected_zone"],
                "cumulative_delta": row["cumulative_delta"],
                "delta_pct": row["delta_pct"],
                "total_qty": row["total_qty"],
                "trades": row["trades"],
                "open_interest_change": row["open_interest_change"],
                "price_change": row["price_change"],
                "price_change_pct": row["price_change_pct"],
                "range_pct": row["range_pct"],
                "price_progress_score": row["price_progress_score"],
                "pressure_without_progress_score": row["pressure_without_progress_score"],
                "compression_score": row["compression_score"],
                "accumulation_direction_score": row["accumulation_direction_score"],
                "distribution_direction_score": row["distribution_direction_score"],
                "buyer_absorption_score": row["buyer_absorption_score"],
                "seller_absorption_score": row["seller_absorption_score"],
                "neutral_compression_score": row["neutral_compression_score"],
                "absorption_score": row["absorption_score"],
                "accumulation_score": row["accumulation_score"],
                "distribution_score": row["distribution_score"],
                "directional_classification_reason": row["directional_classification_reason"],
                "evidence_summary": row["evidence_summary"],
                "missing_data_flags": row["missing_data_flags"],
                "review_priority_rank": rank,
                "visible_for_review": "true" if rank <= MAX_VISIBLE_REVIEW else "false",
            }
        )
    return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)


def _build_future_labels(feed: pd.DataFrame, candidates: pd.DataFrame, future_windows: list[int]) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame(columns=FUTURE_COLUMNS)
    rows = []
    feed_indexed = feed.set_index("timestamp")
    for _, candidate in candidates.iterrows():
        end_ts = pd.Timestamp(candidate["end_timestamp"])
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        start_price = _price_at_or_before(feed, end_ts)
        for minutes in future_windows:
            future_end = end_ts + pd.Timedelta(minutes=minutes)
            future = feed_indexed[(feed_indexed.index > end_ts) & (feed_indexed.index <= future_end)]
            rows.append(_future_label_row(candidate, minutes, start_price, future))
    return pd.DataFrame(rows, columns=FUTURE_COLUMNS)


def _future_label_row(candidate: pd.Series, minutes: int, start_price: float, future: pd.DataFrame) -> dict[str, object]:
    if future.empty or start_price == 0:
        return {
            "candidate_id": candidate["candidate_id"],
            "future_window_minutes": int(minutes),
            "future_price_change": 0.0,
            "future_price_change_pct": 0.0,
            "max_favorable_up": 0.0,
            "max_favorable_down": 0.0,
            "impulse_direction_label": "FUTURE_UNCLEAR",
            "impulse_size_bucket": "NONE",
            "false_positive_flag": True,
        }
    last_close = float(future["close_price"].iloc[-1])
    max_up = float(future["high_price"].max() - start_price)
    max_down = float(start_price - future["low_price"].min())
    change = last_close - start_price
    change_pct = change / start_price * 100
    max_up_pct = max_up / start_price * 100
    max_down_pct = max_down / start_price * 100
    if max_up_pct < 0.25 and max_down_pct < 0.25:
        direction = "FUTURE_CHOP"
    elif max_up_pct >= max_down_pct * 1.2 and (change_pct > 0.2 or max_up_pct >= 0.75):
        direction = "FUTURE_EXPANSION_UP"
    elif max_down_pct >= max_up_pct * 1.2 and (change_pct < -0.2 or max_down_pct >= 0.75):
        direction = "FUTURE_EXPANSION_DOWN"
    else:
        direction = "FUTURE_UNCLEAR"
    size_bucket = _size_bucket(max(max_up_pct, max_down_pct))
    return {
        "candidate_id": candidate["candidate_id"],
        "future_window_minutes": int(minutes),
        "future_price_change": round(change, 6),
        "future_price_change_pct": round(change_pct, 6),
        "max_favorable_up": round(max_up, 6),
        "max_favorable_down": round(max_down, 6),
        "impulse_direction_label": direction,
        "impulse_size_bucket": size_bucket,
        "false_positive_flag": _false_positive(candidate["candidate_label"], direction),
    }


def _false_positive(candidate_label: str, future_direction: str) -> bool:
    up_labels = {"HIDDEN_ACCUMULATION_UP_CANDIDATE", "BUYER_ABSORPTION_CANDIDATE", "DOWNTREND_EXHAUSTION_CANDIDATE"}
    down_labels = {"HIDDEN_DISTRIBUTION_DOWN_CANDIDATE", "SELLER_ABSORPTION_CANDIDATE", "UPTREND_EXHAUSTION_CANDIDATE"}
    if candidate_label in up_labels:
        return future_direction != "FUTURE_EXPANSION_UP"
    if candidate_label in down_labels:
        return future_direction != "FUTURE_EXPANSION_DOWN"
    if candidate_label == "COMPRESSION_BEFORE_EXPANSION_CANDIDATE":
        return future_direction == "FUTURE_CHOP"
    return False


def _size_bucket(move_pct: float) -> str:
    if move_pct < 0.25:
        return "NONE"
    if move_pct < 0.75:
        return "SMALL"
    if move_pct < 1.5:
        return "MEDIUM"
    return "LARGE"


def _price_at_or_before(feed: pd.DataFrame, timestamp: pd.Timestamp) -> float:
    rows = feed[feed["timestamp"] <= timestamp]
    if rows.empty:
        return float(feed["close_price"].iloc[0])
    return float(rows["close_price"].iloc[-1])


def _nearest_zone(zones: pd.DataFrame, price: float) -> dict[str, object]:
    distances = (zones["representative_price"].astype(float) - price).abs()
    row = zones.loc[distances.sort_values(kind="mergesort").index[0]]
    distance_pct = (float(row["representative_price"]) - price) / price * 100 if price else 0.0
    return {
        "zone_id": str(row["zone_id"]),
        "side": str(row["side"]),
        "bucket": str(row["bucket"]),
        "price_lower": float(row["price_lower"]),
        "price_upper": float(row["price_upper"]),
        "distance_pct": round(distance_pct, 6),
    }


def _missing_flags(feed: pd.DataFrame, selected_zones: pd.DataFrame) -> dict[str, str]:
    evidence_missing = "|".join(selected_zones.get("evidence_fields_missing", pd.Series(dtype=str)).fillna("").astype(str)).lower()
    return {
        "liquidations": _liquidation_availability(feed),
        "vwap": "not_available" if "vwap=not_available" in evidence_missing else "available_or_not_reported",
        "compression": "not_available" if "compression=not_available" in evidence_missing else "available_or_not_reported",
    }


def _liquidation_availability(feed: pd.DataFrame) -> str:
    required = {"liq_buy_qty", "liq_sell_qty"}
    if feed.empty or not required.issubset(feed.columns):
        return "not_available"
    values = (
        pd.to_numeric(feed["liq_buy_qty"], errors="coerce").fillna(0).abs()
        + pd.to_numeric(feed["liq_sell_qty"], errors="coerce").fillna(0).abs()
    )
    return "available" if float(values.sum()) > 0 else "available_zero"


def _format_missing_flags(flags: dict[str, str]) -> str:
    return "|".join(f"{key}={value}" for key, value in sorted(flags.items()))


def _evidence_summary(
    row: pd.Series,
    pressure: float,
    compression: float,
    buyer_absorption: float,
    seller_absorption: float,
    accumulation: float,
    distribution: float,
    neutral_compression: float,
) -> str:
    return (
        f"delta_pct={float(row['delta_pct']):.4f}; "
        f"relative_volume={float(row['relative_volume']):.3f}; "
        f"price_change_pct={float(row['price_change_pct']):.3f}; "
        f"range_pct={float(row['range_pct']):.3f}; "
        f"pressure_without_progress={pressure:.1f}; "
        f"compression={compression:.1f}; "
        f"buyer_absorption={buyer_absorption:.1f}; "
        f"seller_absorption={seller_absorption:.1f}; "
        f"accumulation={accumulation:.1f}; "
        f"distribution={distribution:.1f}; "
        f"neutral_compression={neutral_compression:.1f}; "
        f"prior_trend={row['prior_trend_direction']}; "
        f"zone_context={row['zone_position_context']}; "
        f"close_location={float(row['close_location_in_window']):.2f}; "
        f"nearest_zone={row['nearest_zone_id']}:{row['nearest_zone_side']}"
    )


def _render_summary(
    *,
    start_date: date,
    end_date: date,
    feed: pd.DataFrame,
    windows_frame: pd.DataFrame,
    candidates: pd.DataFrame,
    future_labels: pd.DataFrame,
    missing_flags: dict[str, str],
) -> str:
    label_counts = candidates["candidate_label"].value_counts().to_dict() if not candidates.empty else {}
    confidence_counts = candidates["confidence"].value_counts().to_dict() if not candidates.empty else {}
    future_counts = future_labels["impulse_direction_label"].value_counts().to_dict() if not future_labels.empty else {}
    false_positive_count = (
        int((future_labels["false_positive_flag"].astype(str).str.lower() == "true").sum())
        if not future_labels.empty
        else 0
    )
    future_by_label = _future_counts_by_label(candidates, future_labels)
    false_positive_by_label = _false_positive_counts_by_label(candidates, future_labels)
    pre_impulse_review = _pre_impulse_review_rows(candidates, future_labels)
    lines = [
        "# Hidden Flow Research Summary",
        "",
        "Research detector only. Future labels are evaluation-only and are not used for candidate detection.",
        "",
        f"- Date range: {start_date.isoformat()} to {end_date.isoformat()}",
        f"- Feed rows: {len(feed)}",
        f"- Market regime windows: {len(windows_frame)}",
        f"- Candidates: {len(candidates)}",
        f"- Visible review candidates: {int((candidates['visible_for_review'].astype(str) == 'true').sum()) if not candidates.empty else 0}",
        f"- Candidate labels after patch/current run: {json.dumps(label_counts, sort_keys=True)}",
        f"- Confidence: {json.dumps(confidence_counts, sort_keys=True)}",
        f"- Future impulse labels: {json.dumps(future_counts, sort_keys=True)}",
        f"- Future false-positive rows: {false_positive_count}",
        f"- Missing data flags: {json.dumps(missing_flags, sort_keys=True)}",
        "",
        "## Future Direction By Candidate Label",
        "",
        _markdown_table(future_by_label, list(future_by_label.columns)),
        "",
        "## False Positive Rows By Candidate Label",
        "",
        _markdown_table(false_positive_by_label, list(false_positive_by_label.columns)),
        "",
        "## 2026-04-05 Pre-Impulse Review",
        "",
        _markdown_table(
            pre_impulse_review,
            [
                "candidate_id",
                "start_timestamp",
                "end_timestamp",
                "window_minutes",
                "candidate_label",
                "confidence",
                "cumulative_delta",
                "delta_pct",
                "price_change",
                "pressure_without_progress_score",
                "compression_score",
                "directional_classification_reason",
                "future_impulse_labels",
            ],
        ),
        "",
        "## Top Review Candidates",
        "",
        _markdown_table(
            candidates.head(20),
            [
                "candidate_id",
                "end_timestamp",
                "window_minutes",
                "candidate_label",
                "confidence",
                "pressure_without_progress_score",
                "delta_pct",
                "price_change_pct",
                "zone_position_context",
                "prior_trend_direction",
                "nearest_zone_side",
            ],
        ),
    ]
    return "\n".join(lines) + "\n"


def _future_counts_by_label(candidates: pd.DataFrame, future_labels: pd.DataFrame) -> pd.DataFrame:
    columns = ["candidate_label", "impulse_direction_label", "rows"]
    if candidates.empty or future_labels.empty:
        return pd.DataFrame(columns=columns)
    merged = future_labels.merge(candidates[["candidate_id", "candidate_label"]], on="candidate_id", how="left")
    grouped = (
        merged.groupby(["candidate_label", "impulse_direction_label"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["candidate_label", "impulse_direction_label"], kind="mergesort")
    )
    return grouped[columns]


def _false_positive_counts_by_label(candidates: pd.DataFrame, future_labels: pd.DataFrame) -> pd.DataFrame:
    columns = ["candidate_label", "false_positive_rows"]
    if candidates.empty or future_labels.empty:
        return pd.DataFrame(columns=columns)
    merged = future_labels.merge(candidates[["candidate_id", "candidate_label"]], on="candidate_id", how="left")
    false_rows = merged[merged["false_positive_flag"].astype(str).str.lower() == "true"]
    if false_rows.empty:
        return pd.DataFrame(columns=columns)
    grouped = (
        false_rows.groupby("candidate_label", dropna=False)
        .size()
        .reset_index(name="false_positive_rows")
        .sort_values(["false_positive_rows", "candidate_label"], ascending=[False, True], kind="mergesort")
    )
    return grouped[columns]


def _pre_impulse_review_rows(candidates: pd.DataFrame, future_labels: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "candidate_id",
        "start_timestamp",
        "end_timestamp",
        "window_minutes",
        "candidate_label",
        "confidence",
        "cumulative_delta",
        "delta_pct",
        "price_change",
        "pressure_without_progress_score",
        "compression_score",
        "directional_classification_reason",
        "future_impulse_labels",
    ]
    if candidates.empty:
        return pd.DataFrame(columns=columns)
    frame = candidates.copy()
    starts = pd.to_datetime(frame["start_timestamp"], errors="coerce", utc=True)
    ends = pd.to_datetime(frame["end_timestamp"], errors="coerce", utc=True)
    mask = (
        (starts >= pd.Timestamp("2026-04-03T18:00:00Z"))
        & (starts <= pd.Timestamp("2026-04-04T02:00:00Z"))
        & (ends >= pd.Timestamp("2026-04-04T06:00:00Z"))
        & (ends <= pd.Timestamp("2026-04-04T12:00:00Z"))
    )
    review = frame.loc[mask].sort_values("review_priority_rank", kind="mergesort").head(5).copy()
    if review.empty:
        return pd.DataFrame(columns=columns)
    if future_labels.empty:
        review["future_impulse_labels"] = ""
    else:
        labels = (
            future_labels.groupby("candidate_id")["impulse_direction_label"]
            .apply(lambda values: ",".join(sorted(set(str(value) for value in values))))
            .to_dict()
        )
        review["future_impulse_labels"] = review["candidate_id"].map(labels).fillna("")
    return review[columns]


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "_None_"
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for _, row in frame.iterrows():
        out.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return "\n".join(out)


def _parse_date(value: str | date, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise HiddenFlowResearchError(f"{name} must be YYYY-MM-DD: {value}") from exc


def _parse_positive_ints(values: Iterable[int], name: str) -> list[int]:
    out = []
    for value in values:
        item = int(value)
        if item <= 0:
            raise HiddenFlowResearchError(f"{name} must contain positive minute values")
        out.append(item)
    return out


def _date_range(start_date: date, end_date: date) -> Iterable[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _repo_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"
