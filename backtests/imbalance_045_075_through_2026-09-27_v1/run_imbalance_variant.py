from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE_REPO = Path(r"D:\Project_V\btc-orderflow-system")
sys.path.insert(0, str(SOURCE_REPO))

from deltascout.research_bundle.scout_backtester import cli  # noqa: E402
from deltascout.research_bundle.scout_backtester.contracts import BacktestContractError  # noqa: E402
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate  # noqa: E402


VARIANTS = {
    "baseline_054_069": {"LONG": (0.54, 0.69), "SHORT": (0.54, 0.69)},
    "lower_045_069": {"LONG": (0.45, 0.69), "SHORT": (0.45, 0.69)},
    "upper_054_075": {"LONG": (0.54, 0.75), "SHORT": (0.54, 0.75)},
    "combined_045_075": {"LONG": (0.45, 0.75), "SHORT": (0.45, 0.75)},
    "long_lower_045": {"LONG": (0.45, 0.69), "SHORT": (0.54, 0.69)},
    "long_lower_050": {"LONG": (0.50, 0.69), "SHORT": (0.54, 0.69)},
    "short_lower_050": {"LONG": (0.54, 0.69), "SHORT": (0.50, 0.69)},
    "baseline_long_only": {"LONG": (0.54, 0.69), "SHORT": None},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=tuple(VARIANTS), required=True)
    args = parser.parse_args()
    thresholds = VARIANTS[args.variant]
    experiment_id = f"{args.variant}_feedfix_v1"

    original_compile = cli.compile_candidates
    original_portfolio = cli.replay_portfolio
    integrity_exclusions: dict[str, dict[str, str]] = {}

    def compile_with_imbalance_band(*compile_args, **compile_kwargs):
        candidates, quality = original_compile(*compile_args, **compile_kwargs)
        selected = []
        for candidate in candidates:
            upstream_passed = candidate.candidate_group == "PEAK_EMIT_BASELINE"
            imbalance_reject = (
                candidate.candidate_group == "GATE_REJECT"
                and candidate.reject_reason == "imb_band"
            )
            if not (upstream_passed or imbalance_reject):
                continue
            if candidate.imbalance is None:
                continue
            side_band = thresholds[candidate.side]
            if side_band is None:
                continue
            imb_min, imb_max = side_band
            if imb_min <= candidate.imbalance <= imb_max:
                selected.append(candidate)
        return selected, quality

    cli.compile_candidates = compile_with_imbalance_band

    def replay_independent_quality_safe(
        candidates, bars, config, *, reference_bars=None
    ):
        results = []
        events = []
        timestamps = [bar.ts for bar in bars]
        reference_bars = reference_bars or bars
        reference_timestamps = [bar.ts for bar in reference_bars]
        for candidate in candidates:
            try:
                result, candidate_events = replay_candidate(
                    candidate,
                    bars,
                    config,
                    reference_bars=reference_bars,
                    _timestamps=timestamps,
                    _reference_timestamps=reference_timestamps,
                )
            except BacktestContractError as exc:
                message = str(exc)
                if not message.startswith("INITIAL_STOP_WRONG_SIDE_AFTER_FILL"):
                    raise
                integrity_exclusions[candidate.candidate_id] = {
                    "candidate_id": candidate.candidate_id,
                    "signal_ts_utc": candidate.signal_ts_utc.isoformat(),
                    "side": candidate.side,
                    "reason": "INITIAL_STOP_WRONG_SIDE_AFTER_FILL",
                    "detail": message,
                }
                continue
            results.append(result)
            events.extend(candidate_events)
        events.sort(key=lambda item: (item.event_ts, item.trade_id, item.event_type))
        return results, events

    def replay_portfolio_quality_safe(candidates, independent_results, config, independent_events=None):
        valid_ids = {result.candidate_id for result in independent_results}
        valid_candidates = [candidate for candidate in candidates if candidate.candidate_id in valid_ids]
        return original_portfolio(
            valid_candidates,
            independent_results,
            config,
            independent_events,
        )

    cli.replay_independent = replay_independent_quality_safe
    cli.replay_portfolio = replay_portfolio_quality_safe
    candidate_index = HERE / "source" / "candidate_index"
    argv = [
        "--candidate-root", str(candidate_index),
        "--raw-archive-root", str(HERE / "source" / "deltascout"),
        "--feed-root", str(HERE / "source" / "effective_feed"),
        "--execution-feed-root", str(HERE / "source" / "execution_feed" / "btcusdc_spot_1m" / "daily"),
        "--quality-sidecar-root", str(SOURCE_REPO / "deltascout" / "research_material" / "recovery_reports"),
        "--server-state-root", str(HERE / "source" / "empty_server_state"),
        "--output-root", str(HERE / "runs"),
        "--date-from", "2026-03-17",
        "--date-to", "2026-09-27",
        "--candidate-groups", "PEAK_EMIT_BASELINE,GATE_REJECT",
        "--candidate-loss-filter", "UNION_A_OR_B",
        "--execution-policy", "EXECUTOR_V15_REPLAY_DUAL_FEED_V0_2",
        "--fill-model", "LIMIT_THEN_MARKET_90S_GUARDED_V0_1",
        "--live-entry-timeout-seconds", "90",
        "--planb-max-dev-r-mult", "0.25",
        "--planb-max-dev-usd", "0",
        "--planb-require-price",
        "--planb-abort-if-past-tp1",
        "--planb-price-proxy", "SECOND_NEXT_BAR_OPEN",
        "--same-bar-policy", "CONSERVATIVE_STOP_FIRST_V0_1",
        "--cost-model", "COMMISSION_TURNOVER_RATE_V0_1",
        "--replay-modes", "independent_opportunity,executor_portfolio",
        "--experiment-id", experiment_id,
        "--description",
        (
            f"Fixed DeltaScout imbalance bands LONG={thresholds['LONG']} "
            f"SHORT={thresholds['SHORT']}; None disables that side; "
            "upstream-pass candidates only; A/B union reapplied; "
            "Executor V15 dual-feed replay through 2026-09-27."
        ),
        "--fixed-notional-usdc", "3000",
        "--commission-rate", "0.000744",
        "--entry-slippage-bps", "0",
        "--exit-slippage-bps", "1",
        "--stop-slippage-bps", "2",
        "--initial-stop-policy", "volume_confirmed_swing",
        "--swing-lookback-minutes", "1440",
        "--initial-swing-price-source", "extreme",
        "--initial-swing-lr", "25",
        "--initial-swing-buffer-usd", "50",
        "--initial-swing-max-distance-usd", "1200",
        "--initial-swing-require-full-window",
        "--trail-swing-lookback", "240",
        "--trail-swing-lr", "25",
        "--trail-swing-buffer-usd", "50",
        "--trail-step-usd", "25",
        "--trail-confirm-buffer-usd", "20",
    ]
    parsed = cli.build_parser().parse_args(argv)
    manifest_path = cli.run(parsed)
    output_dir = manifest_path.parent
    metadata = {
        "variant": args.variant,
        "experiment_id": experiment_id,
        "thresholds_by_side": thresholds,
        "candidate_source_rule": (
            "PEAK_EMIT_BASELINE plus CANDIDATE_GATE_REJECT/reject_reason=imb_band; "
            "retain candidates whose recorded imbalance is inside the fixed band"
        ),
        "date_from": "2026-03-17",
        "date_to": "2026-09-27",
        "candidate_loss_filter": "UNION_A_OR_B",
        "production_changed": False,
    }
    (output_dir / "imbalance_selector.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "integrity_exclusions.json").write_text(
        json.dumps(
            sorted(integrity_exclusions.values(), key=lambda row: row["candidate_id"]),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"output={output_dir}")


if __name__ == "__main__":
    main()
