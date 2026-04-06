"""Tests for previous-day feed loading to support ret_15m/ret_60m near day boundaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from deltascout.delta_analyzer.cli import _resolve_prev_day_feed
from deltascout.delta_analyzer.modules.build_events_base import build_events_base_dataset
from deltascout.delta_analyzer.modules.build_events_context import build_events_context_dataset
from deltascout.delta_analyzer.modules.feed_reader import read_feed_rows
from deltascout.delta_analyzer.types import NormalizedEvent


def _write_feed(path, rows_text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rows_text, encoding="utf-8")


def _make_event(ts: datetime) -> NormalizedEvent:
    return NormalizedEvent(
        ts=ts,
        event_type="DELTA_MIN",
        kind="short",
        reject_reason=None,
        delta=-10.0,
        vol=20.0,
        imb=0.5,
        price=100.0,
        vwap=100.0,
        poc=100.0,
        source_file="archive.jsonl",
        raw={},
    )


ENRICHED_HEADER = "Timestamp,Open,High,Low,Close,Volume,AggTrades,BuyQty,SellQty,VWAP,OpenInterest,FundingRate,LiqBuyQty,LiqSellQty,IsSynthetic"


def test_resolve_prev_day_feed_finds_previous_date(tmp_path):
    current = tmp_path / "2026-03-20.csv"
    prev = tmp_path / "2026-03-19.csv"
    _write_feed(current, f"{ENRICHED_HEADER}\n")
    _write_feed(prev, f"{ENRICHED_HEADER}\n")

    result = _resolve_prev_day_feed([current], "2026-03-20")

    assert result == prev


def test_resolve_prev_day_feed_returns_none_when_missing(tmp_path):
    current = tmp_path / "2026-03-20.csv"
    _write_feed(current, f"{ENRICHED_HEADER}\n")

    result = _resolve_prev_day_feed([current], "2026-03-20")

    assert result is None


def test_resolve_prev_day_feed_returns_none_without_date():
    assert _resolve_prev_day_feed([], "") is None
    assert _resolve_prev_day_feed([], None) is None


def test_ret_15m_available_with_prev_day_feed(tmp_path):
    """Early-day event at 00:05 needs price at 23:50 from previous day."""
    prev_feed = tmp_path / "2026-03-19.csv"
    curr_feed = tmp_path / "2026-03-20.csv"

    # Previous day: rows from 23:00 to 23:59
    prev_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-19T23:{m:02d}:00Z"
        price = 100.0 + m * 0.1
        prev_lines.append(f"{ts},99,102,98,{price},50,10,5,2,100.5,1000,0.0001,1,1,False")
    _write_feed(prev_feed, "\n".join(prev_lines) + "\n")

    # Current day: rows from 00:00 to 01:00
    curr_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-20T00:{m:02d}:00Z"
        price = 110.0 + m * 0.1
        curr_lines.append(f"{ts},109,112,108,{price},50,10,5,2,110.5,1000,0.0001,1,1,False")
    _write_feed(curr_feed, "\n".join(curr_lines) + "\n")

    # Event at 00:05 — needs price at 23:50 for ret_15m
    event_ts = datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)
    event = _make_event(event_ts)

    # Without previous day: ret_15m should be None
    feed_rows_curr = read_feed_rows([curr_feed])
    base_curr = build_events_base_dataset([event], feed_rows_curr)
    ctx_curr = build_events_context_dataset(base_curr, feed_rows_curr)
    assert ctx_curr[0].ret_15m is None

    # With previous day: ret_15m should be populated
    feed_rows_both = read_feed_rows([prev_feed, curr_feed])
    base_both = build_events_base_dataset([event], feed_rows_curr)  # base uses current-day only
    ctx_both = build_events_context_dataset(base_both, feed_rows_both)
    assert ctx_both[0].ret_15m is not None
    # Price at 00:05 = 110.5, price at 23:50 = 105.0
    assert abs(ctx_both[0].ret_15m - (110.5 - 105.0)) < 0.01


def test_ret_60m_available_with_prev_day_feed(tmp_path):
    """Early-day event at 00:30 needs price at 23:30 from previous day."""
    prev_feed = tmp_path / "2026-03-19.csv"
    curr_feed = tmp_path / "2026-03-20.csv"

    prev_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-19T23:{m:02d}:00Z"
        price = 200.0 + m
        prev_lines.append(f"{ts},199,202,198,{price},50,10,5,2,200,1000,0.0001,1,1,False")
    _write_feed(prev_feed, "\n".join(prev_lines) + "\n")

    curr_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-20T00:{m:02d}:00Z"
        price = 300.0 + m
        curr_lines.append(f"{ts},299,302,298,{price},50,10,5,2,300,1000,0.0001,1,1,False")
    _write_feed(curr_feed, "\n".join(curr_lines) + "\n")

    event_ts = datetime(2026, 3, 20, 0, 30, tzinfo=timezone.utc)
    event = _make_event(event_ts)

    # Without previous day: ret_60m None
    feed_curr = read_feed_rows([curr_feed])
    base = build_events_base_dataset([event], feed_curr)
    ctx = build_events_context_dataset(base, feed_curr)
    assert ctx[0].ret_60m is None

    # With previous day: ret_60m populated
    feed_both = read_feed_rows([prev_feed, curr_feed])
    base = build_events_base_dataset([event], feed_curr)
    ctx = build_events_context_dataset(base, feed_both)
    assert ctx[0].ret_60m is not None
    # Price at 00:30 = 330.0, price at 23:30 = 230.0
    assert abs(ctx[0].ret_60m - (330.0 - 230.0)) < 0.01


def test_missing_prev_day_feed_no_crash(tmp_path):
    """When previous-day feed is absent, early-day returns remain None without error."""
    curr_feed = tmp_path / "2026-03-20.csv"
    curr_lines = [ENRICHED_HEADER]
    for m in range(0, 10):
        ts = f"2026-03-20T00:{m:02d}:00Z"
        curr_lines.append(f"{ts},99,102,98,{100.0 + m},50,10,5,2,100.5,1000,0.0001,1,1,False")
    _write_feed(curr_feed, "\n".join(curr_lines) + "\n")

    event_ts = datetime(2026, 3, 20, 0, 5, tzinfo=timezone.utc)
    event = _make_event(event_ts)

    feed_rows = read_feed_rows([curr_feed])
    base = build_events_base_dataset([event], feed_rows)
    ctx = build_events_context_dataset(base, feed_rows)

    # Should not crash, returns are None because no lookback data
    assert ctx[0].ret_15m is None
    assert ctx[0].ret_60m is None


def test_output_contains_only_requested_date_events(tmp_path):
    """Even with prev-day feed loaded, output events are only for the target date."""
    prev_feed = tmp_path / "2026-03-19.csv"
    curr_feed = tmp_path / "2026-03-20.csv"

    prev_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-19T23:{m:02d}:00Z"
        prev_lines.append(f"{ts},99,102,98,100,50,10,5,2,100,1000,0.0001,1,1,False")
    _write_feed(prev_feed, "\n".join(prev_lines) + "\n")

    curr_lines = [ENRICHED_HEADER]
    for m in range(0, 60):
        ts = f"2026-03-20T00:{m:02d}:00Z"
        curr_lines.append(f"{ts},99,102,98,100,50,10,5,2,100,1000,0.0001,1,1,False")
    _write_feed(curr_feed, "\n".join(curr_lines) + "\n")

    # Events on 03-20 only
    events = [
        _make_event(datetime(2026, 3, 20, 0, 10, tzinfo=timezone.utc)),
        _make_event(datetime(2026, 3, 20, 0, 30, tzinfo=timezone.utc)),
    ]

    feed_both = read_feed_rows([prev_feed, curr_feed])
    feed_curr = read_feed_rows([curr_feed])
    base = build_events_base_dataset(events, feed_curr)
    ctx = build_events_context_dataset(base, feed_both)

    assert len(ctx) == 2
    for row in ctx:
        assert row.ts.strftime("%Y-%m-%d") == "2026-03-20"


def test_combined_feed_rows_sorted_chronologically(tmp_path):
    """Feed rows from two days are merged in chronological order."""
    prev_feed = tmp_path / "2026-03-19.csv"
    curr_feed = tmp_path / "2026-03-20.csv"

    _write_feed(prev_feed, f"{ENRICHED_HEADER}\n2026-03-19T23:58:00Z,99,102,98,100,50,10,5,2,100,1000,0.0001,1,1,False\n2026-03-19T23:59:00Z,99,102,98,101,50,10,5,2,100,1000,0.0001,1,1,False\n")
    _write_feed(curr_feed, f"{ENRICHED_HEADER}\n2026-03-20T00:00:00Z,99,102,98,102,50,10,5,2,100,1000,0.0001,1,1,False\n2026-03-20T00:01:00Z,99,102,98,103,50,10,5,2,100,1000,0.0001,1,1,False\n")

    rows = read_feed_rows([prev_feed, curr_feed])

    timestamps = [r.ts for r in rows]
    assert timestamps == sorted(timestamps)
    assert len(rows) == 4
    assert rows[0].ts.day == 19
    assert rows[-1].ts.day == 20
