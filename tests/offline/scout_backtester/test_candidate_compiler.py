from __future__ import annotations

import csv
import json
from datetime import timezone
from pathlib import Path

import pytest

from deltascout.research_bundle.scout_backtester.candidate_compiler import (
    compile_candidates,
    local_event_to_utc,
)
from deltascout.research_bundle.scout_backtester.contracts import BacktestContractError


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_compiler_uses_raw_archive_for_3of3_and_deduplicates(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    raw = tmp_path / "raw_archive"
    day = "2026-03-20"
    row = {
        "ts": "2026-03-20 01:36:00",
        "event_type": "CANDIDATE_COMPARISON_REJECT",
        "kind": "long",
        "reject_reason": "3of3_fail",
        "delta": "189.62",
        "vol": "191.03",
        "imb": "0.993",
        "price": "70126.443466",
        "vwap": "70060",
        "poc": "",
    }
    _write_csv(reviews / day / f"events_context_{day}.csv", [row, row])
    raw.mkdir()
    events = [
        {"event": "DELTA_MAX", "ts": row["ts"], "kind": "long", "delta": 189.62, "vol": 191.03, "price": 70126.443466, "vwap": 70060, "poc": 69270},
        {"event": "CANDIDATE_COMPARISON_REJECT", "ts": row["ts"], "kind": "long", "reject_reason": "3of3_fail", "delta": 189.62, "vol": 191.03, "price": 70126.443466, "vwap": 70060, "prev_price": 70059.74, "prev_vol": 200.0, "prev_vwap": 70073},
    ]
    (raw / f"{day}.jsonl").write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")

    candidates, quality = compile_candidates(
        reviews,
        date_from=day,
        date_to=day,
        raw_archive_root=raw,
        candidate_groups=["ALMOST_PEAK_1_OF_3"],
    )

    assert len(candidates) == 1
    assert candidates[0].comparison_3of3_pass_count == 1
    assert candidates[0].comparison_3of3_failed_subconditions == "vol|vwap"
    assert candidates[0].poc == 69270
    assert quality[0].reason == "DUPLICATE_CANDIDATE"


def test_local_timestamp_conversion_and_ambiguous_time_failure() -> None:
    converted = local_event_to_utc("2026-03-20 01:36:00")
    assert converted.tzinfo == timezone.utc
    assert converted.isoformat() == "2026-03-20T00:36:00+00:00"
    with pytest.raises(BacktestContractError, match="ambiguous"):
        local_event_to_utc("2026-10-25 02:30:00")


def test_filter_reject_is_compiled_directly_from_raw_archive_as_peak_counterfactual(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    raw = tmp_path / "raw_archive"
    reviews.mkdir()
    raw.mkdir()
    day = "2026-08-20"
    would_be_peak = {
        "ts": "2026-08-20 16:30:00",
        "source": "DeltaScout",
        "action": "PEAK",
        "kind": "long",
        "delta": 125.0,
        "vol": 200.0,
        "imb": 0.625,
        "price": 65000.5,
        "vwap": 64950,
        "poc": 64900,
    }
    row = {
        "schema": 1,
        "event": "PEAK_LOSS_FILTER_REJECT",
        "ts": would_be_peak["ts"],
        "kind": "long",
        "rule_id": "DS_PEAK_LOSS_AVOIDANCE_UNION_V1",
        "decision": "BLOCK",
        "component_a": False,
        "component_b": True,
        "union": True,
        "same_side_peak_count_24h": 12,
        "same_side_peak_percentile_24h": 75.0,
        "oi_change_60m": -100.0,
        "oi_trusted_60m": True,
        "directional_delta_pct_240m": 0.02,
        "would_be_peak": would_be_peak,
    }
    (raw / f"{day}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    candidates, quality = compile_candidates(
        reviews,
        date_from=day,
        date_to=day,
        raw_archive_root=raw,
        candidate_groups=["PEAK_EMIT_BASELINE"],
    )

    assert quality == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.event_type == "PEAK_LOSS_FILTER_REJECT"
    assert candidate.candidate_group == "PEAK_EMIT_BASELINE"
    assert candidate.admission_status == "FILTER_REJECTED"
    assert candidate.filter_decision == "BLOCK"
    assert candidate.filter_rule_id == "DS_PEAK_LOSS_AVOIDANCE_UNION_V1"
    assert candidate.signal_price == 65000.5
    assert candidate.signal_ts_utc.isoformat() == "2026-08-20T14:30:00+00:00"
    assert candidate.shadow_flags["loss_avoidance_conservative_union"] is True
    assert candidate.shadow_flags["oi_change_60m"] == -100.0
