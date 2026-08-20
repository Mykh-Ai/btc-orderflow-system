from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from .candidate_compiler import compile_candidates, write_candidate_artifacts
from .contracts import (
    CONSERVATIVE_SAME_BAR_POLICY_ID,
    TARGET_FIRST_SAME_BAR_POLICY_ID,
    BacktestContractError,
    CandidateQualityRow,
    ReplayConfig,
)
from .feed_loader import load_feed, quality_counts
from .ledger import write_csv, write_replay_events, write_trade_ledger, write_trade_legs
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
    "trade_key", "excluded_from_scoring", "candidate_id", "candidate_join_status",
    "entry_plan_match", "stop_plan_difference_usd", "tp1_difference_usd",
    "tp2_difference_usd", "qty_difference", "operational_lifecycle",
    "replay_lifecycle", "lifecycle_match", "operational_gross_pnl_usdc",
    "replay_gross_pnl_usdc", "gross_pnl_difference_usdc", "operational_net_pnl_usdc",
    "replay_net_pnl_usdc", "net_pnl_difference_usdc", "mismatch_reason",
]
EQUITY_FIELDS = ["exit_ts", "trade_id", "net_pnl_usdc", "cumulative_net_pnl_usdc"]
DRAWDOWN_FIELDS = ["exit_ts", "trade_id", "equity_peak_usdc", "equity_usdc", "drawdown_usdc"]


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline deterministic DeltaScout candidate replay")
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--raw-archive-root", type=Path)
    parser.add_argument("--feed-root", type=Path, required=True)
    parser.add_argument("--quality-sidecar-root", type=Path)
    parser.add_argument("--server-state-root", type=Path, default=Path("deltascout/research_material/server_state"))
    parser.add_argument("--output-root", type=Path, default=Path("deltascout/research_material/backtests"))
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--candidate-groups", required=True)
    parser.add_argument("--execution-policy", default="EXECUTOR_V15_REPLAY_V0_1")
    parser.add_argument("--fill-model", default="MARKETABLE_LIMIT_NEXT_BAR_V0_1")
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
    return parser


def _existing_nonempty(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _input_paths(
    *,
    candidate_root: Path,
    raw_archive_root: Path,
    feed_root: Path,
    quality_root: Path | None,
    server_state_root: Path,
    date_from: str,
    date_to: str,
    feed_from: str,
    feed_to: str,
) -> list[Path]:
    paths: list[Path] = []
    paths.extend(path for path in sorted(candidate_root.glob("*/events_context_*.csv")) if date_from <= path.parent.name <= date_to)
    paths.extend(path for path in sorted(raw_archive_root.glob("*.jsonl")) if date_from <= path.stem <= date_to)
    paths.extend(path for path in sorted(feed_root.glob("*.csv")) if feed_from <= path.stem <= feed_to)
    if quality_root and quality_root.exists():
        paths.extend(sorted(quality_root.glob("recovery_quality_*.csv")))
        paths.extend(sorted(quality_root.glob("recovery_report_*.md")))
    for name in ("trade_execution_snapshots.jsonl", "trade_pnl_ledger.csv", "trade_outcomes.jsonl"):
        path = server_state_root / name
        if path.exists():
            paths.append(path)
    unique: dict[str, Path] = {str(path.resolve()): path for path in paths}
    return [unique[key] for key in sorted(unique)]


def _available_feed_range(feed_root: Path, date_from: str) -> tuple[str, str]:
    stems = sorted(path.stem for path in feed_root.glob("*.csv") if len(path.stem) == 10)
    if not stems:
        raise BacktestContractError(f"no dated feed files under {feed_root}")
    prior = (datetime.fromisoformat(date_from) - timedelta(days=1)).date().isoformat()
    usable = [stem for stem in stems if stem >= prior]
    if not usable:
        raise BacktestContractError(f"no feed coverage at or after {prior}")
    return usable[0], usable[-1]


def run(args: argparse.Namespace) -> Path:
    candidate_groups = _csv_list(args.candidate_groups)
    replay_modes = _csv_list(args.replay_modes)
    supported_modes = {"independent_opportunity", "executor_portfolio"}
    if not replay_modes or set(replay_modes).difference(supported_modes):
        raise BacktestContractError(f"unsupported replay modes={replay_modes}")
    raw_archive_root = args.raw_archive_root or args.candidate_root.parent / "raw_archive"
    output_dir = args.output_root / args.experiment_id
    if _existing_nonempty(output_dir):
        raise BacktestContractError(f"experiment directory already exists and is non-empty: {output_dir}")

    config = ReplayConfig(
        experiment_id=args.experiment_id,
        description=args.description,
        fixed_notional_usdc=args.fixed_notional_usdc,
        execution_policy_id=args.execution_policy,
        fill_model_id=args.fill_model,
        same_bar_policy_id=args.same_bar_policy,
        cost_model_id=args.cost_model,
        commission_rate=args.commission_rate,
        entry_slippage_bps=args.entry_slippage_bps,
        exit_slippage_bps=args.exit_slippage_bps,
        stop_slippage_bps=args.stop_slippage_bps,
    )
    config.validate()
    candidates, candidate_quality = compile_candidates(
        args.candidate_root,
        date_from=args.date_from,
        date_to=args.date_to,
        raw_archive_root=raw_archive_root,
        candidate_groups=candidate_groups,
    )
    feed_from, feed_to = _available_feed_range(args.feed_root, args.date_from)
    bars = load_feed(
        args.feed_root,
        date_from=feed_from,
        date_to=feed_to,
        quality_sidecar_root=args.quality_sidecar_root,
    )
    candidates = enrich_shadow_flags(
        candidates,
        bars,
        raw_archive_root=raw_archive_root,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    independent, independent_events = replay_independent(candidates, bars, config)

    sensitivity_config = replace(config, same_bar_policy_id=TARGET_FIRST_SAME_BAR_POLICY_ID)
    sensitivity, _ = replay_independent(candidates, bars, sensitivity_config)
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
        quality_root=args.quality_sidecar_root,
        server_state_root=args.server_state_root,
        date_from=args.date_from,
        date_to=args.date_to,
        feed_from=feed_from,
        feed_to=feed_to,
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

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    output_paths.extend(write_candidate_artifacts(candidates, candidate_quality, output_dir))
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
    output_paths.append(
        write_summary(
            output_dir / "summary.md",
            config=config,
            date_from=args.date_from,
            date_to=args.date_to,
            candidates=len(candidates),
            independent=independent,
            portfolio=portfolio,
            parity_rows=parity_rows,
            feed_quality_counts=quality_counts(bars),
            opportunity_rows=opportunities,
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
        feed_date_from=feed_from,
        feed_date_to=feed_to,
        candidate_groups=candidate_groups,
        replay_modes=replay_modes,
        candidate_count=len(candidates),
        quality_count=len(candidate_quality),
        feed_quality_counts=quality_counts(bars),
        exclusions=exclusions,
        output_paths=output_paths,
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
