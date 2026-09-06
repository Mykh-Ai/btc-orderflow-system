from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from deltascout.research_bundle.scout_backtester.shadow_features import (
    conservative_filter_flags,
    enrich_shadow_flags,
)

from .conftest import bar, candidate


def test_shadow_flags_are_cutoff_safe_and_feed_quality_aware(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    events = [
        {"event": "DELTA_MAX", "ts": "2026-01-02 12:00:00", "kind": "long", "delta": 20},
        {"event": "DELTA_MAX", "ts": "2026-01-02 13:00:00", "kind": "long", "delta": 10},
    ]
    (raw / "2026-01-02.jsonl").write_text("\n".join(json.dumps(row) for row in events) + "\n", encoding="utf-8")
    bars = [
        replace(bar(-1, open_=100, high=100, low=100, close=100), buy_qty=0.525, sell_qty=0.475, optional={"OpenInterest": 100.0}),
        replace(bar(0, open_=100, high=100, low=100, close=100), buy_qty=0.525, sell_qty=0.475, optional={"OpenInterest": 90.0}),
    ]
    result = enrich_shadow_flags([candidate("LONG")], bars, raw_archive_root=raw, date_from="2026-01-02", date_to="2026-01-02")[0]
    assert result.shadow_flags["weak_peak_le_50"] is True
    assert result.shadow_flags["oi_down_60_and_directional_delta_pct_240_lt_0_06"] is True
    assert result.shadow_flags["loss_avoidance_conservative_union"] is True


def test_peak_percentile_includes_cutoff_event_but_not_future_events(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    events = [
        {"event": "DELTA_MAX", "ts": "2026-01-02 12:00:00", "kind": "long", "delta": 20},
        {"event": "DELTA_MAX", "ts": "2026-01-02 13:00:00", "kind": "long", "delta": 10},
        {"event": "DELTA_MAX", "ts": "2026-01-02 13:01:00", "kind": "long", "delta": 5},
    ]
    (raw / "2026-01-02.jsonl").write_text("\n".join(json.dumps(row) for row in events) + "\n", encoding="utf-8")

    result = enrich_shadow_flags(
        [candidate("LONG")],
        [],
        raw_archive_root=raw,
        date_from="2026-01-02",
        date_to="2026-01-02",
    )[0]

    assert result.shadow_flags["same_side_peak_count_24h"] == 2
    assert result.shadow_flags["same_side_peak_percentile_24h"] == 50.0
    assert result.shadow_flags["weak_peak_le_50"] is True


def test_conservative_filter_boundaries_and_unknowns_do_not_auto_block() -> None:
    at_boundaries = conservative_filter_flags(
        same_side_peak_percentile_24h=50.0,
        oi_change_60m=-1.0,
        oi_trusted_60m=True,
        directional_delta_pct_240m=0.06,
    )
    assert at_boundaries["weak_peak_le_50"] is True
    assert at_boundaries["oi_down_60_and_directional_delta_pct_240_lt_0_06"] is False
    assert at_boundaries["loss_avoidance_conservative_union"] is True

    untrusted = conservative_filter_flags(
        same_side_peak_percentile_24h=75.0,
        oi_change_60m=-5.0,
        oi_trusted_60m=False,
        directional_delta_pct_240m=0.01,
    )
    assert untrusted["oi_down_60_and_directional_delta_pct_240_lt_0_06"] is None
    assert untrusted["loss_avoidance_conservative_union"] is None

    unknown_oi = conservative_filter_flags(
        same_side_peak_percentile_24h=75.0,
        oi_change_60m=None,
        oi_trusted_60m=True,
        directional_delta_pct_240m=0.01,
    )
    assert unknown_oi["loss_avoidance_conservative_union"] is None

    below_six_percent = conservative_filter_flags(
        same_side_peak_percentile_24h=75.0,
        oi_change_60m=-1.0,
        oi_trusted_60m=True,
        directional_delta_pct_240m=0.059999,
    )
    assert below_six_percent["oi_down_60_and_directional_delta_pct_240_lt_0_06"] is True
    assert below_six_percent["loss_avoidance_conservative_union"] is True
