from deltascout.research_bundle.build_loss_avoidance_policy_review import (
    _oi_down_weak_broad_flow,
    _snapshot_gross,
    _weak_peak,
)


def test_snapshot_gross_handles_long_and_short() -> None:
    base = {
        "fill_summaries": {
            "entry": {"total_quote_qty": "3000"},
            "tp1": {"total_quote_qty": "1010"},
            "tp2": {},
            "final_sl": {"total_quote_qty": "2000"},
        },
        "pnl": {},
    }
    long = {**base, "local_last_closed": {"side": "LONG"}}
    short = {**base, "local_last_closed": {"side": "SHORT"}}
    assert _snapshot_gross(long) == 10.0
    assert _snapshot_gross(short) == -10.0


def test_shadow_components_use_predeclared_boundaries() -> None:
    weak = _weak_peak(50.0)
    assert weak({"peak_delta_percentile_24h": 50.0}) is True
    assert weak({"peak_delta_percentile_24h": 50.1}) is False
    assert _oi_down_weak_broad_flow(
        {"patterns": {"oi_down_60m": True}, "directional_delta_pct_240m": 0.059}
    ) is True
    assert _oi_down_weak_broad_flow(
        {"patterns": {"oi_down_60m": True}, "directional_delta_pct_240m": 0.06}
    ) is False
    assert _oi_down_weak_broad_flow(
        {"patterns": {"oi_down_60m": False}, "directional_delta_pct_240m": 0.01}
    ) is False
