"""Tests for Phase 1 research archive instrumentation.

Verifies:
- research archive is separate from live deltascout.log
- archive is append-only JSONL with schema/event/seq fields
- DELTA_MAX / DELTA_MIN events emitted for window owners
- CANDIDATE_COMPARISON_REJECT emitted on comparison failure
- CANDIDATE_GATE_REJECT emitted on gate failure
- PEAK emission path unchanged
- archive write failure soft-fails without crashing handle_row
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest


def _find_repo_root(start: Path) -> Path:
    p = start.resolve()
    for _ in range(30):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path.cwd().resolve()


def _load_delta_scout_module():
    here = Path(__file__).resolve()
    repo = _find_repo_root(here)
    candidates = [repo / "deltascout" / "delta_scout.py", repo / "delta_scout.py"]
    target = next((c for c in candidates if c.exists()), None)
    if not target:
        raise FileNotFoundError(f"delta_scout.py not found in {candidates}")
    spec = importlib.util.spec_from_file_location("delta_scout_mod", str(target))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ds():
    return _load_delta_scout_module()


@pytest.fixture()
def tmp_dirs(tmp_path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    live_log = tmp_path / "deltascout.log"
    live_log.touch()
    return {"archive": str(archive_dir), "live_log": str(live_log)}


def _wire(monkeypatch, ds, tmp_dirs, *, vwap_by_ts=None):
    """Deterministic test wiring — relaxes gates, stubs market context."""
    monkeypatch.setattr(ds, "RESEARCH_ARCHIVE_DIR", tmp_dirs["archive"])
    monkeypatch.setattr(ds, "ENABLE_RESEARCH_LOG", True)
    monkeypatch.setattr(ds, "LOG_PATH", tmp_dirs["live_log"])

    monkeypatch.setattr(ds, "IMB_MIN", 0.0)
    monkeypatch.setattr(ds, "IMB_MAX", 1.0)
    monkeypatch.setattr(ds, "CHOP30_MAX", 9999.0)
    monkeypatch.setattr(ds, "COH10_MIN", 0.0)
    monkeypatch.setattr(ds, "AVG9_MAX", 9999.0)
    monkeypatch.setattr(ds, "ZERO_QTY_TH", 0.0)
    monkeypatch.setattr(ds, "VWAP_MAX_DIST_USD", 50000.0)

    state = {"ts": "1970-01-01 00:00:00", "price": 0.0, "ema50": 0.0}
    vwap_map = vwap_by_ts or {}

    def load_df_sorted():
        return pd.DataFrame([{
            "Timestamp": pd.to_datetime(state["ts"]).floor("min"),
            "price": float(state["price"]),
            "ema50": float(state["ema50"]),
        }])

    monkeypatch.setattr(ds, "load_df_sorted", load_df_sorted)
    monkeypatch.setattr(ds, "locate_index_by_ts", lambda _df, _ts: 0)
    monkeypatch.setattr(ds, "chop30_idx", lambda _df, _i: 1.0)
    monkeypatch.setattr(ds, "coh10_idx", lambda _df, _i: 0.5)
    monkeypatch.setattr(ds.Scout, "_ingest_buyer_events", lambda self: None)
    monkeypatch.setattr(ds.Scout, "_emit", lambda self, *a, **k: None)

    def _context(self):
        ts = getattr(self, "_test_ts", None)
        v = vwap_map.get(ts)
        if v is None:
            return None, None
        return float(v), 0

    monkeypatch.setattr(ds.Scout, "_context", _context)

    peak_emitted = []
    orig_emit_json = ds.Scout._emit_json

    def _emit_json(self_scout, payload):
        peak_emitted.append(payload)

    monkeypatch.setattr(ds.Scout, "_emit_json", _emit_json)

    return state, peak_emitted


def _run(ds, state, scout, rows):
    for r in rows:
        ts = str(r["Timestamp"])
        price = float(r["AvgPrice"])
        delta = float(r["BuyQty"]) - float(r["SellQty"])
        scout._test_ts = ts
        state["ts"] = ts
        state["price"] = price
        state["ema50"] = (price - 10000.0) if delta >= 0 else (price + 10000.0)
        scout.handle_row(r)


def _read_archive(archive_dir: str) -> list[dict]:
    events = []
    for fn in sorted(Path(archive_dir).glob("*.jsonl")):
        for line in fn.read_text(encoding="utf-8").strip().splitlines():
            events.append(json.loads(line))
    return events


# ── Test: research archive is separate from live bus ──

def test_archive_separate_from_live_bus(monkeypatch, ds, tmp_dirs):
    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
    }
    state, peaks = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run(ds, state, s, [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
    ])

    archive_events = _read_archive(tmp_dirs["archive"])
    live_log_content = Path(tmp_dirs["live_log"]).read_text()

    assert len(archive_events) > 0, "research archive should have events"
    assert live_log_content == "", "live bus must remain untouched by research events"


# ── Test: schema/event/seq fields present ──

def test_archive_record_format(monkeypatch, ds, tmp_dirs):
    vwap_by_ts = {"2026-01-01 00:00:00": 9900, "2026-01-01 00:01:00": 9500}
    state, _ = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run(ds, state, s, [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
    ])

    for evt in _read_archive(tmp_dirs["archive"]):
        assert "schema" in evt and evt["schema"] == 1
        assert "event" in evt
        assert "seq" in evt and isinstance(evt["seq"], int)

    seqs = [e["seq"] for e in _read_archive(tmp_dirs["archive"])]
    assert seqs == sorted(seqs), "seq must be monotonically increasing"
    assert len(seqs) == len(set(seqs)), "seq must be unique"


# ── Test: DELTA_MAX and DELTA_MIN emitted ──

def test_delta_max_min_emitted(monkeypatch, ds, tmp_dirs):
    vwap_by_ts = {
        "2026-01-01 00:00:00": 10100,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 10100,
        "2026-01-01 00:03:00": 10200,
    }
    state, _ = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run(ds, state, s, [
        # row 0: balanced (near-zero delta, sets initial window)
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 5, "SellQty": 5, "AvgPrice": 10000},
        # row 1: strong short (min owner, delta = -8)
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 9, "AvgPrice": 9800},
        # row 2: strong long (max owner, delta = +15)
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10500},
        # row 3: even stronger long (new max owner, delta = +18)
        {"Timestamp": "2026-01-01 00:03:00", "Trades": 1, "TotalQty": 25,
         "BuyQty": 20, "SellQty": 2, "AvgPrice": 10600},
    ])

    events = _read_archive(tmp_dirs["archive"])
    event_types = [e["event"] for e in events]
    assert "DELTA_MAX" in event_types
    assert "DELTA_MIN" in event_types

    dm = [e for e in events if e["event"] == "DELTA_MAX"]
    assert all("delta" in e and "price" in e and "kind" in e for e in dm)


# ── Test: CANDIDATE_COMPARISON_REJECT on 3/3 failure ──

def test_comparison_reject_3of3(monkeypatch, ds, tmp_dirs):
    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 9600,  # vwap improved
    }
    state, peaks = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run(ds, state, s, [
        # short dummy
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        # long baseline (max owner, sets prev_peak)
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        # new max owner, but LOWER volume → 3/3 fails on vol
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 15,
         "BuyQty": 12, "SellQty": 3, "AvgPrice": 10500},
    ])

    events = _read_archive(tmp_dirs["archive"])
    rejects = [e for e in events if e["event"] == "CANDIDATE_COMPARISON_REJECT"]
    # row 1 sets prev_peak (no_prev_peak). row 2 is a new max owner with
    # higher price and vwap but LOWER vol (20 vs 20) → 3of3 fails on vol.
    # Filter to only the reject from the third row (the actual 3of3 path).
    rejects_3of3 = [r for r in rejects if r["reject_reason"] == "3of3_fail"]
    assert len(rejects_3of3) == 1, f"expected exactly one 3of3_fail, got {[r['reject_reason'] for r in rejects]}"
    assert rejects_3of3[0]["kind"] == "long"


# ── Test: CANDIDATE_GATE_REJECT on IMB gate ──

def test_gate_reject_imb(monkeypatch, ds, tmp_dirs):
    # Set tight IMB band so gate rejects
    monkeypatch.setattr(ds, "IMB_MIN", 0.90)
    monkeypatch.setattr(ds, "IMB_MAX", 0.95)

    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 10000,
    }
    state, peaks = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    # Re-apply tight IMB after _wire relaxed it
    monkeypatch.setattr(ds, "IMB_MIN", 0.90)
    monkeypatch.setattr(ds, "IMB_MAX", 0.95)

    s = ds.Scout()
    _run(ds, state, s, [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 30,
         "BuyQty": 18, "SellQty": 6, "AvgPrice": 10500},
    ])

    events = _read_archive(tmp_dirs["archive"])
    gate_rejects = [e for e in events if e["event"] == "CANDIDATE_GATE_REJECT"]
    assert len(gate_rejects) > 0
    assert any(r["reject_reason"] == "imb_band" for r in gate_rejects)


# ── Test: PEAK emission unchanged ──

def test_peak_still_emitted(monkeypatch, ds, tmp_dirs):
    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 10000,
    }
    state, peaks = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()
    _run(ds, state, s, [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 30,
         "BuyQty": 18, "SellQty": 6, "AvgPrice": 10500},
    ])

    peak_events = [p for p in peaks if p.get("action") == "PEAK"]
    assert len(peak_events) == 1
    pk = peak_events[0]

    # PEAK must go through _emit_json (live bus), not research archive
    assert pk["source"] == "DeltaScout"
    assert pk["action"] == "PEAK"
    assert pk["kind"] == "long"

    # Contract fields that existed before Patch 1 — must still be present
    for field in ("ts", "source", "action", "kind", "delta", "vol", "imb", "price", "vwap", "poc"):
        assert field in pk, f"PEAK missing contract field: {field}"


# ── Test: archive write failure soft-fails ──

def test_archive_write_failure_softfails(monkeypatch, ds, tmp_dirs):
    from unittest.mock import patch as mock_patch

    vwap_by_ts = {
        "2026-01-01 00:00:00": 9900,
        "2026-01-01 00:01:00": 9500,
        "2026-01-01 00:02:00": 10000,
    }
    state, peaks = _wire(monkeypatch, ds, tmp_dirs, vwap_by_ts=vwap_by_ts)
    s = ds.Scout()

    # Force deterministic write failure via monkeypatch on builtins.open
    original_open = open

    def _failing_open(path, *args, **kwargs):
        if "archive" in str(path):
            raise OSError("injected archive write failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _failing_open)

    # Must not raise despite archive write failure
    _run(ds, state, s, [
        {"Timestamp": "2026-01-01 00:00:00", "Trades": 1, "TotalQty": 10,
         "BuyQty": 1, "SellQty": 3, "AvgPrice": 9800},
        {"Timestamp": "2026-01-01 00:01:00", "Trades": 1, "TotalQty": 20,
         "BuyQty": 15, "SellQty": 5, "AvgPrice": 10000},
        {"Timestamp": "2026-01-01 00:02:00", "Trades": 1, "TotalQty": 30,
         "BuyQty": 18, "SellQty": 6, "AvgPrice": 10500},
    ])

    # Live PEAK still emitted despite archive failure
    peak_events = [p for p in peaks if p.get("action") == "PEAK"]
    assert len(peak_events) == 1, "PEAK must still emit when archive write fails"
