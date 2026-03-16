#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.offline.common import OfflineBuildError, load_feed, read_jsonl, sort_and_order, write_dataframe


def _read_archive(archive_file: Path) -> pd.DataFrame:
    events = read_jsonl(archive_file)
    if not events:
        raise OfflineBuildError(f"empty archive file: {archive_file}")
    df = pd.DataFrame(events)
    if "event" not in df.columns or "ts" not in df.columns:
        raise OfflineBuildError("archive must contain event and ts fields")
    df["event_ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    if df["event_ts"].isna().any():
        raise OfflineBuildError("archive contains invalid ts values")
    return df


def _filter_df_by_date(df: pd.DataFrame, ts_col: str, source_date: str) -> pd.DataFrame:
    out = df.copy()
    if ts_col not in out.columns:
        raise OfflineBuildError(f"missing timestamp column '{ts_col}' for date scoping")
    out["_date"] = out[ts_col].dt.strftime("%Y-%m-%d")
    out = out[out["_date"] == source_date].copy()
    return out.drop(columns=["_date"])


def derive_reject_dataset(df_evt: pd.DataFrame, source_date: str, soft_vwap_margin: float, soft_imb_margin: float) -> pd.DataFrame:
    rej = df_evt[df_evt["event"].isin(["CANDIDATE_COMPARISON_REJECT", "CANDIDATE_GATE_REJECT"])].copy()
    if rej.empty:
        return pd.DataFrame(columns=["source_date", "event", "event_ts", "kind", "reject_reason", "reject_class", "seq"])

    def classify(row: pd.Series) -> str:
        reason = str(row.get("reject_reason") or "")
        if reason in {"3of3_fail", "chop_coh", "ema50_vwap_regime"}:
            return "multi_condition"
        cls = "single_condition"

        # conservative soft-fail heuristics from available numeric margins only
        if reason == "vwap_distance":
            price = row.get("price")
            vwap = row.get("vwap")
            cap = row.get("vwap_max_dist_usd")
            if cap is None:
                cap = 1000.0
            try:
                over = abs(float(price) - float(vwap)) - float(cap)
                if 0.0 <= over <= soft_vwap_margin:
                    return "soft_fail"
            except Exception:
                pass
        if reason == "imb_band":
            imb = row.get("imb")
            lo = row.get("imb_min")
            hi = row.get("imb_max")
            try:
                imb_f = float(imb)
                lo_f = float(lo)
                hi_f = float(hi)
                d = min(abs(imb_f - lo_f), abs(imb_f - hi_f))
                if d <= soft_imb_margin:
                    return "soft_fail"
            except Exception:
                pass
        return cls

    rej["reject_class"] = rej.apply(classify, axis=1)
    rej["source_date"] = source_date
    out = sort_and_order(
        rej,
        sort_cols=["event_ts", "seq"],
        col_order=["source_date", "event", "event_ts", "kind", "reject_reason", "reject_class", "seq", "ts"],
    )
    return out


def derive_baseline_init(df_evt: pd.DataFrame, source_date: str) -> pd.DataFrame:
    base = df_evt[(df_evt["event"] == "CANDIDATE_COMPARISON_REJECT") & (df_evt.get("reject_reason") == "no_prev_peak")].copy()
    if base.empty:
        return pd.DataFrame(columns=["source_date", "event_ts", "kind", "seq", "reject_reason"])
    base["source_date"] = source_date
    return sort_and_order(
        base,
        sort_cols=["event_ts", "seq"],
        col_order=["source_date", "event_ts", "kind", "seq", "reject_reason", "event", "ts"],
    )


def derive_window_owner_miss(df_feed: pd.DataFrame, df_evt: pd.DataFrame, source_date: str, roll_window: int, quantile: float) -> pd.DataFrame:
    df = df_feed.copy()
    df["rolling_max"] = df["delta"].rolling(window=roll_window, min_periods=1).max()
    df["rolling_min"] = df["delta"].rolling(window=roll_window, min_periods=1).min()
    df["is_owner_max"] = df["delta"] == df["rolling_max"]
    df["is_owner_min"] = df["delta"] == df["rolling_min"]

    owners = df_evt[df_evt["event"].isin(["DELTA_MAX", "DELTA_MIN"])].copy()
    owner_deltas = pd.to_numeric(owners.get("delta"), errors="coerce").abs().dropna()
    threshold = float(owner_deltas.quantile(quantile)) if not owner_deltas.empty else 0.0

    df["abs_delta"] = df["delta"].abs()
    miss = df[(df["abs_delta"] >= threshold) & (~df["is_owner_max"]) & (~df["is_owner_min"])].copy()
    if miss.empty:
        return pd.DataFrame(columns=["source_date", "ts", "delta", "abs_delta", "rolling_max", "rolling_min", "threshold_abs_delta"])

    miss["source_date"] = source_date
    miss["threshold_abs_delta"] = threshold
    out = sort_and_order(
        miss,
        sort_cols=["ts"],
        col_order=[
            "source_date",
            "ts",
            "delta",
            "abs_delta",
            "price",
            "rolling_max",
            "rolling_min",
            "threshold_abs_delta",
            "is_owner_max",
            "is_owner_min",
        ],
    )
    return out


def derive_late_peak(df_feed: pd.DataFrame, df_evt: pd.DataFrame, source_date: str, lookback_rows: int) -> pd.DataFrame:
    peaks = df_evt[df_evt["event"] == "PEAK_EMIT"].copy()
    if peaks.empty:
        return pd.DataFrame(columns=["source_date", "event_ts", "kind", "move_start_ts", "latency_min", "move_size"])

    feed = df_feed[["ts", "price"]].copy().reset_index(drop=True)
    out_rows: list[dict[str, Any]] = []
    for _, p in peaks.sort_values(["event_ts", "seq"], kind="mergesort").iterrows():
        ts = p["event_ts"]
        kind = str(p.get("kind") or "")
        i = feed[feed["ts"] <= ts].index.max()
        if pd.isna(i):
            continue
        i = int(i)
        lo = max(0, i - lookback_rows)
        window = feed.iloc[lo : i + 1]
        if kind == "long":
            ref_i = window["price"].idxmin()
            ref_price = float(window.loc[ref_i, "price"])
            move_size = float(p.get("price", ref_price)) - ref_price
        else:
            ref_i = window["price"].idxmax()
            ref_price = float(window.loc[ref_i, "price"])
            move_size = ref_price - float(p.get("price", ref_price))
        start_ts = window.loc[ref_i, "ts"]
        latency = (ts - start_ts).total_seconds() / 60.0
        out_rows.append(
            {
                "source_date": source_date,
                "event_ts": ts,
                "kind": kind,
                "seq": p.get("seq"),
                "move_start_ts": start_ts,
                "latency_min": float(latency),
                "move_size": float(move_size),
                "peak_price": p.get("price"),
                "reference_price": ref_price,
                "lookback_rows": lookback_rows,
            }
        )

    if not out_rows:
        return pd.DataFrame(columns=["source_date", "event_ts", "kind", "move_start_ts", "latency_min", "move_size"])
    return sort_and_order(pd.DataFrame(out_rows), ["event_ts", "seq"], ["source_date", "event_ts", "kind", "seq", "move_start_ts", "latency_min", "move_size", "peak_price", "reference_price", "lookback_rows"])


def run(args: argparse.Namespace) -> None:
    input_root = Path(args.input_root)
    archive_file = input_root / "archive" / "deltascout" / f"{args.date}.jsonl"
    feed_file = Path(args.feed_file) if args.feed_file else input_root / "feed" / "aggregated.csv"

    df_evt = _read_archive(archive_file)
    df_feed = load_feed(feed_file)

    df_evt = _filter_df_by_date(df_evt, "event_ts", args.date)
    df_feed = _filter_df_by_date(df_feed, "ts", args.date)
    if df_feed.empty:
        raise OfflineBuildError(f"feed has no rows for requested date {args.date}: {feed_file}")

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    reject = derive_reject_dataset(df_evt, args.date, args.soft_vwap_margin, args.soft_imb_margin)
    baseline = derive_baseline_init(df_evt, args.date)
    owner_miss = derive_window_owner_miss(df_feed, df_evt, args.date, args.roll_window, args.owner_quantile)
    late = derive_late_peak(df_feed, df_evt, args.date, args.late_lookback_rows)

    p_reject = write_dataframe(reject, output_root / f"reject_dataset_{args.date}")
    p_baseline = write_dataframe(baseline, output_root / f"baseline_init_{args.date}")
    p_owner = write_dataframe(owner_miss, output_root / f"window_owner_miss_{args.date}")
    p_late = write_dataframe(late, output_root / f"late_peak_{args.date}")

    print(f"reject_dataset rows={len(reject)} path={p_reject} classes={reject.get('reject_class', pd.Series(dtype=str)).value_counts().to_dict()}")
    print(f"baseline_init rows={len(baseline)} path={p_baseline}")
    print(f"window_owner_miss rows={len(owner_miss)} path={p_owner}")
    print(f"late_peak rows={len(late)} path={p_late}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build DeltaScout Phase 1 derived datasets (offline only)")
    p.add_argument("--date", required=True, help="Date in YYYY-MM-DD")
    p.add_argument("--input-root", default="/data", help="Root with archive/ and feed/")
    p.add_argument("--output-root", default="/data/archive/datasets", help="Output dataset root")
    p.add_argument("--feed-file", default=None, help="Optional explicit feed CSV path")
    p.add_argument("--roll-window", type=int, default=180, help="Rolling ownership window")
    p.add_argument("--owner-quantile", type=float, default=0.75, help="Quantile for meaningful abs(delta) threshold")
    p.add_argument("--late-lookback-rows", type=int, default=30, help="Lookback rows for move-start proxy")
    p.add_argument("--soft-vwap-margin", type=float, default=50.0, help="Soft-fail max excess over vwap cap")
    p.add_argument("--soft-imb-margin", type=float, default=0.01, help="Soft-fail max distance to IMB band")
    return p


if __name__ == "__main__":
    run(build_parser().parse_args())
