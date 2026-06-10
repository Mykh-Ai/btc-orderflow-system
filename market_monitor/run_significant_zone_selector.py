from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.significant_zone_selector import (
    SignificantZoneSelectorError,
    run_significant_zone_selector,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select significant Market Monitor zones for future snapshot rendering."
    )
    parser.add_argument("--start", required=True, help="Inclusive start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Inclusive end date YYYY-MM-DD.")
    parser.add_argument(
        "--input-root",
        required=True,
        help="Directory containing accepted daily Market Monitor output directories.",
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for selector artifacts.")
    parser.add_argument(
        "--max-visible-zones",
        type=int,
        default=7,
        help="Maximum visible zones to mark for a future snapshot.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_significant_zone_selector(
            input_root=Path(args.input_root),
            output_dir=Path(args.out_dir),
            start=args.start,
            end=args.end,
            max_visible_zones=args.max_visible_zones,
        )
    except SignificantZoneSelectorError as exc:
        print(f"significant zone selector failed: {exc}", file=sys.stderr)
        return 2

    print(
        "significant zone selector complete: "
        f"candidates={result.total_candidate_count} "
        f"visible={result.visible_zone_count} "
        f"buy_side_visible={result.visible_buy_side_count} "
        f"sell_side_visible={result.visible_sell_side_count} "
        f"selected_zones={result.selected_zones_path} "
        f"summary={result.summary_path} "
        f"manifest={result.manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
