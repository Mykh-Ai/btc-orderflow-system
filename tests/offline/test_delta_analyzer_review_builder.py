from __future__ import annotations

import csv
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_review_tables import (
    build_daily_review_package,
)


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
    "matched_open_interest",
    "matched_funding_rate",
    "matched_liq_buy_qty",
    "matched_liq_sell_qty",
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
    "final_close_ts",
    "final_close_reason",
    "lifecycle_tp1_done",
    "lifecycle_tp2_done",
    "lifecycle_sl_done",
    "lifecycle_trail_active",
    "lifecycle_trail_sl_price",
    "lifecycle_prices_entry",
    "lifecycle_prices_sl",
    "lifecycle_prices_tp1",
    "lifecycle_prices_tp2",
    "trade_lifecycle_state",
]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_parquet(path: Path, rows: list[dict[str, str]]) -> None:
    pd = pytest.importorskip("pandas")
    pyarrow = pytest.importorskip("pyarrow")
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False, engine="pyarrow")


def _make_events_context_row(**overrides: str) -> dict[str, str]:
    row = {field: "" for field in EVENTS_CONTEXT_FIELDS}
    row.update(
        {
            "ts": "2026-01-02T00:00:00Z",
            "day": "2026-01-02",
            "event_type": "CANDIDATE_GATE_REJECT",
            "kind": "long",
            "reject_reason": "direction_mismatch",
        }
    )
    row.update(overrides)
    return row


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


def test_accepted_table_includes_peak_emit_rows_only(
    dataset_root: Path, tmp_path: Path
):
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
    assert {row["event_type"] for row in rows} == {
        "CANDIDATE_GATE_REJECT",
        "CANDIDATE_COMPARISON_REJECT",
    }


def test_reject_table_includes_loss_filter_reject(tmp_path: Path):
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            _make_events_context_row(
                event_type="PEAK_LOSS_FILTER_REJECT",
                reject_reason="loss_avoidance_union",
                delta="12",
                vol="20",
                price="101",
            )
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.reject_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["event_type"] == "PEAK_LOSS_FILTER_REJECT"
    assert rows[0]["reject_reason"] == "loss_avoidance_union"


def test_accepted_table_joins_close_outcomes_on_peak_ts_and_peak_kind(
    dataset_root: Path, tmp_path: Path
):
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

    assert row["join_status"] == "joined"
    assert row["join_confidence"] == "1.0"
    assert row["close_reason"] == "TP1"
    assert row["final_close_reason"] == "TP1"
    assert row["entry"] == "101.25"
    assert row["side"] == "LONG"
    assert result.matched_close_count == 1


def test_accepted_table_joins_close_outcomes_from_parquet_when_csv_absent(
    dataset_root: Path, tmp_path: Path
):
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

    assert row["join_status"] == "joined"
    assert row["close_reason"] == "TP1"
    assert result.matched_close_count == 1


def test_accepted_table_joins_close_outcomes_when_event_ts_is_naive_and_outcome_ts_is_utc_aware(
    dataset_root: Path, tmp_path: Path
):
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

    assert row["join_status"] == "joined"
    assert row["close_ts"] == "2026-01-02T01:00:00Z"
    assert result.matched_close_count == 1


def test_review_outputs_include_matched_enriched_feed_fields(dataset_root: Path, tmp_path: Path):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:10:00Z",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
                "matched_open_interest": "12345",
                "matched_funding_rate": "0.0001",
                "matched_liq_buy_qty": "7",
                "matched_liq_sell_qty": "8",
            },
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:20:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_GATE_REJECT",
                "kind": "short",
                "reject_reason": "weak_delta",
                "matched_open_interest": "54321",
                "matched_funding_rate": "-0.0002",
                "matched_liq_buy_qty": "9",
                "matched_liq_sell_qty": "10",
            },
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)

    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        accepted_row = next(csv.DictReader(handle))
    with result.reject_path.open("r", encoding="utf-8", newline="") as handle:
        reject_row = next(csv.DictReader(handle))

    assert accepted_row["matched_open_interest"] == "12345"
    assert accepted_row["matched_funding_rate"] == "0.0001"
    assert accepted_row["matched_liq_buy_qty"] == "7"
    assert accepted_row["matched_liq_sell_qty"] == "8"
    assert reject_row["matched_open_interest"] == "54321"
    assert reject_row["matched_funding_rate"] == "-0.0002"
    assert reject_row["matched_liq_buy_qty"] == "9"
    assert reject_row["matched_liq_sell_qty"] == "10"


