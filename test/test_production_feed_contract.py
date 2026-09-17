"""Raw production ten-column feed -> V8 structural initial-stop contract.

The differential oracle is the captured running loader, not a pre-normalized DF.
See docs/executor-runtime-parity-evidence.json for capture provenance/SHA256.
"""
import csv
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd
import pytest

from executor_mod import entry_math, market_data


HEADER = ["Timestamp", "Trades", "TotalQty", "AvgSize", "BuyQty", "SellQty",
          "AvgPrice", "ClosePrice", "HiPrice", "LowPrice"]
INTERNAL = {"low_usdt", "high_usdt", "volume_1m", "swing_row_real"}
ORACLE_SHA256 = "ee0297be087714648cd68be16a9a1f62b44bc282b371cca57d5e4e8a41fa8dbc"


@pytest.fixture
def raw_feed(tmp_path, monkeypatch):
    path = tmp_path / "aggregated.csv"
    env = {
        "AGG_CSV": str(path), "INITIAL_STOP_POLICY": "VOLUME_SWING_24H_LR25",
        "INITIAL_SWING_LOOKBACK": 1440, "INITIAL_SWING_LR": 25,
        "INITIAL_SWING_BUFFER_USD": 50., "INITIAL_SWING_MAX_DISTANCE_USD": 1200.,
        "INITIAL_SWING_REQUIRE_FULL_WINDOW": True, "SL_PCT": .002, "TICK_SIZE": Decimal("0.01"),
    }
    monkeypatch.setattr(market_data, "ENV", env)
    monkeypatch.setattr(entry_math, "ENV", env)
    def write(rows):
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER)
            writer.writeheader()
            writer.writerows(rows)
        with path.open(newline="") as f:
            header = next(csv.reader(f))
        assert header == HEADER and not INTERNAL.intersection(header)
        return path
    return write


def rows(count=1440):
    start = pd.Timestamp("2026-09-16T00:00:00Z")
    result = []
    for i in range(count):
        result.append(dict(zip(HEADER, [str(start + pd.Timedelta(minutes=i)),
            10, 1., .1, .5, .5, 60000., 60000., 60100., 59900.])))
    for index, low, high, volume in [(700, 59000., 61000., 999.), (1000, 59100., 60900., 100.)]:
        if index < count:
            result[index].update(LowPrice=low, HiPrice=high, TotalQty=volume)
    return result


def assert_matches_production(path, actual):
    fixture = Path(__file__).parent / "fixtures" / "production_market_data_loader.py.txt"
    source = fixture.read_text(encoding="utf-8").encode("utf-8")
    assert hashlib.sha256(source).hexdigest() == ORACLE_SHA256
    namespace = {"pd": pd, "os": os, "ENV": {"AGG_CSV": str(path)}}
    exec(compile(source, str(fixture), "exec"), namespace)
    expected = namespace["load_df_sorted"]()
    pd.testing.assert_frame_equal(actual, expected)


def select(df, side, timestamp=None):
    timestamp = timestamp if timestamp is not None else "2026-09-16T23:59:00Z"
    index = market_data.locate_index_by_ts(df, pd.Timestamp(timestamp).to_pydatetime())
    return entry_math.select_volume_confirmed_initial_stop(df, index, side, 60000.)


@pytest.mark.parametrize("side,expected", [("BUY", 58950.), ("SELL", 61050.)], ids=["LONG", "SHORT"])
def test_raw_production_feed_selects_valid_structural_stop(raw_feed, side, expected):
    # Descending raw CSV order exercises the real loader timestamp/sort path.
    path = raw_feed(list(reversed(rows())))
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert INTERNAL.issubset(df.columns)
    assert len(df) == 1440 and df["swing_row_real"].all()
    assert df["Timestamp"].dt.tz is None
    assert df["Timestamp"].diff().dropna().dt.total_seconds().eq(60).all()
    assert market_data.locate_index_by_ts(df, pd.Timestamp("2026-09-16T23:59:37Z")) == 1439
    assert df.iloc[700]["low_usdt"] == df.iloc[700]["LowPrice"] == 59000.
    assert df.iloc[700]["high_usdt"] == df.iloc[700]["HiPrice"] == 61000.
    assert df.iloc[700]["volume_1m"] == df.iloc[700]["TotalQty"] == 999.
    selected = select(df, side)
    assert selected.stop_usdt == expected
    assert selected.swing_ts == pd.Timestamp("2026-09-16T11:40:00Z").to_pydatetime()
    assert selected.swing_volume == 999. and selected.window_gap_count == 0
    assert selected.confirmed_count == 2 and selected.eligible_count == 2


