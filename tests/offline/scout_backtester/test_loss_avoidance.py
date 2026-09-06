from __future__ import annotations

from dataclasses import replace

from deltascout.research_bundle.scout_backtester.contracts import TradeResult
from deltascout.research_bundle.scout_backtester.loss_avoidance import (
    build_loss_avoidance_artifacts,
    write_loss_avoidance_summary,
)

from .conftest import candidate


def _result(candidate_id: str, lifecycle: str, net: float) -> TradeResult:
    return TradeResult(
        trade_id=f"T_{candidate_id}",
        candidate_id=candidate_id,
        experiment_id="test",
        replay_mode="independent_opportunity",
        candidate_group="PEAK_EMIT_BASELINE",
        side="LONG",
        signal_ts_utc=candidate().signal_ts_utc,
        entry_status="FILLED",
        lifecycle_class=lifecycle,
        gross_pnl_usdc=net + 1.0,
        net_pnl_usdc=net,
    )


def test_counterfactual_blocks_only_true_union_and_keeps_unknown() -> None:
    blocked = replace(
        candidate(candidate_id="BLOCKED"),
        shadow_flags={
            "weak_peak_le_50": True,
            "oi_down_60_and_directional_delta_pct_240_lt_0_06": None,
            "loss_avoidance_conservative_union": True,
            "oi_trusted_60m": False,
            "directional_delta_pct_240m": None,
        },
    )
    unknown = replace(
        candidate(candidate_id="UNKNOWN", offset_minutes=1),
        shadow_flags={
            "weak_peak_le_50": False,
            "oi_down_60_and_directional_delta_pct_240_lt_0_06": None,
            "loss_avoidance_conservative_union": None,
            "oi_trusted_60m": False,
            "directional_delta_pct_240m": None,
        },
    )
    details, metrics, coverage = build_loss_avoidance_artifacts(
        [blocked, unknown],
        [_result("BLOCKED", "PLAIN_SL", -10.0), _result("UNKNOWN", "TP1_TP2_TRAILING_STOP", 20.0)],
    )

    assert {row["candidate_id"]: row["counterfactual_decision"] for row in details} == {
        "BLOCKED": "BLOCKED",
        "UNKNOWN": "KEPT_UNKNOWN",
    }
    after = next(row for row in metrics if row["cohort"] == "COUNTERFACTUAL_AFTER_FILTER")
    assert after["candidate_count"] == 1
    assert after["protected_count"] == 1
    assert after["net_pnl_usdc_sum"] == 20.0
    union_all = next(
        row for row in coverage
        if row["outcome_class"] == "ALL_CANDIDATES" and row["component"] == "conservative_union"
    )
    assert union_all["unknown_count"] == 1


def test_operational_guardrail_excludes_test_trades(tmp_path) -> None:
    protected = replace(
        candidate(candidate_id="PROTECTED"),
        shadow_flags={
            "weak_peak_le_50": False,
            "oi_down_60_and_directional_delta_pct_240_lt_0_06": False,
            "loss_avoidance_conservative_union": False,
            "oi_trusted_60m": True,
            "directional_delta_pct_240m": 0.10,
        },
    )
    test_trade = replace(
        candidate(candidate_id="TEST", offset_minutes=1),
        shadow_flags={
            "weak_peak_le_50": True,
            "oi_down_60_and_directional_delta_pct_240_lt_0_06": False,
            "loss_avoidance_conservative_union": True,
            "oi_trusted_60m": True,
            "directional_delta_pct_240m": 0.10,
        },
    )
    details, metrics, coverage = build_loss_avoidance_artifacts(
        [protected, test_trade],
        [
            _result("PROTECTED", "TP1_TP2_TRAILING_STOP", 20.0),
            _result("TEST", "PLAIN_SL", -10.0),
        ],
        parity_rows=[
            {
                "candidate_id": "PROTECTED",
                "candidate_join_status": "MATCHED",
                "excluded_from_scoring": False,
                "operational_lifecycle": "TP1_TP2_TRAILING_STOP",
            },
            {
                "candidate_id": "TEST",
                "candidate_join_status": "MATCHED",
                "excluded_from_scoring": True,
                "operational_lifecycle": "PLAIN_SL",
            },
        ],
    )

    output = write_loss_avoidance_summary(
        tmp_path / "summary.md", metrics=metrics, coverage=coverage, details=details
    ).read_text(encoding="utf-8")
    assert "## Operational PEAK guardrail" in output
    assert "| `conservative_union` | 1 | 0/0 | 0/0 | 0/1 |" in output


def test_summary_handles_run_without_peak_candidates(tmp_path) -> None:
    output = write_loss_avoidance_summary(
        tmp_path / "summary.md", metrics=[], coverage=[], details=[]
    ).read_text(encoding="utf-8")

    assert "| `component_a_weak_peak_le_50` | 0 | 0/0/0 | 0 | 0.00 | n/a |" in output
