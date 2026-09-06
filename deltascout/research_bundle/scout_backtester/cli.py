from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from .candidate_compiler import compile_candidates, write_candidate_artifacts
from .comparison_variants import VARIANTS, materialize_variant_artifacts
from .contracts import (
    CONSERVATIVE_SAME_BAR_POLICY_ID,
    CONVERSION_MODEL_ID,
    EXECUTION_POLICY_ID,
    FILL_MODEL_ID,
    IDENTITY_CONVERSION_MODEL_ID,
    LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID,
    TARGET_FIRST_SAME_BAR_POLICY_ID,
    USDT_SIGNAL_EXECUTION_POLICY_ID,
    BacktestContractError,
    Candidate,
    CandidateQualityRow,
    ReplayConfig,
)
from .feed_loader import load_feed, quality_counts
from .ledger import write_csv, write_replay_events, write_trade_ledger, write_trade_legs
from .loss_avoidance import build_loss_avoidance_artifacts, write_loss_avoidance_summary
from .manifests import (
    build_run_fingerprint,
    code_fingerprint,
    input_record,
    write_manifest,
)
from .metrics import build_equity_and_drawdown, build_group_metrics, build_portfolio_metrics
from .parity import build_parity_report
from .portfolio import replay_portfolio
from .replay_engine import replay_independent
from .reports import write_summary
from .shadow_features import enrich_shadow_flags


REPO_ROOT = Path(__file__).resolve().parents[3]

