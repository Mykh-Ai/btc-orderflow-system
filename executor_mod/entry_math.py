"""Entry sizing and price decision helpers extracted from executor.py."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from executor_mod.risk_math import ceil_to_step, floor_to_step


ENV: Dict[str, Any] = {}


def configure(env: Dict[str, Any]) -> None:
    global ENV
    ENV = env


def build_entry_price(kind: str, close_price: float) -> float:
    """Entry price builder used for live.

    For breakout-style entries:
      - long  -> above close
      - short -> below close

    Rounding is *directional* so we don't accidentally make the trigger harder by rounding.
    """
    raw = close_price + ENV["ENTRY_OFFSET_USD"] if kind == "long" else close_price - ENV["ENTRY_OFFSET_USD"]

    if kind == "long":
        # keep it above close by at least 1 tick
        raw = max(raw, close_price + float(ENV["TICK_SIZE"]))
        return floor_to_step(raw, ENV["TICK_SIZE"])
    else:
        # keep it below close by at least 1 tick
        raw = min(raw, close_price - float(ENV["TICK_SIZE"]))
        return ceil_to_step(raw, ENV["TICK_SIZE"])


def notional_to_qty(entry: float, usd: float) -> float:
    if entry <= 0:
        return 0.0
    qty = usd / entry
    qty = floor_to_step(qty, ENV["QTY_STEP"])
    return qty


def validate_qty(qty: float, entry: float) -> bool:
    if qty <= 0:
        return False
    if Decimal(str(qty)) < ENV["MIN_QTY"]:
        return False
    if qty * entry < ENV["MIN_NOTIONAL"]:
        return False
    return True


def swing_stop_far(df: Any, i: int, side: str, entry: float) -> float:
    """Return a stop that is FARTHER from entry (vs near).

    side: BUY for long, SELL for short

    - BUY: choose min(pct_sl, swing_low)
    - SELL: choose max(pct_sl, swing_high)
    - swings are based on LowPrice/HiPrice when available (v2), else fall back to price.
    """
    pct_sl = entry * (1 - ENV["SL_PCT"]) if side == "BUY" else entry * (1 + ENV["SL_PCT"])

    if i < 0 or i >= len(df):
        sl = pct_sl
    else:
        lookback = df.iloc[max(0, i - ENV["SWING_MINS"]): i + 1]
        if side == "BUY":
            swing_col = "LowPrice" if "LowPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.min())
            sl = min(pct_sl, swing)
        else:
            swing_col = "HiPrice" if "HiPrice" in lookback.columns else "price"
            s = lookback[swing_col].dropna()
            if s.empty:
                s = lookback["price"].dropna()
            swing = pct_sl if s.empty else float(s.max())
            sl = max(pct_sl, swing)

    # Safety: enforce correct side and rounding
    if side == "BUY":
        sl = min(sl, entry - float(ENV["TICK_SIZE"]))
    else:
        sl = max(sl, entry + float(ENV["TICK_SIZE"]))

    return floor_to_step(sl, ENV["TICK_SIZE"]) if side == "BUY" else ceil_to_step(sl, ENV["TICK_SIZE"])


def compute_tps(entry: float, sl: float, side: str) -> List[float]:
    """TP list based on the *real* risk (entry <-> SL).

    Rounding is directional:
      - BUY (long): TP rounded down (slightly easier to hit)
      - SELL (short): TP rounded up (slightly easier to hit)
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return []

    tps: List[float] = []
    for rmult in ENV["TP_R_LIST"]:
        if side == "BUY":
            tp_raw = entry + rmult * risk
            tp = floor_to_step(tp_raw, ENV["TICK_SIZE"])
        else:
            tp_raw = entry - rmult * risk
            tp = ceil_to_step(tp_raw, ENV["TICK_SIZE"])
        tps.append(tp)
    return tps


