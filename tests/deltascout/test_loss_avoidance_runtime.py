from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deltascout.loss_avoidance_policy import RULE_ID
from deltascout.loss_avoidance_runtime import (
    STATE_SCHEMA,
    LossAvoidanceRuntimeConfig,
    LossAvoidanceRuntimeEvaluator,
    parse_runtime_timestamp,
)


FIELDS = [
    "Timestamp",
    "BuyQty",
    "SellQty",
    "OpenInterest",
    "IsSynthetic",
]


def _write_state(path: Path, *, cutoff: datetime, peaks: list[tuple[datetime, str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": STATE_SCHEMA,
        "rule_id": RULE_ID,
        "tracking_started_at_utc": (cutoff - timedelta(hours=25)).isoformat(),
        "updated_at_utc": cutoff.isoformat(),
        "peaks": [
            {"event_ts_utc": ts.isoformat(), "side": side, "abs_delta": delta}
            for ts, side, delta in peaks
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_feed(
    root: Path,
    *,
    cutoff: datetime,
    omit_cutoff: bool = False,
    synthetic_at: datetime | None = None,
) -> None:
    rows_by_day: dict[str, list[dict[str, str]]] = {}
    start = cutoff - timedelta(minutes=239)
    for index in range(240):
        ts = start + timedelta(minutes=index)
        if omit_cutoff and ts == cutoff:
            continue
        rows_by_day.setdefault(ts.date().isoformat(), []).append(
            {
                "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "BuyQty": "51",
                "SellQty": "49",
                "OpenInterest": str(1000.0 - index),
                "IsSynthetic": "1" if ts == synthetic_at else "0",
            }
        )
    root.mkdir(parents=True, exist_ok=True)
    for day, rows in rows_by_day.items():
        with (root / f"{day}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)


def _write_archive(
    root: Path,
    *,
    cutoff: datetime,
    peaks: list[tuple[datetime, str, float]],
) -> None:
    zone = ZoneInfo("Europe/Bratislava")
    first_day = (cutoff - timedelta(hours=24)).astimezone(zone).date()
    last_day = cutoff.astimezone(zone).date()
    day = first_day
    paths: dict[str, Path] = {}
    while day <= last_day:
        path = root / f"{day.isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        paths[day.isoformat()] = path
        day += timedelta(days=1)
    for event_ts, side, delta in peaks:
        local_ts = event_ts.astimezone(zone)
        event = "DELTA_MAX" if side == "LONG" else "DELTA_MIN"
        row = {
            "schema": 1,
            "event": event,
            "ts": local_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": side.lower(),
            "delta": delta,
        }
        path = paths[local_ts.date().isoformat()]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


def _config(tmp_path: Path, *, mode: str = "veto", budget: float = 500.0) -> LossAvoidanceRuntimeConfig:
    return LossAvoidanceRuntimeConfig(
        mode=mode,
        enriched_feed_dir=tmp_path / "feed",
        state_path=tmp_path / "state" / "loss_filter_state.json",
        research_archive_dir=tmp_path / "archive",
        evaluation_budget_ms=budget,
    )


def test_startup_bootstraps_full_peak_history_from_canonical_archive(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(
        config.research_archive_dir,
        cutoff=cutoff,
        peaks=[
            (cutoff - timedelta(hours=5), "LONG", 10.0),
            (cutoff - timedelta(hours=2), "LONG", 20.0),
            (cutoff - timedelta(hours=1), "SHORT", -15.0),
        ],
    )
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)

    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert evaluator.record_peak(
        event_ts="2026-01-02 13:00:00", side="LONG", delta=5.0
    )
    result = evaluator.evaluate(
        signal_ts="2026-01-02 13:00:00", side="LONG", delta=5.0
    )

    assert result.peak_history_status == "ARCHIVE_BOOTSTRAPPED"
    assert result.same_side_peak_count_24h == 3
    assert result.same_side_peak_percentile_24h == pytest.approx(100 / 3)
    assert result.decision.component_a is True
    assert config.state_path.exists()


def test_valid_archive_repairs_corrupt_runtime_cache(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    config.state_path.parent.mkdir(parents=True)
    config.state_path.write_text("not json", encoding="utf-8")
    _write_archive(
        config.research_archive_dir,
        cutoff=cutoff,
        peaks=[(cutoff - timedelta(hours=1), "LONG", 10.0)],
    )
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)

    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(
        signal_ts="2026-01-02 13:00:00", side="LONG", delta=5.0
    )

    assert result.peak_history_status == "ARCHIVE_BOOTSTRAPPED"
    assert result.fail_open_reason is None
    assert result.same_side_peak_percentile_24h == 0.0
    assert json.loads(config.state_path.read_text(encoding="utf-8"))["schema"] == STATE_SCHEMA


def test_runtime_exact_cross_midnight_window_matches_policy_and_may_veto(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 0, 30, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_state(
        config.state_path,
        cutoff=cutoff,
        peaks=[
            (cutoff - timedelta(hours=5), "LONG", 10.0),
            (cutoff - timedelta(hours=2), "LONG", 20.0),
        ],
    )
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)

    assert evaluator.record_peak(event_ts="2026-01-02 01:30:00", side="LONG", delta=15.0)
    result = evaluator.evaluate(signal_ts="2026-01-02 01:30:00", side="LONG", delta=15.0)

    assert result.signal_ts_utc == cutoff
    assert result.same_side_peak_count_24h == 3
    assert result.same_side_peak_percentile_24h == pytest.approx(2 / 3 * 100)
    assert result.decision.component_a is False
    assert result.decision.component_b is True
    assert result.decision.union is True
    assert result.feature_status == "EXACT"
    assert result.fail_open_reason is None
    assert result.may_veto is True


def test_incomplete_initial_peak_history_leaves_a_unknown_b_can_still_block(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert evaluator.record_peak(event_ts="2026-01-02 13:00:00", side="LONG", delta=10.0)

    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="LONG", delta=10.0)

    assert result.decision.component_a is None
    assert result.decision.component_b is True
    assert result.decision.union is True
    assert result.may_veto is True


def test_missing_exact_cutoff_is_global_fail_open(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_state(config.state_path, cutoff=cutoff, peaks=[(cutoff, "LONG", 1.0), (cutoff - timedelta(hours=1), "LONG", 10.0)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff, omit_cutoff=True)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)

    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="LONG", delta=1.0)

    assert result.decision.component_a is True
    assert result.feature_status == "STALE"
    assert result.fail_open_reason == "ENRICHED_STALE"
    assert result.may_veto is False


def test_corrupt_state_is_fail_open_even_when_component_b_matches(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    config.state_path.parent.mkdir(parents=True)
    config.state_path.write_text("not json", encoding="utf-8")
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)

    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="LONG", delta=10.0)

    assert result.decision.component_b is True
    assert result.fail_open_reason is not None
    assert result.fail_open_reason.startswith("STATE_LOAD_FAILED")
    assert result.may_veto is False


def test_synthetic_window_is_fail_open(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_feed(config.enriched_feed_dir, cutoff=cutoff, synthetic_at=cutoff - timedelta(minutes=10))
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)

    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="SHORT", delta=-10.0)

    assert result.feature_status == "INVALID"
    assert result.fail_open_reason == "ENRICHED_INVALID"
    assert result.may_veto is False


def test_off_and_invalid_env_modes_never_veto(tmp_path: Path) -> None:
    config = LossAvoidanceRuntimeConfig.from_env(
        {
            "LOSS_FILTER_MODE": "unexpected",
            "LOSS_FILTER_STATE_PATH": str(tmp_path / "state.json"),
        }
    )
    evaluator = LossAvoidanceRuntimeEvaluator(config)
    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="LONG", delta=10.0)

    assert config.mode == "off"
    assert result.feature_status == "DISABLED"
    assert result.may_veto is False


def test_runtime_timestamp_handles_dst_and_rejects_ambiguous_local_minute() -> None:
    assert parse_runtime_timestamp("2026-03-20 01:36:00", "Europe/Bratislava").isoformat() == "2026-03-20T00:36:00+00:00"
    with pytest.raises(ValueError, match="ambiguous"):
        parse_runtime_timestamp("2026-10-25 02:30:00", "Europe/Bratislava")
