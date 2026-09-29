from __future__ import annotations

import importlib
import sys
from collections import deque
from types import SimpleNamespace

import pandas as pd
import pytest


def _module(monkeypatch, tmp_path, *, long_min: str | None, short_min: str | None):
    monkeypatch.setenv("DELTASCOUT_LOG", str(tmp_path / "deltascout.log"))
    monkeypatch.setenv("RESEARCH_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("IMB_MIN", "0.54")
    monkeypatch.setenv("IMB_MAX", "0.69")
    for name, value in (("IMB_MIN_LONG", long_min), ("IMB_MIN_SHORT", short_min)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    sys.modules.pop("deltascout.delta_scout", None)
    return importlib.import_module("deltascout.delta_scout")


def _run_candidate(monkeypatch, module, *, side: str, imbalance: float):
    long = side == "long"
    price = 101.0 if long else 99.0
    vwap = 100.0
    frame = pd.DataFrame([{"price": price, "ema50": 90.0 if long else 110.0}])
    monkeypatch.setattr(module, "load_df_sorted", lambda: frame)
    monkeypatch.setattr(module, "locate_index_by_ts", lambda _df, _ts: 0)
    monkeypatch.setattr(module, "chop30_idx", lambda _df, _i: 1.0)
    monkeypatch.setattr(module, "coh10_idx", lambda _df, _i: 0.5)

    scout = module.Scout.__new__(module.Scout)
    scout.win = deque([(1.0 if long else -1.0, 0.1, 10.0, 100.0, 1, "2026-01-01 00:00:00")])
    scout.vbuf = deque()
    scout.last_owner = {"max": None, "min": None}
    scout.prev_peak = {
        "kind": side,
        "price": 100.0,
        "vol": 50.0,
        "vwap": 99.0 if long else 101.0,
    }
    scout.loss_filter = SimpleNamespace(mode="off", config=None)
    scout._ingest_buyer_events = lambda: None
    scout._record_loss_filter_peak = lambda **_kwargs: None
    scout._emit = lambda *_args, **_kwargs: None
    scout._context = lambda: (vwap, 100.0)
    events: list[tuple[str, dict]] = []
    bus: list[dict] = []
    scout._emit_research = lambda event, fields: events.append((event, dict(fields))) or True
    scout._emit_json = lambda payload: bus.append(dict(payload))

    volume = 100.0
    delta = imbalance * volume * (1 if long else -1)
    scout.handle_row({
        "Timestamp": "2026-01-01 00:01:00",
        "Trades": 1,
        "TotalQty": 100,
        "BuyQty": (volume + delta) / 2,
        "SellQty": (volume - delta) / 2,
        "AvgPrice": price,
    })
    return events, bus


@pytest.mark.parametrize(
    ("side", "imbalance", "admitted", "effective_min"),
    [
        ("long", 0.499, False, 0.50),
        ("long", 0.500, True, 0.50),
        ("long", 0.539, True, 0.50),
        ("short", 0.500, False, 0.54),
        ("short", 0.539, False, 0.54),
        ("short", 0.540, True, 0.54),
        ("long", 0.690, True, 0.50),
        ("short", 0.690, True, 0.54),
        ("long", 0.691, False, 0.50),
        ("short", 0.691, False, 0.54),
    ],
)
def test_side_specific_gate_and_research_payload(
    monkeypatch, tmp_path, side, imbalance, admitted, effective_min
):
    module = _module(monkeypatch, tmp_path, long_min="0.50", short_min="0.54")
    events, bus = _run_candidate(monkeypatch, module, side=side, imbalance=imbalance)

    assert bool(bus) is admitted
    if admitted:
        assert bus[0]["action"] == "PEAK"
        assert bus[0]["kind"] == side
        event, fields = next((event, fields) for event, fields in events if event == "PEAK_EMIT")
    else:
        event, fields = next(
            (event, fields) for event, fields in events
            if event == "CANDIDATE_GATE_REJECT" and fields.get("reject_reason") == "imb_band"
        )
    assert fields["kind"] == side
    assert fields["imb_min"] == effective_min
    assert fields["imb_max"] == 0.69


@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize(("imbalance", "admitted"), [(0.539, False), (0.540, True)])
def test_legacy_minimum_applies_to_both_sides(monkeypatch, tmp_path, side, imbalance, admitted):
    module = _module(monkeypatch, tmp_path, long_min=None, short_min=None)
    events, bus = _run_candidate(monkeypatch, module, side=side, imbalance=imbalance)

    assert bool(bus) is admitted
    event, fields = next(
        (event, fields) for event, fields in events
        if event in {"CANDIDATE_GATE_REJECT", "PEAK_EMIT"}
    )
    assert fields["imb_min"] == 0.54
    assert fields["imb_max"] == 0.69


def test_missing_short_override_uses_legacy_minimum(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, long_min="0.50", short_min=None)

    assert module.ENV["IMB_MIN_LONG"] == 0.50
    assert module.ENV["IMB_MIN_SHORT"] == 0.54
    events, bus = _run_candidate(monkeypatch, module, side="short", imbalance=0.539)
    assert bus == []
    reject = next(fields for event, fields in events if event == "CANDIDATE_GATE_REJECT")
    assert reject["reject_reason"] == "imb_band"
    assert reject["imb_min"] == 0.54
