#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.offline.common import OfflineBuildError, read_jsonl, sort_and_order, write_dataframe


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise OfflineBuildError(f"missing state file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OfflineBuildError(f"invalid state json: {path}: {exc}") from exc


def _load_peak_events(archive_file: Path) -> pd.DataFrame:
    rows = [r for r in read_jsonl(archive_file) if r.get("event") == "PEAK_EMIT"]
    if not rows:
        return pd.DataFrame(
            {
                "event_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "kind": pd.Series(dtype="object"),
                "price": pd.Series(dtype="float64"),
                "delta": pd.Series(dtype="float64"),
                "imb": pd.Series(dtype="float64"),
                "vol": pd.Series(dtype="float64"),
                "seq": pd.Series(dtype="int64"),
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
    if out.empty:
        return out
    out[ts_col] = pd.to_datetime(out[ts_col], utc=True, errors="coerce")
    if out[ts_col].isna().any():
        raise OfflineBuildError(f"invalid timestamp values in '{ts_col}' for date scoping")
    out["_date"] = out[ts_col].dt.strftime("%Y-%m-%d")
    out = out[out["_date"] == source_date].copy()
    return out.drop(columns=["_date"])


def _load_close_events(exec_log_file: Path, state_file: Path) -> list[dict[str, Any]]:
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
    def _norm_scalar(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return f"{float(v):.8f}"
        return str(v)

    def _norm_text(v: Any, *, upper: bool = False, lower: bool = False) -> str:
        text = _norm_scalar(v).strip()
        if upper:
            return text.upper()
        if lower:
            return text.lower()
        return text

    reason = _norm_text(row.get("reason") or row.get("close_reason"), upper=True)
    mode = _norm_text(row.get("mode"), upper=True)
    side = _norm_text(row.get("side"), upper=True)
    close_price = _norm_scalar(row.get("close_price"))
    entry = _norm_scalar(row.get("entry"))
    sl = _norm_scalar(row.get("sl"))
    src_evt = row.get("src_evt") if isinstance(row.get("src_evt"), dict) else {}
    src_evt_ts = _norm_scalar(src_evt.get("ts"))
    src_evt_kind = _norm_text(src_evt.get("kind"), lower=True)
    src_evt_price = _norm_scalar(src_evt.get("price"))

    # executor.log and state.last_closed often emit different close timestamps for the
    # same close; when src_evt is present prefer a ts-free key so cross-source evidence
    # hashes together. Without src_evt, keep a coarse time bucket to avoid collapsing
    # unrelated closes that happen to share reason/price.
    fallback_ts = pd.to_datetime(row.get("ts") or row.get("closed_at"), utc=True, errors="coerce")
    ts_bucket = ""
    if pd.notna(fallback_ts) and not src_evt_ts:
        ts_bucket = fallback_ts.floor("min").isoformat()

    raw = "|".join([reason, mode, side, close_price, entry, sl, src_evt_ts, src_evt_kind, src_evt_price, ts_bucket])
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
    cands = cands[(cands["event_ts"] <= close_ts) & (cands["event_ts"] >= lo)]
    if len(cands) == 1:
        return "window_match", 0.6, cands.iloc[0].to_dict()
    if len(cands) > 1:
        return "ambiguous", 0.2, None
    return "missing", 0.0, None


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
            "src_evt_ts",
            "src_evt_kind",
            "src_evt_price",
            "peak_ts",
            "peak_kind",
            "peak_price",
            "peak_delta",
            "peak_imb",
            "peak_vol",
        ],
    )


def run(args: argparse.Namespace) -> None:
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    archive_file = input_root / "archive" / "deltascout" / f"{args.date}.jsonl"
    exec_log = Path(args.exec_log) if args.exec_log else input_root / "logs" / "executor.log"
    state_file = Path(args.state_file) if args.state_file else input_root / "state" / "executor_state.json"

    peaks = _load_peak_events(archive_file)
    close_events = _load_close_events(exec_log, state_file)
    peaks = _filter_df_by_date(peaks, "event_ts", args.date)
    close_events = _filter_close_events_by_date(close_events, args.date)
    close_events = _dedupe_close_events(close_events)
    close_df = derive_close_outcomes(close_events, peaks, args.date, args.window_min)

    out_path = write_dataframe(close_df, output_root / f"close_outcomes_{args.date}")
    print(f"close_outcomes rows={len(close_df)} path={out_path} join_status={close_df['join_status'].value_counts().to_dict()}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build offline close outcomes dataset for DeltaScout Phase 1")
    p.add_argument("--date", required=True, help="Date in YYYY-MM-DD")
    p.add_argument("--input-root", default="/data", help="Root with archive/logs/state")
    p.add_argument("--output-root", default="/data/archive/datasets", help="Output dataset root")
    p.add_argument("--exec-log", default=None, help="Optional explicit executor.log path")
    p.add_argument("--state-file", default=None, help="Optional explicit executor_state.json path")
    p.add_argument("--window-min", type=int, default=360, help="Fallback join window in minutes")
    return p


if __name__ == "__main__":
    run(build_parser().parse_args())
