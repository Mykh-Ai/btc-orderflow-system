from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_monitor.accumulation_zones import (
    ACCUMULATION_ZONES_COLUMNS,
    build_accumulation_zones,
)
from market_monitor.context_windows import (
    MARKET_CONTEXT_WINDOW_COLUMNS,
    build_market_context_windows,
)
from market_monitor.events import (
    EVENT_LOG_COLUMNS,
    MARKET_MOVE_GROUP_COLUMNS,
    build_event_log,
    build_market_move_groups,
    event_stats,
)
from market_monitor.label_taxonomy import (
    SWEEP_LABEL_SUMMARY_COLUMNS,
    SWEEP_LABEL_TAXONOMY_COLUMNS,
    build_sweep_label_frames,
    label_stats,
)
from market_monitor.liquidity_zones import LIQUIDITY_MAP_COLUMNS, build_liquidity_map
from market_monitor.pattern_structures import (
    PATTERN_STRUCTURES_COLUMNS,
    build_pattern_structures,
)
from market_monitor.post_sweep_observation import (
    POST_SWEEP_OBSERVATION_COLUMNS,
    build_post_sweep_observations,
    observation_stats,
)
from market_monitor.significant_market_zones import (
    SIGNIFICANT_MARKET_ZONE_COLUMNS,
    build_significant_market_zones,
)
from market_monitor.structure import STRUCTURE_LEVEL_COLUMNS, build_structure_levels
from market_monitor.summary import write_market_summary
from market_monitor.zone_registry import (
    REGISTRY_COLUMNS,
    build_zone_registry,
    forward_liquidity_from_registry,
    load_registry,
    write_registry,
)


MARKET_STATE_TIMELINE_COLUMNS = [
    "state_id",
    "start_timestamp",
    "end_timestamp",
    "state",
    "confidence_tier",
    "evidence_json",
    "invalidation_reason",
    "data_quality",
]

VOLUME_DELTA_STATE_COLUMNS = [
    "timestamp",
    "total_qty",
    "buy_qty",
    "sell_qty",
    "delta",
    "delta_pct",
    "volume_zscore",
    "delta_zscore",
    "oi",
    "oi_change",
    "funding_rate",
    "liq_buy_qty",
    "liq_sell_qty",
    "data_quality",
]

REQUIRED_CSV_SCHEMAS = {
    "market_state_timeline.csv": MARKET_STATE_TIMELINE_COLUMNS,
    "liquidity_map.csv": LIQUIDITY_MAP_COLUMNS,
    "structure_levels.csv": STRUCTURE_LEVEL_COLUMNS,
    "volume_delta_state.csv": VOLUME_DELTA_STATE_COLUMNS,
    "market_context_windows.csv": MARKET_CONTEXT_WINDOW_COLUMNS,
    "accumulation_zones.csv": ACCUMULATION_ZONES_COLUMNS,
    "significant_market_zones.csv": SIGNIFICANT_MARKET_ZONE_COLUMNS,
    "event_log.csv": EVENT_LOG_COLUMNS,
    "pattern_structures.csv": PATTERN_STRUCTURES_COLUMNS,
    "market_move_groups.csv": MARKET_MOVE_GROUP_COLUMNS,
    "post_sweep_observation.csv": POST_SWEEP_OBSERVATION_COLUMNS,
    "sweep_label_taxonomy.csv": SWEEP_LABEL_TAXONOMY_COLUMNS,
    "sweep_label_summary.csv": SWEEP_LABEL_SUMMARY_COLUMNS,
    "liquidity_zone_registry.csv": REGISTRY_COLUMNS,
}


