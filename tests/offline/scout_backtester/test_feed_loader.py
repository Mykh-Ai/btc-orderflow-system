from __future__ import annotations

import csv
from pathlib import Path

from deltascout.research_bundle.scout_backtester.feed_loader import load_feed


def _csv(path: Path, fields: list[str], row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def test_recovery_quality_is_joined_per_bar(tmp_path: Path) -> None:
    feed = tmp_path / "feed"
    quality = tmp_path / "quality"
    fields = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty", "IsSynthetic"]
    _csv(feed / "2026-04-24.csv", fields, {"Timestamp": "2026-04-24 00:00:00", "Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0})
    _csv(quality / "recovery_quality_test.csv", ["Timestamp", "RecoveryClass"], {"Timestamp": "2026-04-24 00:00:00", "RecoveryClass": "RECOVERED_LEGACY_PRICE"})
    bars = load_feed(feed, date_from="2026-04-24", date_to="2026-04-24", quality_sidecar_root=quality)
    assert bars[0].recovery_overlap is True
    assert bars[0].feed_quality_class == "RECOVERED_LEGACY_PRICE"
