from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
RUN_NAMES = {
    "baseline": "baseline_054_069_feedfix_v1",
    "lower": "lower_045_069_feedfix_v1",
    "upper": "upper_054_075_feedfix_v1",
    "combined": "combined_045_075_feedfix_v1",
    "long_lower": "long_lower_045_feedfix_v1",
    "long_lower_050": "long_lower_050_feedfix_v1",
    "short_lower_050": "short_lower_050_feedfix_v1",
    "baseline_long_only": "baseline_long_only_feedfix_v1",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def f(row: dict[str, str], name: str) -> float:
    return float(row.get(name) or 0.0)


def band(imbalance: float) -> str:
    if 0.54 <= imbalance <= 0.69:
        return "baseline"
    if 0.45 <= imbalance < 0.54:
        return "low_added"
    if 0.69 < imbalance <= 0.75:
        return "high_added"
    return "outside"


def summarize_trades(rows: list[dict[str, str]]) -> dict:
    filled = [row for row in rows if row["entry_status"] == "FILLED"]
    lifecycle = Counter(row["lifecycle_class"] for row in rows)
    return {
        "candidates": len(rows),
        "filled": len(filled),
        "not_filled_or_blocked": len(rows) - len(filled),
        "positive_net_filled": sum(f(row, "net_pnl_usdc") > 0 for row in filled),
        "negative_net_filled": sum(f(row, "net_pnl_usdc") < 0 for row in filled),
        "plain_sl": sum(row["lifecycle_class"] == "PLAIN_SL" for row in filled),
        "tp1_reached": sum(bool(row["tp1_fill_ts"]) for row in filled),
        "tp2_reached": sum(bool(row["tp2_fill_ts"]) for row in filled),
        "net_pnl_usdc": sum(f(row, "net_pnl_usdc") for row in rows),
        "gross_pnl_usdc": sum(f(row, "gross_pnl_usdc") for row in rows),
        "average_net_per_candidate_usdc": (
            sum(f(row, "net_pnl_usdc") for row in rows) / len(rows) if rows else None
        ),
        "average_net_per_fill_usdc": (
            sum(f(row, "net_pnl_usdc") for row in filled) / len(filled) if filled else None
        ),
        "sum_position_r": sum(f(row, "position_r") for row in filled),
        "recovery_overlap_count": sum(row["recovery_overlap"].lower() == "true" for row in rows),
        "same_bar_sensitive_count": sum(
            row["outcome_changes_under_sensitivity"].lower() == "true" for row in rows
        ),
        "lifecycle_counts": dict(sorted(lifecycle.items())),
    }


def main() -> None:
    loaded = {}
    for label, dirname in RUN_NAMES.items():
        root = RUNS / dirname
        candidates = read_csv(root / "normalized_candidates.csv")
        by_id = {row["candidate_id"]: row for row in candidates}
        independent = read_csv(root / "independent_trades.csv")
        portfolio = read_csv(root / "portfolio_trades.csv")
        for rows in (independent, portfolio):
            for row in rows:
                candidate = by_id[row["candidate_id"]]
                row["_imbalance"] = candidate["imbalance"]
                row["_band"] = band(float(candidate["imbalance"]))
        loaded[label] = {
            "root": root,
            "candidates": candidates,
            "independent": independent,
            "portfolio": portfolio,
            "ab_exclusions": read_csv(root / "candidate_loss_filter_exclusions.csv"),
            "integrity_exclusions": json.loads(
                (root / "integrity_exclusions.json").read_text(encoding="utf-8")
            ),
            "portfolio_metrics": read_csv(root / "portfolio_metrics.csv")[0],
        }

    independent_rows = []
    combined = loaded["combined"]["independent"]
    for cohort in ("low_added", "high_added"):
        for side in ("LONG", "SHORT"):
            rows = [r for r in combined if r["_band"] == cohort and r["side"] == side]
            independent_rows.append({"cohort": cohort, "side": side, **summarize_trades(rows)})

    portfolio_variant_rows = []
    baseline_net = sum(f(r, "net_pnl_usdc") for r in loaded["baseline"]["portfolio"])
    for label in (
        "baseline", "lower", "upper", "combined", "long_lower", "long_lower_050",
        "short_lower_050", "baseline_long_only",
    ):
        data = loaded[label]
        summary = summarize_trades(data["portfolio"])
        portfolio_variant_rows.append(
            {
                "variant": label,
                **summary,
                "net_delta_vs_baseline_usdc": summary["net_pnl_usdc"] - baseline_net,
                "position_lock_blocked_count": sum(
                    row["entry_status"] == "BLOCKED" for row in data["portfolio"]
                ),
                "max_drawdown_usdc": float(data["portfolio_metrics"]["max_drawdown_usdc"]),
                "ab_blocked_count": len(data["ab_exclusions"]),
                "integrity_excluded_count": len(data["integrity_exclusions"]),
            }
        )

    incremental_portfolio_rows = []
    for label, cohort in (("lower", "low_added"), ("upper", "high_added")):
        for side in ("LONG", "SHORT"):
            rows = [
                row for row in loaded[label]["portfolio"]
                if row["_band"] == cohort and row["side"] == side
            ]
            incremental_portfolio_rows.append(
                {
                    "variant": label,
                    "cohort": cohort,
                    "side": side,
                    **summarize_trades(rows),
                    "position_lock_blocked_count": sum(
                        row["entry_status"] == "BLOCKED" for row in rows
                    ),
                }
            )

    def flatten(row: dict) -> dict:
        result = dict(row)
        result["lifecycle_counts"] = json.dumps(
            result["lifecycle_counts"], ensure_ascii=False, sort_keys=True
        )
        return result

    for name, rows in (
        ("incremental_independent_metrics.csv", independent_rows),
        ("portfolio_variant_metrics.csv", portfolio_variant_rows),
        ("incremental_portfolio_metrics.csv", incremental_portfolio_rows),
    ):
        path = HERE / name
        flat = [flatten(row) for row in rows]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(flat[0]))
            writer.writeheader()
            writer.writerows(flat)

    archive_counts = Counter()
    for path in sorted((HERE / "source" / "deltascout").glob("*.jsonl")):
        if not ("2026-03-17" <= path.stem <= "2026-09-27"):
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                archive_counts[json.loads(line).get("event")] += 1

    result = {
        "scope": {"date_from": "2026-03-17", "date_to": "2026-09-27"},
        "archive": {
            "delta_min": archive_counts["DELTA_MIN"],
            "delta_max": archive_counts["DELTA_MAX"],
            "delta_total": archive_counts["DELTA_MIN"] + archive_counts["DELTA_MAX"],
            "candidate_gate_reject": archive_counts["CANDIDATE_GATE_REJECT"],
        },
        "candidate_cohorts_before_ab": {
            "baseline": {"total": 56, "long": 32, "short": 24},
            "low_added": {"total": 29, "long": 18, "short": 11},
            "high_added": {"total": 28, "long": 13, "short": 15},
        },
        "incremental_independent": independent_rows,
        "portfolio_variants": portfolio_variant_rows,
        "incremental_portfolio": incremental_portfolio_rows,
        "integrity_exclusions_combined": loaded["combined"]["integrity_exclusions"],
        "superseded_runs": [
            "baseline_054_069",
            "lower_045_069",
            "upper_054_075",
            "combined_045_075",
        ],
        "authoritative_runs": RUN_NAMES,
    }
    (HERE / "results_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
