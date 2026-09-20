"""Research-only canonical replay. No model calls or production state writes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from executor_mod.entry_snapshot import build_entry_snapshot, validate_canonical_monitor_snapshot
from market_monitor.feed_adapter import load_feed
from market_monitor.snapshot_builder_v39a import build_market_monitor_snapshot_v39a


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def feed_lookup(manifest: Path, roots: list[Path]) -> dict[str, tuple[Path, str]]:
    result = {}
    for row in csv.DictReader(manifest.open(encoding="utf-8", newline="")):
        date, expected = row["date_utc"], row["sha256"].lower()
        for root in roots:
            path = root / f"{date}.csv"
            if path.is_file() and path.stat().st_size == int(row["size_bytes"]):
                if hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                    result[date] = (path, expected)
                    break
        else:
            raise FileNotFoundError(f"No SHA-256-matching source: {date}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior-snapshots", type=Path, required=True)
    parser.add_argument("--prior-cases", type=Path, required=True)
    parser.add_argument("--feed-manifest", type=Path, required=True)
    parser.add_argument("--feed-root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = feed_lookup(args.feed_manifest, args.feed_root)
    with args.prior_snapshots.open(encoding="utf-8") as stream:
        old_inputs = {x["signal"]["trade_key"]: x for x in (json.loads(line) for line in stream)}
    cases = list(csv.DictReader(args.prior_cases.open(encoding="utf-8", newline="")))
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = []
    with (args.output / "frozen_canonical_entry_snapshots.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            key = case["trade_key"]
            old = old_inputs[key]
            cutoff = pd.Timestamp(case["cutoff_utc"])
            cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
            days = pd.date_range((cutoff - pd.Timedelta(days=30)).floor("D"), cutoff.floor("D"), freq="D", tz="UTC")
            file_list = [sources[d.strftime("%Y-%m-%d")][0] for d in days]
            feed = load_feed(file_list)
            # The production adapter inspects a whole CSV for IsSynthetic. A
            # completed archive can contain rows later than this case's cutoff.
            # Recompute each file's quality using only rows then available.
            for path in file_list:
                raw = pd.read_csv(path, usecols=lambda name: name in {"Timestamp", "IsSynthetic"})
                if "IsSynthetic" in raw.columns:
                    timestamps = pd.to_datetime(raw["Timestamp"], utc=True, errors="raise")
                    degraded = bool(pd.to_numeric(raw.loc[timestamps <= cutoff, "IsSynthetic"], errors="coerce").fillna(0).ne(0).any())
                else:
                    degraded = False
                if "feed_recovered" in {part.lower() for part in path.parts}:
                    degraded = True
                feed.loc[feed["SourceFile"] == path.name, "DataQuality"] = "RECOVERED_DEGRADED" if degraded else "RAW"
            feed = feed[feed["Timestamp"] <= cutoff].copy()
            current = feed[feed["Timestamp"] >= cutoff - pd.Timedelta(minutes=1439)].copy()
            signal = old["signal"]
            src_evt = {k: v for k, v in signal["fields"].items() if k not in {"ts", "timestamp"}}
            src_evt["kind"] = signal["direction"]
            monitor = build_market_monitor_snapshot_v39a(
                current, context_feed=feed, cutoff_ts=cutoff, state_path=None,
                symbol=signal["symbol"], src_event=src_evt, persist_state=False,
                # Full-day source hashes belong to the separate audit manifest:
                # a cutoff-time model could not have known their final digests.
                lineage={"feed_identity": "historical_sha256_verified_replay", "source_hashes": {}},
            )
            try:
                validate_canonical_monitor_snapshot(monitor)
                valid = True
            except ValueError:
                valid = False
            entry = build_entry_snapshot({
                "trade_key": key, "symbol": signal["symbol"], "direction": signal["direction"],
                "peak_ts": signal["signal_ts_utc"], "analysis_cutoff_ts": cutoff.isoformat(),
                "cutoff_source": signal.get("cutoff_source"), "timestamp_contract": "normalized_utc",
                "src_evt": src_evt, "market_monitor_snapshot": monitor, "market_context": {},
            }, env={"LLM_TRADE_JUDGE_ENABLED": "false"})
            serialized = canonical(entry)
            if any(name in serialized.lower() for name in ('"outcome"', '"realized_pnl"', '"filled_at"')):
                raise ValueError(f"Post-entry field in model input: {key}")
            if pd.Timestamp(entry["decision_cutoff_utc"]) != cutoff:
                raise ValueError(f"Cutoff mismatch: {key}")
            if any(pd.Timestamp(w["end_timestamp"]) > cutoff for w in monitor["windows"].values()):
                raise ValueError(f"Future monitor window: {key}")
            out.write(serialized + "\n")
            old_class = case["input_class"]
            if old_class == "INPUT_RECONSTRUCTABLE_CANONICAL":
                input_class = "INPUT_RECONSTRUCTED_CANONICAL" if valid else "INPUT_INSUFFICIENT"
            else:
                input_class = old_class
            ledger.append({
                "trade_key": key, "cutoff_utc": cutoff.isoformat(), "side": signal["direction"],
                "input_class": input_class, "canonical_validator_pass": valid,
                "monitor_readiness": monitor["quality"]["readiness"],
                "canonical_240_rows": monitor["windows"]["240"]["rows_used"],
                "canonical_1440_rows": monitor["windows"]["1440"]["rows_used"],
                "broad_30d_complete": monitor["broad_context"].get("30d", {}).get("complete"),
                "entry_snapshot_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                "historical_verdict": case["historical_verdict"], "historical_model": case["historical_model"],
                "historical_monitor_schema": case["historical_v1_monitor_schema"],
                "historical_v1_240_rows": case["historical_v1_240_rows"],
                "historical_outcome_reason": case["outcome_reason"], "case_notes": case["case_notes"],
            })
            print(f"{key} {input_class} {monitor['quality']['readiness']}", flush=True)
    with (args.output / "case_ledger.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)


if __name__ == "__main__":
    main()
