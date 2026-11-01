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
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=5), "LONG", 10), (cutoff-timedelta(hours=2), "LONG", 20)])
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


def test_missing_exact_cutoff_does_not_cancel_trustworthy_a_block(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_state(config.state_path, cutoff=cutoff, peaks=[(cutoff, "LONG", 1.0), (cutoff - timedelta(hours=1), "LONG", 10.0)])
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff, "LONG", 1.0), (cutoff-timedelta(hours=1), "LONG", 10.0)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff, omit_cutoff=True)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)

    result = evaluator.evaluate(signal_ts="2026-01-02 13:00:00", side="LONG", delta=1.0)

    assert result.decision.component_a is True
    assert result.feature_status == "STALE"
    assert result.fail_open_reason == "ENRICHED_STALE"
    assert result.may_veto is True


def test_corrupt_state_does_not_cancel_trustworthy_b_block(tmp_path: Path) -> None:
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
    assert result.decision.component_a is None
    assert result.may_veto is True


def test_synthetic_window_is_fail_open(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[])
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


def test_old_fault_recovers_from_current_archive(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 6, 7, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff - timedelta(hours=1), "LONG", 20.0)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    assert evaluator._state_error.startswith("STATE_RECORD_FAILED")
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.peak_history_status == "ARCHIVE_VERIFIED_RECOVERED"
    assert result.fail_open_reason is None
    assert result.decision.component_a is True
    assert result.may_veto is True


def test_fault_recovery_backfills_archived_extrema_before_deciding(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 6, 7, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    # Two archived extrema missing from cache change A from BLOCK to PASS.
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[
        (cutoff-timedelta(hours=1), "LONG", 20),
        (cutoff-timedelta(hours=2), "LONG", 2),
        (cutoff-timedelta(minutes=30), "LONG", 3),
    ])
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is False
    assert result.same_side_peak_count_24h == 3
    assert result.same_side_peak_percentile_24h == pytest.approx(200/3)
    assert result.fail_open_reason is None
    assert result.peak_history_status == "ARCHIVE_VERIFIED_RECOVERED"
    assert len(json.loads(config.state_path.read_text())["peaks"]) == 3


def test_archive_reads_only_on_history_fault_and_stop_after_recovery(tmp_path: Path, monkeypatch) -> None:
    cutoff = datetime(2026, 11, 1, 6, 7, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    opened = []
    original_open = Path.open

    def observe_open(path, *args, **kwargs):
        if path.parent == config.research_archive_dir:
            opened.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observe_open)
    for _ in range(3):
        assert evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5).fail_open_reason is None
    assert not opened
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    assert evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5).fail_open_reason is None
    read_count = len(opened)
    assert read_count == 2
    for _ in range(3):
        assert evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5).fail_open_reason is None
    assert len(opened) == read_count


def test_synthetic_b_does_not_cancel_known_a_veto(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff, synthetic_at=cutoff-timedelta(minutes=10))
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is True
    assert result.decision.component_b is None
    assert result.may_veto is True


def test_ambiguous_extrema_in_active_window_remains_untrusted(tmp_path: Path) -> None:
    cutoff = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    with (config.research_archive_dir / "2026-10-25.jsonl").open("a") as handle:
        handle.write(json.dumps({"event":"DELTA_MAX","kind":"long","ts":"2026-10-25 02:37:00","delta":10}) + "\n")
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is None
    assert result.fail_open_reason.startswith("STATE_RECORD_FAILED")
    # The independent B input may still produce a valid block.
    assert result.decision.component_b is True
    assert result.may_veto is True


