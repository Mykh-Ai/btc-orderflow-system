"""Frozen, offline pre-TP1 failed-impulse experiment on completed-minute replays.

The ordinary replay is reproduced first. Its chronological TP1/close/interruption
events gate an as-of scan; future lifecycle and PnL never enter the exit rule.
Only a pre-TP1 prefix can be replaced, after which portfolio admission is replayed.
No executor or baseline replay files are changed.
"""
from __future__ import annotations

import argparse
import json
import math
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .build_trade_development import FeedIndex, read_csv, sha
from .scout_backtester.contracts import BacktestContractError, Candidate, ReplayConfig, ReplayEvent, TradeResult
from .scout_backtester.feed_loader import load_feed, parse_feed_timestamp
from .scout_backtester.manifests import code_fingerprint
from .scout_backtester.portfolio import replay_portfolio
from .scout_backtester.replay_engine import _add_leg, _finalize_economics, _quality, replay_independent

MINUTE = timedelta(minutes=1)
EARLY = "EARLY_EXIT_PRE_TP1"


@dataclass(frozen=True)
class ExitRule:
    policy_id: str = "FAILED_IMPULSE_60M_MFE050R_FLOW15M_V1"
    minimum_age_min: int = 60
    minimum_mfe_r: float = 0.5
    flow_window_min: int = 15

    def validate(self):
        if self.minimum_age_min < 1 or self.flow_window_min < 1 or self.minimum_mfe_r <= 0:
            raise BacktestContractError("early-exit parameters must be positive")


