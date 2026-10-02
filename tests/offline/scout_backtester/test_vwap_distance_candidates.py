from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from deltascout.research_bundle.scout_backtester.candidate_compiler import compile_candidates
from deltascout.research_bundle.scout_backtester.cli import build_parser, run
from deltascout.research_bundle.scout_backtester.contracts import BacktestContractError
from deltascout.research_bundle.scout_backtester.shadow_features import enrich_shadow_flags


DAY = "2026-09-18"
GROUP = "VWAP_DISTANCE_REJECT"


def archive(tmp_path: Path, *, distance: float = 1300, side: str = "long"):
    raw = tmp_path / "raw"
    raw.mkdir()
    ts = f"{DAY} 15:41:00"
    row = {"event": "CANDIDATE_COMPARISON_REJECT", "ts": ts, "kind": side,
           "reject_reason": "vwap_distance", "price": 77000 + (distance if side == "long" else -distance),
           "vwap": 77000, "delta": 100 if side == "long" else -100, "vol": 200}
    rows = [{**row, "event": "DELTA_MAX" if side == "long" else "DELTA_MIN"}, row, row,
            {**row, "ts": f"{DAY} 15:42:00", "reject_reason": "vwap_side"}]
    (raw / f"{DAY}.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    return raw, row


def compile_day(tmp_path, raw, **kwargs):
    return compile_candidates(tmp_path / "reviews", date_from=DAY, date_to=DAY,
                              raw_archive_root=raw, candidate_groups=[GROUP], **kwargs)


@pytest.mark.parametrize("side", ["long", "short"])
def test_raw_distance_reject_direction_identity_and_metadata(tmp_path, side):
    raw, row = archive(tmp_path, side=side)
    candidates, quality = compile_day(tmp_path, raw)
    assert quality == []
    assert len(candidates) == 1  # no DELTA/reject double count, no other reject
    c = candidates[0]
    assert c.side == side.upper()
    assert c.signal_ts_utc.isoformat() == "2026-09-18T13:41:00+00:00"
    assert c.signal_price == row["price"]
    assert c.candidate_group == GROUP
    assert c.admission_status == "PRE_ADMISSION_REJECT"
    assert c.filter_decision is None  # not an AB decision or an admitted PEAK
    assert c.shadow_flags["vwap_distance_usd"] == 1300
    assert c.shadow_flags["downstream_admission_status"] == "NOT_EVALUATED"
    enriched = enrich_shadow_flags(candidates, [], raw_archive_root=raw, date_from=DAY, date_to=DAY)
    assert enriched[0].shadow_flags["vwap_distance_usd"] == 1300
    assert enriched[0].shadow_flags["downstream_admission_status"] == "NOT_EVALUATED"


@pytest.mark.parametrize("distance,expected", [(1200, 0), (1200.01, 1), (1100, 0)])
def test_distance_selector_is_strictly_greater(tmp_path, distance, expected):
    raw, _ = archive(tmp_path, distance=distance)
    candidates, quality = compile_day(tmp_path, raw, vwap_distance_min_usd=1200)
    assert len(candidates) == expected
    assert quality == []


@pytest.mark.parametrize("minimum", [-1, float("nan"), float("inf")])
def test_invalid_minimum_rejected(tmp_path, minimum):
    raw, _ = archive(tmp_path)
    with pytest.raises(BacktestContractError, match="finite and nonnegative"):
        compile_day(tmp_path, raw, vwap_distance_min_usd=minimum)


def test_minimum_cannot_silently_filter_other_groups(tmp_path):
    raw, _ = archive(tmp_path)
    with pytest.raises(BacktestContractError, match="requires only"):
        compile_candidates(tmp_path / "reviews", date_from=DAY, date_to=DAY,
                           raw_archive_root=raw, candidate_groups=["PEAK_EMIT_BASELINE"],
                           vwap_distance_min_usd=1200)


def test_csv_plus_raw_dedup_and_legacy_other_cohort(tmp_path):
    raw, row = archive(tmp_path)
    reviews = tmp_path / "reviews" / DAY
    reviews.mkdir(parents=True)
    csv_row = {**row, "event_type": row["event"]}
    with (reviews / f"events_context_{DAY}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_row))
        writer.writeheader()
        writer.writerow(csv_row)
    new, quality = compile_day(tmp_path, raw)
    assert len(new) == 1
    assert quality == []
    old, _ = compile_candidates(reviews.parent, date_from=DAY, date_to=DAY,
                                raw_archive_root=raw, candidate_groups=["OTHER_COMPARISON_REJECT"])
    assert len(old) == 1
    assert old[0].candidate_group == "OTHER_COMPARISON_REJECT"
    assert old[0].candidate_id == new[0].candidate_id


def test_malformed_vwap_is_quality_error(tmp_path):
    raw, row = archive(tmp_path)
    row["vwap"] = "bad"
    (raw / f"{DAY}.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    candidates, quality = compile_day(tmp_path, raw)
    assert not candidates
    assert quality[0].reason == "INVALID_CANDIDATE"
    assert "positive price and vwap" in quality[0].detail


def test_cli_materializes_raw_cohort_and_manifest(tmp_path):
    raw, _ = archive(tmp_path)
    feed = tmp_path / "feed"
    feed.mkdir()
    fields = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty", "IsSynthetic"]
    with (feed / f"{DAY}.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for minute in range(39, 45):
            writer.writerow(dict(zip(fields, [f"{DAY} 13:{minute}:00", 78300, 78350, 78250, 78300, 2, 1, 1, 0])))
    args = build_parser().parse_args([
        "--candidate-root", str(tmp_path / "reviews"), "--raw-archive-root", str(raw),
        "--feed-root", str(feed), "--execution-feed-root", str(feed),
        "--server-state-root", str(tmp_path / "state"), "--output-root", str(tmp_path / "output"),
        "--date-from", DAY, "--date-to", DAY, "--candidate-groups", GROUP,
        "--vwap-distance-min-usd", "1200", "--initial-stop-policy", "window_extreme",
        "--initial-swing-price-source", "close", "--swing-lookback-minutes", "10",
        "--experiment-id", "distance-e2e",
    ])
    manifest = run(args)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert payload["candidate_groups"] == [GROUP]
    assert payload["candidate_selection"]["vwap_distance_min_usd"] == 1200
    with (manifest.parent / "normalized_candidates.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert json.loads(rows[0]["shadow_flags"])["vwap_distance_usd"] == 1300
    with (manifest.parent / "independent_trades.csv").open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 1
