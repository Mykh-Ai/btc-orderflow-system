from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path

from deltascout.research_bundle.scout_backtester.parity import build_parity_report
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate

from .conftest import bar, candidate


def test_parity_separates_planning_and_lifecycle(tmp_path: Path, replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.6, low=100.2, close=100.3),
    ]
    result, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    state = tmp_path / "state"
    state.mkdir()
    snapshot = {
        "trade_key": "LIVE1",
        "excluded_from_scoring": False,
        "lifecycle_class": "plain_sl",
        "local_last_closed": {
            "trade_key": "LIVE1",
            "side": "LONG",
            "opened_at": result.entry_fill_ts.isoformat(),
            "entry": result.planned_entry_price,
            "qty": result.qty_total,
            "prices": {"entry": result.planned_entry_price, "sl": result.initial_stop_price, "tp1": result.tp1_price, "tp2": result.tp2_price},
        },
    }
    (state / "trade_execution_snapshots.jsonl").write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
    with (state / "trade_pnl_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["trade_key", "gross_pnl_usdc", "net_pnl_usdc"])
        writer.writeheader()
        writer.writerow({"trade_key": "LIVE1", "gross_pnl_usdc": result.gross_pnl_usdc, "net_pnl_usdc": result.net_pnl_usdc})
    rows = build_parity_report([result], server_state_root=state, tick_size=replay_config.tick_size)
    assert rows[0]["candidate_join_status"] == "MATCHED"
    assert rows[0]["entry_plan_match"] is True
    assert rows[0]["lifecycle_match"] is True


def test_parity_merges_outcomes_missing_from_snapshot_coverage(tmp_path: Path, replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=100.5, high=100.6, low=100.4, close=100.5),
        bar(2, open_=100.5, high=100.6, low=100.2, close=100.3),
    ]
    result, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    result.lifecycle_class = "TP1_TP2_TRAILING_STOP"
    state = tmp_path / "state"
    state.mkdir()
    snapshot = {
        "trade_key": "NEWER_SNAPSHOT",
        "ts": (result.entry_fill_ts + timedelta(days=1)).isoformat(),
        "excluded_from_scoring": False,
        "lifecycle_class": "plain_sl",
        "local_last_closed": {
            "trade_key": "NEWER_SNAPSHOT",
            "side": "SHORT",
            "opened_at": (result.entry_fill_ts + timedelta(days=1)).isoformat(),
            "prices": {"entry": 200.0},
        },
    }
    outcome = {
        "schema": "trade_outcome_v1",
        "ts": (result.entry_fill_ts + timedelta(minutes=5)).isoformat(),
        "last_closed": {
            "trade_key": "OLDER_OUTCOME",
            "side": "LONG",
            "opened_at": result.entry_fill_ts.isoformat(),
            "entry": result.planned_entry_price,
            "entry_actual": result.planned_entry_price + 0.1,
            "sl_done": True,
            "tp1_done": False,
            "tp2_done": False,
            "trail_active": False,
            "prices": {
                "entry": result.planned_entry_price,
                "sl": result.initial_stop_price,
                "tp1": result.tp1_price,
                "tp2": result.tp2_price,
            },
        },
    }
    (state / "trade_execution_snapshots.jsonl").write_text(json.dumps(snapshot) + "\n", encoding="utf-8")
    (state / "trade_outcomes.jsonl").write_text(json.dumps(outcome) + "\n", encoding="utf-8")

    rows = build_parity_report([result], server_state_root=state, tick_size=replay_config.tick_size)
    older = next(row for row in rows if row["trade_key"] == "OLDER_OUTCOME")
    assert older["operational_record_source"] == "trade_outcome_fallback"
    assert older["candidate_join_status"] == "MATCHED"
    assert older["operational_lifecycle"] == "PLAIN_SL"
    assert older["replay_lifecycle"] == "TP1_TP2_TRAILING_STOP"
    assert older["lifecycle_match"] is False
    assert "lifecycle_difference_reference_feed_or_execution_symbol_path" in older["mismatch_reason"]


def test_parity_matches_candidate_even_when_replay_entry_did_not_fill(
    tmp_path: Path, replay_config
) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=101.0, high=101.2, low=100.9, close=101.1),
        bar(2, open_=101.1, high=101.3, low=101.0, close=101.2),
    ]
    result, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    assert result.entry_status == "NO_FILL"

    state = tmp_path / "state"
    state.mkdir()
    snapshot = {
        "trade_key": "LIVE_NO_FILL",
        "excluded_from_scoring": False,
        "lifecycle_class": "plain_sl",
        "local_last_closed": {
            "trade_key": "LIVE_NO_FILL",
            "side": "LONG",
            "opened_at": (result.signal_ts_utc + timedelta(seconds=30)).isoformat(),
            "entry": result.planned_entry_price,
            "qty": result.qty_total,
            "prices": {
                "entry": result.planned_entry_price,
                "sl": result.initial_stop_price,
                "tp1": result.tp1_price,
                "tp2": result.tp2_price,
            },
        },
    }
    (state / "trade_execution_snapshots.jsonl").write_text(
        json.dumps(snapshot) + "\n", encoding="utf-8"
    )

    rows = build_parity_report([result], server_state_root=state, tick_size=replay_config.tick_size)
    assert rows[0]["candidate_join_status"] == "MATCHED"
    assert rows[0]["replay_entry_status"] == "NO_FILL"
    assert rows[0]["lifecycle_match"] is False
    assert "entry_not_filled_in_replay" in rows[0]["mismatch_reason"]


def test_parity_infers_side_and_matches_canceled_entry(tmp_path: Path, replay_config) -> None:
    bars = [
        bar(0, open_=100.4, high=100.4, low=100.4, close=100.4),
        bar(1, open_=101.0, high=101.2, low=100.9, close=101.1),
        bar(2, open_=101.1, high=101.3, low=101.0, close=101.2),
    ]
    result, _ = replay_candidate(candidate("LONG"), bars, replay_config)
    assert result.entry_status == "NO_FILL"
    state = tmp_path / "state"
    state.mkdir()
    snapshot = {
        "trade_key": "LIVE_ABORT",
        "excluded_from_scoring": True,
        "scoring_exclusion_reason": "entry_canceled_no_fill",
        "local_last_closed": {
            "trade_key": "LIVE_ABORT",
            "opened_at": (result.signal_ts_utc + timedelta(seconds=30)).isoformat(),
            "reason": "ENTRY_TIMEOUT_ABORT",
            "entry_actual": None,
            "prices": {
                "entry": result.planned_entry_price,
                "sl": result.initial_stop_price,
                "tp1": result.tp1_price,
                "tp2": result.tp2_price,
            },
        },
    }
    (state / "trade_execution_snapshots.jsonl").write_text(
        json.dumps(snapshot) + "\n", encoding="utf-8"
    )

    rows = build_parity_report([result], server_state_root=state, tick_size=replay_config.tick_size)

    assert rows[0]["candidate_join_status"] == "MATCHED"
    assert rows[0]["operational_entry_status"] == "ABORTED"
    assert rows[0]["entry_execution_match"] is True
    assert "entry_execution_difference" not in rows[0]["mismatch_reason"]
