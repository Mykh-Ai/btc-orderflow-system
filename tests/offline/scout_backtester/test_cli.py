from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from deltascout.research_bundle.scout_backtester.cli import build_parser, run
from deltascout.research_bundle.scout_backtester.contracts import BacktestContractError


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_cli_materializes_required_artifacts_and_rejects_overwrite(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    raw = tmp_path / "raw_archive"
    feed = tmp_path / "effective_feed"
    state = tmp_path / "server_state"
    outputs = tmp_path / "backtests"
    day = "2026-01-02"
    _write_csv(
        reviews / day / f"events_context_{day}.csv",
        ["ts", "event_type", "kind", "reject_reason", "delta", "vol", "imb", "price", "vwap", "poc"],
        [{"ts": f"{day} 13:00:00", "event_type": "PEAK_EMIT", "kind": "long", "reject_reason": "", "delta": 10, "vol": 20, "imb": 0.5, "price": 100, "vwap": 99, "poc": 98}],
    )
    raw.mkdir()
    (raw / f"{day}.jsonl").write_text(
        json.dumps({"event": "DELTA_MAX", "ts": f"{day} 13:00:00", "kind": "long", "delta": 10, "vol": 20, "imb": 0.5, "price": 100, "vwap": 99, "poc": 98}) + "\n"
        + json.dumps({"event": "PEAK_EMIT", "ts": f"{day} 13:00:00", "kind": "long", "delta": 10, "vol": 20, "imb": 0.5, "price": 100, "vwap": 99, "poc": 98}) + "\n",
        encoding="utf-8",
    )
    feed_fields = ["Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty", "IsSynthetic"]
    _write_csv(
        feed / f"{day}.csv",
        feed_fields,
        [
            {"Timestamp": f"{day} 11:59:00", "Open": 100.4, "High": 100.4, "Low": 100.4, "Close": 100.4, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
            {"Timestamp": f"{day} 12:01:00", "Open": 100.5, "High": 100.6, "Low": 100.4, "Close": 100.5, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
            {"Timestamp": f"{day} 12:02:00", "Open": 100.5, "High": 100.6, "Low": 100.2, "Close": 100.3, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
        ],
    )
    state.mkdir()
    args = build_parser().parse_args(
        [
            "--candidate-root", str(reviews),
            "--raw-archive-root", str(raw),
            "--feed-root", str(feed),
            "--server-state-root", str(state),
            "--output-root", str(outputs),
            "--date-from", day,
            "--date-to", day,
            "--candidate-groups", "PEAK_EMIT_BASELINE",
            "--experiment-id", "e2e",
        ]
    )
    manifest = run(args)
    assert manifest.exists()
    required = {
        "run_manifest.json", "normalized_candidates.csv", "candidate_quality.csv",
        "replay_events.jsonl", "independent_trades.csv", "portfolio_trades.csv",
        "position_lock_opportunity_cost.csv", "candidate_group_metrics.csv",
        "portfolio_metrics.csv",
        "equity_curve.csv", "drawdown.csv", "parity_report.csv", "summary.md",
        "trade_legs.csv", "same_bar_sensitivity.csv", "cost_sensitivity.csv",
    }
    assert required.issubset({path.name for path in manifest.parent.iterdir()})
    with pytest.raises(BacktestContractError, match="non-empty"):
        run(args)