def _planb_market_allowed(posi: Dict[str, Any], px_exec: float) -> Tuple[bool, str, Dict[str, Any]]:
    """Guard against chasing far away from planned entry.
    Returns (allowed, reason, info).
    """
    try:
        prices = posi.get("prices") or {}
        entry = float(prices.get("entry"))
        sl = float(prices.get("sl"))
        tp1 = float(prices.get("tp1"))
    except Exception:
        return False, "bad_prices", {}
    if not (math.isfinite(entry) and math.isfinite(sl) and entry > 0 and sl > 0):
        return False, "bad_prices", {"entry": entry, "sl": sl}

    risk = abs(entry - sl)
    r_mult = float(ENV.get("PLANB_MAX_DEV_R_MULT") or 0.0)
    max_usd = float(ENV.get("PLANB_MAX_DEV_USD") or 0.0)
    max_dev = max(risk * r_mult, max_usd) if max_usd > 0 else risk * r_mult

    dev = abs(px_exec - entry)
    info = {"px_exec": px_exec, "entry": entry, "sl": sl, "risk": risk, "dev": dev, "max_dev": max_dev}

    if max_dev > 0 and dev > max_dev:
        return False, "deviation_too_large", info

    if ENV.get("PLANB_ABORT_IF_PAST_TP1", True):
        side_txt = str(posi.get("side") or "").upper()
        if math.isfinite(tp1) and tp1 > 0:
            if side_txt == "LONG" and px_exec >= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info
            if side_txt == "SHORT" and px_exec <= tp1:
                info["tp1"] = tp1
                return False, "past_tp1", info

    return True, "ok", info


