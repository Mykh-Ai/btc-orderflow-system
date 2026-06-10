from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.hidden_flow_research import (
    HiddenFlowResearchError,
    run_hidden_flow_research,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run SHI_RESET_37A hidden-flow research detection from feed and selected zones."
    )
    parser.add_argument("--start", required=True, help="Inclusive start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Inclusive end date YYYY-MM-DD.")
    parser.add_argument("--feed-dir", required=True, help="Directory containing feed YYYY-MM-DD.csv files.")
    parser.add_argument("--selected-zones", required=True, help="Path to SHI_RESET_36B selected_zones.csv.")
    parser.add_argument(
        "--input-root",
        required=True,
        help="Directory containing accepted daily Market Monitor outputs.",
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for hidden-flow research artifacts.")
    parser.add_argument(
        "--windows",
        default="60,240,720,1440",
        help="Comma-separated detection windows in minutes.",
    )
    parser.add_argument(
        "--future-windows",
        default="60,240,720",
        help="Comma-separated future evaluation windows in minutes.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_hidden_flow_research(
            start=args.start,
            end=args.end,
            feed_dir=Path(args.feed_dir),
            selected_zones_path=Path(args.selected_zones),
            input_root=Path(args.input_root),
            output_dir=Path(args.out_dir),
            windows=_parse_csv_ints(args.windows),
            future_windows=_parse_csv_ints(args.future_windows),
        )
    except HiddenFlowResearchError as exc:
        print(f"hidden flow research failed: {exc}", file=sys.stderr)
        return 2

    print(
        "hidden flow research complete: "
        f"windows={result.window_count} "
        f"candidates={result.candidate_count} "
        f"visible_review={result.visible_review_count} "
        f"market_regime_windows={result.windows_path} "
        f"hidden_flow_candidates={result.candidates_path} "
        f"hidden_flow_future_labels={result.future_labels_path} "
        f"summary={result.summary_path} "
        f"manifest={result.manifest_path}"
    )
    return 0


def _parse_csv_ints(text: str) -> list[int]:
    return [int(part.strip()) for part in text.split(",") if part.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
