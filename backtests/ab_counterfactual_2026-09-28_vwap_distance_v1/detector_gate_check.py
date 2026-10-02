import csv
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
FEED = ROOT / "historical_legacy_feed.csv"
OUT = ROOT / "detector_gate_results.json"

CASES = [
    {
        "candidate_utc": "2026-09-28T05:39:00Z",
        "candidate_feed_time": "2026-09-28 07:39:00",
        "vwap": 84319.0,
        "previous_peak_feed_time": "2026-09-28 07:03:00",
        "previous_peak_abs_delta": 67.84401,
        "previous_peak_price": 83437.565625,
        "previous_peak_volume": 72.68,
        "previous_peak_vwap": 84409.0,
    },
    {
        "candidate_utc": "2026-09-28T09:21:00Z",
        "candidate_feed_time": "2026-09-28 11:21:00",
        "vwap": 83899.0,
        "previous_peak_feed_time": "2026-09-28 10:50:00",
        "previous_peak_abs_delta": 39.81493,
        "previous_peak_price": 82933.199295,
        "previous_peak_volume": 47.45,
        "previous_peak_vwap": 83988.0,
    },
]

CHOP30_MAX = 3.0
COH10_MIN = 0.30
IMB_MIN = 0.54
IMB_MAX = 0.69


def main():
    df = pd.read_csv(FEED)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.floor("min")
    for col in ["AvgPrice", "ClosePrice", "BuyQty", "SellQty"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("Timestamp").drop_duplicates("Timestamp", keep="last").reset_index(drop=True)
    df["price"] = df["ClosePrice"].where(df["ClosePrice"].notna(), df["AvgPrice"])
    df["vol1m"] = df["BuyQty"] + df["SellQty"]
    df["delta"] = df["BuyQty"] - df["SellQty"]
    df["ema50"] = df["price"].ewm(span=50, adjust=False).mean()

    results = []
    for case in CASES:
        ts = pd.Timestamp(case["candidate_feed_time"])
        matches = df.index[df["Timestamp"] == ts].tolist()
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one row for {ts}, got {len(matches)}")
        i = matches[0]
        row = df.iloc[i]

        p30 = df["price"].iloc[i - 29 : i + 1]
        price_range = float(p30.max() - p30.min())
        chop = float(p30.diff().abs().sum() / price_range) if price_range > 0 else None

        w10 = df.iloc[i - 9 : i + 1]
        sum_volume = float(w10["vol1m"].sum())
        sum_delta = float(w10["delta"].sum())
        coh = abs(sum_delta) / sum_volume if sum_volume > 0 else None

        price = float(row["price"])
        avg_price = float(row["AvgPrice"])
        volume = float(row["vol1m"])
        delta = float(row["delta"])
        imbalance = abs(delta) / volume
        vwap = case["vwap"]
        ema = float(row["ema50"])

        gates = {
            "short_regime_price_below_ema50": price < ema,
            "short_regime_price_below_vwap": price < vwap,
            "chop30": chop <= CHOP30_MAX,
            "coh10": coh >= COH10_MIN,
            "imbalance_band": IMB_MIN <= imbalance <= IMB_MAX,
        }
        comparison = {
            "delta_abs_increased": abs(delta) > case["previous_peak_abs_delta"],
            "volume_increased": volume > case["previous_peak_volume"],
            "price_lower": avg_price < case["previous_peak_price"],
            "vwap_lower": vwap < case["previous_peak_vwap"],
        }
        results.append(
            {
                **case,
                "feed_row_index": int(i),
                "price_close_used_by_detector": price,
                "avg_price_used_in_candidate_comparison": avg_price,
                "buy_volume": float(row["BuyQty"]),
                "sell_volume": float(row["SellQty"]),
                "volume": volume,
                "delta": delta,
                "imbalance": imbalance,
                "ema50": ema,
                "vwap_distance_from_avg_price": abs(avg_price - vwap),
                "chop30": chop,
                "chop30_price_range": price_range,
                "coh10": coh,
                "coh10_sum_delta": sum_delta,
                "coh10_sum_volume": sum_volume,
                "thresholds": {
                    "CHOP30_MAX": CHOP30_MAX,
                    "COH10_MIN": COH10_MIN,
                    "IMB_MIN": IMB_MIN,
                    "IMB_MAX": IMB_MAX,
                },
                "gates": gates,
                "all_post_comparison_detector_gates_pass": all(gates.values()),
                "candidate_comparison_non_delta_checks": comparison,
            }
        )

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
