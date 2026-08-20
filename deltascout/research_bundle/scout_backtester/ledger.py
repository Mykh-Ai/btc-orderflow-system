from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .contracts import ReplayEvent, TradeResult


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str] | None = None) -> Path:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        seen: set[str] = set()
        for row in materialized:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(materialized)
    return path


def write_trade_ledger(path: Path, results: Iterable[TradeResult]) -> Path:
    rows = [result.to_dict() for result in results]
    fields = list(TradeResult.__dataclass_fields__)
    fields.remove("legs")
    return write_csv(path, rows, fields)


def write_trade_legs(path: Path, results: Iterable[TradeResult]) -> Path:
    rows = [leg.to_dict() for result in results for leg in result.legs]
    fields = [
        "trade_id",
        "leg_id",
        "leg_type",
        "qty",
        "entry_price",
        "exit_price",
        "exit_ts",
        "gross_pnl_usdc",
        "turnover_usdc",
    ]
    return write_csv(path, rows, fields)


def write_replay_events(path: Path, events: Iterable[ReplayEvent]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return path
