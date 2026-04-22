"""Tests for feed archive in binance_run_aggregator.

Verifies:
- daily archive file created with correct header
- rows appended with correct 10-column schema
- duplicate timestamps are not written (dedup on restart)
- new day creates a new file
- write errors soft-fail without raising
"""
import os
import tempfile
import time
import importlib.util
from pathlib import Path

import pytest


def _load_aggregator(feed_dir, logs_dir, archive_dir):
    """Import aggregator module with patched dirs."""
    src = Path(__file__).resolve().parent / "binance_run_aggregator.py"
    spec = importlib.util.spec_from_file_location("aggregator", src)
    mod = importlib.util.module_from_spec(spec)
    # patch dirs before exec
    mod.os = os
    mod.time = time
    mod.__name__ = "aggregator"
    # We need to patch the module-level constants before exec.
    # Inject via env vars and re-exec.
    os.environ["FEED_ARCHIVE_DIR"] = archive_dir
    # Override feed_dir/logs_dir in source by monkey-patching after load
    spec.loader.exec_module(mod)
    mod.feed_dir = feed_dir
    mod.logs_dir = logs_dir
    mod.aggregated_file_path = os.path.join(feed_dir, "aggregated.csv")
    mod.log_file_path = os.path.join(logs_dir, "trades_log.txt")
    mod.lock_file_path = os.path.join(logs_dir, "analyzer.lock")
    mod.FEED_ARCHIVE_DIR = archive_dir
    return mod


@pytest.fixture
def env(tmp_path):
    feed_dir = str(tmp_path / "feed")
    logs_dir = str(tmp_path / "logs")
    archive_dir = str(tmp_path / "archive" / "feed")
    os.makedirs(feed_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)
    mod = _load_aggregator(feed_dir, logs_dir, archive_dir)
    return mod, feed_dir, logs_dir, archive_dir


HEADER = "Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice,HiPrice,LowPrice\n"


class TestArchiveFeedRow:
    def test_creates_new_daily_file_with_header(self, env):
        mod, _, _, archive_dir = env
        row_ts = "2026-03-16 12:00:00"
        row_line = f"{row_ts},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        mod._archive_feed_row(row_ts, row_line)

        archive_path = os.path.join(archive_dir, "2026-03-16.csv")
        assert os.path.exists(archive_path)
        with open(archive_path) as f:
            lines = f.readlines()
        assert lines[0] == HEADER
        assert lines[1] == row_line
        assert len(lines) == 2

    def test_appends_to_existing_file(self, env):
        mod, _, _, archive_dir = env
        ts1 = "2026-03-16 12:00:00"
        ts2 = "2026-03-16 12:01:00"
        row1 = f"{ts1},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        row2 = f"{ts2},120,1.200000,0.010000,0.700000,0.500000,74010.000000,74010,74060,73960\n"
        mod._archive_feed_row(ts1, row1)
        mod._archive_feed_row(ts2, row2)

        archive_path = os.path.join(archive_dir, "2026-03-16.csv")
        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 3  # header + 2 rows
        assert lines[1] == row1
        assert lines[2] == row2

    def test_dedup_same_timestamp(self, env):
        mod, _, _, archive_dir = env
        row_ts = "2026-03-16 12:00:00"
        row_line = f"{row_ts},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"

        mod._archive_feed_row(row_ts, row_line)
        mod._archive_feed_row(row_ts, row_line)  # duplicate
        mod._archive_feed_row(row_ts, row_line)  # duplicate again

        archive_path = os.path.join(archive_dir, "2026-03-16.csv")
        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 2  # header + 1 row only

    def test_dedup_after_restart_simulation(self, env):
        """Simulate: write rows, then 'restart' and re-write last timestamp."""
        mod, _, _, archive_dir = env
        ts1 = "2026-03-16 12:00:00"
        ts2 = "2026-03-16 12:01:00"
        row1 = f"{ts1},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        row2 = f"{ts2},120,1.200000,0.010000,0.700000,0.500000,74010.000000,74010,74060,73960\n"

        mod._archive_feed_row(ts1, row1)
        mod._archive_feed_row(ts2, row2)
        # "restart" — try to write ts2 again
        mod._archive_feed_row(ts2, row2)

        archive_path = os.path.join(archive_dir, "2026-03-16.csv")
        with open(archive_path) as f:
            lines = f.readlines()
        assert len(lines) == 3  # header + 2 rows, no duplicate

    def test_new_day_creates_new_file(self, env):
        mod, _, _, archive_dir = env
        row1 = "2026-03-16 23:59:00,100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        row2 = "2026-03-17 00:00:00,110,1.100000,0.010000,0.650000,0.450000,74005.000000,74005,74055,73955\n"

        mod._archive_feed_row("2026-03-16 23:59:00", row1)
        mod._archive_feed_row("2026-03-17 00:00:00", row2)

        assert os.path.exists(os.path.join(archive_dir, "2026-03-16.csv"))
        assert os.path.exists(os.path.join(archive_dir, "2026-03-17.csv"))

        with open(os.path.join(archive_dir, "2026-03-16.csv")) as f:
            assert len(f.readlines()) == 2
        with open(os.path.join(archive_dir, "2026-03-17.csv")) as f:
            assert len(f.readlines()) == 2

    def test_write_error_soft_fails(self, env, tmp_path):
        mod, _, _, _ = env
        # point to a non-writable path
        mod.FEED_ARCHIVE_DIR = "/nonexistent/path/archive"
        row_ts = "2026-03-16 12:00:00"
        row_line = f"{row_ts},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        # should not raise
        mod._archive_feed_row(row_ts, row_line)

    def test_10_column_schema_preserved(self, env):
        mod, _, _, archive_dir = env
        row_ts = "2026-03-16 12:00:00"
        row_line = f"{row_ts},100,1.000000,0.010000,0.600000,0.400000,74000.000000,74000,74050,73950\n"
        mod._archive_feed_row(row_ts, row_line)

        archive_path = os.path.join(archive_dir, "2026-03-16.csv")
        with open(archive_path) as f:
            lines = f.readlines()
        header_cols = lines[0].strip().split(",")
        data_cols = lines[1].strip().split(",")
        assert len(header_cols) == 10
        assert len(data_cols) == 10
        assert header_cols[0] == "Timestamp"
