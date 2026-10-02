from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source" / "deltascout"
OUT_CSV = HERE / "chop_coh_only_detector_candidates.csv"
OUT_JSON = HERE / "chop_coh_only_detector_summary.json"
LOCAL_TZ = ZoneInfo("Europe/Bratislava")
UTC = ZoneInfo("UTC")


def utc_timestamp(local_text: str) -> str:
    local = datetime.strptime(local_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(UTC).isoformat()


def main() -> None:
    all_rejects: list[dict] = []
    detector_only: list[dict] = []
    for path in sorted(SOURCE.glob("*.jsonl")):
        if not ("2026-03-17" <= path.stem <= "2026-09-27"):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event") != "CANDIDATE_GATE_REJECT" or event.get("reject_reason") != "chop_coh":
                continue
            side = str(event["kind"]).upper()
            imbalance = float(event["imb"])
            chop = float(event["chop30"])
            coh = float(event["coh10"])
            imb_min = 0.50 if side == "LONG" else 0.54
            imb_max = 0.69
            chop_failed = chop > 3.0
            coh_failed = coh < 0.30
            row = {
                "signal_ts_utc": utc_timestamp(str(event["ts"])),
                "source_ts_local": event["ts"],
                "side": side,
                "imbalance": imbalance,
                "chop30": chop,
                "coh10": coh,
                "failure_component": (
                    "BOTH" if chop_failed and coh_failed else "CHOP" if chop_failed else "COH"
                ),
                "price_now": event.get("price_now"),
                "ema50_now": event.get("ema50_now"),
                "vwap_now": event.get("vwap_now"),
                "source_file": path.name,
                "source_line": line_number,
            }
            all_rejects.append(row)
            if imb_min <= imbalance <= imb_max:
                detector_only.append(row)

    detector_only.sort(key=lambda row: row["signal_ts_utc"])
    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(detector_only[0]))
        writer.writeheader()
        writer.writerows(detector_only)

    summary = {
        "scope": {"date_from": "2026-03-17", "date_to": "2026-09-27"},
        "thresholds": {
            "long_imbalance": [0.50, 0.69],
            "short_imbalance": [0.54, 0.69],
            "chop30_max": 3.0,
            "coh10_min": 0.30,
        },
        "all_chop_coh_rejects": len(all_rejects),
        "pass_side_specific_imbalance": len(detector_only),
        "by_side": dict(sorted(Counter(row["side"] for row in detector_only).items())),
        "by_failure_component": dict(
            sorted(Counter(row["failure_component"] for row in detector_only).items())
        ),
        "by_side_and_failure": {
            f"{side}_{component}": sum(
                row["side"] == side and row["failure_component"] == component
                for row in detector_only
            )
            for side in ("LONG", "SHORT")
            for component in ("CHOP", "COH", "BOTH")
        },
        "candidates": detector_only,
        "interpretation": (
            "These candidates passed all gates preceding chop_coh and also fit the requested "
            "side-specific imbalance bands. A/B was not evaluated live because chop_coh rejected "
            "them first; therefore they are detector-only candidates, not guaranteed PEAK_EMITs."
        ),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