def apply_early_exit(base: TradeResult, events: list[ReplayEvent], execution: FeedIndex,
                     reference: FeedIndex, config: ReplayConfig, rule: ExitRule
                     ) -> tuple[TradeResult, list[ReplayEvent], dict]:
    """Evaluate completed bars while the original position is still pre-TP1.

    Intrabar SL/TP1 on the decision bar has priority. A scheduled exit executes
    at the next contiguous bar OPEN, before its later high/low. If that open is
    already at/beyond a standing SL/TP1, preserve the baseline bracket behavior.
    Exit timestamps retain the baseline completed-bar convention (<=1m delay
    in slot availability); the actual open-price time is also logged.
    """
    rule.validate()
    audit = dict(candidate_id=base.candidate_id, policy_id=rule.policy_id,
                 fired=False, eligible_minutes=0, missing_flow_windows=0,
                 unavailable_next_bars=0, standing_bracket_open_collisions=0,
                 execution_gap=False, decision=None)
    if base.entry_status != "FILLED":
        return base, events, audit
    anchor = base.entry_fill_ts
    entry, stop = float(base.entry_fill_price), float(base.initial_stop_price)
    risk = abs(entry - stop)
    sign = 1 if base.side == "LONG" else -1
    if risk <= 0 or sign * (entry - stop) <= 0:
        raise BacktestContractError("non-protective initial risk")
    first = bisect_left(execution.times, anchor)
    if first == len(execution.bars) or execution.times[first] != anchor:
        raise BacktestContractError("entry bar is absent")
    # Future timestamps only restrict the scan when those events have happened.
    end_events = [t for t in (base.tp1_fill_ts, base.exit_ts, base.data_quality_interruption_ts) if t]
    end = min(end_events) if end_events else None
    mfe = 0.0
    previous = anchor - MINUTE
    for index in range(first, len(execution.bars)):
        bar = execution.bars[index]
        if end is not None and bar.ts >= end:
            break
        if bar.ts != previous + MINUTE or bar.is_synthetic:
            audit["execution_gap"] = True
            break
        previous = bar.ts
        # Entry-bar wicks may predate the fill. Its completed close is known.
        favourable = bar.close if index == first else bar.high if sign == 1 else bar.low
        mfe = max(mfe, sign * (favourable - entry) / risk)
        age = (bar.ts - anchor).total_seconds() / 60
        if age < rule.minimum_age_min:
            continue
        audit["eligible_minutes"] += 1
        price_r = sign * (bar.close - entry) / risk
        if mfe < rule.minimum_mfe_r or price_r > 0:
            continue
        flow, complete = reference.complete(bar.ts - MINUTE * rule.flow_window_min, bar.ts)
        valid_qty = all(math.isfinite(b.buy_qty) and math.isfinite(b.sell_qty)
                        and b.buy_qty >= 0 and b.sell_qty >= 0 for b in flow)
        buy, sell = sum(b.buy_qty for b in flow), sum(b.sell_qty for b in flow)
        if not complete or not valid_qty or buy + sell <= 0:
            audit["missing_flow_windows"] += 1
            continue
        delta = sign * (buy - sell) / (buy + sell)
        if delta >= 0:  # zero is neutral, not opposing flow
            continue
        if index + 1 >= len(execution.bars):
            audit["unavailable_next_bars"] += 1
            continue
        nxt = execution.bars[index + 1]
        if nxt.ts != bar.ts + MINUTE or nxt.is_synthetic:
            audit["unavailable_next_bars"] += 1
            continue
        if sign * (nxt.open - stop) <= 0 or sign * (nxt.open - float(base.tp1_price)) >= 0:
            audit["standing_bracket_open_collisions"] += 1
            continue
        decision = dict(decision_ts_utc=bar.ts.isoformat(), age_min=age, mfe_r=mfe,
                        price_r=price_r, directional_delta_pct=delta,
                        flow_window_min=rule.flow_window_min,
                        reference_recovered_minutes=sum(b.recovery_overlap for b in flow),
                        decision_close_usdc=bar.close, risk_price_usdc=risk,
                        fill_bar_close_ts_utc=nxt.ts.isoformat(),
                        fill_price_time_utc=(nxt.ts - MINUTE).isoformat(), fill_price_usdc=nxt.open)
        # Clear all metadata from the discarded future, including quality/collisions.
        result = replace(base, legs=[], exit_ts=nxt.ts, lifecycle_class=EARLY,
                         utility_bucket="RESEARCH_EARLY_EXIT", tp1_fill_ts=None, tp2_fill_ts=None,
                         breakeven_stop_price=None, trail_activation_ts=None, trail_update_count=0,
                         final_stop_price=base.initial_stop_price, data_quality_interruption_ts=None,
                         same_bar_ambiguous=False, same_bar_collision_count=0,
                         outcome_changes_under_sensitivity=None, blocked_reason="")
        result.feed_quality_class, result.recovery_overlap = _quality(execution.bars[first:index + 2])
        _add_leg(result, EARLY, result.qty_total, nxt.open, nxt.ts)
        _finalize_economics(result, config)
        kept = [e for e in events if e.event_ts <= bar.ts]
        kept += [ReplayEvent(bar.ts, "EARLY_EXIT_DECIDED", result.trade_id, result.candidate_id,
                             result.replay_mode, {"policy_id": rule.policy_id, **decision}),
                 ReplayEvent(nxt.ts, "EARLY_EXIT_FILLED", result.trade_id, result.candidate_id,
                             result.replay_mode, {"price": nxt.open, "qty": result.qty_total}),
                 ReplayEvent(nxt.ts, "POSITION_CLOSED", result.trade_id, result.candidate_id,
                             result.replay_mode, {"lifecycle": EARLY})]
        audit.update(fired=True, decision=decision)
        return result, kept, audit
    return base, events, audit


