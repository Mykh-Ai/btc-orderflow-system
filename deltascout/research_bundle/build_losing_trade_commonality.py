"""Build a cutoff-safe commonality review for known losing DeltaScout trades."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Europe/Bratislava")
PLAIN_LOSS = "plain_loss_stop"
PROTECTED = "protected_profit_trailing_stop"
TP1_STOP = "tp1_then_stop"
UNKNOWN = "manual_or_unknown"

PATTERN_LABELS = {
    "near_60m_extreme": "entry within 0.15% of the directional 60m extreme",
    "near_240m_extreme": "entry within 0.25% of the directional 240m extreme",
    "vwap_extension_ge_0_5pct": "absolute VWAP extension at least 0.50%",
    "weak_or_mid_peak_percentile": "current same-side delta-candidate percentile at or below 50",
    "oi_down_60m": "open interest fell over the pre-entry 60m window",
    "oi_down_240m": "open interest fell over the pre-entry 240m window",
    "directional_move_with_oi_down_60m": "price moved with the trade direction while OI fell over 60m",
    "counterflow_delta_60m": "60m buy/sell delta opposed the trade direction",
    "broad_delta_conflict_24h": "24h cumulative delta opposed the trade direction",
    "momentum_chase_60m": "60m directional move plus entry near the 60m extreme",
    "poc_ahead": "POC remained ahead of the entry in the trade direction",
    "prior_same_side_peak_240m": "at least one earlier same-side delta candidate existed in the prior 240m",
    "crowded_funding": "funding sign was crowded in the trade direction",
}


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except Exception:
        return None


def _parse_utc(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _parse_local(value: Any) -> datetime:
    text = str(value).strip()
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _local_naive(value: Any) -> datetime:
    return _parse_local(value).replace(tzinfo=None)


def _feed_utc_naive_from_local(local_naive: datetime) -> datetime:
    """Convert a legacy DeltaScout local-naive event time to feed UTC-naive time."""
    if local_naive.tzinfo is not None:
        local_aware = local_naive.astimezone(LOCAL_TZ)
    else:
        local_aware = local_naive.replace(tzinfo=LOCAL_TZ)
    return local_aware.astimezone(timezone.utc).replace(tzinfo=None)


def _fmt(value: Optional[float], digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _pct_text(count: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{count}/{denominator} ({count / denominator * 100:.0f}%)"


def _lifecycle(last_closed: Dict[str, Any]) -> str:
    if last_closed.get("tp1_done") and last_closed.get("tp2_done") and last_closed.get("trail_active"):
        return PROTECTED
    if last_closed.get("tp1_done"):
        return TP1_STOP
    if last_closed.get("sl_done") and not last_closed.get("tp1_done") and not last_closed.get("tp2_done"):
        return PLAIN_LOSS
    return UNKNOWN


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_accepted(material: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted((material / "reviews").glob("20??-??-??/accepted_event_context_*.csv")):
        for row in _read_csv(path):
            if not row.get("ts"):
                continue
            item: Dict[str, Any] = dict(row)
            item["_dt_local"] = _local_naive(row["ts"])
            item["_source_path"] = str(path)
            rows.append(item)
    return rows


def _load_all_peak_events(material: Path) -> List[Dict[str, Any]]:
    by_key: Dict[tuple[datetime, str], Dict[str, Any]] = {}
    for path in sorted((material / "reviews").glob("20??-??-??/events_context_*.csv")):
        for row in _read_csv(path):
            if not row.get("ts") or str(row.get("event_type") or "") not in {"DELTA_MAX", "DELTA_MIN"}:
                continue
            item: Dict[str, Any] = dict(row)
            item["_dt_local"] = _local_naive(row["ts"])
            by_key[(item["_dt_local"], str(item.get("kind") or "").lower())] = item
    rows = list(by_key.values())
    rows.sort(key=lambda row: row["_dt_local"])
    return rows


def _load_feed(material: Path) -> tuple[List[datetime], List[Dict[str, Any]]]:
    quality: Dict[str, Dict[str, str]] = {}
    sidecar = material / "recovery_reports" / "recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv"
    if sidecar.exists():
        quality = {row["Timestamp"]: row for row in _read_csv(sidecar) if row.get("Timestamp")}
    rows: List[Dict[str, Any]] = []
    for path in sorted((material / "effective_feed").glob("20??-??-??.csv")):
        for row in _read_csv(path):
            if not row.get("Timestamp"):
                continue
            quality_row = quality.get(row["Timestamp"]) or {}
            rows.append(
                {
                    "dt": datetime.fromisoformat(row["Timestamp"]),
                    "open": _num(row.get("Open")),
                    "high": _num(row.get("High")),
                    "low": _num(row.get("Low")),
                    "close": _num(row.get("Close")),
                    "buy": _num(row.get("BuyQty")),
                    "sell": _num(row.get("SellQty")),
                    "oi": _num(row.get("OpenInterest")),
                    "funding": _num(row.get("FundingRate")),
                    "synthetic": _bool(row.get("IsSynthetic")),
                    "recovery_class": quality_row.get("RecoveryClass") or "OUTSIDE_RECOVERY_SIDECAR",
                    "oi_source": quality_row.get("OiSource") or "effective_feed",
                    "funding_source": quality_row.get("FundingSource") or "effective_feed",
                }
            )
    rows.sort(key=lambda row: row["dt"])
    return [row["dt"] for row in rows], rows


def _nearest_signal(
    accepted: Sequence[Dict[str, Any]], side: str, opened_local: datetime, tolerance_seconds: float = 180.0
) -> Optional[Dict[str, Any]]:
    side_l = side.lower()
    candidates = [row for row in accepted if str(row.get("kind") or "").lower() == side_l]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda row: abs((row["_dt_local"] - opened_local).total_seconds()))
    gap = abs((nearest["_dt_local"] - opened_local).total_seconds())
    return nearest if gap <= tolerance_seconds else None


def _window(feed_times: Sequence[datetime], feed_rows: Sequence[Dict[str, Any]], cutoff: datetime, minutes: int):
    end = bisect.bisect_right(feed_times, cutoff)
    start = bisect.bisect_left(feed_times, cutoff - timedelta(minutes=minutes - 1), 0, end)
    return list(feed_rows[start:end])


def _first_last_numeric(rows: Sequence[Dict[str, Any]], key: str) -> tuple[Optional[float], Optional[float]]:
    values = [row.get(key) for row in rows if row.get(key) is not None]
    return (values[0], values[-1]) if values else (None, None)


def _feed_features(
    feed_times: Sequence[datetime], feed_rows: Sequence[Dict[str, Any]], cutoff: datetime, side_sign: int
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for minutes in (15, 60, 240):
        rows = _window(feed_times, feed_rows, cutoff, minutes)
        closes = [row["close"] for row in rows if row.get("close") is not None]
        highs = [row["high"] for row in rows if row.get("high") is not None]
        lows = [row["low"] for row in rows if row.get("low") is not None]
        first_oi, last_oi = _first_last_numeric(rows, "oi")
        result[f"feed_rows_{minutes}m"] = len(rows)
        result[f"ret_{minutes}m_pct"] = (
            ((closes[-1] / closes[0]) - 1.0) * 100.0 if len(closes) >= 2 and closes[0] else None
        )
        result[f"oi_change_{minutes}m"] = (
            last_oi - first_oi if first_oi is not None and last_oi is not None else None
        )
        degraded = any(
            row.get("recovery_class") not in {"REAL_ENRICHED", "OUTSIDE_RECOVERY_SIDECAR"}
            for row in rows
        )
        result[f"oi_trusted_{minutes}m"] = not degraded
        buy = sum(row["buy"] for row in rows if row.get("buy") is not None)
        sell = sum(row["sell"] for row in rows if row.get("sell") is not None)
        total_qty = buy + sell
        result[f"buy_sell_delta_{minutes}m"] = buy - sell if rows else None
        result[f"total_qty_{minutes}m"] = total_qty if rows else None
        result[f"buy_sell_delta_pct_{minutes}m"] = (buy - sell) / total_qty if rows and total_qty else None
        current = closes[-1] if closes else None
        if current is not None and current:
            extreme = max(highs) if side_sign > 0 and highs else min(lows) if lows else None
            if extreme is not None:
                distance = ((extreme - current) * side_sign / current) * 100.0
                result[f"directional_extreme_distance_{minutes}m_pct"] = max(0.0, distance)
            else:
                result[f"directional_extreme_distance_{minutes}m_pct"] = None
        else:
            result[f"directional_extreme_distance_{minutes}m_pct"] = None
    rows_60 = _window(feed_times, feed_rows, cutoff, 60)
    funding_values = [row["funding"] for row in rows_60 if row.get("funding") is not None]
    result["funding_last"] = funding_values[-1] if funding_values else None
    result["funding_trusted_60m"] = not any(
        row.get("recovery_class") not in {"REAL_ENRICHED", "OUTSIDE_RECOVERY_SIDECAR"}
        for row in rows_60
    )
    result["feed_has_synthetic_240m"] = any(row.get("synthetic") for row in _window(feed_times, feed_rows, cutoff, 240))
    return result


def _peak_history_features(all_events: Sequence[Dict[str, Any]], signal: Dict[str, Any]) -> Dict[str, Any]:
    cutoff = signal["_dt_local"]
    kind = str(signal.get("kind") or "").lower()
    current_abs_delta = abs(_num(signal.get("delta")) or 0.0)
    prior_24h = [
        row
        for row in all_events
        if cutoff - timedelta(hours=24) <= row["_dt_local"] <= cutoff
        and str(row.get("kind") or "").lower() == kind
        and _num(row.get("delta")) is not None
    ]
    values = sorted(abs(_num(row.get("delta")) or 0.0) for row in prior_24h)
    percentile = None
    if values:
        percentile = sum(value <= current_abs_delta for value in values) / len(values) * 100.0
    prior_only = [row for row in all_events if row["_dt_local"] < cutoff]
    return {
        "same_side_peak_count_24h": len(values),
        "peak_delta_percentile_24h": percentile,
        "prior_same_side_peak_count_60m": sum(
            cutoff - timedelta(minutes=60) <= row["_dt_local"]
            and str(row.get("kind") or "").lower() == kind
            for row in prior_only
        ),
        "prior_same_side_peak_count_240m": sum(
            cutoff - timedelta(minutes=240) <= row["_dt_local"]
            and str(row.get("kind") or "").lower() == kind
            for row in prior_only
        ),
        "prior_opposite_peak_count_60m": sum(
            cutoff - timedelta(minutes=60) <= row["_dt_local"]
            and str(row.get("kind") or "").lower() != kind
            for row in prior_only
        ),
    }


def _session(hour: int) -> str:
    if hour < 8:
        return "asia"
    if hour < 14:
        return "europe"
    if hour < 22:
        return "us_overlap"
    return "late"


def _patterns(row: Dict[str, Any]) -> Dict[str, Optional[bool]]:
    sign = row["side_sign"]
    price = row.get("signal_price")
    poc = row.get("poc")
    funding = row.get("funding_last")
    ret60 = row.get("ret_60m_pct_feed")
    oi60 = row.get("oi_change_60m")
    aligned_move60 = ret60 * sign if ret60 is not None else None
    return {
        "near_60m_extreme": (
            row.get("directional_extreme_distance_60m_pct") <= 0.15
            if row.get("directional_extreme_distance_60m_pct") is not None
            else None
        ),
        "near_240m_extreme": (
            row.get("directional_extreme_distance_240m_pct") <= 0.25
            if row.get("directional_extreme_distance_240m_pct") is not None
            else None
        ),
        "vwap_extension_ge_0_5pct": (
            row.get("vwap_extension_abs_pct") >= 0.5 if row.get("vwap_extension_abs_pct") is not None else None
        ),
        "weak_or_mid_peak_percentile": (
            row.get("peak_delta_percentile_24h") <= 50.0
            if row.get("peak_delta_percentile_24h") is not None
            else None
        ),
        "oi_down_60m": oi60 < 0 if oi60 is not None and row.get("oi_trusted_60m") else None,
        "oi_down_240m": (
            row.get("oi_change_240m") < 0
            if row.get("oi_change_240m") is not None and row.get("oi_trusted_240m")
            else None
        ),
        "directional_move_with_oi_down_60m": (
            aligned_move60 > 0 and oi60 < 0
            if aligned_move60 is not None and oi60 is not None and row.get("oi_trusted_60m")
            else None
        ),
        "counterflow_delta_60m": (
            row.get("buy_sell_delta_60m") * sign <= 0
            if row.get("buy_sell_delta_60m") is not None
            else None
        ),
        "broad_delta_conflict_24h": (
            row.get("cum_delta_24h") * sign <= 0 if row.get("cum_delta_24h") is not None else None
        ),
        "momentum_chase_60m": (
            aligned_move60 > 0 and row.get("directional_extreme_distance_60m_pct") <= 0.15
            if aligned_move60 is not None and row.get("directional_extreme_distance_60m_pct") is not None
            else None
        ),
        "poc_ahead": ((poc - price) * sign > 0 if poc is not None and price is not None else None),
        "prior_same_side_peak_240m": (
            row.get("prior_same_side_peak_count_240m") > 0
            if row.get("prior_same_side_peak_count_240m") is not None
            else None
        ),
        "crowded_funding": funding * sign > 0 if funding is not None and row.get("funding_trusted_60m") else None,
    }


def _diagnostic_family(patterns: Dict[str, Optional[bool]]) -> str:
    """Assign one descriptive family in explicit priority order; this is not a causal label."""
    if patterns.get("oi_down_240m") is True:
        return "deleveraging_or_missing_position_build_240m"
    if patterns.get("oi_down_240m") is None:
        return "oi_quality_gap"
    if patterns.get("broad_delta_conflict_24h") is True:
        return "broad_delta_conflict"
    if patterns.get("weak_or_mid_peak_percentile") is True:
        return "weak_or_mid_delta_candidate"
    if patterns.get("momentum_chase_60m") is True:
        return "late_momentum_chase"
    if patterns.get("counterflow_delta_60m") is True:
        return "short_horizon_counterflow"
    return "unresolved_other"


def _make_feature_row(
    *,
    outcome_group: str,
    provenance: str,
    signal: Dict[str, Any],
    last_closed: Optional[Dict[str, Any]],
    feed_times: Sequence[datetime],
    feed_rows: Sequence[Dict[str, Any]],
    all_events: Sequence[Dict[str, Any]],
    verdict: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    side = str(signal.get("kind") or (last_closed or {}).get("side") or "").lower()
    sign = 1 if side == "long" else -1
    cutoff = signal["_dt_local"]
    feed_cutoff = _feed_utc_naive_from_local(cutoff)
    price = _num(signal.get("price"))
    vwap = _num(signal.get("vwap"))
    poc = _num(signal.get("poc"))
    row: Dict[str, Any] = {
        "outcome_group": outcome_group,
        "provenance": provenance,
        "trade_key": (last_closed or {}).get("trade_key"),
        "signal_ts_local": cutoff.isoformat(sep=" "),
        "side": side,
        "side_sign": sign,
        "session": _session(cutoff.hour),
        "signal_price": price,
        "delta": _num(signal.get("delta")),
        "abs_delta": abs(_num(signal.get("delta")) or 0.0),
        "volume": _num(signal.get("vol")),
        "imbalance": _num(signal.get("imb")),
        "vwap": vwap,
        "poc": poc,
        "vwap_extension_abs_pct": abs((price - vwap) / vwap * 100.0) if price and vwap else None,
        "cum_delta_24h": _num(signal.get("cum_delta_24h")),
        "cum_delta_180m": _num(signal.get("cum_delta_180m")),
        "cum_delta_60m": _num(signal.get("cum_delta_60m")),
        "ret_15m_review": _num(signal.get("ret_15m")),
        "ret_60m_review": _num(signal.get("ret_60m")),
        "entry_actual": _num((last_closed or {}).get("entry_actual")),
        "duration_minutes": (
            (_parse_utc((last_closed or {})["ts"]) - _parse_utc((last_closed or {})["opened_at"])).total_seconds()
            / 60.0
            if last_closed and last_closed.get("ts") and last_closed.get("opened_at")
            else None
        ),
        "stop_distance_pct": None,
        "llm_verdict": verdict.get("verdict") if verdict else None,
        "llm_confidence": _num(verdict.get("confidence")) if verdict else None,
        "llm_setup_class": verdict.get("setup_class") if verdict else None,
        "llm_reason_codes": verdict.get("reason_codes") if verdict else [],
        "llm_risk_flags": verdict.get("risk_flags") if verdict else [],
    }
    if last_closed:
        prices = last_closed.get("prices") if isinstance(last_closed.get("prices"), dict) else {}
        actual = row["entry_actual"]
        stop = _num(prices.get("sl"))
        row["stop_distance_pct"] = abs(actual - stop) / actual * 100.0 if actual and stop else None
    feed = _feed_features(feed_times, feed_rows, feed_cutoff, sign)
    row["feed_cutoff_ts_utc"] = feed_cutoff.isoformat(sep=" ")
    row.update(feed)
    row["ret_15m_pct_feed"] = row.pop("ret_15m_pct")
    row["ret_60m_pct_feed"] = row.pop("ret_60m_pct")
    row["ret_240m_pct_feed"] = row.pop("ret_240m_pct")
    for minutes in (15, 60, 240):
        raw_delta = row.get(f"buy_sell_delta_{minutes}m")
        raw_delta_pct = row.get(f"buy_sell_delta_pct_{minutes}m")
        row[f"directional_delta_{minutes}m"] = raw_delta * sign if raw_delta is not None else None
        row[f"directional_delta_pct_{minutes}m"] = raw_delta_pct * sign if raw_delta_pct is not None else None
    delta_240 = row.get("directional_delta_240m")
    delta_pct_240 = row.get("directional_delta_pct_240m")
    row["flow_concentration_15_240"] = (
        row["directional_delta_15m"] / abs(delta_240)
        if row.get("directional_delta_15m") is not None and delta_240
        else None
    )
    row["flow_concentration_60_240"] = (
        row["directional_delta_60m"] / abs(delta_240)
        if row.get("directional_delta_60m") is not None and delta_240
        else None
    )
    row["delta_efficiency_acceleration_15_240"] = (
        row["directional_delta_pct_15m"] / abs(delta_pct_240)
        if row.get("directional_delta_pct_15m") is not None and delta_pct_240
        else None
    )
    row.update(_peak_history_features(all_events, signal))
    row["patterns"] = _patterns(row)
    row["diagnostic_family"] = _diagnostic_family(row["patterns"])
    return row


def _rate(rows: Sequence[Dict[str, Any]], key: str) -> Dict[str, Any]:
    values = [row["patterns"].get(key) for row in rows if row["patterns"].get(key) is not None]
    count = sum(value is True for value in values)
    return {"count": count, "denominator": len(values), "rate": count / len(values) if values else None}


def _fisher_two_sided(left: Dict[str, Any], right: Dict[str, Any]) -> Optional[float]:
    if not left["denominator"] or not right["denominator"]:
        return None
    a = int(left["count"])
    b = int(left["denominator"] - left["count"])
    c = int(right["count"])
    d = int(right["denominator"] - right["count"])
    row_one = a + b
    column_one = a + c
    total = a + b + c + d

    def probability(x: int) -> float:
        return math.comb(column_one, x) * math.comb(total - column_one, row_one - x) / math.comb(total, row_one)

    low = max(0, row_one - (total - column_one))
    high = min(row_one, column_one)
    observed = probability(a)
    return min(1.0, sum(probability(x) for x in range(low, high + 1) if probability(x) <= observed + 1e-12))


def _median(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    values = []
    for row in rows:
        if key == "oi_change_60m" and not row.get("oi_trusted_60m"):
            continue
        if key == "oi_change_240m" and not row.get("oi_trusted_240m"):
            continue
        if row.get(key) is not None:
            values.append(row.get(key))
    return median(values) if values else None


def _pair_rate(rows: Sequence[Dict[str, Any]], left: str, right: str) -> Dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row["patterns"].get(left) is not None and row["patterns"].get(right) is not None
    ]
    count = sum(row["patterns"].get(left) is True and row["patterns"].get(right) is True for row in eligible)
    return {"count": count, "denominator": len(eligible), "rate": count / len(eligible) if eligible else None}


def _theme_flags(record: Dict[str, Any]) -> set[str]:
    text = " ".join(
        str(value).lower()
        for value in (record.get("reason_codes") or []) + (record.get("risk_flags") or [])
    )
    themes = set()
    if any(token in text for token in ("late", "chase", "extreme", "extended", "stretched")):
        themes.add("late_or_extended_entry")
    if any(token in text for token in ("oi_decline", "open_interest_down", "oi_down", "short_cover", "unwind")):
        themes.add("oi_unwind_or_covering")
    if any(token in text for token in ("resistance", "supply", "liquidity", "zone", "poc")):
        themes.add("nearby_level_or_liquidity")
    if any(token in text for token in ("weak", "moderate_peak", "peak_strength", "modest")):
        themes.add("weak_or_moderate_peak")
    if any(token in text for token in ("conflict", "mixed", "higher_timeframe", "broad_context")):
        themes.add("broader_context_conflict")
    return themes


def build(material: Path, output_json: Path, output_md: Path) -> Dict[str, Any]:
    accepted = _load_accepted(material)
    all_events = _load_all_peak_events(material)
    feed_times, feed_rows = _load_feed(material)
    outcome_records = _read_jsonl(material / "server_state" / "trade_outcomes.jsonl")
    verdict_records = [
        row
        for row in _read_jsonl(material / "server_state" / "llm_trade_verdicts.jsonl")
        if row.get("is_primary") is True and row.get("llm_call_status") == "success"
    ]
    verdict_by_trade = {str(row.get("trade_key")): row for row in verdict_records if row.get("trade_key")}

    feature_rows: List[Dict[str, Any]] = []
    excluded_test_trades: List[str] = []
    unmatched: List[str] = []
    known_signal_keys: set[tuple[str, str]] = set()
    for obj in outcome_records:
        lc = obj.get("last_closed") if isinstance(obj.get("last_closed"), dict) else {}
        key = str(lc.get("trade_key") or "")
        if obj.get("excluded_from_scoring") is True or obj.get("test_trade") is True:
            excluded_test_trades.append(key)
            continue
        group = _lifecycle(lc)
        if group == UNKNOWN or not lc.get("side") or not lc.get("opened_at"):
            continue
        opened_local = _parse_utc(lc["opened_at"]).astimezone(LOCAL_TZ).replace(tzinfo=None)
        signal = _nearest_signal(accepted, str(lc["side"]), opened_local)
        if signal is None:
            unmatched.append(key)
            continue
        signal_key = (signal["_dt_local"].isoformat(), str(signal.get("kind") or "").lower())
        known_signal_keys.add(signal_key)
        feature_rows.append(
            _make_feature_row(
                outcome_group=group,
                provenance="canonical_trade_outcome",
                signal=signal,
                last_closed=lc,
                feed_times=feed_times,
                feed_rows=feed_rows,
                all_events=all_events,
                verdict=verdict_by_trade.get(key),
            )
        )

    ledger_path = material / "reviews" / "accepted_outcome_ledger_2026-03-17_to_2026-05-02.csv"
    supplemented: List[str] = []
    if ledger_path.exists():
        for ledger in _read_csv(ledger_path):
            if ledger.get("lifecycle_bucket") not in {
                "manual_confirmed_sl_result",
                "user_confirmed_sl_without_artifact_join",
            }:
                continue
            ts = _local_naive(ledger["accepted_ts"])
            side = str(ledger.get("side") or "").lower()
            signal_key = (ts.isoformat(), side)
            if signal_key in known_signal_keys:
                continue
            signal = min(
                (
                    row
                    for row in accepted
                    if str(row.get("kind") or "").lower() == side
                ),
                key=lambda row: abs((row["_dt_local"] - ts).total_seconds()),
                default=None,
            )
            if signal is None or abs((signal["_dt_local"] - ts).total_seconds()) > 1:
                unmatched.append(f"supplement:{ledger.get('accepted_ts')}:{side}")
                continue
            supplemented.append(f"{ledger.get('accepted_ts')}:{side}")
            feature_rows.append(
                _make_feature_row(
                    outcome_group=PLAIN_LOSS,
                    provenance=ledger.get("lifecycle_bucket") or "user_confirmed",
                    signal=signal,
                    last_closed=None,
                    feed_times=feed_times,
                    feed_rows=feed_rows,
                    all_events=all_events,
                    verdict=None,
                )
            )

    losses = [row for row in feature_rows if row["outcome_group"] == PLAIN_LOSS]
    protected = [row for row in feature_rows if row["outcome_group"] == PROTECTED]
    tp1_stops = [row for row in feature_rows if row["outcome_group"] == TP1_STOP]

    pattern_comparison = []
    for key, label in PATTERN_LABELS.items():
        loss_rate = _rate(losses, key)
        protected_rate = _rate(protected, key)
        tp1_stop_rate = _rate(tp1_stops, key)
        difference = (
            loss_rate["rate"] - protected_rate["rate"]
            if loss_rate["rate"] is not None and protected_rate["rate"] is not None
            else None
        )
        pattern_comparison.append(
            {
                "pattern": key,
                "label": label,
                "loss": loss_rate,
                "protected": protected_rate,
                "tp1_then_stop": tp1_stop_rate,
                "loss_minus_protected_rate": difference,
                "fisher_exact_two_sided_p": _fisher_two_sided(loss_rate, protected_rate),
            }
        )
    pattern_comparison.sort(
        key=lambda row: (
            row["loss_minus_protected_rate"] if row["loss_minus_protected_rate"] is not None else -2,
            row["loss"]["rate"] if row["loss"]["rate"] is not None else -1,
        ),
        reverse=True,
    )

    numeric = {}
    for key in (
        "abs_delta",
        "imbalance",
        "vwap_extension_abs_pct",
        "peak_delta_percentile_24h",
        "directional_extreme_distance_60m_pct",
        "directional_extreme_distance_240m_pct",
        "oi_change_60m",
        "oi_change_240m",
        "directional_delta_240m",
        "directional_delta_pct_240m",
        "flow_concentration_15_240",
        "flow_concentration_60_240",
        "delta_efficiency_acceleration_15_240",
        "ret_60m_pct_feed",
        "duration_minutes",
    ):
        numeric[key] = {
            "loss_median": _median(losses, key),
            "protected_median": _median(protected, key),
            "tp1_stop_median": _median(tp1_stops, key),
        }

    pair_comparison = []
    for left, right in combinations(PATTERN_LABELS, 2):
        loss_rate = _pair_rate(losses, left, right)
        protected_rate = _pair_rate(protected, left, right)
        difference = (
            loss_rate["rate"] - protected_rate["rate"]
            if loss_rate["rate"] is not None and protected_rate["rate"] is not None
            else None
        )
        if loss_rate["count"] < 2:
            continue
        pair_comparison.append(
            {
                "patterns": [left, right],
                "loss": loss_rate,
                "protected": protected_rate,
                "loss_minus_protected_rate": difference,
            }
        )
    pair_comparison.sort(
        key=lambda row: (
            row["loss_minus_protected_rate"] if row["loss_minus_protected_rate"] is not None else -2,
            row["loss"]["rate"] if row["loss"]["rate"] is not None else -1,
        ),
        reverse=True,
    )

    outcome_group_by_trade = {}
    for obj in outcome_records:
        if obj.get("excluded_from_scoring") is True or obj.get("test_trade") is True:
            continue
        lc = obj.get("last_closed") if isinstance(obj.get("last_closed"), dict) else {}
        if lc.get("trade_key"):
            outcome_group_by_trade[str(lc["trade_key"])] = _lifecycle(lc)
    llm_by_group: Dict[str, Any] = {}
    for group in (PLAIN_LOSS, PROTECTED, TP1_STOP):
        cohort = [
            row
            for row in verdict_records
            if outcome_group_by_trade.get(str(row.get("trade_key") or "")) == group
        ]
        verdict_counts = Counter(row.get("verdict") for row in cohort)
        theme_counts = Counter()
        for row in cohort:
            theme_counts.update(_theme_flags(row))
        llm_by_group[group] = {
            "count": len(cohort),
            "verdict_counts": dict(verdict_counts),
            "theme_counts": dict(theme_counts),
        }

    result = {
        "schema_version": "losing_trade_commonality_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "first_signal_ts_local": min(row["signal_ts_local"] for row in feature_rows),
            "last_signal_ts_local": max(row["signal_ts_local"] for row in feature_rows),
            "canonical_outcome_records": len(outcome_records),
            "known_plain_losses": len(losses),
            "canonical_plain_losses": sum(row["provenance"] == "canonical_trade_outcome" for row in losses),
            "user_confirmed_plain_losses": sum(row["provenance"] != "canonical_trade_outcome" for row in losses),
            "canonical_protected_profit_total": sum(
                _lifecycle(obj.get("last_closed") or {}) == PROTECTED
                and obj.get("excluded_from_scoring") is not True
                for obj in outcome_records
            ),
            "protected_profit_controls_with_signal_join": len(protected),
            "tp1_then_stop_separate": len(tp1_stops),
            "excluded_test_trades": excluded_test_trades,
            "supplemented_user_confirmed": supplemented,
            "unmatched_trade_keys": unmatched,
        },
        "pattern_comparison": pattern_comparison,
        "numeric_medians": numeric,
        "top_loss_pattern_pairs": pair_comparison[:12],
        "side_counts": {
            "loss": dict(Counter(row["side"] for row in losses)),
            "protected": dict(Counter(row["side"] for row in protected)),
            "tp1_then_stop": dict(Counter(row["side"] for row in tp1_stops)),
        },
        "session_counts": {
            "loss": dict(Counter(row["session"] for row in losses)),
            "protected": dict(Counter(row["session"] for row in protected)),
        },
        "loss_diagnostic_family_counts": dict(Counter(row["diagnostic_family"] for row in losses)),
        "llm_subcohort": llm_by_group,
        "trades": feature_rows,
        "contracts": {
            "loss_definition": "plain SL with no TP/trailing flags, plus two explicitly user-confirmed plain SL rows",
            "protected_control_definition": "TP1 and TP2 reached with trailing active before final SL event",
            "tp1_stop_treatment": "reported separately because exact net PnL is not available in trade_outcomes.jsonl",
            "feature_boundary": (
                "DeltaScout event times are Europe/Bratislava local-naive; effective_feed timestamps are UTC-naive. "
                "Feed features use rows at or before the event time converted to UTC."
            ),
        },
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    pattern_by_name = {item["pattern"]: item for item in pattern_comparison}
    oi240_comparison = pattern_by_name["oi_down_240m"]
    oi60_comparison = pattern_by_name["oi_down_60m"]
    latest_protected = max(protected, key=lambda item: item["signal_ts_local"])

    lines = [
        "# Losing Trade Commonality Review",
        "",
        "## Scope and outcome contract",
        "",
        f"- Known plain losses: **{len(losses)}** ({result['scope']['canonical_plain_losses']} canonical + {result['scope']['user_confirmed_plain_losses']} user-confirmed).",
        f"- Protected-profit controls with comparable signal joins: **{len(protected)}** of **{result['scope']['canonical_protected_profit_total']}** (`TP1 + TP2 + trailing`).",
        f"- TP1-then-stop cases kept separate: **{len(tp1_stops)}**.",
        f"- Operator test trades excluded: **{len(excluded_test_trades)}** (`{', '.join(excluded_test_trades)}`).",
        "- Every market feature is pre-entry/cutoff-safe. Final outcome is used only as the cohort label.",
        "- Timestamp contract: DeltaScout events are Europe/Bratislava local-naive; effective feed rows are UTC-naive and are joined only after conversion to UTC.",
        "",
        "## Pattern prevalence: losses versus protected-profit controls",
        "",
        "| Pattern | Plain losses | TP1→stop | Protected controls | Loss−protected | Fisher p (exploratory) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in pattern_comparison:
        loss = item["loss"]
        win = item["protected"]
        partial = item["tp1_then_stop"]
        diff = item["loss_minus_protected_rate"]
        lines.append(
            f"| {item['label']} | {_pct_text(loss['count'], loss['denominator'])} | "
            f"{_pct_text(partial['count'], partial['denominator'])} | "
            f"{_pct_text(win['count'], win['denominator'])} | "
            f"{('n/a' if diff is None else f'{diff * 100:+.0f} pp')} | "
            f"{_fmt(item.get('fisher_exact_two_sided_p'), 3) or 'n/a'} |"
        )

    lines.extend(
        [
            "",
            "## Descriptive loss families",
            "",
            "The families below are mutually exclusive and assigned in this priority order: trusted 240m OI decline, OI-quality gap, broad-delta conflict, weak candidate, momentum chase, short-horizon counterflow, unresolved.",
            "",
            "| Diagnostic family | Count | Share of known losses |",
            "|---|---:|---:|",
        ]
    )
    for family, count in sorted(result["loss_diagnostic_family_counts"].items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{family}` | {count} | {count / len(losses) * 100:.0f}% |")

    lines.extend(
        [
            "",
            "## Numeric medians",
            "",
            "| Feature | Plain loss | Protected | TP1→stop |",
            "|---|---:|---:|---:|",
        ]
    )
    for key, values in numeric.items():
        lines.append(
            f"| `{key}` | {_fmt(values['loss_median'])} | {_fmt(values['protected_median'])} | {_fmt(values['tp1_stop_median'])} |"
        )

    lines.extend(
        [
            "",
            "## Strongest loss pattern pairs",
            "",
            "| Pair | Plain losses | Protected controls | Difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for item in result["top_loss_pattern_pairs"]:
        loss = item["loss"]
        win = item["protected"]
        diff = item["loss_minus_protected_rate"]
        lines.append(
            f"| `{' + '.join(item['patterns'])}` | {_pct_text(loss['count'], loss['denominator'])} | "
            f"{_pct_text(win['count'], win['denominator'])} | "
            f"{('n/a' if diff is None else f'{diff * 100:+.0f} pp')} |"
        )

    lines.extend(
        [
            "",
            "## LLM-judged subcohort",
            "",
            "| Outcome group | Judged trades | Verdict counts | Repeated risk themes |",
            "|---|---:|---|---|",
        ]
    )
    for group, data in llm_by_group.items():
        verdict_text = ", ".join(f"{key}={value}" for key, value in sorted(data["verdict_counts"].items())) or "none"
        theme_text = ", ".join(f"{key}={value}" for key, value in sorted(data["theme_counts"].items())) or "none"
        lines.append(f"| `{group}` | {data['count']} | {verdict_text} | {theme_text} |")

    lines.extend(
        [
            "",
            "## Shadow-policy decision",
            "",
            f"- Do **not** use `oi_change_240m < 0` as a live veto or automatic penalty. After correcting the local-to-UTC feed join it appears in {_pct_text(oi240_comparison['loss']['count'], oi240_comparison['loss']['denominator'])} plain losses and {_pct_text(oi240_comparison['protected']['count'], oi240_comparison['protected']['denominator'])} protected controls (exploratory Fisher p={_fmt(oi240_comparison.get('fisher_exact_two_sided_p'), 3)}).",
            f"- `oi_change_60m < 0` remains a shadow-only candidate: {_pct_text(oi60_comparison['loss']['count'], oi60_comparison['loss']['denominator'])} losses versus {_pct_text(oi60_comparison['protected']['count'], oi60_comparison['protected']['denominator'])} protected controls, but the current sample is not decisive (p={_fmt(oi60_comparison.get('fisher_exact_two_sided_p'), 3)}).",
            f"- Latest protected trade `{latest_protected.get('trade_key')}` is a direct counterexample: OI Δ15={_fmt(latest_protected.get('oi_change_15m'))}, Δ60={_fmt(latest_protected.get('oi_change_60m'))}, Δ240={_fmt(latest_protected.get('oi_change_240m'))}, while its lifecycle reached TP1, TP2 and trailing protection.",
            "- Implementation target: journal the OI windows and a descriptive participation label, then calibrate prospectively against outcomes. Keep it out of order admission until enough shadow observations establish incremental value beyond the existing LLM verdict.",
        ]
    )

    lines.extend(
        [
            "",
            "## Per-loss audit table",
            "",
            "| Signal local | Side | Provenance | Δ | Imb | VWAP ext % | 60m extreme dist % | OI Δ60 | Peak pctile | LLM | Active patterns |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in sorted(losses, key=lambda item: item["signal_ts_local"]):
        active = ", ".join(key for key, value in row["patterns"].items() if value is True)
        lines.append(
            f"| {row['signal_ts_local']} | {row['side']} | `{row['provenance']}` | {_fmt(row['delta'])} | "
            f"{_fmt(row['imbalance'], 3)} | {_fmt(row['vwap_extension_abs_pct'], 3)} | "
            f"{_fmt(row['directional_extreme_distance_60m_pct'], 3)} | {_fmt(row['oi_change_60m'])} | "
            f"{_fmt(row['peak_delta_percentile_24h'])} | {row.get('llm_verdict') or ''} | {active} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- `SL` alone is not a loss label; lifecycle flags control classification.",
            "- Pattern prevalence is descriptive, not a causal proof or a ready-to-deploy trading rule.",
            "- Fisher p-values are exploratory and unadjusted for multiple comparisons; the sample remains small.",
            "- Protected controls are a small sample and one early control lacks an accepted-event join, so denominators are shown for every rate.",
            "- The two user-confirmed losses have no canonical trade key/duration and remain visibly separated by provenance.",
        ]
    )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--material-root",
        type=Path,
        default=Path("deltascout/research_material"),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("deltascout/research_material/reviews/losing_trade_commonality_2026-03-20_to_2026-08-20.json"),
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("deltascout/research_material/reviews/losing_trade_commonality_2026-03-20_to_2026-08-20.md"),
    )
    args = parser.parse_args()
    result = build(args.material_root, args.output_json, args.output_md)
    print(json.dumps(result["scope"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
