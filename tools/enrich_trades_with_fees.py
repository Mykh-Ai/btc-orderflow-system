#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline fee enrichment for TradeReportInternal (Policy A, strict).

Reads:  /data/reports/trades.jsonl
Writes: /data/reports/trades_enriched.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from executor_mod import binance_api

INPUT_PATH_DEFAULT = "/data/reports/trades.jsonl"
OUTPUT_PATH_DEFAULT = "/data/reports/trades_enriched.jsonl"
TMP_SUFFIX = ".tmp"


def _load_env() -> Dict[str, Any]:
    return {
        "BINANCE_API_KEY": os.getenv("BINANCE_API_KEY", ""),
        "BINANCE_API_SECRET": os.getenv("BINANCE_API_SECRET", ""),
        "BINANCE_BASE_URL": os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
        "BINANCE_API_BASES": os.getenv("BINANCE_API_BASES", ""),
        "RECV_WINDOW": int(os.getenv("RECV_WINDOW", "5000")),
        "TRADE_MODE": os.getenv("TRADE_MODE", "spot"),
        "MARGIN_ISOLATED": os.getenv("MARGIN_ISOLATED", "FALSE"),
    }


def _split_symbol_guess(symbol: str) -> Tuple[str, str]:
    s = (symbol or "").strip().upper()
    suffixes = (
        "USDT",
        "USDC",
        "FDUSD",
        "BUSD",
        "TUSD",
        "USDP",
        "DAI",
        "BTC",
        "ETH",
        "BNB",
    )
    for suf in suffixes:
        if s.endswith(suf) and len(s) > len(suf):
            return s[:-len(suf)], suf
    return s, ""


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _read_jsonl(path: str) -> Tuple[List[Dict[str, Any]], int]:
    records: List[Dict[str, Any]] = []
    skipped = 0
    if not os.path.exists(path):
        return records, skipped
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                skipped += 1
    return records, skipped


def _write_jsonl(path: str, records: List[Dict[str, Any]]) -> None:
    tmp = path + TMP_SUFFIX
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


def _append_note(rec: Dict[str, Any], note: str) -> None:
    if not note:
        return
    prev = rec.get("reconciliation_notes")
    if not prev:
        rec["reconciliation_notes"] = note
        return
    if note in str(prev):
        return
    rec["reconciliation_notes"] = f"{prev}; {note}"


def _fetch_trades_with_retry(symbol: str, order_id: int, retries: int = 3) -> List[Dict[str, Any]]:
    delay = 0.5
    last_err: Optional[str] = None
    for _ in range(max(1, retries)):
        try:
            return binance_api.my_trades(symbol, order_id=order_id, limit=1000)
        except Exception as exc:
            last_err = str(exc)
            time.sleep(delay)
            delay = min(delay * 2.0, 5.0)
    raise RuntimeError(last_err or "my_trades_failed")


def _sum_commission_quote(trades: List[Dict[str, Any]], quote_asset: str) -> Tuple[Optional[float], Optional[str]]:
    total = 0.0
    seen = False
    for tr in trades:
        if not isinstance(tr, dict):
            continue
        asset = str(tr.get("commissionAsset") or "").upper()
        if asset and asset != quote_asset:
            return None, "commission_asset_mismatch"
        commission = _safe_float(tr.get("commission"))
        if commission is None:
            continue
        total += commission
        seen = True
    if not seen:
        return None, "no_commission"
    return total, None


def _compute_exit_quote_total(rec: Dict[str, Any]) -> Optional[float]:
    val = _safe_float(rec.get("exit_quote_total"))
    if val is not None:
        return val
    exit_leg_orders = rec.get("exit_leg_orders") or {}
    total = 0.0
    seen = False
    for leg in ("tp1", "tp2", "sl", "trail"):
        leg_data = exit_leg_orders.get(leg)
        if not isinstance(leg_data, dict):
            continue
        leg_val = _safe_float(leg_data.get("cummulativeQuoteQty"))
        if leg_val is None:
            continue
        total += leg_val
        seen = True
    return total if seen else None


def _leg_is_filled(leg_data: Dict[str, Any]) -> bool:
    executed_qty = _safe_float(leg_data.get("executedQty"))
    if executed_qty is not None and executed_qty > 0:
        return True
    quote_qty = _safe_float(leg_data.get("cummulativeQuoteQty"))
    if quote_qty is not None and quote_qty > 0:
        return True
    status = str(leg_data.get("status") or "").upper()
    return status == "FILLED"


