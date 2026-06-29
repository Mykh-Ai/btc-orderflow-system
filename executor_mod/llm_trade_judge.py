"""LLM Trade Judge foundation.

The judge is advisory only. It never opens, closes, or modifies orders.
The durable artifact is an append-only JSONL verdict journal.
"""
from __future__ import annotations

import json
import os
import time
import uuid
import csv
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

ENV: Dict[str, Any] = {
    "SYMBOL": os.getenv("SYMBOL", "BTCUSDC"),
    "LLM_TRADE_JUDGE_ENABLED": os.getenv("LLM_TRADE_JUDGE_ENABLED", "false"),
    "LLM_TRADE_JUDGE_VERDICTS_FN": os.getenv("LLM_TRADE_JUDGE_VERDICTS_FN", "/data/state/llm_trade_verdicts.jsonl"),
    "LLM_TRADE_JUDGE_MODE": os.getenv("LLM_TRADE_JUDGE_MODE", "stub"),
    "LLM_TRADE_JUDGE_MODEL": os.getenv("LLM_TRADE_JUDGE_MODEL", "gpt-5.5"),
    "LLM_TRADE_JUDGE_TIMEOUT_SEC": os.getenv("LLM_TRADE_JUDGE_TIMEOUT_SEC", "20"),
    "LLM_TRADE_JUDGE_MAX_RETRIES": os.getenv("LLM_TRADE_JUDGE_MAX_RETRIES", "1"),
    "LLM_TRADE_JUDGE_NOTIFY_TELEGRAM": os.getenv("LLM_TRADE_JUDGE_NOTIFY_TELEGRAM", "true"),
    "LLM_TRADE_JUDGE_CONTEXT_ENABLED": os.getenv("LLM_TRADE_JUDGE_CONTEXT_ENABLED", "true"),
    "LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS": os.getenv("LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS", "24"),
    "LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS": os.getenv("LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS", "5000"),
    "LLM_TRADE_JUDGE_DELTASCOUT_LOG": os.getenv("LLM_TRADE_JUDGE_DELTASCOUT_LOG", os.getenv("DELTASCOUT_LOG", "/data/logs/deltascout.log")),
    "LLM_TRADE_JUDGE_AGG_CSV": os.getenv("LLM_TRADE_JUDGE_AGG_CSV", os.getenv("AGG_CSV", "/data/feed/aggregated.csv")),
    "LLM_TRADE_JUDGE_FEED_TIMEZONE": os.getenv("LLM_TRADE_JUDGE_FEED_TIMEZONE", os.getenv("FEED_SOURCE_TIMEZONE", "Europe/Bratislava")),
    "LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED": os.getenv("LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED", "false"),
    "LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED": os.getenv("LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED", ""),
    "LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED": os.getenv("LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED", ""),
    "LLM_TRADE_JUDGE_MARKET_MONITOR_MAX_ZONES": os.getenv("LLM_TRADE_JUDGE_MARKET_MONITOR_MAX_ZONES", "5"),
}

save_state: Optional[Callable[[dict], None]] = None
log_event: Optional[Callable[..., None]] = None
send_webhook: Optional[Callable[[dict], None]] = None
openai_client: Optional[Callable[..., Any]] = None

ALLOWED_VERDICTS = {"SUPPORT", "REJECT", "UNCLEAR"}
ALLOWED_SETUP_CLASSES = {
    "continuation_pressure",
    "reversal_onset",
    "reversal_confirmation",
    "exhaustion",
    "trap_false_break",
    "absorption_like",
    "honest_directional_flow",
    "noisy_peak",
    "unknown",
}