def write_outputs(
    feed: pd.DataFrame,
    output_dir: Path,
    *,
    run_timestamp: str,
    input_files: list[str],
    registry_in_path: Path | None = None,
    registry_out_path: Path | None = None,
    context_feed: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_close = None if feed.empty else float(feed.iloc[-1]["ClosePrice"])
    registry_out_path = registry_out_path or output_dir / "liquidity_zone_registry.csv"

    structure_levels = build_structure_levels(feed)
    liquidity_map = build_liquidity_map(structure_levels, latest_close)
    registry_in = load_registry(registry_in_path)
    volume_delta_state = build_volume_delta_state(feed)
    effective_context_feed = _context_feed_until_cutoff(context_feed, feed)
    context_volume_delta_state = build_volume_delta_state(effective_context_feed)
    market_context_windows = build_market_context_windows(
        effective_context_feed,
        end_timestamp=None if feed.empty else feed["Timestamp"].max(),
    )
    liquidity_zone_registry, registry_stats = build_zone_registry(
        liquidity_map=liquidity_map,
        feed=feed,
        registry_in=registry_in,
    )
    pattern_structures = build_pattern_structures(
        structure_levels=structure_levels,
        liquidity_zone_registry=liquidity_zone_registry,
    )
    forward_liquidity_map = forward_liquidity_from_registry(liquidity_zone_registry, latest_close)
    event_log = build_event_log(
        registry=liquidity_zone_registry,
        feed=feed,
        volume_delta_state=volume_delta_state,
        previous_registry=registry_in,
    )
    market_move_groups = build_market_move_groups(event_log)
    post_sweep_observation = build_post_sweep_observations(
        event_log=event_log,
        feed=feed,
        volume_delta_state=volume_delta_state,
    )
    sweep_label_taxonomy, sweep_label_summary = build_sweep_label_frames(
        observations=post_sweep_observation,
        market_move_groups=market_move_groups,
    )
    accumulation_zones = build_accumulation_zones(feed, volume_delta_state)
    context_accumulation_zones = build_accumulation_zones(
        effective_context_feed,
        context_volume_delta_state,
    )
    significant_market_zones = build_significant_market_zones(
        inventory_zones=context_accumulation_zones,
        liquidity_zone_registry=liquidity_zone_registry,
        market_context_windows=market_context_windows,
    )
    market_state_timeline = build_market_state_timeline(
        feed,
        market_context_windows=market_context_windows,
        significant_market_zones=significant_market_zones,
    )

    frames = {
        "market_state_timeline.csv": market_state_timeline,
        "liquidity_map.csv": forward_liquidity_map,
        "structure_levels.csv": structure_levels,
        "volume_delta_state.csv": volume_delta_state,
        "market_context_windows.csv": market_context_windows,
        "accumulation_zones.csv": accumulation_zones,
        "significant_market_zones.csv": significant_market_zones,
        "event_log.csv": event_log,
        "pattern_structures.csv": pattern_structures,
        "market_move_groups.csv": market_move_groups,
        "post_sweep_observation.csv": post_sweep_observation,
        "sweep_label_taxonomy.csv": sweep_label_taxonomy,
        "sweep_label_summary.csv": sweep_label_summary,
        "liquidity_zone_registry.csv": liquidity_zone_registry,
    }
    for filename, columns in REQUIRED_CSV_SCHEMAS.items():
        frame = frames[filename].reindex(columns=columns)
        output_path = registry_out_path if filename == "liquidity_zone_registry.csv" else output_dir / filename
        frame.to_csv(output_path, index=False)
        frames[filename] = frame
    if registry_out_path != output_dir / "liquidity_zone_registry.csv":
        write_registry(liquidity_zone_registry, output_dir / "liquidity_zone_registry.csv")

    write_market_summary(
        output_dir / "market_summary.md",
        feed=feed,
        liquidity_map=forward_liquidity_map,
        structure_levels=structure_levels,
        event_log=event_log,
        accumulation_zones=accumulation_zones,
        market_context_windows=market_context_windows,
        significant_market_zones=significant_market_zones,
        run_timestamp=run_timestamp,
        input_files=input_files,
        output_dir=output_dir,
        registry_input=registry_in_path,
        registry_output=registry_out_path,
        registry_stats=registry_stats,
        event_stats=event_stats(event_log),
        observation_stats=observation_stats(post_sweep_observation),
        label_stats=label_stats(sweep_label_taxonomy),
    )

    return frames


def build_volume_delta_state(feed: pd.DataFrame) -> pd.DataFrame:
    if feed.empty:
        return pd.DataFrame(columns=VOLUME_DELTA_STATE_COLUMNS)

    frame = feed.sort_values("Timestamp", kind="mergesort").copy()
    delta = frame["BuyQty"] - frame["SellQty"]
    total_qty = frame["TotalQty"]
    volume_zscore = _rolling_zscore(total_qty)
    delta_zscore = _rolling_zscore(delta)
    result = pd.DataFrame(
        {
            "timestamp": frame["Timestamp"].map(_format_ts),
            "total_qty": total_qty.astype(float),
            "buy_qty": frame["BuyQty"].astype(float),
            "sell_qty": frame["SellQty"].astype(float),
            "delta": delta.astype(float),
            "delta_pct": delta.where(total_qty > 0, 0).div(total_qty.where(total_qty > 0, 1)),
            "volume_zscore": volume_zscore,
            "delta_zscore": delta_zscore,
            "oi": frame["OpenInterest"].astype(float),
            "oi_change": frame["OpenInterest"].diff().fillna(0).astype(float),
            "funding_rate": frame["FundingRate"].astype(float),
            "liq_buy_qty": frame["LiqBuyQty"].astype(float),
            "liq_sell_qty": frame["LiqSellQty"].astype(float),
            "data_quality": frame["DataQuality"],
        }
    )
    return result[VOLUME_DELTA_STATE_COLUMNS]


def build_market_state_timeline(
    feed: pd.DataFrame,
    *,
    market_context_windows: pd.DataFrame | None = None,
    significant_market_zones: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if feed.empty:
        return pd.DataFrame(columns=MARKET_STATE_TIMELINE_COLUMNS)

    quality = "RAW" if set(feed["DataQuality"]) == {"RAW"} else "RECOVERED_DEGRADED"
    open_price = float(feed.iloc[0]["OpenPrice"])
    close_price = float(feed.iloc[-1]["ClosePrice"])
    price_change_pct = (close_price / open_price - 1.0) * 100.0 if open_price else 0.0
    total_qty = float(feed["TotalQty"].sum())
    delta = float((feed["BuyQty"] - feed["SellQty"]).sum())
    oi_change = float(feed.iloc[-1]["OpenInterest"] - feed.iloc[0]["OpenInterest"])
    liq_buy = float(feed["LiqBuyQty"].sum()) if "LiqBuyQty" in feed.columns else 0.0
    liq_sell = float(feed["LiqSellQty"].sum()) if "LiqSellQty" in feed.columns else 0.0
    state, confidence = _classify_market_state(
        price_change_pct=price_change_pct,
        delta=delta,
        oi_change=oi_change,
        liq_buy=liq_buy,
        liq_sell=liq_sell,
    )
    evidence = {
        "price_change_pct": round(price_change_pct, 6),
        "total_qty": round(total_qty, 6),
        "delta": round(delta, 6),
        "open_interest_change": round(oi_change, 6),
        "liq_buy_qty": round(liq_buy, 6),
        "liq_sell_qty": round(liq_sell, 6),
        "classification_scope": "descriptive_daily_market_state_only",
    }
    evidence.update(_context_evidence(market_context_windows))
    evidence.update(_significant_zone_evidence(significant_market_zones))
    row = {
        "state_id": "state_000001",
        "start_timestamp": _format_ts(feed["Timestamp"].min()),
        "end_timestamp": _format_ts(feed["Timestamp"].max()),
        "state": state,
        "confidence_tier": confidence,
        "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        "invalidation_reason": "",
        "data_quality": quality,
    }
    return pd.DataFrame([row], columns=MARKET_STATE_TIMELINE_COLUMNS)


def _classify_market_state(
    *,
    price_change_pct: float,
    delta: float,
    oi_change: float,
    liq_buy: float,
    liq_sell: float,
) -> tuple[str, str]:
    liquidation_total = liq_buy + liq_sell
    sell_liq_dominant = liquidation_total > 0 and liq_sell >= liq_buy * 2
    buy_liq_dominant = liquidation_total > 0 and liq_buy >= liq_sell * 2
    if price_change_pct <= -1.0 and (delta < 0 or sell_liq_dominant):
        confidence = "HIGH" if price_change_pct <= -2.0 and (abs(delta) > 1000 or liq_sell >= 100) else "MEDIUM"
        return "EXPANSION_DOWN", confidence
    if price_change_pct >= 1.0 and (delta > 0 or buy_liq_dominant):
        confidence = "HIGH" if price_change_pct >= 2.0 and (abs(delta) > 1000 or liq_buy >= 100) else "MEDIUM"
        return "EXPANSION_UP", confidence
    if price_change_pct < 0 and delta < 0 and oi_change > 0:
        return "DISTRIBUTION", "MEDIUM"
    if price_change_pct > 0 and delta > 0 and oi_change > 0:
        return "ACCUMULATION", "MEDIUM"
    if price_change_pct < 0 and delta > 0:
        return "DISTRIBUTION", "LOW"
    if price_change_pct > 0 and delta < 0:
        return "ACCUMULATION", "LOW"
    return "CHOP", "LOW"


def _rolling_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    rolling_mean = series.rolling(window=window, min_periods=window).mean()
    rolling_std = series.rolling(window=window, min_periods=window).std(ddof=0)
    zscore = (series - rolling_mean) / rolling_std.mask(rolling_std == 0)
    return zscore.fillna(0).astype(float)


def _context_feed_until_cutoff(
    context_feed: pd.DataFrame | None,
    feed: pd.DataFrame,
) -> pd.DataFrame:
    source = context_feed if context_feed is not None and not context_feed.empty else feed
    if source.empty or feed.empty:
        return source.copy()
    cutoff = pd.Timestamp(feed["Timestamp"].max())
    start = cutoff - pd.Timedelta(days=30)
    return source[
        (source["Timestamp"] >= start) & (source["Timestamp"] <= cutoff)
    ].sort_values("Timestamp", kind="mergesort").copy()


def _context_evidence(context_windows: pd.DataFrame | None) -> dict[str, object]:
    if context_windows is None or context_windows.empty:
        return {}
    evidence: dict[str, object] = {}
    for _, row in context_windows.iterrows():
        days = int(row["window_days"])
        evidence[f"context_{days}d_regime_bias"] = row["regime_bias"]
        evidence[f"context_{days}d_delta"] = round(float(row["delta"]), 6)
        evidence[f"context_{days}d_open_interest_change"] = round(float(row["open_interest_change"]), 6)
        evidence[f"context_{days}d_data_quality_flags"] = row["data_quality_flags"]
    return evidence


def _significant_zone_evidence(significant_market_zones: pd.DataFrame | None) -> dict[str, object]:
    if significant_market_zones is None or significant_market_zones.empty:
        return {"significant_market_zone_count": 0}
    top = significant_market_zones.sort_values(
        ["significance_score", "source_day_count", "source_zone_count"],
        ascending=[False, False, False],
        kind="mergesort",
    ).head(3)
    return {
        "significant_market_zone_count": int(len(significant_market_zones)),
        "top_significant_market_zones": "|".join(str(value) for value in top["zone_id"].tolist()),
    }


def _format_ts(value) -> str:
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")