class InitialStopSelectionError(RuntimeError):
    """A candidate cannot satisfy the frozen V8 initial-stop contract."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)

@dataclass(frozen=True)
class InitialSwingSelection:
    stop_usdt: float
    swing_ts: datetime
    swing_price_usdt: float
    swing_volume: float
    eligible_count: int
    confirmed_count: int
    window_gap_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": str(ENV.get("INITIAL_STOP_POLICY") or ""),
            "stop_usdt": self.stop_usdt,
            "swing_ts": self.swing_ts.isoformat(),
            "swing_price_usdt": self.swing_price_usdt,
            "swing_volume": self.swing_volume,
            "eligible_count": self.eligible_count,
            "confirmed_count": self.confirmed_count,
            "window_gap_count": self.window_gap_count,
        }

def _initial_stop_from_swing_usdt(side: str, entry_usdt: float, swing_price_usdt: float) -> float:
    """Apply the structural buffer and the existing 0.2% far-stop floor."""

    pct_stop = (
        float(Decimal(str(entry_usdt)) * (1 - Decimal(str(ENV["SL_PCT"]))))
        if side == "BUY"
        else float(Decimal(str(entry_usdt)) * (1 + Decimal(str(ENV["SL_PCT"]))))
    )
    buffer_usd = float(ENV["INITIAL_SWING_BUFFER_USD"])
    tick = ENV["TICK_SIZE"]
    tick_f = float(tick)
    if side == "BUY":
        stop = min(pct_stop, float(Decimal(str(swing_price_usdt)) - Decimal(str(buffer_usd))), float(Decimal(str(entry_usdt)) - Decimal(str(tick_f))))
        return floor_to_step(stop, tick)
    if side == "SELL":
        stop = max(pct_stop, float(Decimal(str(swing_price_usdt)) + Decimal(str(buffer_usd))), float(Decimal(str(entry_usdt)) + Decimal(str(tick_f))))
        return ceil_to_step(stop, tick)
    raise InitialStopSelectionError("INVALID_SIDE", str(side))

def select_volume_confirmed_initial_stop(
    df: pd.DataFrame,
    signal_index: int,
    side: str,
    entry_usdt: float,
) -> InitialSwingSelection:
    """Select the highest-volume confirmed 25/25 swing in the prior 24 hours."""

    policy = str(ENV.get("INITIAL_STOP_POLICY") or "").strip().upper()
    if policy != "VOLUME_SWING_24H_LR25":
        raise InitialStopSelectionError("UNSUPPORTED_INITIAL_STOP_POLICY", policy)

    lookback = int(ENV["INITIAL_SWING_LOOKBACK"])
    lr = int(ENV["INITIAL_SWING_LR"])
    if lookback <= 0 or lr <= 0 or lookback < 2 * lr + 1:
        raise InitialStopSelectionError(
            "INVALID_INITIAL_STOP_CONFIG",
            f"lookback={lookback} lr={lr}",
        )
    if signal_index < 0 or signal_index >= len(df):
        raise InitialStopSelectionError("MISSING_EXACT_SIGNAL_MINUTE")

    start = signal_index + 1 - lookback
    if start < 0:
        raise InitialStopSelectionError(
            "NO_FULL_INITIAL_SWING_WINDOW",
            f"bars={signal_index + 1} required={lookback}",
        )
    window = df.iloc[start:signal_index + 1].copy()
    if bool(ENV.get("INITIAL_SWING_REQUIRE_FULL_WINDOW", True)) and len(window) != lookback:
        raise InitialStopSelectionError(
            "NO_FULL_INITIAL_SWING_WINDOW",
            f"bars={len(window)} required={lookback}",
        )

    required = {
        "Timestamp",
        "low_usdt",
        "high_usdt",
        "volume_1m",
        "swing_row_real",
    }
    missing = sorted(required.difference(window.columns))
    if missing:
        raise InitialStopSelectionError("INITIAL_SWING_SCHEMA_MISSING", ",".join(missing))

    timestamps = pd.to_datetime(window["Timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise InitialStopSelectionError("INVALID_INITIAL_SWING_TIMESTAMPS")
    deltas = timestamps.diff().dropna().dt.total_seconds()
    window_gap_count = int(deltas.ne(60.0).sum())
    rows = window.reset_index(drop=True)
    confirmed_count = 0
    eligible: list[tuple[float, datetime, float, float]] = []
    cap = float(ENV["INITIAL_SWING_MAX_DISTANCE_USD"])

    for index in range(lr, len(rows) - lr):
        neighborhood = rows.iloc[index - lr:index + lr + 1]
        if not bool(neighborhood["swing_row_real"].all()):
            continue
        row = rows.iloc[index]
        if side == "BUY":
            swing_price = float(row["low_usdt"])
            if swing_price >= entry_usdt:
                continue
            comparisons = neighborhood["low_usdt"].tolist()
            center = comparisons.pop(lr)
            is_swing = all(center < float(value) for value in comparisons)
        elif side == "SELL":
            swing_price = float(row["high_usdt"])
            if swing_price <= entry_usdt:
                continue
            comparisons = neighborhood["high_usdt"].tolist()
            center = comparisons.pop(lr)
            is_swing = all(center > float(value) for value in comparisons)
        else:
            raise InitialStopSelectionError("INVALID_SIDE", str(side))
        if not is_swing:
            continue

        confirmed_count += 1
        stop_usdt = _initial_stop_from_swing_usdt(side, entry_usdt, swing_price)
        if cap > 0 and abs(entry_usdt - stop_usdt) > cap:
            continue
        swing_ts = pd.Timestamp(row["Timestamp"])
        if swing_ts.tzinfo is None:
            swing_ts = swing_ts.tz_localize("UTC")
        else:
            swing_ts = swing_ts.tz_convert("UTC")
        eligible.append(
            (
                float(row["volume_1m"]),
                swing_ts.to_pydatetime(),
                swing_price,
                stop_usdt,
            )
        )

    if not eligible:
        reason = "NO_SWING_WITHIN_INITIAL_STOP_CAP" if confirmed_count else "NO_CONFIRMED_VOLUME_SWING"
        raise InitialStopSelectionError(reason, f"confirmed={confirmed_count} cap={cap}")

    swing_volume, swing_ts, swing_price, stop_usdt = max(
        eligible,
        key=lambda item: (item[0], item[1]),
    )
    return InitialSwingSelection(
        stop_usdt=stop_usdt,
        swing_ts=swing_ts,
        swing_price_usdt=swing_price,
        swing_volume=swing_volume,
        eligible_count=len(eligible),
        confirmed_count=confirmed_count,
        window_gap_count=window_gap_count,
    )
