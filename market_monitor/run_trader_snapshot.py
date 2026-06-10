from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.trader_snapshot_builder import (
    TraderSnapshotBuilderError,
    build_trader_snapshot,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a static research snapshot from SHI_RESET_36B selected_zones.csv."
    )
    parser.add_argument("--start", required=True, help="Inclusive start date YYYY-MM-DD.")
    parser.add_argument("--end", required=True, help="Inclusive end date YYYY-MM-DD.")
    parser.add_argument("--selected-zones", required=True, help="Path to SHI_RESET_36B selected_zones.csv.")
    parser.add_argument(
        "--input-root",
        required=True,
        help="Directory containing accepted daily Market Monitor output directories.",
    )
    parser.add_argument("--feed-dir", required=True, help="Directory containing feed YYYY-MM-DD.csv files.")
    parser.add_argument("--out-dir", required=True, help="Output directory for trader snapshot artifacts.")
    args = parser.parse_args(argv)

    try:
        result = build_trader_snapshot(
            start=args.start,
            end=args.end,
            selected_zones_path=Path(args.selected_zones),
            input_root=Path(args.input_root),
            feed_dir=Path(args.feed_dir),
            output_dir=Path(args.out_dir),
        )
    except TraderSnapshotBuilderError as exc:
        print(f"trader snapshot failed: {exc}", file=sys.stderr)
        return 2

    print(
        "trader snapshot complete: "
        f"html={result.html_path} "
        f"svg={result.svg_path} "
        f"png={result.png_path} "
        f"manifest={result.manifest_path} "
        f"rendered_zones={result.rendered_zones_path} "
        f"state={result.state_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
