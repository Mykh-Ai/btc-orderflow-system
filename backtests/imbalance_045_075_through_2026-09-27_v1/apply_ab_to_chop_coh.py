from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source"
CANDIDATE_CSV = HERE / "chop_coh_only_detector_candidates.csv"
POLICY_PATH = HERE.parent / "ab_counterfactual_2026-09-28_vwap_distance_v1" / "source" / "loss_avoidance_policy.py"
QUALITY_PATH = Path(
    r"D:\Project_V\btc-orderflow-system\deltascout\research_material\recovery_reports"
) / "recovery_quality_2026-04-23_1705_to_2026-05-06_2251.csv"
OUT_CSV = HERE / "chop_coh_ab_results.csv"
OUT_JSON = HERE / "chop_coh_ab_results.json"
LOCAL = ZoneInfo("Europe/Bratislava")
UTC = timezone.utc
TRUSTED_OI_CLASSES = {"REAL_ENRICHED"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=LOCAL).astimezone(UTC)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def load_policy():
    spec = importlib.util.spec_from_file_location("frozen_loss_avoidance_policy", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load policy: {POLICY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.evaluate_loss_avoidance_policy


def main() -> None:
    evaluate = load_policy()
    candidates = read_csv(CANDIDATE_CSV)

    legacy: dict[datetime, dict[str, str]] = {}
    feed: dict[datetime, dict[str, str]] = {}
    for path in sorted((SOURCE / "legacy_feed").glob("*.csv")):
        for row in read_csv(path):
            legacy[parse_local(row["Timestamp"])] = row
    for path in sorted((SOURCE / "effective_feed").glob("*.csv")):
        for row in read_csv(path):
            feed[parse_utc(row["Timestamp"])] = row

    recovery_quality = {
        parse_utc(row["Timestamp"]): row["RecoveryClass"] for row in read_csv(QUALITY_PATH)
    }

    peaks: list[dict] = []
    for path in sorted((SOURCE / "deltascout").glob("*.jsonl")):
        if not ("2026-03-17" <= path.stem <= "2026-09-27"):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") not in {"DELTA_MAX", "DELTA_MIN"}:
                continue
            ts = parse_local(str(event["ts"]))
            legacy_row = legacy.get(ts)
            if legacy_row is None:
                raise RuntimeError(f"missing legacy row for peak {path.name}:{line_number} {ts.isoformat()}")
            peaks.append(
                {
                    "ts": ts,
                    "side": str(event["kind"]).upper(),
                    "exact_abs_delta": abs(float(legacy_row["BuyQty"]) - float(legacy_row["SellQty"])),
                }
            )
    peaks.sort(key=lambda row: (row["ts"], row["side"], row["exact_abs_delta"]))

    output_rows: list[dict] = []
    details: list[dict] = []
    for candidate in candidates:
        cutoff = datetime.fromisoformat(candidate["signal_ts_utc"])
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        side = candidate["side"]
        same_side = [
            row
            for row in peaks
            if cutoff - timedelta(hours=24) <= row["ts"] <= cutoff and row["side"] == side
        ]
        current = next((row for row in same_side if row["ts"] == cutoff), None)
        if current is None:
            raise RuntimeError(f"candidate peak missing at {cutoff.isoformat()} {side}")
        percentile = (
            100.0
            * sum(row["exact_abs_delta"] <= current["exact_abs_delta"] for row in same_side)
            / len(same_side)
        )

        expected_240 = [cutoff - timedelta(minutes=239 - index) for index in range(240)]
        missing = [ts for ts in expected_240 if ts not in feed]
        synthetic = [
            ts
            for ts in expected_240
            if ts in feed and feed[ts]["IsSynthetic"].strip().lower() not in {"0", "false", "no", "n"}
        ]
        if missing or synthetic:
            directional = None
        else:
            buy = sum(float(feed[ts]["BuyQty"]) for ts in expected_240)
            sell = sum(float(feed[ts]["SellQty"]) for ts in expected_240)
            directional = (buy - sell) / (buy + sell) * (1.0 if side == "LONG" else -1.0)

        expected_60 = expected_240[-60:]
        oi_classes = [recovery_quality.get(ts, "REAL_ENRICHED") for ts in expected_60]
        oi_trusted = (
            not any(ts not in feed for ts in expected_60)
            and all(feed[ts].get("OpenInterest", "") != "" for ts in expected_60)
            and all(value in TRUSTED_OI_CLASSES for value in oi_classes)
        )
        oi_change = (
            float(feed[expected_60[-1]]["OpenInterest"])
            - float(feed[expected_60[0]]["OpenInterest"])
            if oi_trusted
            else None
        )

        decision = evaluate(
            same_side_peak_percentile_24h=percentile,
            oi_change_60m=oi_change,
            oi_trusted_60m=oi_trusted,
            directional_delta_pct_240m=directional,
        )
        flat = {
            **candidate,
            "candidate_exact_abs_delta": current["exact_abs_delta"],
            "same_side_peak_count_24h": len(same_side),
            "same_side_peak_percentile_24h": percentile,
            "component_a": decision.component_a,
            "oi_change_60m": oi_change,
            "oi_trusted_60m": oi_trusted,
            "directional_delta_pct_240m": directional,
            "component_b": decision.component_b,
            "union": decision.union,
            "decision": decision.decision,
            "reason_codes": "|".join(decision.reason_codes),
        }
        output_rows.append(flat)
        details.append(
            {
                **flat,
                "ab_policy": decision.to_dict(),
                "component_b_quality": {
                    "missing_240m_rows": [ts.isoformat() for ts in missing],
                    "synthetic_240m_rows": [ts.isoformat() for ts in synthetic],
                    "oi_quality_classes_60m": dict(sorted(Counter(oi_classes).items())),
                },
            }
        )

    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    summary = {
        "schema": "chop_coh_ab_counterfactual_v1",
        "scope": {"date_from": "2026-03-17", "date_to": "2026-09-27"},
        "candidate_count": len(output_rows),
        "decision_counts": dict(sorted(Counter(row["decision"] for row in output_rows).items())),
        "component_counts": {
            "a_true": sum(row["component_a"] is True for row in output_rows),
            "b_true": sum(row["component_b"] is True for row in output_rows),
            "a_and_b_true": sum(
                row["component_a"] is True and row["component_b"] is True for row in output_rows
            ),
            "b_unknown": sum(row["component_b"] is None for row in output_rows),
        },
        "kept_by_side": {
            side: sum(row["side"] == side and row["decision"] != "BLOCK" for row in output_rows)
            for side in ("LONG", "SHORT")
        },
        "blocked_by_side": {
            side: sum(row["side"] == side and row["decision"] == "BLOCK" for row in output_rows)
            for side in ("LONG", "SHORT")
        },
        "policy_path": str(POLICY_PATH),
        "policy_sha256": digest(POLICY_PATH),
        "candidate_csv_sha256": digest(CANDIDATE_CSV),
        "source_snapshot_manifest_sha256": digest(HERE / "source_snapshot_manifest.json"),
        "recovery_quality_sha256": digest(QUALITY_PATH),
        "results": details,
        "interpretation": (
            "Offline cutoff-safe A/B evaluation for candidates rejected before live A/B. "
            "BLOCK is excluded by the union; KEEP and UNKNOWN_KEEP preserve live fail-open behavior."
        ),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
