from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

from deltascout.loss_avoidance_policy import evaluate_loss_avoidance_policy
from deltascout.loss_avoidance_runtime import RuntimeFilterEvaluation


class FakeEvaluator:
    def __init__(self, evaluation: RuntimeFilterEvaluation) -> None:
        self.mode = evaluation.configured_mode
        self.evaluation = evaluation

    def evaluate(self, **_kwargs) -> RuntimeFilterEvaluation:
        return self.evaluation


def _module(monkeypatch, tmp_path):
    monkeypatch.setenv("DELTASCOUT_LOG", str(tmp_path / "deltascout.log"))
    monkeypatch.setenv("RESEARCH_ARCHIVE_DIR", str(tmp_path / "archive"))
    sys.modules.pop("deltascout.delta_scout", None)
    return importlib.import_module("deltascout.delta_scout")


def _evaluation(*, mode: str, block: bool, fail_open: str | None = None) -> RuntimeFilterEvaluation:
    decision = evaluate_loss_avoidance_policy(
        same_side_peak_percentile_24h=25.0 if block else 75.0,
        oi_change_60m=10.0,
        oi_trusted_60m=True,
        directional_delta_pct_240m=0.1,
    )
    return RuntimeFilterEvaluation(
        configured_mode=mode,
        rule_id=decision.rule_id,
        signal_ts_utc=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
        decision=decision,
        same_side_peak_count_24h=10,
        same_side_peak_percentile_24h=25.0 if block else 75.0,
        oi_change_60m=10.0,
        oi_trusted_60m=True,
        directional_delta_pct_240m=0.1,
        feature_status="EXACT",
        enriched_last_ts_utc=datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc),
        evaluation_ms=1.0,
        fail_open_reason=fail_open,
    )


def _scout(module, evaluator, *, audit_success: bool = True):
    scout = module.Scout.__new__(module.Scout)
    scout.loss_filter = FakeEvaluator(evaluator)
    scout._loss_filter_consecutive_would_block = 0
    scout._loss_filter_circuit_open = False
    scout._loss_filter_counts = {"evaluated": 0, "kept": 0, "blocked": 0, "unknown": 0}
    bus: list[dict] = []
    research: list[tuple[str, dict]] = []
    notifications: list[dict] = []
    scout._emit_json = lambda payload: bus.append(dict(payload))

    def emit_research(event, fields):
        research.append((event, dict(fields)))
        return audit_success if event == "PEAK_LOSS_FILTER_DECISION" else True

    scout._emit_research = emit_research
    scout._notify_loss_filter_block = lambda fields: notifications.append(dict(fields))
    return scout, bus, research, notifications


def _payloads():
    peak = {
        "ts": "2026-08-20 16:30:00",
        "source": "DeltaScout",
        "action": "PEAK",
        "kind": "long",
        "delta": 100.0,
        "vol": 150.0,
        "imb": 0.6,
        "price": 70000.0,
        "vwap": 69900,
        "poc": 69800,
    }
    mirror = {"ts": peak["ts"], "kind": "long", "delta": 100.0, "price": 70000.0}
    return peak, mirror


def test_shadow_block_decision_preserves_exact_live_peak_payload(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, notifications = _scout(module, _evaluation(mode="shadow", block=True))
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is True
    assert bus == [peak]
    assert [event for event, _ in research] == ["PEAK_LOSS_FILTER_DECISION", "PEAK_EMIT"]
    assert research[0][1]["effective_action"] == "EMIT"
    assert research[0][1]["would_be_peak"] == peak
    assert notifications == []


def test_veto_blocks_only_after_successful_durable_audit(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, notifications = _scout(module, _evaluation(mode="veto", block=True))
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is False
    assert bus == []
    assert [event for event, _ in research] == ["PEAK_LOSS_FILTER_DECISION", "PEAK_LOSS_FILTER_REJECT"]
    assert research[1][1]["would_be_peak"] == peak
    assert research[1][1]["reject_reason"] == "loss_avoidance_union"
    assert len(notifications) == 1


def test_veto_audit_failure_is_fail_open(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, notifications = _scout(
        module,
        _evaluation(mode="veto", block=True),
        audit_success=False,
    )
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is True
    assert bus == [peak]
    assert [event for event, _ in research] == ["PEAK_LOSS_FILTER_DECISION", "PEAK_EMIT"]
    assert notifications == []


def test_runtime_fail_open_reason_prevents_veto(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(
        module,
        _evaluation(mode="veto", block=True, fail_open="ENRICHED_STALE"),
    )
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is True
    assert bus == [peak]
    assert research[0][1]["effective_action"] == "EMIT"


def test_circuit_opens_after_five_consecutive_would_blocks(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(module, _evaluation(mode="veto", block=True))
    peak, mirror = _payloads()

    results = [scout._admit_peak(peak, mirror) for _ in range(6)]

    assert results == [False, False, False, False, False, True]
    assert scout._loss_filter_circuit_open is True
    assert bus == [peak]
    decision_rows = [fields for event, fields in research if event == "PEAK_LOSS_FILTER_DECISION"]
    assert decision_rows[-1]["circuit_open"] is True
