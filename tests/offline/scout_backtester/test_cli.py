from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from deltascout.research_bundle.scout_backtester.cli import (
    _apply_candidate_loss_filter,
    build_parser,
    run,
)
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
            {"Timestamp": f"{day} 12:00:00", "Open": 100.4, "High": 100.5, "Low": 100.3, "Close": 100.4, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
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
            "--execution-feed-root", str(feed),
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
        "loss_avoidance_counterfactual.csv", "loss_avoidance_metrics.csv",
        "loss_avoidance_coverage.csv", "loss_avoidance_summary.md",
        "comparison_variant_metrics.csv", "comparison_variant_trades.csv",
        "comparison_variant_monthly.csv", "comparison_variant_loss_filter.csv",
        "other_candidate_groups_inventory.csv", "candidate_loss_filter_exclusions.csv",
    }
    assert required.issubset({path.name for path in manifest.parent.iterdir()})
    with pytest.raises(BacktestContractError, match="non-empty"):
        run(args)


def test_cli_usdt_signal_contour_reuses_quality_checked_signal_bars(tmp_path: Path) -> None:
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
        json.dumps({"event": "PEAK_EMIT", "ts": f"{day} 13:00:00", "kind": "long", "delta": 10, "vol": 20, "imb": 0.5, "price": 100, "vwap": 99, "poc": 98}) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        feed / f"{day}.csv",
        ["Timestamp", "Open", "High", "Low", "Close", "Volume", "BuyQty", "SellQty", "IsSynthetic"],
        [
            {"Timestamp": f"{day} 12:00:00", "Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
            {"Timestamp": f"{day} 12:01:00", "Open": 100.5, "High": 101, "Low": 100.4, "Close": 100.8, "Volume": 1, "BuyQty": 0.5, "SellQty": 0.5, "IsSynthetic": 0},
        ],
    )
    state.mkdir()
    args = build_parser().parse_args(
        [
            "--candidate-root", str(reviews),
            "--raw-archive-root", str(raw),
            "--feed-root", str(feed),
            "--execution-feed-root", str(tmp_path / "deliberately_unused"),
            "--price-contour", "btcusdt_signal",
            "--server-state-root", str(state),
            "--output-root", str(outputs),
            "--date-from", day,
            "--date-to", day,
            "--candidate-groups", "PEAK_EMIT_BASELINE",
            "--experiment-id", "usdt-contour",
        ]
    )
    manifest = run(args)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["resolved_config"]["price_contour"] == "btcusdt_signal"
    assert payload["resolved_config"]["conversion_model_id"] == "IDENTITY_BTCUSDT_SIGNAL_CONTOUR_V0_1"
    assert payload["resolved_config"]["replay_feed_symbol"] == "BTCUSDT_USDM_FUTURES_ENRICHED"
    assert payload["execution_feed_quality_counts"] == payload["signal_feed_quality_counts"]
    with (manifest.parent / "independent_trades.csv").open("r", encoding="utf-8", newline="") as handle:
        trade = next(csv.DictReader(handle))
    assert float(trade["conversion_ratio"]) == 1.0


def test_cli_rejects_unknown_comparison_setup_variant(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--candidate-root", str(tmp_path / "reviews"),
            "--feed-root", str(tmp_path / "feed"),
            "--execution-feed-root", str(tmp_path / "execution"),
            "--date-from", "2026-01-01",
            "--date-to", "2026-01-01",
            "--candidate-groups", "ALMOST_PEAK_2_OF_3",
            "--comparison-setup-variants", "NOT_A_VARIANT",
            "--experiment-id", "invalid-variant",
        ]
    )

    with pytest.raises(BacktestContractError, match="unsupported comparison setup variants"):
        run(args)


def test_candidate_loss_filter_union_blocks_true_and_keeps_unknown() -> None:
    def item(candidate_id: str, *, component_a: bool | None, component_b: bool | None):
        union = True if component_a is True or component_b is True else (
            None if component_a is None or component_b is None else False
        )
        return SimpleNamespace(
            candidate_id=candidate_id,
            signal_ts_utc=datetime.fromisoformat("2026-01-02T12:00:00+00:00"),
            side="LONG",
            candidate_group="ALMOST_PEAK_2_OF_3",
            comparison_setup_variant="ALMOST_2OF3_PRICE_FAIL",
            shadow_flags={
                "weak_peak_le_50": component_a,
                "oi_down_60_and_directional_delta_pct_240_lt_0_06": component_b,
                "loss_avoidance_conservative_union": union,
            },
        )

    candidates = [
        item("A", component_a=True, component_b=False),
        item("B", component_a=False, component_b=True),
        item("KEEP", component_a=False, component_b=False),
        item("UNKNOWN", component_a=False, component_b=None),
    ]

    kept, exclusions, stats = _apply_candidate_loss_filter(candidates, "UNION_A_OR_B")

    assert [candidate.candidate_id for candidate in kept] == ["KEEP", "UNKNOWN"]
    assert [row["candidate_id"] for row in exclusions] == ["A", "B"]
    assert stats == {
        "policy": "UNION_A_OR_B",
        "input_candidate_count": 4,
        "blocked_candidate_count": 2,
        "kept_candidate_count": 2,
        "unknown_kept_count": 1,
        "unknown_policy": "KEEP_FAIL_OPEN",
    }
