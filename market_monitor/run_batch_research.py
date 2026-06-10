from __future__ import annotations

import argparse
import sys
from pathlib import Path

from market_monitor.batch_runner import BatchResearchError, run_batch_research


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Market Monitor batch research.")
    parser.add_argument("--feed-dir", required=True, help="Directory of daily YYYY-MM-DD.csv feed files.")
    parser.add_argument("--output", required=True, help="Batch output directory.")
    parser.add_argument("--start-date", default=None, help="Optional inclusive start date YYYY-MM-DD.")
    parser.add_argument("--end-date", default=None, help="Optional inclusive end date YYYY-MM-DD.")
    parser.add_argument("--max-days", type=int, default=None, help="Optional maximum number of days.")
    parser.add_argument(
        "--include-degraded",
        action="store_true",
        help="Process RECOVERED_DEGRADED daily feeds instead of skipping them.",
    )
    parser.add_argument(
        "--skip-missing",
        action="store_true",
        help="Skip missing days inside an explicit date range instead of failing.",
    )
    parser.add_argument(
        "--fail-fast",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Stop on the first failed day. Default: true.",
    )
    parser.add_argument(
        "--run-timestamp",
        default=None,
        help="Deterministic timestamp override for reproducible runs.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_batch_research(
            feed_dir=Path(args.feed_dir),
            output_dir=Path(args.output),
            start_date=args.start_date,
            end_date=args.end_date,
            max_days=args.max_days,
            include_degraded=args.include_degraded,
            run_timestamp=args.run_timestamp,
            skip_missing=args.skip_missing,
            fail_fast=args.fail_fast,
        )
    except BatchResearchError as exc:
        print(f"batch research failed: {exc}", file=sys.stderr)
        return 2

    print(
        "batch research complete: "
        f"processed={result.processed_days} "
        f"skipped={result.skipped_days} "
        f"failed={result.failed_days} "
        f"unresolved_sweeps={result.unresolved_sweep_count} "
        f"post_sweep_observations={result.post_sweep_observation_count} "
        f"output={result.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