@pytest.mark.parametrize("field,value", [
    ("ClosePrice", "bad"), ("HiPrice", "bad"), ("LowPrice", "bad"),
    ("TotalQty", "bad"), ("Trades", "bad"), ("Trades", 0),
    ("TotalQty", 0), ("ClosePrice", 0), ("HiPrice", 0), ("LowPrice", 0),
    ("Trades", -1), ("TotalQty", -1), ("HiPrice", 58000.),
])
@pytest.mark.parametrize("side,expected", [("BUY", 59050.), ("SELL", 60950.)])
def test_invalid_source_neighbor_cannot_confirm_primary_swing(raw_feed, field, value, side, expected):
    source = rows()
    source[701][field] = value  # Within the primary 25/25 confirmation neighborhood.
    path = raw_feed(source)
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert len(df) == 1440
    assert not bool(df.iloc[701]["swing_row_real"])
    if field == "ClosePrice" and value == "bad":
        assert pd.isna(df.iloc[701]["close_usdt"])
        assert df.iloc[701]["price"] == 60000.  # Forward-fill legacy price only.
    if field in ("HiPrice", "LowPrice") and value == "bad":
        normalized = "high_usdt" if field == "HiPrice" else "low_usdt"
        assert pd.isna(df.iloc[701][normalized])
        assert df.iloc[701][field] == 60000.  # Fallback does not validate raw input.
    selected = select(df, side)
    assert selected.stop_usdt == expected and selected.swing_volume == 100.


@pytest.mark.parametrize("field,value,expected", [
    ("Trades", .5, True), ("HiPrice", "inf", True),
    ("TotalQty", "inf", True), ("Trades", "inf", True),
    ("ClosePrice", "inf", True), ("LowPrice", "nan", False),
    ("HiPrice", "nan", False), ("TotalQty", "nan", False),
    ("Trades", "nan", False), ("ClosePrice", "nan", False),
    ("ClosePrice", 62000., True),  # Production does not require close inside high/low.
    ("HiPrice", 59900., True),  # Equality high == low is allowed.
])
def test_exact_production_validity_semantics(raw_feed, field, value, expected):
    source = rows()
    source[100][field] = value
    path = raw_feed(source)
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert bool(df.iloc[100]["swing_row_real"]) is expected


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("minute", ["2026-09-15T23:59:00Z", "2026-09-17T00:00:00Z"])
def test_exact_minute_miss_has_no_latest_row_lookahead(raw_feed, side, minute):
    path = raw_feed(rows())
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert market_data.locate_index_by_ts(df, pd.Timestamp(minute)) == -1
    with pytest.raises(entry_math.InitialStopSelectionError) as error:
        select(df, side, minute)
    assert error.value.reason == "MISSING_EXACT_SIGNAL_MINUTE"


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_missing_interior_signal_minute_remains_fail_closed(raw_feed, side):
    source = rows()
    del source[800]
    raw_feed(source)
    df = market_data.load_df_sorted()
    assert market_data.locate_index_by_ts(df, pd.Timestamp("2026-09-16T13:20:00Z")) == -1
    with pytest.raises(entry_math.InitialStopSelectionError) as error:
        select(df, side, "2026-09-16T13:20:00Z")
    assert error.value.reason == "MISSING_EXACT_SIGNAL_MINUTE"


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("count,minute", [(1439, "2026-09-16T23:58:00Z"), (1440, "2026-09-16T23:58:00Z")])
def test_full_1440_bars_required_before_exact_signal_not_latest(raw_feed, side, count, minute):
    path = raw_feed(rows(count))
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    with pytest.raises(entry_math.InitialStopSelectionError) as error:
        select(df, side, minute)
    assert error.value.reason == "NO_FULL_INITIAL_SWING_WINDOW"


def test_leading_invalid_close_dropped_but_interior_invalid_close_preserved(raw_feed):
    source = rows()
    source[0]["ClosePrice"] = "bad"
    source[100]["ClosePrice"] = "bad"
    path = raw_feed(source)
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert len(df) == 1439 and df.iloc[0]["Timestamp"] == pd.Timestamp("2026-09-16T00:01:00")
    interior = df.loc[df["Timestamp"] == pd.Timestamp("2026-09-16T01:40:00")].iloc[0]
    assert interior["price"] == 60000. and pd.isna(interior["close_usdt"])
    assert not bool(interior["swing_row_real"])


def test_malformed_timestamp_returns_empty_like_production(raw_feed):
    source = rows()
    source[100]["Timestamp"] = "not-a-timestamp"
    path = raw_feed(source)
    df = market_data.load_df_sorted()
    assert_matches_production(path, df)
    assert df.empty


def test_matches_values_captured_in_actual_production_pandas(raw_feed):
    fixture = Path(__file__).parent / "fixtures" / "production_market_data_normalization_reference.json"
    reference = json.loads(fixture.read_text(encoding="utf-8"))
    source = list(csv.DictReader(reference["raw_csv"].splitlines()))
    raw_feed(source)
    df = market_data.load_df_sorted()
    actual = []
    for row in df[reference["columns"]].to_dict("records"):
        normalized = {}
        for key, value in row.items():
            if key == "Timestamp":
                normalized[key] = value.isoformat()
            elif pd.isna(value):
                normalized[key] = None
            elif key == "swing_row_real":
                normalized[key] = bool(value)
            else:
                number = float(value)
                normalized[key] = number if math.isfinite(number) else ("Infinity" if number > 0 else "-Infinity")
        actual.append(normalized)
    assert actual == reference["normalized_rows"]