def test_build_succeeds_without_close_outcomes_and_leaves_join_fields_empty(
    dataset_root: Path, tmp_path: Path
):
    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)

    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "missing"
    assert row["close_ts"] == ""
    assert row["close_reason"] == ""
    assert result.matched_close_count == 0


def test_build_fails_clearly_when_events_context_is_missing(tmp_path: Path):
    with pytest.raises(
        RuntimeError,
        match=r"missing events_context input: .+events_context_2026-01-02\.csv",
    ):
        build_daily_review_package("2026-01-02", tmp_path, tmp_path)


def test_markdown_summary_is_created_with_required_counts(
    dataset_root: Path, tmp_path: Path
):
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
    assert (
        "reject_reason_summary_created: reject_reason_summary_2026-01-02.csv" in summary
    )
    assert "reject_reason_summary_group_count: 2" in summary
    assert "comparison_fail: 1" in summary
    assert "weak_delta: 1" in summary
    assert result.accepted_path.name in summary
    assert result.reject_path.name in summary
    assert result.reject_reason_summary_path.name in summary
    assert result.summary_path.name in summary


def test_reject_reason_summary_groups_by_reject_reason_and_kind_with_stats(
    dataset_root: Path, tmp_path: Path
):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:20:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_GATE_REJECT",
                "kind": "short",
                "reject_reason": "vwap_side",
                "cum_delta_180m": "10",
                "cum_delta_60m": "2",
                "ret_15m": "-1",
                "ret_60m": "-2",
                "dist_vwap": "-1",
                "abs_dist_vwap": "1",
                "price_vs_vwap_side": "below",
            },
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:25:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_GATE_REJECT",
                "kind": "short",
                "reject_reason": "vwap_side",
                "cum_delta_180m": "14",
                "cum_delta_60m": "6",
                "ret_15m": "3",
                "ret_60m": "4",
                "dist_vwap": "-3",
                "abs_dist_vwap": "3",
                "price_vs_vwap_side": "below",
            },
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:30:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_COMPARISON_REJECT",
                "kind": "long",
                "reject_reason": "direction_mismatch",
                "cum_delta_180m": "11",
                "cum_delta_60m": "5",
                "ret_15m": "1",
                "ret_60m": "2",
                "dist_vwap": "2",
                "abs_dist_vwap": "2",
                "price_vs_vwap_side": "above",
            },
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.reject_reason_summary_path.open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert [(row["reject_reason"], row["kind"], row["count"]) for row in rows] == [
        ("direction_mismatch", "long", "1"),
        ("vwap_side", "short", "2"),
    ]
    vwap_side_row = rows[1]
    assert vwap_side_row["cum_delta_60m_mean"] == "4"
    assert vwap_side_row["cum_delta_60m_median"] == "4"
    assert vwap_side_row["cum_delta_180m_mean"] == "12"
    assert vwap_side_row["cum_delta_180m_median"] == "12"
    assert vwap_side_row["ret_15m_mean"] == "1"
    assert vwap_side_row["ret_15m_median"] == "1"
    assert vwap_side_row["ret_60m_mean"] == "1"
    assert vwap_side_row["ret_60m_median"] == "1"
    assert vwap_side_row["dist_vwap_mean"] == "-2"
    assert vwap_side_row["dist_vwap_median"] == "-2"
    assert vwap_side_row["abs_dist_vwap_mean"] == "2"
    assert vwap_side_row["abs_dist_vwap_median"] == "2"
    assert vwap_side_row["price_vs_vwap_side_mode"] == "below"
    assert vwap_side_row["price_vs_vwap_side_mode_count"] == "2"


def test_reject_reason_summary_is_empty_with_header_when_no_reject_rows(tmp_path: Path):
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:10:00Z",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.reject_reason_summary_path.open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))

    assert rows == []
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "reject_row_count: 0" in summary
    assert "reject_reason_summary_group_count: 0" in summary
    assert "<none>: 0" in summary