def test_recovery_requires_successful_persist(tmp_path: Path, monkeypatch) -> None:
    cutoff = datetime(2026, 11, 1, 6, 7, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    monkeypatch.setattr(evaluator, "_persist_state", lambda: False)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is None
    assert result.fail_open_reason is not None


def test_restart_with_old_ambiguous_row_outside_window_recovers(tmp_path: Path) -> None:
    cutoff = datetime(2026, 10, 26, 2, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    current = cutoff - timedelta(hours=1)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(current, "LONG", 20)])
    _write_state(config.state_path, cutoff=cutoff, peaks=[(current, "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    with (config.research_archive_dir / "2026-10-25.jsonl").open("a") as handle:
        handle.write(json.dumps({"event":"DELTA_MAX","kind":"long","ts":"2026-10-25 02:37:00","delta":10}) + "\n")
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert evaluator._state_error.startswith("ARCHIVE_BOOTSTRAP_FAILED")
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.peak_history_status == "ARCHIVE_VERIFIED_RECOVERED"
    assert result.decision.component_a is True and result.may_veto


def test_recovery_reconciles_delta_disagreement_from_archive(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 6, 7, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    evaluator._peaks = [type(evaluator._peaks[0])(evaluator._peaks[0].event_ts_utc, "LONG", 22)]
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is True
    assert result.fail_open_reason is None
    assert result.peak_history_status == "ARCHIVE_VERIFIED_RECOVERED"
    assert evaluator._peaks[0].abs_delta == 20
    assert json.loads(config.state_path.read_text())["peaks"][0]["abs_delta"] == 20


def test_incomplete_archive_cannot_make_stale_state_a_trustworthy(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_state(config.state_path, cutoff=cutoff-timedelta(hours=4), peaks=[(cutoff-timedelta(hours=6), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.peak_history_status == "ARCHIVE_INCOMPLETE"
    assert result.decision.component_a is None
    assert result.fail_open_reason.startswith("ARCHIVE_BOOTSTRAP_INCOMPLETE")


def test_bootstrap_merges_rounded_archive_and_precise_state_without_double_count(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    t = cutoff - timedelta(hours=1)
    _write_state(config.state_path, cutoff=cutoff, peaks=[(t, "LONG", 20.1234)])
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(t, "LONG", 20.12)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=20.122)
    assert result.same_side_peak_count_24h == 1
    assert result.same_side_peak_percentile_24h == 0.0
    assert result.peak_history_status == "ARCHIVE_BOOTSTRAPPED"


@pytest.mark.parametrize("precise", [20.1236, 20.1264])
@pytest.mark.parametrize("reverse", [False, True])
def test_bootstrap_accepts_old_cache_precision_duplicates(tmp_path: Path, precise: float, reverse: bool) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    ts = cutoff - timedelta(hours=1)
    rounded = round(precise, 2)
    values = [rounded, precise]
    if reverse:
        values.reverse()
    # This is the state shape persisted by the old merge + exact-value dedup.
    _write_state(config.state_path, cutoff=cutoff, peaks=[(ts, "LONG", value) for value in values])
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(ts, "LONG", rounded)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert result.fail_open_reason is None
    assert result.decision.component_a is False
    assert result.same_side_peak_count_24h == 1
    assert evaluator._peaks[0].abs_delta == precise
    assert len(json.loads(config.state_path.read_text())["peaks"]) == 1
    # A subsequent restart must preserve the same single-event distribution.
    restarted = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    again = restarted.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert again.fail_open_reason is None
    assert again.same_side_peak_count_24h == 1
    assert restarted._peaks[0].abs_delta == precise


def test_bootstrap_delta_difference_uses_archive_without_history_fault(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    ts = cutoff - timedelta(hours=1)
    _write_state(config.state_path, cutoff=cutoff, peaks=[(ts, "LONG", 22)])
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(ts, "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=21)
    assert result.fail_open_reason is None
    assert result.decision.component_a is False
    assert result.same_side_peak_count_24h == 1
    assert evaluator._peaks[0].abs_delta == 20


@pytest.mark.parametrize("archive_repeats", [1, 2])
def test_stale_fault_recovers_with_repeated_precision_variants(tmp_path: Path, archive_repeats: int) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    ts = cutoff - timedelta(hours=1)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(ts, "LONG", 20.12)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    # Exercise recovery of an already-running cache, independently of bootstrap.
    event_type = type(evaluator._peaks[0])
    evaluator._peaks = [event_type(ts, "LONG", value) for value in (20.12, 20.1236)]
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(ts, "LONG", 20.12)] * archive_repeats)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert result.fail_open_reason is None
    assert result.peak_history_status == "ARCHIVE_VERIFIED_RECOVERED"
    assert result.decision.component_a is False
    assert result.same_side_peak_count_24h == 1
    assert evaluator._peaks[0].abs_delta == 20.1236


def test_repeated_live_record_is_one_event_and_keeps_opposite_side(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[])
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    for side, value in [("LONG", 20.1236), ("LONG", 20.12), ("SHORT", -20.12)]:
        assert evaluator.record_peak(event_ts=cutoff.isoformat(), side=side, delta=value)
    assert len(evaluator._peaks) == 2
    assert evaluator._peak_percentile(cutoff=cutoff, side="LONG", delta=30)[0] == 1
    assert evaluator._peak_percentile(cutoff=cutoff, side="SHORT", delta=-30)[0] == 1


def test_bootstrap_retains_cached_extrema_absent_from_research_archive(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_state(config.state_path, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=5)
    assert result.decision.component_a is True
    assert result.same_side_peak_count_24h == 1
    assert result.fail_open_reason is None
    assert result.peak_history_status == "ARCHIVE_BOOTSTRAPPED"
    assert evaluator._peaks[0].abs_delta == 20


def test_recovery_unions_event_ids_without_merging_other_times_or_sides(tmp_path: Path) -> None:
    cutoff = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    ts = cutoff-timedelta(hours=1)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(ts, "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    assert not evaluator.record_peak(event_ts="2026-10-25 02:37:00", side="LONG", delta=10)
    # A cache-only opposite-side event must survive repair.
    assert evaluator.record_peak(event_ts=ts.isoformat(), side="SHORT", delta=-20)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[
        (ts, "LONG", 20), (ts+timedelta(minutes=1), "LONG", 20),
    ])
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert result.fail_open_reason is None
    assert {(peak.event_ts_utc, peak.side) for peak in evaluator._peaks} == {
        (ts, "LONG"), (ts+timedelta(minutes=1), "LONG"), (ts, "SHORT"),
    }
    assert result.same_side_peak_count_24h == 2


@pytest.mark.parametrize("count", [1, 2, 3])
def test_synthetic_rows_are_counted_without_inventing_b_values(tmp_path: Path, count: int) -> None:
    cutoff = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff)
    path = config.enriched_feed_dir / "2026-01-02.csv"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows[5:5+count]:
        row["IsSynthetic"] = "1"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert result.decision.component_a is False
    assert result.decision.component_b is None
    assert result.detail == (f"limited_synthetic_240m:count={count}" if count <= 2 else "synthetic_240m:count=3")


def test_synthetic_exception_rejects_other_invalid_rows(tmp_path: Path) -> None:
    cutoff = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    config = _config(tmp_path)
    _write_archive(config.research_archive_dir, cutoff=cutoff, peaks=[(cutoff-timedelta(hours=1), "LONG", 20)])
    _write_feed(config.enriched_feed_dir, cutoff=cutoff, synthetic_at=cutoff-timedelta(minutes=10))
    path = config.enriched_feed_dir / "2026-01-02.csv"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["BuyQty"] = "not-a-number"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    evaluator = LossAvoidanceRuntimeEvaluator(config, now_fn=lambda: cutoff)
    result = evaluator.evaluate(signal_ts=cutoff.isoformat(), side="LONG", delta=30)
    assert result.detail.startswith("invalid_numeric:")
