from __future__ import annotations

import csv
from datetime import datetime, timezone
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


def test_official_spot_execution_role_does_not_require_signal_recovery_sidecar(tmp_path: Path) -> None:
    feed = tmp_path / "spot"
    fields = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty", "IsSynthetic"]
    _csv(feed / "2026-04-24.csv", fields, {"Timestamp": "2026-04-24 00:00:00", "Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0})

    bars = load_feed(
        feed,
        date_from="2026-04-24",
        date_to="2026-04-24",
        feed_role="official_spot_execution",
    )

    assert bars[0].feed_quality_class == "BINANCE_SPOT_OFFICIAL"
    assert bars[0].recovery_overlap is False
    assert bars[0].ts == datetime(2026, 4, 24, 0, 1, tzinfo=timezone.utc)


def test_official_candle_close_cannot_leak_into_signal_minute(tmp_path, replay_config):
    from deltascout.research_bundle.scout_backtester.execution_policy import build_execution_plan
    from .conftest import bar, candidate

    path = tmp_path / '2026-01-02.csv'
    fields = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'BuyQty', 'SellQty', 'IsSynthetic']
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for ts, price in [('2026-01-02 11:59:00', 100), ('2026-01-02 12:00:00', 104)]:
            writer.writerow(dict(Timestamp=ts, Open=price, High=price, Low=price, Close=price,
                                 Volume=1, BuyQty=.5, SellQty=.5, IsSynthetic=0))
    execution = load_feed(tmp_path, date_from='2026-01-02', date_to='2026-01-02', feed_role='official_spot_execution')
    reference = [bar(0, open_=100, high=100, low=100, close=100)]
    plan = build_execution_plan(candidate(), reference, replay_config, execution_bars=execution)
    assert plan.execution_feed_close_usdc == 100
    assert plan.conversion_ratio == 1
    assert execution[1].ts > candidate().signal_ts_utc


def test_official_close_label_rolls_into_next_utc_day_without_rewriting_input(tmp_path):
    path = tmp_path / '2026-01-02.csv'
    fields = ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'BuyQty', 'SellQty', 'IsSynthetic']
    _csv(path, fields, dict(Timestamp='2026-01-02 23:59:00', Open=100, High=100, Low=100,
                           Close=100, Volume=1, BuyQty=.5, SellQty=.5, IsSynthetic=0))
    before = path.read_bytes()
    execution = load_feed(tmp_path, date_from='2026-01-02', date_to='2026-01-02', feed_role='official_spot_execution')
    signal = load_feed(tmp_path, date_from='2026-01-02', date_to='2026-01-02')
    assert execution[0].ts == datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert signal[0].ts == datetime(2026, 1, 2, 23, 59, tzinfo=timezone.utc)
    assert path.read_bytes() == before