def test_reject_reason_summary_skips_missing_numeric_values_without_crashing(
    dataset_root: Path, tmp_path: Path
):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:20:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_GATE_REJECT",
                "kind": "",
                "reject_reason": "",
                "cum_delta_180m": "",
                "cum_delta_60m": "bad-number",
                "ret_15m": "",
                "ret_60m": "5",
                "dist_vwap": "",
                "abs_dist_vwap": "7",
            },
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T00:30:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_COMPARISON_REJECT",
                "kind": "",
                "reject_reason": "",
                "cum_delta_180m": "",
                "cum_delta_60m": "",
                "ret_15m": "",
                "ret_60m": "",
                "dist_vwap": "",
                "abs_dist_vwap": "",
            },
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.reject_reason_summary_path.open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        row = next(csv.DictReader(handle))

    assert row["reject_reason"] == "UNKNOWN"
    assert row["kind"] == "UNKNOWN"
    assert row["count"] == "2"
    assert row["cum_delta_60m_mean"] == ""
    assert row["cum_delta_60m_median"] == ""
    assert row["cum_delta_180m_mean"] == ""
    assert row["ret_15m_mean"] == ""
    assert row["ret_60m_mean"] == "5"
    assert row["ret_60m_median"] == "5"
    assert row["abs_dist_vwap_mean"] == "7"


def test_interesting_rejects_excludes_filtered_reasons_and_weak_context(tmp_path: Path):
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            _make_events_context_row(ts="2026-01-02T00:01:00Z", reject_reason="no_prev_peak", cum_delta_60m="500", ret_15m="0.003", abs_dist_vwap="200"),
            _make_events_context_row(ts="2026-01-02T00:02:00Z", reject_reason="imb_band", cum_delta_60m="500", ret_15m="0.003", abs_dist_vwap="200"),
            _make_events_context_row(ts="2026-01-02T00:03:00Z", reject_reason="direction_mismatch", cum_delta_60m="149", ret_15m="0.0014", abs_dist_vwap="149"),
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.interesting_rejects_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows == []
    assert result.interesting_reject_count == 0


def test_interesting_rejects_builds_expected_bucket_rows(tmp_path: Path):
    rows = [
        _make_events_context_row(ts="2026-01-02T00:01:00Z", reject_reason="vwap_side", kind="long", cum_delta_60m="300", cum_delta_180m="500", ret_15m="0.003", ret_60m="-0.004", abs_dist_vwap="450"),
        _make_events_context_row(ts="2026-01-02T00:02:00Z", reject_reason="direction_mismatch", kind="long", cum_delta_60m="250", cum_delta_180m="150", ret_15m="-0.0005", abs_dist_vwap="300"),
        _make_events_context_row(ts="2026-01-02T00:03:00Z", reject_reason="direction_mismatch", kind="long", cum_delta_60m="450", cum_delta_180m="-250", ret_15m="-0.004", ret_60m="-0.0005", abs_dist_vwap="220"),
        _make_events_context_row(ts="2026-01-02T00:04:00Z", reject_reason="3of3_fail", kind="long", cum_delta_60m="200", cum_delta_180m="-50", ret_15m="0.003", ret_60m="-0.004", abs_dist_vwap="500"),
        _make_events_context_row(ts="2026-01-02T00:05:00Z", reject_reason="3of3_fail", kind="short", cum_delta_60m="-350", cum_delta_180m="100", ret_15m="0.001", ret_60m="-0.004", abs_dist_vwap="650"),
        _make_events_context_row(ts="2026-01-02T00:06:00Z", reject_reason="vwap_side", kind="long", cum_delta_60m="260", cum_delta_180m="100", ret_15m="0.0025", ret_60m="", abs_dist_vwap="900"),
    ]
    _write_csv(tmp_path / "events_context_2026-01-02.csv", EVENTS_CONTEXT_FIELDS, rows)

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.interesting_rejects_path.open("r", encoding="utf-8", newline="") as handle:
        interesting_rows = list(csv.DictReader(handle))

    assert [(row["interesting_rule_id"], row["interesting_reject_bucket"]) for row in interesting_rows] == [
        ("IR_B1", "possible_reversal_confirmation"),
        ("IR_A1", "possible_reversal_onset"),
        ("IR_D1", "possible_exhaustion_probe"),
        ("IR_E2", "possible_trap_or_false_break"),
        ("IR_C2", "possible_continuation_pressure"),
        ("IR_F1", "unclear_but_constructive"),
    ]
    assert all(row["interesting_reject_flag"] == "1" for row in interesting_rows)


