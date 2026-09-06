from __future__ import annotations

from datetime import date, timezone

from deltascout.research_bundle.scout_backtester.acquire_binance_spot_klines import (
    _archive_candidates,
    _timestamp_utc,
)


def test_binance_vision_spot_microsecond_timestamp_is_utc_open_time() -> None:
    parsed = _timestamp_utc("1776933900000000")
    assert parsed.tzinfo == timezone.utc
    assert parsed.isoformat() == "2026-04-23T08:45:00+00:00"


def test_archive_plan_uses_complete_months_then_daily_current_month() -> None:
    items = _archive_candidates("BTCUSDC", "1m", date(2026, 3, 19), date(2026, 8, 19))
    monthly = [item for item in items if item["kind"] == "monthly"]
    daily = [item for item in items if item["kind"] == "daily"]
    assert [item["name"] for item in monthly] == [
        "BTCUSDC-1m-2026-03.zip",
        "BTCUSDC-1m-2026-04.zip",
        "BTCUSDC-1m-2026-05.zip",
        "BTCUSDC-1m-2026-06.zip",
        "BTCUSDC-1m-2026-07.zip",
    ]
    assert len(daily) == 19
    assert daily[0]["name"] == "BTCUSDC-1m-2026-08-01.zip"
    assert daily[-1]["name"] == "BTCUSDC-1m-2026-08-19.zip"
