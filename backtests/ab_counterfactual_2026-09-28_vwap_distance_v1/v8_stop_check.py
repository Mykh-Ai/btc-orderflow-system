"""Offline V8 initial-stop check for the two Sep 28 pre-admission rejects."""

from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO))
from executor_mod import entry_math, market_data  # noqa: E402


CANDIDATES = [
    {"feed_timestamp": "2026-09-28 07:39:00", "signal_ts_utc": "2026-09-28T05:39:00Z", "signal_price_usdt": 82818.893068},
    {"feed_timestamp": "2026-09-28 11:21:00", "signal_ts_utc": "2026-09-28T09:21:00Z", "signal_price_usdt": 82889.485481},
]


def main() -> None:
    rows: dict[str, dict[str, str]] = {}
    for path in sorted((ROOT / "source" / "legacy_feed").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows[row["Timestamp"]] = row
    merged = ROOT / "historical_legacy_feed.csv"
    with merged.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(next(iter(rows.values()))))
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))

    env = {
        "AGG_CSV": str(merged),
        "ENTRY_OFFSET_USD": 0.5,
        "INITIAL_STOP_POLICY": "VOLUME_SWING_24H_LR25",
        "INITIAL_SWING_LOOKBACK": 1440,
        "INITIAL_SWING_LR": 25,
        "INITIAL_SWING_BUFFER_USD": 50.0,
        "INITIAL_SWING_MAX_DISTANCE_USD": 1200.0,
        "INITIAL_SWING_REQUIRE_FULL_WINDOW": True,
        "SL_PCT": 0.002,
        "TICK_SIZE": Decimal("0.01"),
    }
    market_data.configure(env)
    entry_math.configure(env)
    df = market_data.load_df_sorted()
    output = []
    for candidate in CANDIDATES:
        signal_ts = pd.Timestamp(candidate["feed_timestamp"])
        index = market_data.locate_index_by_ts(df, signal_ts)
        entry = entry_math.build_entry_price("short", candidate["signal_price_usdt"])
        item = {**candidate, "signal_index": index, "planned_entry_usdt": entry}
        try:
            selection = entry_math.select_volume_confirmed_initial_stop(df, index, "SELL", entry)
            swing_feed_naive = selection.swing_ts.replace(tzinfo=None)
            swing_utc = swing_feed_naive.replace(tzinfo=ZoneInfo("Europe/Bratislava")).astimezone(ZoneInfo("UTC"))
            item.update({
                "selector_result": "SELECTED",
                "swing_ts_feed_local_naive": swing_feed_naive.isoformat(),
                "swing_ts_utc": swing_utc.isoformat(),
                "swing_price_usdt": selection.swing_price_usdt,
                "swing_volume": selection.swing_volume,
                "stop_usdt": selection.stop_usdt,
                "stop_distance_usd": selection.stop_usdt - entry,
                "eligible_count": selection.eligible_count,
                "confirmed_count": selection.confirmed_count,
                "window_gap_count": selection.window_gap_count,
                "would_cancel_for_1200_cap": False,
            })
        except entry_math.InitialStopSelectionError as exc:
            item.update({
                "selector_result": "REJECTED",
                "reason": exc.reason,
                "detail": exc.detail,
                "would_cancel_for_1200_cap": exc.reason == "NO_SWING_WITHIN_INITIAL_STOP_CAP",
            })
        output.append(item)
    path = ROOT / "v8_stop_results.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
