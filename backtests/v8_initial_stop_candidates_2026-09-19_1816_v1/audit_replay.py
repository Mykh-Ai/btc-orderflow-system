"""Read-only reconstruction of the 2026-09-19 20:16 local V8 stop window.

Outputs stay in this audit directory. No production path is written.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from executor_mod import entry_math, market_data


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
SIGNAL_MINUTE = "2026-09-19 20:16:00"  # legacy feed local naive label
SIDE = "SELL"
ENTRY_USDT = 81306.58  # durable src_evt.entry_usdt
LOOKBACK = 1440
LR = 25
CAP = 1200.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    archives = [SOURCE / "2026-09-18.csv", SOURCE / "2026-09-19.csv"]
    current = SOURCE / "aggregated_current.csv"
    by_time: dict[str, dict[str, str]] = {}
    for path in archives:
        for row in raw_rows(path):
            timestamp = row["Timestamp"]
            if timestamp in by_time and by_time[timestamp] != row:
                raise AssertionError(f"archive conflict at {timestamp}")
            by_time[timestamp] = row

    current_by_time = {row["Timestamp"]: row for row in raw_rows(current)}
    overlap = sorted(set(by_time) & set(current_by_time))
    overlap_mismatches = [timestamp for timestamp in overlap if by_time[timestamp] != current_by_time[timestamp]]

    merged = ROOT / "historical_archive_input.csv"
    with merged.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(next(iter(by_time.values()))))
        writer.writeheader()
        writer.writerows(by_time[timestamp] for timestamp in sorted(by_time))

    env = {
        "AGG_CSV": str(merged),
        "INITIAL_STOP_POLICY": "VOLUME_SWING_24H_LR25",
        "INITIAL_SWING_LOOKBACK": LOOKBACK,
        "INITIAL_SWING_LR": LR,
        "INITIAL_SWING_BUFFER_USD": 50.0,
        "INITIAL_SWING_MAX_DISTANCE_USD": CAP,
        "INITIAL_SWING_REQUIRE_FULL_WINDOW": True,
        "SL_PCT": 0.002,
        "TICK_SIZE": Decimal("0.01"),
    }
    market_data.configure(env)
    entry_math.configure(env)
    df = market_data.load_df_sorted()
    signal_index = market_data.locate_index_by_ts(df, pd.Timestamp(SIGNAL_MINUTE))
    if signal_index < 0:
        raise AssertionError("exact signal minute absent")
    window = df.iloc[signal_index + 1 - LOOKBACK : signal_index + 1].copy().reset_index(drop=True)
    if len(window) != LOOKBACK:
        raise AssertionError(f"historical window has {len(window)} rows")

    true_count = int(window["swing_row_real"].sum())
    window_times = pd.to_datetime(window["Timestamp"], utc=True)
    deltas = window_times.diff().dt.total_seconds()
    gap_indices = list(deltas.index[(deltas.notna()) & (deltas != 60)])
    gap_count = len(gap_indices)
    gap_details = [
        {
            "previous_feed_timestamp": pd.Timestamp(window.iloc[i - 1]["Timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            "feed_timestamp": pd.Timestamp(window.iloc[i]["Timestamp"]).strftime("%Y-%m-%d %H:%M:%S"),
            "delta_seconds": float(deltas.iloc[i]),
        }
        for i in gap_indices
    ]
    pct_stop = float(Decimal(str(ENTRY_USDT)) * (1 + Decimal(str(env["SL_PCT"]))))
    ledger = []
    for i, row in window.iterrows():
        timestamp = pd.Timestamp(row["Timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        timestamp_utc = pd.Timestamp(row["Timestamp"]).to_pydatetime().replace(tzinfo=ZoneInfo("Europe/Bratislava")).astimezone(ZoneInfo("UTC")).isoformat()
        swing_price = float(row["high_usdt"])
        record = {
            "timestamp": timestamp,
            "timestamp_utc": timestamp_utc,
            "TotalQty": float(row["TotalQty"]),
            "Trades": float(row["Trades"]),
            "LowPrice": float(row["LowPrice"]),
            "HighPrice": float(row["HiPrice"]),
            "swing_row_real": bool(row["swing_row_real"]),
            "side": SIDE,
            "is_25_25_swing": False,
            "confirmed": False,
            "candidate": False,
            "eligible": False,
            "rejection_reason": "",
            "neighbor_extremum_price": "",
            "neighbor_extremum_timestamp": "",
            "all_51_real": "",
            "swing_price_usdt": swing_price,
            "swing_distance_usd": swing_price - ENTRY_USDT,
            "buffered_structural_stop_usdt": "",
            "pct_stop_usdt": pct_stop,
            "calculated_stop_usdt": "",
            "distance_usd": "",
        }
        if i < LR or i >= len(window) - LR:
            record["rejection_reason"] = "window_edge_no_25_25_confirmation"
        else:
            neighborhood = window.iloc[i - LR : i + LR + 1]
            neighbors = neighborhood.drop(index=i)
            neighbor_index = int(neighbors["high_usdt"].idxmax())
            record["neighbor_extremum_price"] = float(window.iloc[neighbor_index]["high_usdt"])
            record["neighbor_extremum_timestamp"] = pd.Timestamp(window.iloc[neighbor_index]["Timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            record["all_51_real"] = bool(neighborhood["swing_row_real"].all())
            record["is_25_25_swing"] = all(swing_price > float(value) for value in neighbors["high_usdt"])
            if not record["all_51_real"]:
                record["rejection_reason"] = "invalid_swing_row_real_neighborhood"
            elif swing_price <= ENTRY_USDT:
                record["rejection_reason"] = "swing_not_above_planned_entry"
            elif not record["is_25_25_swing"]:
                reason = "equal_neighboring_high" if record["neighbor_extremum_price"] == swing_price else "higher_neighboring_high"
                record["rejection_reason"] = reason
            else:
                record["confirmed"] = True
                record["candidate"] = True
                buffered = float(Decimal(str(swing_price)) + Decimal("50.0"))
                stop = entry_math._initial_stop_from_swing_usdt(SIDE, ENTRY_USDT, swing_price)
                distance = abs(ENTRY_USDT - stop)
                record["buffered_structural_stop_usdt"] = buffered
                record["calculated_stop_usdt"] = stop
                record["distance_usd"] = distance
                record["eligible"] = distance <= CAP
                record["rejection_reason"] = "" if record["eligible"] else "stop_distance_exceeds_1200_cap"
        ledger.append(record)

    output = ROOT / "all_1440_rows.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)

    confirmed = sorted((record for record in ledger if record["confirmed"]), key=lambda record: (record["TotalQty"], record["timestamp"]), reverse=True)
    eligible = [record for record in confirmed if record["eligible"]]
    selection = entry_math.select_volume_confirmed_initial_stop(df, signal_index, SIDE, ENTRY_USDT)
    selected_time = selection.swing_ts.strftime("%Y-%m-%d %H:%M:%S")
    assert eligible and eligible[0]["timestamp"] == selected_time
    assert eligible[0]["calculated_stop_usdt"] == selection.stop_usdt

    summary = {
        "trade_key": "EX_EN_1789841876",
        "signal_minute_local_naive": SIGNAL_MINUTE,
        "signal_minute_utc": "2026-09-19T18:16:00Z",
        "side": SIDE,
        "planned_entry_usdt": ENTRY_USDT,
        "archive_sha256": {path.name: sha256(path) for path in archives},
        "current_feed_sha256": sha256(current),
        "merged_input_sha256": sha256(merged),
        "full_ledger_sha256": sha256(output),
        "current_archive_overlap_rows": len(overlap),
        "current_archive_overlap_mismatches": len(overlap_mismatches),
        "current_archive_overlap_first_mismatches": overlap_mismatches[:10],
        "window_rows_in_current_feed": sum(record["timestamp"] in current_by_time for record in ledger),
        "loaded_rows": len(df),
        "signal_index": signal_index,
        "window_start": ledger[0]["timestamp"],
        "window_end": ledger[-1]["timestamp"],
        "window_rows": len(ledger),
        "window_gap_count": gap_count,
        "window_gap_details": gap_details,
        "window_duplicate_timestamp_count": int(window_times.duplicated().sum()),
        "swing_row_real_true": true_count,
        "swing_row_real_false": len(ledger) - true_count,
        "confirmed_count": len(confirmed),
        "eligible_count": len(eligible),
        "selected": eligible[0],
        "selection_from_production_function": {
            "timestamp": selected_time,
            "stop_usdt": selection.stop_usdt,
            "swing_price_usdt": selection.swing_price_usdt,
            "swing_volume": selection.swing_volume,
            "eligible_count": selection.eligible_count,
            "confirmed_count": selection.confirmed_count,
            "window_gap_count": selection.window_gap_count,
        },
        "all_confirmed_by_volume": confirmed,
        "top_20_raw_volume": sorted(ledger, key=lambda record: (record["TotalQty"], record["timestamp"]), reverse=True)[:20],
    }
    if len(confirmed) != selection.confirmed_count or len(eligible) != selection.eligible_count or gap_count != selection.window_gap_count:
        raise AssertionError("independent ledger does not match production selector")
    (ROOT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key not in ("all_confirmed_by_volume", "top_20_raw_volume")}, indent=2))


if __name__ == "__main__":
    main()
