from __future__ import annotations

import importlib
from dataclasses import replace
import pytest
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
    admission = bus[0]["loss_filter_admission"]
    assert admission["decision"] == "BLOCK"
    assert admission["effective_action"] == "EMIT"
    assert admission["filter_a"]["status"] == "BLOCK"
    assert admission["filter_b"]["status"] == "PASS"
    assert "same_side_peak_percentile_24h" in admission["filter_a"]["condition"]
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


def test_veto_still_blocks_on_audit_failure(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, notifications = _scout(
        module,
        _evaluation(mode="veto", block=True),
        audit_success=False,
    )
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is False
    assert bus == []
    assert [event for event, _ in research] == ["PEAK_LOSS_FILTER_DECISION", "PEAK_LOSS_FILTER_REJECT"]
    assert peak["loss_filter_admission"]["effective_action"] == "BLOCK"
    assert len(notifications) == 1
    assert notifications[0]["audit_write_failed"] is True


def test_invalid_b_does_not_bypass_known_a_veto(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(
        module,
        _evaluation(mode="veto", block=True, fail_open="ENRICHED_STALE"),
    )
    peak, mirror = _payloads()

    admitted = scout._admit_peak(peak, mirror)

    assert admitted is False
    assert bus == []
    assert research[0][1]["effective_action"] == "BLOCK"
    assert peak["loss_filter_admission"]["filter_a"]["status"] == "BLOCK"
    assert peak["loss_filter_admission"]["fail_open_reason"] == "ENRICHED_STALE"


def test_reliable_blocks_are_not_bypassed_after_five_decisions(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(module, _evaluation(mode="veto", block=True))
    peak, mirror = _payloads()

    results = [scout._admit_peak(peak, mirror) for _ in range(6)]

    assert results == [False, False, False, False, False, False]
    assert scout._loss_filter_circuit_open is False
    assert bus == []
    decision_rows = [fields for event, fields in research if event == "PEAK_LOSS_FILTER_DECISION"]
    assert decision_rows[-1]["effective_action"] == "BLOCK"


def test_filter_status_explains_blocker_flags_for_entry_assessor(monkeypatch, tmp_path) -> None:
    module = _module(monkeypatch, tmp_path)
    scout, bus, _, _ = _scout(module, _evaluation(mode="veto", block=False))
    peak, mirror = _payloads()

    assert scout._admit_peak(peak, mirror) is True
    admission = bus[0]["loss_filter_admission"]
    assert admission["decision"] == "KEEP"
    assert admission["filter_a"]["status"] == "PASS"
    assert admission["filter_b"]["status"] == "PASS"
    assert admission["combined_rule"].startswith("A OR B blocker")


def test_problematic_signal_is_blocked_and_warned(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(module, _evaluation(mode="veto", block=False, fail_open="ENRICHED_STALE"))
    warnings = []
    scout._notify_loss_filter_unverified = lambda peak, admission, reason: warnings.append((peak, admission, reason))
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert len(bus) == 0 and len(warnings) == 1
    assert warnings[0][2] == "ENRICHED_STALE"
    assert warnings[0][1]["filter_a"]["status"] == "PASS"
    assert research[-1][0] == "PEAK_LOSS_FILTER_DATA_BLOCK"


def test_warning_webhook_identifies_signal_not_order(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(module, "WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(module, "post_json", lambda url, payload: sent.append(payload))
    scout, _, _, _ = _scout(module, _evaluation(mode="veto", block=False))
    peak, _ = _payloads()
    scout._notify_loss_filter_unverified(peak, {"filter_a":{"status":"UNKNOWN"},"filter_b":{"status":"PASS"}}, "FILTER_INPUT_UNKNOWN")
    assert sent[0]["event"] == "LOSS_FILTER_UNVERIFIED_BLOCKED"
    assert sent[0]["action"] == "RESEARCH_ONLY"
    assert "Сигнал не відправлено на ринок" in sent[0]["text"]


def test_warning_webhook_for_emitted_signal_does_not_claim_order_open(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(module, "WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(module, "post_json", lambda url, payload: sent.append(payload))
    scout, _, _, _ = _scout(module, _evaluation(mode="veto", block=False))
    peak, _ = _payloads()
    scout._notify_loss_filter_unverified(peak, {"effective_action":"EMIT", "filter_a":{"status":"PASS"}, "filter_b":{"status":"UNKNOWN"}}, "limited_synthetic_240m:count=2")
    assert sent[0]["event"] == "LOSS_FILTER_UNVERIFIED_EMITTED"
    assert "не підтвердження відкриття угоди" in sent[0]["text"]


def test_successful_block_sends_no_unverified_signal_warning(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    scout, bus, _, _ = _scout(module, _evaluation(mode="veto", block=True))
    warnings = []
    scout._notify_loss_filter_unverified = lambda *args: warnings.append(args)
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == [] and warnings == []


def test_completed_block_applies_even_over_evaluation_budget(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    scout, bus, _, _ = _scout(module, _evaluation(mode="veto", block=True, fail_open="EVALUATION_BUDGET_EXCEEDED"))
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == []


def test_both_unknown_are_blocked_and_alerted(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    initial = _evaluation(mode="veto", block=False)
    decision = evaluate_loss_avoidance_policy(same_side_peak_percentile_24h=None, oi_change_60m=None, oi_trusted_60m=False, directional_delta_pct_240m=None)
    evaluation = replace(initial, decision=decision, fail_open_reason="STATE_RECORD_FAILED:ValueError")
    scout, bus, research, _ = _scout(module, evaluation)
    alerts = []
    scout._notify_loss_filter_unverified = lambda peak, admission, reason: alerts.append(reason)
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == [] and alerts == ["STATE_RECORD_FAILED:ValueError"]
    assert research[0][1]["effective_action"] == "BLOCK"
    assert research[-1][0] == "PEAK_LOSS_FILTER_DATA_BLOCK"
    assert peak["loss_filter_admission"]["unknown_policy"] == "BLOCK_AND_WARN"


def test_evaluation_exception_blocks_and_alerts_in_veto(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    scout, bus, research, _ = _scout(module, _evaluation(mode="veto", block=False))
    def fail(**kwargs):
        raise ValueError("failure")
    scout.loss_filter.evaluate = fail
    alerts = []
    scout._notify_loss_filter_unverified = lambda peak, admission, reason: alerts.append(reason)
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == [] and alerts == ["EVALUATION_ERROR"]
    assert peak["loss_filter_admission"]["effective_action"] == "BLOCK"
    assert research[-1][0] == "PEAK_LOSS_FILTER_DATA_BLOCK"


@pytest.mark.parametrize("count", [1, 2])
def test_a_pass_with_up_to_two_synthetic_minutes_emits_with_warning(monkeypatch, tmp_path, count):
    module = _module(monkeypatch, tmp_path)
    initial = _evaluation(mode="veto", block=False)
    decision = evaluate_loss_avoidance_policy(same_side_peak_percentile_24h=75, oi_change_60m=None, oi_trusted_60m=False, directional_delta_pct_240m=None)
    reason = f"limited_synthetic_240m:count={count}"
    evaluation = replace(initial, decision=decision, feature_status="INVALID", fail_open_reason="ENRICHED_INVALID", detail=reason)
    scout, bus, research, _ = _scout(module, evaluation)
    alerts = []
    scout._notify_loss_filter_unverified = lambda peak, admission, reason: alerts.append((admission, reason))
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is True
    assert len(bus) == 1 and len(alerts) == 1 and alerts[0][1] == reason
    assert alerts[0][0]["filter_b"]["status"] == "UNKNOWN"
    assert research[0][1]["quality_exception"] == "UP_TO_TWO_SYNTHETIC_240M_A_PASS"


def test_three_synthetic_minutes_still_blocks_and_warns(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    initial = _evaluation(mode="veto", block=False)
    decision = evaluate_loss_avoidance_policy(same_side_peak_percentile_24h=75, oi_change_60m=None, oi_trusted_60m=False, directional_delta_pct_240m=None)
    evaluation = replace(initial, decision=decision, feature_status="INVALID", fail_open_reason="ENRICHED_INVALID", detail="synthetic_240m:count=3")
    scout, bus, _, _ = _scout(module, evaluation)
    alerts = []
    scout._notify_loss_filter_unverified = lambda *args: alerts.append(args)
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == [] and len(alerts) == 1


def test_failed_audit_still_suppresses_signal(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    scout, bus, _, _ = _scout(module, _evaluation(mode="veto", block=True), audit_success=False)
    warnings = []
    scout._notify_loss_filter_unverified = lambda peak, admission, reason: warnings.append(reason)
    peak, mirror = _payloads()
    assert scout._admit_peak(peak, mirror) is False
    assert bus == [] and warnings == []