def _enrich_record(rec: Dict[str, Any], cache: Dict[Tuple[str, int], List[Dict[str, Any]]]) -> Dict[str, Any]:
    rec = dict(rec)
    symbol = str(rec.get("symbol") or "").upper()
    _, quote_asset = _split_symbol_guess(symbol)
    exit_leg_orders = rec.get("exit_leg_orders") or {}
    if not isinstance(exit_leg_orders, dict):
        exit_leg_orders = {}
        rec["exit_leg_orders"] = exit_leg_orders

    fees_total_quote: Optional[float] = 0.0
    fees_allowed = True
    had_leg = False
    filled_exit_legs = 0
    for leg in ("tp1", "tp2", "sl", "trail"):
        leg_data = exit_leg_orders.get(leg)
        if not isinstance(leg_data, dict):
            continue
        order_id = leg_data.get("orderId")
        if order_id in (None, 0, "", "0"):
            continue
        had_leg = True
        if not _leg_is_filled(leg_data):
            leg_data["feeQuote"] = 0.0
            _append_note(rec, f"skip_fee_leg_{leg}_unfilled")
            continue
        filled_exit_legs += 1
        oid = int(order_id)
        cache_key = (symbol, oid)
        trades = cache.get(cache_key)
        if trades is None:
            trades = _fetch_trades_with_retry(symbol, oid)
            cache[cache_key] = trades
        fee, fee_err = _sum_commission_quote(trades, quote_asset)
        if fee_err:
            fees_allowed = False
            leg_data["feeQuote"] = None
            if fee_err == "no_commission":
                _append_note(rec, f"fee_{leg}_missing_commission_on_filled_leg")
            else:
                _append_note(rec, f"fee_{leg}_{fee_err}")
        else:
            leg_data["feeQuote"] = fee
            fees_total_quote = (fees_total_quote or 0.0) + float(fee or 0.0)

    if had_leg and filled_exit_legs == 0:
        rec["fees_total_quote"] = None
        rec["pnl_quote"] = None
        rec["roi_pct"] = None
        _append_note(rec, "pnl_blocked_no_filled_exit")
        return rec

    if not had_leg:
        fees_allowed = False
        _append_note(rec, "no_exit_legs")

    if not fees_allowed:
        rec["fees_total_quote"] = None
        rec["pnl_quote"] = None
        rec["roi_pct"] = None
        return rec

    rec["fees_total_quote"] = fees_total_quote
    entry_price = _safe_float(rec.get("entry_price"))
    qty_base_total = _safe_float(rec.get("qty_base_total"))
    exit_quote_total = _compute_exit_quote_total(rec)
    if entry_price is None or qty_base_total is None or exit_quote_total is None:
        rec["pnl_quote"] = None
        rec["roi_pct"] = None
        _append_note(rec, "pnl_missing_inputs")
        return rec

    entry_cost = float(entry_price) * float(qty_base_total)
    side = str(rec.get("side") or "").upper()
    if side == "SHORT":
        gross = entry_cost - float(exit_quote_total)
    else:
        gross = float(exit_quote_total) - entry_cost
    pnl_quote = gross - float(fees_total_quote or 0.0)
    rec["pnl_quote"] = pnl_quote
    rec["roi_pct"] = (pnl_quote / entry_cost) * 100.0 if entry_cost > 0 else None
    return rec


def _load_existing_output(path: str) -> Dict[str, Dict[str, Any]]:
    existing: Dict[str, Dict[str, Any]] = {}
    if not os.path.exists(path):
        return existing
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            report_id = rec.get("report_id")
            if report_id:
                existing[report_id] = rec
    return existing


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich TradeReportInternal with fees via myTrades.")
    parser.add_argument("--input", default=INPUT_PATH_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_PATH_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = _load_env()
    binance_api.configure(env)

    records, skipped = _read_jsonl(args.input)
    existing = _load_existing_output(args.output) if args.output else {}
    cache: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}

    enriched: List[Dict[str, Any]] = []
    pnl_ok = 0
    for rec in records:
        report_id = rec.get("report_id")
        if report_id and report_id in existing:
            out_rec = existing[report_id]
        else:
            try:
                out_rec = _enrich_record(rec, cache)
            except Exception as exc:
                out_rec = dict(rec)
                out_rec["fees_total_quote"] = None
                out_rec["pnl_quote"] = None
                out_rec["roi_pct"] = None
                _append_note(out_rec, f"enrich_error:{exc}")
        if out_rec.get("pnl_quote") is not None:
            pnl_ok += 1
        enriched.append(out_rec)

    if not args.dry_run:
        _write_jsonl(args.output, enriched)

    print(f"input_records={len(records)}")
    print(f"enriched_records={len(enriched)}")
    print(f"pnl_non_null={pnl_ok}")
    print(f"invalid_json_skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
