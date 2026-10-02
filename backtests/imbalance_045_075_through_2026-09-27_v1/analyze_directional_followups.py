from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RUN_DIRS = {
    "baseline": "baseline_054_069_feedfix_v1",
    "short_lower_050": "short_lower_050_feedfix_v1",
    "baseline_long_only": "baseline_long_only_feedfix_v1",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    return float(row.get(key) or 0.0)


def load_run(dirname: str) -> dict:
    root = RUNS / dirname
    candidates = read_csv(root / "normalized_candidates.csv")
    return {
        "candidates": {row["candidate_id"]: row for row in candidates},
        "portfolio": {row["candidate_id"]: row for row in read_csv(root / "portfolio_trades.csv")},
        "independent": {row["candidate_id"]: row for row in read_csv(root / "independent_trades.csv")},
        "portfolio_metrics": read_csv(root / "portfolio_metrics.csv")[0],
        "ab_blocked": len(read_csv(root / "candidate_loss_filter_exclusions.csv")),
        "integrity_exclusions": json.loads(
            (root / "integrity_exclusions.json").read_text(encoding="utf-8")
        ),
    }


def summarize(rows: list[dict[str, str]]) -> dict:
    filled = [row for row in rows if row["entry_status"] == "FILLED"]
    return {
        "candidates": len(rows),
        "filled": len(filled),
        "blocked": sum(row["entry_status"] == "BLOCKED" for row in rows),
        "no_fill": sum(row["entry_status"] == "NO_FILL" for row in rows),
        "positive_fills": sum(number(row, "net_pnl_usdc") > 0 for row in filled),
        "negative_fills": sum(number(row, "net_pnl_usdc") < 0 for row in filled),
        "plain_sl": sum(row["lifecycle_class"] == "PLAIN_SL" for row in filled),
        "tp1": sum(bool(row["tp1_fill_ts"]) for row in filled),
        "tp2": sum(bool(row["tp2_fill_ts"]) for row in filled),
        "net_pnl_usdc": sum(number(row, "net_pnl_usdc") for row in rows),
        "lifecycle_counts": dict(sorted(Counter(row["lifecycle_class"] for row in rows).items())),
    }


def run_summary(data: dict) -> dict:
    summary = summarize(list(data["portfolio"].values()))
    summary.update(
        {
            "max_drawdown_usdc": number(data["portfolio_metrics"], "max_drawdown_usdc"),
            "ab_blocked": data["ab_blocked"],
            "integrity_excluded": len(data["integrity_exclusions"]),
        }
    )
    return summary


def changed_common_rows(base: dict, variant: dict) -> list[dict]:
    changed = []
    common = sorted(set(base["portfolio"]) & set(variant["portfolio"]))
    for candidate_id in common:
        old = base["portfolio"][candidate_id]
        new = variant["portfolio"][candidate_id]
        old_net = number(old, "net_pnl_usdc")
        new_net = number(new, "net_pnl_usdc")
        if old["entry_status"] == new["entry_status"] and abs(old_net - new_net) < 1e-9:
            continue
        candidate = base["candidates"][candidate_id]
        changed.append(
            {
                "candidate_id": candidate_id,
                "signal_ts_utc": candidate["signal_ts_utc"],
                "side": candidate["side"],
                "imbalance": float(candidate["imbalance"]),
                "baseline_status": old["entry_status"],
                "baseline_lifecycle": old["lifecycle_class"],
                "baseline_net_pnl_usdc": old_net,
                "variant_status": new["entry_status"],
                "variant_lifecycle": new["lifecycle_class"],
                "variant_net_pnl_usdc": new_net,
                "delta_usdc": new_net - old_net,
            }
        )
    return changed


def main() -> None:
    data = {label: load_run(dirname) for label, dirname in RUN_DIRS.items()}
    baseline = data["baseline"]
    short = data["short_lower_050"]
    long_only = data["baseline_long_only"]

    base_ids = set(baseline["portfolio"])
    short_added_ids = sorted(set(short["portfolio"]) - base_ids)
    short_added_portfolio = [short["portfolio"][candidate_id] for candidate_id in short_added_ids]
    short_added_independent = [short["independent"][candidate_id] for candidate_id in short_added_ids]
    short_changed = changed_common_rows(baseline, short)
    long_changed = changed_common_rows(baseline, long_only)

    baseline_short_fills = []
    for candidate_id, trade in baseline["portfolio"].items():
        if trade["side"] != "SHORT" or trade["entry_status"] != "FILLED":
            continue
        candidate = baseline["candidates"][candidate_id]
        baseline_short_fills.append(
            {
                "candidate_id": candidate_id,
                "signal_ts_utc": candidate["signal_ts_utc"],
                "imbalance": float(candidate["imbalance"]),
                "lifecycle_class": trade["lifecycle_class"],
                "tp1_reached": bool(trade["tp1_fill_ts"]),
                "tp2_reached": bool(trade["tp2_fill_ts"]),
                "net_pnl_usdc": number(trade, "net_pnl_usdc"),
            }
        )
    baseline_short_fills.sort(key=lambda row: (row["imbalance"], row["signal_ts_utc"]))

    def imbalance_group(rows: list[dict]) -> dict:
        values = [row["imbalance"] for row in rows]
        return {
            "count": len(rows),
            "imbalance_min": min(values) if values else None,
            "imbalance_max": max(values) if values else None,
            "imbalance_mean": sum(values) / len(values) if values else None,
            "net_pnl_usdc": sum(row["net_pnl_usdc"] for row in rows),
            "trades": rows,
        }

    baseline_short_plain_sl = [
        row for row in baseline_short_fills if row["lifecycle_class"] == "PLAIN_SL"
    ]
    baseline_short_tp1_plus = [row for row in baseline_short_fills if row["tp1_reached"]]

    results = {
        "runs": {label: run_summary(run) for label, run in data.items()},
        "short_lower_050": {
            "added_candidate_ids": short_added_ids,
            "added_independent": summarize(short_added_independent),
            "added_portfolio": summarize(short_added_portfolio),
            "common_candidate_timeline_delta_usdc": sum(row["delta_usdc"] for row in short_changed),
            "changed_common_candidates": short_changed,
        },
        "baseline_long_only": {
            "removed_short_candidate_ids": sorted(base_ids - set(long_only["portfolio"])),
            "removed_short_baseline_portfolio": summarize(
                [baseline["portfolio"][candidate_id] for candidate_id in sorted(base_ids - set(long_only["portfolio"]))]
            ),
            "common_long_timeline_delta_usdc": sum(row["delta_usdc"] for row in long_changed),
            "changed_common_candidates": long_changed,
        },
        "baseline_short_filled_by_outcome": {
            "all": imbalance_group(baseline_short_fills),
            "plain_sl": imbalance_group(baseline_short_plain_sl),
            "tp1_or_better": imbalance_group(baseline_short_tp1_plus),
        },
    }
    results["runs"]["short_lower_050"]["delta_vs_baseline_usdc"] = (
        results["runs"]["short_lower_050"]["net_pnl_usdc"]
        - results["runs"]["baseline"]["net_pnl_usdc"]
    )
    results["runs"]["baseline_long_only"]["delta_vs_baseline_usdc"] = (
        results["runs"]["baseline_long_only"]["net_pnl_usdc"]
        - results["runs"]["baseline"]["net_pnl_usdc"]
    )
    (HERE / "directional_followups.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    csv_path = HERE / "baseline_short_outcomes_by_imbalance.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(baseline_short_fills[0]))
        writer.writeheader()
        writer.writerows(baseline_short_fills)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
