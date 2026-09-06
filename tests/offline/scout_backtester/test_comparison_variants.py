from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from deltascout.research_bundle.scout_backtester.candidate_compiler import (
    compile_candidates,
    comparison_diagnostics,
)
from deltascout.research_bundle.scout_backtester.comparison_variants import (
    VARIANTS,
    build_variant_metrics,
    validate_comparison_variants,
    write_variant_summary,
)
from deltascout.research_bundle.scout_backtester.contracts import ReplayConfig, TradeResult
from .conftest import candidate


@pytest.mark.parametrize(
    ("kind", "price", "previous", "expected"),
    [
        ("long", 101, 100, True),
        ("long", 99, 100, False),
        ("short", 99, 100, True),
        ("short", 101, 100, False),
    ],
)
def test_directional_price_comparison(kind: str, price: float, previous: float, expected: bool) -> None:
    row = {
        "reject_reason": "3of3_fail", "kind": kind,
        "price": price, "prev_price": previous,
        "vol": 11, "prev_vol": 10, "vwap": price, "prev_vwap": previous,
    }
    assert comparison_diagnostics(row)["price_pass"] is expected


def test_volume_and_vwap_comparison_and_failed_gate() -> None:
    row = {
        "reject_reason": "3of3_fail", "kind": "short",
        "price": 99, "prev_price": 100,
        "vol": 10, "prev_vol": 10,
        "vwap": 98, "prev_vwap": 100,
    }
    diagnostics = comparison_diagnostics(row)
    assert diagnostics["vol_pass"] is False
    assert diagnostics["vwap_pass"] is True
    assert diagnostics["pass_count"] == 2
    assert diagnostics["failed"] == "vol"
    assert diagnostics["variant"] == "ALMOST_2OF3_VOLUME_FAIL"


def test_missing_comparison_value_is_explicitly_invalid() -> None:
    diagnostics = comparison_diagnostics({
        "reject_reason": "3of3_fail", "kind": "long",
        "price": 101, "prev_price": 100, "vol": 11, "prev_vol": 10,
        "vwap": 101,
    })
    assert diagnostics["valid"] is False
    assert diagnostics["pass_count"] is None
    assert diagnostics["variant"] is None
    assert "vwap" in diagnostics["quality_detail"]


def test_candidate_id_formula_is_independent_of_variant() -> None:
    timestamp = "2026-03-20T00:36:00+00:00"
    expected = "SCOUT_" + hashlib.sha256(
        f"{timestamp}|LONG|CANDIDATE_COMPARISON_REJECT|70126.44".encode("utf-8")
    ).hexdigest()[:20]
    assert expected == "SCOUT_439f54d000fc77c3741f"


def test_variants_are_mutually_exclusive() -> None:
    items = [
        replace(
            candidate(candidate_id=f"C{index}"),
            candidate_group="ALMOST_PEAK_2_OF_3",
            comparison_price_pass=failed != "price",
            comparison_vol_pass=failed != "vol",
            comparison_vwap_pass=failed != "vwap",
            comparison_3of3_pass_count=2,
            comparison_3of3_failed_subconditions=failed,
            comparison_setup_variant=variant,
        )
        for index, (failed, variant) in enumerate(zip(("price", "vol", "vwap"), VARIANTS))
    ]
    assert validate_comparison_variants(items) == []
    assert len({item.comparison_setup_variant for item in items}) == 3


def test_variant_metrics_are_deterministic() -> None:
    item = replace(
        candidate(candidate_id="C1"),
        candidate_group="ALMOST_PEAK_2_OF_3",
        comparison_price_pass=False,
        comparison_vol_pass=True,
        comparison_vwap_pass=True,
        comparison_3of3_pass_count=2,
        comparison_3of3_failed_subconditions="price",
        comparison_setup_variant="ALMOST_2OF3_PRICE_FAIL",
    )
    result = TradeResult(
        trade_id="T1", candidate_id="C1", experiment_id="x",
        replay_mode="independent_opportunity", candidate_group=item.candidate_group,
        side="LONG", signal_ts_utc=item.signal_ts_utc, entry_status="FILLED",
        lifecycle_class="PLAIN_SL", gross_pnl_usdc=-10, commission_usdc=1,
        net_pnl_usdc=-11, position_r=-1,
    )
    first = build_variant_metrics([item], [result])
    second = build_variant_metrics([item], [result])
    assert first == second


def test_historical_control_distribution_66_74_107() -> None:
    repo = Path(__file__).resolve().parents[3]
    reviews = repo / "deltascout" / "research_material" / "reviews"
    raw = repo / "deltascout" / "research_material" / "raw_archive"
    if not reviews.exists() or not raw.exists():
        pytest.skip("historical research archive is not present")
    candidates, quality = compile_candidates(
        reviews,
        date_from="2026-03-20",
        # The frozen v3 control archive ended on 2026-08-18; later review days
        # are an additive untouched extension and must not move this assertion.
        date_to="2026-08-18",
        raw_archive_root=raw,
        candidate_groups=["ALMOST_PEAK_2_OF_3"],
    )
    counts = {variant: sum(item.comparison_setup_variant == variant for item in candidates) for variant in VARIANTS}
    assert counts == {
        "ALMOST_2OF3_PRICE_FAIL": 66,
        "ALMOST_2OF3_VOLUME_FAIL": 74,
        "ALMOST_2OF3_VWAP_FAIL": 107,
    }
    assert not [row for row in quality if row.reason == "COMPARISON_CLASSIFICATION_INVALID"]


def test_variant_summary_does_not_recommend_negative_volume_cohort(tmp_path) -> None:
    base = {
        "comparison_cohort": "ALMOST_2OF3_VOLUME_FAIL",
        "side": "ALL",
        "candidate_count": 10,
        "filled_count": 8,
        "plain_sl_count": 5,
        "tp1_sl_count": 1,
        "protected_count": 2,
        "net_pnl_usdc": -40.0,
        "mean_net_pnl_per_fill_usdc": -5.0,
        "profit_factor": 0.5,
        "average_r": -0.1,
        "total_r": -0.8,
        "max_drawdown_usdc": 50.0,
    }
    metrics = [
        {**base, "period": "ALL"},
        {**base, "period": "VALIDATION", "candidate_count": 5, "filled_count": 4},
    ]

    output = write_variant_summary(
        tmp_path / "summary.md",
        config=ReplayConfig(experiment_id="negative-volume"),
        metrics=metrics,
        loss_filter=[],
        quality=[],
        distribution={"ALMOST_2OF3_VOLUME_FAIL": 10},
    ).read_text(encoding="utf-8")

    assert "No failed-gate subgroup has positive full-history expectancy" in output
    assert "continue only `ALMOST_2OF3_VOLUME_FAIL`" not in output


def test_variant_summary_identifies_pre_replay_filter_without_reapplying_claim(tmp_path) -> None:
    output = write_variant_summary(
        tmp_path / "summary.md",
        config=ReplayConfig(experiment_id="filtered"),
        metrics=[],
        loss_filter=[],
        quality=[],
        distribution={},
        applied_candidate_loss_filter={
            "policy": "UNION_A_OR_B",
            "input_candidate_count": 70,
            "blocked_candidate_count": 40,
            "kept_candidate_count": 30,
            "unknown_kept_count": 3,
        },
    ).read_text(encoding="utf-8")

    assert "Applied pre-replay loss filter" in output
    assert "Candidates before / blocked / kept: 70 / 40 / 30" in output
    assert "residual reapplication diagnostic" in output
    assert "The union filter is not portable" not in output