OPPORTUNITY_FIELDS = [
    "blocked_trade_id", "candidate_id", "blocked_reason", "active_trade_id",
    "blocked_independent_lifecycle", "blocked_independent_gross_pnl_usdc",
    "blocked_independent_net_pnl_usdc", "blocked_independent_position_r",
    "blocked_reached_tp1", "blocked_reached_tp2", "opportunity_cost_evaluable", "active_lifecycle",
    "active_net_pnl_usdc", "active_position_r", "entry_improvement_usd",
    "entry_improvement_pct", "normalized_r_difference", "fixed_notional_pnl_difference",
    "r_pnl_ranking_disagrees", "blocked_outperformed_active",
]
PARITY_FIELDS = [
    "trade_key", "operational_record_source", "excluded_from_scoring", "candidate_id", "candidate_join_status",
    "operational_opened_at", "operational_entry_status", "operational_entry_reference", "operational_entry_actual",
    "replay_signal_ts_utc", "replay_entry_status", "replay_entry_fill_ts", "replay_planned_entry_price",
    "entry_execution_match", "entry_plan_match", "stop_plan_difference_usd", "tp1_difference_usd",
    "tp2_difference_usd", "qty_difference", "operational_lifecycle",
    "replay_lifecycle", "lifecycle_match", "operational_gross_pnl_usdc",
    "replay_gross_pnl_usdc", "gross_pnl_difference_usdc", "operational_net_pnl_usdc",
    "replay_net_pnl_usdc", "net_pnl_difference_usdc", "mismatch_reason",
]
EQUITY_FIELDS = ["exit_ts", "trade_id", "net_pnl_usdc", "cumulative_net_pnl_usdc"]
DRAWDOWN_FIELDS = ["exit_ts", "trade_id", "equity_peak_usdc", "equity_usdc", "drawdown_usdc"]
LOSS_FILTER_FLAGS = {
    "NONE": None,
    "COMPONENT_A": "weak_peak_le_50",
    "COMPONENT_B": "oi_down_60_and_directional_delta_pct_240_lt_0_06",
    "UNION_A_OR_B": "loss_avoidance_conservative_union",
}
LOSS_FILTER_EXCLUSION_FIELDS = [
    "candidate_id",
    "signal_ts_utc",
    "side",
    "candidate_group",
    "comparison_setup_variant",
    "loss_filter_policy",
    "component_a",
    "component_b",
    "union_a_or_b",
]


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _apply_candidate_loss_filter(
    candidates: list[Candidate],
    policy: str,
) -> tuple[list[Candidate], list[dict[str, object]], dict[str, object]]:
    flag_name = LOSS_FILTER_FLAGS[policy]
    if flag_name is None:
        return candidates, [], {
            "policy": policy,
            "input_candidate_count": len(candidates),
            "blocked_candidate_count": 0,
            "kept_candidate_count": len(candidates),
            "unknown_kept_count": 0,
            "unknown_policy": "NOT_APPLICABLE",
        }

    blocked = [candidate for candidate in candidates if candidate.shadow_flags.get(flag_name) is True]
    kept = [candidate for candidate in candidates if candidate.shadow_flags.get(flag_name) is not True]
    unknown_kept_count = sum(candidate.shadow_flags.get(flag_name) is None for candidate in kept)
    exclusions = [
        {
            "candidate_id": candidate.candidate_id,
            "signal_ts_utc": candidate.signal_ts_utc.isoformat(),
            "side": candidate.side,
            "candidate_group": candidate.candidate_group,
            "comparison_setup_variant": candidate.comparison_setup_variant,
            "loss_filter_policy": policy,
            "component_a": candidate.shadow_flags.get("weak_peak_le_50"),
            "component_b": candidate.shadow_flags.get(
                "oi_down_60_and_directional_delta_pct_240_lt_0_06"
            ),
            "union_a_or_b": candidate.shadow_flags.get("loss_avoidance_conservative_union"),
        }
        for candidate in blocked
    ]
    return kept, exclusions, {
        "policy": policy,
        "input_candidate_count": len(candidates),
        "blocked_candidate_count": len(blocked),
        "kept_candidate_count": len(kept),
        "unknown_kept_count": unknown_kept_count,
        "unknown_policy": "KEEP_FAIL_OPEN",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline deterministic DeltaScout candidate replay")
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--raw-archive-root", type=Path)
    parser.add_argument("--feed-root", type=Path, required=True)
    parser.add_argument("--execution-feed-root", type=Path, required=True)
    parser.add_argument(
        "--price-contour",
        choices=("btcusdc_spot", "btcusdt_signal"),
        default="btcusdc_spot",
        help="Use BTCUSDC Spot execution prices or keep the full replay on the BTCUSDT signal feed.",
    )
    parser.add_argument("--quality-sidecar-root", type=Path)
    parser.add_argument("--server-state-root", type=Path, default=Path("deltascout/research_material/server_state"))
    parser.add_argument("--output-root", type=Path, default=Path("deltascout/research_material/backtests"))
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--candidate-groups", required=True)
    parser.add_argument(
        "--comparison-setup-variants",
        default="",
        help="Optional comma-separated ALMOST 2/3 failed-gate variants to replay in isolation.",
    )
    parser.add_argument(
        "--candidate-loss-filter",
        choices=tuple(LOSS_FILTER_FLAGS),
        default="NONE",
        help="Optionally remove candidates where the selected loss-filter component is definitely true.",
    )
    parser.add_argument("--execution-policy", default=EXECUTION_POLICY_ID)
    parser.add_argument(
        "--fill-model",
        choices=(FILL_MODEL_ID, LIMIT_THEN_MARKET_90S_GUARDED_FILL_MODEL_ID),
        default=FILL_MODEL_ID,
    )
    parser.add_argument("--live-entry-timeout-seconds", type=int, default=90)
    parser.add_argument("--planb-max-dev-r-mult", type=float, default=0.25)
    parser.add_argument("--planb-max-dev-usd", type=float, default=0.0)
    parser.add_argument(
        "--planb-price-proxy",
        choices=("SECOND_NEXT_BAR_OPEN",),
        default="SECOND_NEXT_BAR_OPEN",
    )
    parser.add_argument(
        "--planb-require-price",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--planb-abort-if-past-tp1",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--same-bar-policy", default=CONSERVATIVE_SAME_BAR_POLICY_ID)
    parser.add_argument("--cost-model", default="COMMISSION_TURNOVER_RATE_V0_1")
    parser.add_argument("--replay-modes", default="independent_opportunity,executor_portfolio")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--fixed-notional-usdc", type=float, default=3000.0)
    parser.add_argument("--commission-rate", type=float, default=0.000744)
    parser.add_argument("--entry-slippage-bps", type=float, default=0.0)
    parser.add_argument("--exit-slippage-bps", type=float, default=1.0)
    parser.add_argument("--stop-slippage-bps", type=float, default=2.0)
    parser.add_argument("--swing-lookback-minutes", type=int, default=180)
    parser.add_argument(
        "--initial-stop-policy",
        choices=("window_extreme", "volume_confirmed_swing"),
        default="window_extreme",
    )
    parser.add_argument(
        "--initial-swing-price-source",
        choices=("close", "extreme"),
        default="close",
        help="Build the initial swing stop from closes or LONG lows / SHORT highs.",
    )
    parser.add_argument("--initial-swing-buffer-usd", type=float, default=0.0)
    parser.add_argument("--initial-swing-lr", type=int, default=25)
    parser.add_argument("--initial-swing-max-distance-usd", type=float, default=0.0)
    parser.add_argument("--initial-swing-require-full-window", action="store_true")
    return parser


def _existing_nonempty(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _input_paths(
    *,
    candidate_root: Path,
    raw_archive_root: Path,
    feed_root: Path,
    execution_feed_root: Path,
    quality_root: Path | None,
    server_state_root: Path,
    date_from: str,
    date_to: str,
    feed_from: str,
    feed_to: str,
    execution_feed_from: str,
    execution_feed_to: str,
) -> list[Path]:
    paths: list[Path] = []
    paths.extend(path for path in sorted(candidate_root.glob("*/events_context_*.csv")) if date_from <= path.parent.name <= date_to)
    peak_history_from = (datetime.fromisoformat(date_from) - timedelta(days=2)).date().isoformat()
    paths.extend(path for path in sorted(raw_archive_root.glob("*.jsonl")) if peak_history_from <= path.stem <= date_to)
    paths.extend(path for path in sorted(feed_root.glob("*.csv")) if feed_from <= path.stem <= feed_to)
    paths.extend(
        path for path in sorted(execution_feed_root.glob("*.csv"))
        if execution_feed_from <= path.stem <= execution_feed_to
    )
    execution_provenance_root = execution_feed_root.parent / "provenance"
    for name in ("source_manifest.json", "daily_quality.csv"):
        path = execution_provenance_root / name
        if path.exists():
            paths.append(path)
    snapshot_manifest = feed_root.parent / "vps_snapshot_manifest.json"
    if snapshot_manifest.exists():
        paths.append(snapshot_manifest)
    if quality_root and quality_root.exists():
        paths.extend(sorted(quality_root.glob("recovery_quality_*.csv")))
        paths.extend(sorted(quality_root.glob("recovery_report_*.md")))
    for name in ("trade_execution_snapshots.jsonl", "trade_pnl_ledger.csv", "trade_outcomes.jsonl"):
        path = server_state_root / name
        if path.exists():
            paths.append(path)
    unique: dict[str, Path] = {str(path.resolve()): path for path in paths}
    return [unique[key] for key in sorted(unique)]


def _available_feed_range(feed_root: Path, date_from: str, *, history_days: int = 1) -> tuple[str, str]:
    stems = sorted(path.stem for path in feed_root.glob("*.csv") if len(path.stem) == 10)
    if not stems:
        raise BacktestContractError(f"no dated feed files under {feed_root}")
    prior = (datetime.fromisoformat(date_from) - timedelta(days=history_days)).date().isoformat()
    usable = [stem for stem in stems if stem >= prior]
    if not usable:
        raise BacktestContractError(f"no feed coverage at or after {prior}")
    return usable[0], usable[-1]


def run(args: argparse.Namespace) -> Path:
    candidate_groups = _csv_list(args.candidate_groups)
    comparison_setup_variants = _csv_list(args.comparison_setup_variants)
    candidate_selection = {
        "comparison_setup_variants": comparison_setup_variants,
        "loss_filter_policy": args.candidate_loss_filter,
    }
    unknown_variants = sorted(set(comparison_setup_variants).difference(VARIANTS))
    if unknown_variants:
        raise BacktestContractError(f"unsupported comparison setup variants={unknown_variants}")
    replay_modes = _csv_list(args.replay_modes)
    supported_modes = {"independent_opportunity", "executor_portfolio"}
    if not replay_modes or set(replay_modes).difference(supported_modes):
        raise BacktestContractError(f"unsupported replay modes={replay_modes}")
    raw_archive_root = args.raw_archive_root or args.candidate_root.parent / "raw_archive"
    output_dir = args.output_root / args.experiment_id
    if _existing_nonempty(output_dir):
        raise BacktestContractError(f"experiment directory already exists and is non-empty: {output_dir}")

    usdt_signal_contour = args.price_contour == "btcusdt_signal"
    execution_policy_id = args.execution_policy
    if usdt_signal_contour and execution_policy_id == EXECUTION_POLICY_ID:
        execution_policy_id = USDT_SIGNAL_EXECUTION_POLICY_ID
    config = ReplayConfig(
        experiment_id=args.experiment_id,
        description=args.description,
        price_contour=args.price_contour,
        symbol="BTCUSDT" if usdt_signal_contour else "BTCUSDC",
        signal_price_symbol="BTCUSDT" if usdt_signal_contour else "BTCUSDT_REFERENCE",
        replay_feed_symbol="BTCUSDT_USDM_FUTURES_ENRICHED" if usdt_signal_contour else "BTCUSDC_SPOT_1M",
        execution_symbol="BTCUSDT" if usdt_signal_contour else "BTCUSDC",
        fixed_notional_usdc=args.fixed_notional_usdc,
        live_entry_timeout_seconds=args.live_entry_timeout_seconds,
        planb_max_dev_r_mult=args.planb_max_dev_r_mult,
        planb_max_dev_usd=args.planb_max_dev_usd,
        planb_require_price=args.planb_require_price,
        planb_abort_if_past_tp1=args.planb_abort_if_past_tp1,
        planb_price_proxy=args.planb_price_proxy,
        swing_lookback_minutes=args.swing_lookback_minutes,
        initial_stop_policy=args.initial_stop_policy,
        initial_swing_price_source=args.initial_swing_price_source,
        initial_swing_buffer_usd=args.initial_swing_buffer_usd,
        initial_swing_lr=args.initial_swing_lr,
        initial_swing_max_distance_usd=args.initial_swing_max_distance_usd,
        initial_swing_require_full_window=args.initial_swing_require_full_window,
        execution_policy_id=execution_policy_id,
        fill_model_id=args.fill_model,
        same_bar_policy_id=args.same_bar_policy,
        cost_model_id=args.cost_model,
        commission_rate=args.commission_rate,
        entry_slippage_bps=args.entry_slippage_bps,
        exit_slippage_bps=args.exit_slippage_bps,
        stop_slippage_bps=args.stop_slippage_bps,
        conversion_model_id=IDENTITY_CONVERSION_MODEL_ID if usdt_signal_contour else CONVERSION_MODEL_ID,
    )
    config.validate()
    candidates, candidate_quality = compile_candidates(
        args.candidate_root,
        date_from=args.date_from,
        date_to=args.date_to,
        raw_archive_root=raw_archive_root,
        candidate_groups=candidate_groups,
    )
    if comparison_setup_variants:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.comparison_setup_variant in comparison_setup_variants
        ]
        if not candidates:
            raise BacktestContractError(
                f"no candidates matched comparison setup variants={comparison_setup_variants}"
            )
    inventory_candidates, inventory_quality = compile_candidates(
        args.candidate_root,
        date_from=args.date_from,
        date_to=args.date_to,
        raw_archive_root=raw_archive_root,
    )
    candidate_quality = inventory_quality
    history_days = max(1, config.swing_lookback_minutes // 1440 + 1)
    feed_from, feed_to = _available_feed_range(
        args.feed_root,
        args.date_from,
        history_days=history_days,
    )
    signal_bars = load_feed(
        args.feed_root,
        date_from=feed_from,
        date_to=feed_to,
        quality_sidecar_root=args.quality_sidecar_root,
    )
    if usdt_signal_contour:
        execution_feed_from, execution_feed_to = feed_from, feed_to
        execution_bars = signal_bars
    else:
        execution_feed_from, execution_feed_to = _available_feed_range(args.execution_feed_root, args.date_from)
        execution_bars = load_feed(
            args.execution_feed_root,
            date_from=execution_feed_from,
            date_to=execution_feed_to,
            feed_role="official_spot_execution",
        )
    candidates = enrich_shadow_flags(
        candidates,
        signal_bars,
        raw_archive_root=raw_archive_root,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    candidates, loss_filter_exclusions, applied_loss_filter = _apply_candidate_loss_filter(
        candidates,
        args.candidate_loss_filter,
    )
    if not candidates:
        raise BacktestContractError(
            f"candidate loss filter removed every selected candidate: {args.candidate_loss_filter}"
        )
    independent, independent_events = replay_independent(
        candidates,
        execution_bars,
        config,
        reference_bars=signal_bars,
    )

    sensitivity_config = replace(config, same_bar_policy_id=TARGET_FIRST_SAME_BAR_POLICY_ID)
    sensitivity, _ = replay_independent(
        candidates,
        execution_bars,
        sensitivity_config,
        reference_bars=signal_bars,
    )
    sensitivity_by_id = {item.candidate_id: item for item in sensitivity}
    same_bar_rows = []
    for result in independent:
        other = sensitivity_by_id[result.candidate_id]
        result.outcome_changes_under_sensitivity = result.lifecycle_class != other.lifecycle_class
        same_bar_rows.append(
            {
                "candidate_id": result.candidate_id,
                "baseline_policy_id": config.same_bar_policy_id,
                "baseline_lifecycle": result.lifecycle_class,
                "baseline_net_pnl_usdc": result.net_pnl_usdc,
                "sensitivity_policy_id": sensitivity_config.same_bar_policy_id,
                "sensitivity_lifecycle": other.lifecycle_class,
                "sensitivity_net_pnl_usdc": other.net_pnl_usdc,
                "outcome_changes": result.lifecycle_class != other.lifecycle_class,
            }
        )

    portfolio, portfolio_events, opportunities = replay_portfolio(candidates, independent, config, independent_events)
    for result in independent:
        if result.entry_status == "NO_FEED_COVERAGE" or result.blocked_reason == "NO_FEED_COVERAGE":
            candidate_quality.append(CandidateQualityRow(result.source_path, None, "NO_FEED_COVERAGE", "untrusted or missing post-signal feed coverage", result.candidate_id))
        elif result.entry_status == "INVALID":
            candidate_quality.append(CandidateQualityRow(result.source_path, None, "INVALID_CANDIDATE", result.blocked_reason, result.candidate_id))

    input_paths = _input_paths(
        candidate_root=args.candidate_root,
        raw_archive_root=raw_archive_root,
        feed_root=args.feed_root,
        execution_feed_root=args.feed_root if usdt_signal_contour else args.execution_feed_root,
        quality_root=args.quality_sidecar_root,
        server_state_root=args.server_state_root,
        date_from=args.date_from,
        date_to=args.date_to,
        feed_from=feed_from,
        feed_to=feed_to,
        execution_feed_from=execution_feed_from,
        execution_feed_to=execution_feed_to,
    )
    records = [input_record(path) for path in input_paths]
    package_root = REPO_ROOT / "deltascout" / "research_bundle" / "scout_backtester"
    fingerprint = build_run_fingerprint(
        config=config,
        input_records=records,
        code_hash=code_fingerprint(package_root),
        date_from=args.date_from,
        date_to=args.date_to,
        candidate_groups=candidate_groups,
        replay_modes=replay_modes,
        candidate_selection=candidate_selection,
    )
    for result in independent + portfolio:
        result.run_fingerprint = fingerprint

    parity_rows = build_parity_report(independent, server_state_root=args.server_state_root, tick_size=config.tick_size)
    all_metric_results = independent + portfolio
    group_metrics = build_group_metrics(all_metric_results)
    equity, drawdown = build_equity_and_drawdown(portfolio)
    portfolio_metrics = build_portfolio_metrics(portfolio, opportunities, drawdown)
    cost_rows = [
        {
            "trade_id": result.trade_id,
            "candidate_id": result.candidate_id,
            "gross_pnl_usdc": result.gross_pnl_usdc,
            "commission_usdc": result.commission_usdc,
            "zero_slippage_net_pnl_usdc": (
                float(result.gross_pnl_usdc) - float(result.commission_usdc)
                if result.gross_pnl_usdc is not None and result.commission_usdc is not None
                else None
            ),
            "adverse_slippage_usdc": result.slippage_usdc,
            "baseline_net_pnl_usdc": result.net_pnl_usdc,
        }
        for result in independent
    ]
    loss_avoidance_detail, loss_avoidance_metrics, loss_avoidance_coverage = build_loss_avoidance_artifacts(
        candidates,
        independent,
        parity_rows=parity_rows,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    variant_paths, research_analysis = materialize_variant_artifacts(
        output_dir,
        config=config,
        candidates=candidates,
        inventory_candidates=inventory_candidates,
        independent=independent,
        quality=candidate_quality,
        applied_candidate_loss_filter=applied_loss_filter,
    )
    research_analysis["requested_comparison_setup_variants"] = comparison_setup_variants
    research_analysis["applied_candidate_loss_filter"] = applied_loss_filter
    output_paths: list[Path] = list(variant_paths)
    output_paths.extend(write_candidate_artifacts(candidates, candidate_quality, output_dir))
    output_paths.append(
        write_csv(
            output_dir / "candidate_loss_filter_exclusions.csv",
            loss_filter_exclusions,
            LOSS_FILTER_EXCLUSION_FIELDS,
        )
    )
    output_paths.append(write_replay_events(output_dir / "replay_events.jsonl", independent_events + portfolio_events))
    if "independent_opportunity" in replay_modes:
        output_paths.append(write_trade_ledger(output_dir / "independent_trades.csv", independent))
    if "executor_portfolio" in replay_modes:
        output_paths.append(write_trade_ledger(output_dir / "portfolio_trades.csv", portfolio))
    output_paths.append(write_trade_legs(output_dir / "trade_legs.csv", independent + portfolio))
    output_paths.append(write_csv(output_dir / "position_lock_opportunity_cost.csv", opportunities, OPPORTUNITY_FIELDS))
    output_paths.append(write_csv(output_dir / "candidate_group_metrics.csv", group_metrics))
    output_paths.append(write_csv(output_dir / "portfolio_metrics.csv", portfolio_metrics))
    output_paths.append(write_csv(output_dir / "equity_curve.csv", equity, EQUITY_FIELDS))
    output_paths.append(write_csv(output_dir / "drawdown.csv", drawdown, DRAWDOWN_FIELDS))
    output_paths.append(write_csv(output_dir / "parity_report.csv", parity_rows, PARITY_FIELDS))
    output_paths.append(write_csv(output_dir / "same_bar_sensitivity.csv", same_bar_rows))
    output_paths.append(write_csv(output_dir / "cost_sensitivity.csv", cost_rows))
    output_paths.append(write_csv(output_dir / "loss_avoidance_counterfactual.csv", loss_avoidance_detail))
    output_paths.append(write_csv(output_dir / "loss_avoidance_metrics.csv", loss_avoidance_metrics))
    output_paths.append(write_csv(output_dir / "loss_avoidance_coverage.csv", loss_avoidance_coverage))
    output_paths.append(
        write_loss_avoidance_summary(
            output_dir / "loss_avoidance_summary.md",
            metrics=loss_avoidance_metrics,
            coverage=loss_avoidance_coverage,
            details=loss_avoidance_detail,
        )
    )
    exclusions = {
        "invalid_candidates": sum(1 for row in candidate_quality if row.reason == "INVALID_CANDIDATE"),
        "duplicates": sum(1 for row in candidate_quality if row.reason == "DUPLICATE_CANDIDATE"),
        "operator_test_parity_rows": sum(1 for row in parity_rows if row["excluded_from_scoring"]),
    }
    manifest_path = write_manifest(
        output_dir / "run_manifest.json",
        config=config,
        repo_root=REPO_ROOT,
        input_records=records,
        run_fingerprint=fingerprint,
        date_from=args.date_from,
        date_to=args.date_to,
        signal_feed_date_from=feed_from,
        signal_feed_date_to=feed_to,
        execution_feed_date_from=execution_feed_from,
        execution_feed_date_to=execution_feed_to,
        candidate_groups=candidate_groups,
        replay_modes=replay_modes,
        candidate_count=len(candidates),
        quality_count=len(candidate_quality),
        signal_feed_quality_counts=quality_counts(signal_bars),
        execution_feed_quality_counts=quality_counts(execution_bars),
        exclusions=exclusions,
        output_paths=output_paths,
        research_analysis=research_analysis,
        candidate_selection=candidate_selection,
    )
    return manifest_path


def main() -> None:
    args = build_parser().parse_args()
    try:
        manifest = run(args)
    except BacktestContractError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"experiment_id={args.experiment_id}")
    print(f"manifest={manifest}")


if __name__ == "__main__":
    main()
