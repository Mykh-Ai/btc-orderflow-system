from __future__ import annotations

import json

import pandas as pd


CONTEXT_WINDOW_DAYS = (1, 3, 7, 30)

MARKET_CONTEXT_WINDOW_COLUMNS = [
    "context_id",
    "end_timestamp",
    "window_days",
    "start_timestamp",
    "rows_used",
    "expected_minutes",
    "coverage_minutes",
    "data_quality",
    "data_quality_flags",
    "price_change_pct",
    "total_qty",
    "delta",
    "delta_pct",
    "open_interest_change",
    "funding_first",
    "funding_last",
    "funding_mean",
    "liq_buy_qty",
    "liq_sell_qty",
    "liq_imbalance",
    "regime_bias",
    "confidence_tier",
    "evidence_json",
]


def build_market_context_windows(
    feed: pd.DataFrame,
    *,
    end_timestamp=None,
    windows_days: tuple[int, ...] = CONTEXT_WINDOW_DAYS,
) -> pd.DataFrame:
    if feed.empty:
        return pd.DataFrame(columns=MARKET_CONTEXT_WINDOW_COLUMNS)

    frame = feed.sort_values("Timestamp", kind="mergesort").reset_index(drop=True).copy()
    end_ts = pd.Timestamp(end_timestamp) if end_timestamp is not None else frame["Timestamp"].max()
    end_ts = _to_utc(end_ts)
    frame = frame[frame["Timestamp"] <= end_ts].copy()
    if frame.empty:
        return pd.DataFrame(columns=MARKET_CONTEXT_WINDOW_COLUMNS)

    rows = []
    for index, days in enumerate(windows_days, start=1):
        rows.append(_build_window_row(frame, end_ts=end_ts, days=int(days), index=index))
    return pd.DataFrame(rows, columns=MARKET_CONTEXT_WINDOW_COLUMNS)