def configure(
    env: Dict[str, Any],
    *,
    save_state_fn: Optional[Callable[[dict], None]] = None,
    log_event_fn: Optional[Callable[..., None]] = None,
    send_webhook_fn: Optional[Callable[[dict], None]] = None,
    openai_client_fn: Optional[Callable[..., Any]] = None,
) -> None:
    global ENV, save_state, log_event, send_webhook, openai_client
    ENV = env
    save_state = save_state_fn
    log_event = log_event_fn
    send_webhook = send_webhook_fn
    openai_client = openai_client_fn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_enabled() -> bool:
    raw = ENV.get("LLM_TRADE_JUDGE_ENABLED", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _journal_path() -> str:
    return str(ENV.get("LLM_TRADE_JUDGE_VERDICTS_FN") or "/data/state/llm_trade_verdicts.jsonl")


def _feed_timezone(env: Optional[Dict[str, Any]] = None) -> str:
    cfg = env if isinstance(env, dict) else ENV
    return str(
        cfg.get("LLM_TRADE_JUDGE_FEED_TIMEZONE")
        or cfg.get("FEED_SOURCE_TIMEZONE")
        or "Europe/Bratislava"
    )


def _zoneinfo(name: Any) -> Optional[ZoneInfo]:
    try:
        return ZoneInfo(str(name or "UTC"))
    except Exception:
        return None


def isoformat_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt_safe(value: Any, *, naive_tz: Optional[str] = None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = None
        for candidate in (text, text.replace(" ", "T", 1)):
            try:
                dt = datetime.fromisoformat(candidate)
                break
            except Exception:
                pass
        if dt is None:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except Exception:
                    pass
        if dt is None:
            return None
    if dt.tzinfo is None:
        if not naive_tz:
            return None
        tz = _zoneinfo(naive_tz)
        if tz is None:
            return None
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def normalize_feed_ts(value: Any, source_timezone: str) -> Dict[str, Any]:
    raw = value
    parsed_original = value if isinstance(value, datetime) else None
    if parsed_original is None and value is not None:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed_original = datetime.fromisoformat(text)
        except Exception:
            parsed_original = None
    dt = parse_dt_safe(value)
    if dt is not None:
        dt_utc = dt.astimezone(timezone.utc)
        original_offset = parsed_original.utcoffset() if isinstance(parsed_original, datetime) and parsed_original.tzinfo is not None else None
        contract = "utc_iso8601" if original_offset == timedelta(0) else "aware_input_normalized_utc"
        return {
            "dt_utc": dt_utc,
            "ts_utc": isoformat_z(dt_utc),
            "ts_raw": raw,
            "ts_source_timezone": None,
            "ts_normalized": isoformat_z(dt_utc) != str(raw),
            "timestamp_contract": contract,
        }

    dt = parse_dt_safe(value, naive_tz=source_timezone)
    if dt is None:
        return {
            "dt_utc": None,
            "ts_utc": None,
            "ts_raw": raw,
            "ts_source_timezone": source_timezone,
            "ts_normalized": False,
            "timestamp_contract": "invalid_timestamp",
        }
    return {
        "dt_utc": dt,
        "ts_utc": isoformat_z(dt),
        "ts_raw": raw,
        "ts_source_timezone": source_timezone,
        "ts_normalized": True,
        "timestamp_contract": "legacy_feed_local_naive",
    }


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _event_public_fields(evt: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in (
        "ts",
        "ts_raw",
        "ts_utc",
        "timestamp_contract",
        "kind",
        "delta",
        "vol",
        "imb",
        "price",
        "vwap",
        "poc",
        "source",
        "action",
    ):
        if key in evt:
            out[key] = evt.get(key)
    return out


def _market_dt(value: Any) -> Optional[datetime]:
    return parse_dt_safe(value, naive_tz=_feed_timezone())


def _event_dt(evt: Dict[str, Any]) -> Optional[datetime]:
    if not isinstance(evt, dict):
        return None
    return parse_dt_safe(evt.get("ts_utc")) or _market_dt(evt.get("ts"))


def get_trade_key(pos: Dict[str, Any]) -> Optional[str]:
    if not isinstance(pos, dict):
        return None
    for key in ("trade_key", "client_id", "clientOrderId", "order_id", "orderId"):
        value = pos.get(key)
        if value:
            return str(value)
    return None


def choose_analysis_cutoff(pos: Dict[str, Any]) -> Dict[str, Any]:
    data_gaps = []
    source_tz = _feed_timezone()
    src_evt = pos.get("src_evt") if isinstance(pos, dict) else None
    if isinstance(src_evt, dict) and src_evt.get("ts"):
        ts_norm = normalize_feed_ts(src_evt.get("ts"), source_tz)
        if not ts_norm.get("ts_utc"):
            data_gaps.append("invalid_src_evt_ts")
            return {
                "peak_ts": None,
                "peak_ts_raw": src_evt.get("ts"),
                "analysis_cutoff_ts": None,
                "cutoff_source": "position.src_evt.ts",
                "ts_source_timezone": source_tz,
                "ts_normalized": False,
                "timestamp_contract": "invalid_timestamp",
                "data_gaps": data_gaps,
            }
        return {
            "peak_ts": ts_norm.get("ts_utc"),
            "peak_ts_raw": ts_norm.get("ts_raw"),
            "analysis_cutoff_ts": ts_norm.get("ts_utc"),
            "cutoff_source": "position.src_evt.ts",
            "ts_source_timezone": ts_norm.get("ts_source_timezone"),
            "ts_normalized": ts_norm.get("ts_normalized"),
            "timestamp_contract": ts_norm.get("timestamp_contract"),
            "data_gaps": data_gaps,
        }

    fallback_ts = None
    if isinstance(pos, dict):
        fallback_ts = pos.get("filled_at") or pos.get("opened_at")
    if fallback_ts:
        dt = parse_dt_safe(fallback_ts)
        ts_utc = isoformat_z(dt) if dt is not None else None
        if ts_utc is None:
            data_gaps.append("invalid_entry_fallback_ts")
        return {
            "peak_ts": None,
            "peak_ts_raw": None,
            "analysis_cutoff_ts": ts_utc,
            "cutoff_source": "entry_ts_fallback",
            "ts_source_timezone": None,
            "ts_normalized": bool(ts_utc and ts_utc != str(fallback_ts)),
            "timestamp_contract": "utc_iso8601" if ts_utc else "invalid_timestamp",
            "data_gaps": data_gaps,
        }

    data_gaps.append("missing_analysis_cutoff_ts")
    return {
        "peak_ts": None,
        "peak_ts_raw": None,
        "analysis_cutoff_ts": None,
        "cutoff_source": "missing",
        "ts_source_timezone": None,
        "ts_normalized": False,
        "timestamp_contract": "missing",
        "data_gaps": data_gaps,
    }


def read_deltascout_events_until_cutoff(
    path: str,
    cutoff_ts: Any,
    lookback_hours: Any,
    max_events: Any,
    source_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    source_tz = source_timezone or _feed_timezone()
    cutoff = parse_dt_safe(cutoff_ts) or parse_dt_safe(cutoff_ts, naive_tz=source_tz)
    data_gaps: List[str] = []
    if cutoff is None:
        return {
            "events": [],
            "data_gaps": ["missing_or_invalid_cutoff_ts"],
            "source_path": path,
            "events_total_read": 0,
            "events_used": 0,
        }
    if not path or not os.path.exists(path):
        return {
            "events": [],
            "data_gaps": ["deltascout_log_missing"],
            "source_path": path,
            "events_total_read": 0,
            "events_used": 0,
        }

    lookback = timedelta(hours=max(0.0, _as_float(lookback_hours, 24.0)))
    start = cutoff - lookback
    cap = max(1, _as_int(max_events, 5000))
    events: List[Dict[str, Any]] = []
    total = 0
    malformed = 0
    skipped_bad_ts = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                total += 1
                try:
                    evt = json.loads(line)
                except Exception:
                    malformed += 1
                    continue
                if not isinstance(evt, dict) or evt.get("action") != "PEAK":
                    continue
                ts_norm = normalize_feed_ts(evt.get("ts"), source_tz)
                event_dt = ts_norm.get("dt_utc")
                if event_dt is None:
                    skipped_bad_ts += 1
                    continue
                if start <= event_dt <= cutoff:
                    public_evt = dict(evt)
                    public_evt["ts_raw"] = ts_norm.get("ts_raw")
                    public_evt["ts_utc"] = ts_norm.get("ts_utc")
                    public_evt["timestamp_contract"] = ts_norm.get("timestamp_contract")
                    events.append(_event_public_fields(public_evt))
                    if len(events) > cap:
                        events.pop(0)
    except Exception as exc:
        return {
            "events": [],
            "data_gaps": [f"deltascout_log_read_error:{type(exc).__name__}"],
            "source_path": path,
            "events_total_read": total,
            "events_used": 0,
        }
    if malformed:
        data_gaps.append(f"deltascout_malformed_json:{malformed}")
    if skipped_bad_ts:
        data_gaps.append(f"deltascout_bad_ts:{skipped_bad_ts}")
    return {
        "events": events,
        "data_gaps": data_gaps,
        "source_path": path,
        "events_total_read": total,
        "events_used": len(events),
    }


def _kind_is_long(kind: Any) -> bool:
    return str(kind or "").strip().lower() == "long"


def _kind_is_short(kind: Any) -> bool:
    return str(kind or "").strip().lower() == "short"


def _avg(values: List[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _max_abs_value(values: List[float]) -> Optional[float]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return max(vals, key=lambda x: abs(x))


def build_peak_context_until_cutoff(
    events: List[Dict[str, Any]],
    current_direction: Any,
    current_price: Any,
    current_peak: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data_gaps: List[str] = []
    safe_events = [e for e in (events or []) if isinstance(e, dict)]
    safe_events.sort(key=lambda e: _event_dt(e) or datetime.min.replace(tzinfo=timezone.utc))
    longs = [e for e in safe_events if _kind_is_long(e.get("kind"))]
    shorts = [e for e in safe_events if _kind_is_short(e.get("kind"))]
    long_deltas = [d for d in (_to_float(e.get("delta")) for e in longs) if d is not None]
    short_deltas = [d for d in (_to_float(e.get("delta")) for e in shorts) if d is not None]

    current = current_peak if isinstance(current_peak, dict) else {}
    current_dt = _event_dt(current) or (_event_dt(safe_events[-1]) if safe_events else None)
    direction = str(current_direction or "").strip().lower()
    recent_start = current_dt - timedelta(minutes=60) if current_dt is not None else None
    recent = []
    if recent_start is not None:
        recent = [e for e in safe_events if (_event_dt(e) or datetime.min.replace(tzinfo=timezone.utc)) >= recent_start]
    same_recent = [e for e in recent if str(e.get("kind") or "").strip().lower() == direction]
    opp_recent = [e for e in recent if str(e.get("kind") or "").strip().lower() in ("long", "short") and str(e.get("kind") or "").strip().lower() != direction]

    price = _to_float(current_price)
    vwap = _to_float(current.get("vwap"))
    poc = _to_float(current.get("poc"))
    if vwap is None:
        data_gaps.append("missing_current_peak_vwap")
    if poc is None:
        data_gaps.append("missing_current_peak_poc")

    price_vs_vwap = (price - vwap) if price is not None and vwap is not None else None
    price_vs_poc = (price - poc) if price is not None and poc is not None else None
    current_delta = _to_float(current.get("delta"))
    all_abs_deltas = sorted(abs(d) for d in [d for d in (_to_float(e.get("delta")) for e in safe_events) if d is not None])
    percentile = None
    if current_delta is not None and all_abs_deltas:
        le_count = sum(1 for d in all_abs_deltas if d <= abs(current_delta))
        percentile = round(100.0 * le_count / len(all_abs_deltas), 3)
    elif current_delta is None:
        data_gaps.append("missing_current_peak_delta")

    return {
        "count_total": len(safe_events),
        "count_long": len(longs),
        "count_short": len(shorts),
        "last_peak": safe_events[-1] if safe_events else None,
        "last_5_peaks": safe_events[-5:],
        "max_delta_long": _max_abs_value(long_deltas),
        "max_delta_short": _max_abs_value(short_deltas),
        "avg_delta_long": _avg(long_deltas),
        "avg_delta_short": _avg(short_deltas),
        "recent_same_direction_count_60m": len(same_recent),
        "recent_opposite_direction_count_60m": len(opp_recent),
        "current_peak": _event_public_fields(current),
        "current_peak_delta_percentile_24h": percentile,
        "price_vs_vwap": price_vs_vwap,
        "price_vs_vwap_pct": (price_vs_vwap / vwap * 100.0) if price_vs_vwap is not None and vwap else None,
        "price_vs_poc": price_vs_poc,
        "price_vs_poc_pct": (price_vs_poc / poc * 100.0) if price_vs_poc is not None and poc else None,
        "data_gaps": data_gaps,
    }


AGG_NUMERIC_FIELDS = ("Trades", "TotalQty", "AvgSize", "BuyQty", "SellQty", "AvgPrice", "ClosePrice", "HiPrice", "LowPrice")


def read_agg_rows_until_cutoff(
    path: str,
    cutoff_ts: Any,
    lookback_hours: Any,
    source_timezone: Optional[str] = None,
) -> Dict[str, Any]:
    source_tz = source_timezone or _feed_timezone()
    cutoff = parse_dt_safe(cutoff_ts) or parse_dt_safe(cutoff_ts, naive_tz=source_tz)
    data_gaps: List[str] = []
    if cutoff is None:
        return {"rows": [], "data_gaps": ["missing_or_invalid_cutoff_ts"], "source_path": path, "rows_used": 0}
    if not path or not os.path.exists(path):
        return {"rows": [], "data_gaps": ["agg_csv_missing"], "source_path": path, "rows_used": 0}
    start = cutoff - timedelta(hours=max(0.0, _as_float(lookback_hours, 24.0)))
    rows: List[Dict[str, Any]] = []
    malformed = 0
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for raw in reader:
                ts_norm = normalize_feed_ts(raw.get("Timestamp"), source_tz)
                row_dt = ts_norm.get("dt_utc")
                if row_dt is None:
                    malformed += 1
                    continue
                if not (start <= row_dt <= cutoff):
                    continue
                row: Dict[str, Any] = {
                    "Timestamp": raw.get("Timestamp"),
                    "Timestamp_raw": ts_norm.get("ts_raw"),
                    "Timestamp_utc": ts_norm.get("ts_utc"),
                    "timestamp_contract": ts_norm.get("timestamp_contract"),
                }
                for key in AGG_NUMERIC_FIELDS:
                    row[key] = _to_float(raw.get(key))
                rows.append(row)
    except Exception as exc:
        return {"rows": [], "data_gaps": [f"agg_csv_read_error:{type(exc).__name__}"], "source_path": path, "rows_used": 0}
    if malformed:
        data_gaps.append(f"agg_csv_bad_rows:{malformed}")
    rows.sort(key=lambda r: parse_dt_safe(r.get("Timestamp_utc")) or _market_dt(r.get("Timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    return {"rows": rows, "data_gaps": data_gaps, "source_path": path, "rows_used": len(rows)}


def _row_close(row: Dict[str, Any]) -> Optional[float]:
    return _to_float(row.get("ClosePrice")) or _to_float(row.get("AvgPrice"))


def _return_pct_for_window(rows: List[Dict[str, Any]], minutes: int) -> Optional[float]:
    if not rows:
        return None
    last_dt = parse_dt_safe(rows[-1].get("Timestamp_utc")) or _market_dt(rows[-1].get("Timestamp"))
    last_close = _row_close(rows[-1])
    if last_dt is None or last_close in (None, 0):
        return None
    target = last_dt - timedelta(minutes=minutes)
    base = None
    for row in rows:
        row_dt = parse_dt_safe(row.get("Timestamp_utc")) or _market_dt(row.get("Timestamp"))
        if row_dt is not None and row_dt <= target:
            base = row
        elif row_dt is not None and row_dt > target:
            if base is None:
                base = row
            break
    base_close = _row_close(base or rows[0])
    if base_close in (None, 0):
        return None
    return (last_close - base_close) / base_close * 100.0


def _rows_since(rows: List[Dict[str, Any]], minutes: int) -> List[Dict[str, Any]]:
    if not rows:
        return []
    last_dt = parse_dt_safe(rows[-1].get("Timestamp_utc")) or _market_dt(rows[-1].get("Timestamp"))
    if last_dt is None:
        return rows
    start = last_dt - timedelta(minutes=minutes)
    return [r for r in rows if (parse_dt_safe(r.get("Timestamp_utc")) or _market_dt(r.get("Timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= start]


def _volatility_60m(rows: List[Dict[str, Any]]) -> Optional[float]:
    window = _rows_since(rows, 60)
    returns: List[float] = []
    prev = None
    for row in window:
        close = _row_close(row)
        if close is None or close == 0:
            continue
        if prev not in (None, 0):
            returns.append((close - prev) / prev * 100.0)
        prev = close
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return variance ** 0.5


def build_agg_context_until_cutoff(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    data_gaps: List[str] = []
    safe_rows = [r for r in (rows or []) if isinstance(r, dict)]
    safe_rows.sort(key=lambda r: parse_dt_safe(r.get("Timestamp_utc")) or _market_dt(r.get("Timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
    if not safe_rows:
        return {"rows_used": 0, "data_gaps": ["agg_no_rows_until_cutoff"]}
    last_close = _row_close(safe_rows[-1])
    w60 = _rows_since(safe_rows, 60)
    w240 = _rows_since(safe_rows, 240)
    buy60 = sum((_to_float(r.get("BuyQty")) or 0.0) for r in w60)
    sell60 = sum((_to_float(r.get("SellQty")) or 0.0) for r in w60)
    delta60 = buy60 - sell60
    total60 = buy60 + sell60
    cum_delta = sum(((_to_float(r.get("BuyQty")) or 0.0) - (_to_float(r.get("SellQty")) or 0.0)) for r in safe_rows)
    weighted_sum = sum(((_to_float(r.get("AvgPrice")) or 0.0) * (_to_float(r.get("TotalQty")) or 0.0)) for r in safe_rows)
    qty_sum = sum((_to_float(r.get("TotalQty")) or 0.0) for r in safe_rows)
    rolling_vwap = weighted_sum / qty_sum if qty_sum > 0 else None
    if rolling_vwap is None:
        data_gaps.append("rolling_vwap_approx_unavailable")
    return {
        "rows_used": len(safe_rows),
        "last_close": last_close,
        "return_15m_pct": _return_pct_for_window(safe_rows, 15),
        "return_60m_pct": _return_pct_for_window(safe_rows, 60),
        "return_240m_pct": _return_pct_for_window(safe_rows, 240),
        "volatility_60m": _volatility_60m(safe_rows),
        "high_60m": max((_to_float(r.get("HiPrice")) or _row_close(r) or float("-inf")) for r in w60) if w60 else None,
        "low_60m": min((_to_float(r.get("LowPrice")) or _row_close(r) or float("inf")) for r in w60) if w60 else None,
        "high_240m": max((_to_float(r.get("HiPrice")) or _row_close(r) or float("-inf")) for r in w240) if w240 else None,
        "low_240m": min((_to_float(r.get("LowPrice")) or _row_close(r) or float("inf")) for r in w240) if w240 else None,
        "buy_qty_sum_60m": buy60,
        "sell_qty_sum_60m": sell60,
        "buy_sell_delta_60m": delta60,
        "buy_sell_imbalance_60m": (delta60 / total60) if total60 > 0 else None,
        "cumulative_delta_24h_approx": cum_delta,
        "rolling_vwap_approx": rolling_vwap,
        "price_vs_rolling_vwap_pct": ((last_close - rolling_vwap) / rolling_vwap * 100.0) if last_close is not None and rolling_vwap else None,
        "data_gaps": data_gaps,
    }


def build_market_context_until_cutoff(evidence_pack: Dict[str, Any], env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = env if isinstance(env, dict) else ENV
    if not _as_bool(cfg.get("LLM_TRADE_JUDGE_CONTEXT_ENABLED", True), True):
        return {"enabled": False, "data_gaps": ["context_disabled"]}

    cutoff_ts = evidence_pack.get("analysis_cutoff_ts")
    source_tz = _feed_timezone(cfg)
    lookback_hours = cfg.get("LLM_TRADE_JUDGE_CONTEXT_LOOKBACK_HOURS", 24)
    max_events = cfg.get("LLM_TRADE_JUDGE_CONTEXT_MAX_EVENTS", 5000)
    deltascout_path = (
        cfg.get("LLM_TRADE_JUDGE_DELTASCOUT_LOG")
        or cfg.get("DELTASCOUT_LOG")
        or os.getenv("DELTASCOUT_LOG")
        or "/data/logs/deltascout.log"
    )
    agg_path = (
        cfg.get("LLM_TRADE_JUDGE_AGG_CSV")
        or cfg.get("AGG_CSV")
        or os.getenv("AGG_CSV")
        or "/data/feed/aggregated.csv"
    )
    src_evt = evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), dict) else {}
    current_price = (
        src_evt.get("price")
        if src_evt.get("price") is not None
        else src_evt.get("price_usdt")
        if src_evt.get("price_usdt") is not None
        else evidence_pack.get("entry_actual")
        if evidence_pack.get("entry_actual") is not None
        else evidence_pack.get("entry")
    )

    data_gaps: List[str] = []
    delta_result = read_deltascout_events_until_cutoff(deltascout_path, cutoff_ts, lookback_hours, max_events, source_tz)
    peak_context = build_peak_context_until_cutoff(
        delta_result.get("events") or [],
        evidence_pack.get("direction"),
        current_price,
        current_peak=src_evt,
    )
    agg_result = read_agg_rows_until_cutoff(agg_path, cutoff_ts, lookback_hours, source_tz)
    agg_context = build_agg_context_until_cutoff(agg_result.get("rows") or [])

    for part in (delta_result, peak_context, agg_result, agg_context):
        for gap in part.get("data_gaps") or []:
            if gap not in data_gaps:
                data_gaps.append(gap)

    return {
        "enabled": True,
        "cutoff_ts": cutoff_ts,
        "lookback_hours": _as_float(lookback_hours, 24.0),
        "ts_source_timezone": source_tz,
        "timestamp_contract": evidence_pack.get("timestamp_contract"),
        "deltascout": {
            "source_path": delta_result.get("source_path"),
            "events_total_read": delta_result.get("events_total_read"),
            "events_used": delta_result.get("events_used"),
            "peak_context": peak_context,
        },
        "aggregated": {
            "source_path": agg_result.get("source_path"),
            "rows_used": agg_result.get("rows_used"),
            "context": agg_context,
        },
        "data_gaps": data_gaps,
    }


def _current_price_for_context(evidence_pack: Dict[str, Any]) -> Any:
    src_evt = evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), dict) else {}
    if src_evt.get("price") is not None:
        return src_evt.get("price")
    if src_evt.get("price_usdt") is not None:
        return src_evt.get("price_usdt")
    if evidence_pack.get("entry_actual") is not None:
        return evidence_pack.get("entry_actual")
    return evidence_pack.get("entry")


def _resolve_market_monitor_current_feed_path(path: str, cutoff_ts: Any) -> str:
    if not path:
        return ""
    if os.path.isdir(path):
        cutoff_dt = parse_dt_safe(cutoff_ts)
        if cutoff_dt is None:
            return path
        return os.path.join(path, f"{cutoff_dt.date().isoformat()}.csv")
    return path


def build_market_monitor_snapshot_until_cutoff(evidence_pack: Dict[str, Any], env: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = env if isinstance(env, dict) else ENV
    if not _as_bool(cfg.get("LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED", False), False):
        return {"enabled": False, "data_gaps": ["market_monitor_snapshot_disabled"]}

    cutoff_ts = evidence_pack.get("analysis_cutoff_ts")
    current_feed_path = str(
        cfg.get("LLM_TRADE_JUDGE_MARKET_MONITOR_CURRENT_FEED")
        or cfg.get("MARKET_MONITOR_CURRENT_FEED")
        or ""
    ).strip()
    context_feed_path = str(
        cfg.get("LLM_TRADE_JUDGE_MARKET_MONITOR_CONTEXT_FEED")
        or cfg.get("MARKET_MONITOR_CONTEXT_FEED")
        or ""
    ).strip()
    resolved_current_feed_path = _resolve_market_monitor_current_feed_path(current_feed_path, cutoff_ts)

    data_gaps: List[str] = []
    if not cutoff_ts:
        data_gaps.append("market_monitor_snapshot_missing_cutoff_ts")
    if not current_feed_path:
        data_gaps.append("market_monitor_snapshot_current_feed_missing")
    elif not os.path.exists(resolved_current_feed_path):
        data_gaps.append("market_monitor_snapshot_current_feed_not_found")
    if context_feed_path and not os.path.exists(context_feed_path):
        data_gaps.append("market_monitor_snapshot_context_feed_not_found")

    if data_gaps:
        return {
            "enabled": True,
            "schema_version": "market_monitor_snapshot_error_v1",
            "cutoff_ts": cutoff_ts,
            "symbol": evidence_pack.get("symbol") or "",
            "source_paths": {
                "current_feed": current_feed_path,
                "resolved_current_feed": resolved_current_feed_path,
                "context_feed": context_feed_path,
            },
            "data_gaps": data_gaps,
            "boundary": "descriptive market-state snapshot only",
        }

    try:
        from market_monitor.feed_adapter import load_feed
        from market_monitor.snapshot_builder import build_market_monitor_snapshot

        current_feed = load_feed(resolved_current_feed_path)
        context_feed = load_feed(context_feed_path) if context_feed_path else None
        snapshot = build_market_monitor_snapshot(
            current_feed,
            context_feed=context_feed,
            cutoff_ts=cutoff_ts,
            current_price=_to_float(_current_price_for_context(evidence_pack)),
            src_event=evidence_pack.get("src_evt") if isinstance(evidence_pack.get("src_evt"), dict) else {},
            symbol=str(evidence_pack.get("symbol") or ""),
            max_zones=max(1, _as_int(cfg.get("LLM_TRADE_JUDGE_MARKET_MONITOR_MAX_ZONES"), 5)),
        )
        if isinstance(snapshot, dict):
            snapshot["enabled"] = True
            return snapshot
        return {
            "enabled": True,
            "schema_version": "market_monitor_snapshot_error_v1",
            "cutoff_ts": cutoff_ts,
            "symbol": evidence_pack.get("symbol") or "",
            "data_gaps": ["market_monitor_snapshot_invalid_result"],
            "boundary": "descriptive market-state snapshot only",
        }
    except Exception as exc:
        return {
            "enabled": True,
            "schema_version": "market_monitor_snapshot_error_v1",
            "cutoff_ts": cutoff_ts,
            "symbol": evidence_pack.get("symbol") or "",
            "source_paths": {
                "current_feed": current_feed_path,
                "resolved_current_feed": resolved_current_feed_path,
                "context_feed": context_feed_path,
            },
            "data_gaps": [f"market_monitor_snapshot_error:{type(exc).__name__}"],
            "boundary": "descriptive market-state snapshot only",
        }


def _direction(side: Any, src_evt: Dict[str, Any]) -> Optional[str]:
    kind = str(src_evt.get("kind") or "").strip().lower()
    if kind in ("long", "short"):
        return kind
    side_u = str(side or "").strip().upper()
    if side_u == "LONG":
        return "long"
    if side_u == "SHORT":
        return "short"
    return None


def build_pretrade_evidence_pack(pos: Dict[str, Any], st: Dict[str, Any], trigger: str) -> Dict[str, Any]:
    src_evt = pos.get("src_evt") if isinstance(pos.get("src_evt"), dict) else {}
    prices = pos.get("prices") if isinstance(pos.get("prices"), dict) else {}
    orders = pos.get("orders") if isinstance(pos.get("orders"), dict) else {}
    cutoff = choose_analysis_cutoff(pos)
    baseline = st.get("baseline") if isinstance(st, dict) and isinstance(st.get("baseline"), dict) else {}

    pack = {
        "schema_version": "llm_trade_judge_open_v1",
        "trigger": trigger,
        "trade_key": get_trade_key(pos),
        "symbol": pos.get("symbol") or (st.get("symbol") if isinstance(st, dict) else None) or ENV.get("SYMBOL"),
        "direction": _direction(pos.get("side"), src_evt),
        "qty": pos.get("qty"),
        "entry": pos.get("entry") or prices.get("entry"),
        "entry_actual": pos.get("entry_actual"),
        "prices": {
            "entry": prices.get("entry"),
            "sl": prices.get("sl"),
            "tp1": prices.get("tp1"),
            "tp2": prices.get("tp2"),
        },
        "orders": {
            "sl": orders.get("sl"),
            "tp1": orders.get("tp1"),
            "tp2": orders.get("tp2"),
        },
        "src_evt": src_evt,
        "opened_at": pos.get("opened_at"),
        "filled_at": pos.get("filled_at"),
        "peak_ts": cutoff.get("peak_ts"),
        "peak_ts_raw": cutoff.get("peak_ts_raw"),
        "analysis_cutoff_ts": cutoff.get("analysis_cutoff_ts"),
        "cutoff_source": cutoff.get("cutoff_source"),
        "ts_source_timezone": cutoff.get("ts_source_timezone"),
        "ts_normalized": cutoff.get("ts_normalized"),
        "timestamp_contract": cutoff.get("timestamp_contract"),
        "data_gaps": list(cutoff.get("data_gaps") or []),
    }

    for key in ("client_id", "order_id", "entry_mode", "executedQty", "cummulativeQuoteQty", "k_entry"):
        if key in pos:
            pack[key] = pos.get(key)
    if isinstance(baseline.get("active"), dict):
        pack["baseline"] = {"active": baseline.get("active")}
    if "kind" in src_evt:
        pack["src_evt_kind"] = src_evt.get("kind")
    if "price_usdt" in src_evt:
        pack["src_evt_price_usdt"] = src_evt.get("price_usdt")
    _add_required_data_gaps(pack)
    try:
        pack["market_context"] = build_market_context_until_cutoff(pack)
    except Exception as exc:
        pack["market_context"] = {
            "enabled": True,
            "data_gaps": [f"market_context_error:{type(exc).__name__}"],
        }
    if _as_bool(ENV.get("LLM_TRADE_JUDGE_MARKET_MONITOR_SNAPSHOT_ENABLED", False), False):
        snapshot = build_market_monitor_snapshot_until_cutoff(pack)
        pack["market_monitor_snapshot"] = snapshot
        for gap in snapshot.get("data_gaps") or []:
            if gap not in pack["data_gaps"]:
                pack["data_gaps"].append(gap)
    return pack


def _add_required_data_gaps(pack: Dict[str, Any]) -> None:
    gaps = list(pack.get("data_gaps") or [])

    def missing(value: Any) -> bool:
        return value is None or value == ""

    checks = {
        "missing_trade_key": pack.get("trade_key"),
        "missing_symbol": pack.get("symbol"),
        "missing_direction": pack.get("direction"),
        "missing_qty": pack.get("qty"),
        "missing_entry": pack.get("entry"),
        "missing_entry_actual": pack.get("entry_actual"),
        "missing_prices.entry": (pack.get("prices") or {}).get("entry"),
        "missing_prices.sl": (pack.get("prices") or {}).get("sl"),
        "missing_prices.tp1": (pack.get("prices") or {}).get("tp1"),
        "missing_prices.tp2": (pack.get("prices") or {}).get("tp2"),
        "missing_orders.sl": (pack.get("orders") or {}).get("sl"),
        "missing_orders.tp1": (pack.get("orders") or {}).get("tp1"),
        "missing_orders.tp2": (pack.get("orders") or {}).get("tp2"),
        "missing_src_evt": pack.get("src_evt"),
        "missing_opened_at": pack.get("opened_at"),
        "missing_filled_at": pack.get("filled_at"),
    }
    for gap, value in checks.items():
        if missing(value) and gap not in gaps:
            gaps.append(gap)
    pack["data_gaps"] = gaps


def append_jsonl(path: str, record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")
        return {"status": "ok", "path": path}
    except Exception as exc:
        return {"status": "error", "path": path, "error": str(exc)}


def has_primary_verdict(journal_path: str, trade_key: str) -> bool:
    if not trade_key:
        return False
    try:
        with open(journal_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("trade_key") == trade_key and obj.get("is_primary") is True:
                    return True
    except FileNotFoundError:
        return False
    except Exception:
        return False
    return False


def append_stub_pretrade_verdict(journal_path: str, evidence_pack: Dict[str, Any]) -> Dict[str, Any]:
    record = {
        "schema_version": "llm_trade_judge_verdict_v1",
        "verdict_id": f"stub-{uuid.uuid4().hex}",
        "created_at": _now_iso(),
        "trade_key": evidence_pack.get("trade_key"),
        "trigger": evidence_pack.get("trigger") or "EXITS_PLACED_V15",
        "is_primary": True,
        "model": None,
        "llm_call_status": "disabled",
        "verdict": "STUB_NOT_CALLED",
        "competitive_side": None,
        "confidence": None,
        "setup_class": None,
        "reason_codes": [],
        "risk_flags": [],
        "summary_ua": None,
        "evidence_pack": evidence_pack,
    }
    result = append_jsonl(journal_path, record)
    result["record"] = record
    if result.get("status") == "ok":
        result["verdict_id"] = record["verdict_id"]
    return result


def _model_name() -> str:
    return str(ENV.get("LLM_TRADE_JUDGE_MODEL") or "gpt-5.5")


def _notify_enabled() -> bool:
    return _as_bool(ENV.get("LLM_TRADE_JUDGE_NOTIFY_TELEGRAM", True), True)


def _competitive_side_for_verdict(verdict: str) -> Optional[str]:
    verdict_u = str(verdict or "").strip().upper()
    if verdict_u == "SUPPORT":
        return "BOT"
    if verdict_u in ("REJECT", "UNCLEAR"):
        return "LLM_REJECT"
    return None


def _json_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "verdict": {"type": "string", "enum": sorted(ALLOWED_VERDICTS)},
            "competitive_side": {"type": ["string", "null"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "setup_class": {"type": "string", "enum": sorted(ALLOWED_SETUP_CLASSES)},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "summary_ua": {"type": ["string", "null"]},
        },
        "required": [
            "verdict",
            "competitive_side",
            "confidence",
            "setup_class",
            "reason_codes",
            "risk_flags",
            "summary_ua",
        ],
    }


def build_llm_trade_judge_prompt(evidence_pack: Dict[str, Any]) -> str:
    return (
        "You are LLM Trade Judge for an automated Binance execution engine.\n"
        "Judge only the trade signal quality at entry time.\n"
        "You only see information available until analysis_cutoff_ts, which is normalized UTC.\n"
        "peak_ts_raw may be legacy feed local time. Do not use raw timestamps for filtering; use analysis_cutoff_ts.\n"
        "The evidence pack includes src_evt/current PEAK, market_context.deltascout, and market_context.aggregated.\n"
        "The evidence pack may include market_monitor_snapshot: a descriptive pre-cutoff Market Monitor snapshot "
        "with local 15m/60m/240m context, broad 1d/3d/7d/30d context, market state, market_structure_state, "
        "zones, liquidity zones, data-quality flags, and context conflicts. market_structure_state is repaired 37E state evidence "
        "with range_pct, close_position, dominant_side, and range_quality; use it to avoid misreading bearish expansion as range/support. "
        "It is not a trading instruction and must not modify live orders.\n"
        "All market_context and market_monitor_snapshot records are intended to be pre-cutoff only; "
        "do not use or infer data after analysis_cutoff_ts.\n"
        "Do not infer future outcome. Do not mention whether the trade won or lost.\n"
        "The LLM is advisory only and must not suggest changing live orders.\n"
        "Return only JSON, no markdown.\n"
        "Allowed verdict values: SUPPORT, REJECT, UNCLEAR.\n"
        "SUPPORT means the bot side is favored. REJECT means reject the bot trade. "
        "UNCLEAR counts as reject-side in the game. If market_context is sufficient and the signal is weak or bad, use REJECT. "
        "Use UNCLEAR only when the edge still cannot be assessed after reading market_context.\n"
        "Calibrate verdict strictly: SUPPORT requires clear, fresh directional edge after accounting for risk_flags. "
        "Do not use SUPPORT merely because local momentum agrees with the bot when the entry is a late chase. "
        "Prefer REJECT when the bot direction is already stretched into a local 60m/240m extreme, the peak is weak or moderate, "
        "or a significant liquidity/market zone immediately opposes continuation. Prefer UNCLEAR when broad 1d/3d/7d context "
        "conflicts with local flow, data quality is degraded/recovered, or zone evidence is mixed enough that edge is not reliable. "
        "If you still choose SUPPORT with multiple material risk_flags, lower confidence and explain why those risks are outweighed.\n"
        "If direction conflicts with VWAP, rolling_vwap_approx, or orderflow/imbalance context, reflect it in reason_codes or risk_flags.\n"
        "Allowed setup_class values: continuation_pressure, reversal_onset, reversal_confirmation, "
        "exhaustion, trap_false_break, absorption_like, honest_directional_flow, noisy_peak, unknown.\n"
        "Evidence pack follows:\n"
        f"{json.dumps(evidence_pack, ensure_ascii=False, separators=(',', ':'), default=str)}"
    )


def _extract_response_text(response: Any) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        if isinstance(response.get("output_text"), str):
            return response["output_text"]
        output = response.get("output")
        if isinstance(output, list):
            parts: List[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and isinstance(c.get("text"), str):
                            parts.append(c["text"])
                elif isinstance(content, str):
                    parts.append(content)
            if parts:
                return "\n".join(parts)
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str):
        return output_text
    return str(response)


def call_openai_trade_judge(evidence_pack: Dict[str, Any]) -> str:
    prompt = build_llm_trade_judge_prompt(evidence_pack)
    model = _model_name()
    timeout_sec = _as_float(ENV.get("LLM_TRADE_JUDGE_TIMEOUT_SEC"), 20.0)
    max_retries = max(0, _as_int(ENV.get("LLM_TRADE_JUDGE_MAX_RETRIES"), 1))

    if openai_client is not None:
        response = openai_client(
            prompt=prompt,
            evidence_pack=evidence_pack,
            model=model,
            timeout_sec=timeout_sec,
            schema=_json_schema(),
        )
        return _extract_response_text(response)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("missing_openai_api_key")

    payload = {
        "model": model,
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "llm_trade_judge_verdict",
                "strict": True,
                "schema": _json_schema(),
            }
        },
        "max_output_tokens": 800,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
                timeout=timeout_sec,
            )
            if response.status_code != 200:
                raise RuntimeError(f"openai_http_{response.status_code}")
            return _extract_response_text(response.json())
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                time.sleep(min(1.0, 0.25 * (attempt + 1)))
                continue
            raise
    raise RuntimeError(str(last_exc) if last_exc else "openai_call_failed")


def validate_llm_verdict_json(raw_text: str) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    try:
        parsed = json.loads(raw_text)
    except Exception as exc:
        return None, [f"json_parse_error:{exc}"]
    if not isinstance(parsed, dict):
        return None, ["json_not_object"]

    verdict = str(parsed.get("verdict") or "").strip().upper()
    if verdict not in ALLOWED_VERDICTS:
        return None, [f"invalid_verdict:{parsed.get('verdict')}"]

    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except Exception:
            return None, ["invalid_confidence"]
        if confidence < 0.0 or confidence > 1.0:
            return None, ["invalid_confidence_range"]

    setup_class = str(parsed.get("setup_class") or "unknown").strip()
    if setup_class not in ALLOWED_SETUP_CLASSES:
        errors.append(f"unknown_setup_class:{setup_class}")
        setup_class = "unknown"

    reason_codes = parsed.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = []
        errors.append("invalid_reason_codes")
    risk_flags = parsed.get("risk_flags")
    if not isinstance(risk_flags, list):
        risk_flags = []
        errors.append("invalid_risk_flags")

    return {
        "verdict": verdict,
        "competitive_side": _competitive_side_for_verdict(verdict),
        "confidence": confidence,
        "setup_class": setup_class,
        "reason_codes": [str(x) for x in reason_codes],
        "risk_flags": [str(x) for x in risk_flags],
        "summary_ua": parsed.get("summary_ua") if parsed.get("summary_ua") is not None else None,
        "validation_errors": errors,
    }, errors


def _base_record(evidence_pack: Dict[str, Any], *, model: Optional[str], status: str) -> Dict[str, Any]:
    return {
        "schema_version": "llm_trade_judge_verdict_v1",
        "verdict_id": f"llmj-{uuid.uuid4().hex}",
        "created_at": _now_iso(),
        "trade_key": evidence_pack.get("trade_key"),
        "trigger": evidence_pack.get("trigger") or "EXITS_PLACED_V15",
        "is_primary": True,
        "model": model,
        "llm_call_status": status,
        "evidence_pack": evidence_pack,
    }


def build_success_verdict_record(evidence_pack: Dict[str, Any], validated: Dict[str, Any]) -> Dict[str, Any]:
    record = _base_record(evidence_pack, model=_model_name(), status="success")
    record.update({
        "verdict": validated.get("verdict"),
        "competitive_side": validated.get("competitive_side"),
        "confidence": validated.get("confidence"),
        "setup_class": validated.get("setup_class"),
        "reason_codes": validated.get("reason_codes") or [],
        "risk_flags": validated.get("risk_flags") or [],
        "summary_ua": validated.get("summary_ua"),
    })
    if validated.get("validation_errors"):
        record["validation_errors"] = validated.get("validation_errors")
    return record


def build_error_verdict_record(
    evidence_pack: Dict[str, Any],
    error_type: str,
    error_message: str,
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    record = _base_record(evidence_pack, model=model if model is not None else _model_name(), status="error")
    record.update({
        "error_type": str(error_type or "unknown_error"),
        "error_message": str(error_message or ""),
        "verdict": "ERROR_NOT_SCORED",
        "competitive_side": None,
        "confidence": None,
        "setup_class": None,
        "reason_codes": [],
        "risk_flags": [],
        "summary_ua": None,
    })
    return record


def append_real_pretrade_verdict(journal_path: str, record: Dict[str, Any]) -> Dict[str, Any]:
    result = append_jsonl(journal_path, record)
    result["record"] = record
    if result.get("status") == "ok":
        result["verdict_id"] = record["verdict_id"]
    return result


def _mark_state_done(st: Dict[str, Any], trade_key: str, verdict_id: str, result: Dict[str, Any]) -> None:
    llm_state = st.setdefault("llm", {})
    pretrade_done = llm_state.setdefault("pretrade_done", {})
    pretrade_done[trade_key] = verdict_id
    if save_state:
        try:
            save_state(st)
        except Exception as exc:
            result["state_marker_error"] = str(exc)


def _telegram_text(record: Dict[str, Any]) -> str:
    evidence = record.get("evidence_pack") if isinstance(record.get("evidence_pack"), dict) else {}
    trade_key = record.get("trade_key") or evidence.get("trade_key")
    if record.get("llm_call_status") == "error":
        return (
            "🤖 LLM Trade Judge ERROR\n\n"
            f"Trade: {trade_key}\n"
            f"Status: {record.get('llm_call_status')}\n"
            f"Reason: {record.get('error_type')}\n"
            "Execution was not affected."
        )

    lines = [
        "🤖 LLM Trade Judge",
        "",
        f"Symbol: {evidence.get('symbol')}",
        f"Direction: {str(evidence.get('direction') or '').upper()}",
        f"Trade: {trade_key}",
        f"Cutoff: {evidence.get('analysis_cutoff_ts')}",
        f"Cutoff source: {evidence.get('cutoff_source')}",
        "",
        f"Verdict: {record.get('verdict')}",
        f"Game side: {record.get('competitive_side')}",
        f"Confidence: {record.get('confidence')}",
        f"Setup: {record.get('setup_class')}",
    ]
    if record.get("verdict") == "UNCLEAR":
        lines.extend(["", "Game rule: UNCLEAR counts as reject-side."])
    if evidence.get("cutoff_source") == "entry_ts_fallback":
        lines.extend(["", "Cutoff fallback: entry_ts_fallback"])
    if record.get("summary_ua"):
        lines.extend(["", "Summary:", str(record.get("summary_ua"))])
    risk_flags = record.get("risk_flags") if isinstance(record.get("risk_flags"), list) else []
    if risk_flags:
        lines.extend(["", "Risk flags:"])
        lines.extend([f"- {flag}" for flag in risk_flags])
    return "\n".join(lines)


def _send_telegram_notification(record: Dict[str, Any]) -> Dict[str, Any]:
    if not _notify_enabled():
        return {"status": "noop", "reason": "telegram_disabled"}
    if send_webhook is None:
        return {"status": "noop", "reason": "no_webhook_sender"}
    try:
        evidence = record.get("evidence_pack") if isinstance(record.get("evidence_pack"), dict) else {}
        text = _telegram_text(record)
        send_webhook({
            "event": "LLM_TRADE_JUDGE_VERDICT",
            "type": "LLM_TRADE_JUDGE_VERDICT",
            "mode": record.get("mode") or evidence.get("mode") or "live",
            "symbol": evidence.get("symbol") or "",
            "trade_key": record.get("trade_key"),
            "llm_call_status": record.get("llm_call_status"),
            "verdict": record.get("verdict"),
            "competitive_side": record.get("competitive_side"),
            "confidence": record.get("confidence"),
            "setup_class": record.get("setup_class"),
            "summary_ua": record.get("summary_ua"),
            "risk_flags": record.get("risk_flags") if isinstance(record.get("risk_flags"), list) else [],
            "cutoff": evidence.get("analysis_cutoff_ts"),
            "cutoff_source": evidence.get("cutoff_source"),
            "text": text,
            "message": text,
            "telegram_text": text,
        })
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def maybe_record_llm_pretrade_judge(st: Dict[str, Any], pos: Dict[str, Any], trigger: str = "EXITS_PLACED_V15") -> Dict[str, Any]:
    try:
        if not _is_enabled():
            return {"status": "noop", "reason": "disabled"}
        if not isinstance(pos, dict) or str(pos.get("status") or "").upper() != "OPEN":
            return {"status": "noop", "reason": "position_not_open"}
        if not pos.get("orders"):
            return {"status": "noop", "reason": "missing_orders"}

        trade_key = get_trade_key(pos)
        if not trade_key:
            return {"status": "noop", "reason": "missing_trade_key"}

        journal_path = _journal_path()
        if has_primary_verdict(journal_path, trade_key):
            if log_event:
                log_event("LLM_TRADE_JUDGE_DUPLICATE_SKIPPED", trade_key=trade_key)
            return {"status": "noop", "reason": "duplicate_primary", "trade_key": trade_key}

        evidence_pack = build_pretrade_evidence_pack(pos, st, trigger)
        mode = str(ENV.get("LLM_TRADE_JUDGE_MODE") or "stub").strip().lower()
        if mode == "stub":
            result = append_stub_pretrade_verdict(journal_path, evidence_pack)
        elif mode == "openai":
            try:
                raw_text = call_openai_trade_judge(evidence_pack)
                validated, errors = validate_llm_verdict_json(raw_text)
                if validated is None:
                    record = build_error_verdict_record(
                        evidence_pack,
                        "json_validation_error",
                        ";".join(errors) if errors else "invalid_json",
                    )
                else:
                    record = build_success_verdict_record(evidence_pack, validated)
            except requests.exceptions.Timeout as exc:
                record = build_error_verdict_record(evidence_pack, "timeout", str(exc))
            except Exception as exc:
                error_msg = str(exc)
                error_type = "missing_api_key" if error_msg == "missing_openai_api_key" else "api_error"
                record = build_error_verdict_record(evidence_pack, error_type, error_msg)
            result = append_real_pretrade_verdict(journal_path, record)
        else:
            record = build_error_verdict_record(evidence_pack, "unsupported_mode", mode, model=None)
            result = append_real_pretrade_verdict(journal_path, record)

        if result.get("status") != "ok":
            if log_event:
                log_event("LLM_TRADE_JUDGE_WRITE_ERROR", trade_key=trade_key, error=result.get("error"))
            return result

        _mark_state_done(st, trade_key, str(result.get("verdict_id") or ""), result)
        if log_event:
            record = result.get("record") or {}
            action = "LLM_TRADE_JUDGE_ERROR" if record.get("llm_call_status") == "error" else "LLM_TRADE_JUDGE_VERDICT"
            log_event(
                action,
                trade_key=trade_key,
                verdict_id=result.get("verdict_id"),
                llm_call_status=record.get("llm_call_status"),
                verdict=record.get("verdict"),
                error_type=record.get("error_type"),
            )
        notify_result = _send_telegram_notification(result.get("record") or {})
        result["telegram"] = notify_result
        return result
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def maybe_record_llm_pretrade_stub(st: Dict[str, Any], pos: Dict[str, Any], trigger: str = "EXITS_PLACED_V15") -> Dict[str, Any]:
    return maybe_record_llm_pretrade_judge(st, pos, trigger=trigger)


def classify_lifecycle(tp1_done: Any, tp2_done: Any, sl_done: Any, trail_active: Any, reason: Any) -> str:
    tp1 = bool(tp1_done)
    tp2 = bool(tp2_done)
    sl = bool(sl_done)
    if not tp1 and not tp2 and sl:
        return "plain_sl"
    if tp1 and not tp2 and sl:
        return "tp1_sl"
    if tp1 and tp2:
        return "tp1_tp2_trailing_stop"
    return "manual_or_unknown"


def score_llm_vs_bot(verdict: Any, lifecycle_class: str) -> Dict[str, Any]:
    verdict_u = str(verdict or "").strip().upper()
    lifecycle = str(lifecycle_class or "")
    if verdict_u in ("STUB_NOT_CALLED", "ERROR_NOT_SCORED"):
        return {"applies": False, "llm_points": 0, "bot_points": 0, "alignment_score": None}

    competitive = {
        ("REJECT", "plain_sl"): (2, 0),
        ("REJECT", "tp1_sl"): (1, 0),
        ("REJECT", "tp1_tp2_trailing_stop"): (0, 2),
        ("UNCLEAR", "plain_sl"): (1, 0),
        ("UNCLEAR", "tp1_sl"): (0, 1),
        ("UNCLEAR", "tp1_tp2_trailing_stop"): (0, 2),
    }
    if (verdict_u, lifecycle) in competitive:
        llm_points, bot_points = competitive[(verdict_u, lifecycle)]
        return {
            "applies": True,
            "competitive": True,
            "llm_points": llm_points,
            "bot_points": bot_points,
            "alignment_score": None,
        }

    alignment = {
        ("SUPPORT", "plain_sl"): -2,
        ("SUPPORT", "tp1_sl"): 1,
        ("SUPPORT", "tp1_tp2_trailing_stop"): 2,
    }
    if (verdict_u, lifecycle) in alignment:
        return {
            "applies": True,
            "competitive": False,
            "llm_points": 0,
            "bot_points": 0,
            "alignment_score": alignment[(verdict_u, lifecycle)],
        }

    return {"applies": False, "llm_points": 0, "bot_points": 0, "alignment_score": None}
