#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""trail.py
Trailing helper logic extracted from executor.py.

Hard rule: moved functions below are verbatim copies from executor.py.
"""
from contextlib import suppress
from typing import Any, Dict, List, Optional, Callable
ENV: Dict[str, Any] = {}

# injected dependency from executor.py
read_tail_lines: Optional[Callable[[str, int], List[str]]] = None


def configure(env: Dict[str, Any], read_tail_lines_fn: Callable[[str, int], List[str]]) -> None:
    global ENV, read_tail_lines
    ENV = env
    read_tail_lines = read_tail_lines_fn


def _read_last_close_prices_from_agg_csv(path: str, n_rows: int) -> list[float]:
    """
    Read last N rows from aggregated.csv and extract ClosePrice (fallback to AvgPrice).
    CSV header expected (example): Timestamp,Trades,TotalQty,AvgSize,BuyQty,SellQty,AvgPrice,ClosePrice
    """
    if n_rows <= 0:
        return []
    # Read tail lines (avoid loading full file)
    lines = read_tail_lines(path, n_rows + 5)  # header + a few extra
    if not lines:
        return []
    # Find header
    header_idx = None
    for i, ln in enumerate(lines):
        if "Timestamp" in ln and "ClosePrice" in ln:
            header_idx = i
            break
    # If no header in tail, assume fixed order and parse from all lines
    data_lines = lines[header_idx + 1:] if header_idx is not None else lines
    closes: list[float] = []
    for ln in data_lines:
        ln = ln.strip()
        if not ln or ln.startswith("Timestamp"):
            continue
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 7:
            continue
        # try ClosePrice last col (idx 7) if present
        v = None
        if len(parts) >= 8:
            v = parts[7]
        else:
            v = parts[6]  # AvgPrice
        try:
            closes.append(float(v))
        except Exception:
            continue
    return closes



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