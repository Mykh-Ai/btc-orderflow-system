from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
BASE = RUNS / "long_lower_050_feedfix_v1"
VARIANT = RUNS / "chop_coh_relaxed_long050_short054_feedfix_v2"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    return float(row.get(key) or 0.0)


def summarize(rows: list[dict[str, str]]) -> dict:
    filled = [row for row in rows if row["entry_status"] == "FILLED"]
    return {
        "candidates": len(rows),
        "filled": len(filled),
        "blocked": sum(row["entry_status"] == "BLOCKED" for row in rows),
        "not_filled": sum(row["entry_status"] not in {"FILLED", "BLOCKED"} for row in rows),
        "positive_fills": sum(number(row, "net_pnl_usdc") > 0 for row in filled),
        "negative_fills": sum(number(row, "net_pnl_usdc") < 0 for row in filled),
        "plain_sl": sum(row["lifecycle_class"] == "PLAIN_SL" for row in filled),
        "tp1": sum(bool(row["tp1_fill_ts"]) for row in filled),
        "tp2": sum(bool(row["tp2_fill_ts"]) for row in filled),
        "net_pnl_usdc": sum(number(row, "net_pnl_usdc") for row in rows),
        "lifecycle_counts": dict(sorted(Counter(row["lifecycle_class"] for row in rows).items())),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    base_portfolio = {row["candidate_id"]: row for row in read_csv(BASE / "portfolio_trades.csv")}
    variant_candidates = {
        row["candidate_id"]: row for row in read_csv(VARIANT / "normalized_candidates.csv")
    }
    variant_portfolio = {
        row["candidate_id"]: row for row in read_csv(VARIANT / "portfolio_trades.csv")
    }
    variant_independent = {
        row["candidate_id"]: row for row in read_csv(VARIANT / "independent_trades.csv")
    }
    ab_rows = {
        (row["signal_ts_utc"], row["side"]): row for row in read_csv(HERE / "chop_coh_ab_results.csv")
    }

    added_ids = sorted(set(variant_portfolio) - set(base_portfolio))
    added_portfolio = []
    added_independent = []
    for candidate_id in added_ids:
        candidate = variant_candidates[candidate_id]
        key = (candidate["signal_ts_utc"], candidate["side"])
        ab = ab_rows[key]
        for source, destination in (
            (variant_portfolio[candidate_id], added_portfolio),
            (variant_independent[candidate_id], added_independent),
        ):
            destination.append(
                {
                    **source,
                    "_imbalance": candidate["imbalance"],
                    "_chop30": ab["chop30"],
                    "_coh10": ab["coh10"],
                    "_failure_component": ab["failure_component"],
                    "_ab_decision": ab["decision"],
                }
            )

    changed_common = []
    for candidate_id in sorted(set(base_portfolio) & set(variant_portfolio)):
        old = base_portfolio[candidate_id]
        new = variant_portfolio[candidate_id]
        old_net = number(old, "net_pnl_usdc")
        new_net = number(new, "net_pnl_usdc")
        if old["entry_status"] == new["entry_status"] and abs(old_net - new_net) < 1e-9:
            continue
        changed_common.append(
            {
                "candidate_id": candidate_id,
                "signal_ts_utc": old["signal_ts_utc"],
                "side": old["side"],
                "baseline_status": old["entry_status"],
                "baseline_lifecycle": old["lifecycle_class"],
                "baseline_net_pnl_usdc": old_net,
                "variant_status": new["entry_status"],
                "variant_lifecycle": new["lifecycle_class"],
                "variant_net_pnl_usdc": new_net,
                "delta_usdc": new_net - old_net,
            }
        )

    base_rows = list(base_portfolio.values())
    variant_rows = list(variant_portfolio.values())
    base_summary = summarize(base_rows)
    variant_summary = summarize(variant_rows)
    base_metrics = read_csv(BASE / "portfolio_metrics.csv")[0]
    variant_metrics = read_csv(VARIANT / "portfolio_metrics.csv")[0]
    base_summary["max_drawdown_usdc"] = number(base_metrics, "max_drawdown_usdc")
    variant_summary["max_drawdown_usdc"] = number(variant_metrics, "max_drawdown_usdc")

    group_metrics = []
    for failure in ("CHOP", "COH", "BOTH"):
        for side in ("LONG", "SHORT"):
            independent_rows = [
                row for row in added_independent
                if row["_failure_component"] == failure and row["side"] == side
            ]
            portfolio_rows = [
                row for row in added_portfolio
                if row["_failure_component"] == failure and row["side"] == side
            ]
            group_metrics.append(
                {
                    "failure_component": failure,
                    "side": side,
                    "independent": summarize(independent_rows),
                    "portfolio": summarize(portfolio_rows),
                }
            )

    direct = summarize(added_portfolio)
    independent = summarize(added_independent)
    displacement = sum(row["delta_usdc"] for row in changed_common)
    result = {
        "baseline_policy": "LONG 0.50-0.69 / SHORT 0.54-0.69 with CHOP/COH enforced",
        "variant_policy": "same bands and A/B, but the combined CHOP/COH gate is bypassed",
        "baseline": base_summary,
        "variant": variant_summary,
        "delta_vs_baseline_usdc": variant_summary["net_pnl_usdc"] - base_summary["net_pnl_usdc"],
        "added_chop_coh_independent": independent,
        "added_chop_coh_portfolio_direct": direct,
        "common_candidate_displacement_usdc": displacement,
        "changed_common_candidates": changed_common,
        "group_metrics": group_metrics,
        "quality": {
            "candidate_quality_rows": len(read_csv(VARIANT / "candidate_quality.csv")),
            "same_bar_changed_outcomes": sum(
                row["outcome_changes"].lower() == "true"
                for row in read_csv(VARIANT / "same_bar_sensitivity.csv")
            ),
            "integrity_exclusions": json.loads(
                (VARIANT / "integrity_exclusions.json").read_text(encoding="utf-8")
            ),
        },
        "authoritative_run": str(VARIANT),
        "superseded_run": str(RUNS / "chop_coh_relaxed_long050_short054_feedfix_v1"),
    }
    (HERE / "chop_coh_backtest_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    compact_added = [
        {
            "candidate_id": row["candidate_id"],
            "signal_ts_utc": row["signal_ts_utc"],
            "side": row["side"],
            "imbalance": row["_imbalance"],
            "chop30": row["_chop30"],
            "coh10": row["_coh10"],
            "failure_component": row["_failure_component"],
            "ab_decision": row["_ab_decision"],
            "entry_status": row["entry_status"],
            "lifecycle_class": row["lifecycle_class"],
            "tp1_reached": bool(row["tp1_fill_ts"]),
            "tp2_reached": bool(row["tp2_fill_ts"]),
            "net_pnl_usdc": row["net_pnl_usdc"],
        }
        for row in added_portfolio
    ]
    write_csv(HERE / "chop_coh_added_portfolio_outcomes.csv", compact_added)
    write_csv(HERE / "chop_coh_displacement_analysis.csv", changed_common)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
