from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_review_tables import build_daily_review_package


EVENTS_CONTEXT_FIELDS = [
    "ts",
    "day",
    "event_type",
    "kind",
    "reject_reason",
    "delta",
    "vol",
    "imb",
    "price",
    "vwap",
    "poc",
    "matched_feed_ts",
    "source_file",
    "terminal_decision_present",
    "cum_delta_24h",
    "cum_delta_180m",
    "cum_delta_60m",
    "ret_15m",
    "ret_60m",
    "dist_vwap",
    "abs_dist_vwap",
    "price_vs_vwap_side",
]


CLOSE_OUTCOME_FIELDS = [
    "peak_ts",
    "peak_kind",
    "join_status",
    "join_confidence",
    "close_ts",
    "close_reason",
    "entry",
    "side",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_parquet(path: Path, rows: list[dict[str, str]]) -> None:
    pd = pytest.importorskip("pandas")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)

@pytest.fixture
def dataset_root(tmp_path: Path) -> Path:
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                "ts": "2026-01-02T00:10:00Z",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
                "reject_reason": "",
                "delta": "10",
                "vol": "2",
                "imb": "0.8",
                "price": "101",
                "vwap": "100",
                "poc": "99",
                "matched_feed_ts": "2026-01-02T00:10:00Z",
                "source_file": "archive.jsonl",
                "terminal_decision_present": "True",
                "cum_delta_24h": "50",
                "cum_delta_180m": "12",
                "cum_delta_60m": "4",
                "ret_15m": "2",
                "ret_60m": "3",
                "dist_vwap": "1",
                "abs_dist_vwap": "1",
                "price_vs_vwap_side": "above",
            },
            {
                "ts": "2026-01-02T00:20:00+00:00",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_GATE_REJECT",
                "kind": "short",
                "reject_reason": "weak_delta",
                "delta": "-5",
                "vol": "1",
                "imb": "-0.4",
                "price": "99",
                "vwap": "100",
                "poc": "98",
                "matched_feed_ts": "2026-01-02T00:20:00Z",
                "source_file": "archive.jsonl",
                "terminal_decision_present": "True",
                "cum_delta_24h": "40",
                "cum_delta_180m": "10",
                "cum_delta_60m": "2",
                "ret_15m": "-1",
                "ret_60m": "-2",
                "dist_vwap": "-1",
                "abs_dist_vwap": "1",
                "price_vs_vwap_side": "below",
            },
            {
                "ts": "2026-01-02T00:30:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_COMPARISON_REJECT",
                "kind": "long",
                "reject_reason": "comparison_fail",
                "delta": "7",
                "vol": "3",
                "imb": "0.6",
                "price": "102",
                "vwap": "101",
                "poc": "100",
                "matched_feed_ts": "2026-01-02T00:30:00Z",
                "source_file": "archive.jsonl",
                "terminal_decision_present": "True",
                "cum_delta_24h": "45",
                "cum_delta_180m": "11",
                "cum_delta_60m": "3",
                "ret_15m": "1",
                "ret_60m": "2",
                "dist_vwap": "1",
                "abs_dist_vwap": "1",
                "price_vs_vwap_side": "above",
            },
            {
                "ts": "2026-01-02T00:40:00Z",
                "day": "2026-01-02",
                "event_type": "DELTA_MAX",
                "kind": "long",
                "reject_reason": "",
                "delta": "8",
                "vol": "4",
                "imb": "0.7",
                "price": "103",
                "vwap": "102",
                "poc": "101",
                "matched_feed_ts": "2026-01-02T00:40:00Z",
                "source_file": "archive.jsonl",
                "terminal_decision_present": "False",
                "cum_delta_24h": "46",
                "cum_delta_180m": "13",
                "cum_delta_60m": "5",
                "ret_15m": "2",
                "ret_60m": "4",
                "dist_vwap": "1",
                "abs_dist_vwap": "1",
                "price_vs_vwap_side": "above",
            },
        ],
    )
    return tmp_path


def test_accepted_table_includes_peak_emit_rows_only(dataset_root: Path, tmp_path: Path):
    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)

    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    assert {row["event_type"] for row in rows} == {"PEAK_EMIT"}



