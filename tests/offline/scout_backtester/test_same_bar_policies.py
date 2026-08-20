from deltascout.research_bundle.scout_backtester.contracts import (
    CONSERVATIVE_SAME_BAR_POLICY_ID,
    TARGET_FIRST_SAME_BAR_POLICY_ID,
)
from deltascout.research_bundle.scout_backtester.same_bar_policies import stop_wins


def test_same_bar_policy_order_is_explicit() -> None:
    assert stop_wins(CONSERVATIVE_SAME_BAR_POLICY_ID) is True
    assert stop_wins(TARGET_FIRST_SAME_BAR_POLICY_ID) is False
