from __future__ import annotations

from datetime import datetime, timezone

from deltascout.delta_analyzer.modules.build_events_base import build_events_base_dataset
from deltascout.delta_analyzer.modules.build_events_context import build_events_context_dataset
from deltascout.delta_analyzer import cli
from deltascout.delta_analyzer.modules.feed_reader import read_feed_rows
from deltascout.delta_analyzer.types import NormalizedEvent


def test_read_feed_rows_supports_enriched_columns(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty\n"
        "2026-01-02T00:00:00Z,100,101,5,2,12345,0.0001,7,8\n",
        encoding="utf-8",
    )

    rows = read_feed_rows([feed])

    assert len(rows) == 1
    row = rows[0]
    assert row.ts == datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc)
    assert row.price == 101.0
    assert row.open_interest == 12345.0
    assert row.funding_rate == 0.0001
    assert row.liq_buy_qty == 7.0
    assert row.liq_sell_qty == 8.0


def test_read_feed_rows_supports_legacy_schema_without_optional_columns(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty\n"
        "2026-01-02T00:00:00Z,100,101,5,2\n",
        encoding="utf-8",
    )

    rows = read_feed_rows([feed])

    assert len(rows) == 1
    row = rows[0]
    assert row.open_interest is None
    assert row.funding_rate is None
    assert row.liq_buy_qty is None
    assert row.liq_sell_qty is None


def test_read_feed_rows_treats_empty_and_nan_numeric_values_as_none(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty\n"
        "2026-01-02T00:00:00Z,100,,NaN,2,,nan, ,NaN\n",
        encoding="utf-8",
    )

    rows = read_feed_rows([feed])

    assert len(rows) == 1
    row = rows[0]
    assert row.price == 100.0
    assert row.buy_qty is None
    assert row.sell_qty == 2.0
    assert row.open_interest is None
    assert row.funding_rate is None
    assert row.liq_buy_qty is None
    assert row.liq_sell_qty is None


def test_enriched_feed_fields_propagate_into_analyzer_output(tmp_path):
    feed = tmp_path / "2026-01-02.csv"
    feed.write_text(
        "Timestamp,AvgPrice,ClosePrice,BuyQty,SellQty,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty\n"
        "2026-01-02T00:00:00Z,100,101,5,2,12345,0.0001,7,8\n",
        encoding="utf-8",
    )
    feed_rows = read_feed_rows([feed])
    events = [
        NormalizedEvent(
            ts=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            event_type="PEAK_EMIT",
            kind="long",
            reject_reason=None,
            delta=10.0,
            vol=20.0,
            imb=0.7,
            price=101.0,
            vwap=100.5,
            poc=100.0,
            source_file="archive.jsonl",
            raw={},
        )
    ]

    base_rows = build_events_base_dataset(events, feed_rows)
    context_rows = build_events_context_dataset(base_rows, feed_rows)

    assert base_rows[0].matched_open_interest == 12345.0
    assert base_rows[0].matched_funding_rate == 0.0001
    assert base_rows[0].matched_liq_buy_qty == 7.0
    assert base_rows[0].matched_liq_sell_qty == 8.0
    assert context_rows[0].matched_open_interest == 12345.0
    assert context_rows[0].matched_funding_rate == 0.0001
    assert context_rows[0].matched_liq_buy_qty == 7.0
    assert context_rows[0].matched_liq_sell_qty == 8.0


def test_resolve_feed_files_uses_canonical_default_without_fallback(monkeypatch):
    monkeypatch.setattr(cli, "DEFAULT_FEED_GLOB", "/opt/aitrader/feed/*.csv")

    calls: list[str] = []

    def fake_expand(pattern: str):
        calls.append(pattern)
        if pattern == "/opt/aitrader/feed/*.csv":
            return ["/opt/aitrader/feed/2026-01-02.csv"]
        raise AssertionError(pattern)

    monkeypatch.setattr(cli, "_expand_glob", fake_expand)

    assert cli._resolve_feed_files("/opt/aitrader/feed/*.csv") == ["/opt/aitrader/feed/2026-01-02.csv"]
    assert calls == ["/opt/aitrader/feed/*.csv"]


def test_resolve_feed_files_preserves_explicit_override_without_fallback(monkeypatch):
    calls: list[str] = []

    def fake_expand(pattern: str):
        calls.append(pattern)
        return []

    monkeypatch.setattr(cli, "_expand_glob", fake_expand)

    assert cli._resolve_feed_files("custom/*.csv") == []
    assert calls == ["custom/*.csv"]


def test_main_fails_loudly_when_feed_glob_has_no_matches(monkeypatch):
    monkeypatch.setattr(cli, "_expand_glob", lambda pattern: [])

    class FakeParser:
        def parse_args(self):
            return cli.argparse.Namespace(
                archive_glob=cli.DEFAULT_ARCHIVE_GLOB,
                feed_glob=cli.DEFAULT_FEED_GLOB,
                dataset="events_context",
                build_review=False,
                date=None,
                input_root=cli.DEFAULT_DATASET_ROOT,
                output_root=cli.DEFAULT_DATASET_ROOT,
            )

    monkeypatch.setattr(cli, "build_parser", lambda: FakeParser())

    try:
        cli.main()
    except SystemExit as exc:
        assert str(exc) == "no feed files matched: /opt/aitrader/feed/*.csv"
    else:
        raise AssertionError("expected SystemExit")
