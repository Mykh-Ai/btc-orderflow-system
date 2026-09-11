"""Offline, as-of trade checkpoints from immutable completed-minute V8 replays.

Outcome labels are explicitly prefixed label_. This builder neither replays orders
nor changes exits. Missing market windows remain missing, including after exit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .scout_backtester.contracts import BacktestContractError, FeedBar
from .scout_backtester.feed_loader import load_feed, parse_feed_timestamp

HORIZONS = (5, 15, 30, 60, 240, 1440)
COHORTS = ("all_independent", "all_portfolio", "ab_independent", "ab_portfolio")


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise BacktestContractError(f"empty output: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FeedIndex:
    def __init__(self, bars: list[FeedBar]):
        self.bars = bars
        self.times = [bar.ts for bar in bars]
        self.at = {bar.ts: bar for bar in bars}
        if self.times != sorted(set(self.times)):
            raise BacktestContractError("feed must contain unique sorted UTC minutes")

    def window(self, start: datetime, end: datetime) -> list[FeedBar]:
        return self.bars[bisect_right(self.times, start):bisect_right(self.times, end)]

    def complete(self, start: datetime, end: datetime) -> tuple[list[FeedBar], bool]:
        bars = self.window(start, end)
        expected = max(0, int((end - start).total_seconds() / 60))
        return bars, len(bars) == expected and not any(bar.is_synthetic for bar in bars)


def signed_excursions(prices: list[float], entry: float, sign: int, risk: float) -> tuple[float, float]:
    moves = [0.] + [sign * (p - entry) / risk for p in prices]
    return max(moves), -min(moves)


def checkpoint(trade: dict, legs: list[dict], execution: FeedIndex, reference: FeedIndex,
               horizon: int, costs: dict) -> dict:
    anchor = parse_feed_timestamp(trade["entry_fill_ts"])
    target = anchor + timedelta(minutes=horizon)
    entry, stop, qty = (float(trade[k]) for k in ("entry_fill_price", "initial_stop_price", "qty_total"))
    risk = abs(entry - stop)
    sign = 1 if trade["side"] == "LONG" else -1
    if risk <= 0 or sign * (entry - stop) <= 0 or qty <= 0:
        raise BacktestContractError("invalid filled trade risk geometry")
    exit_ts = parse_feed_timestamp(trade["exit_ts"]) if trade.get("exit_ts") else None
    closed = exit_ts is not None and exit_ts <= target
    done = [leg for leg in legs if parse_feed_timestamp(leg["exit_ts"]) <= target]
    remaining = qty - sum(float(leg["qty"]) for leg in done)
    if abs(remaining) < 1e-10:
        remaining = 0.
    if remaining < 0 or closed != (remaining == 0):
        raise BacktestContractError(f"leg/position mismatch: {trade['candidate_id']} horizon={horizon}")

    market, market_complete = execution.complete(anchor, target)
    ref, ref_complete = reference.complete(anchor, target)
    at_entry, at_target = execution.at.get(anchor), execution.at.get(target)
    ref_entry, ref_target = reference.at.get(anchor), reference.at.get(target)
    mark = at_target.close if at_target is not None and not at_target.is_synthetic else None
    market_complete = bool(market_complete and at_entry is not None and not at_entry.is_synthetic)
    ref_complete = bool(ref_complete and ref_entry is not None and not ref_entry.is_synthetic)
    price_r = sign * (mark - entry) / risk if mark is not None else None
    market_mfe = market_mae = None
    if market_complete:
        # Entry-bar wicks are excluded: a limit touch may have occurred after them.
        market_mfe, market_mae = signed_excursions(
            [at_entry.close] + [p for b in market for p in (b.high, b.low)], entry, sign, risk)

    # During-position excursion is a lower bound. Terminal-bar wicks may occur
    # after exit, so use only full interior bars plus known executed leg prices.
    active_end = min(target, exit_ts - timedelta(minutes=1)) if closed else target
    active_end = max(anchor, active_end)
    active_bars, active_complete = execution.complete(anchor, active_end)
    active_points = [float(leg["exit_price"]) for leg in done]
    if at_entry is not None and not at_entry.is_synthetic and (exit_ts is None or exit_ts > anchor):
        active_points.append(at_entry.close)
    active_points.extend(p for b in active_bars for p in (b.high, b.low))
    active_mfe = active_mae = None
    if active_complete:
        active_mfe, active_mae = signed_excursions(active_points, entry, sign, risk)

    gross_realized = sum(float(leg["gross_pnl_usdc"]) for leg in done)
    unrealized = remaining * sign * (mark - entry) if remaining and mark is not None else 0. if not remaining else None
    commission = qty * entry * costs["commission_rate"]
    slippage = qty * entry * costs["entry_slippage_bps"] / 10000
    for leg in done:
        turnover = float(leg["qty"]) * float(leg["exit_price"])
        commission += turnover * costs["commission_rate"]
        bps = costs["stop_slippage_bps"] if leg["leg_type"].endswith("STOP") else costs["exit_slippage_bps"]
        slippage += turnover * bps / 10000
    gross = gross_realized + unrealized if unrealized is not None else None
    exit_cost_estimate = remaining * mark * (costs["commission_rate"] + costs["exit_slippage_bps"] / 10000) if remaining and mark is not None else 0.
    net = gross - commission - slippage - exit_cost_estimate if gross is not None else None
    if closed and not math.isclose(net, float(trade["net_pnl_usdc"]), abs_tol=1e-7):
        raise BacktestContractError(f"closed PnL does not reconcile: {trade['candidate_id']}")

    directional_delta, delta_pct, ref_return, flow_response = None, None, None, "UNAVAILABLE"
    structure_adverse, first_adverse, breached = None, None, None
    if ref_complete:
        buy, sell = sum(b.buy_qty for b in ref), sum(b.sell_qty for b in ref)
        directional_delta = sign * (buy - sell)
        delta_pct = directional_delta / (buy + sell) if buy + sell > 0 else None
        ref_return = sign * (ref_target.close / ref_entry.close - 1)
        if delta_pct is not None:
            flow_response = ("SUPPORTIVE" if delta_pct > 0 else "OPPOSING" if delta_pct < 0 else "NEUTRAL")
            flow_response += "_PROGRESS" if ref_return > 0 else "_NO_PROGRESS"
        level = float(trade["initial_swing_price_usdt"])
        adverse = [b for b in [ref_entry] + ref if sign * (b.close - level) < 0]
        breached = bool(adverse)
        structure_adverse = sign * (ref_target.close - level) < 0
        first_adverse = (adverse[0].ts - anchor).total_seconds() / 60 if adverse else None

    tp1 = parse_feed_timestamp(trade["tp1_fill_ts"]) if trade.get("tp1_fill_ts") else None
    tp2 = parse_feed_timestamp(trade["tp2_fill_ts"]) if trade.get("tp2_fill_ts") else None
    state = "CLOSED" if closed else "TRAILING" if tp2 is not None and tp2 <= target else "TP1_DONE" if tp1 is not None and tp1 <= target else "OPEN_PRE_TP1"
    return {
        "candidate_id": trade["candidate_id"], "trade_id": trade["trade_id"], "side": trade["side"],
        "entry_bar_close_ts_utc": anchor.isoformat(), "horizon_min": horizon, "checkpoint_ts_utc": target.isoformat(),
        "state_at_checkpoint": state, "remaining_qty": remaining,
        "entry_price_usdc": entry, "initial_stop_usdc": stop, "risk_price_usdc": risk, "risk_capital_usdc": risk * qty,
        "market_complete": market_complete, "market_minutes_observed": len(market),
        "reference_complete": ref_complete, "reference_minutes_observed": len(ref),
        "reference_recovered_minutes": sum(b.recovery_overlap for b in ref),
        "reference_quality_classes": ",".join(sorted({b.feed_quality_class for b in ref})),
        "market_close_usdc": mark, "market_price_r": price_r,
        "market_mfe_r": market_mfe, "market_mae_r": market_mae,
        "position_mfe_lower_bound_r": active_mfe, "position_mae_lower_bound_r": active_mae,
        "position_gross_realized_usdc": gross_realized, "position_gross_unrealized_usdc": unrealized,
        "position_gross_r": gross / (risk * qty) if gross is not None else None,
        "position_net_if_closed_now_usdc": net, "position_net_if_closed_now_r": net / (risk * qty) if net is not None else None,
        "commission_incurred_usdc": commission, "slippage_incurred_usdc": slippage,
        "remaining_exit_cost_estimate_usdc": exit_cost_estimate,
        "directional_delta_qty": directional_delta, "directional_delta_pct": delta_pct,
        "directional_reference_return_pct": ref_return, "flow_price_response": flow_response,
        "structure_level_usdt": float(trade["initial_swing_price_usdt"]),
        "structure_adverse_at_checkpoint": structure_adverse, "structure_breached_by_checkpoint": breached,
        "structure_first_adverse_min": first_adverse,
        "tp1_done_by_checkpoint": bool(tp1 is not None and tp1 <= target),
        "label_lifecycle": trade["lifecycle_class"],
        "label_time_to_tp1_min": (tp1 - anchor).total_seconds() / 60 if tp1 is not None else None,
        "label_holding_min": (exit_ts - anchor).total_seconds() / 60 if exit_ts is not None else None,
        "label_final_net_usdc": float(trade["net_pnl_usdc"]),
    }


def summarize(rows: list[dict]) -> list[dict]:
    result = []
    for cohort in COHORTS:
        selected = [r for r in rows if r[cohort]]
        for lifecycle in ["ALL", "PLAIN_SL", "TP1_SL", "TP1_TP2_TRAILING_STOP"]:
            for horizon in sorted({r["horizon_min"] for r in rows}):
                group = [r for r in selected if r["horizon_min"] == horizon and (lifecycle == "ALL" or r["label_lifecycle"] == lifecycle)]
                if not group:
                    continue
                def med(key):
                    values = [r[key] for r in group if r[key] is not None]
                    return statistics.median(values) if values else None
                full = [r for r in group if r["market_complete"]]
                ref_full = [r for r in group if r["reference_complete"]]
                result.append(dict(cohort=cohort, lifecycle=lifecycle, horizon_min=horizon, trade_count=len(group),
                    open_count=sum(r["state_at_checkpoint"] != "CLOSED" for r in group),
                    market_complete_count=len(full), reference_complete_count=len(ref_full),
                    tp1_done_count=sum(r["tp1_done_by_checkpoint"] for r in group),
                    median_market_price_r=med("market_price_r"), median_market_mfe_r=med("market_mfe_r"),
                    median_market_mae_r=med("market_mae_r"),
                    median_position_mfe_lower_bound_r=med("position_mfe_lower_bound_r"),
                    median_position_mae_lower_bound_r=med("position_mae_lower_bound_r"),
                    median_position_net_r=med("position_net_if_closed_now_r"),
                    median_directional_delta_pct=med("directional_delta_pct"),
                    supportive_no_progress_count=sum(r["flow_price_response"] == "SUPPORTIVE_NO_PROGRESS" for r in ref_full),
                    structure_adverse_count=sum(r["structure_adverse_at_checkpoint"] is True for r in ref_full),
                    median_label_time_to_tp1_min=med("label_time_to_tp1_min")))
    return result


def build(no_filter_root: Path, ab_root: Path, execution_root: Path, reference_root: Path,
          quality_root: Path, output_root: Path, horizons=HORIZONS) -> dict:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"choose an empty new output root: {output_root}")
    if not horizons or any(h <= 0 or not isinstance(h, int) for h in horizons):
        raise ValueError("horizons must be positive integer minutes")
    manifests = [json.loads((root / "run_manifest.json").read_text()) for root in (no_filter_root, ab_root)]
    for manifest in manifests:
        if manifest["feed_contract_version"] != "SCOUT_FEED_V0_2_COMPLETED_MINUTE":
            raise BacktestContractError("requires completed-minute clock-corrected baseline")
        for record in manifest["input_files"]:
            if sha(Path(record["path"])) != record["sha256"]:
                raise BacktestContractError(f"baseline input changed: {record['path']}")
    source_hashes = {str(Path(r["path"]).resolve()): r["sha256"] for r in manifests[0]["input_files"]}
    independent = read_csv(no_filter_root / "independent_trades.csv")
    if len({t['candidate_id'] for t in independent}) != len(independent):
        raise BacktestContractError("duplicate candidates")
    cohorts = dict(zip(COHORTS, [independent, read_csv(no_filter_root / "portfolio_trades.csv"),
        read_csv(ab_root / "independent_trades.csv"), read_csv(ab_root / "portfolio_trades.csv")]))
    membership = {key: {r["candidate_id"] for r in values if r["entry_status"] == "FILLED"} for key, values in cohorts.items()}
    legs = defaultdict(list)
    for leg in read_csv(no_filter_root / "trade_legs.csv"):
        legs[leg["trade_id"]].append(leg)
    dates = manifests[0]["date_range"]
    execution = FeedIndex(load_feed(execution_root, date_from=dates["execution_feed_from"], date_to=dates["execution_feed_to"], feed_role="official_spot_execution"))
    reference = FeedIndex(load_feed(reference_root, date_from=dates["signal_feed_from"], date_to=dates["signal_feed_to"], quality_sidecar_root=quality_root))
    loaded_paths = {Path(b.source_path) for b in execution.bars + reference.bars}
    loaded_paths.update(quality_root.glob("recovery_quality_*.csv"))
    for path in loaded_paths:
        if source_hashes.get(str(path.resolve())) != sha(path):
            raise BacktestContractError(f"loaded feed/quality is not a frozen baseline input: {path}")
    independent_by_id = {t["candidate_id"]: t for t in independent}
    for values in cohorts.values():
        for t in values:
            if t["entry_status"] != "FILLED":
                continue
            base = independent_by_id[t["candidate_id"]]
            for key in ("entry_fill_ts", "exit_ts", "side", "lifecycle_class"):
                if t[key] != base[key]:
                    raise BacktestContractError(f"cohort trajectory differs for {t['candidate_id']}: {key}")
            for key in ("entry_fill_price", "initial_stop_price", "net_pnl_usdc"):
                if not math.isclose(float(t[key]), float(base[key]), abs_tol=1e-7):
                    raise BacktestContractError(f"cohort economics differ for {t['candidate_id']}: {key}")
    output, inventory = [], []
    for trade in independent:
        member = {key: trade["candidate_id"] in values for key, values in membership.items()}
        inventory.append({**trade, **member})
        if trade["entry_status"] != "FILLED":
            continue
        trade_legs = legs[trade["trade_id"]]
        if not trade_legs:
            raise BacktestContractError(f"missing legs: {trade['trade_id']}")
        if len({leg['leg_id'] for leg in trade_legs}) != len(trade_legs):
            raise BacktestContractError(f"duplicate legs: {trade['trade_id']}")
        if trade.get("exit_ts") and not math.isclose(sum(float(leg['qty']) for leg in trade_legs), float(trade['qty_total']), abs_tol=1e-10):
            raise BacktestContractError(f"closed trade quantities do not reconcile: {trade['trade_id']}")
        for horizon in sorted(set(horizons)):
            output.append({**checkpoint(trade, trade_legs, execution, reference, horizon, manifests[0]["resolved_config"]), **member})
    summaries = summarize(output)
    output_root.mkdir(parents=True, exist_ok=True)
    write_csv(output_root / "trade_checkpoints.csv", output)
    write_csv(output_root / "cohort_summary.csv", summaries)
    write_csv(output_root / "candidate_inventory.csv", inventory)
    payload = dict(checkpoints=output, summaries=summaries, inventory=inventory)
    (output_root / "analysis.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    source_paths = [root / name for root in (no_filter_root, ab_root)
        for name in ("run_manifest.json", "independent_trades.csv", "portfolio_trades.csv", "trade_legs.csv")]
    manifest = dict(schema="TRADE_DEVELOPMENT_V0_1", generated_at_utc=datetime.now(timezone.utc).isoformat(),
        horizons_min=sorted(set(horizons)), anchor="entry_fill_ts completed-bar label; intrabar timing uncertain by <=1m",
        risk_definition="abs(actual modeled fill - initial SL), fixed throughout position",
        excursion_definition="market excludes entry-bar wicks; position also excludes exit-bar wicks, adds executed leg prices (lower bound)",
        builder_sha256=sha(Path(__file__)), sources=[dict(path=str(p), sha256=sha(p)) for p in source_paths],
        candidate_count=len(inventory), checkpoint_count=len(output), cohort_fills={k:len(v) for k,v in membership.items()},
        missing_market_windows=sum(not r['market_complete'] for r in output),
        missing_reference_windows=sum(not r['reference_complete'] for r in output))
    (output_root / "development_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("no-filter-root", "ab-root", "execution-root", "reference-root", "quality-root", "output-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--horizons", default=",".join(map(str, HORIZONS)))
    args = vars(parser.parse_args())
    args["horizons"] = tuple(int(h) for h in args["horizons"].split(","))
    print(json.dumps(build(**args), indent=2))


if __name__ == "__main__":
    main()
