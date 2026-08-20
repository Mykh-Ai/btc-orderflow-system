from deltascout.research_bundle import build_losing_trade_commonality as analysis

from datetime import datetime


def test_lifecycle_does_not_treat_every_sl_as_loss():
    assert analysis._lifecycle({"tp1_done": False, "tp2_done": False, "sl_done": True}) == analysis.PLAIN_LOSS
    assert (
        analysis._lifecycle({"tp1_done": True, "tp2_done": True, "trail_active": True, "sl_done": True})
        == analysis.PROTECTED
    )
    assert analysis._lifecycle({"tp1_done": True, "tp2_done": False, "sl_done": True}) == analysis.TP1_STOP


def test_fisher_exact_matches_oi_240m_comparison():
    result = analysis._fisher_two_sided(
        {"count": 9, "denominator": 17, "rate": 9 / 17},
        {"count": 0, "denominator": 7, "rate": 0.0},
    )

    assert result is not None
    assert round(result, 3) == 0.022


def test_diagnostic_family_prioritizes_trusted_oi_decline():
    assert (
        analysis._diagnostic_family(
            {
                "oi_down_240m": True,
                "broad_delta_conflict_24h": True,
                "counterflow_delta_60m": True,
            }
        )
        == "deleveraging_or_missing_position_build_240m"
    )
    assert analysis._diagnostic_family({"oi_down_240m": None}) == "oi_quality_gap"


def test_legacy_local_event_time_is_converted_to_feed_utc():
    assert analysis._feed_utc_naive_from_local(datetime(2026, 8, 18, 16, 30)) == datetime(
        2026, 8, 18, 14, 30
    )
