from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


RULE_ID = "DS_PEAK_LOSS_AVOIDANCE_UNION_V1"
PEAK_PERCENTILE_MAX = 50.0
DIRECTIONAL_DELTA_PCT_240M_MAX = 0.06

TriState = bool | None
PolicyDecision = Literal["KEEP", "BLOCK", "UNKNOWN_KEEP"]


@dataclass(frozen=True)
class LossAvoidanceDecision:
    rule_id: str
    component_a: TriState
    component_b: TriState
    union: TriState
    decision: PolicyDecision
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["reason_codes"] = list(self.reason_codes)
        return row


def evaluate_loss_avoidance_policy(
    *,
    same_side_peak_percentile_24h: float | None,
    oi_change_60m: float | None,
    oi_trusted_60m: bool,
    directional_delta_pct_240m: float | None,
) -> LossAvoidanceDecision:
    """Evaluate the frozen PEAK-only loss-avoidance rule.

    Missing or untrusted inputs use three-valued logic. A known match blocks; two
    known misses keep; any unresolved combination is UNKNOWN_KEEP.
    """

    component_a: TriState = (
        same_side_peak_percentile_24h <= PEAK_PERCENTILE_MAX
        if same_side_peak_percentile_24h is not None
        else None
    )
    component_b: TriState = (
        oi_change_60m < 0
        and directional_delta_pct_240m < DIRECTIONAL_DELTA_PCT_240M_MAX
        if oi_trusted_60m
        and oi_change_60m is not None
        and directional_delta_pct_240m is not None
        else None
    )

    if component_a is True or component_b is True:
        union: TriState = True
        decision: PolicyDecision = "BLOCK"
    elif component_a is False and component_b is False:
        union = False
        decision = "KEEP"
    else:
        union = None
        decision = "UNKNOWN_KEEP"

    reasons: list[str] = []
    if component_a is True:
        reasons.append("WEAK_SAME_SIDE_PEAK")
    if component_b is True:
        reasons.append("OI_DOWN_60M_AND_WEAK_DIRECTIONAL_FLOW_240M")
    if decision == "UNKNOWN_KEEP":
        if component_a is None:
            reasons.append("COMPONENT_A_UNKNOWN")
        if component_b is None:
            reasons.append("COMPONENT_B_UNKNOWN")

    return LossAvoidanceDecision(
        rule_id=RULE_ID,
        component_a=component_a,
        component_b=component_b,
        union=union,
        decision=decision,
        reason_codes=tuple(reasons),
    )
