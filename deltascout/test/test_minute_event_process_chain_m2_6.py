from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from deltascout.delta_analyzer.modules.build_minute_event_process_chain import (
    SUPPORTED_CHAIN_ROLES,
    SUPPORTED_FAMILIES,
    build_cluster_summaries,
    build_m2_6_outputs,
    build_reference_cases,
)


def _ts(day: str, hhmm: str) -> str:
    return f"{day} {hhmm}:00"


def _mechanics_row(
    day: str,
    hhmm: str,
    *,
    close: float,
    delta_1m: float,
    vol_1m: float,
    imbalance_1m: float,
    dist_from_vwap: float,
    alignment: str,
    open_interest: float = 1000.0,
) -> dict[str, str]:
    return {
        "ts": _ts(day, hhmm),
        "day": day,
        "close": str(close),
        "delta_1m": str(delta_1m),
        "vol_1m": str(vol_1m),
        "imbalance_1m": str(imbalance_1m),
        "dist_from_vwap": str(dist_from_vwap),
        "delta_price_alignment_1m": alignment,
        "delta_price_efficiency_1m": "1.2",
        "price_vs_vwap_side": "above" if dist_from_vwap > 0 else "below",
        "open_interest": str(open_interest),
        "funding_rate": "0.00001",
        "liq_buy_qty": "1.0",
        "liq_sell_qty": "0.5",
        "delta_sign": "positive" if delta_1m > 0 else "negative" if delta_1m < 0 else "flat_or_unknown",
    }


def _outcomes_row(
    day: str,
    hhmm: str,
    *,
    direction: str,
    ret_fwd_30m: float,
    ret_fwd_60m: float,
    favorable_30m: float,
    adverse_30m: float,
) -> dict[str, str]:
    return {
        "ts": _ts(day, hhmm),
        "day": day,
        "reference_direction": direction,
        "ret_fwd_30m": str(ret_fwd_30m),
        "ret_fwd_60m": str(ret_fwd_60m),
        "favorable_max_30m": str(favorable_30m),
        "adverse_max_30m": str(adverse_30m),
    }


def _sample_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    mechanics = [
        _mechanics_row("2026-01-01", "00:00", close=100.0, delta_1m=10.0, vol_1m=20.0, imbalance_1m=0.2, dist_from_vwap=2.0, alignment="aligned"),
        _mechanics_row("2026-01-01", "00:01", close=102.0, delta_1m=40.0, vol_1m=30.0, imbalance_1m=0.5, dist_from_vwap=20.0, alignment="aligned"),
        _mechanics_row("2026-01-01", "00:05", close=104.0, delta_1m=26.0, vol_1m=29.0, imbalance_1m=0.55, dist_from_vwap=18.0, alignment="aligned"),
        _mechanics_row("2026-01-01", "00:07", close=103.0, delta_1m=22.0, vol_1m=28.0, imbalance_1m=0.6, dist_from_vwap=16.0, alignment="aligned"),
        _mechanics_row("2026-01-01", "00:40", close=103.0, delta_1m=21.0, vol_1m=27.0, imbalance_1m=0.5, dist_from_vwap=18.0, alignment="opposed"),
        _mechanics_row("2026-01-02", "00:00", close=100.0, delta_1m=-38.0, vol_1m=30.0, imbalance_1m=-0.6, dist_from_vwap=-20.0, alignment="aligned"),
    ]
    outcomes = [
        _outcomes_row("2026-01-01", "00:00", direction="up", ret_fwd_30m=1.0, ret_fwd_60m=2.0, favorable_30m=8.0, adverse_30m=7.0),
        _outcomes_row("2026-01-01", "00:01", direction="up", ret_fwd_30m=30.0, ret_fwd_60m=40.0, favorable_30m=50.0, adverse_30m=20.0),
        _outcomes_row("2026-01-01", "00:05", direction="up", ret_fwd_30m=18.0, ret_fwd_60m=22.0, favorable_30m=35.0, adverse_30m=15.0),
        _outcomes_row("2026-01-01", "00:07", direction="up", ret_fwd_30m=-5.0, ret_fwd_60m=-10.0, favorable_30m=10.0, adverse_30m=30.0),
        _outcomes_row("2026-01-01", "00:40", direction="up", ret_fwd_30m=5.0, ret_fwd_60m=7.0, favorable_30m=12.0, adverse_30m=11.0),
        _outcomes_row("2026-01-02", "00:00", direction="down", ret_fwd_30m=25.0, ret_fwd_60m=35.0, favorable_30m=45.0, adverse_30m=18.0),
    ]
    return mechanics, outcomes


def test_m2_6_candidates_build_from_mechanics_and_outcomes_and_schema_has_required_fields():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    assert len(candidates) >= 1
    row = candidates[0]
    assert hasattr(row, "ts")
    assert hasattr(row, "day")
    assert hasattr(row, "direction")
    assert hasattr(row, "family_hint")
    assert hasattr(row, "chain_role_hypothesis")
    assert hasattr(row, "reference_window_id")
    assert hasattr(row, "cum_delta_24h")
    assert hasattr(row, "cum_delta_180m")
    assert hasattr(row, "cum_delta_60m")
    assert hasattr(row, "ret_15m")
    assert hasattr(row, "ret_60m")
    assert hasattr(row, "ret_fwd_30m")
    assert hasattr(row, "ret_fwd_60m")
    assert hasattr(row, "favorable_max_30m")


def test_m2_6_candidates_have_supported_family_and_role_values_only():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    assert {row.family_hint for row in candidates}.issubset(SUPPORTED_FAMILIES)
    assert {row.chain_role_hypothesis for row in candidates}.issubset(SUPPORTED_CHAIN_ROLES)


