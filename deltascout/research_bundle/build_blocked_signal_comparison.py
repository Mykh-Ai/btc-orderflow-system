"""Compare the protected 2026-08-18 long with the two blocked 2026-08-19 longs."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MATERIAL = ROOT / "deltascout" / "research_material"
SERVER_FEED = MATERIAL / "server_feed_snapshot" / "2026-08-20"
OUTPUT_JSON = MATERIAL / "shadow_verdicts" / "2026-08-19_blocked_signal_comparison.json"
OUTPUT_MD = MATERIAL / "shadow_verdicts" / "2026-08-19_blocked_signal_comparison.md"


SIGNALS = [
    {
        "name": "protected_2026-08-18",
        "cutoff_utc": "2026-08-18 14:30:00",
        "signal_local": "2026-08-18 16:30:00",
        "price": 65010.090869,
        "event_delta": 97.51,
        "event_volume": 177.98,
        "event_imbalance": 0.548,
        "vwap": 64232.0,
        "poc": 64200.0,
        "actual_entry": 64943.67,
        "initial_stop": 63989.78,
        "tp1": 65953.79,
        "tp2": 66935.79,
        "final_trail": 69110.0,
        "actual_gross_pnl_usdc": 110.3239845,
        "verdict": "REJECT",
        "confidence": 0.74,
        "outcome": "TP1_TP2_TRAILING_PROFIT",
    },
    {
        "name": "blocked_2026-08-19_1435",
        "cutoff_utc": "2026-08-19 12:35:00",
        "signal_local": "2026-08-19 14:35:00",
        "price": 64615.983359,
        "event_delta": 48.58,
        "event_volume": 82.21,
        "event_imbalance": 0.591,
        "vwap": 64505.0,
        "poc": 64340.0,
        "verdict": "REJECT",
        "confidence": 0.74,
        "outcome": "HYPOTHETICAL_BLOCKED",
    },
    {
        "name": "blocked_2026-08-19_1438",
        "cutoff_utc": "2026-08-19 12:38:00",
        "signal_local": "2026-08-19 14:38:00",
        "price": 64697.801317,
        "event_delta": 52.22,
        "event_volume": 83.83,
        "event_imbalance": 0.623,
        "vwap": 64507.0,
        "poc": 64340.0,
        "verdict": "REJECT",
        "confidence": 0.72,
        "outcome": "HYPOTHETICAL_BLOCKED",
    },
]


def _number(value: Any) -> float:
    return float(value)


def _load_rows() -> list[dict[str, Any]]:
    paths = [
        MATERIAL / "effective_feed" / "2026-08-18.csv",
        SERVER_FEED / "2026-08-19.csv",
        SERVER_FEED / "2026-08-20.csv",
    ]
    by_ts: dict[datetime, dict[str, Any]] = {}
    for path in paths:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                ts = datetime.fromisoformat(raw["Timestamp"])
                by_ts[ts] = {
                    "ts": ts,
                    "open": _number(raw["Open"]),
                    "high": _number(raw["High"]),
                    "low": _number(raw["Low"]),
                    "close": _number(raw["Close"]),
                    "volume": _number(raw["Volume"]),
                    "buy": _number(raw["BuyQty"]),
                    "sell": _number(raw["SellQty"]),
                    "oi": _number(raw["OpenInterest"]),
                    "funding": _number(raw["FundingRate"]),
                    "liq_buy": _number(raw["LiqBuyQty"]),
                    "liq_sell": _number(raw["LiqSellQty"]),
                }
    return [by_ts[key] for key in sorted(by_ts)]


def _window(rows: list[dict[str, Any]], cutoff: datetime, minutes: int) -> list[dict[str, Any]]:
    start = cutoff - timedelta(minutes=minutes - 1)
    return [row for row in rows if start <= row["ts"] <= cutoff][-minutes:]


def _window_metrics(rows: list[dict[str, Any]], cutoff: datetime, minutes: int) -> dict[str, Any]:
    window = _window(rows, cutoff, minutes)
    total = sum(row["volume"] for row in window)
    delta = sum(row["buy"] - row["sell"] for row in window)
    return {
        "rows": len(window),
        "start": window[0]["ts"].isoformat(sep=" ") if window else None,
        "end": window[-1]["ts"].isoformat(sep=" ") if window else None,
        "price_change_pct": ((window[-1]["close"] / window[0]["open"]) - 1.0) * 100.0 if window else None,
        "total_volume": total,
        "directional_delta": delta,
        "delta_pct": delta / total if total else None,
        "oi_change": window[-1]["oi"] - window[0]["oi"] if window else None,
        "high": max(row["high"] for row in window) if window else None,
        "low": min(row["low"] for row in window) if window else None,
        "liq_buy": sum(row["liq_buy"] for row in window),
        "liq_sell": sum(row["liq_sell"] for row in window),
    }


def _floor_cent(value: float) -> float:
    return math.floor(value * 100.0 + 1e-8) / 100.0


def _first_hit(rows: list[dict[str, Any]], cutoff: datetime, level: float, kind: str) -> str | None:
    for row in rows:
        if row["ts"] < cutoff:
            continue
        if kind == "up" and row["high"] >= level:
            return row["ts"].isoformat(sep=" ")
        if kind == "down" and row["low"] <= level:
            return row["ts"].isoformat(sep=" ")
    return None


def _last_fractal_low(values: list[float], lr: int = 2) -> float | None:
    for index in range(len(values) - lr - 1, lr - 1, -1):
        value = values[index]
        if all(value < other for other in values[index - lr:index]) and all(
            value < other for other in values[index + 1:index + 1 + lr]
        ):
            return value
    return None


def _simulate_minute_trail(
    rows: list[dict[str, Any]], cutoff: datetime, horizon: datetime, tp2: float, entry: float, risk: float
) -> dict[str, Any]:
    eligible = [row for row in rows if cutoff <= row["ts"] <= horizon]
    activation_index = next((index for index, row in enumerate(eligible) if row["high"] >= tp2), None)
    if activation_index is None:
        return {"activated": False}

    history = [row for row in rows if row["ts"] <= eligible[activation_index]["ts"]][-240:]
    swing = _last_fractal_low([row["low"] for row in history])
    current_stop = swing - 15.0 if swing is not None else entry
    activation_stop = current_stop
    updates = 0
    for row in eligible[activation_index + 1:]:
        if row["low"] <= current_stop:
            return {
                "activated": True,
                "activation_ts_utc": eligible[activation_index]["ts"].isoformat(sep=" "),
                "activation_stop": activation_stop,
                "exit_ts_utc": row["ts"].isoformat(sep=" "),
                "exit_stop": current_stop,
                "third_leg_r": (current_stop - entry) / risk,
                "updates": updates,
                "simulation_contract": "minute_bar_fractal_lr2_lookback240_buffer15_step20",
            }
        history.append(row)
        history = history[-240:]
        swing = _last_fractal_low([item["low"] for item in history])
        desired = swing - 15.0 if swing is not None else None
        if desired is not None and desired >= current_stop + 20.0:
            current_stop = desired
            updates += 1
    return {
        "activated": True,
        "activation_ts_utc": eligible[activation_index]["ts"].isoformat(sep=" "),
        "activation_stop": activation_stop,
        "exit_ts_utc": None,
        "exit_stop": current_stop,
        "third_leg_r": None,
        "updates": updates,
        "simulation_contract": "minute_bar_fractal_lr2_lookback240_buffer15_step20",
    }


def _blocked_plan(rows: list[dict[str, Any]], signal: dict[str, Any], horizon: datetime) -> dict[str, Any]:
    cutoff = datetime.fromisoformat(signal["cutoff_utc"])
    entry = _floor_cent(signal["price"] + 0.5)
    swing = _window(rows, cutoff, 180)
    swing_low = min(row["low"] for row in swing)
    stop = _floor_cent(min(entry * (1.0 - 0.002), swing_low))
    risk = entry - stop
    tp1 = _floor_cent(entry + risk)
    tp2 = _floor_cent(entry + 2.0 * risk)
    forward = [row for row in rows if cutoff <= row["ts"] <= horizon]
    high = max(row["high"] for row in forward)
    low = min(row["low"] for row in forward)
    trail = _simulate_minute_trail(rows, cutoff, horizon, tp2, entry, risk)
    if trail.get("third_leg_r") is not None:
        trail["unweighted_leg_r_sum"] = 1.0 + 2.0 + trail["third_leg_r"]
        trail["equal_thirds_position_r"] = trail["unweighted_leg_r_sum"] / 3.0
        average_exit = (tp1 + tp2 + trail["exit_stop"]) / 3.0
        trail["equal_thirds_average_exit"] = average_exit
        trail["gross_return_pct"] = (average_exit / entry - 1.0) * 100.0
        trail["fixed_notional_gross_pnl_usdc_3000"] = 3000.0 * (average_exit / entry - 1.0)
    return {
        "planned_entry_usdt": entry,
        "planned_stop_usdt": stop,
        "initial_risk_usdt": risk,
        "planned_tp1_usdt": tp1,
        "planned_tp2_usdt": tp2,
        "first_tp1_ts_utc": _first_hit(forward, cutoff, tp1, "up"),
        "first_tp2_ts_utc": _first_hit(forward, cutoff, tp2, "up"),
        "first_initial_stop_ts_utc": _first_hit(forward, cutoff, stop, "down"),
        "mfe_price_to_horizon": high,
        "mae_price_to_horizon": low,
        "mfe_r_to_horizon": (high - entry) / risk,
        "mae_r_to_horizon": (low - entry) / risk,
        "r_at_active_trade_final_trail": (69110.0 - entry) / risk,
        "entry_improvement_vs_active_usd": 64943.67 - entry,
        "entry_improvement_vs_active_pct": (64943.67 - entry) / 64943.67 * 100.0,
        "minute_trail_simulation": trail,
    }


def build() -> dict[str, Any]:
    rows = _load_rows()
    horizon = datetime.fromisoformat("2026-08-20 03:05:00")
    results = []
    for source in SIGNALS:
        signal = dict(source)
        cutoff = datetime.fromisoformat(signal["cutoff_utc"])
        signal["vwap_extension_pct"] = (signal["price"] / signal["vwap"] - 1.0) * 100.0
        signal["poc_extension_pct"] = (signal["price"] / signal["poc"] - 1.0) * 100.0
        signal["event_delta_pct"] = signal["event_delta"] / signal["event_volume"]
        signal["windows"] = {
            f"{minutes}m": _window_metrics(rows, cutoff, minutes)
            for minutes in (15, 60, 240)
        }
        window_240 = signal["windows"]["240m"]
        window_15 = signal["windows"]["15m"]
        window_60 = signal["windows"]["60m"]
        oi_abs = abs(window_240["oi_change"])
        signal["delta_to_abs_oi_240m"] = window_240["directional_delta"] / oi_abs if oi_abs else None
        signal["flow_concentration_15_240"] = (
            window_15["directional_delta"] / abs(window_240["directional_delta"])
            if window_240["directional_delta"]
            else None
        )
        signal["flow_concentration_60_240"] = (
            window_60["directional_delta"] / abs(window_240["directional_delta"])
            if window_240["directional_delta"]
            else None
        )
        signal["delta_efficiency_acceleration_15_240"] = (
            window_15["delta_pct"] / abs(window_240["delta_pct"])
            if window_240["delta_pct"]
            else None
        )
        if signal["name"].startswith("blocked_"):
            signal["hypothetical_plan"] = _blocked_plan(rows, signal, horizon)
            signal["hypothetical_plan"]["entry_improvement_r"] = (
                signal["hypothetical_plan"]["entry_improvement_vs_active_usd"]
                / signal["hypothetical_plan"]["initial_risk_usdt"]
            )
        else:
            average_exit = (signal["tp1"] + signal["tp2"] + signal["final_trail"]) / 3.0
            signal["actual_position"] = {
                "equal_thirds_average_exit": average_exit,
                "gross_return_pct": (average_exit / signal["actual_entry"] - 1.0) * 100.0,
                "fixed_notional_gross_pnl_usdc_3000": 3000.0
                * (average_exit / signal["actual_entry"] - 1.0),
                "actual_exchange_fill_gross_pnl_usdc": signal["actual_gross_pnl_usdc"],
            }
        results.append(signal)

    payload = {
        "schema_version": "blocked_signal_comparison_v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "feature_boundary": "All signal features use UTC feed rows at or before the normalized cutoff.",
        "forward_horizon_utc": horizon.isoformat(sep=" "),
        "results": results,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Blocked LONG signal comparison — 2026-08-19",
        "",
        "All pre-signal features use normalized UTC cutoffs. Forward MFE/MAE is explicitly hypothetical and is not supplied to the LLM.",
        "",
        "| Signal | Price | Event Δ | Event Δ/vol | VWAP ext | OI Δ60 | OI Δ240 | Flow Δ60 | Flow Δ240 | Δ240/|OI240| |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        w60 = row["windows"]["60m"]
        w240 = row["windows"]["240m"]
        lines.append(
            f"| {row['signal_local']} | {row['price']:.2f} | {row['event_delta']:.2f} | {row['event_delta_pct']:.3f} | "
            f"{row['vwap_extension_pct']:.3f}% | {w60['oi_change']:.2f} | {w240['oi_change']:.2f} | "
            f"{w60['directional_delta']:.2f} | {w240['directional_delta']:.2f} | {row['delta_to_abs_oi_240m']:.3f} |"
        )
    lines.extend([
        "",
        "## Flow acceleration coefficients",
        "",
        "| Signal | Δ15/|Δ240| | Δ60/|Δ240| | (Δ/vol)15 /(Δ/vol)240 | Entry improvement R |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in results:
        plan = row.get("hypothetical_plan") or {}
        lines.append(
            f"| {row['signal_local']} | {row['flow_concentration_15_240']:.3f} | "
            f"{row['flow_concentration_60_240']:.3f} | {row['delta_efficiency_acceleration_15_240']:.3f} | "
            f"{plan.get('entry_improvement_r', 0.0):.3f} |"
        )
    lines.extend([
        "",
        "## Hypothetical executor plans",
        "",
        "| Signal | Entry | Initial SL | Risk | TP1 | TP2 | First TP1 | First TP2 | First initial SL | MFE R | MAE R | Sim trail exit | Sim position R |",
        "|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|",
    ])
    for row in results:
        plan = row.get("hypothetical_plan")
        if not plan:
            continue
        trail = plan["minute_trail_simulation"]
        lines.append(
            f"| {row['signal_local']} | {plan['planned_entry_usdt']:.2f} | {plan['planned_stop_usdt']:.2f} | "
            f"{plan['initial_risk_usdt']:.2f} | {plan['planned_tp1_usdt']:.2f} | {plan['planned_tp2_usdt']:.2f} | "
            f"{plan['first_tp1_ts_utc'] or ''} | {plan['first_tp2_ts_utc'] or ''} | {plan['first_initial_stop_ts_utc'] or ''} | "
            f"{plan['mfe_r_to_horizon']:.2f} | {plan['mae_r_to_horizon']:.2f} | "
            f"{trail.get('exit_stop') or 0.0:.2f} | {trail.get('equal_thirds_position_r') or 0.0:.2f} |"
        )
    lines.extend([
        "",
        "## Actual-dollar comparison at equal 3,000 USDC notional",
        "",
        "This is the correct comparison for the current executor because position notional is approximately fixed; normalized R alone overstates trades whose initial stop is unusually tight.",
        "",
        "| Signal | Status | Equal-thirds average exit | Gross return | Gross PnL at 3,000 USDC | Exchange-fill gross PnL |",
        "|---|---|---:|---:|---:|---:|",
    ])
    for row in results:
        if row.get("actual_position"):
            position = row["actual_position"]
            lines.append(
                f"| {row['signal_local']} | actual | {position['equal_thirds_average_exit']:.2f} | "
                f"{position['gross_return_pct']:.3f}% | {position['fixed_notional_gross_pnl_usdc_3000']:.2f} | "
                f"{position['actual_exchange_fill_gross_pnl_usdc']:.2f} |"
            )
        else:
            trail = row["hypothetical_plan"]["minute_trail_simulation"]
            lines.append(
                f"| {row['signal_local']} | hypothetical | {trail['equal_thirds_average_exit']:.2f} | "
                f"{trail['gross_return_pct']:.3f}% | {trail['fixed_notional_gross_pnl_usdc_3000']:.2f} |  |"
            )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- The protected 2026-08-18 entry was a broad established impulse: 240m directional delta was +3318.03 and delta efficiency was 11.15% of volume.",
        "- The two blocked 2026-08-19 entries were a different archetype: absolute 240m delta was only +444.39 and +598.73, but their last-15m delta exceeded the entire net 240m delta. This is fresh flow acceleration, not broad mature participation.",
        "- Requiring a large absolute 240m delta would therefore retain the earlier protected trade but incorrectly reject both blocked signals that subsequently reached TP1 and TP2 before touching their initial stop.",
        "- Their event VWAP extensions were only 0.172% and 0.296%, versus 1.211% for the protected trade. The LLM's repeated 'late/extended' explanation is not supported by event VWAP extension alone.",
        "- The 14:35 signal had the better risk geometry: lower planned entry, the same 64323.20 swing stop, 293.28 risk versus 375.10, and an entry improvement equal to about 1.12R versus 0.65R at 14:38.",
        "- R and dollar PnL answer different questions here. At equal 3,000 USDC notional the actual 2026-08-18 trade earned about 110.38 USDC gross (110.32 from exchange fills), versus about 71.04 and 73.48 USDC in the two hypothetical reconstructions. The first trade was therefore materially more profitable despite the blocked entries' larger normalized R.",
        "- Candidate features for the full historical audit are `directional_delta_240m`, `flow_concentration_15_240`, `delta_efficiency_acceleration_15_240`, `vwap_extension_pct`, and `entry_improvement_r`. They should remain separate until tested across all loss/protected cohorts.",
        "- The trailing results are a minute-bar reconstruction of the executor's fractal trail, not exchange fills. They estimate about 5.22R and 4.22R for the whole equal-thirds position; use them as comparative evidence, not exact realized PnL.",
    ])
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    built = build()
    print(json.dumps({"output": str(OUTPUT_JSON), "signals": len(built["results"])}, indent=2))