def _build_window_row(frame: pd.DataFrame, *, end_ts: pd.Timestamp, days: int, index: int) -> dict[str, object]:
    start_boundary = end_ts - pd.Timedelta(days=days)
    window = frame[(frame["Timestamp"] >= start_boundary) & (frame["Timestamp"] <= end_ts)].copy()
    if window.empty:
        return _empty_row(index, days, start_boundary, end_ts)

    first_ts = _to_utc(window.iloc[0]["Timestamp"])
    last_ts = _to_utc(window.iloc[-1]["Timestamp"])
    expected_minutes = int(days * 1440)
    coverage_minutes = int(max((last_ts - first_ts).total_seconds() // 60, 0) + 1)
    data_quality = _quality_summary(window)
    data_quality_flags = _quality_flags(
        window=window,
        first_ts=first_ts,
        start_boundary=start_boundary,
        rows_used=len(window),
        expected_minutes=expected_minutes,
    )

    open_price = float(window.iloc[0]["OpenPrice"])
    close_price = float(window.iloc[-1]["ClosePrice"])
    total_qty = float(window["TotalQty"].sum())
    buy_qty = float(window["BuyQty"].sum())
    sell_qty = float(window["SellQty"].sum())
    delta = buy_qty - sell_qty
    delta_pct = delta / total_qty if total_qty > 0 else 0.0
    oi_change = float(window.iloc[-1]["OpenInterest"] - window.iloc[0]["OpenInterest"])
    funding_first = float(window.iloc[0]["FundingRate"])
    funding_last = float(window.iloc[-1]["FundingRate"])
    funding_mean = float(window["FundingRate"].mean())
    liq_buy = float(window["LiqBuyQty"].sum()) if "LiqBuyQty" in window.columns else 0.0
    liq_sell = float(window["LiqSellQty"].sum()) if "LiqSellQty" in window.columns else 0.0
    liq_total = liq_buy + liq_sell
    liq_imbalance = (liq_buy - liq_sell) / liq_total if liq_total > 0 else 0.0
    price_change_pct = (close_price / open_price - 1.0) * 100.0 if open_price else 0.0
    regime_bias, confidence = _classify_context(
        price_change_pct=price_change_pct,
        delta=delta,
        delta_pct=delta_pct,
        oi_change=oi_change,
        liq_buy=liq_buy,
        liq_sell=liq_sell,
        data_quality_flags=data_quality_flags,
        expected_minutes=expected_minutes,
        rows_used=len(window),
    )
    evidence = {
        "classification_scope": "descriptive_multi_day_market_context_only",
        "first_timestamp": _format_ts(first_ts),
        "last_timestamp": _format_ts(last_ts),
        "coverage_minutes": coverage_minutes,
        "expected_minutes": expected_minutes,
        "data_quality": data_quality,
        "data_quality_flags": data_quality_flags,
    }

    return {
        "context_id": f"context_{index:06d}",
        "end_timestamp": _format_ts(end_ts),
        "window_days": days,
        "start_timestamp": _format_ts(first_ts),
        "rows_used": int(len(window)),
        "expected_minutes": expected_minutes,
        "coverage_minutes": coverage_minutes,
        "data_quality": data_quality,
        "data_quality_flags": data_quality_flags,
        "price_change_pct": round(price_change_pct, 6),
        "total_qty": round(total_qty, 6),
        "delta": round(delta, 6),
        "delta_pct": round(delta_pct, 8),
        "open_interest_change": round(oi_change, 6),
        "funding_first": round(funding_first, 10),
        "funding_last": round(funding_last, 10),
        "funding_mean": round(funding_mean, 10),
        "liq_buy_qty": round(liq_buy, 6),
        "liq_sell_qty": round(liq_sell, 6),
        "liq_imbalance": round(liq_imbalance, 8),
        "regime_bias": regime_bias,
        "confidence_tier": confidence,
        "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    }


def _empty_row(index: int, days: int, start_boundary: pd.Timestamp, end_ts: pd.Timestamp) -> dict[str, object]:
    evidence = {
        "classification_scope": "descriptive_multi_day_market_context_only",
        "data_quality_flags": "NO_ROWS",
    }
    return {
        "context_id": f"context_{index:06d}",
        "end_timestamp": _format_ts(end_ts),
        "window_days": days,
        "start_timestamp": _format_ts(start_boundary),
        "rows_used": 0,
        "expected_minutes": int(days * 1440),
        "coverage_minutes": 0,
        "data_quality": "none",
        "data_quality_flags": "NO_ROWS",
        "price_change_pct": 0.0,
        "total_qty": 0.0,
        "delta": 0.0,
        "delta_pct": 0.0,
        "open_interest_change": 0.0,
        "funding_first": 0.0,
        "funding_last": 0.0,
        "funding_mean": 0.0,
        "liq_buy_qty": 0.0,
        "liq_sell_qty": 0.0,
        "liq_imbalance": 0.0,
        "regime_bias": "DEGRADED_UNKNOWN",
        "confidence_tier": "LOW",
        "evidence_json": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    }


def _classify_context(
    *,
    price_change_pct: float,
    delta: float,
    delta_pct: float,
    oi_change: float,
    liq_buy: float,
    liq_sell: float,
    data_quality_flags: str,
    expected_minutes: int,
    rows_used: int,
) -> tuple[str, str]:
    if rows_used < max(60, expected_minutes * 0.35):
        return "DEGRADED_UNKNOWN", "LOW"

    sell_liq_pressure = liq_sell > liq_buy * 1.5 and liq_sell >= 100
    buy_liq_pressure = liq_buy > liq_sell * 1.5 and liq_buy >= 100
    bearish_flow = price_change_pct < -1.0 and (delta < 0 or sell_liq_pressure)
    bullish_flow = price_change_pct > 1.0 and (delta > 0 or buy_liq_pressure)
    distribution = price_change_pct < 0 and oi_change > 0 and (delta < 0 or sell_liq_pressure)
    accumulation = price_change_pct > 0 and oi_change > 0 and (delta > 0 or buy_liq_pressure)

    degraded = "RECOVERED_DEGRADED" in data_quality_flags or "INCOMPLETE" in data_quality_flags
    confidence = "MEDIUM" if degraded else "HIGH"
    if abs(delta_pct) < 0.002 and abs(price_change_pct) < 1.0:
        confidence = "LOW"

    if distribution:
        return "DISTRIBUTION_PRESSURE", confidence
    if accumulation:
        return "ACCUMULATION_PRESSURE", confidence
    if bearish_flow:
        return "BEARISH_FLOW", confidence
    if bullish_flow:
        return "BULLISH_FLOW", confidence
    return "MIXED", "LOW"


def _quality_summary(frame: pd.DataFrame) -> str:
    if frame.empty or "DataQuality" not in frame.columns:
        return "none"
    counts = frame["DataQuality"].astype(str).value_counts().sort_index()
    return ", ".join(f"{name}={int(count)}" for name, count in counts.items())


def _quality_flags(
    *,
    window: pd.DataFrame,
    first_ts: pd.Timestamp,
    start_boundary: pd.Timestamp,
    rows_used: int,
    expected_minutes: int,
) -> str:
    flags: list[str] = []
    if first_ts > start_boundary + pd.Timedelta(minutes=1):
        flags.append("INCOMPLETE_START")
    if rows_used < expected_minutes * 0.9:
        flags.append("INCOMPLETE_ROWS")
    if "DataQuality" in window.columns and "RECOVERED_DEGRADED" in set(window["DataQuality"].astype(str)):
        flags.append("RECOVERED_DEGRADED")
    return "|".join(flags) if flags else "OK"


def _to_utc(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _format_ts(value) -> str:
    return _to_utc(value).isoformat().replace("+00:00", "Z")
