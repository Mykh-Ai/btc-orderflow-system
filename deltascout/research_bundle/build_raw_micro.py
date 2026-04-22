from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import ScopeInfo
from .select_cases import SelectedCase

WINDOW_MINUTES = 30
RAW_MICRO_FIELDNAMES = [
    "target_ts",
    "Timestamp",
    "minutes_from_target",
    "Close",
    "VWAP",
    "BuyQty",
    "SellQty",
    "OpenInterest",
    "FundingRate",
    "LiqBuyQty",
    "LiqSellQty",
    "IsSynthetic",
    "delta_1m",
    "vol_1m",
    "price_minus_vwap",
]


@dataclass(frozen=True)
class RawMicroBuildResult:
    path: Path
    row_count: int
    missing_case_count: int
    status: str


class RawMicroBuildError(RuntimeError):
    """Raised when raw micro context cannot be built."""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _to_float(value: str) -> float | None:
    if value == "" or value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _format_num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _default_raw_feed_root(scope: ScopeInfo) -> Path:
    return scope.input_root.parent / "raw_feed"


def build_raw_micro(
    scope: ScopeInfo,
    selected_cases: list[SelectedCase],
    raw_feed_root: str | Path | None = None,
) -> RawMicroBuildResult:
    root = Path(raw_feed_root) if raw_feed_root else _default_raw_feed_root(scope)
    out_path = scope.bundle_dir / f"selected_case_raw_feed_micro_{scope.scope_start}_to_{scope.scope_end}.csv"
    rows_out: list[dict[str, str]] = []
    missing_case_count = 0
    feed_cache: dict[str, list[dict[str, str]]] = {}

    for case in sorted(selected_cases, key=lambda item: (_parse_ts(item.target_ts), item.event_type, item.kind)):
        if case.session_date not in feed_cache:
            feed_path = root / f"{case.session_date}.csv"
            feed_cache[case.session_date] = _read_csv_rows(feed_path)
        day_rows = feed_cache[case.session_date]
        if not day_rows:
            missing_case_count += 1
            continue

        target_dt = _parse_ts(case.target_ts)
        window_rows = []
        for row in day_rows:
            ts_value = row.get("Timestamp", "")
            if not ts_value:
                continue
            row_dt = _parse_ts(ts_value)
            minutes_from_target = int((row_dt - target_dt).total_seconds() / 60)
            if -WINDOW_MINUTES <= minutes_from_target <= WINDOW_MINUTES:
                window_rows.append((row_dt, minutes_from_target, row))

        if not window_rows:
            missing_case_count += 1
            continue

        for row_dt, minutes_from_target, row in sorted(window_rows, key=lambda item: (case.target_ts, item[0])):
            buy_qty = _to_float(row.get("BuyQty", ""))
            sell_qty = _to_float(row.get("SellQty", ""))
            close_val = _to_float(row.get("Close", ""))
            vwap_val = _to_float(row.get("VWAP", ""))
            vol_val = _to_float(row.get("Volume", ""))
            delta_1m = None if buy_qty is None or sell_qty is None else buy_qty - sell_qty
            price_minus_vwap = None if close_val is None or vwap_val is None else close_val - vwap_val
            rows_out.append(
                {
                    "target_ts": case.target_ts,
                    "Timestamp": row.get("Timestamp", ""),
                    "minutes_from_target": str(minutes_from_target),
                    "Close": row.get("Close", ""),
                    "VWAP": row.get("VWAP", ""),
                    "BuyQty": row.get("BuyQty", ""),
                    "SellQty": row.get("SellQty", ""),
                    "OpenInterest": row.get("OpenInterest", ""),
                    "FundingRate": row.get("FundingRate", ""),
                    "LiqBuyQty": row.get("LiqBuyQty", ""),
                    "LiqSellQty": row.get("LiqSellQty", ""),
                    "IsSynthetic": row.get("IsSynthetic", ""),
                    "delta_1m": _format_num(delta_1m),
                    "vol_1m": _format_num(vol_val),
                    "price_minus_vwap": _format_num(price_minus_vwap),
                }
            )

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RAW_MICRO_FIELDNAMES)
        writer.writeheader()
        for row in rows_out:
            writer.writerow(row)

    status = "missing"
    if rows_out:
        status = "partial" if missing_case_count else "complete"
    return RawMicroBuildResult(path=out_path, row_count=len(rows_out), missing_case_count=missing_case_count, status=status)
