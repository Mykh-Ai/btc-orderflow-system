from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..types import FeedRow


def _parse_ts(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00").replace(" ", "T")
    return datetime.fromisoformat(normalized)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    result = float(value)
    if math.isnan(result):
        return None
    return result


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
                        open_interest=_to_float(raw_row.get("OpenInterest")),
                        funding_rate=_to_float(raw_row.get("FundingRate")),
                        liq_buy_qty=_to_float(raw_row.get("LiqBuyQty")),
                        liq_sell_qty=_to_float(raw_row.get("LiqSellQty")),
                        row=raw_row,
                        source_file=path.name,
                    )
                )
    return sorted(rows, key=lambda item: item.ts)
