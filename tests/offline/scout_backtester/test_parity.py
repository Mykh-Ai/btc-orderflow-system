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
