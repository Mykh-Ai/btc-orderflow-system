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
