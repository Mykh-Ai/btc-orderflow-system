from __future__ import annotations

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW = HERE / "source" / "deltascout"
OUT = HERE / "source" / "candidate_index"
TERMINAL = {
    "PEAK_EMIT",
    "PEAK_LOSS_FILTER_REJECT",
    "CANDIDATE_COMPARISON_REJECT",
    "CANDIDATE_GATE_REJECT",
}


def main() -> None:
    total = 0
    for source in sorted(RAW.glob("*.jsonl")):
        day = source.stem
        if not ("2026-03-17" <= day <= "2026-09-27"):
            continue
        rows = []
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            event = str(row.get("event") or "")
            if event not in TERMINAL:
                continue
            rows.append(
                {
                    "ts": row.get("ts", ""),
                    "event_type": event,
                    "kind": row.get("kind", ""),
                    "reject_reason": row.get("reject_reason", ""),
                }
            )
        destination = OUT / day / f"events_context_{day}.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("ts", "event_type", "kind", "reject_reason"),
            )
            writer.writeheader()
            writer.writerows(rows)
        total += len(rows)
    print(f"indexed_terminal_events={total}")


if __name__ == "__main__":
    main()
