#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.offline.common import OfflineBuildError, read_jsonl, sort_and_order, write_dataframe

DEFAULT_MANUAL_CLOSE_OVERRIDES_FILE = Path("deltascout/research_material/manual_close_overrides.jsonl")


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise OfflineBuildError(f"missing state file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OfflineBuildError(f"invalid state json: {path}: {exc}") from exc


def _load_peak_events(archive_files: Path | list[Path]) -> pd.DataFrame:
    if isinstance(archive_files, Path):
        archive_files = [archive_files]
    rows: list[dict[str, Any]] = []
    for archive_file in archive_files:
        if not archive_file.exists():
            continue
        rows.extend(r for r in read_jsonl(archive_file) if r.get("event") == "PEAK_EMIT")
    if not rows:
        return pd.DataFrame(
            {
                "event_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "kind": pd.Series(dtype="object"),
                "price": pd.Series(dtype="float64"),
                "delta": pd.Series(dtype="float64"),
                "imb": pd.Series(dtype="float64"),
                "vol": pd.Series(dtype="float64"),
                "seq": pd.Series(dtype="Int64"),
            }
        )
    df = pd.DataFrame(rows)
    df["event_ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    if df["event_ts"].isna().any():
        raise OfflineBuildError("invalid ts in PEAK_EMIT archive rows")
    return df


def _filter_df_by_date(df: pd.DataFrame, ts_col: str, source_date: str) -> pd.DataFrame:
    out = df.copy()
    if ts_col not in out.columns:
        raise OfflineBuildError(f"missing timestamp column '{ts_col}' for date scoping")
    out["_date"] = out[ts_col].dt.strftime("%Y-%m-%d")
    out = out[out["_date"] == source_date].copy()
    return out.drop(columns=["_date"])


def _load_trade_outcomes_events(trade_outcomes_file: Path, source_date: str | None = None) -> list[dict[str, Any]]:
    if not trade_outcomes_file.exists():
        return []
    events: list[dict[str, Any]] = []
    for row in read_jsonl(trade_outcomes_file):
        if not isinstance(row, dict):
            continue
        lc = row.get("last_closed") if isinstance(row.get("last_closed"), dict) else None
        if not lc:
            continue
        evt: dict[str, Any] = {
            # top-level record metadata
            "schema": row.get("schema"),
            "event": row.get("event"),
            "record_ts": row.get("ts"),
            "symbol": row.get("symbol"),
            "source": row.get("source"),
            # compatibility hints
            "action": "CLOSE",
        }

        # flatten full last_closed snapshot with stable prefix
        for k, v in lc.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                evt[f"lc_{k}"] = v
            elif isinstance(v, dict) and k == "prices":
                for pk, pv in v.items():
                    if isinstance(pv, (str, int, float, bool)) or pv is None:
                        evt[f"lc_prices_{pk}"] = pv
            else:
                # keep small nested event payload for exact join support
                if k == "src_evt" and isinstance(v, dict):
                    evt["src_evt"] = v

        # normalized aliases to keep existing join/derivation semantics
        evt["ts"] = lc.get("ts") or row.get("ts")
        evt["closed_at"] = lc.get("closed_at")
        evt["mode"] = lc.get("mode")
        evt["reason"] = lc.get("reason") or lc.get("close_reason")
        evt["close_reason"] = lc.get("close_reason") or lc.get("reason")
        evt["close_price"] = lc.get("close_price")
        evt["side"] = lc.get("side")
        evt["entry"] = lc.get("entry")
        evt["sl"] = lc.get("sl")

        if source_date:
            evt_ts = pd.to_datetime(evt.get("ts") or evt.get("closed_at"), utc=True, errors="coerce")
            if pd.isna(evt_ts) or evt_ts.strftime("%Y-%m-%d") != source_date:
                continue
        events.append(evt)
    return events


def _load_manual_close_overrides(overrides_file: Path, source_date: str) -> list[dict[str, Any]]:
    if not overrides_file.exists():
        return []

    rows: list[dict[str, Any]] = []
    for row in read_jsonl(overrides_file):
        if not isinstance(row, dict):
            continue
        if str(row.get("source_date") or "").strip() != source_date:
            continue
        if str(row.get("peak_ts") or "").strip() == "":
            continue
        if str(row.get("peak_kind") or "").strip() == "":
            continue
        rows.append(row)
    return rows


def _load_close_events(exec_log_file: Path, state_file: Path, trade_outcomes_file: Path, source_date: str) -> list[dict[str, Any]]:
    trade_events = _load_trade_outcomes_events(trade_outcomes_file, source_date=source_date)
    if trade_events:
        return trade_events

    # legacy/backfill compatibility path when canonical trade outcomes are unavailable
    events = []
    if exec_log_file.exists():
        for r in read_jsonl(exec_log_file):
            if str(r.get("action") or "").upper() == "CLOSE":
                events.append(r)
    st = _safe_load_json(state_file)
    lc = st.get("last_closed")
    if isinstance(lc, dict) and lc:
        events.append({"source": "state", "action": "CLOSE", **lc})
    if not events:
        raise OfflineBuildError("no close evidence found in executor.log or executor_state.json:last_closed")
    return events


def _close_identity_key(row: dict[str, Any]) -> str:
    close_ts = pd.to_datetime(row.get("ts") or row.get("closed_at"), utc=True, errors="coerce")
    # tiny skew tolerance for cross-source evidence (e.g. log vs state +/-1s)
    ts = "" if pd.isna(close_ts) else close_ts.floor("2s").isoformat()
    reason = str(row.get("reason") or row.get("close_reason") or "").strip().upper()
    mode = str(row.get("mode") or "").strip().upper()
    side = str(row.get("side") or "").strip().upper()

    def _norm_num(v: Any) -> str:
        try:
            return f"{float(v):.8f}"
        except Exception:
            return ""

    close_price = _norm_num(row.get("close_price"))
    entry = _norm_num(row.get("entry"))
    sl = _norm_num(row.get("sl"))
    trade_key = str(row.get("lc_trade_key") or row.get("trade_key") or "").strip()
    symbol = str(row.get("symbol") or row.get("lc_symbol") or "").strip().upper()

    if trade_key:
        raw = "|".join(["trade_key", trade_key, symbol, reason, ts, side])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    src_evt = row.get("src_evt") if isinstance(row.get("src_evt"), dict) else {}
    src_evt_ts_parsed = pd.to_datetime(src_evt.get("ts"), utc=True, errors="coerce")
    src_evt_ts = "" if pd.isna(src_evt_ts_parsed) else src_evt_ts_parsed.floor("s").isoformat()
    src_evt_kind = str(src_evt.get("kind") or "").strip().lower()
    raw = "|".join([ts, reason, mode, side, close_price, entry, sl, src_evt_ts, src_evt_kind])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _dedupe_close_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Deterministic rule: keep the first seen close by key, preferring executor.log ordering,
    # then skip same-key duplicates from state snapshot.
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for evt in events:
        k = _close_identity_key(evt)
        if k in seen:
            continue
        seen.add(k)
        out.append(evt)
    return out


def _filter_close_events_by_date(events: list[dict[str, Any]], source_date: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for evt in events:
        ts = pd.to_datetime(evt.get("ts") or evt.get("closed_at"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        if ts.strftime("%Y-%m-%d") == source_date:
            out.append(evt)
    return out


def _kind_from_side(side: Any) -> str | None:
    s = str(side or "").upper()
    if s == "LONG":
        return "long"
    if s == "SHORT":
        return "short"
    return None


def _float_eq(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _join_peak(close_row: dict[str, Any], peaks: pd.DataFrame, window_min: int) -> tuple[str, float, dict[str, Any] | None]:
    src_evt = close_row.get("src_evt")
    if isinstance(src_evt, dict) and src_evt:
        ts = pd.to_datetime(src_evt.get("ts"), utc=True, errors="coerce")
        k = str(src_evt.get("kind") or "")
        cands = peaks.copy()
        if pd.notna(ts):
            cands = cands[cands["event_ts"] == ts]
        if k:
            cands = cands[cands["kind"] == k]
        if not cands.empty:
            def _score(row: pd.Series) -> int:
                score = 0
                for f in ("price", "delta", "imb", "vol"):
                    if f in src_evt and _float_eq(src_evt.get(f), row.get(f), tol=1e-6):
                        score += 1
                return score
            cands = cands.assign(_score=cands.apply(_score, axis=1)).sort_values(["_score", "seq"], ascending=[False, True])
            best = cands.iloc[0].to_dict()
            return "exact", 1.0, best

    close_ts = pd.to_datetime(close_row.get("ts"), utc=True, errors="coerce")
    if pd.isna(close_ts):
        return "missing", 0.0, None
    kind = _kind_from_side(close_row.get("side"))
    cands = peaks.copy()
    if kind:
        cands = cands[cands["kind"] == kind]
    lo = close_ts - pd.Timedelta(minutes=window_min)
    opened_at = pd.to_datetime(close_row.get("lc_opened_at") or close_row.get("opened_at"), utc=True, errors="coerce")
    if pd.notna(opened_at):
        lo = max(lo, opened_at)
    cands = cands[(cands["event_ts"] <= close_ts) & (cands["event_ts"] >= lo)]
    if len(cands) == 1:
        return "window_match", 0.6, cands.iloc[0].to_dict()
    if len(cands) > 1:
        return "ambiguous", 0.2, None
    return "missing", 0.0, None


def _derive_trade_lifecycle_state(row: dict[str, Any]) -> str:
    tp1_done = _to_bool(row.get("lc_tp1_done"))
    tp2_done = _to_bool(row.get("lc_tp2_done"))
    sl_done = _to_bool(row.get("lc_sl_done"))
    trail_active = _to_bool(row.get("lc_trail_active"))

    if (not tp1_done) and (not tp2_done) and sl_done:
        return "plain_sl"
    if tp1_done and (not tp2_done) and sl_done:
        return "tp1_then_sl"
    if tp1_done and tp2_done and sl_done:
        return "tp1_tp2_then_trailing_stop"
    return ""


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes"}


def _load_peak_archive_files(input_root: Path, source_date: str, lookback_days: int) -> list[Path]:
    start = pd.Timestamp(source_date) - pd.Timedelta(days=lookback_days)
    end = pd.Timestamp(source_date)
    files: list[Path] = []
    current = start
    while current <= end:
        files.append(input_root / "archive" / "deltascout" / f"{current.strftime('%Y-%m-%d')}.jsonl")
        current += pd.Timedelta(days=1)
    return files


def derive_close_outcomes(close_events: list[dict[str, Any]], peaks: pd.DataFrame, source_date: str, window_min: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for r in close_events:
        join_status, confidence, peak = _join_peak(r, peaks, window_min)
        src_evt = r.get("src_evt") if isinstance(r.get("src_evt"), dict) else None
        close_ts = pd.to_datetime(r.get("ts") or r.get("closed_at"), utc=True, errors="coerce")
        close_key = _close_identity_key(r)
        row = {
            "close_key": close_key,
            "source_date": source_date,
            "close_ts": close_ts,
            "mode": r.get("mode"),
            "close_reason": r.get("reason") or r.get("close_reason"),
            "close_price": r.get("close_price"),
            "side": r.get("side"),
            "entry": r.get("entry"),
            "sl": r.get("sl"),
            "join_status": join_status,
            "join_confidence": confidence,
            "lifecycle_tp1_done": r.get("lc_tp1_done", ""),
            "lifecycle_tp2_done": r.get("lc_tp2_done", ""),
            "lifecycle_sl_done": r.get("lc_sl_done", ""),
            "lifecycle_trail_active": r.get("lc_trail_active", ""),
            "lifecycle_trail_sl_price": r.get("lc_trail_sl_price", ""),
            "lifecycle_prices_entry": r.get("lc_prices_entry", ""),
            "lifecycle_prices_sl": r.get("lc_prices_sl", ""),
            "lifecycle_prices_tp1": r.get("lc_prices_tp1", ""),
            "lifecycle_prices_tp2": r.get("lc_prices_tp2", ""),
            "trade_lifecycle_state": _derive_trade_lifecycle_state(r),
            "src_evt_ts": (src_evt or {}).get("ts"),
            "src_evt_kind": (src_evt or {}).get("kind"),
            "src_evt_price": (src_evt or {}).get("price"),
            "peak_ts": (peak or {}).get("event_ts"),
            "peak_kind": (peak or {}).get("kind"),
            "peak_price": (peak or {}).get("price"),
            "peak_delta": (peak or {}).get("delta"),
            "peak_imb": (peak or {}).get("imb"),
            "peak_vol": (peak or {}).get("vol"),
        }

        extra_cols = {
            k: v
            for k, v in r.items()
            if k.startswith("lc_") or k in {"schema", "event", "record_ts", "symbol", "source"}
        }
        row.update(extra_cols)
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["source_date", "close_ts", "join_status"])  # pragma: no cover
    return sort_and_order(
        df,
        sort_cols=["close_ts", "close_key", "join_status"],
        col_order=[
            "close_key",
            "source_date",
            "close_ts",
            "mode",
            "close_reason",
            "close_price",
            "side",
            "entry",
            "sl",
            "join_status",
            "join_confidence",
            "lifecycle_tp1_done",
            "lifecycle_tp2_done",
            "lifecycle_sl_done",
            "lifecycle_trail_active",
            "lifecycle_trail_sl_price",
            "lifecycle_prices_entry",
            "lifecycle_prices_sl",
            "lifecycle_prices_tp1",
            "lifecycle_prices_tp2",
            "trade_lifecycle_state",
            "src_evt_ts",
            "src_evt_kind",
            "src_evt_price",
            "peak_ts",
            "peak_kind",
            "peak_price",
            "peak_delta",
            "peak_imb",
            "peak_vol",
            "schema",
            "event",
            "record_ts",
            "symbol",
            "source",
        ],
    )


def _manual_override_identity_key(row: dict[str, Any]) -> tuple[str, str]:
    return (
        str(row.get("peak_ts") or "").strip(),
        str(row.get("peak_kind") or "").strip().lower(),
    )


def _merge_manual_close_overrides(close_df: pd.DataFrame, manual_rows: list[dict[str, Any]], source_date: str) -> pd.DataFrame:
    if not manual_rows:
        return close_df

    existing_peak_keys: set[tuple[str, str]] = set()
    if not close_df.empty:
        for _, row in close_df.iterrows():
            peak_ts = row.get("peak_ts")
            peak_kind = row.get("peak_kind")
            if pd.notna(peak_ts) and str(peak_ts).strip():
                existing_peak_keys.add((str(peak_ts).strip(), str(peak_kind or "").strip().lower()))

    manual_records: list[dict[str, Any]] = []
    for row in manual_rows:
        peak_key = _manual_override_identity_key(row)
        if peak_key in existing_peak_keys:
            continue
        manual_records.append(
            {
                "close_key": str(row.get("close_key") or f"manual_override:{source_date}:{peak_key[0]}:{peak_key[1]}"),
                "source_date": source_date,
                "close_ts": row.get("close_ts", ""),
                "mode": row.get("mode", "manual_override"),
                "close_reason": row.get("close_reason", ""),
                "close_price": row.get("close_price", ""),
                "side": row.get("side", ""),
                "entry": row.get("entry", ""),
                "sl": row.get("sl", ""),
                "join_status": row.get("join_status", "manual_override"),
                "join_confidence": row.get("join_confidence", "1.0"),
                "lifecycle_tp1_done": row.get("lifecycle_tp1_done", ""),
                "lifecycle_tp2_done": row.get("lifecycle_tp2_done", ""),
                "lifecycle_sl_done": row.get("lifecycle_sl_done", ""),
                "lifecycle_trail_active": row.get("lifecycle_trail_active", ""),
                "lifecycle_trail_sl_price": row.get("lifecycle_trail_sl_price", ""),
                "lifecycle_prices_entry": row.get("lifecycle_prices_entry", row.get("entry", "")),
                "lifecycle_prices_sl": row.get("lifecycle_prices_sl", row.get("sl", "")),
                "lifecycle_prices_tp1": row.get("lifecycle_prices_tp1", ""),
                "lifecycle_prices_tp2": row.get("lifecycle_prices_tp2", ""),
                "trade_lifecycle_state": row.get("trade_lifecycle_state", "manual_override"),
                "src_evt_ts": row.get("src_evt_ts", row.get("peak_ts", "")),
                "src_evt_kind": row.get("src_evt_kind", row.get("peak_kind", "")),
                "src_evt_price": row.get("src_evt_price", row.get("peak_price", row.get("entry", ""))),
                "peak_ts": row.get("peak_ts", ""),
                "peak_kind": row.get("peak_kind", ""),
                "peak_price": row.get("peak_price", ""),
                "peak_delta": row.get("peak_delta", ""),
                "peak_imb": row.get("peak_imb", ""),
                "peak_vol": row.get("peak_vol", ""),
                "schema": row.get("schema", "manual_close_override_v1"),
                "event": row.get("event", "MANUAL_CLOSE_OVERRIDE"),
                "record_ts": row.get("record_ts", ""),
                "symbol": row.get("symbol", ""),
                "source": row.get("source", "manual_user_confirmed"),
            }
        )

    if not manual_records:
        return close_df

    manual_df = pd.DataFrame(manual_records)
    combined = pd.concat([close_df, manual_df], ignore_index=True, sort=False)
    return sort_and_order(
        combined,
        sort_cols=["close_ts", "close_key", "join_status"],
        col_order=[
            "close_key",
            "source_date",
            "close_ts",
            "mode",
            "close_reason",
            "close_price",
            "side",
            "entry",
            "sl",
            "join_status",
            "join_confidence",
            "lifecycle_tp1_done",
            "lifecycle_tp2_done",
            "lifecycle_sl_done",
            "lifecycle_trail_active",
            "lifecycle_trail_sl_price",
            "lifecycle_prices_entry",
            "lifecycle_prices_sl",
            "lifecycle_prices_tp1",
            "lifecycle_prices_tp2",
            "trade_lifecycle_state",
            "src_evt_ts",
            "src_evt_kind",
            "src_evt_price",
            "peak_ts",
            "peak_kind",
            "peak_price",
            "peak_delta",
            "peak_imb",
            "peak_vol",
            "schema",
            "event",
            "record_ts",
            "symbol",
            "source",
        ],
    )


def run(args: argparse.Namespace) -> None:
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    exec_log = Path(args.exec_log) if args.exec_log else input_root / "logs" / "executor.log"
    state_file = Path(args.state_file) if args.state_file else input_root / "state" / "executor_state.json"
    trade_outcomes_file = Path(args.trade_outcomes_file) if args.trade_outcomes_file else input_root / "state" / "trade_outcomes.jsonl"
    manual_overrides_file = Path(args.manual_overrides_file) if args.manual_overrides_file else DEFAULT_MANUAL_CLOSE_OVERRIDES_FILE

    peak_files = _load_peak_archive_files(input_root, args.date, args.peak_lookback_days)
    peaks = _load_peak_events(peak_files)
    close_events = _load_close_events(exec_log, state_file, trade_outcomes_file, args.date)
    close_events = _filter_close_events_by_date(close_events, args.date)
    close_events = _dedupe_close_events(close_events)
    close_df = derive_close_outcomes(close_events, peaks, args.date, args.window_min)
    close_df = _merge_manual_close_overrides(
        close_df,
        _load_manual_close_overrides(manual_overrides_file, args.date),
        args.date,
    )

    out_path = write_dataframe(close_df, output_root / f"close_outcomes_{args.date}")
    print(f"close_outcomes rows={len(close_df)} path={out_path} join_status={close_df['join_status'].value_counts().to_dict()}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build offline close outcomes dataset for DeltaScout Phase 1")
    p.add_argument("--date", required=True, help="Date in YYYY-MM-DD")
    p.add_argument("--input-root", default="/data", help="Root with archive/logs/state")
    p.add_argument("--output-root", default="/data/archive/datasets", help="Output dataset root")
    p.add_argument("--trade-outcomes-file", default=None, help="Optional explicit trade_outcomes.jsonl path")
    p.add_argument("--exec-log", default=None, help="Optional explicit executor.log path")
    p.add_argument("--state-file", default=None, help="Optional explicit executor_state.json path")
    p.add_argument("--manual-overrides-file", default=None, help="Optional manual close-override JSONL path")
    p.add_argument("--window-min", type=int, default=4320, help="Fallback join window in minutes")
    p.add_argument("--peak-lookback-days", type=int, default=3, help="How many prior UTC days of PEAK_EMIT archive rows to load for close linkage")
    return p


if __name__ == "__main__":
    run(build_parser().parse_args())
