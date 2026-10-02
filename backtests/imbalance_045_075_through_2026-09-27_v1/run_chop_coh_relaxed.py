from __future__ import annotations

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE_REPO = Path(r"D:\Project_V\btc-orderflow-system")
sys.path.insert(0, str(SOURCE_REPO))

from deltascout.research_bundle.scout_backtester import cli  # noqa: E402
from deltascout.research_bundle.scout_backtester.contracts import BacktestContractError  # noqa: E402
from deltascout.research_bundle.scout_backtester.replay_engine import replay_candidate  # noqa: E402


EXPERIMENT_ID = "chop_coh_relaxed_long050_short054_feedfix_v2"
BANDS = {"LONG": (0.50, 0.69), "SHORT": (0.54, 0.69)}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def tri(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def main() -> None:
    ab_rows = read_csv(HERE / "chop_coh_ab_results.csv")
    ab_by_key = {
        (row["signal_ts_utc"], row["side"]): row
        for row in ab_rows
    }
    accepted_chop_keys = {
        key for key, row in ab_by_key.items() if row["decision"] != "BLOCK"
    }
    blocked_chop_keys = set(ab_by_key) - accepted_chop_keys

    original_compile = cli.compile_candidates
    original_enrich = cli.enrich_shadow_flags
    original_portfolio = cli.replay_portfolio
    integrity_exclusions: dict[str, dict[str, str]] = {}

    def compile_with_policy(*compile_args, **compile_kwargs):
        candidates, quality = original_compile(*compile_args, **compile_kwargs)
        selected = []
        for candidate in candidates:
            if candidate.imbalance is None:
                continue
            imb_min, imb_max = BANDS[candidate.side]
            if not (imb_min <= candidate.imbalance <= imb_max):
                continue

            is_baseline = candidate.candidate_group == "PEAK_EMIT_BASELINE"
            is_imb = (
                candidate.candidate_group == "GATE_REJECT"
                and candidate.reject_reason == "imb_band"
            )
            is_chop = (
                candidate.candidate_group == "GATE_REJECT"
                and candidate.reject_reason == "chop_coh"
            )
            if is_chop:
                key = (candidate.signal_ts_utc.isoformat(), candidate.side)
                if key not in accepted_chop_keys:
                    continue
                selected.append(candidate)
                continue

            if not (is_baseline or is_imb):
                continue
            selected.append(candidate)
        return selected, quality

    cli.compile_candidates = compile_with_policy

    def enrich_with_exact_chop(*enrich_args, **enrich_kwargs):
        candidates = original_enrich(*enrich_args, **enrich_kwargs)
        enriched = []
        for candidate in candidates:
            key = (candidate.signal_ts_utc.isoformat(), candidate.side)
            if not (
                candidate.candidate_group == "GATE_REJECT"
                and candidate.reject_reason == "chop_coh"
                and key in accepted_chop_keys
            ):
                enriched.append(candidate)
                continue
            ab = ab_by_key[key]
            enriched.append(
                replace(
                    candidate,
                    shadow_flags={
                        **candidate.shadow_flags,
                        "weak_peak_le_50": tri(ab["component_a"]),
                        "oi_down_60_and_directional_delta_pct_240_lt_0_06": tri(ab["component_b"]),
                        "loss_avoidance_conservative_union": tri(ab["union"]),
                        "same_side_peak_count_24h": int(ab["same_side_peak_count_24h"]),
                        "same_side_peak_percentile_24h": float(ab["same_side_peak_percentile_24h"]),
                        "oi_change_60m": float(ab["oi_change_60m"]) if ab["oi_change_60m"] else None,
                        "oi_trusted_60m": tri(ab["oi_trusted_60m"]),
                        "directional_delta_pct_240m": (
                            float(ab["directional_delta_pct_240m"])
                            if ab["directional_delta_pct_240m"]
                            else None
                        ),
                        "counterfactual_ab_decision": ab["decision"],
                    },
                )
            )
        return enriched

    cli.enrich_shadow_flags = enrich_with_exact_chop

    def replay_independent_quality_safe(candidates, bars, config, *, reference_bars=None):
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
        return original_portfolio(valid_candidates, independent_results, config, independent_events)

    cli.replay_independent = replay_independent_quality_safe
    cli.replay_portfolio = replay_portfolio_quality_safe
    argv = [
        "--candidate-root", str(HERE / "source" / "candidate_index"),
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
        "--experiment-id", EXPERIMENT_ID,
        "--description",
        (
            "LONG imbalance 0.50-0.69, SHORT 0.54-0.69; baseline and imb-band candidates "
            "use reapplied A/B union, and chop_coh rejects use exact cutoff-safe A/B results; "
            "combined-filter relaxation; Executor V15 replay through 2026-09-27."
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
    manifest_path = cli.run(cli.build_parser().parse_args(argv))
    output_dir = manifest_path.parent
    metadata = {
        "experiment_id": EXPERIMENT_ID,
        "bands": BANDS,
        "candidate_sources": ["PEAK_EMIT_BASELINE", "imb_band", "chop_coh"],
        "chop_coh_ab_input": {
            "total": len(ab_rows),
            "accepted_live_semantics": len(accepted_chop_keys),
            "blocked": len(blocked_chop_keys),
        },
        "supersedes_run": "chop_coh_relaxed_long050_short054_feedfix_v1",
        "supersession_reason": (
            "v1 selected baseline/imb candidates before shadow enrichment and therefore did not "
            "reapply UNION_A_OR_B with parity to long_lower_050"
        ),
        "production_changed": False,
    }
    (output_dir / "chop_coh_selector.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "integrity_exclusions.json").write_text(
        json.dumps(sorted(integrity_exclusions.values(), key=lambda row: row["candidate_id"]), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"output={output_dir}")


if __name__ == "__main__":
    main()