def load_candidates(path: Path) -> list[Candidate]:
    result = []
    floats = ("signal_price", "delta", "volume", "imbalance", "vwap", "poc",
              "comparison_previous_price", "comparison_previous_vol", "comparison_previous_vwap")
    bools = ("comparison_price_pass", "comparison_vol_pass", "comparison_vwap_pass")
    nullable = ("reject_reason", "filter_rule_id", "filter_decision", "comparison_setup_variant",
                "comparison_3of3_failed_subconditions")
    for row in read_csv(path):
        row["signal_ts_utc"] = parse_feed_timestamp(row["signal_ts_utc"])
        row["shadow_flags"] = json.loads(row["shadow_flags"])
        for key in floats:
            row[key] = float(row[key]) if row[key] else None
        for key in bools:
            if row[key] not in ("", "True", "False", "true", "false"):
                raise BacktestContractError(f"invalid bool {key}")
            row[key] = row[key].lower() == "true" if row[key] else None
        for key in nullable:
            row[key] = row[key] or None
        row["comparison_3of3_pass_count"] = int(row["comparison_3of3_pass_count"]) if row["comparison_3of3_pass_count"] else None
        result.append(Candidate(**row))
    if len({c.candidate_id for c in result}) != len(result):
        raise BacktestContractError("duplicate candidates")
    return result


def verify_baseline(results: list[TradeResult], path: Path):
    expected = {r["candidate_id"]: r for r in read_csv(path)}
    if set(expected) != {r.candidate_id for r in results}:
        raise BacktestContractError("baseline candidate membership changed")
    for result in results:
        for key, value in result.to_dict().items():
            if key in {"run_fingerprint", "outcome_changes_under_sensitivity"}:
                continue
            old = expected[result.candidate_id][key]
            if isinstance(value, (float, int)) and not isinstance(value, bool):
                valid = bool(old) and math.isclose(float(old), value, rel_tol=1e-10, abs_tol=1e-8)
            else:
                valid = old == ("" if value is None else str(value))
            if not valid:
                raise BacktestContractError(f"baseline mismatch {result.candidate_id} {key}: {old} / {value}")


def metrics(results: list[TradeResult]) -> dict:
    filled = [r for r in results if r.entry_status == "FILLED"]
    closed = [r for r in filled if r.exit_ts is not None]
    if len(closed) != len(filled):
        raise BacktestContractError("unresolved trades: do not report partial PnL as final")
    pnls = [float(r.net_pnl_usdc) for r in closed]
    gains, losses = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
    equity, peak, dd = 0., 0., 0.
    for r in sorted(closed, key=lambda r: (r.exit_ts, r.trade_id)):
        equity += r.net_pnl_usdc
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dict(candidates=len(results), filled=len(filled), net_usdc=sum(pnls),
                gross_usdc=sum(float(r.gross_pnl_usdc) for r in filled),
                commission_usdc=sum(float(r.commission_usdc) for r in filled),
                slippage_usdc=sum(float(r.slippage_usdc) for r in filled),
                profit_factor=gains / losses if losses else None,
                max_closed_trade_drawdown_usdc=dd,
                lifecycle_counts=dict(Counter(r.lifecycle_class for r in filled)))


