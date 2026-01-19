#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate manager report from enriched trades (offline, cron-safe)."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

INPUT_PATH_DEFAULT = "/data/reports/trades_enriched.jsonl"
OUTPUT_PATH_DEFAULT = "/data/reports/manager_report.md"
TMP_SUFFIX = ".tmp"


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


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


def _format_number(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1:
        return f"{val:.4f}"
    return f"{val:.8f}"


def _format_bool(val: Any) -> str:
    if val is None:
        return "N/A"
    return "true" if bool(val) else "false"


def _record_date(rec: Dict[str, Any]) -> Optional[str]:
    closed_at = rec.get("closed_at")
    dt = _parse_iso(closed_at) if closed_at else None
    if dt:
        return dt.date().isoformat()
    date = rec.get("date")
    if isinstance(date, str) and date:
        return date
    return None


def _record_month(rec: Dict[str, Any]) -> Optional[str]:
    closed_at = rec.get("closed_at")
    dt = _parse_iso(closed_at) if closed_at else None
    if dt:
        return dt.strftime("%Y-%m")
    date = rec.get("date")
    if isinstance(date, str) and len(date) >= 7:
        return date[:7]
    return None


def _write_markdown(path: str, content: str) -> None:
    tmp = path + TMP_SUFFIX
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def _summarize(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "trades_total": 0,
        "trades_with_pnl": 0,
        "pnl_sum_quote": 0.0,
        "fees_sum_quote": 0.0,
        "tp1_hits": 0,
        "tp2_hits": 0,
        "entry_cost_sum": 0.0,
    })
    for rec in records:
        month = _record_month(rec) or "N/A"
        data = summary[month]
        data["trades_total"] += 1

        if bool(rec.get("tp1_hit")):
            data["tp1_hits"] += 1
        if bool(rec.get("tp2_hit")):
            data["tp2_hits"] += 1

        pnl = _safe_float(rec.get("pnl_quote"))
        if pnl is not None:
            data["trades_with_pnl"] += 1
            data["pnl_sum_quote"] += pnl
            entry_price = _safe_float(rec.get("entry_price"))
            qty = _safe_float(rec.get("qty_base_total"))
            if entry_price is not None and qty is not None:
                entry_cost = entry_price * qty
                if entry_cost > 0:
                    data["entry_cost_sum"] += entry_cost

        if pnl is not None:
            fees = _safe_float(rec.get("fees_total_quote"))
            if fees is not None:
                data["fees_sum_quote"] += fees
    return summary


def _build_markdown(records: List[Dict[str, Any]], input_path: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = _summarize(records)
    lines: List[str] = []
    lines.append(f"# Manager Report")
    lines.append("")
    lines.append(f"- Generated (UTC): {now}")
    lines.append(f"- Input: {input_path}")
    lines.append("")
    lines.append("## Monthly Summary")
    lines.append("")
    lines.append("| month | trades_total | trades_with_pnl | pnl_sum_quote | roi_weighted_pct | fees_sum_quote | tp1_hit_rate | tp2_hit_rate |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")

    for month in sorted(summary.keys()):
        data = summary[month]
        trades_total = data["trades_total"]
        trades_with_pnl = data["trades_with_pnl"]
        pnl_sum = data["pnl_sum_quote"] if trades_with_pnl else None
        fees_sum = data["fees_sum_quote"] if trades_with_pnl else None
        entry_cost_sum = data["entry_cost_sum"]
        roi_weighted = None
        if trades_with_pnl and entry_cost_sum > 0:
            roi_weighted = (data["pnl_sum_quote"] / entry_cost_sum) * 100.0
        tp1_rate = (data["tp1_hits"] / trades_total * 100.0) if trades_total else None
        tp2_rate = (data["tp2_hits"] / trades_total * 100.0) if trades_total else None

        lines.append(
            "| {month} | {trades_total} | {trades_with_pnl} | {pnl_sum} | {roi_weighted} | {fees_sum} | {tp1_rate} | {tp2_rate} |".format(
                month=month,
                trades_total=trades_total,
                trades_with_pnl=trades_with_pnl,
                pnl_sum=_format_number(pnl_sum),
                roi_weighted=_format_number(roi_weighted),
                fees_sum=_format_number(fees_sum),
                tp1_rate=_format_number(tp1_rate),
                tp2_rate=_format_number(tp2_rate),
            )
        )

    lines.append("")
    lines.append("## Trades Detail")
    lines.append("")
    lines.append("| date | symbol | side | qty_base_total | entry_price | avg_exit_price | fees_total_quote | pnl_quote | roi_pct | exit_type | tp1_hit | tp2_hit |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    def sort_key(rec: Dict[str, Any]) -> str:
        closed_at = rec.get("closed_at")
        dt = _parse_iso(closed_at) if closed_at else None
        if dt:
            return dt.isoformat()
        date = rec.get("date")
        if isinstance(date, str):
            return date
        return ""

    for rec in sorted(records, key=sort_key):
        date = _record_date(rec) or "N/A"
        lines.append(
            "| {date} | {symbol} | {side} | {qty} | {entry} | {avg_exit} | {fees} | {pnl} | {roi} | {exit_type} | {tp1} | {tp2} |".format(
                date=date,
                symbol=rec.get("symbol") or "N/A",
                side=rec.get("side") or "N/A",
                qty=_format_number(_safe_float(rec.get("qty_base_total"))),
                entry=_format_number(_safe_float(rec.get("entry_price"))),
                avg_exit=_format_number(_safe_float(rec.get("avg_exit_price"))),
                fees=_format_number(_safe_float(rec.get("fees_total_quote"))),
                pnl=_format_number(_safe_float(rec.get("pnl_quote"))),
                roi=_format_number(_safe_float(rec.get("roi_pct"))),
                exit_type=rec.get("exit_type") or "N/A",
                tp1=_format_bool(rec.get("tp1_hit")),
                tp2=_format_bool(rec.get("tp2_hit")),
            )
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate manager report from enriched trade reports.")
    parser.add_argument("--input", default=INPUT_PATH_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_PATH_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records, skipped = _read_jsonl(args.input)
    summary = _summarize(records)
    total_pnl_rows = sum(data["trades_with_pnl"] for data in summary.values())
    total_pnl_sum = sum(data["pnl_sum_quote"] for data in summary.values()) if total_pnl_rows else None

    if args.dry_run:
        for month in sorted(summary.keys()):
            data = summary[month]
            print(
                f"{month}: trades_total={data['trades_total']} trades_with_pnl={data['trades_with_pnl']} pnl_sum={_format_number(data['pnl_sum_quote'])}"
            )
    else:
        content = _build_markdown(records, args.input)
        _write_markdown(args.output, content)

    print(f"input_records={len(records)}")
    print(f"months_found={len(summary)}")
    print(f"total_pnl_rows={total_pnl_rows}")
    print(f"total_pnl_sum={_format_number(total_pnl_sum)}")
    print(f"invalid_json_skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
