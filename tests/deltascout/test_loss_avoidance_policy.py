from __future__ import annotations

import pytest

from deltascout.loss_avoidance_policy import (
    DIRECTIONAL_DELTA_PCT_240M_MAX,
    PEAK_PERCENTILE_MAX,
    RULE_ID,
    evaluate_loss_avoidance_policy,
)


@pytest.mark.parametrize(
    ("peak", "oi_change", "oi_trusted", "flow", "expected_a", "expected_b", "expected_union", "decision"),
    [
        (49.99, 1.0, True, 0.10, True, False, True, "BLOCK"),
        (PEAK_PERCENTILE_MAX, 1.0, True, 0.10, True, False, True, "BLOCK"),
        (50.01, -1.0, True, 0.0599, False, True, True, "BLOCK"),
        (50.01, -1.0, True, DIRECTIONAL_DELTA_PCT_240M_MAX, False, False, False, "KEEP"),
        (50.01, 0.0, True, 0.01, False, False, False, "KEEP"),
        (None, -1.0, True, 0.01, None, True, True, "BLOCK"),
        (49.0, None, False, None, True, None, True, "BLOCK"),
        (51.0, None, False, None, False, None, None, "UNKNOWN_KEEP"),
        (None, None, False, None, None, None, None, "UNKNOWN_KEEP"),
    ],
)
def test_frozen_truth_table(
    peak,
    oi_change,
    oi_trusted,
    flow,
    expected_a,
    expected_b,
    expected_union,
    decision,
) -> None:
    result = evaluate_loss_avoidance_policy(
        same_side_peak_percentile_24h=peak,
        oi_change_60m=oi_change,
        oi_trusted_60m=oi_trusted,
        directional_delta_pct_240m=flow,
    )

    assert result.rule_id == RULE_ID
    assert result.component_a is expected_a
    assert result.component_b is expected_b
    assert result.union is expected_union
    assert result.decision == decision


def test_reason_codes_identify_each_component() -> None:
    result = evaluate_loss_avoidance_policy(
        same_side_peak_percentile_24h=25.0,
        oi_change_60m=-10.0,
        oi_trusted_60m=True,
        directional_delta_pct_240m=-0.2,
    )

    assert result.reason_codes == (
        "WEAK_SAME_SIDE_PEAK",
        "OI_DOWN_60M_AND_WEAK_DIRECTIONAL_FLOW_240M",
    )
