from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.label_quality import build_label_quality_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Market Monitor label quality report.")
    parser.add_argument(
        "--input-dir",
        action="append",
        required=True,
        help="Daily output dir or batch output dir. May be supplied multiple times.",
    )
    parser.add_argument("--output", required=True, help="Output directory for label quality artifacts.")
    parser.add_argument(
        "--run-timestamp",
        default=None,
        help="Deterministic timestamp override for reproducible reports.",
    )
    args = parser.parse_args(argv)

    try:
        result = build_label_quality_report(
            input_dirs=[Path(path) for path in args.input_dir],
            output_dir=Path(args.output),
            run_timestamp=args.run_timestamp,
        )
    except (OSError, ValueError) as exc:
        print(f"label quality report failed: {exc}", file=sys.stderr)
        return 2

    print(
        "label quality report complete: "
        f"total_market_moves={result.total_market_moves} "
        f"clean_labelable_moves={result.clean_labelable_moves} "
        f"global_verdict={result.global_verdict} "
        f"output={Path(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
