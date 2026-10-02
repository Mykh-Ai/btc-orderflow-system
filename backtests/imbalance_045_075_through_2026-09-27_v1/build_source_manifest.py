from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(relative_root: str, suffix: str, date_from: str, date_to: str) -> dict:
    root = HERE / relative_root
    files = [
        path for path in sorted(root.glob(f"*{suffix}"))
        if date_from <= path.stem <= date_to
    ]
    return {
        "root": str(root),
        "file_count": len(files),
        "first": files[0].name if files else None,
        "last": files[-1].name if files else None,
        "bytes": sum(path.stat().st_size for path in files),
        "files": [
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }


def main() -> None:
    date_from = "2026-03-17"
    date_to = "2026-09-27"
    execution_quality = read_csv(
        HERE / "source" / "execution_feed" / "btcusdc_spot_1m" / "provenance" / "daily_quality.csv"
    )
    manifest = {
        "schema": "imbalance_experiment_source_snapshot_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"date_from": date_from, "date_to": date_to},
        "server_sources": {
            "deltascout": "/root/volume-alert/data/archive/deltascout/YYYY-MM-DD.jsonl",
            "legacy_feed": "/root/volume-alert/data/archive/feed/YYYY-MM-DD.csv",
            "enriched_feed": "/opt/aitrader_data/feed/YYYY-MM-DD.csv",
        },
        "deltascout": inventory("source/deltascout", ".jsonl", date_from, date_to),
        "legacy_feed": inventory("source/legacy_feed", ".csv", date_from, date_to),
        "enriched_feed": inventory("source/enriched_feed", ".csv", date_from, date_to),
        "effective_feed": inventory("source/effective_feed", ".csv", date_from, date_to),
        "execution_feed_quality": {
            "days": len(execution_quality),
            "rows": sum(int(row["row_count"]) for row in execution_quality),
            "days_with_gaps": sum(int(row["missing_minutes"]) > 0 for row in execution_quality),
            "duplicate_minutes": sum(int(row["duplicate_minutes"]) for row in execution_quality),
            "first": execution_quality[0]["date_utc"],
            "last": execution_quality[-1]["date_utc"],
        },
    }
    (HERE / "source_snapshot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: value for key, value in manifest.items() if key != "deltascout"
                      and key != "legacy_feed" and key != "enriched_feed"
                      and key != "effective_feed"}, ensure_ascii=False, indent=2))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    main()