def compare(before: list[TradeResult], after: list[TradeResult]) -> tuple[dict, list[dict]]:
    old = {r.candidate_id: r for r in before}
    rows = []
    for new in after:
        base = old[new.candidate_id]
        base_fill, new_fill = base.entry_status == "FILLED", new.entry_status == "FILLED"
        base_net = float(base.net_pnl_usdc) if base_fill else 0.
        new_net = float(new.net_pnl_usdc) if new_fill else 0.
        change = "COMMON" if base_fill and new_fill else "ADDED" if new_fill else "REMOVED" if base_fill else "NEITHER"
        rows.append(dict(candidate_id=new.candidate_id, signal_ts_utc=new.signal_ts_utc.isoformat(),
                         side=new.side, membership_change=change,
                         baseline_lifecycle=base.lifecycle_class, variant_lifecycle=new.lifecycle_class,
                         baseline_net_usdc=base_net, variant_net_usdc=new_net,
                         delta_net_usdc=new_net-base_net, early_exit=new_fill and new.lifecycle_class == EARLY,
                         baseline_exit_ts=base.exit_ts.isoformat() if base.exit_ts else None,
                         variant_exit_ts=new.exit_ts.isoformat() if new.exit_ts else None))
    common = [r for r in rows if r["membership_change"] == "COMMON"]
    summary = dict(baseline=metrics(before), variant=metrics(after),
                   net_change_usdc=sum(r["delta_net_usdc"] for r in rows),
                   common_trade_change_usdc=sum(r["delta_net_usdc"] for r in common),
                   common_plain_sl_change_usdc=sum(r["delta_net_usdc"] for r in common if r["baseline_lifecycle"] == "PLAIN_SL"),
                   common_tp1_sl_change_usdc=sum(r["delta_net_usdc"] for r in common if r["baseline_lifecycle"] == "TP1_SL"),
                   common_tp2_trail_change_usdc=sum(r["delta_net_usdc"] for r in common if r["baseline_lifecycle"] == "TP1_TP2_TRAILING_STOP"),
                   added_count=sum(r["membership_change"] == "ADDED" for r in rows),
                   removed_count=sum(r["membership_change"] == "REMOVED" for r in rows),
                   admission_change_usdc=sum(r["delta_net_usdc"] for r in rows if r["membership_change"] in {"ADDED", "REMOVED"}),
                   early_exit_baseline_classes=dict(Counter(r["baseline_lifecycle"] for r in rows if r["early_exit"])))
    assert math.isclose(summary["net_change_usdc"], summary["variant"]["net_usdc"]-summary["baseline"]["net_usdc"], abs_tol=1e-8)
    return summary, rows


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def build(no_filter_root: Path, ab_root: Path, execution_root: Path, reference_root: Path,
          quality_root: Path, output_root: Path) -> dict:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"choose an empty output root: {output_root}")
    rule = ExitRule()
    protocol = dict(schema="EARLY_EXIT_EXPERIMENT_V1", frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                    rule=asdict(rule), decision_frequency="every completed minute while pre-TP1",
                    return_condition="directional execution close <= actual fill (0R)",
                    flow_condition="side * sum(buy-sell)/sum(buy+sell) < 0 over exact last 15 completed reference minutes",
                    risk="abs(actual modeled fill - initial SL)",
                    mfe="completed execution High/Low since fill; entry candle close only; no post-exit wicks",
                    fill="next contiguous execution bar open; normal exit cost; existing brackets at that open have priority",
                    timing="fills/portfolio cooldown retain completed-bar labels, <=1m later than the modeled open-price time",
                    controls="same candidates, filters, sizing, SL/TP/trailing, commissions, slippage and portfolio lock/cooldown",
                    missing="skip incomplete flow windows; no forward filling; stop exit scan at missing/synthetic execution",
                    search="one hypothesis, no threshold optimization or parameter sweep",
                    scope="existing PEAK reference-class diagnostics; retrospective, previously inspected sample; not OOS",
                    exclusions="no live changes; no funding/OI/liquidation features in exit; net excludes borrow interest",
                    builder_sha256=sha(Path(__file__)))
    output_root.mkdir(parents=True, exist_ok=True)
    write_json(output_root/"protocol.json", protocol)  # freeze before calculating results
    roots = dict(all=no_filter_root, ab=ab_root)
    manifests = {key: json.loads((root/"run_manifest.json").read_text()) for key, root in roots.items()}
    frozen_inputs = {}
    current_code = code_fingerprint(Path(__file__).parent/"scout_backtester")
    for manifest in manifests.values():
        if manifest["feed_contract_version"] != "SCOUT_FEED_V0_2_COMPLETED_MINUTE" or manifest["code_fingerprint"] != current_code:
            raise BacktestContractError("baseline code or completed-minute contract changed")
        for item in manifest["input_files"]:
            path = Path(item["path"]).resolve()
            if path in frozen_inputs and frozen_inputs[path] != item["sha256"]:
                raise BacktestContractError(f"conflicting frozen source: {path}")
            frozen_inputs[path] = item["sha256"]
    for path, digest in frozen_inputs.items():
        if sha(path) != digest:
            raise BacktestContractError(f"frozen input changed: {path}")
    print(f"verified {len(frozen_inputs)} frozen inputs and replay code", flush=True)
    dates = manifests["all"]["date_range"]
    if dates != manifests["ab"]["date_range"]:
        raise BacktestContractError("cohort feed ranges differ")
    execution = FeedIndex(load_feed(execution_root, date_from=dates["execution_feed_from"],
        date_to=dates["execution_feed_to"], feed_role="official_spot_execution"))
    reference = FeedIndex(load_feed(reference_root, date_from=dates["signal_feed_from"],
        date_to=dates["signal_feed_to"], quality_sidecar_root=quality_root))
    loaded = {Path(b.source_path).resolve() for b in execution.bars+reference.bars}
    loaded.update(p.resolve() for p in quality_root.glob("recovery_quality_*.csv"))
    for path in loaded:
        if frozen_inputs.get(path) != sha(path):
            raise BacktestContractError(f"loaded feed is not frozen baseline input: {path}")
    summaries, comparisons, audits, trades, replay_events = {}, {}, {}, {}, {}
    for cohort, root in roots.items():
        raw_config = dict(manifests[cohort]["resolved_config"])
        raw_config["tp_r_multipliers"] = tuple(raw_config["tp_r_multipliers"])
        config = ReplayConfig(**raw_config)
        config.validate()
        candidates = load_candidates(root/"normalized_candidates.csv")
        print(f"reproducing {cohort}: {len(candidates)} candidates", flush=True)
        baseline, events = replay_independent(candidates, execution.bars, config, reference_bars=reference.bars)
        verify_baseline(baseline, root/"independent_trades.csv")
        base_portfolio, _, _ = replay_portfolio(candidates, baseline, config, events)
        verify_baseline(base_portfolio, root/"portfolio_trades.csv")
        by_id = defaultdict(list)
        for event in events:
            by_id[event.candidate_id].append(event)
        variant, variant_events, cohort_audit = [], [], []
        for base in baseline:
            trade, changed_events, audit = apply_early_exit(base, by_id[base.candidate_id], execution, reference, config, rule)
            variant.append(trade)
            variant_events.extend(changed_events)
            cohort_audit.append(audit)
        portfolio, portfolio_events, _ = replay_portfolio(candidates, variant, config, variant_events)
        audits[cohort] = cohort_audit
        for mode, before, after, current_events in (
            ("independent", baseline, variant, variant_events),
            ("portfolio", base_portfolio, portfolio, portfolio_events)):
            key = f"{cohort}_{mode}"
            summaries[key], comparisons[key] = compare(before, after)
            trades[key] = [dict(**r.to_dict(), legs=[leg.to_dict() for leg in r.legs]) for r in after]
            replay_events[key] = [e.to_dict() for e in sorted(current_events, key=lambda e: (e.event_ts, e.trade_id, e.event_type))]
        print(f"{cohort}: baseline reproduced; independent triggers={sum(a['fired'] for a in cohort_audit)}", flush=True)
    payload = dict(protocol=protocol, summaries=summaries, comparisons=comparisons, audits=audits, trades=trades)
    write_json(output_root/"analysis.json", payload)
    write_json(output_root/"replay_events.json", replay_events)
    sources = [root/name for root in roots.values() for name in
               ("run_manifest.json", "normalized_candidates.csv", "independent_trades.csv", "portfolio_trades.csv", "trade_legs.csv")]
    sources += [Path(__file__), Path(__file__).parent/"build_trade_development.py", quality_root/"recovery_manifest.json"]
    write_json(output_root/"experiment_manifest.json", dict(schema="EARLY_EXIT_EXPERIMENT_V1",
        generated_at_utc=datetime.now(timezone.utc).isoformat(), replay_code_fingerprint=current_code,
        frozen_inputs_verified=len(frozen_inputs), baseline_reproduction="all fields except run hash and unused same-bar sensitivity flag",
        sources=[dict(path=str(p), sha256=sha(p)) for p in sources],
        outputs=[dict(path=str(output_root/name), sha256=sha(output_root/name))
                 for name in ("protocol.json", "analysis.json", "replay_events.json")]))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("no-filter-root", "ab-root", "execution-root", "reference-root", "quality-root", "output-root"):
        parser.add_argument("--"+name, type=Path, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