def test_reject_table_includes_only_reject_rows(dataset_root: Path, tmp_path: Path):
    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)

    with result.reject_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 2
    assert {row["event_type"] for row in rows} == {"CANDIDATE_GATE_REJECT", "CANDIDATE_COMPARISON_REJECT"}



def test_accepted_table_joins_close_outcomes_on_peak_ts_and_peak_kind(dataset_root: Path, tmp_path: Path):
    _write_csv(
        dataset_root / "close_outcomes_2026-01-02.csv",
        CLOSE_OUTCOME_FIELDS,
        [
            {
                "peak_ts": "2026-01-02 00:10:00+00:00",
                "peak_kind": "LONG",
                "join_status": "exact",
                "join_confidence": "1.0",
                "close_ts": "2026-01-02T01:00:00Z",
                "close_reason": "TP1",
                "entry": "101.25",
                "side": "LONG",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "exact"
    assert row["join_confidence"] == "1.0"
    assert row["close_reason"] == "TP1"
    assert row["entry"] == "101.25"
    assert row["side"] == "LONG"
    assert result.matched_close_count == 1




def test_accepted_table_joins_close_outcomes_from_parquet_when_csv_absent(dataset_root: Path, tmp_path: Path):
    _write_parquet(
        dataset_root / "close_outcomes_2026-01-02.parquet",
        [
            {
                "peak_ts": "2026-01-02T00:10:00Z",
                "peak_kind": "long",
                "join_status": "exact",
                "join_confidence": "1.0",
                "close_ts": "2026-01-02T01:00:00Z",
                "close_reason": "TP1",
                "entry": "101.25",
                "side": "LONG",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "exact"
    assert row["close_reason"] == "TP1"
    assert result.matched_close_count == 1


def test_accepted_table_joins_close_outcomes_when_event_ts_is_naive_and_outcome_ts_is_utc_aware(dataset_root: Path, tmp_path: Path):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:10:00",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
            }
        ],
    )
    _write_csv(
        dataset_root / "close_outcomes_2026-01-02.csv",
        CLOSE_OUTCOME_FIELDS,
        [
            {
                "peak_ts": "2026-01-02T00:10:00+00:00",
                "peak_kind": "long",
                "join_status": "exact",
                "join_confidence": "1.0",
                "close_ts": "2026-01-02T01:00:00Z",
                "close_reason": "TP1",
                "entry": "101.25",
                "side": "LONG",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "exact"
    assert row["close_ts"] == "2026-01-02T01:00:00Z"
    assert result.matched_close_count == 1


def test_build_succeeds_without_close_outcomes_and_leaves_join_fields_empty(dataset_root: Path, tmp_path: Path):
    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)

    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == ""
    assert row["close_ts"] == ""
    assert row["close_reason"] == ""
    assert result.matched_close_count == 0



def test_build_fails_clearly_when_events_context_is_missing(tmp_path: Path):
    with pytest.raises(RuntimeError, match=r"missing events_context input: .+events_context_2026-01-02\.csv"):
        build_daily_review_package("2026-01-02", tmp_path, tmp_path)



def test_markdown_summary_is_created_with_required_counts(dataset_root: Path, tmp_path: Path):
    _write_csv(
        dataset_root / "close_outcomes_2026-01-02.csv",
        CLOSE_OUTCOME_FIELDS,
        [
            {
                "peak_ts": "2026-01-02T00:10:00Z",
                "peak_kind": "long",
                "join_status": "exact",
                "join_confidence": "1.0",
                "close_ts": "2026-01-02T01:00:00Z",
                "close_reason": "TP1",
                "entry": "101.25",
                "side": "LONG",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    summary = result.summary_path.read_text(encoding="utf-8")

    assert "processed_date: 2026-01-02" in summary
    assert "accepted_row_count: 1" in summary
    assert "reject_row_count: 2" in summary
    assert "accepted_with_close_outcomes: 1" in summary
    assert "comparison_fail: 1" in summary
    assert "weak_delta: 1" in summary
    assert result.accepted_path.name in summary
    assert result.reject_path.name in summary
    assert result.summary_path.name in summary
