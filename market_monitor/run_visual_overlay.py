from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.visual_overlay import VisualOverlayOptions, build_visual_overlay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Market Monitor visual audit overlays.")
    parser.add_argument("--run-dir", required=True, help="Daily Market Monitor output directory.")
    parser.add_argument("--feed-file", required=True, help="Corresponding feed CSV file.")
    parser.add_argument("--output", required=True, help="Output directory for visual artifacts.")
    parser.add_argument("--market-move-id", default=None, help="Render one market_move_id case.")
    parser.add_argument("--missed-timestamp", default=None, help="Render a missed manual timestamp case.")
    parser.add_argument("--window-hours-before", type=float, default=24.0)
    parser.add_argument("--window-hours-after", type=float, default=24.0)
    parser.add_argument("--timeframe", choices=["M1", "M5", "M15"], default="M1")
    parser.add_argument("--format", choices=["html", "png", "both"], default="html")
    parser.add_argument("--include-low-precision", action="store_true")
    parser.add_argument("--include-consumed", action="store_true")
    parser.add_argument("--include-expired", action="store_true")
    parser.add_argument("--include-secondary", action="store_true")
    parser.add_argument("--focused-price-window-pct", type=float, default=2.0)
    args = parser.parse_args(argv)

    if args.market_move_id and args.missed_timestamp:
        print("visual overlay failed: choose --market-move-id or --missed-timestamp, not both", file=sys.stderr)
        return 2

    try:
        result = build_visual_overlay(
            VisualOverlayOptions(
                run_dir=Path(args.run_dir),
                feed_file=Path(args.feed_file),
                output_dir=Path(args.output),
                market_move_id=args.market_move_id,
                missed_timestamp=args.missed_timestamp,
                window_hours_before=args.window_hours_before,
                window_hours_after=args.window_hours_after,
                timeframe=args.timeframe,
                output_format=args.format,
                include_low_precision=args.include_low_precision,
                include_consumed=args.include_consumed,
                include_expired=args.include_expired,
                include_secondary=args.include_secondary,
                focused_price_window_pct=args.focused_price_window_pct,
            )
        )
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"visual overlay failed: {exc}", file=sys.stderr)
        return 2

    print(
        "visual overlay complete: "
        f"files={len(result.files)} "
        f"manifest={result.manifest_path} "
        f"output={Path(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
