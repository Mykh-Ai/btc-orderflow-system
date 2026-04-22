from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..types import NormalizedEvent


def _parse_ts(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00").replace(" ", "T")
    return datetime.fromisoformat(normalized)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def read_archive_events(paths: Iterable[Path]) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    for path in sorted(paths):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                ts = _parse_ts(str(row["ts"]))
                events.append(
                    NormalizedEvent(
                        ts=ts,
                        event_type=str(row["event"]),
                        kind=row.get("kind"),
                        reject_reason=row.get("reject_reason"),
                        delta=_to_float(row.get("delta")),
                        vol=_to_float(row.get("vol")),
                        imb=_to_float(row.get("imb")),
                        price=_to_float(row.get("price")),
                        vwap=_to_float(row.get("vwap")),
                        poc=_to_float(row.get("poc")),
                        source_file=path.name,
                        raw=row,
                    )
                )
    return sorted(events, key=lambda item: item.ts)