def test_interesting_rejects_uses_first_match_wins_ordering(tmp_path: Path):
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            _make_events_context_row(
                ts="2026-01-02T00:01:00Z",
                reject_reason="vwap_side",
                kind="long",
                cum_delta_60m="500",
                cum_delta_180m="500",
                ret_15m="0.004",
                ret_60m="0.005",
                abs_dist_vwap="300",
            )
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.interesting_rejects_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["interesting_rule_id"] == "IR_B1"
    assert row["interesting_reject_bucket"] == "possible_reversal_confirmation"



def test_interesting_rejects_writes_empty_schema_when_no_rows_match(tmp_path: Path):
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            _make_events_context_row(ts="2026-01-02T00:01:00Z", reject_reason="no_prev_peak", cum_delta_60m="200", ret_15m="0.003", abs_dist_vwap="200")
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)

    with result.interesting_rejects_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows == []
    assert reader.fieldnames == EVENTS_CONTEXT_FIELDS + [
        "interesting_reject_flag",
        "interesting_reject_bucket",
        "interesting_reject_note",
        "interesting_rule_id",
    ]
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "interesting_reject_row_count: 0" in summary
    assert result.interesting_rejects_path.name in summary


def test_accepted_table_joins_close_outcomes_from_next_day_when_peak_closes_after_midnight(
    dataset_root: Path, tmp_path: Path
):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T23:56:00Z",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
                "price": "67451.71266",
            }
        ],
    )
    _write_csv(
        dataset_root / "close_outcomes_2026-01-03.csv",
        CLOSE_OUTCOME_FIELDS,
        [
            {
                "peak_ts": "2026-01-02T23:56:00Z",
                "peak_kind": "long",
                "join_status": "window_match",
                "join_confidence": "0.6",
                "close_ts": "2026-01-03T01:00:00Z",
                "close_reason": "SL",
                "entry": "67451.49",
                "side": "LONG",
                "final_close_ts": "2026-01-03T01:00:00Z",
                "final_close_reason": "SL",
                "trade_lifecycle_state": "plain_sl",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "joined"
    assert row["close_reason"] == "SL"
    assert row["close_ts"] == "2026-01-03T01:00:00Z"
    assert row["trade_lifecycle_state"] == "plain_sl"
    assert result.matched_close_count == 1


def test_accepted_table_keeps_cross_day_case_unresolved_when_multiple_candidates_exist(
    dataset_root: Path, tmp_path: Path
):
    _write_csv(
        dataset_root / "events_context_2026-01-02.csv",
        EVENTS_CONTEXT_FIELDS,
        [
            {
                **{field: "" for field in EVENTS_CONTEXT_FIELDS},
                "ts": "2026-01-02T16:20:00Z",
                "day": "2026-01-02",
                "event_type": "PEAK_EMIT",
                "kind": "long",
            }
        ],
    )
    _write_csv(
        dataset_root / "close_outcomes_2026-01-03.csv",
        CLOSE_OUTCOME_FIELDS + ["lc_opened_at", "lc_side"],
        [
            {
                "peak_ts": "",
                "peak_kind": "",
                "join_status": "missing",
                "join_confidence": "0.0",
                "close_ts": "2026-01-03T20:10:32Z",
                "close_reason": "SL",
                "entry": "66798.52",
                "side": "LONG",
                "lc_opened_at": "2026-01-02T14:20:05+00:00",
                "lc_side": "LONG",
            },
            {
                "peak_ts": "",
                "peak_kind": "",
                "join_status": "missing",
                "join_confidence": "0.0",
                "close_ts": "2026-01-03T21:10:32Z",
                "close_reason": "TP1",
                "entry": "66800.00",
                "side": "LONG",
                "lc_opened_at": "2026-01-02T15:20:05+00:00",
                "lc_side": "LONG",
            },
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "missing"
    assert row["close_reason"] == ""
    assert row["close_ts"] == ""
    assert result.matched_close_count == 0


def test_accepted_table_marks_ambiguous_when_multiple_exact_close_rows_match(
    dataset_root: Path, tmp_path: Path
):
    _write_csv(
        dataset_root / "close_outcomes_2026-01-02.csv",
        CLOSE_OUTCOME_FIELDS,
        [
            {
                "peak_ts": "2026-01-02T00:10:00Z",
                "peak_kind": "long",
                "join_status": "window_match",
                "join_confidence": "0.6",
                "close_ts": "2026-01-02T01:00:00Z",
                "close_reason": "TP1",
                "entry": "101.25",
                "side": "LONG",
            },
            {
                "peak_ts": "2026-01-02T00:10:00Z",
                "peak_kind": "long",
                "join_status": "window_match",
                "join_confidence": "0.6",
                "close_ts": "2026-01-02T01:10:00Z",
                "close_reason": "SL",
                "entry": "100.90",
                "side": "LONG",
            },
        ],
    )

    result = build_daily_review_package("2026-01-02", dataset_root, tmp_path)
    with result.accepted_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["join_status"] == "ambiguous"
    assert row["join_confidence"] == "0.0"
    assert row["close_reason"] == ""
    assert result.matched_close_count == 0


def test_accepted_table_applies_manual_close_override_when_close_outcomes_missing(dataset_root: Path, tmp_path: Path):
    overrides_path = REPO_ROOT / 'deltascout' / 'research_material' / 'manual_close_overrides.jsonl'
    original = overrides_path.read_text(encoding='utf-8') if overrides_path.exists() else None
    overrides_path.parent.mkdir(parents=True, exist_ok=True)
    overrides_path.write_text(
        '{"source_date":"2026-01-02","peak_ts":"2026-01-02T00:10:00Z","peak_kind":"long","close_reason":"SL","side":"LONG","entry":"101.25","join_status":"manual_override","join_confidence":"1.0","source":"manual_user_confirmed"}\n',
        encoding='utf-8',
    )
    try:
        result = build_daily_review_package('2026-01-02', dataset_root, tmp_path)
        with result.accepted_path.open('r', encoding='utf-8', newline='') as handle:
            row = next(csv.DictReader(handle))
        assert row['join_status'] == 'joined'
        assert row['close_reason'] == 'SL'
        assert row['entry'] == '101.25'
        assert row['side'] == 'LONG'
        assert result.matched_close_count == 1
    finally:
        if original is None:
            overrides_path.unlink(missing_ok=True)
        else:
            overrides_path.write_text(original, encoding='utf-8')


def test_reject_table_preserves_3of3_decomposition_fields(tmp_path: Path):
    extended_fields = EVENTS_CONTEXT_FIELDS + [
        "prev_price",
        "prev_vol",
        "prev_vwap",
        "comparison_price_pass",
        "comparison_vol_pass",
        "comparison_vwap_pass",
        "comparison_3of3_pass_count",
        "comparison_3of3_failed_subconditions",
    ]
    _write_csv(
        tmp_path / "events_context_2026-01-02.csv",
        extended_fields,
        [
            {
                **{field: "" for field in extended_fields},
                "ts": "2026-01-02T00:20:00Z",
                "day": "2026-01-02",
                "event_type": "CANDIDATE_COMPARISON_REJECT",
                "kind": "long",
                "reject_reason": "3of3_fail",
                "prev_price": "105",
                "prev_vol": "20",
                "prev_vwap": "99",
                "comparison_price_pass": "False",
                "comparison_vol_pass": "True",
                "comparison_vwap_pass": "False",
                "comparison_3of3_pass_count": "1",
                "comparison_3of3_failed_subconditions": "price|vwap",
            }
        ],
    )

    result = build_daily_review_package("2026-01-02", tmp_path, tmp_path)
    with result.reject_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))

    assert row["comparison_price_pass"] == "False"
    assert row["comparison_vol_pass"] == "True"
    assert row["comparison_vwap_pass"] == "False"
    assert row["comparison_3of3_pass_count"] == "1"
    assert row["comparison_3of3_failed_subconditions"] == "price|vwap"
