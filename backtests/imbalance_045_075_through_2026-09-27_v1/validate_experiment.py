from __future__ import annotations

import csv
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
EXPECTED = {
    "baseline_054_069_feedfix_v1": (34, 33),
    "lower_045_069_feedfix_v1": (52, 51),
    "upper_054_075_feedfix_v1": (55, 53),
    "combined_045_075_feedfix_v1": (73, 71),
    "long_lower_045_feedfix_v1": (47, 46),
    "long_lower_050_feedfix_v1": (40, 39),
    "short_lower_050_feedfix_v1": (37, 36),
    "baseline_long_only_feedfix_v1": (19, 19),
    "chop_coh_relaxed_long050_short054_feedfix_v2": (60, 59),
}


def rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    checks = []
    for source_name, pattern in (
        ("deltascout", "*.jsonl"),
        ("legacy_feed", "*.csv"),
        ("enriched_feed", "*.csv"),
    ):
        paths = sorted((HERE / "source" / source_name).glob(pattern))
        assert paths
        assert paths[-1].stem == "2026-09-27"
        checks.append({"check": f"{source_name}_cutoff", "status": "PASS", "last": paths[-1].name})

    quality = rows(
        HERE / "source" / "execution_feed" / "btcusdc_spot_1m" / "provenance" / "daily_quality.csv"
    )
    assert len(quality) == 195
    assert sum(int(row["missing_minutes"]) for row in quality) == 0
    assert sum(int(row["duplicate_minutes"]) for row in quality) == 0
    checks.append({"check": "execution_feed_quality", "status": "PASS", "days": 195})

    for name, (candidate_count, trade_count) in EXPECTED.items():
        root = HERE / "runs" / name
        assert (root / "run_manifest.json").exists()
        assert len(rows(root / "normalized_candidates.csv")) == candidate_count
        assert len(rows(root / "independent_trades.csv")) == trade_count
        assert len(rows(root / "portfolio_trades.csv")) == trade_count
        assert rows(root / "candidate_quality.csv") == []
        sensitivity = rows(root / "same_bar_sensitivity.csv")
        assert all(row["outcome_changes"].lower() == "false" for row in sensitivity)
        checks.append(
            {
                "check": name,
                "status": "PASS",
                "candidates_after_ab": candidate_count,
                "evaluable_trades": trade_count,
            }
        )

    output = {"status": "PASS", "checks": checks}
    (HERE / "validation.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
