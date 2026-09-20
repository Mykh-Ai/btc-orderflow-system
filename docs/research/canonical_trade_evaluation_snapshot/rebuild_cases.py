"""Offline research replay from SHA-matched feed and contemporaneous Judge packs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from docs.research.llm_judge_calibration.rebuild_cases import feed_lookup
from executor_mod.trade_evaluation_snapshot import TradeEvaluationSnapshotError, build_trade_evaluation_snapshot
from market_monitor.feed_adapter import load_feed
from market_monitor.snapshot_builder_v39a import build_market_monitor_snapshot_v39a


def _journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def _feed_at_cutoff(paths: list[Path], cutoff: pd.Timestamp) -> pd.DataFrame:
    feed = load_feed(paths)
    for path in paths:
        raw = pd.read_csv(path, usecols=lambda name: name in {"Timestamp", "IsSynthetic"})
        timestamps = pd.to_datetime(raw["Timestamp"], utc=True, errors="raise")
        degraded = bool("IsSynthetic" in raw and pd.to_numeric(
            raw.loc[timestamps <= cutoff, "IsSynthetic"], errors="coerce"
        ).fillna(0).ne(0).any())
        if "feed_recovered" in {part.lower() for part in path.parts}:
            degraded = True
        feed.loc[feed["SourceFile"] == path.name, "DataQuality"] = "RECOVERED_DEGRADED" if degraded else "RAW"
    return feed[feed["Timestamp"] <= cutoff].copy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verdict-journal", type=Path, required=True)
    parser.add_argument("--outcome-journal", type=Path, required=True)
    parser.add_argument("--execution-journal", type=Path)
    parser.add_argument("--prior-signals", type=Path, required=True)
    parser.add_argument("--prior-cases", type=Path, required=True)
    parser.add_argument("--feed-manifest", type=Path, required=True)
    parser.add_argument("--feed-root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = feed_lookup(args.feed_manifest, args.feed_root)
    signals = {x["signal"]["trade_key"]: x["signal"] for x in _journal(args.prior_signals)}
    prior = {row["trade_key"]: row for row in csv.DictReader(args.prior_cases.open(encoding="utf-8", newline=""))}
    verdicts = _journal(args.verdict_journal)
    outcomes = {x["last_closed"].get("trade_key"): x["last_closed"] for x in _journal(args.outcome_journal) if isinstance(x.get("last_closed"), dict)}
    executions = {x.get("trade_key"): x for x in _journal(args.execution_journal)} if args.execution_journal else {}
    args.output.mkdir(parents=True, exist_ok=True)
    ledger = []
    with (args.output / "frozen_trade_evaluation_snapshots.jsonl").open("w", encoding="utf-8") as output:
        for record in verdicts:
            key = record["trade_key"]
            pack = record.get("evidence_pack") or {}
            group = "PRIOR_21" if key in prior else "SUPPLEMENTAL"
            row = {"trade_key": key, "group": group, "journal_status": record.get("llm_call_status"),
                   "snapshot_status": "UNUSABLE", "reason": "", "snapshot_sha256": "",
                   "market_readiness": "", "incomplete_horizons": "", "actual_entry_source": "evidence_pack.entry_actual",
                   "assessment_cutoff_source": "NOT_RECORDED", "outcome_reason": "", "tp1_done": "", "tp2_done": "",
                   "execution_snapshot_status": "", "lifecycle_class": "", "gross_realized_pnl_approx": "",
                   "net_realized_pnl_approx": "", "prior_input_class": prior.get(key, {}).get("input_class", "")}
            try:
                fill = pd.Timestamp(pack.get("filled_at"))
                if pd.isna(fill):
                    raise TradeEvaluationSnapshotError("observed fill time missing")
                fill = fill.tz_localize("UTC") if fill.tzinfo is None else fill.tz_convert("UTC")
                cutoff = fill.floor("min")
                dates = pd.date_range((cutoff - pd.Timedelta(days=30)).floor("D"), cutoff.floor("D"), freq="D", tz="UTC")
                missing = [d.strftime("%Y-%m-%d") for d in dates if d.strftime("%Y-%m-%d") not in sources]
                if missing:
                    raise FileNotFoundError("source feed hash missing for " + ",".join(missing[:3]))
                paths = [sources[d.strftime("%Y-%m-%d")][0] for d in dates]
                feed = _feed_at_cutoff(paths, cutoff)
                current = feed[feed["Timestamp"] >= cutoff - pd.Timedelta(minutes=1439)].copy()
                monitor = build_market_monitor_snapshot_v39a(
                    current, context_feed=feed, cutoff_ts=cutoff, state_path=None,
                    symbol=str(pack.get("symbol") or "BTCUSDC"), src_event=pack.get("src_evt") or {},
                    persist_state=False, lineage={"feed_identity": "historical_sha256_verified_replay", "source_hashes": {}},
                )
                snapshot = build_trade_evaluation_snapshot(
                    pack, monitor, assessment_cutoff_utc=None,
                    assessment_cutoff_source="historical_judge_invocation_timestamp_not_recorded",
                    signal_facts=signals.get(key), reconstructed=True,
                )
                serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if any(token in serialized.lower() for token in ('"outcome"', '"realized_pnl"', '"trailing"', '"verdict"')):
                    raise TradeEvaluationSnapshotError("forbidden future outcome in model input")
                if snapshot["market_cutoff_utc"] != cutoff.isoformat():
                    raise TradeEvaluationSnapshotError("market cutoff mismatch")
                output.write(serialized + "\n")
                row.update(snapshot_status="REBUILT_PARTIAL_ASSESSMENT_TIME", snapshot_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                           market_readiness=monitor["quality"]["readiness"],
                           incomplete_horizons="|".join(snapshot["quality"]["incomplete_horizons"]))
            except (TradeEvaluationSnapshotError, FileNotFoundError, ValueError, KeyError) as exc:
                row["reason"] = f"{type(exc).__name__}:{exc}"
            # Join outcome only after freezing the model input.
            outcome = outcomes.get(key) or {}
            row["outcome_reason"] = outcome.get("reason", "")
            row["tp1_done"] = outcome.get("tp1_done", "")
            row["tp2_done"] = outcome.get("tp2_done", "")
            execution = executions.get(key) or {}
            pnl = execution.get("pnl") or {}
            row["execution_snapshot_status"] = execution.get("snapshot_status", "")
            row["lifecycle_class"] = execution.get("lifecycle_class", "")
            row["gross_realized_pnl_approx"] = pnl.get("gross_realized_pnl_approx") or ""
            row["net_realized_pnl_approx"] = pnl.get("net_realized_pnl_approx") or prior.get(key, {}).get("net_realized_pnl_approx", "")
            ledger.append(row)
            print(key, row["snapshot_status"], row["reason"], flush=True)
    with (args.output / "case_ledger.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)


if __name__ == "__main__":
    main()
