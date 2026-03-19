from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..types import FeedRow


def _parse_ts(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00").replace(" ", "T")
    return datetime.fromisoformat(normalized)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def read_feed_rows(paths: Iterable[Path]) -> list[FeedRow]:
    rows: list[FeedRow] = []
    for path in sorted(paths):
        with path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                ts = _parse_ts(str(raw_row["Timestamp"]))
                price = _to_float(raw_row.get("ClosePrice"))
                if price is None:
                    price = _to_float(raw_row.get("AvgPrice"))
                rows.append(
                    FeedRow(
                        ts=ts,
                        price=price,
                        buy_qty=_to_float(raw_row.get("BuyQty")),
                        sell_qty=_to_float(raw_row.get("SellQty")),
                        row=raw_row,
                        source_file=path.name,
                    )
                )
    return sorted(rows, key=lambda item: item.ts)
