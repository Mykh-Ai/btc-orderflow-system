#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trail.py
Trailing helper logic extracted from executor.py.

Hard rule: moved functions below are verbatim copies from executor.py.
"""
from contextlib import suppress
import csv
from collections import deque
from typing import Any, Dict, List, Optional, Callable
ENV: Dict[str, Any] = {}
_LOG_EVENT: Optional[Callable[..., None]] = None

# injected dependency from executor.py
read_tail_lines: Optional[Callable[[str, int], List[str]]] = None

AGG_HEADER_V2 = [
    "Timestamp",
    "Trades",
    "TotalQty",
    "AvgSize",
    "BuyQty",
    "SellQty",
    "AvgPrice",
    "ClosePrice",
    "HiPrice",
    "LowPrice",
]


def _norm_col(c: str) -> str:
    return (c or "").replace("\ufeff", "").strip()


def _assert_agg_header_v2(path: str) -> None:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
    if not header:
        raise RuntimeError(f"aggregated.csv empty/missing header: {path}")
    got = [_norm_col(x) for x in header]
    if got != AGG_HEADER_V2:
        raise RuntimeError(
            "aggregated.csv schema mismatch (FAIL-LOUD)\n"
            f"Expected: {AGG_HEADER_V2}\n"
            f"Got:      {got}\n"
            f"File: {path}"
        )


def configure(
    env: Dict[str, Any],
    read_tail_lines_fn: Callable[[str, int], List[str]],
    log_event: Optional[Callable[..., None]] = None,
) -> None:
    global ENV, read_tail_lines, _LOG_EVENT
    ENV = env
    read_tail_lines = read_tail_lines_fn
    _LOG_EVENT = log_event
    ENV.setdefault("TRAIL_CONFIRM_BUFFER_USD", 0.0)


def _log_event(action: str, **fields: Any) -> None:
    if _LOG_EVENT is None:
        return
    _LOG_EVENT(action, **fields)


def _read_last_close_prices_from_agg_csv(path: str, n_rows: int) -> list[float]:
    """
    Read last N ClosePrice values from aggregated.csv (v2 strict schema).
    - FAIL-LOUD on schema mismatch (header != expected v2).
    - Fail-closed (return []) if file is missing/empty (startup/rotation).
    - Malformed data rows are skipped (best-effort tail parsing).
    """
    if int(n_rows or 0) <= 0:
        return []
    n_rows = int(n_rows)
    closes = deque(maxlen=n_rows)
    close_idx = AGG_HEADER_V2.index("ClosePrice")

    # Prefer injected tail reader for performance; fallback to full scan if not provided.
    if read_tail_lines is not None:
        # Important: preserve fail-closed startup behavior when file doesn't exist yet.
        # executor.read_tail_lines typically catches FileNotFoundError and returns [].
        lines = read_tail_lines(path, n_rows + 5)  # a few extra lines for safety
        if not lines:
            return []
        _assert_agg_header_v2(path)
        for ln in lines:
            ln = ln.strip()
            if not ln or ln.startswith("Timestamp"):
                continue
            parts = [p.strip() for p in ln.split(",")]
            if len(parts) != len(AGG_HEADER_V2):
                continue
            try:
                closes.append(float(parts[close_idx]))
            except Exception:
                continue
    else:
        try:
            _assert_agg_header_v2(path)
        except FileNotFoundError:
            return []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if not row:
                    continue
                if len(row) != len(AGG_HEADER_V2):
                    continue
                try:
                    closes.append(float(row[close_idx]))
                except Exception:
                    continue

    return list(closes)



def _find_last_fractal_swing(series: list[float], lr: int, kind: str) -> Optional[float]:
    """
    Find last swing point in series using simple fractal:
      low:  x[i] < x[i-1..i-lr] and x[i] < x[i+1..i+lr]
      high: x[i] > x[i-1..i-lr] and x[i] > x[i+1..i+lr]
    Returns swing price or None.
    """
    if lr < 1:
        lr = 1
    if len(series) < (2 * lr + 1):
        return None
    # scan from right to left so we get the most recent confirmed swing
    # last index we can test is len(series)-lr-1
    for i in range(len(series) - lr - 1, lr - 1, -1):
        x = series[i]
        left = series[i - lr:i]
        right = series[i + 1:i + 1 + lr]
        if len(left) < lr or len(right) < lr:
            continue
        if kind == "low":
            if all(x < v for v in left) and all(x < v for v in right):
                return x
        else:
            if all(x > v for v in left) and all(x > v for v in right):
                return x
    return None



def _trail_desired_stop_from_agg(pos: dict) -> Optional[float]:
    """
    Compute desired trailing stop based on last swing from aggregated.csv ClosePrice.
    LONG: stop = swing_low - buffer
    SHORT: stop = swing_high + buffer
    """
    if pos.get("trail_active") and pos.get("trail_wait_confirm") is True:
        side = pos.get("side")
        if side not in ("LONG", "SHORT"):
            pos["trail_wait_confirm"] = False
            pos["trail_confirmed"] = False
        else:
            ref_price = float(pos.get("trail_ref_price") or 0.0)
            trail_sl_price = float(pos.get("trail_sl_price") or 0.0)
            if ref_price <= 0 or trail_sl_price <= 0:
                pos["trail_wait_confirm"] = False
                pos["trail_confirmed"] = False
            else:
                path = ENV.get("AGG_CSV") or ""
                try:
                    closes = _read_last_close_prices_from_agg_csv(path, 10) if path else []
                except Exception:
                    closes = []
                if not closes:
                    _log_event("TRAIL_CONFIRM_SKIPPED_NO_AGG", side=pos.get("side"), ref=ref_price)
                    return None
                else:
                    last_close = closes[-1]
                    confirm_buf = float(ENV.get("TRAIL_CONFIRM_BUFFER_USD") or 0.0)
                    if side == "LONG":
                        confirmed = last_close > ref_price + confirm_buf
                    else:
                        confirmed = last_close < ref_price - confirm_buf
                    if not confirmed:
                        return None
                    pos["trail_wait_confirm"] = False
                    pos["trail_confirmed"] = True
                    _log_event(
                        "TRAIL_CONFIRM_BREAK",
                        side=side,
                        ref=ref_price,
                        last_close=last_close,
                        buffer=confirm_buf,
                    )
    path = ENV.get("AGG_CSV") or ""
    if not path:
        return None
    lookback = int(ENV.get("TRAIL_SWING_LOOKBACK") or 0)
    lr = int(ENV.get("TRAIL_SWING_LR") or 2)
    buf = float(ENV.get("TRAIL_SWING_BUFFER_USD") or 0.0)
    closes = _read_last_close_prices_from_agg_csv(path, lookback)
    if not closes:
        return None
    kind = "low" if pos.get("side") == "LONG" else "high"
    swing = _find_last_fractal_swing(closes, lr=lr, kind=kind)
    if swing is None:
        return None
    if pos.get("side") == "LONG":
        return float(swing - buf)
    else:
        return float(swing + buf)
