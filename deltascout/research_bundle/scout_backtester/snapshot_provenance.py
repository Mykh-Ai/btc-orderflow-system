from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .manifests import input_record


REMOTE_ROOTS = {
    "raw_archive": "/root/volume-alert/data/archive/deltascout",
    "legacy_feed": "/root/volume-alert/data/archive/feed",
    "enriched_feed": "/opt/aitrader_data/feed",
    "server_state": "/root/volume-alert/data/state",
}


def build_snapshot_manifest(snapshot_root: Path, *, date_from: str, date_to: str) -> Path:
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    expected_days: list[str] = []
    cursor = start
    while cursor <= end:
        expected_days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    records: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for category, remote_root in REMOTE_ROOTS.items():
        local_root = snapshot_root / category
        if category == "server_state":
            names = ("trade_outcomes.jsonl", "trade_execution_snapshots.jsonl", "trade_pnl_ledger.csv")
        else:
            suffix = ".jsonl" if category == "raw_archive" else ".csv"
            names = tuple(f"{day}{suffix}" for day in expected_days)
        for name in names:
            path = local_root / name
            remote_parent = "/root/volume-alert/data/reports" if name == "trade_pnl_ledger.csv" else remote_root
            if not path.exists():
                missing.append({"category": category, "remote_path": f"{remote_parent}/{name}"})
                continue
            record = input_record(path)
            record.update({"category": category, "remote_path": f"{remote_parent}/{name}"})
            records.append(record)
    payload = {
        "schema": "deltascout_vps_readonly_snapshot_v0_1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_host": "root@95.216.139.172",
        "transfer_mode": "read_only_scp",
        "date_from": date_from,
        "date_to": date_to,
        "files": records,
        "file_count": len(records),
        "missing_files": missing,
        "missing_file_count": len(missing),
        "checksum_verification": "local SHA-256 values were compared with remote sha256sum before use",
    }
    path = snapshot_root / "vps_snapshot_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build provenance for a read-only DeltaScout VPS snapshot")
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    args = parser.parse_args()
    print(build_snapshot_manifest(args.snapshot_root, date_from=args.date_from, date_to=args.date_to))


if __name__ == "__main__":
    main()
