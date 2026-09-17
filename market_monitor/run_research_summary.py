from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from market_monitor.research_summary import build_post_sweep_research_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build post-sweep research summary artifacts.")
    parser.add_argument(
        "--input-dir",
        action="append",
        required=True,
        help="Market Monitor run output directory. May be supplied multiple times.",
    )
    parser.add_argument("--output", required=True, help="Output directory for summary artifacts.")
    parser.add_argument(
        "--run-timestamp",
        default=None,
        help="Deterministic timestamp override for reproducible summaries.",
    )
    args = parser.parse_args(argv)

    run_timestamp = args.run_timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        result = build_post_sweep_research_summary(
            [Path(path) for path in args.input_dir],
            Path(args.output),
            run_timestamp=run_timestamp,
        )
    except OSError as exc:
        print(f"research summary failed: {exc}", file=sys.stderr)
        return 2

    print(
        "research summary complete: "
        f"observations={result.observation_count} "
        f"complete={result.complete_count} "
        f"incomplete={result.incomplete_count} "
        f"output={Path(args.output)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
