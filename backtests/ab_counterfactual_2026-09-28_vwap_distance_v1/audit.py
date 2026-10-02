"""Offline A/B counterfactual for two Sep 28 VWAP-distance rejects."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
sys.path.insert(0, str(SOURCE))
from loss_avoidance_policy import evaluate_loss_avoidance_policy  # noqa: E402


LOCAL = ZoneInfo("Europe/Bratislava")
CANDIDATES = [
    datetime(2026, 9, 28, 5, 39, tzinfo=timezone.utc),
    datetime(2026, 9, 28, 9, 21, tzinfo=timezone.utc),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL).astimezone(timezone.utc)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    legacy: dict[datetime, dict[str, str]] = {}
    enriched: dict[datetime, dict[str, str]] = {}
    provenance: dict[str, str] = {}
    for path in sorted((SOURCE / "legacy_feed").glob("*.csv")):
        provenance[str(path.relative_to(ROOT))] = digest(path)
        for row in read_csv(path):
            legacy[parse_local(row["Timestamp"])] = row
    for path in sorted((SOURCE / "enriched_feed").glob("*.csv")):
        provenance[str(path.relative_to(ROOT))] = digest(path)
        for row in read_csv(path):
            enriched[parse_utc(row["Timestamp"])] = row

    peaks: list[dict] = []
    rejects: dict[datetime, dict] = {}
    for path in sorted((SOURCE / "deltascout").glob("*.jsonl")):
        provenance[str(path.relative_to(ROOT))] = digest(path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            row = json.loads(line)
            if row.get("event") in {"DELTA_MAX", "DELTA_MIN"}:
                ts = parse_local(row["ts"])
                feed = legacy[ts]
                exact_delta = abs(float(feed["BuyQty"]) - float(feed["SellQty"]))
                peaks.append({
                    "timestamp_utc": ts,
                    "timestamp_local": row["ts"],
                    "side": row["kind"].upper(),
                    "exact_abs_delta": exact_delta,
                    "archive_delta_rounded": abs(float(row["delta"])),
                    "source": f"{path.name}:{line_number}",
                })
            if row.get("event") == "CANDIDATE_COMPARISON_REJECT" and row.get("reject_reason") == "vwap_distance":
                rejects[parse_local(row["ts"])] = dict(row, source=f"{path.name}:{line_number}")
    policy_hash = digest(SOURCE / "loss_avoidance_policy.py")
    provenance["source/loss_avoidance_policy.py"] = policy_hash

    results = []
    for cutoff in CANDIDATES:
        reject = rejects[cutoff]
        same_side = [
            row for row in peaks
            if cutoff - timedelta(hours=24) <= row["timestamp_utc"] <= cutoff and row["side"] == "SHORT"
        ]
        current_delta = next(row["exact_abs_delta"] for row in same_side if row["timestamp_utc"] == cutoff)
        percentile = 100.0 * sum(row["exact_abs_delta"] <= current_delta for row in same_side) / len(same_side)

        expected = [cutoff - timedelta(minutes=239 - index) for index in range(240)]
        missing = [ts.isoformat() for ts in expected if ts not in enriched]
        synthetic = [ts.isoformat() for ts in expected if ts in enriched and enriched[ts]["IsSynthetic"].strip().lower() not in {"0", "false", "no", "n"}]
        if missing or synthetic:
            trusted = False
            oi_change = directional = None
            status = "MISSING_OR_SYNTHETIC"
            buy = sell = None
        else:
            trusted = True
            status = "EXACT"
            buy = sum(float(enriched[ts]["BuyQty"]) for ts in expected)
            sell = sum(float(enriched[ts]["SellQty"]) for ts in expected)
            oi_now = float(enriched[expected[-1]]["OpenInterest"])
            oi_reference = float(enriched[expected[-60]]["OpenInterest"])
            oi_change = oi_now - oi_reference
            directional = (buy - sell) / (buy + sell) * -1.0

        decision = evaluate_loss_avoidance_policy(
            same_side_peak_percentile_24h=percentile,
            oi_change_60m=oi_change,
            oi_trusted_60m=trusted,
            directional_delta_pct_240m=directional,
        )
        results.append({
            "signal_ts_utc": cutoff.isoformat(),
            "signal_ts_bratislava": cutoff.astimezone(LOCAL).isoformat(),
            "side": "SHORT",
            "source_reject": reject["source"],
            "pre_admission_reject_reason": reject["reject_reason"],
            "candidate_exact_abs_delta": current_delta,
            "component_a_inputs": {
                "same_side_peak_count_24h": len(same_side),
                "same_side_peak_percentile_24h": percentile,
                "threshold_block_if_percentile_le": 50.0,
                "sample": [
                    {
                        **row,
                        "timestamp_utc": row["timestamp_utc"].isoformat(),
                    }
                    for row in same_side
                ],
            },
            "component_b_inputs": {
                "feature_status": status,
                "window_start_utc": expected[0].isoformat(),
                "window_end_utc": expected[-1].isoformat(),
                "rows": len(expected) - len(missing),
                "missing_rows": missing,
                "synthetic_rows": synthetic,
                "buy_qty_240m": buy,
                "sell_qty_240m": sell,
                "directional_delta_pct_240m": directional,
                "threshold_block_if_directional_lt": 0.06,
                "oi_reference_ts_utc": expected[-60].isoformat(),
                "oi_reference": float(enriched[expected[-60]]["OpenInterest"]) if trusted else None,
                "oi_now": float(enriched[expected[-1]]["OpenInterest"]) if trusted else None,
                "oi_change_60m": oi_change,
                "oi_trusted_60m": trusted,
            },
            "counterfactual_policy": decision.to_dict(),
        })

    output = {
        "schema": "ab_counterfactual_v1",
        "scope": "Offline counterfactual only; candidates were rejected before live A/B evaluation.",
        "policy_source_sha256": policy_hash,
        "source_sha256": provenance,
        "results": results,
    }
    out_path = ROOT / "results.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