def test_m2_6_reference_window_id_and_row_ordering_are_deterministic():
    mechanics, outcomes = _sample_rows()
    first, _, _ = build_m2_6_outputs(mechanics, outcomes)
    second, _, _ = build_m2_6_outputs(mechanics, outcomes)

    assert [row.reference_window_id for row in first] == [row.reference_window_id for row in second]
    assert [row.ts for row in first] == sorted([row.ts for row in first])


def test_m2_6_empty_no_match_case_is_clean():
    mechanics = [
        _mechanics_row("2026-01-01", "00:00", close=100.0, delta_1m=1.0, vol_1m=1.0, imbalance_1m=0.1, dist_from_vwap=1.0, alignment="opposed"),
    ]
    outcomes = [
        _outcomes_row("2026-01-01", "00:00", direction="up", ret_fwd_30m=0.0, ret_fwd_60m=0.0, favorable_30m=1.0, adverse_30m=1.0),
    ]

    candidates, references, clusters = build_m2_6_outputs(mechanics, outcomes)
    assert candidates == []
    assert references == []
    assert clusters == []


def test_m2_6_reference_cases_are_deterministic_and_keep_representative_rows_when_eligible():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    a = build_reference_cases(candidates)
    b = build_reference_cases(candidates)

    assert a == b
    assert len(a) >= 1
    required = {
        "ts",
        "day",
        "direction",
        "family_hint",
        "chain_role_label",
        "role_confidence",
        "phase_marker_vs_entry_candidate",
        "reference_window_id",
        "pre_window_summary",
        "post_window_summary",
        "move_followthrough_notes",
        "invalidating_notes",
    }
    assert required.issubset(set(a[0].__dataclass_fields__.keys()))


def test_m2_6_cluster_summaries_deterministic_and_support_lone_and_multi_window_patterns():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    first = build_cluster_summaries(candidates)
    second = build_cluster_summaries(candidates)

    assert first == second
    assert any(row.candidate_count == 1 for row in first)
    assert any(row.candidate_count > 1 for row in first)
    assert all(row.provisional_chain_pattern in {"seed_only", "seed_then_release", "release_only", "continuation_cluster", "late_mixed", "ambiguous"} for row in first)


def test_m2_6_reference_window_id_grouping_is_day_and_direction_aware():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    grouped = {(row.day, row.direction, row.reference_window_id) for row in candidates}
    assert len(grouped) >= 2
    assert all(window_id.startswith(f"{day}_{direction}_") for day, direction, window_id in grouped)


def test_m2_6_role_values_include_unknown_when_evidence_is_insufficient():
    mechanics = [
        _mechanics_row("2026-01-03", "00:00", close=100.0, delta_1m=22.0, vol_1m=28.0, imbalance_1m=0.5, dist_from_vwap=16.0, alignment="opposed"),
    ]
    outcomes = [
        _outcomes_row("2026-01-03", "00:00", direction="up", ret_fwd_30m=1.0, ret_fwd_60m=1.0, favorable_30m=9.0, adverse_30m=8.0),
    ]

    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)
    assert len(candidates) == 1
    assert candidates[0].chain_role_hypothesis == "unknown"


def test_m2_6_candidate_helper_fields_are_present_when_multiple_candidates_exist():
    mechanics, outcomes = _sample_rows()
    candidates, _, _ = build_m2_6_outputs(mechanics, outcomes)

    assert any(row.minutes_from_prev_candidate_any_family is not None for row in candidates)
    assert all(row.candidate_rank_in_window >= 1 for row in candidates)


def test_m2_6_cluster_summary_fields_exist_and_have_datetime_bounds():
    mechanics, outcomes = _sample_rows()
    candidates, _, clusters = build_m2_6_outputs(mechanics, outcomes)

    assert clusters
    sample = clusters[0]
    assert isinstance(sample.earliest_ts, datetime)
    assert isinstance(sample.latest_ts, datetime)
    assert sample.earliest_ts <= sample.latest_ts


def test_m2_6_candidate_build_is_deterministic_under_input_permutation():
    mechanics, outcomes = _sample_rows()
    forward, _, _ = build_m2_6_outputs(mechanics, outcomes)
    reverse, _, _ = build_m2_6_outputs(list(reversed(mechanics)), list(reversed(outcomes)))

    assert forward == reverse


def test_m2_6_reference_cases_include_low_confidence_when_role_is_ambiguous():
    mechanics = [
        _mechanics_row("2026-01-04", "00:00", close=100.0, delta_1m=24.0, vol_1m=27.0, imbalance_1m=0.5, dist_from_vwap=17.0, alignment="opposed"),
    ]
    outcomes = [
        _outcomes_row("2026-01-04", "00:00", direction="up", ret_fwd_30m=1.0, ret_fwd_60m=1.0, favorable_30m=9.0, adverse_30m=8.0),
    ]
    candidates, references, _ = build_m2_6_outputs(mechanics, outcomes)

    assert candidates[0].chain_role_hypothesis == "unknown"
    assert references[0].role_confidence == "low"


def test_m2_6_cluster_pattern_is_conservative_for_mixed_roles():
    mechanics, outcomes = _sample_rows()
    candidates, _, clusters = build_m2_6_outputs(mechanics, outcomes)
    mixed_windows = [row for row in clusters if row.candidate_count > 1]

    assert mixed_windows
    assert all(row.provisional_chain_pattern in {"seed_then_release", "late_mixed", "ambiguous", "continuation_cluster"} for row in mixed_windows)
