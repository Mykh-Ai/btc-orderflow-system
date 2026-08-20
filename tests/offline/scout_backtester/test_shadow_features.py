from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from deltascout.research_bundle.scout_backtester.shadow_features import enrich_shadow_flags

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
