from __future__ import annotations

import csv
from pathlib import Path

from deltascout.research_bundle.scout_backtester.normalize_legacy_aggregator_feed import (
    normalize_legacy_aggregator_feed,
)


LEGACY_HEADER = [
    "Timestamp",
    "Trades",
    "TotalQty",
    "AvgSize",
    "BuyQty",
    "SellQty",
    "AvgPrice",
    "ClosePrice",
    "HiPrice",
    "LowPrice",
]


def _write_day(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(LEGACY_HEADER)
        writer.writerows(rows)


def test_normalizes_legacy_rows_and_preserves_cross_day_open(tmp_path: Path) -> None:
    source = tmp_path / "raw"
    output = tmp_path / "normalized"
    _write_day(
        source / "2026-04-01.csv",
        [
            ["2026-04-01 23:58:00", "10", "2", "0.2", "1", "1", "100", "101", "102", "99"],
            ["2026-04-01 23:59:00", "11", "3", "0.3", "2", "1", "103", "104", "105", "100"],
        ],
    )
    _write_day(
        source / "2026-04-02.csv",
        [
            ["2026-04-02 02:00:00", "12", "4", "0.4", "3", "1", "106", "107", "108", "106"],
        ],
    )

    files, rows = normalize_legacy_aggregator_feed(
        source,
        output,
        date_from="2026-04-01",
        date_to="2026-04-02",
    )

    assert (files, rows) == (2, 3)
    with (output / "daily" / "2026-04-02.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        normalized = list(csv.DictReader(handle))
    assert normalized[0]["Open"] == "104"
    assert normalized[0]["High"] == "108"
    assert normalized[0]["Low"] == "104"
    assert normalized[0]["Close"] == "107"
    assert normalized[0]["IsSynthetic"] == "0"
    assert normalized[0]["Timestamp"] == "2026-04-02 00:00:00"

    with (output / "provenance" / "daily_quality.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        quality = list(csv.DictReader(handle))
    assert quality[-1]["row_count"] == "1"
    assert quality[-1]["missing_minutes"] == "0"
