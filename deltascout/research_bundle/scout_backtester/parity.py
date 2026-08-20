from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import TradeResult


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalized_lifecycle(value: Any) -> str:
    return str(value or "").strip().upper()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _pnl_by_key(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {str(row.get("trade_key") or ""): row for row in csv.DictReader(handle)}


def _operational_records(server_state_root: Path) -> list[dict[str, Any]]:
    snapshots = _load_jsonl(server_state_root / "trade_execution_snapshots.jsonl")
    if snapshots:
        return snapshots
    outcomes = _load_jsonl(server_state_root / "trade_outcomes.jsonl")
    return [
        {
            "schema": row.get("schema"),
            "trade_key": (row.get("last_closed") or {}).get("trade_key"),
            "ts": row.get("ts"),
            "excluded_from_scoring": False,
            "local_last_closed": row.get("last_closed") or {},
            "lifecycle_class": (row.get("last_closed") or {}).get("trade_lifecycle_state"),
        }
        for row in outcomes
    ]


def _match_result(record: dict[str, Any], results: list[TradeResult]) -> tuple[TradeResult | None, str]:
    last_closed = record.get("local_last_closed") or {}
    opened_at = _parse_ts(last_closed.get("opened_at"))
    side = str(last_closed.get("side") or "").upper()
    if opened_at is None or side not in {"LONG", "SHORT"}:
        return None, "missing operational opened_at/side"
    eligible: list[tuple[float, float, TradeResult]] = []
    live_entry = _float((last_closed.get("prices") or {}).get("entry") or last_closed.get("entry"))
    for result in results:
        if result.side != side or result.entry_fill_ts is None:
            continue
        time_distance = abs((result.entry_fill_ts - opened_at).total_seconds())
        if time_distance > 6 * 3600:
            continue
        price_distance = abs(float(result.planned_entry_price or 0.0) - live_entry) if live_entry is not None else 0.0
        eligible.append((time_distance, price_distance, result))
    if not eligible:
        return None, "no candidate within six hours of operational entry"
    eligible.sort(key=lambda item: (item[0], item[1], item[2].candidate_id))
    best = eligible[0]
    if len(eligible) > 1 and best[:2] == eligible[1][:2]:
        return None, "ambiguous candidate match"
    return best[2], ""


def build_parity_report(
    results: list[TradeResult],
    *,
    server_state_root: Path,
    tick_size: float,
) -> list[dict[str, Any]]:
    records = _operational_records(server_state_root)
    pnl = _pnl_by_key(server_state_root / "trade_pnl_ledger.csv")
    rows: list[dict[str, Any]] = []
    for record in records:
        last_closed = record.get("local_last_closed") or {}
        trade_key = str(record.get("trade_key") or last_closed.get("trade_key") or "")
        excluded = bool(record.get("excluded_from_scoring"))
        result, join_reason = _match_result(record, results)
        live_prices = last_closed.get("prices") or {}
        live_entry = _float(live_prices.get("entry") or last_closed.get("entry"))
        live_stop = _float(live_prices.get("sl"))
        live_tp1 = _float(live_prices.get("tp1"))
        live_tp2 = _float(live_prices.get("tp2"))
        live_qty = _float(last_closed.get("qty"))
        live_tp1_done = bool(last_closed.get("tp1_done"))
        operational_lifecycle = _normalized_lifecycle(record.get("lifecycle_class") or last_closed.get("trade_lifecycle_state"))
        pnl_row = pnl.get(trade_key, {})
        operational_gross = _float(pnl_row.get("gross_pnl_usdc"))
        operational_net = _float(pnl_row.get("net_pnl_usdc"))
        mismatch_reasons: list[str] = []
        if excluded:
            mismatch_reasons.append(str(record.get("scoring_exclusion_reason") or "excluded_from_scoring"))
        if join_reason:
            mismatch_reasons.append(join_reason)
        entry_match = (
            abs(float(result.planned_entry_price) - live_entry) <= tick_size
            if result and result.planned_entry_price is not None and live_entry is not None
            else None
        )
        stop_difference = (
            float(result.initial_stop_price) - live_stop
            if result and not live_tp1_done and result.initial_stop_price is not None and live_stop is not None
            else None
        )
        tp1_difference = float(result.tp1_price) - live_tp1 if result and result.tp1_price is not None and live_tp1 is not None else None
        tp2_difference = float(result.tp2_price) - live_tp2 if result and result.tp2_price is not None and live_tp2 is not None else None
        qty_difference = float(result.qty_total) - live_qty if result and live_qty is not None else None
        if entry_match is False:
            mismatch_reasons.append("entry_plan_difference_conversion_or_order_timing")
        if result is not None and live_tp1_done:
            mismatch_reasons.append("initial_stop_unavailable_after_live_breakeven_mutation")
        if stop_difference is not None and abs(stop_difference) > tick_size:
            mismatch_reasons.append("stop_plan_difference_conversion_or_swing_window")
        if tp1_difference is not None and abs(tp1_difference) > tick_size:
            mismatch_reasons.append("tp1_plan_difference_from_entry_or_stop")
        if tp2_difference is not None and abs(tp2_difference) > tick_size:
            mismatch_reasons.append("tp2_plan_difference_from_entry_or_stop")
        if qty_difference is not None and abs(qty_difference) > 0.000010001:
            mismatch_reasons.append("qty_difference_period_notional_or_fill_price")
        if result is not None and operational_lifecycle and result.lifecycle_class != operational_lifecycle:
            if operational_lifecycle == "TP1_SL" and result.lifecycle_class == "TP1_TP2_TRAILING_STOP":
                mismatch_reasons.append("tp2_touch_difference_conversion_or_target_plan")
            else:
                mismatch_reasons.append("lifecycle_difference_minute_bar_or_execution_timing")
        gross_difference = float(result.gross_pnl_usdc) - operational_gross if result and result.gross_pnl_usdc is not None and operational_gross is not None else None
        net_difference = float(result.net_pnl_usdc) - operational_net if result and result.net_pnl_usdc is not None and operational_net is not None else None
        if gross_difference is not None and abs(gross_difference) > 0.01:
            mismatch_reasons.append("gross_pnl_difference_fill_or_price_path")
        if net_difference is not None and abs(net_difference) > 0.01:
            mismatch_reasons.append("net_pnl_difference_cost_or_fill_model")
        rows.append(
            {
                "trade_key": trade_key,
                "excluded_from_scoring": excluded,
                "candidate_id": result.candidate_id if result else "",
                "candidate_join_status": "MATCHED" if result else "UNMATCHED",
                "entry_plan_match": entry_match,
                "stop_plan_difference_usd": stop_difference,
                "tp1_difference_usd": tp1_difference,
                "tp2_difference_usd": tp2_difference,
                "qty_difference": qty_difference,
                "operational_lifecycle": operational_lifecycle,
                "replay_lifecycle": result.lifecycle_class if result else "",
                "lifecycle_match": result.lifecycle_class == operational_lifecycle if result and operational_lifecycle else None,
                "operational_gross_pnl_usdc": operational_gross,
                "replay_gross_pnl_usdc": result.gross_pnl_usdc if result else None,
                "gross_pnl_difference_usdc": gross_difference,
                "operational_net_pnl_usdc": operational_net,
                "replay_net_pnl_usdc": result.net_pnl_usdc if result else None,
                "net_pnl_difference_usdc": net_difference,
                "mismatch_reason": "|".join(mismatch_reasons),
            }
        )
    return rows
